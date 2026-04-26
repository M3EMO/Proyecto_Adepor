"""
A/B altitud Bolivia + Peru: shadow vs produccion.
Read-only. NO modifica DB ni motor_calculadora.

Compara dos predicciones para cada Liquidado con altitud_local > 1500:
  Lado A (produccion sin altitud):  Poisson(xg_crudo, xg_crudo) + tau Dixon-Coles
  Lado B (shadow con altitud):      Poisson(shadow_xg, shadow_xg) + tau Dixon-Coles

Reporta dos versiones:
  - "puro":     SIN Hallazgo G ni Fix #5 en ambos lados (impacto altitud aislada)
  - "sistema":  CON Hallazgo G y Fix #5 en ambos lados (impacto en sistema actual)

Estratifica por: liga, nivel altitud, visitante_de_altura vs visitante_lowland.
Bootstrap 5000 resamples + CI 95% sobre delta_brier.
Split temporal H1/H2 para validacion cruzada.
"""

from __future__ import annotations
import json
import math
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
import os
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "fondo_quant.db"
OUT_DIR = ROOT / "analisis"

# -- Constantes copiadas de motor_calculadora.py para no depender del import --
RHO_FALLBACK = -0.09
RANGO_POISSON = 10
GAMMA_DEFAULT = 0.59  # gamma_display default si no hay scope en config

# Hallazgo G
N_MIN_HALLAZGO_G = 50
BOOST_G_FRACCION = 0.50

# Fix #5
CALIBRACION_BUCKET_MIN = 0.40
CALIBRACION_BUCKET_MAX = 0.50
CALIBRACION_CORRECCION = 0.042

# Altitud
ALTITUD_NIVELES = [
    (3601, 99999, 0.75, 1.35, "Zona de la Muerte"),
    (3001, 3600, 0.80, 1.25, "Extremo"),
    (2501, 3000, 0.85, 1.15, "Alto"),
    (1501, 2500, 0.90, 1.10, "Medio"),
]

LIGAS_AB = ("Bolivia", "Peru")
BOOTSTRAP_N = 5000
SEED = 20260425


def nivel_altitud(altitud: float) -> str:
    if altitud <= 1500:
        return "Sin Altitud"
    for alt_min, alt_max, _, _, nivel in ALTITUD_NIVELES:
        if alt_min <= altitud <= alt_max:
            return nivel
    return "Sin Altitud"


def poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 0.0
    try:
        return (math.exp(-lam) * (lam ** k)) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


def tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    if i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    if i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    if i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def calcular_probs(xg_l: float, xg_v: float, rho: float) -> tuple[float, float, float]:
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v)
            pb *= tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    s = p1 + px + p2
    if s > 0:
        return p1 / s, px / s, p2 / s
    return 0.0, 0.0, 0.0


def aplicar_hallazgo_g(p1: float, px: float, p2: float, freq_local: float) -> tuple[float, float, float]:
    gap = freq_local - p1
    if gap < 0.01:
        return p1, px, p2
    boost = gap * BOOST_G_FRACCION
    p1_new = min(p1 + boost, 0.95)
    delta = p1_new - p1
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    peso_p2 = 1.0 - peso_px
    px_new = max(0.01, px - delta * peso_px)
    p2_new = max(0.01, p2 - delta * peso_p2)
    total = p1_new + px_new + p2_new
    return p1_new / total, px_new / total, p2_new / total


def aplicar_fix5(p1: float, px: float, p2: float) -> tuple[float, float, float]:
    p1_cal, p2_cal = p1, p2
    if CALIBRACION_BUCKET_MIN <= p1 < CALIBRACION_BUCKET_MAX:
        p1_cal = p1 + CALIBRACION_CORRECCION
    if CALIBRACION_BUCKET_MIN <= p2 < CALIBRACION_BUCKET_MAX:
        p2_cal = p2 + CALIBRACION_CORRECCION
    if p1_cal == p1 and p2_cal == p2:
        return p1, px, p2
    total = p1_cal + px + p2_cal
    if total <= 0:
        return p1, px, p2
    return p1_cal / total, px / total, p2_cal / total


def brier_1x2(p1: float, px: float, p2: float, gl: int, gv: int) -> float:
    """Brier score multiclass para 1X2. Promedio de (p_i - y_i)^2 sobre las 3 clases."""
    y1 = 1 if gl > gv else 0
    yx = 1 if gl == gv else 0
    y2 = 1 if gl < gv else 0
    return ((p1 - y1) ** 2 + (px - yx) ** 2 + (p2 - y2) ** 2) / 3.0


def hit(p1: float, px: float, p2: float, gl: int, gv: int) -> int:
    """1 si argmax(probs) coincide con resultado real."""
    pred = max((p1, "L"), (px, "X"), (p2, "V"))[1]
    if gl > gv:
        actual = "L"
    elif gl < gv:
        actual = "V"
    else:
        actual = "X"
    return 1 if pred == actual else 0


def bootstrap_ci(deltas: list[float], n_resamples: int = BOOTSTRAP_N, alpha: float = 0.05) -> tuple[float, float, float]:
    """Bootstrap CI 95% de la media de deltas."""
    if not deltas:
        return 0.0, 0.0, 0.0
    rng = random.Random(SEED)
    n = len(deltas)
    means = []
    for _ in range(n_resamples):
        sample = [deltas[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(alpha / 2 * n_resamples)]
    hi = means[int((1 - alpha / 2) * n_resamples)]
    return mean(deltas), lo, hi


def cargar_gamma_por_liga(cursor) -> dict[str, float]:
    """gamma_1x2 por liga si esta en config, sino default 0.59."""
    out = {}
    cursor.execute("SELECT clave, valor FROM configuracion WHERE clave LIKE 'gamma_1x2%'")
    for clave, valor in cursor.fetchall():
        try:
            v = float(valor)
        except (TypeError, ValueError):
            continue
        if clave == "gamma_1x2":
            out["__default__"] = v
        elif clave.startswith("gamma_1x2."):
            out[clave.split(".", 1)[1]] = v
    return out


def cargar_rho_por_liga(cursor) -> dict[str, float]:
    cursor.execute("SELECT liga, rho_calculado FROM ligas_stats")
    return {liga: rho for liga, rho in cursor.fetchall() if rho is not None}


def cargar_freq_local(cursor) -> dict[str, tuple[int, float]]:
    """N + freq_local por liga (para HG)."""
    cursor.execute("""
        SELECT pais, COUNT(*) as n,
               AVG(CASE WHEN goles_l > goles_v THEN 1.0 ELSE 0.0 END) as freq_local
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        GROUP BY pais
    """)
    return {pais: (n, freq) for pais, n, freq in cursor.fetchall()}


def main():
    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    gamma_map = cargar_gamma_por_liga(c)
    rho_map = cargar_rho_por_liga(c)
    freq_local_map = cargar_freq_local(c)

    print(f"[CONFIG] gamma_map: {gamma_map}")
    print(f"[CONFIG] rho Bolivia={rho_map.get('Bolivia')}, Peru={rho_map.get('Peru')}")
    for pais in LIGAS_AB:
        n, fl = freq_local_map.get(pais, (0, 0))
        hg_activo = n >= N_MIN_HALLAZGO_G
        print(f"[CONFIG] {pais}: N_liq={n} freq_local={fl:.3f} HG_activo={hg_activo}")

    # Cargar altitudes (no usamos altitud_visita; solo para clasificar visitante)
    c.execute("SELECT equipo_norm, altitud FROM equipos_altitud")
    altitudes = {r[0]: r[1] for r in c.fetchall()}

    # Query: Liquidados Bolivia/Peru con shadow_xg poblado
    placeholders = ",".join("?" * len(LIGAS_AB))
    c.execute(f"""
        SELECT id_partido, pais, fecha, local, visita,
               xg_local, xg_visita, shadow_xg_local, shadow_xg_visita,
               prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND pais IN ({placeholders})
          AND shadow_xg_local IS NOT NULL
          AND xg_local > 0 AND xg_visita > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha
    """, LIGAS_AB)
    rows = c.fetchall()
    print(f"\n[QUERY] Liquidados Bolivia+Peru con shadow: N={len(rows)}")

    def normalizar_extremo(texto: str) -> str:
        import re, unicodedata
        if not texto:
            return ""
        sin_tildes = ''.join(
            ch for ch in unicodedata.normalize('NFD', str(texto).lower().strip())
            if unicodedata.category(ch) != 'Mn'
        )
        return re.sub(r'[^a-z0-9]', '', sin_tildes)

    # Filtrar a partidos con altitud_local > 1500 (donde shadow != real)
    partidos = []
    for row in rows:
        (id_p, pais, fecha, local, visita,
         xg_l_db, xg_v_db, sh_xg_l, sh_xg_v,
         p1_db, px_db, p2_db, gl, gv) = row
        loc_norm = normalizar_extremo(local)
        vis_norm = normalizar_extremo(visita)
        alt_local = altitudes.get(loc_norm, 0)
        alt_visita = altitudes.get(vis_norm, 0)
        if alt_local <= 1500:
            continue
        partidos.append({
            "id": id_p, "pais": pais, "fecha": fecha,
            "local": local, "visita": visita,
            "xg_l_db": xg_l_db, "xg_v_db": xg_v_db,
            "sh_xg_l": sh_xg_l, "sh_xg_v": sh_xg_v,
            "p1_db": p1_db, "px_db": px_db, "p2_db": p2_db,
            "gl": gl, "gv": gv,
            "altitud_local": alt_local,
            "altitud_visita": alt_visita,
            "nivel": nivel_altitud(alt_local),
            "visitante_altura": "altura" if alt_visita > 1500 else "lowland",
        })
    print(f"[FILTER] Con altitud_local > 1500: N={len(partidos)}")
    # SANITY CHECK: para partidos donde local NO esta en equipos_altitud (altitud=0),
    # shadow_xg_l == xg_l_crudo. Mi Lado A recomputado debe coincidir con prob_1/x/2 de DB
    # (modulo HG y Fix5: las probs de DB tienen ambos aplicados, mi recompute "puro" no).
    # Como Bolivia/Peru tienen N<50 (HG inactivo), unica fuente de divergencia es Fix5.
    # Aceptable epsilon = 0.05 (margen amplio por Fix5 en bucket 40-50%).
    sanity = {"n_total": 0, "n_pass": 0, "n_fail": 0, "fails": []}
    EPS_SANITY = 0.05  # tolerancia para Fix5 + redondeo
    for row in rows:
        (id_p, pais, fecha, local, visita,
         xg_l_db, xg_v_db, sh_xg_l, sh_xg_v,
         p1_db, px_db, p2_db, gl, gv) = row
        loc_norm_s = normalizar_extremo(local)
        alt_local_s = altitudes.get(loc_norm_s, 0)
        if alt_local_s > 1500:
            continue  # solo partidos sin altitud aplicada
        gamma_s = gamma_map.get(pais, gamma_map.get("__default__", GAMMA_DEFAULT))
        rho_s = rho_map.get(pais, RHO_FALLBACK)
        xg_l_crudo_s = xg_l_db / gamma_s
        xg_v_crudo_s = xg_v_db / gamma_s
        # Mi recompute Lado A (sin HG, sin Fix5)
        a_p1_s, a_px_s, a_p2_s = calcular_probs(xg_l_crudo_s, xg_v_crudo_s, rho_s)
        # Lado A debe == probs DB (con tolerancia para Fix5 + HG)
        diff_p1 = abs(a_p1_s - (p1_db or 0))
        diff_px = abs(a_px_s - (px_db or 0))
        diff_p2 = abs(a_p2_s - (p2_db or 0))
        max_diff = max(diff_p1, diff_px, diff_p2)
        sanity["n_total"] += 1
        if max_diff <= EPS_SANITY:
            sanity["n_pass"] += 1
        else:
            sanity["n_fail"] += 1
            sanity["fails"].append({
                "id": id_p, "pais": pais, "fecha": fecha, "local": local, "visita": visita,
                "xg_l_db": xg_l_db, "xg_v_db": xg_v_db, "gamma": gamma_s, "rho": rho_s,
                "p1_db": p1_db, "px_db": px_db, "p2_db": p2_db,
                "a_p1_recompute": a_p1_s, "a_px_recompute": a_px_s, "a_p2_recompute": a_p2_s,
                "max_diff": max_diff,
            })
    pct_pass = (sanity["n_pass"] / sanity["n_total"] * 100) if sanity["n_total"] else 0
    print()
    print(f"[SANITY] Recompute Lado A vs probs DB en partidos SIN altitud (eps={EPS_SANITY}):")
    print(f"  N total = {sanity['n_total']}, N pass = {sanity['n_pass']} ({pct_pass:.1f}%), N fail = {sanity['n_fail']}")
    if sanity["fails"]:
        print(f"  Top 3 fails (mayor diff):")
        for f in sorted(sanity["fails"], key=lambda x: -x["max_diff"])[:3]:
            print(f"    {f['fecha'][:10]} {f['local'][:25]:25s} max_diff={f['max_diff']:.4f} | DB p1={f['p1_db']:.3f} recompute={f['a_p1_recompute']:.3f}")


    # Loop A/B
    resultados = []
    for p in partidos:
        pais = p["pais"]
        gamma = gamma_map.get(pais, gamma_map.get("__default__", GAMMA_DEFAULT))
        rho = rho_map.get(pais, RHO_FALLBACK)
        freq_data = freq_local_map.get(pais, (0, 0))
        hg_activo = freq_data[0] >= N_MIN_HALLAZGO_G
        freq_local = freq_data[1]

        # Recuperar xg_crudo del DB
        xg_l_crudo = p["xg_l_db"] / gamma
        xg_v_crudo = p["xg_v_db"] / gamma

        # Lado A: Poisson sin altitud (xg_crudo)
        a_p1, a_px, a_p2 = calcular_probs(xg_l_crudo, xg_v_crudo, rho)
        # Lado B: Poisson con altitud (shadow_xg)
        b_p1, b_px, b_p2 = calcular_probs(p["sh_xg_l"], p["sh_xg_v"], rho)

        # Brier puro (sin HG ni Fix5)
        brier_a_puro = brier_1x2(a_p1, a_px, a_p2, p["gl"], p["gv"])
        brier_b_puro = brier_1x2(b_p1, b_px, b_p2, p["gl"], p["gv"])
        hit_a_puro = hit(a_p1, a_px, a_p2, p["gl"], p["gv"])
        hit_b_puro = hit(b_p1, b_px, b_p2, p["gl"], p["gv"])

        # Sistema completo (con HG si activo + Fix5)
        a_p1_s, a_px_s, a_p2_s = a_p1, a_px, a_p2
        b_p1_s, b_px_s, b_p2_s = b_p1, b_px, b_p2
        if hg_activo:
            a_p1_s, a_px_s, a_p2_s = aplicar_hallazgo_g(a_p1_s, a_px_s, a_p2_s, freq_local)
            b_p1_s, b_px_s, b_p2_s = aplicar_hallazgo_g(b_p1_s, b_px_s, b_p2_s, freq_local)
        a_p1_s, a_px_s, a_p2_s = aplicar_fix5(a_p1_s, a_px_s, a_p2_s)
        b_p1_s, b_px_s, b_p2_s = aplicar_fix5(b_p1_s, b_px_s, b_p2_s)
        brier_a_sis = brier_1x2(a_p1_s, a_px_s, a_p2_s, p["gl"], p["gv"])
        brier_b_sis = brier_1x2(b_p1_s, b_px_s, b_p2_s, p["gl"], p["gv"])
        hit_a_sis = hit(a_p1_s, a_px_s, a_p2_s, p["gl"], p["gv"])
        hit_b_sis = hit(b_p1_s, b_px_s, b_p2_s, p["gl"], p["gv"])

        resultados.append({
            **p,
            "gamma": gamma, "rho": rho, "hg_activo": hg_activo,
            "xg_l_crudo": xg_l_crudo, "xg_v_crudo": xg_v_crudo,
            "a_p1": a_p1, "a_px": a_px, "a_p2": a_p2,
            "b_p1": b_p1, "b_px": b_px, "b_p2": b_p2,
            "a_p1_sis": a_p1_s, "a_px_sis": a_px_s, "a_p2_sis": a_p2_s,
            "b_p1_sis": b_p1_s, "b_px_sis": b_px_s, "b_p2_sis": b_p2_s,
            "brier_a_puro": brier_a_puro, "brier_b_puro": brier_b_puro,
            "delta_puro": brier_b_puro - brier_a_puro,
            "brier_a_sis": brier_a_sis, "brier_b_sis": brier_b_sis,
            "delta_sis": brier_b_sis - brier_a_sis,
            "hit_a_puro": hit_a_puro, "hit_b_puro": hit_b_puro,
            "hit_a_sis": hit_a_sis, "hit_b_sis": hit_b_sis,
        })

    # Sanity check: si altitud_local <= 1500 hubieramos incluido, shadow == crudo y delta deberia ser ~0.
    # (Filtrado arriba ya excluye. Pero verifico que en ningun partido incluido sucede esto.)
    sanity_violations = [r for r in resultados if abs(r["sh_xg_l"] - r["xg_l_crudo"]) < 1e-6 and abs(r["sh_xg_v"] - r["xg_v_crudo"]) < 1e-6]
    if sanity_violations:
        print(f"[WARN] {len(sanity_violations)} partidos sin diferencia shadow/crudo (deberian estar fuera).")

    # ----- AGREGADOS -----
    def agg(rs: list[dict], key_delta: str, key_hit_a: str, key_hit_b: str, label: str) -> dict:
        if not rs:
            return {"label": label, "n": 0}
        deltas = [r[key_delta] for r in rs]
        mean_delta, ci_lo, ci_hi = bootstrap_ci(deltas)
        return {
            "label": label,
            "n": len(rs),
            "mean_brier_a": mean(r[key_delta.replace("delta", "brier_a")] for r in rs),
            "mean_brier_b": mean(r[key_delta.replace("delta", "brier_b")] for r in rs),
            "mean_delta": mean_delta,
            "ci95_lo": ci_lo,
            "ci95_hi": ci_hi,
            "ci_includes_zero": ci_lo <= 0 <= ci_hi,
            "hit_rate_a": sum(r[key_hit_a] for r in rs) / len(rs),
            "hit_rate_b": sum(r[key_hit_b] for r in rs) / len(rs),
        }

    overall_puro = agg(resultados, "delta_puro", "hit_a_puro", "hit_b_puro", "GLOBAL_puro")
    overall_sis = agg(resultados, "delta_sis", "hit_a_sis", "hit_b_sis", "GLOBAL_sistema")

    # Por liga
    por_liga = {}
    for pais in LIGAS_AB:
        rs = [r for r in resultados if r["pais"] == pais]
        por_liga[pais] = {
            "puro": agg(rs, "delta_puro", "hit_a_puro", "hit_b_puro", f"{pais}_puro"),
            "sistema": agg(rs, "delta_sis", "hit_a_sis", "hit_b_sis", f"{pais}_sistema"),
        }

    # Por nivel altitud
    por_nivel = {}
    for nivel in ["Medio", "Alto", "Extremo", "Zona de la Muerte"]:
        rs = [r for r in resultados if r["nivel"] == nivel]
        por_nivel[nivel] = {
            "puro": agg(rs, "delta_puro", "hit_a_puro", "hit_b_puro", f"{nivel}_puro"),
            "sistema": agg(rs, "delta_sis", "hit_a_sis", "hit_b_sis", f"{nivel}_sistema"),
        }

    # Por visitante (altura vs lowland)
    por_visitante = {}
    for tipo in ["altura", "lowland"]:
        rs = [r for r in resultados if r["visitante_altura"] == tipo]
        por_visitante[tipo] = {
            "puro": agg(rs, "delta_puro", "hit_a_puro", "hit_b_puro", f"vis_{tipo}_puro"),
            "sistema": agg(rs, "delta_sis", "hit_a_sis", "hit_b_sis", f"vis_{tipo}_sistema"),
        }

    # Split temporal H1/H2 (mitad cronologica de los partidos ya ordenados)
    n_total = len(resultados)
    mid = n_total // 2
    h1 = resultados[:mid]
    h2 = resultados[mid:]
    split = {
        "H1": {
            "puro": agg(h1, "delta_puro", "hit_a_puro", "hit_b_puro", "H1_puro"),
            "sistema": agg(h1, "delta_sis", "hit_a_sis", "hit_b_sis", "H1_sistema"),
            "fecha_min": h1[0]["fecha"] if h1 else None,
            "fecha_max": h1[-1]["fecha"] if h1 else None,
        },
        "H2": {
            "puro": agg(h2, "delta_puro", "hit_a_puro", "hit_b_puro", "H2_puro"),
            "sistema": agg(h2, "delta_sis", "hit_a_sis", "hit_b_sis", "H2_sistema"),
            "fecha_min": h2[0]["fecha"] if h2 else None,
            "fecha_max": h2[-1]["fecha"] if h2 else None,
        },
    }

    # ----- IMPRIMIR REPORTE -----
    print("\n" + "=" * 80)
    print("A/B ALTITUD — Bolivia + Peru — Liquidados con altitud_local > 1500")
    print("=" * 80)
    print(f"\nN total = {n_total}")
    print(f"Bolivia: N = {sum(1 for r in resultados if r['pais']=='Bolivia')}")
    print(f"Peru:    N = {sum(1 for r in resultados if r['pais']=='Peru')}")
    print(f"\nNiveles altitud:")
    for nivel in ["Medio", "Alto", "Extremo", "Zona de la Muerte"]:
        n_n = sum(1 for r in resultados if r["nivel"] == nivel)
        print(f"  {nivel:20s}: {n_n}")
    print(f"\nVisitante:")
    for tipo in ["altura", "lowland"]:
        n_t = sum(1 for r in resultados if r["visitante_altura"] == tipo)
        print(f"  {tipo:8s}: {n_t}")

    def print_agg(a: dict):
        if a["n"] == 0:
            print(f"  {a['label']:30s} N=0 (sin datos)")
            return
        sig = "" if a["ci_includes_zero"] else "  *** CI no incluye 0 ***"
        signo_delta = "MEJORA" if a["mean_delta"] < 0 else "EMPEORA"
        print(f"  {a['label']:30s} N={a['n']:3d} | "
              f"Brier A={a['mean_brier_a']:.4f} B={a['mean_brier_b']:.4f} | "
              f"delta={a['mean_delta']:+.5f} CI95=[{a['ci95_lo']:+.5f},{a['ci95_hi']:+.5f}] {signo_delta}{sig}")
        print(f"  {'':30s}     hit_A={a['hit_rate_a']:.3f} hit_B={a['hit_rate_b']:.3f}")

    print("\n--- GLOBAL ---")
    print_agg(overall_puro)
    print_agg(overall_sis)

    print("\n--- POR LIGA ---")
    for pais in LIGAS_AB:
        print_agg(por_liga[pais]["puro"])
        print_agg(por_liga[pais]["sistema"])

    print("\n--- POR NIVEL ALTITUD ---")
    for nivel in ["Medio", "Alto", "Extremo", "Zona de la Muerte"]:
        print_agg(por_nivel[nivel]["puro"])
        print_agg(por_nivel[nivel]["sistema"])

    print("\n--- POR VISITANTE (altura vs lowland) ---")
    for tipo in ["altura", "lowland"]:
        print_agg(por_visitante[tipo]["puro"])
        print_agg(por_visitante[tipo]["sistema"])

    print("\n--- SPLIT TEMPORAL (validacion cruzada) ---")
    print(f"H1: {split['H1']['fecha_min']} -> {split['H1']['fecha_max']}")
    print_agg(split["H1"]["puro"])
    print_agg(split["H1"]["sistema"])
    print(f"H2: {split['H2']['fecha_min']} -> {split['H2']['fecha_max']}")
    print_agg(split["H2"]["puro"])
    print_agg(split["H2"]["sistema"])

    print("\n--- TABLA POR PARTIDO (sistema completo) ---")
    print(f"{'fecha':19s} {'liga':8s} {'nivel':18s} {'vis_loc':8s} | "
          f"{'p1_A':>6s} {'p1_B':>6s} | gl-gv | "
          f"{'br_A':>6s} {'br_B':>6s} {'delta':>8s}")
    for r in resultados:
        print(f"{r['fecha']:19s} {r['pais']:8s} {r['nivel']:18s} {r['visitante_altura']:8s} | "
              f"{r['a_p1_sis']:6.3f} {r['b_p1_sis']:6.3f} | {r['gl']}-{r['gv']:<3d} | "
              f"{r['brier_a_sis']:6.4f} {r['brier_b_sis']:6.4f} {r['delta_sis']:+8.5f}")

    # ----- PERSISTIR JSON -----
    out_path = OUT_DIR / f"altitud_ab_{ts}.json"
    payload = {
        "ts": ts,
        "config": {
            "ligas": list(LIGAS_AB),
            "gamma_map": gamma_map,
            "rho_por_liga": {p: rho_map.get(p) for p in LIGAS_AB},
            "freq_local": {p: freq_local_map.get(p) for p in LIGAS_AB},
            "hg_activo_por_liga": {p: freq_local_map.get(p, (0, 0))[0] >= N_MIN_HALLAZGO_G for p in LIGAS_AB},
            "n_min_hallazgo_g": N_MIN_HALLAZGO_G,
            "altitud_niveles": [list(t) for t in ALTITUD_NIVELES],
            "rango_poisson": RANGO_POISSON,
            "bootstrap_n": BOOTSTRAP_N,
            "seed": SEED,
        },
        "n_total": n_total,
        "global": {"puro": overall_puro, "sistema": overall_sis},
        "por_liga": por_liga,
        "por_nivel": por_nivel,
        "por_visitante": por_visitante,
        "split_temporal": split,
        "sanity_check_recompute_vs_db": sanity,
        "partidos": [
            {k: v for k, v in r.items()
             if not isinstance(v, (set, sqlite3.Row))}
            for r in resultados
        ],
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[OUT] JSON: {out_path}")

    # ----- RECOMENDACION -----
    print("\n" + "=" * 80)
    print("RECOMENDACION FINAL")
    print("=" * 80)
    sis = overall_sis
    if sis["mean_delta"] < 0 and not sis["ci_includes_zero"]:
        rec = "A: ACTIVAR. delta_brier negativo significativo (CI95 excluye 0)."
    elif sis["mean_delta"] < 0 and sis["ci_includes_zero"]:
        rec = "B: NO ACTIVAR (todavia). delta_brier sugiere mejora pero CI95 incluye 0 (no significativo con N actual)."
    elif sis["mean_delta"] > 0 and not sis["ci_includes_zero"]:
        rec = "B: NO ACTIVAR. delta_brier POSITIVO significativo: shadow EMPEORA prediccion."
    else:
        rec = "B: NO ACTIVAR. delta_brier no significativo, sin senial de mejora."
    print(rec)

    # Validacion cruzada H1/H2
    h1_d = split["H1"]["sistema"]["mean_delta"] if split["H1"]["sistema"]["n"] > 0 else 0
    h2_d = split["H2"]["sistema"]["mean_delta"] if split["H2"]["sistema"]["n"] > 0 else 0
    consistente = (h1_d * h2_d > 0)
    print(f"Validacion cruzada H1/H2: H1={h1_d:+.5f} H2={h2_d:+.5f} -> {'CONSISTENTE' if consistente else 'INCONSISTENTE'}")

    print("\nLIMITACIONES:")
    print(f"  - N={n_total} es chico, CI95 amplio. Confiabilidad limitada.")
    print(f"  - Bolivia tiene 6/12 equipos en altitud → muchos partidos altura-vs-altura.")
    print(f"  - shadow_xg fue calculado con multiplicadores ACTUALES de ALTITUD_NIVELES.")
    print(f"  - Si se activa, cualquier ajuste futuro de los multiplicadores invalida este A/B.")

    conn.close()
    return out_path


if __name__ == "__main__":
    sys.exit(main() and 0)

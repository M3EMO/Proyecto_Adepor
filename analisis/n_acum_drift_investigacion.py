"""adepor-0ac: Investigar caida yield con n_acum EMA alto (drift fin-temp?).

Hallazgo Fase 4 base (sobre N=3.117 con n_acum>=5):
  | n_acum_l bucket | N apost | Hit% | Yield% |
  | <10             | 92      | 38.0 | +33.3  |
  | 10-29           | 387     | 38.5 | +5.4   |
  | 30-59           | 392     | 35.7 | -3.8   |
  | >=60            | 210     | 31.4 | -13.7  |

Hipotesis competidoras:
  H1. n_acum es PROXY de momento_temp (cierre de temp): drift = fin-de-temp.
  H2. n_acum es PROXY de overfitting Pinnacle a equipos conocidos.
  H3. Combinacion.

Tests:
  T1. Matriz n_acum_bucket x momento_bin_4 -> yield. Si signal vive solo
      en momento alto, H1 confirma.
  T2. Decomposicion liga por liga: efecto global o concentrado en
      Argentina/Brasil (cierres atipicos)?
  T3. Correlacion n_acum_l x pct_temp. Si correlacion alta, n_acum es
      practicamente proxy de momento.

Logica de pick: identica a Fase 4 (argmax con gap >= 5%, EV >= 3%, K=2.5%).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "n_acum_drift_investigacion.json"


def cargar_oos(con):
    """OOS predicciones con n_acum_l/v y momento del partido."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.pct_temp, p.momento_bin_4, p.momento_octavo,
               (SELECT n_acum FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS n_acum_l,
               (SELECT n_acum FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.visita AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS n_acum_v
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, 0.025))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    """Identica a fase4_score_apostable: argmax con gap>=5%, EV>=3%, K cap 2.5%."""
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05:
        return False, 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0
    if prob * cuota - 1 < 0.03:
        return False, 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0
    if label == outcome:
        return True, stake, stake * (cuota - 1)
    return True, stake, -stake


def n_bucket(n):
    if n is None or n < 0:
        return None
    if n < 10:
        return "<10"
    if n < 30:
        return "10-29"
    if n < 60:
        return "30-59"
    return ">=60"


def momento_bucket_label(b):
    return {0: "Q1_arr", 1: "Q2_ini", 2: "Q3_mit", 3: "Q4_cie"}.get(b, "?")


def yield_metrics(rows):
    """Metrics agregadas: N, n_apost, hit%, yield%, sum_stake, sum_pl."""
    n_apost = 0
    n_gano = 0
    sum_stake = 0.0
    sum_pl = 0.0
    for r in rows:
        ap, stk, prof = evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                      r["psch"], r["pscd"], r["psca"], r["outcome"])
        if ap:
            n_apost += 1
            if prof > 0:
                n_gano += 1
            sum_stake += stk
            sum_pl += prof
    yld = (sum_pl / sum_stake * 100) if sum_stake > 0 else 0.0
    hit = (n_gano / n_apost * 100) if n_apost > 0 else 0.0
    return {
        "n_pred": len(rows),
        "n_apost": n_apost,
        "n_gano": n_gano,
        "hit_pct": round(hit, 2),
        "yield_pct": round(yld, 2),
        "sum_stake": round(sum_stake, 4),
        "sum_pl": round(sum_pl, 4),
    }


def bootstrap_ci_yield(rows, B=1000, seed=42):
    """Bootstrap CI95 sobre yield% del subconjunto."""
    if not rows:
        return None, None
    rng = np.random.default_rng(seed)
    # Construyo lista de (stake, prof) para los apost
    pairs = []
    for r in rows:
        ap, stk, prof = evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                      r["psch"], r["pscd"], r["psca"], r["outcome"])
        if ap:
            pairs.append((stk, prof))
    if len(pairs) < 5:
        return None, None
    n = len(pairs)
    stks = np.array([p[0] for p in pairs])
    profs = np.array([p[1] for p in pairs])
    idx_mat = rng.integers(0, n, size=(B, n))
    yields = []
    for b in range(B):
        idx = idx_mat[b]
        s = stks[idx].sum()
        p = profs[idx].sum()
        if s > 0:
            yields.append(p / s * 100)
    if not yields:
        return None, None
    lo = float(np.percentile(yields, 2.5))
    hi = float(np.percentile(yields, 97.5))
    return round(lo, 2), round(hi, 2)


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS con n_acum + momento_temp...")
    rows = cargar_oos(con)
    print(f"  N total OOS: {len(rows):,}")

    # Filtrar a n_acum_l valido (>=5 para alinear con Fase 4)
    rows_full = [r for r in rows if r.get("n_acum_l") is not None and r["n_acum_l"] >= 5
                 and r.get("momento_bin_4") is not None]
    print(f"  N con n_acum_l>=5 y momento_bin_4 valido: {len(rows_full):,}")
    print()

    payload = {
        "n_total_oos": len(rows),
        "n_filtrado": len(rows_full),
        "logica_pick": "argmax gap>=5%, EV>=3%, K cap 2.5%",
        "tests": {},
    }

    # ==========================================
    # T0. Replica del hallazgo base (sanity check)
    # ==========================================
    print("=== T0. Replica del hallazgo base ===")
    print(f"{'n_acum_bucket':<14} {'N':>6} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    by_n = defaultdict(list)
    for r in rows_full:
        b = n_bucket(r["n_acum_l"])
        if b:
            by_n[b].append(r)
    t0 = {}
    for b in ["<10", "10-29", "30-59", ">=60"]:
        sub = by_n.get(b, [])
        if not sub:
            continue
        m = yield_metrics(sub)
        ci = bootstrap_ci_yield(sub)
        ci_str = f"[{ci[0]:>+5.1f},{ci[1]:>+5.1f}]" if ci[0] is not None else "n/a"
        print(f"{b:<14} {m['n_pred']:>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t0[b] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
    payload["tests"]["T0_replica_base"] = t0
    print()

    # ==========================================
    # T1. Matriz n_acum_bucket x momento_bin_4
    # ==========================================
    print("=== T1. Matriz n_acum x momento_temp ===")
    print(f"{'n_acum':<8} | {'Q1_arr':>20} | {'Q2_ini':>20} | {'Q3_mit':>20} | {'Q4_cie':>20}")
    print("-" * 110)
    matriz = {}
    for nb in ["<10", "10-29", "30-59", ">=60"]:
        row_str = f"{nb:<8} | "
        matriz[nb] = {}
        for mb in [0, 1, 2, 3]:
            sub = [r for r in rows_full if n_bucket(r["n_acum_l"]) == nb and r["momento_bin_4"] == mb]
            if sub:
                m = yield_metrics(sub)
                ci = bootstrap_ci_yield(sub, B=500)
                cell = f"N={m['n_apost']} y={m['yield_pct']:+.1f}%"
                row_str += f"{cell:>20} | "
                matriz[nb][f"Q{mb+1}"] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
            else:
                row_str += f"{'-':>20} | "
                matriz[nb][f"Q{mb+1}"] = None
        print(row_str)
    payload["tests"]["T1_matriz_nacum_x_momento"] = matriz
    print()

    # ==========================================
    # T2. Yield por liga x n_acum_bucket
    # ==========================================
    print("=== T2. Yield por liga x n_acum_bucket ===")
    ligas = sorted(set(r["liga"] for r in rows_full))
    print(f"{'liga':<14} | {'<10':>22} | {'10-29':>22} | {'30-59':>22} | {'>=60':>22}")
    print("-" * 130)
    por_liga = {}
    for liga in ligas:
        por_liga[liga] = {}
        row_str = f"{liga:<14} | "
        for nb in ["<10", "10-29", "30-59", ">=60"]:
            sub = [r for r in rows_full if r["liga"] == liga and n_bucket(r["n_acum_l"]) == nb]
            if len(sub) >= 10:
                m = yield_metrics(sub)
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:+6.1f}%"
                row_str += f"{cell:>22} | "
                por_liga[liga][nb] = m
            else:
                row_str += f"{'-':>22} | "
                por_liga[liga][nb] = None
        print(row_str)
    payload["tests"]["T2_por_liga"] = por_liga
    print()

    # ==========================================
    # T3. Correlacion n_acum_l x pct_temp
    # ==========================================
    print("=== T3. Correlacion n_acum_l x pct_temp ===")
    n_vals = np.array([r["n_acum_l"] for r in rows_full if r["pct_temp"] is not None])
    pct_vals = np.array([r["pct_temp"] for r in rows_full if r["pct_temp"] is not None])
    r_pearson = float(np.corrcoef(n_vals, pct_vals)[0, 1])
    print(f"  Pearson r(n_acum_l, pct_temp) = {r_pearson:+.3f}")
    # Spearman manual = Pearson sobre rangos
    n_ranks = n_vals.argsort().argsort().astype(float)
    pct_ranks = pct_vals.argsort().argsort().astype(float)
    rho_spearman = float(np.corrcoef(n_ranks, pct_ranks)[0, 1])
    # p-value aproximado via Fisher z-transform
    n_sample = len(n_vals)
    if n_sample > 3 and abs(rho_spearman) < 0.999:
        z = 0.5 * np.log((1 + rho_spearman) / (1 - rho_spearman)) * np.sqrt(n_sample - 3)
        # 2-tailed p-value via normal approx
        from math import erfc, sqrt
        p_spearman = erfc(abs(z) / sqrt(2))
    else:
        p_spearman = 0.0
    print(f"  Spearman rho                  = {rho_spearman:+.3f}  (p_aprox={p_spearman:.2e})")
    payload["tests"]["T3_correlacion"] = {
        "pearson_r": round(r_pearson, 4),
        "spearman_rho": round(rho_spearman, 4),
        "spearman_p_aprox": float(p_spearman),
        "n": int(n_sample),
    }
    print()

    # ==========================================
    # T4. Yield por momento_bin_4 (sin filtrar n_acum)
    # ==========================================
    print("=== T4. Yield por momento_bin_4 (control: solo momento) ===")
    print(f"{'momento_bin':<14} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    momento_full = {}
    for mb in [0, 1, 2, 3]:
        sub = [r for r in rows_full if r["momento_bin_4"] == mb]
        if not sub:
            continue
        m = yield_metrics(sub)
        ci = bootstrap_ci_yield(sub)
        ci_str = f"[{ci[0]:>+5.1f},{ci[1]:>+5.1f}]" if ci[0] is not None else "n/a"
        label = momento_bucket_label(mb)
        print(f"{label:<14} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        momento_full[label] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
    payload["tests"]["T4_solo_momento"] = momento_full
    print()

    # ==========================================
    # T5. Decomposicion: comparar variabilidad
    # ==========================================
    print("=== T5. Comparacion de magnitudes ===")
    n_yields = [t0[b]["yield_pct"] for b in ["<10", "10-29", "30-59", ">=60"] if b in t0 and t0[b].get("yield_pct") is not None]
    m_yields = [momento_full[k]["yield_pct"] for k in ["Q1_arr","Q2_ini","Q3_mit","Q4_cie"] if k in momento_full]
    n_range = max(n_yields) - min(n_yields) if n_yields else 0
    m_range = max(m_yields) - min(m_yields) if m_yields else 0
    print(f"  Rango yield por n_acum_bucket : {n_range:.1f}pp")
    print(f"  Rango yield por momento_bin_4 : {m_range:.1f}pp")
    print(f"  Ratio n_acum/momento          : {n_range / m_range:.2f}" if m_range > 0 else "  (momento sin variabilidad)")
    payload["tests"]["T5_comparacion_magnitudes"] = {
        "rango_n_acum_pp": round(n_range, 2),
        "rango_momento_pp": round(m_range, 2),
        "ratio": round(n_range / m_range, 2) if m_range > 0 else None,
    }
    print()

    # ==========================================
    # T6. Filtros operativos propuestos
    # ==========================================
    print("=== T6. Yield con filtros operativos propuestos ===")
    print(f"{'Filtro':<35} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    filtros = {
        "BASELINE (sin filtro)": rows_full,
        "Excluir n_acum_l >=60": [r for r in rows_full if r["n_acum_l"] < 60],
        "Excluir momento Q4 (cierre)": [r for r in rows_full if r["momento_bin_4"] != 3],
        "Excluir (n_acum>=60 OR Q4)": [r for r in rows_full if r["n_acum_l"] < 60 and r["momento_bin_4"] != 3],
        "Excluir (n_acum>=60 AND Q4)": [r for r in rows_full if not (r["n_acum_l"] >= 60 and r["momento_bin_4"] == 3)],
        "Solo n_acum<30 (joven EMA)": [r for r in rows_full if r["n_acum_l"] < 30],
        "Solo momento Q2-Q3 (medio temp)": [r for r in rows_full if r["momento_bin_4"] in (1, 2)],
    }
    t6 = {}
    for nombre, sub in filtros.items():
        if not sub:
            continue
        m = yield_metrics(sub)
        ci = bootstrap_ci_yield(sub, B=1000)
        ci_str = f"[{ci[0]:>+5.1f},{ci[1]:>+5.1f}]" if ci[0] is not None else "n/a"
        print(f"{nombre:<35} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t6[nombre] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
    payload["tests"]["T6_filtros_operativos"] = t6
    print()

    # ==========================================
    # T7. Validacion lado visita (efecto simetrico?)
    # ==========================================
    print("=== T7. Yield por n_acum_v (visita) — control simetria ===")
    rows_v = [r for r in rows_full if r.get("n_acum_v") is not None and r["n_acum_v"] >= 5]
    print(f"  N con n_acum_v>=5: {len(rows_v):,}")
    print(f"{'n_acum_v_bucket':<14} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    by_v = defaultdict(list)
    for r in rows_v:
        b = n_bucket(r["n_acum_v"])
        if b:
            by_v[b].append(r)
    t7 = {}
    for b in ["<10", "10-29", "30-59", ">=60"]:
        sub = by_v.get(b, [])
        if not sub:
            continue
        m = yield_metrics(sub)
        ci = bootstrap_ci_yield(sub, B=500)
        ci_str = f"[{ci[0]:>+5.1f},{ci[1]:>+5.1f}]" if ci[0] is not None else "n/a"
        print(f"{b:<14} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t7[b] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
    payload["tests"]["T7_lado_visita"] = t7
    print()

    # ==========================================
    # T8. Cruce con filtro liga adepor-ptk (TOP-5)
    # ==========================================
    print("=== T8. Cruce con filtro liga adepor-ptk (TOP-5: Arg/Bra/Ing/Nor/Tur) ===")
    # Noruega no esta en OOS. Top-5 efectivo en OOS: Arg/Bra/Ing/Tur
    ligas_top = {"Argentina", "Brasil", "Inglaterra", "Turquia"}
    rows_top = [r for r in rows_full if r["liga"] in ligas_top]
    rows_otras = [r for r in rows_full if r["liga"] not in ligas_top]
    print(f"  N TOP-4 (Arg/Bra/Ing/Tur OOS): {len(rows_top):,}")
    print(f"  N otras (Esp/Ita/Fra/Ale OOS): {len(rows_otras):,}")
    print()
    print(f"{'Subset':<40} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    cruces = {
        "TOP-4 baseline": rows_top,
        "TOP-4 + excluir n_acum>=60": [r for r in rows_top if r["n_acum_l"] < 60],
        "TOP-4 + excluir Q4": [r for r in rows_top if r["momento_bin_4"] != 3],
        "TOP-4 + excluir (n_acum>=60 OR Q4)": [r for r in rows_top if r["n_acum_l"] < 60 and r["momento_bin_4"] != 3],
        "Otras 4 baseline": rows_otras,
        "Otras 4 + excluir (n_acum>=60 OR Q4)": [r for r in rows_otras if r["n_acum_l"] < 60 and r["momento_bin_4"] != 3],
    }
    t8 = {}
    for nombre, sub in cruces.items():
        if not sub:
            continue
        m = yield_metrics(sub)
        ci = bootstrap_ci_yield(sub, B=1000)
        ci_str = f"[{ci[0]:>+5.1f},{ci[1]:>+5.1f}]" if ci[0] is not None else "n/a"
        print(f"{nombre:<40} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t8[nombre] = {**m, "ci95_lo": ci[0], "ci95_hi": ci[1]}
    payload["tests"]["T8_cruce_top4_liga"] = t8
    print()

    # ==========================================
    # CONCLUSION DIAGNOSTICA
    # ==========================================
    print("=== CONCLUSION DIAGNOSTICA ===")
    veredicto = []
    if abs(r_pearson) < 0.20 and abs(rho_spearman) < 0.20:
        veredicto.append(f"H1 (n_acum proxy de momento) DESCARTADA: correlacion "
                          f"baja r={r_pearson:+.2f}/rho={rho_spearman:+.2f}")
    elif abs(r_pearson) > 0.40 or abs(rho_spearman) > 0.40:
        veredicto.append(f"H1 (n_acum proxy de momento) PLAUSIBLE: correlacion "
                          f"alta r={r_pearson:+.2f}/rho={rho_spearman:+.2f}")
    else:
        veredicto.append(f"H1 (n_acum proxy de momento) PARCIAL: correlacion "
                          f"media r={r_pearson:+.2f}/rho={rho_spearman:+.2f}")

    if n_range > 30 and m_range < 15:
        veredicto.append("Senal en n_acum domina sobre momento. H2 (overfit Pinnacle) "
                          "PLAUSIBLE como driver dominante.")
    elif m_range > 30 and n_range < 15:
        veredicto.append("Senal en momento domina sobre n_acum. H1 confirma: drift fin-temp.")
    else:
        veredicto.append("Ambos rangos similares. H3 (combinacion) plausible. "
                          "Ver matriz T1 para concluir.")

    for v in veredicto:
        print(f"  - {v}")
    payload["veredicto"] = veredicto

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

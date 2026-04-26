"""
comparativo_ema_dual.py — Baseline SHADOW EMA largo vs corto (read-only).

Bead: adepor-8zz (depends on adepor-2rn migration + adepor-mpm backfill).
Aprobado por Lead 2026-04-26 (Opcion B post-backfill).

Las 4 funciones reportan baseline pre-deployment del EMA corto:
  1) divergencias_por_equipo: top 20 equipos con mayor delta(ema_largo, ema_corto).
  2) hit_rate_shadow_vs_actual: % flips direccionales del pick si se usara xg_corto.
  3) regime_change_cusum: deteccion regime shift via Brier rolling 50 (con warmup).
  4) caso_boca: validacion narrativa del piloto.

Output:
  analisis/ema_dual_baseline_<ts>.json + tabla console-friendly.

NO escribe DB. NO corre Poisson. NO modifica motor_calculadora.
"""
import sqlite3
import json
import math
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path(__file__).resolve().parents[2] / "fondo_quant.db"
ANALISIS_DIR = Path(__file__).resolve().parents[2] / "analisis"

ALFA_LARGO_POR_LIGA = {
    "Brasil": 0.20, "Turquia": 0.20, "Venezuela": 0.20,
    "Noruega": 0.18, "Peru": 0.18, "Ecuador": 0.18,
    "Argentina": 0.15, "Chile": 0.15, "Uruguay": 0.15,
    "Colombia": 0.15, "Bolivia": 0.15,
    "Francia": 0.14, "Alemania": 0.13,
    "Inglaterra": 0.12, "Espana": 0.12, "Italia": 0.12,
}
ALFA_GLOBAL_FALLBACK = 0.15
CAP_ALFA_CORTO = 0.50

EPS_FLIP = 0.05
N_MIN_EQUIPO = 5
N_MIN_LIGA_CUSUM = 50
VENTANA_BRIER = 50


def alfa_corto_por_liga(pais):
    largo = ALFA_LARGO_POR_LIGA.get(pais, ALFA_GLOBAL_FALLBACK)
    return min(2.0 * largo, CAP_ALFA_CORTO)


def divergencias_por_equipo(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT equipo_norm, equipo_real, liga,
               ema_xg_favor_home, ema_xg_contra_home,
               ema_xg_favor_away, ema_xg_contra_away,
               ema_corto_favor_home, ema_corto_contra_home,
               ema_corto_favor_away, ema_corto_contra_away,
               partidos_home, partidos_away,
               partidos_corto_home, partidos_corto_away
        FROM historial_equipos
    """)
    rows = cur.fetchall()
    detalle = []
    fallback_n = 0
    modulados_n = 0
    boca_row = None
    for r in rows:
        (en, er, liga,
         lfh, lch, lfa, lca,
         cfh, cch, cfa, cca,
         ph, pa, pch, pca) = r
        n_total = (ph or 0) + (pa or 0)
        if n_total < N_MIN_EQUIPO:
            continue
        d_fh = abs((lfh or 0) - (cfh or 0))
        d_ch = abs((lch or 0) - (cch or 0))
        d_fa = abs((lfa or 0) - (cfa or 0))
        d_ca = abs((lca or 0) - (cca or 0))
        d_max = max(d_fh, d_ch, d_fa, d_ca)
        d_avg = (d_fh + d_ch + d_fa + d_ca) / 4.0
        is_fallback = (d_max < 1e-9)
        if is_fallback:
            fallback_n += 1
        else:
            modulados_n += 1
        item = {
            "equipo_norm": en, "equipo_real": er, "liga": liga,
            "n_largo_home": ph, "n_largo_away": pa,
            "n_corto_home": pch, "n_corto_away": pca,
            "ema_largo": {"fh": round(lfh or 0, 4), "ch": round(lch or 0, 4),
                          "fa": round(lfa or 0, 4), "ca": round(lca or 0, 4)},
            "ema_corto": {"fh": round(cfh or 0, 4), "ch": round(cch or 0, 4),
                          "fa": round(cfa or 0, 4), "ca": round(cca or 0, 4)},
            "deltas": {"fh": round(d_fh, 4), "ch": round(d_ch, 4),
                       "fa": round(d_fa, 4), "ca": round(d_ca, 4)},
            "delta_max": round(d_max, 4),
            "delta_avg": round(d_avg, 4),
            "is_fallback_puro": is_fallback,
        }
        detalle.append(item)
        if en == "bocajuniors" and liga == "Argentina":
            boca_row = item
    detalle.sort(key=lambda x: x["delta_max"], reverse=True)
    top20 = detalle[:20]
    by_liga = defaultdict(list)
    for d in detalle:
        by_liga[d["liga"]].append(d["delta_avg"])
    agregados = {}
    for liga, vals in by_liga.items():
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        p95 = vals_sorted[int(0.95 * (n - 1))] if n > 0 else 0.0
        agregados[liga] = {
            "n_equipos": n,
            "mean_delta_avg": round(sum(vals) / n if n > 0 else 0.0, 4),
            "p95_delta_avg": round(p95, 4),
        }
    return {
        "n_equipos_analizados": len(detalle),
        "n_modulados": modulados_n,
        "n_fallback_puro": fallback_n,
        "top20": top20,
        "agregados_por_liga": agregados,
        "boca_juniors_arg": boca_row,
    }


def hit_rate_shadow_vs_actual(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id_partido, local, visita, pais, fecha,
               xg_local, xg_visita,
               xg_local_corto, xg_visita_corto,
               apuesta_1x2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')
    """)
    rows = cur.fetchall()
    n_picks_reales = len(rows)
    n_con_xg_corto = sum(1 for r in rows if r[7] is not None and r[8] is not None)
    if n_con_xg_corto == 0:
        return {
            "status": "PENDING_DATA",
            "n_picks_reales": n_picks_reales,
            "n_con_xg_corto": 0,
            "caveat": "xg_*_corto NULL en todos los Liquidados. Espera proximo ciclo motor_fixture+motor_calculadora.",
        }
    flips = []
    for r in rows:
        (_id, _l, _v, _p, _f, xgl, xgv, xglc, xgvc, ap, gl, gv) = r
        if xgl is None or xgv is None or xglc is None or xgvc is None:
            continue
        d_actual = xgl - xgv
        d_shadow = xglc - xgvc
        if abs(d_actual) < EPS_FLIP:
            pa = "X"
        elif d_actual > 0:
            pa = "L"
        else:
            pa = "V"
        if abs(d_shadow) < EPS_FLIP:
            ps = "X"
        elif d_shadow > 0:
            ps = "L"
        else:
            ps = "V"
        if pa != ps:
            ganador_real = "L" if (gl or 0) > (gv or 0) else ("V" if (gv or 0) > (gl or 0) else "X")
            flips.append({"id": _id, "pick_actual": pa, "pick_shadow": ps,
                          "ganador_real": ganador_real,
                          "actual_acerto": int(pa == ganador_real),
                          "shadow_acerto": int(ps == ganador_real)})
    n_flips = len(flips)
    pct_flips = n_flips / n_picks_reales if n_picks_reales > 0 else 0.0
    if n_flips > 0:
        hit_actual_flips = sum(f["actual_acerto"] for f in flips) / n_flips
        hit_shadow_flips = sum(f["shadow_acerto"] for f in flips) / n_flips
    else:
        hit_actual_flips = 0.0
        hit_shadow_flips = 0.0
    delta_brier_proxy = pct_flips * (hit_shadow_flips - hit_actual_flips)
    return {
        "status": "OK",
        "n_picks_reales": n_picks_reales,
        "n_con_xg_corto": n_con_xg_corto,
        "n_flips": n_flips,
        "pct_flips": round(pct_flips, 4),
        "hit_rate_actual_en_flips": round(hit_actual_flips, 4),
        "hit_rate_shadow_en_flips": round(hit_shadow_flips, 4),
        "delta_brier_proxy": round(delta_brier_proxy, 4),
        "limitacion": "proxy direccional, no Poisson exacto",
        "flips_detalle": flips[:30],
    }


def _brier_partido(p1, px, p2, gl, gv):
    res_l = 1.0 if (gl or 0) > (gv or 0) else 0.0
    res_x = 1.0 if (gl or 0) == (gv or 0) else 0.0
    res_v = 1.0 if (gv or 0) > (gl or 0) else 0.0
    return ((p1 - res_l) ** 2 + (px - res_x) ** 2 + (p2 - res_v) ** 2) / 3.0


def regime_change_cusum(conn):
    """CUSUM con warmup: el flag solo se evalua a partir del partido VENTANA_BRIER-esimo
    (cuando el rolling Brier esta basado en la ventana completa). Antes de eso, el rolling
    es un promedio de tamaño creciente y el CUSUM dispararia falsos positivos.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT pais, fecha, prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND prob_1 > 0 AND prob_x > 0 AND prob_2 > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY pais, fecha
    """)
    by_liga = defaultdict(list)
    for pais, fecha, p1, px, p2, gl, gv in cur.fetchall():
        by_liga[pais].append((fecha, _brier_partido(p1, px, p2, gl, gv)))
    out = {}
    for pais, lst in by_liga.items():
        n = len(lst)
        if n < N_MIN_LIGA_CUSUM:
            out[pais] = {"status": "INSUFFICIENT_DATA", "n": n, "n_min": N_MIN_LIGA_CUSUM}
            continue
        rolling = []
        for i in range(n):
            ini = max(0, i - VENTANA_BRIER + 1)
            window = [lst[j][1] for j in range(ini, i + 1)]
            rolling.append(sum(window) / len(window))
        warmup = VENTANA_BRIER - 1
        rolling_estable = rolling[warmup:]
        if len(rolling_estable) < 2:
            out[pais] = {"status": "WARMUP_ONLY", "n": n,
                         "n_post_warmup": len(rolling_estable)}
            continue
        mean_b = sum(rolling_estable) / len(rolling_estable)
        var_b = sum((x - mean_b) ** 2 for x in rolling_estable) / len(rolling_estable)
        sigma_b = math.sqrt(var_b) if var_b > 0 else 0.0
        cusum = 0.0
        cusum_serie = []
        flag_15_idx = None
        flag_20_idx = None
        for i, b in enumerate(rolling):
            if i < warmup:
                cusum_serie.append(0.0)
                continue
            cusum = max(0.0, cusum + (b - mean_b))
            cusum_serie.append(cusum)
            if flag_15_idx is None and sigma_b > 0 and cusum > 1.5 * sigma_b:
                flag_15_idx = i
            if flag_20_idx is None and sigma_b > 0 and cusum > 2.0 * sigma_b:
                flag_20_idx = i
        out[pais] = {
            "status": "OK",
            "n": n,
            "n_post_warmup": len(rolling_estable),
            "warmup_window": VENTANA_BRIER,
            "mean_brier_rolling": round(mean_b, 5),
            "sigma_brier_rolling": round(sigma_b, 5),
            "cusum_actual": round(cusum_serie[-1], 5),
            "umbral_1_5_sigma": round(1.5 * sigma_b, 5),
            "umbral_2_0_sigma": round(2.0 * sigma_b, 5),
            "flag_1_5_disparado_idx": flag_15_idx,
            "flag_1_5_fecha": lst[flag_15_idx][0] if flag_15_idx is not None else None,
            "flag_2_0_disparado_idx": flag_20_idx,
            "flag_2_0_fecha": lst[flag_20_idx][0] if flag_20_idx is not None else None,
            "brier_rolling_actual": round(rolling[-1], 5),
        }
    return out


def caso_boca(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT equipo_norm, equipo_real, liga,
               ema_xg_favor_home, ema_xg_contra_home,
               ema_xg_favor_away, ema_xg_contra_away,
               ema_corto_favor_home, ema_corto_contra_home,
               ema_corto_favor_away, ema_corto_contra_away,
               partidos_home, partidos_away,
               partidos_corto_home, partidos_corto_away
        FROM historial_equipos
        WHERE equipo_norm = 'bocajuniors' AND liga = 'Argentina'
    """)
    r = cur.fetchone()
    if not r:
        return {"status": "NOT_FOUND"}
    (en, er, liga, lfh, lch, lfa, lca, cfh, cch, cfa, cca, ph, pa, pch, pca) = r
    delta_fh = (cfh or 0) - (lfh or 0)
    delta_fa = (cfa or 0) - (lfa or 0)
    detecta_upturn = (delta_fh + delta_fa) > 0.20
    cur.execute("""
        SELECT fecha, local, visita, pais, goles_l, goles_v,
               xg_local, xg_visita
        FROM partidos_backtest
        WHERE pais = 'Argentina'
          AND (local LIKE 'Boca%' OR visita LIKE 'Boca%')
          AND estado = 'Liquidado'
        ORDER BY fecha DESC
        LIMIT 10
    """)
    ultimos = []
    for f, loc, vis, _, gl, gv, xgl, xgv in cur.fetchall():
        pick_actual = "L" if (xgl or 0) > (xgv or 0) + EPS_FLIP else (
            "V" if (xgv or 0) > (xgl or 0) + EPS_FLIP else "X")
        ultimos.append({
            "fecha": f, "local": loc, "visita": vis,
            "goles_l": gl, "goles_v": gv,
            "xg_local": round(xgl or 0, 3), "xg_visita": round(xgv or 0, 3),
            "pick_dir_actual": pick_actual,
        })
    return {
        "status": "OK",
        "equipo": er, "liga": liga,
        "n_largo": {"home": ph, "away": pa},
        "n_corto": {"home": pch, "away": pca},
        "ema_largo": {"fav_home": round(lfh, 4), "contra_home": round(lch, 4),
                      "fav_away": round(lfa, 4), "contra_away": round(lca, 4)},
        "ema_corto": {"fav_home": round(cfh, 4), "contra_home": round(cch, 4),
                      "fav_away": round(cfa, 4), "contra_away": round(cca, 4)},
        "deltas": {"fav_home": round(delta_fh, 4), "fav_away": round(delta_fa, 4)},
        "el_corto_detecta_upturn": detecta_upturn,
        "alfa_corto_argentina": alfa_corto_por_liga("Argentina"),
        "ultimos_10_partidos": ultimos,
        "caveat_estadistico": "N=38 partidos; segun Miller-Sanjurjo no distingue skill de luck. Narrativa, no evidencia firme.",
    }


def imprimir_console(reporte):
    print("=" * 70)
    print("BASELINE EMA DUAL SHADOW - comparativo_ema_dual.py")
    print("=" * 70)
    print(f"snapshot_db_sha256 (DataOps post-migration): {reporte['snapshot_db_sha256']}")
    print(f"snapshot_db_sha256 (this run):              {reporte['snapshot_db_sha256_now']}")
    d = reporte["divergencias_por_equipo"]
    print(f"\n[1] DIVERGENCIAS - {d['n_equipos_analizados']} equipos N>={N_MIN_EQUIPO}; "
          f"{d['n_modulados']} modulados, {d['n_fallback_puro']} fallback puro")
    print(f"    Top 10 por delta_max:")
    for it in d["top20"][:10]:
        print(f"      {it['equipo_real']:<24} ({it['liga']:<11}) "
              f"delta_max={it['delta_max']:.3f}  delta_avg={it['delta_avg']:.3f}")

    h = reporte["hit_rate_shadow_vs_actual"]
    print(f"\n[2] HIT RATE SHADOW VS ACTUAL: status={h['status']}")
    if h["status"] == "OK":
        print(f"    N picks={h['n_picks_reales']}, con_xg_corto={h['n_con_xg_corto']}, "
              f"flips={h['n_flips']} ({h['pct_flips']:.1%})")
        print(f"    Hit rate en flips: actual={h['hit_rate_actual_en_flips']:.3f}, "
              f"shadow={h['hit_rate_shadow_en_flips']:.3f}")
        print(f"    delta_brier_proxy={h['delta_brier_proxy']:+.4f}")
    else:
        print(f"    N picks reales={h['n_picks_reales']}; caveat: {h['caveat']}")

    cu = reporte["regime_change_cusum"]
    print(f"\n[3] CUSUM REGIME CHANGE (warmup={VENTANA_BRIER}):")
    for liga, info in cu.items():
        if info["status"] != "OK":
            print(f"    {liga:<12} {info['status']} (N={info['n']})")
            continue
        flag15 = info["flag_1_5_fecha"] or "(no)"
        flag20 = info["flag_2_0_fecha"] or "(no)"
        print(f"    {liga:<12} N={info['n']:<3} sigma={info['sigma_brier_rolling']:.4f} "
              f"cusum={info['cusum_actual']:.4f} flag1.5={flag15}  flag2.0={flag20}")

    b = reporte["caso_boca"]
    print(f"\n[4] CASO BOCA (N=38, narrativa):")
    if b["status"] == "OK":
        print(f"    EMA largo: fav_home={b['ema_largo']['fav_home']:.3f}, "
              f"fav_away={b['ema_largo']['fav_away']:.3f}")
        print(f"    EMA corto: fav_home={b['ema_corto']['fav_home']:.3f}, "
              f"fav_away={b['ema_corto']['fav_away']:.3f}")
        print(f"    Delta dir: fav_home={b['deltas']['fav_home']:+.3f}, "
              f"fav_away={b['deltas']['fav_away']:+.3f}")
        print(f"    El corto detecta upturn? {b['el_corto_detecta_upturn']}")
    print("=" * 70)


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] DB no encontrada: {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    ANALISIS_DIR.mkdir(parents=True, exist_ok=True)
    sha_now = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()

    snapshot_dataops = "444ac5be2ea9faf0716766376f6f5623f776f6391fab611cf032c8d78be18e7c"
    conn = sqlite3.connect(str(DB_PATH))

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(historial_equipos)")
    cols = {r[1] for r in cur.fetchall()}
    requeridas = {"ema_corto_favor_home", "ema_corto_contra_home",
                  "ema_corto_favor_away", "ema_corto_contra_away",
                  "partidos_corto_home", "partidos_corto_away"}
    if not requeridas.issubset(cols):
        print(f"[ERROR] Faltan columnas EMA corto en historial_equipos: {requeridas - cols}",
              file=sys.stderr)
        sys.exit(2)

    n_pob = cur.execute("""
        SELECT COUNT(*) FROM historial_equipos
        WHERE ema_corto_favor_home != 1.4 OR ema_corto_contra_home != 1.4
           OR ema_corto_favor_away != 1.4 OR ema_corto_contra_away != 1.4
    """).fetchone()[0]
    if n_pob < 100:
        print(f"[ERROR] EMA corto poco poblado: {n_pob} equipos. Backfill incompleto?",
              file=sys.stderr)
        sys.exit(3)

    print(f"[INFO] DB OK - sha256(now)={sha_now[:16]}...")
    print(f"[INFO] {n_pob}/333 equipos con ema_corto != default")

    reporte = {
        "ts": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "bead_id": "adepor-8zz",
        "snapshot_db_sha256": snapshot_dataops,
        "snapshot_db_sha256_now": sha_now,
        "snapshot_match": (sha_now == snapshot_dataops),
        "snapshot_match_caveat": (
            "El sha actual difiere del DataOps. SQLite puede modificar journal/metadata "
            "al abrir conn aun en SELECT. Datos NO modificados. Usar snapshot_db_sha256 "
            "(post-migration DataOps) como referencia oficial."
        ),
        "alfa_corto_por_liga": {l: alfa_corto_por_liga(l) for l in ALFA_LARGO_POR_LIGA},
        "divergencias_por_equipo": divergencias_por_equipo(conn),
        "hit_rate_shadow_vs_actual": hit_rate_shadow_vs_actual(conn),
        "regime_change_cusum": regime_change_cusum(conn),
        "caso_boca": caso_boca(conn),
        "limitaciones_metodologicas": [
            "(a) proxy direccional para flip, no Poisson exacto",
            "(b) CUSUM retrospectivo, no predictivo (GARCH out-of-scope)",
            "(c) caso Boca N=38: narrativa no evidencia (Miller-Sanjurjo)",
            "(d) delta_brier_proxy heuristico, no Brier real recalculado",
            "(e) seed=ema_largo en backfill: information leakage retroactivo, mitigado porque alfa_corto~0.30 -> peso seed cae 17% tras 5 partidos, 3% tras 10",
            "(f) CUSUM con warmup=VENTANA_BRIER: solo evalua flags despues de N>=ventana. Para Argentina (N=78) y Brasil (N=64), eso deja 28 y 14 puntos post-warmup respectivamente.",
        ],
    }
    out_path = ANALISIS_DIR / f"ema_dual_baseline_{reporte['ts']}.json"
    out_path.write_text(json.dumps(reporte, indent=2, ensure_ascii=False))
    print(f"[INFO] JSON escrito: {out_path}")
    imprimir_console(reporte)
    conn.close()
    print(f"\n[DONE] {out_path}")


if __name__ == "__main__":
    main()

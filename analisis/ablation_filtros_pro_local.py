"""Ablation completo: ¿qué pasa si SACAMOS los filtros pro-local?

Compara yield de TODAS las combinaciones:
  V0 - Base puro       (Poisson + tau, NADA mas)
  V1 - + HG            (boost local en Argentina/Brasil)
  V2 - + Fix #5        (+0.042 bucket 40-50%)
  V3 - + HG + Fix #5   (sistema actual = baseline)
  V4 - + HG + Fix #5 + Fix #6 v3 (propuesto, 1 bucket -0.024 outcome 1)
  V5 - + Fix #5 SOLO   (sin HG)
  V6 - + Fix #6 v3 SOLO (sin HG ni Fix #5)
  V7 - Base + Fix #6 v3 simetrizado (correccion -0.024 a p1 Y a p2 en bucket 30-35%)

Asi vemos:
  - Si HG aporta yield real (V1 vs V0)
  - Si Fix #5 aporta yield real (V2 vs V0)
  - Si Fix #6 v3 aporta sin HG (V6 vs V0)
  - Si simetrizar Fix #6 mejora (V7 vs V6)
"""
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

RANGO_POISSON = 10
N_MIN_HG = 50
BOOST_G_FRACCION = 0.50
HG_CAP_MAX = 0.95
CALIBRACION_BUCKET_MIN = 0.40
CALIBRACION_BUCKET_MAX = 0.50
CALIBRACION_CORRECCION = 0.042
MARGEN_MIN = 0.05
KELLY_CAP = 0.025
EV_MIN = 0.03

FIX6_V3_BUCKETS_ORIG = [("1", 0.30, 0.35, -0.0236)]
FIX6_V3_BUCKETS_SIM = [("1", 0.30, 0.35, -0.0236), ("2", 0.30, 0.35, -0.0236)]


def poisson(k, lam):
    if lam <= 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


def tau(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    if i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    if i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    if i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def calcular_probs_1x2(xg_l, xg_v, rho):
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    total = p1 + px + p2
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p1/total, px/total, p2/total


def aplicar_hg(p1, px, p2, freq_real):
    if freq_real is None or freq_real <= p1:
        return p1, px, p2
    boost = (freq_real - p1) * BOOST_G_FRACCION
    p1_new = min(p1 + boost, HG_CAP_MAX)
    rest = px + p2
    if rest <= 0:
        return p1_new, 0.5*(1-p1_new), 0.5*(1-p1_new)
    target = 1 - p1_new
    return p1_new, px*target/rest, p2*target/rest


def aplicar_fix5(p1, px, p2):
    p1_c, p2_c = p1, p2
    if CALIBRACION_BUCKET_MIN <= p1 < CALIBRACION_BUCKET_MAX:
        p1_c = p1 + CALIBRACION_CORRECCION
    if CALIBRACION_BUCKET_MIN <= p2 < CALIBRACION_BUCKET_MAX:
        p2_c = p2 + CALIBRACION_CORRECCION
    s = p1_c + px + p2_c
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1_c/s, px/s, p2_c/s


def aplicar_buckets(p1, px, p2, buckets):
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for b_out, lo, hi, corr in buckets:
            if b_out == outcome and lo <= prob < hi:
                p_corr[outcome] = max(0.001, prob + corr)
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"]/s, p_corr["X"]/s, p_corr["2"]/s


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0
    f = p - (1 - p) / (cuota - 1)
    return max(0, min(f, KELLY_CAP))


def simular_apuesta(p1, px, p2, c1, cx, c2):
    sorted_p = sorted([p1, px, p2], reverse=True)
    margen = sorted_p[0] - sorted_p[1]
    if margen < MARGEN_MIN:
        return None, 0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    argmax_label, argmax_prob, argmax_cuota = max(options, key=lambda x: x[1])
    if not argmax_cuota or argmax_cuota <= 1.0:
        return None, 0
    ev = argmax_prob * argmax_cuota - 1
    if ev < EV_MIN:
        return None, 0
    return argmax_label, kelly_fraction(argmax_prob, argmax_cuota)


def evaluar_yield(rows, freq_per_liga, rho_per_liga, version):
    sum_profit, sum_stake, n_apost, n_gano = 0, 0, 0, 0
    n_local, n_visita, n_empate = 0, 0, 0
    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv = r
        rho = rho_per_liga.get(pais, -0.09)
        p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)

        # Aplicar segun version
        if version in ("V1", "V3", "V4"):
            freq = freq_per_liga.get(pais)
            if freq is not None:
                p1, px, p2 = aplicar_hg(p1, px, p2, freq)
        if version in ("V2", "V3", "V4", "V5"):
            p1, px, p2 = aplicar_fix5(p1, px, p2)
        if version == "V4":
            p1, px, p2 = aplicar_buckets(p1, px, p2, FIX6_V3_BUCKETS_ORIG)
        if version == "V6":
            p1, px, p2 = aplicar_buckets(p1, px, p2, FIX6_V3_BUCKETS_ORIG)
        if version == "V7":
            p1, px, p2 = aplicar_buckets(p1, px, p2, FIX6_V3_BUCKETS_SIM)
        # V0: nada extra

        outcome = "1" if gl > gv else ("X" if gl == gv else "2")
        ap, stake = simular_apuesta(p1, px, p2, c1, cx, c2)
        if ap:
            cuota = {"1": c1, "X": cx, "2": c2}[ap]
            sum_stake += stake
            n_apost += 1
            if ap == "1":
                n_local += 1
            elif ap == "X":
                n_empate += 1
            else:
                n_visita += 1
            if ap == outcome:
                sum_profit += stake * (cuota - 1)
                n_gano += 1
            else:
                sum_profit -= stake
    return {
        "n_apost": n_apost, "n_gano": n_gano,
        "n_local": n_local, "n_visita": n_visita, "n_empate": n_empate,
        "stake": sum_stake, "profit": sum_profit,
        "yield": (sum_profit/sum_stake*100) if sum_stake > 0 else 0,
        "hit": (n_gano/n_apost*100) if n_apost > 0 else 0,
    }


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pais, xg_local, xg_visita, cuota_1, cuota_x, cuota_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND xg_local > 0 AND xg_visita > 0
          AND cuota_1 > 0 AND cuota_x > 0 AND cuota_2 > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """).fetchall()
    n_total = len(rows)

    freq_per_liga = {}
    for r in cur.execute("""
        SELECT pais, COUNT(*) as n,
               AVG(CASE WHEN goles_l > goles_v THEN 1.0 ELSE 0.0 END) as freq
        FROM partidos_backtest WHERE estado='Liquidado' AND goles_l IS NOT NULL
        GROUP BY pais
    """):
        if r[1] >= N_MIN_HG:
            freq_per_liga[r[0]] = r[2]
    rho_per_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    con.close()

    print(f"=== Ablation filtros pro-local — N={n_total} Liquidados ===\n")
    print("HG activo en:", list(freq_per_liga.keys()), "\n")

    # 5-fold CV pool
    np.random.seed(42)
    indices = list(range(n_total))
    np.random.shuffle(indices)
    K = 5
    fold_size = n_total // K

    versions = {
        "V0_base": "V0",
        "V1_HG": "V1",
        "V2_Fix5": "V2",
        "V3_HG+Fix5(actual)": "V3",
        "V4_HG+Fix5+Fix6v3": "V4",
        "V5_Fix5_sin_HG": "V5",
        "V6_Fix6v3_solo": "V6",
        "V7_Fix6v3_simetrizado": "V7",
    }

    all_results = {}
    for label, code in versions.items():
        sum_profit = sum_stake = n_a = n_g = 0
        n_loc = n_vis = n_emp = 0
        for fold in range(K):
            test_idx = set(indices[fold*fold_size:(fold+1)*fold_size])
            test_rows = [rows[j] for j in indices if j in test_idx]
            r = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, code)
            sum_profit += r["profit"]
            sum_stake += r["stake"]
            n_a += r["n_apost"]
            n_g += r["n_gano"]
            n_loc += r["n_local"]
            n_vis += r["n_visita"]
            n_emp += r["n_empate"]
        all_results[label] = {
            "n_apost": n_a, "n_gano": n_g,
            "n_local": n_loc, "n_visita": n_vis, "n_empate": n_emp,
            "stake": sum_stake, "profit": sum_profit,
            "yield": (sum_profit/sum_stake*100) if sum_stake > 0 else 0,
            "hit": (n_g/n_a*100) if n_a > 0 else 0,
            "pct_local": (n_loc/n_a*100) if n_a > 0 else 0,
        }

    print(f"{'Version':<28} {'N_apost':>8} {'Hit%':>7} {'%local':>7} {'Profit':>9} {'Yield%':>8}")
    print("-" * 75)
    for label, r in all_results.items():
        print(f"{label:<28} {r['n_apost']:>8} {r['hit']:>7.2f} {r['pct_local']:>7.1f} "
              f"{r['profit']:>+9.4f} {r['yield']:>+8.2f}")

    print()
    print("=== ANALISIS DE SESGO PRO-LOCAL ===")
    base = all_results["V0_base"]
    print(f"  Base (V0):   N={base['n_apost']}, %local={base['pct_local']:.1f}%, yield={base['yield']:+.2f}%")
    actual = all_results["V3_HG+Fix5(actual)"]
    print(f"  Actual (V3): N={actual['n_apost']}, %local={actual['pct_local']:.1f}%, yield={actual['yield']:+.2f}%")
    sin_hg = all_results["V5_Fix5_sin_HG"]
    print(f"  Sin HG (V5): N={sin_hg['n_apost']}, %local={sin_hg['pct_local']:.1f}%, yield={sin_hg['yield']:+.2f}%")

    print()
    print(f"  Δ %local V3 vs V0: {actual['pct_local'] - base['pct_local']:+.2f}pp")
    print(f"  Δ %local V3 vs V5: {actual['pct_local'] - sin_hg['pct_local']:+.2f}pp  (efecto solo HG)")

    print()
    print("=== MEJOR VERSION ABSOLUTA ===")
    best = max(all_results.items(), key=lambda x: x[1]["yield"])
    print(f"  Mejor yield: {best[0]} → {best[1]['yield']:+.2f}%")


if __name__ == "__main__":
    main()

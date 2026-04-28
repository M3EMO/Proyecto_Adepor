"""Análisis temporal: ¿V4.7 (adepor-6rv) y Fix #6 (adepor-u4z) cambian
su efecto sobre yield por temporada (2022/2023/2024)?

Si SÍ -> drift estructural del fútbol (cuotas/momentum/lineups cambian con
el tiempo y el efecto del parche varía).
Si NO (consistentemente neg/pos) -> efecto estable, ruido in-sample chico.

Setup OOS: predicciones_walkforward x cuotas_externas_historico (Pinnacle closing).
Por temp = 2022, 2023, 2024 (cada uno ~2,500 partidos).

Para cada temp:
  - Y_A baseline (HG+Fix5)
  - Y_D V4.7 (sin nada)
  - Y_Fix6 v2 (calibracion piecewise display)
  - paired bootstrap CI95 de cada delta

Compara contra in-sample (post 2026-03-16) reportado en v47_yield_in_sample.py.
"""
from __future__ import annotations

import json
import math
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
OUT = Path(__file__).resolve().parent / "yield_por_temp_v47_y_fix6.json"

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025
N_BOOTSTRAP = 2000
RANGO_POISSON = 10

N_MIN_HG = 50
BOOST_G_FRAC = 0.50
HG_CAP_MAX = 0.95
HG_GAP_MIN = 0.01

FIX5_BUCKET_LO = 0.40
FIX5_BUCKET_HI = 0.50
FIX5_DELTA = 0.042

FIX6_V2_BUCKETS = [
    ("1", 0.25, 0.30, -0.0369), ("1", 0.30, 0.35, -0.0236),
    ("1", 0.35, 0.40, +0.0181), ("1", 0.40, 0.45, +0.0198),
    ("1", 0.50, 0.55, +0.0605), ("1", 0.55, 0.60, +0.1067),
    ("2", 0.20, 0.25, -0.0451), ("2", 0.25, 0.30, -0.0348),
    ("2", 0.30, 0.35, -0.0314), ("2", 0.45, 0.50, +0.0536),
    ("2", 0.50, 0.55, +0.1092),
]


def aplicar_fix5(p1, px, p2):
    p1_c, p2_c = p1, p2
    if FIX5_BUCKET_LO <= p1 < FIX5_BUCKET_HI:
        p1_c = p1 + FIX5_DELTA
    if FIX5_BUCKET_LO <= p2 < FIX5_BUCKET_HI:
        p2_c = p2 + FIX5_DELTA
    if p1_c == p1 and p2_c == p2:
        return p1, px, p2
    s = p1_c + px + p2_c
    return p1_c / s, px / s, p2_c / s


def aplicar_fix6_v2(p1, px, p2):
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for b_out, lo, hi, corr in FIX6_V2_BUCKETS:
            if b_out == outcome and lo <= prob < hi:
                p_corr[outcome] = max(0.001, prob + corr)
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"]/s, p_corr["X"]/s, p_corr["2"]/s


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_partido(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < MARGEN_MIN:
        return 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return 0.0, 0.0
    if prob * cuota - 1 < EV_MIN:
        return 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return 0.0, 0.0
    if label == outcome:
        return stake, stake * (cuota - 1)
    return stake, -stake


def per_partido_metrics(rows):
    out = np.empty((len(rows), 4))
    for i, (p1, px, p2, c1, cx, c2, outcome) in enumerate(rows):
        stk, prof = evaluar_partido(p1, px, p2, c1, cx, c2, outcome)
        o1 = 1 if outcome == "1" else 0
        ox = 1 if outcome == "X" else 0
        o2 = 1 if outcome == "2" else 0
        br = (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2
        out[i] = (stk, prof, br, 1.0 if stk > 0 else 0.0)
    return out


def yield_de(arr):
    s = arr[:, 0].sum()
    p = arr[:, 1].sum()
    return (p / s * 100) if s > 0 else 0.0


def hit_de(arr):
    apostados = arr[arr[:, 3] == 1]
    if len(apostados) == 0:
        return 0.0
    n_gano = (apostados[:, 1] > 0).sum()
    return n_gano / len(apostados) * 100


def paired_bootstrap_delta(arr_a, arr_x, B=N_BOOTSTRAP, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr_a)
    deltas = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        sa = arr_a[idx, 0].sum()
        pa = arr_a[idx, 1].sum()
        sx = arr_x[idx, 0].sum()
        px = arr_x[idx, 1].sum()
        ya = (pa / sa * 100) if sa > 0 else 0.0
        yx = (px / sx * 100) if sx > 0 else 0.0
        deltas[b] = yx - ya
    return {
        "delta_yield_obs": yield_de(arr_x) - yield_de(arr_a),
        "delta_yield_mean_boot": float(deltas.mean()),
        "delta_yield_ci95_lo": float(np.percentile(deltas, 2.5)),
        "delta_yield_ci95_hi": float(np.percentile(deltas, 97.5)),
        "p_delta_negativo": float((deltas < 0).mean()),
        "p_delta_positivo": float((deltas > 0).mean()),
    }


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargo TODO con la temp
    rows_real = cur.execute("""
        SELECT p.temp, p.liga, p.fecha_partido, p.ht, p.at,
               p.prob_1, p.prob_x, p.prob_2,
               q.psch, q.pscd, q.psca, p.outcome
        FROM predicciones_walkforward p
        JOIN cuotas_externas_historico q
          ON p.liga = q.liga
         AND substr(p.fecha_partido, 1, 10) = q.fecha
         AND p.ht = q.ht
         AND p.at = q.at
        WHERE p.fuente='walk_forward_sistema_real'
          AND q.psch IS NOT NULL AND q.pscd IS NOT NULL AND q.psca IS NOT NULL
          AND p.prob_1 IS NOT NULL
    """).fetchall()
    rows_pure = cur.execute("""
        SELECT p.temp, p.liga, p.fecha_partido, p.ht, p.at,
               p.prob_1, p.prob_x, p.prob_2
        FROM predicciones_walkforward p
        WHERE p.fuente='walk_forward_persistente'
          AND p.prob_1 IS NOT NULL
    """).fetchall()
    con.close()

    key_real = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6], r[7], r[8], r[9], r[10], r[11]) for r in rows_real}
    key_pure = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6], r[7]) for r in rows_pure}
    keys = sorted(set(key_real.keys()) & set(key_pure.keys()))

    print(f"=== Yield por temp (V4.7 + Fix #6) — N alineado total = {len(keys)} ===")
    print(f"Filtros: MARGEN>={MARGEN_MIN} EV>={EV_MIN} KELLY={KELLY_CAP} B_boot={N_BOOTSTRAP}")
    print()

    # Construir 3 escenarios para cada partido: A, D (V4.7), Fix6_v2
    rows_por_temp = defaultdict(lambda: {"A": [], "D": [], "F6": []})
    for k in keys:
        temp, liga, fecha, ht, at = k
        p1_a, px_a, p2_a, c1, cx, c2, outcome = key_real[k]
        p1_d, px_d, p2_d = key_pure[k]
        # Fix #6 v2 sobre A (sistema_real probs)
        p1_f, px_f, p2_f = aplicar_fix6_v2(p1_a, px_a, p2_a)

        rA = (p1_a, px_a, p2_a, c1, cx, c2, outcome)
        rD = (p1_d, px_d, p2_d, c1, cx, c2, outcome)
        rF = (p1_f, px_f, p2_f, c1, cx, c2, outcome)
        rows_por_temp[temp]["A"].append(rA)
        rows_por_temp[temp]["D"].append(rD)
        rows_por_temp[temp]["F6"].append(rF)

    # Por temp: tabla con A vs D y A vs F6
    print(f"=== TABLA POR TEMP ===")
    print(f"{'Temp':<6} {'N':>5} {'NApA':>5} {'YldA%':>7} {'YldD%':>7} {'dY_DvA':>7} "
          f"{'CI95_lo':>9} {'CI95_hi':>9} {'P>0':>5} {'sig':>4} | "
          f"{'YldF6%':>7} {'dY_F6vA':>8} {'CI95_lo':>9} {'CI95_hi':>9} {'P>0':>5} {'sig':>4}")
    payload = {"por_temp": {}}
    for temp in sorted(rows_por_temp.keys()):
        rows = rows_por_temp[temp]
        arrA = per_partido_metrics(rows["A"])
        arrD = per_partido_metrics(rows["D"])
        arrF = per_partido_metrics(rows["F6"])

        yA = yield_de(arrA)
        yD = yield_de(arrD)
        yF = yield_de(arrF)
        n = len(rows["A"])
        nApA = int(arrA[:, 3].sum())
        nApD = int(arrD[:, 3].sum())
        nApF = int(arrF[:, 3].sum())

        res_DvA = paired_bootstrap_delta(arrA, arrD)
        res_FvA = paired_bootstrap_delta(arrA, arrF)
        sigD = "*" if (res_DvA["delta_yield_ci95_lo"] > 0 or res_DvA["delta_yield_ci95_hi"] < 0) else " "
        sigF = "*" if (res_FvA["delta_yield_ci95_lo"] > 0 or res_FvA["delta_yield_ci95_hi"] < 0) else " "

        print(f"{temp:<6} {n:>5} {nApA:>5} {yA:>+7.2f} {yD:>+7.2f} {res_DvA['delta_yield_obs']:>+7.2f} "
              f"{res_DvA['delta_yield_ci95_lo']:>+9.2f} {res_DvA['delta_yield_ci95_hi']:>+9.2f} "
              f"{res_DvA['p_delta_positivo']:>5.2f} {sigD:>4} | "
              f"{yF:>+7.2f} {res_FvA['delta_yield_obs']:>+8.2f} "
              f"{res_FvA['delta_yield_ci95_lo']:>+9.2f} {res_FvA['delta_yield_ci95_hi']:>+9.2f} "
              f"{res_FvA['p_delta_positivo']:>5.2f} {sigF:>4}")

        payload["por_temp"][int(temp)] = {
            "n": n,
            "n_apost_A": nApA, "n_apost_D": nApD, "n_apost_F6": nApF,
            "yield_A": yA, "yield_D": yD, "yield_F6": yF,
            "hit_A": hit_de(arrA), "hit_D": hit_de(arrD), "hit_F6": hit_de(arrF),
            "brier_A": float(arrA[:, 2].mean()),
            "brier_D": float(arrD[:, 2].mean()),
            "brier_F6": float(arrF[:, 2].mean()),
            "paired_DvsA": res_DvA,
            "paired_F6vsA": res_FvA,
        }

    # Drift detector: ¿la dirección es consistente entre temps?
    print()
    print(f"=== ANALISIS DE DRIFT ===")
    dys_DvA = [payload["por_temp"][t]["paired_DvsA"]["delta_yield_obs"] for t in sorted(payload["por_temp"].keys())]
    dys_FvA = [payload["por_temp"][t]["paired_F6vsA"]["delta_yield_obs"] for t in sorted(payload["por_temp"].keys())]
    temps_sorted = sorted(payload["por_temp"].keys())

    print(f"V4.7 (D - A) por temp: {[(t, f'{dy:+.2f}') for t,dy in zip(temps_sorted, dys_DvA)]}")
    print(f"  rango={max(dys_DvA)-min(dys_DvA):.2f}pp  signos={'+' if all(d>0 for d in dys_DvA) else '-' if all(d<0 for d in dys_DvA) else 'MIXTO'}")
    print(f"  → mismo signo todas las temps: {'SI (estable)' if all(d>=0 for d in dys_DvA) or all(d<=0 for d in dys_DvA) else 'NO (drift sospechoso)'}")
    print()
    print(f"Fix #6 (F6 - A) por temp: {[(t, f'{dy:+.2f}') for t,dy in zip(temps_sorted, dys_FvA)]}")
    print(f"  rango={max(dys_FvA)-min(dys_FvA):.2f}pp  signos={'+' if all(d>0 for d in dys_FvA) else '-' if all(d<0 for d in dys_FvA) else 'MIXTO'}")
    print(f"  → mismo signo todas las temps: {'SI (estable)' if all(d>=0 for d in dys_FvA) or all(d<=0 for d in dys_FvA) else 'NO (drift sospechoso)'}")

    payload["drift_analysis"] = {
        "dys_DvA_por_temp": dict(zip([int(t) for t in temps_sorted], dys_DvA)),
        "dys_F6vA_por_temp": dict(zip([int(t) for t in temps_sorted], dys_FvA)),
        "rango_DvA": max(dys_DvA) - min(dys_DvA),
        "rango_F6vA": max(dys_FvA) - min(dys_FvA),
        "signos_DvA_consistentes": all(d >= 0 for d in dys_DvA) or all(d <= 0 for d in dys_DvA),
        "signos_F6vA_consistentes": all(d >= 0 for d in dys_FvA) or all(d <= 0 for d in dys_FvA),
    }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

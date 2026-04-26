"""Fix #6 v3 selectivo: ablation por bucket + 5-fold CV.

Para cada uno de los 11 buckets de Fix #6 v2:
  1. Cross-validation 5-fold sobre Liquidados con cuotas
  2. En cada fold: simular yield SOLO con ese bucket activo (otros = 0)
  3. Δ yield_b = yield(Fix #5 + bucket b) - yield(Fix #5 solo)
  4. Bucket "robusto" = Δ yield > 0 en >=3/5 folds

Fix #6 v3 = union de buckets robustos.
Comparar yield Fix #5 vs Fix #6 v2 (completo) vs Fix #6 v3 (selectivo).
"""
import json
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

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "fix6_v3_ablation_selectivo.json"

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

# Fix #6 v2 buckets (todos)
FIX6_V2_BUCKETS = [
    ("1", 0.25, 0.30, -0.0369),
    ("1", 0.30, 0.35, -0.0236),
    ("1", 0.35, 0.40, +0.0181),
    ("1", 0.40, 0.45, +0.0198),
    ("1", 0.50, 0.55, +0.0605),
    ("1", 0.55, 0.60, +0.1067),
    ("2", 0.20, 0.25, -0.0451),
    ("2", 0.25, 0.30, -0.0348),
    ("2", 0.30, 0.35, -0.0314),
    ("2", 0.45, 0.50, +0.0536),
    ("2", 0.50, 0.55, +0.1092),
]


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


def aplicar_buckets_set(p1, px, p2, buckets_set):
    """Aplica un conjunto de buckets seleccionados. buckets_set = list of (outcome, lo, hi, corr)."""
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for b_out, lo, hi, corr in buckets_set:
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


def evaluar_yield(rows, freq_per_liga, rho_per_liga, buckets_extra):
    """Evalua yield aplicando cadena: probs_base + HG + Fix #5 + buckets_extra.
    Si buckets_extra=[], es Fix #5 solo (V_A baseline).
    """
    sum_profit, sum_stake, n_apost, n_gano = 0, 0, 0, 0
    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv = r
        rho = rho_per_liga.get(pais, -0.09)
        p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)
        freq = freq_per_liga.get(pais)
        if freq is not None:
            p1, px, p2 = aplicar_hg(p1, px, p2, freq)
        p1, px, p2 = aplicar_fix5(p1, px, p2)
        if buckets_extra:
            p1, px, p2 = aplicar_buckets_set(p1, px, p2, buckets_extra)

        outcome = "1" if gl > gv else ("X" if gl == gv else "2")
        ap, stake = simular_apuesta(p1, px, p2, c1, cx, c2)
        if ap:
            cuota = {"1": c1, "X": cx, "2": c2}[ap]
            sum_stake += stake
            n_apost += 1
            if ap == outcome:
                sum_profit += stake * (cuota - 1)
                n_gano += 1
            else:
                sum_profit -= stake
    yield_pct = (sum_profit / sum_stake * 100) if sum_stake > 0 else 0
    hit_pct = (n_gano / n_apost * 100) if n_apost > 0 else 0
    return {"n_apost": n_apost, "n_gano": n_gano,
            "stake": sum_stake, "profit": sum_profit,
            "yield": yield_pct, "hit": hit_pct}


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
    print(f"=== Ablation Fix #6 v3 selectivo — N={n_total} ===\n")

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

    # 5-fold CV
    np.random.seed(42)
    indices = list(range(n_total))
    np.random.shuffle(indices)
    K = 5
    fold_size = n_total // K

    # Por bucket: contar folds donde delta yield > 0
    bucket_results = []
    for i, bucket in enumerate(FIX6_V2_BUCKETS):
        outcome, lo, hi, corr = bucket
        bucket_label = f"{outcome}_{lo:.2f}-{hi:.2f}"
        deltas_yield = []
        for fold in range(K):
            test_idx = set(indices[fold*fold_size: (fold+1)*fold_size])
            test_rows = [rows[j] for j in indices if j in test_idx]
            r_a = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, [])
            r_b = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, [bucket])
            deltas_yield.append(r_b["yield"] - r_a["yield"])
        n_pos = sum(1 for d in deltas_yield if d > 0)
        avg_d = np.mean(deltas_yield)
        bucket_results.append({
            "bucket": bucket_label, "outcome": outcome, "lo": lo, "hi": hi, "corr": corr,
            "deltas_yield": deltas_yield, "n_folds_pos": n_pos, "avg_delta_yield": avg_d,
        })

    print(f"=== ABLATION POR BUCKET (5-fold CV, Δyield aislado) ===\n")
    print(f"{'Bucket':<18} {'Corr':>8} {'Folds_pos':>10} {'Avg ΔY':>9} {'Detalle ΔY por fold'}")
    for b in bucket_results:
        det = " ".join(f"{d:>+5.1f}" for d in b["deltas_yield"])
        print(f"{b['bucket']:<18} {b['corr']:>+8.4f} {b['n_folds_pos']}/5 {b['avg_delta_yield']:>+9.2f}  [{det}]")

    # Bucket robustos: >=3/5 folds positivos
    robustos = [b for b in bucket_results if b["n_folds_pos"] >= 3]
    print(f"\n=== BUCKETS ROBUSTOS (>=3/5 folds positivos): {len(robustos)} ===")
    fix6_v3_buckets = []
    for b in robustos:
        bk = next(bk for bk in FIX6_V2_BUCKETS if f"{bk[0]}_{bk[1]:.2f}-{bk[2]:.2f}" == b["bucket"])
        fix6_v3_buckets.append(bk)
        print(f"  {b['bucket']:<18} corr={b['corr']:+.4f} avg_Δyield={b['avg_delta_yield']:+.2f}pp")

    # Validacion final: comparar A (Fix #5) vs B (Fix #6 v2 completo) vs C (Fix #6 v3)
    print(f"\n=== VALIDACION FINAL (5-fold CV pool sobre N={n_total}) ===")
    fold_a, fold_b, fold_c = [], [], []
    for fold in range(K):
        test_idx = set(indices[fold*fold_size: (fold+1)*fold_size])
        test_rows = [rows[j] for j in indices if j in test_idx]
        r_a = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, [])
        r_b = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, FIX6_V2_BUCKETS)
        r_c = evaluar_yield(test_rows, freq_per_liga, rho_per_liga, fix6_v3_buckets)
        fold_a.append(r_a)
        fold_b.append(r_b)
        fold_c.append(r_c)

    def aggregate(folds):
        prof = sum(f["profit"] for f in folds)
        st = sum(f["stake"] for f in folds)
        nap = sum(f["n_apost"] for f in folds)
        ngano = sum(f["n_gano"] for f in folds)
        return {
            "n_apost": nap, "n_gano": ngano,
            "yield": (prof/st*100) if st > 0 else 0,
            "hit": (ngano/nap*100) if nap > 0 else 0,
            "profit": prof, "stake": st,
        }

    a, b, c = aggregate(fold_a), aggregate(fold_b), aggregate(fold_c)
    print(f"\n{'Version':<22} {'N_apost':>8} {'Hit%':>7} {'Stake':>8} {'Profit':>9} {'Yield%':>8}")
    print(f"{'A (Fix #5 actual)':<22} {a['n_apost']:>8} {a['hit']:>7.2f} {a['stake']:>8.4f} {a['profit']:>+9.4f} {a['yield']:>+8.2f}")
    print(f"{'B (Fix #6 v2 completo)':<22} {b['n_apost']:>8} {b['hit']:>7.2f} {b['stake']:>8.4f} {b['profit']:>+9.4f} {b['yield']:>+8.2f}")
    print(f"{'C (Fix #6 v3 selectivo)':<22} {c['n_apost']:>8} {c['hit']:>7.2f} {c['stake']:>8.4f} {c['profit']:>+9.4f} {c['yield']:>+8.2f}")

    print(f"\n=== DELTAS vs A (Fix #5 baseline) ===")
    print(f"  B vs A: ΔApost={b['n_apost']-a['n_apost']:+d}  ΔHit={b['hit']-a['hit']:+.2f}pp  "
          f"ΔProfit={b['profit']-a['profit']:+.4f}  ΔYield={b['yield']-a['yield']:+.2f}pp")
    print(f"  C vs A: ΔApost={c['n_apost']-a['n_apost']:+d}  ΔHit={c['hit']-a['hit']:+.2f}pp  "
          f"ΔProfit={c['profit']-a['profit']:+.4f}  ΔYield={c['yield']-a['yield']:+.2f}pp")

    OUT.write_text(json.dumps({
        "n_total": n_total,
        "bucket_ablation": bucket_results,
        "buckets_robustos": [
            {"outcome": b[0], "lo": b[1], "hi": b[2], "corr": b[3]}
            for b in fix6_v3_buckets
        ],
        "validation": {"A_fix5": a, "B_fix6v2": b, "C_fix6v3": c},
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

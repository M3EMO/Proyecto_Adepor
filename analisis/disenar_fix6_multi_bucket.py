"""Fix #6 multi-bucket: extension de Fix #5 con corrections calibradas en N=11634.

Procedimiento:
  1. Cargar predicciones_walkforward (N=11634).
  2. Reliability diagram por outcome (1, X, 2) — buckets 5pp.
  3. Para cada bucket con N>=50 y |gap|>=0.03: definir correccion = freq_real - prob_avg.
  4. Output: tabla de correcciones por (outcome, bucket) consumible por motor_calculadora.

Comparar con Fix #5 actual:
  Fix #5: bucket [40%, 50%) -> +0.042 a p1/p2.
  Fix #6: multi-bucket, signo per bucket.

Cross-validation 5-fold para detectar overfit.
"""
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

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "fix6_multi_bucket_design.json"

# Buckets 5pp
BUCKETS = [(i * 0.05, (i + 1) * 0.05) for i in range(20)]
N_MIN_BUCKET = 50
GAP_MIN = 0.03


def reliability_per_outcome(samples):
    """Por outcome ('1','X','2'), agrupa en buckets y retorna gap real-pred."""
    rel = {"1": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0}),
           "X": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0}),
           "2": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0})}
    for p1, px, p2, outcome in samples:
        for label, prob in [("1", p1), ("X", px), ("2", p2)]:
            for lo, hi in BUCKETS:
                if lo <= prob < hi:
                    hit = 1 if outcome == label else 0
                    rel[label][(lo, hi)]["sum_prob"] += prob
                    rel[label][(lo, hi)]["sum_hit"] += hit
                    rel[label][(lo, hi)]["n"] += 1
                    break
    return rel


def derivar_correcciones(rel):
    """Por outcome+bucket, define correccion si N>=50 y |gap|>=0.03."""
    correcciones = {"1": {}, "X": {}, "2": {}}
    for outcome in ["1", "X", "2"]:
        for (lo, hi), d in rel[outcome].items():
            if d["n"] < N_MIN_BUCKET:
                continue
            avg_prob = d["sum_prob"] / d["n"]
            freq_real = d["sum_hit"] / d["n"]
            gap = freq_real - avg_prob
            if abs(gap) < GAP_MIN:
                continue
            correcciones[outcome][f"{lo:.2f}-{hi:.2f}"] = {
                "lo": lo, "hi": hi, "n": d["n"],
                "avg_prob": round(avg_prob, 4),
                "freq_real": round(freq_real, 4),
                "correccion": round(gap, 4),
            }
    return correcciones


def aplicar_fix6(p1, px, p2, correcciones):
    """Aplica correcciones por bucket+outcome y renormaliza."""
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for bucket_label, info in correcciones[outcome].items():
            if info["lo"] <= prob < info["hi"]:
                p_corr[outcome] = max(0.001, prob + info["correccion"])
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"] / s, p_corr["X"] / s, p_corr["2"] / s


def aplicar_fix5_actual(p1, px, p2):
    """Fix #5 actual: +0.042 a p1/p2 en bucket [40%, 50%)."""
    p1_c, px_c, p2_c = p1, px, p2
    if 0.40 <= p1 < 0.50:
        p1_c = p1 + 0.042
    if 0.40 <= p2 < 0.50:
        p2_c = p2 + 0.042
    s = p1_c + px_c + p2_c
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1_c / s, px_c / s, p2_c / s


def brier(samples):
    total = 0
    for p1, px, p2, outcome in samples:
        b = ((p1 - (1 if outcome == "1" else 0)) ** 2
             + (px - (1 if outcome == "X" else 0)) ** 2
             + (p2 - (1 if outcome == "2" else 0)) ** 2)
        total += b
    return total / len(samples)


def hit_rate(samples):
    hits = 0
    for p1, px, p2, outcome in samples:
        argmax = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
        if argmax == outcome:
            hits += 1
    return hits / len(samples)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT prob_1, prob_x, prob_2, outcome
        FROM predicciones_walkforward
    """).fetchall()
    con.close()
    n = len(rows)
    print(f"=== Reliability + Fix #6 design — N={n} ===\n")

    samples = list(rows)

    # 5-fold CV
    np.random.seed(42)
    indices = list(range(n))
    np.random.shuffle(indices)
    K = 5
    fold_size = n // K

    fold_results = []
    for fold in range(K):
        test_idx = set(indices[fold * fold_size: (fold + 1) * fold_size])
        train = [samples[i] for i in indices if i not in test_idx]
        test = [samples[i] for i in indices if i in test_idx]

        # Aprender correcciones de train
        rel_train = reliability_per_outcome(train)
        corr_train = derivar_correcciones(rel_train)

        # Eval en test
        # Lado A: probs originales
        b_a = brier(test)
        h_a = hit_rate(test)

        # Lado B: probs con Fix #6
        test_b = [(*aplicar_fix6(t[0], t[1], t[2], corr_train), t[3]) for t in test]
        b_b = brier(test_b)
        h_b = hit_rate(test_b)

        # Lado C: probs con Fix #5 actual (bucket 40-50% +0.042)
        test_c = [(*aplicar_fix5_actual(t[0], t[1], t[2]), t[3]) for t in test]
        b_c = brier(test_c)
        h_c = hit_rate(test_c)

        fold_results.append({
            "fold": fold, "n_test": len(test), "n_train": len(train),
            "n_correcciones": sum(len(corr_train[o]) for o in ["1", "X", "2"]),
            "brier_orig": b_a, "brier_fix6": b_b, "brier_fix5": b_c,
            "hit_orig": h_a, "hit_fix6": h_b, "hit_fix5": h_c,
        })

    # Aggregate
    print(f"{'Fold':<5} {'N_test':>6} {'#corr':>6} {'Brier_orig':>11} {'Brier_Fix5':>11} {'Brier_Fix6':>11} {'Δ6_orig':>9} {'Δ6_5':>9}")
    for r in fold_results:
        d6_o = r["brier_fix6"] - r["brier_orig"]
        d6_5 = r["brier_fix6"] - r["brier_fix5"]
        print(f"{r['fold']:<5} {r['n_test']:>6} {r['n_correcciones']:>6} "
              f"{r['brier_orig']:>11.4f} {r['brier_fix5']:>11.4f} {r['brier_fix6']:>11.4f} "
              f"{d6_o:>+9.4f} {d6_5:>+9.4f}")

    # Pool
    n_total = sum(r["n_test"] for r in fold_results)
    b_o = sum(r["brier_orig"] * r["n_test"] for r in fold_results) / n_total
    b_5 = sum(r["brier_fix5"] * r["n_test"] for r in fold_results) / n_total
    b_6 = sum(r["brier_fix6"] * r["n_test"] for r in fold_results) / n_total
    h_o = sum(r["hit_orig"] * r["n_test"] for r in fold_results) / n_total
    h_5 = sum(r["hit_fix5"] * r["n_test"] for r in fold_results) / n_total
    h_6 = sum(r["hit_fix6"] * r["n_test"] for r in fold_results) / n_total

    print()
    print(f"=== POOL 5-fold (N={n_total}) ===")
    print(f"  Brier ORIG (sin fix):   {b_o:.4f}  Hit: {h_o:.4f}")
    print(f"  Brier Fix #5 actual:    {b_5:.4f}  Hit: {h_5:.4f}  Δ: {b_5-b_o:+.4f}")
    print(f"  Brier Fix #6 multi:     {b_6:.4f}  Hit: {h_6:.4f}  Δ: {b_6-b_o:+.4f}")
    print()
    print(f"  Δ Brier Fix #6 vs #5:   {b_6-b_5:+.4f}  ({'MEJORA' if b_6 < b_5 else 'EMPEORA'})")
    print(f"  Δ Hit Fix #6 vs #5:     {h_6-h_5:+.4f}")

    # Correcciones derivadas (sobre TODA la data, para expor)
    rel_all = reliability_per_outcome(samples)
    corr_all = derivar_correcciones(rel_all)
    print()
    print("=== Correcciones derivadas Fix #6 (con TODA la data) ===")
    for outcome in ["1", "X", "2"]:
        print(f"\n  Outcome {outcome}:")
        for bucket, info in sorted(corr_all[outcome].items()):
            print(f"    bucket {bucket}: N={info['n']:>4}  pred={info['avg_prob']:.3f}  real={info['freq_real']:.3f}  corr={info['correccion']:+.4f}")

    OUT.write_text(json.dumps({
        "n_total": n_total,
        "fold_results": fold_results,
        "pool": {
            "brier_orig": b_o, "brier_fix5": b_5, "brier_fix6": b_6,
            "hit_orig": h_o, "hit_fix5": h_5, "hit_fix6": h_6,
        },
        "correcciones_finales": corr_all,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

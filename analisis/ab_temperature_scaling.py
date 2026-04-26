"""A/B: motor actual vs motor + temperature scaling.

Temperature scaling: 1 parametro T. Si T=1 sin cambio. T<1 stretch (mas extremas).
T>1 compress (hacia 1/3). Aplicado al softmax(logits/T).

Para 1X2 con probs (p1, px, p2):
  logits = log(p)
  probs_T = softmax(logits / T)

Optimizamos T sobre TRAIN minimizando NLL (Negative Log Likelihood),
equivalente a log-loss. Luego eval en TEST.

Ventaja: 1 sola variable optimizada. Imposible overfit.
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np


def minimize_scalar_simple(f, bounds=(0.3, 3.0), n_iter=50):
    """Golden section search simple, sin scipy."""
    a, b = bounds
    phi = (1 + 5 ** 0.5) / 2
    inv_phi = 1 / phi
    c = b - (b - a) * inv_phi
    d = a + (b - a) * inv_phi
    for _ in range(n_iter):
        if f(c) < f(d):
            b = d
        else:
            a = c
        c = b - (b - a) * inv_phi
        d = a + (b - a) * inv_phi
    return (a + b) / 2

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "ab_temperature_scaling.json"


def temperature_scale(p1, px, p2, T):
    """Aplica softmax(logits/T) preservando proporciones."""
    eps = 1e-12
    p1 = max(p1, eps); px = max(px, eps); p2 = max(p2, eps)
    l1 = math.log(p1); lx = math.log(px); l2 = math.log(p2)
    l1 /= T; lx /= T; l2 /= T
    m = max(l1, lx, l2)
    e1 = math.exp(l1 - m); ex = math.exp(lx - m); e2 = math.exp(l2 - m)
    s = e1 + ex + e2
    return e1/s, ex/s, e2/s


def nll(samples, T):
    """Negative log-likelihood de los samples."""
    total = 0
    eps = 1e-12
    for p1, px, p2, outcome in samples:
        p1_t, px_t, p2_t = temperature_scale(p1, px, p2, T)
        if outcome == "1":
            total -= math.log(max(p1_t, eps))
        elif outcome == "X":
            total -= math.log(max(px_t, eps))
        else:
            total -= math.log(max(p2_t, eps))
    return total / len(samples)


def brier_score(samples, T):
    total = 0
    for p1, px, p2, outcome in samples:
        p1_t, px_t, p2_t = temperature_scale(p1, px, p2, T)
        b = ((p1_t - (1 if outcome == "1" else 0)) ** 2
             + (px_t - (1 if outcome == "X" else 0)) ** 2
             + (p2_t - (1 if outcome == "2" else 0)) ** 2)
        total += b
    return total / len(samples)


def hit_rate(samples, T):
    hits = 0
    for p1, px, p2, outcome in samples:
        p1_t, px_t, p2_t = temperature_scale(p1, px, p2, T)
        argmax = max([("1", p1_t), ("X", px_t), ("2", p2_t)], key=lambda x: x[1])[0]
        if argmax == outcome:
            hits += 1
    return hits / len(samples)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pais, fecha, prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND prob_1 IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha
    """).fetchall()
    con.close()
    n = len(rows)
    print(f"=== A/B Temperature Scaling — N={n} ===\n")

    # Build samples (pais, p1, px, p2, outcome)
    samples = []
    for r in rows:
        pais, fecha, p1, px, p2, gl, gv = r
        if gl > gv:
            outcome = "1"
        elif gl == gv:
            outcome = "X"
        else:
            outcome = "2"
        samples.append((pais, p1, px, p2, outcome))

    # 5-fold CV
    np.random.seed(42)
    indices = list(range(n))
    np.random.shuffle(indices)
    K = 5
    fold_size = n // K
    fold_results = []

    for fold in range(K):
        test_idx = indices[fold * fold_size: (fold + 1) * fold_size]
        train_idx = [i for i in indices if i not in set(test_idx)]
        train = [(s[1], s[2], s[3], s[4]) for s in [samples[i] for i in train_idx]]
        test = [(s[1], s[2], s[3], s[4]) for s in [samples[i] for i in test_idx]]

        # Optimize T on train
        T_opt = minimize_scalar_simple(lambda T: nll(train, T), bounds=(0.3, 3.0))

        b_a = brier_score(test, T=1.0)
        b_b = brier_score(test, T=T_opt)
        h_a = hit_rate(test, T=1.0)
        h_b = hit_rate(test, T=T_opt)

        fold_results.append({"fold": fold, "T": T_opt, "n_test": len(test),
                             "brier_a": b_a, "brier_b": b_b,
                             "hit_a": h_a, "hit_b": h_b})

    # Aggregate 5-fold results
    print(f"{'Fold':<5} {'T_opt':>7} {'N_test':>7} {'Brier_A':>8} {'Brier_B':>8} {'ΔB':>8} {'Hit_A':>7} {'Hit_B':>7}")
    print("-" * 80)
    sum_b_a, sum_b_b, sum_h_a, sum_h_b, total_n = 0, 0, 0, 0, 0
    for r in fold_results:
        print(f"{r['fold']:<5} {r['T']:>7.4f} {r['n_test']:>7} {r['brier_a']:>8.4f} "
              f"{r['brier_b']:>8.4f} {r['brier_b']-r['brier_a']:>+8.4f} "
              f"{r['hit_a']:>7.4f} {r['hit_b']:>7.4f}")
        sum_b_a += r["brier_a"] * r["n_test"]
        sum_b_b += r["brier_b"] * r["n_test"]
        sum_h_a += r["hit_a"] * r["n_test"]
        sum_h_b += r["hit_b"] * r["n_test"]
        total_n += r["n_test"]

    print()
    print(f"=== POOL 5-fold (N={total_n}) ===")
    print(f"  Brier_A pool:   {sum_b_a/total_n:.4f}")
    print(f"  Brier_B pool:   {sum_b_b/total_n:.4f}")
    print(f"  Δ Brier:        {(sum_b_b-sum_b_a)/total_n:+.4f}  ({'MEJORA' if sum_b_b < sum_b_a else 'EMPEORA'})")
    print(f"  Hit_A pool:     {sum_h_a/total_n:.4f}")
    print(f"  Hit_B pool:     {sum_h_b/total_n:.4f}")
    print(f"  Δ Hit:          {(sum_h_b-sum_h_a)/total_n:+.4f}")
    print()

    T_avg = np.mean([r["T"] for r in fold_results])
    print(f"  T_optimal promedio: {T_avg:.4f}")
    if T_avg < 0.95:
        print(f"    -> Modelo COMPRIME (probs hacia 1/3). Calibracion las STRETCH para {1-T_avg:.0%} más extremas.")
    elif T_avg > 1.05:
        print(f"    -> Modelo es OVER-CONFIDENT. Calibracion las COMPRIME hacia 1/3 ({T_avg-1:.0%} reduccion).")
    else:
        print(f"    -> Modelo casi calibrado.")

    OUT.write_text(json.dumps({
        "n_total": n,
        "fold_results": fold_results,
        "pool_brier_a": sum_b_a / total_n,
        "pool_brier_b": sum_b_b / total_n,
        "delta_brier": (sum_b_b - sum_b_a) / total_n,
        "T_avg": T_avg,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

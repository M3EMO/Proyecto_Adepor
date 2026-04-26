"""A/B: motor actual vs motor + calibracion isotonica post-process.

Procedimiento:
  1. Cargar Liquidados con probs y goles.
  2. Split: train (primeros 70%) + test (ultimos 30%).
  3. Train: aprender funcion isotonica prob_calibrada = f(prob_modelo)
     por outcome (1, X, 2).
  4. Test: aplicar f() a probs y comparar Brier vs probs originales.

Si delta_brier negativo (mejora) y consistente cross-liga -> PROPOSAL.

Implementacion isotonic regression:
  Para cada outcome, ordenar (prob, hit_real) por prob, hacer Pool Adjacent
  Violators algorithm para producir mapping monotono.
"""
import json
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
OUT = Path(__file__).resolve().parent / "ab_calibracion_isotonica.json"


def isotonic_regression(x, y):
    """Pool Adjacent Violators (PAV) algorithm - implementacion simple.

    Input: x sorted ascending, y values
    Output: y_iso fitted monotonic non-decreasing.
    """
    n = len(x)
    if n == 0:
        return np.array([])

    # Sort by x
    idx = np.argsort(x)
    x_sorted = x[idx]
    y_sorted = y[idx].astype(float)

    # PAV
    y_fit = y_sorted.copy()
    weights = np.ones(n)

    i = 0
    while i < n - 1:
        if y_fit[i] > y_fit[i + 1]:
            # Violation: pool
            new_w = weights[i] + weights[i + 1]
            new_v = (y_fit[i] * weights[i] + y_fit[i + 1] * weights[i + 1]) / new_w
            y_fit[i] = new_v
            y_fit[i + 1] = new_v
            weights[i] = new_w
            weights[i + 1] = new_w
            # Backtrack to ensure monotonicity
            j = i
            while j > 0 and y_fit[j - 1] > y_fit[j]:
                w = weights[j - 1] + weights[j]
                v = (y_fit[j - 1] * weights[j - 1] + y_fit[j] * weights[j]) / w
                y_fit[j - 1] = v
                y_fit[j] = v
                weights[j - 1] = w
                weights[j] = w
                j -= 1
        else:
            i += 1

    # Reconstruct in original order
    result = np.zeros(n)
    result[idx] = y_fit
    return x_sorted, y_fit


def apply_isotonic(prob, x_sorted, y_fit):
    """Aplica mapping isotonico a una prob nueva (interpolacion lineal)."""
    if len(x_sorted) == 0:
        return prob
    if prob <= x_sorted[0]:
        return y_fit[0]
    if prob >= x_sorted[-1]:
        return y_fit[-1]
    # Linear interp
    idx = np.searchsorted(x_sorted, prob)
    x0, x1 = x_sorted[idx - 1], x_sorted[idx]
    y0, y1 = y_fit[idx - 1], y_fit[idx]
    if x1 == x0:
        return (y0 + y1) / 2
    return y0 + (y1 - y0) * (prob - x0) / (x1 - x0)


def renormalize(p1, px, p2):
    s = p1 + px + p2
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


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
    print(f"=== A/B Calibracion Isotonica — N={n} ===\n")

    # Train/test split: 70% / 30% chronological
    split = int(n * 0.7)
    train, test = rows[:split], rows[split:]
    print(f"Train: {len(train)}  Test: {len(test)}")

    # Build train data per outcome
    def build_data(data):
        s1, sx, s2 = [], [], []
        for r in data:
            pais, fecha, p1, px, p2, gl, gv = r
            if gl > gv:
                outcome = "1"
            elif gl == gv:
                outcome = "X"
            else:
                outcome = "2"
            s1.append((p1, 1 if outcome == "1" else 0))
            sx.append((px, 1 if outcome == "X" else 0))
            s2.append((p2, 1 if outcome == "2" else 0))
        return s1, sx, s2

    s1_t, sx_t, s2_t = build_data(train)

    # Fit isotonic per outcome
    mappings = {}
    for label, samples in [("1", s1_t), ("X", sx_t), ("2", s2_t)]:
        x = np.array([s[0] for s in samples])
        y = np.array([s[1] for s in samples])
        x_sorted, y_fit = isotonic_regression(x, y)
        mappings[label] = (x_sorted, y_fit)

    # Apply on test, compute Brier antes y despues
    brier_a_sum = 0
    brier_b_sum = 0
    hits_a = 0
    hits_b = 0
    n_test = 0
    pred_data = []
    for r in test:
        pais, fecha, p1, px, p2, gl, gv = r
        if gl > gv:
            outcome = "1"; idx_real = 0
        elif gl == gv:
            outcome = "X"; idx_real = 1
        else:
            outcome = "2"; idx_real = 2

        # Lado A: probs originales
        b_a = ((p1 - (1 if outcome == "1" else 0)) ** 2
               + (px - (1 if outcome == "X" else 0)) ** 2
               + (p2 - (1 if outcome == "2" else 0)) ** 2)
        argmax_a = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
        hit_a = argmax_a == outcome

        # Lado B: probs calibradas isotonicamente
        p1_b = apply_isotonic(p1, *mappings["1"])
        px_b = apply_isotonic(px, *mappings["X"])
        p2_b = apply_isotonic(p2, *mappings["2"])
        # Renormalizar
        p1_b, px_b, p2_b = renormalize(p1_b, px_b, p2_b)
        b_b = ((p1_b - (1 if outcome == "1" else 0)) ** 2
               + (px_b - (1 if outcome == "X" else 0)) ** 2
               + (p2_b - (1 if outcome == "2" else 0)) ** 2)
        argmax_b = max([("1", p1_b), ("X", px_b), ("2", p2_b)], key=lambda x: x[1])[0]
        hit_b = argmax_b == outcome

        brier_a_sum += b_a
        brier_b_sum += b_b
        hits_a += int(hit_a)
        hits_b += int(hit_b)
        n_test += 1
        pred_data.append({
            "pais": pais, "outcome": outcome,
            "p_a": [p1, px, p2], "p_b": [p1_b, px_b, p2_b],
            "brier_a": b_a, "brier_b": b_b,
            "hit_a": hit_a, "hit_b": hit_b,
        })

    print(f"\n=== RESULTADOS sobre TEST set N={n_test} ===")
    print(f"  Brier_A (motor actual):    {brier_a_sum/n_test:.4f}")
    print(f"  Brier_B (con calibracion): {brier_b_sum/n_test:.4f}")
    print(f"  Δ Brier:                   {(brier_b_sum - brier_a_sum)/n_test:+.4f}  ({'MEJORA' if brier_b_sum < brier_a_sum else 'EMPEORA'})")
    print(f"  Hit_A:                     {hits_a/n_test:.4f}")
    print(f"  Hit_B:                     {hits_b/n_test:.4f}")
    print(f"  Δ Hit:                     {(hits_b - hits_a)/n_test:+.4f}")
    print()

    # Por liga
    by_liga = {}
    for p in pred_data:
        by_liga.setdefault(p["pais"], []).append(p)
    print("=== Por liga ===")
    print(f"{'Liga':<13} {'N':>4} {'Brier_A':>8} {'Brier_B':>8} {'ΔB':>8}  {'Hit_A':>6} {'Hit_B':>6}")
    for pais, preds in sorted(by_liga.items()):
        n_l = len(preds)
        b_a_l = sum(p["brier_a"] for p in preds) / n_l
        b_b_l = sum(p["brier_b"] for p in preds) / n_l
        h_a_l = sum(int(p["hit_a"]) for p in preds) / n_l
        h_b_l = sum(int(p["hit_b"]) for p in preds) / n_l
        print(f"{pais:<13} {n_l:>4} {b_a_l:>8.4f} {b_b_l:>8.4f} {b_b_l-b_a_l:>+8.4f}  {h_a_l:>6.3f} {h_b_l:>6.3f}")

    # Save mappings
    serializable_mappings = {}
    for k, (xs, ys) in mappings.items():
        serializable_mappings[k] = {"x": xs.tolist(), "y": ys.tolist()}
    OUT.write_text(json.dumps({
        "n_train": len(train), "n_test": n_test,
        "brier_a": brier_a_sum / n_test,
        "brier_b": brier_b_sum / n_test,
        "delta_brier": (brier_b_sum - brier_a_sum) / n_test,
        "hit_a": hits_a / n_test,
        "hit_b": hits_b / n_test,
        "delta_hit": (hits_b - hits_a) / n_test,
        "mappings": serializable_mappings,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

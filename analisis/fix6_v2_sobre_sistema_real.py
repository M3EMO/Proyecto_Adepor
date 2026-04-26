"""C4 PROPOSAL adepor-u4z: Fix #6 derivado sobre el SISTEMA REAL (con HG + Fix #5).

Compara contra Fix #6 v1 (derivado sobre modelo puro):
  - Si las correcciones bajan en magnitud -> mucho gap del modelo puro YA esta
    cubierto por HG + Fix #5, Fix #6 v1 es over-correccion.
  - Si las correcciones se mantienen -> HG/Fix #5 cubren poco del gap real.

Si Fix #6 v2 da mejora significativa con shrinkage 50%, va a PROPOSAL.
"""
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

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "fix6_v2_sistema_real.json"

BUCKETS = [(i * 0.05, (i + 1) * 0.05) for i in range(20)]
N_MIN_BUCKET = 50
GAP_MIN = 0.03
SHRINK = 0.5  # C2 critico: aplicar 50% shrinkage


def reliability_per_outcome(samples):
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


def derivar_correcciones(rel, shrink=SHRINK):
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
            corr_shrunk = gap * shrink
            correcciones[outcome][f"{lo:.2f}-{hi:.2f}"] = {
                "lo": lo, "hi": hi, "n": d["n"],
                "avg_prob": round(avg_prob, 4),
                "freq_real": round(freq_real, 4),
                "gap_empirico": round(gap, 4),
                "correccion_shrink50": round(corr_shrunk, 4),
            }
    return correcciones


def aplicar_fix6(p1, px, p2, correcciones):
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for bucket_label, info in correcciones[outcome].items():
            if info["lo"] <= prob < info["hi"]:
                p_corr[outcome] = max(0.001, prob + info["correccion_shrink50"])
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"] / s, p_corr["X"] / s, p_corr["2"] / s


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


def margen_mean(samples):
    """Margen medio entre top1 y top2 (para detectar inflation)."""
    margenes = []
    for p1, px, p2, _ in samples:
        s = sorted([p1, px, p2], reverse=True)
        margenes.append(s[0] - s[1])
    return np.mean(margenes)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT prob_1, prob_x, prob_2, outcome
        FROM predicciones_walkforward
        WHERE fuente = 'walk_forward_sistema_real'
    """).fetchall()
    con.close()
    n = len(rows)
    print(f"=== Fix #6 v2 sobre SISTEMA REAL (con HG + Fix #5) — N={n} ===\n")
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

        rel_train = reliability_per_outcome(train)
        corr_train = derivar_correcciones(rel_train, shrink=SHRINK)

        b_a = brier(test)
        h_a = hit_rate(test)
        margen_a = margen_mean(test)

        test_b = [(*aplicar_fix6(t[0], t[1], t[2], corr_train), t[3]) for t in test]
        b_b = brier(test_b)
        h_b = hit_rate(test_b)
        margen_b = margen_mean(test_b)

        fold_results.append({
            "fold": fold, "n_test": len(test),
            "n_correcciones": sum(len(corr_train[o]) for o in ["1", "X", "2"]),
            "brier_orig": b_a, "brier_fix6v2": b_b,
            "hit_orig": h_a, "hit_fix6v2": h_b,
            "margen_orig": margen_a, "margen_fix6v2": margen_b,
        })

    print(f"{'Fold':<5} {'#corr':>5} {'BrierA':>8} {'BrierB':>8} {'ΔB':>8} {'HitA':>6} {'HitB':>6} {'mgnA':>6} {'mgnB':>6}")
    for r in fold_results:
        print(f"{r['fold']:<5} {r['n_correcciones']:>5} "
              f"{r['brier_orig']:>8.4f} {r['brier_fix6v2']:>8.4f} {r['brier_fix6v2']-r['brier_orig']:>+8.4f} "
              f"{r['hit_orig']:>6.3f} {r['hit_fix6v2']:>6.3f} "
              f"{r['margen_orig']:>6.3f} {r['margen_fix6v2']:>6.3f}")

    n_total = sum(r["n_test"] for r in fold_results)
    b_o = sum(r["brier_orig"] * r["n_test"] for r in fold_results) / n_total
    b_b = sum(r["brier_fix6v2"] * r["n_test"] for r in fold_results) / n_total
    h_o = sum(r["hit_orig"] * r["n_test"] for r in fold_results) / n_total
    h_b = sum(r["hit_fix6v2"] * r["n_test"] for r in fold_results) / n_total
    m_o = sum(r["margen_orig"] * r["n_test"] for r in fold_results) / n_total
    m_b = sum(r["margen_fix6v2"] * r["n_test"] for r in fold_results) / n_total

    print()
    print(f"=== POOL 5-fold (N={n_total}) ===")
    print(f"  Sistema actual (HG + Fix #5):   Brier={b_o:.4f}  Hit={h_o:.4f}  Margen_avg={m_o:.4f}")
    print(f"  + Fix #6 v2 (shrink 50%):       Brier={b_b:.4f}  Hit={h_b:.4f}  Margen_avg={m_b:.4f}")
    print(f"  Δ Brier:    {b_b-b_o:+.4f}  ({'MEJORA' if b_b < b_o else 'EMPEORA'})")
    print(f"  Δ Hit:      {h_b-h_o:+.4f}")
    print(f"  Δ Margen:   {m_b-m_o:+.4f}  ({'INFLATE' if m_b > m_o else 'no inflate'})")

    # Correcciones derivadas con TODA la data (para implementacion final)
    rel_all = reliability_per_outcome(samples)
    corr_all = derivar_correcciones(rel_all, shrink=SHRINK)
    print()
    print("=== Correcciones Fix #6 v2 (con TODA data, shrink 50%) ===")
    for outcome in ["1", "X", "2"]:
        if not corr_all[outcome]:
            print(f"\n  Outcome {outcome}: 0 buckets requieren correccion")
            continue
        print(f"\n  Outcome {outcome}:")
        for bucket, info in sorted(corr_all[outcome].items()):
            print(f"    bucket {bucket}: N={info['n']:>4}  pred={info['avg_prob']:.3f}  real={info['freq_real']:.3f}  "
                  f"gap={info['gap_empirico']:+.4f}  corr_shrink50={info['correccion_shrink50']:+.4f}")

    OUT.write_text(json.dumps({
        "n_total": n_total,
        "fold_results": fold_results,
        "pool": {
            "brier_sistema_actual": b_o,
            "brier_fix6v2": b_b,
            "delta_brier": b_b - b_o,
            "hit_sistema_actual": h_o,
            "hit_fix6v2": h_b,
            "delta_hit": h_b - h_o,
            "margen_sistema_actual": m_o,
            "margen_fix6v2": m_b,
            "delta_margen": m_b - m_o,
        },
        "correcciones_finales": corr_all,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

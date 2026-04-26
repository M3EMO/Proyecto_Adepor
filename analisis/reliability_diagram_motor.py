"""Reliability diagram + Murphy decomposition del motor real.

Para cada outcome (1, X, 2):
  Agrupa predicciones en buckets de prob (5pp)
  Calcula prob_promedio_predicha vs frecuencia_real_observada
  Si bucket prob 40-50% tiene freq real 35% -> motor SOBRE-confiado
  Si bucket prob 30-40% tiene freq real 45% -> motor SUB-confiado

Murphy decomposition: Brier = Reliability + Resolution + Uncertainty (signo)
  Reliability LOW = bien calibrado
  Resolution HIGH = discriminativo
  Aplicar calibracion isotonica baja Reliability sin tocar Resolution.

OUTPUTS:
  - reliability_diagram_motor.json
  - Recomendacion: calibrar Platt/Isotonic/Beta?
"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "reliability_diagram_motor.json"


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar Liquidados con probs y goles
    rows = cur.execute("""
        SELECT pais, prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND prob_1 IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """).fetchall()
    n_total = len(rows)
    print(f"=== RELIABILITY DIAGRAM — N={n_total} Liquidados ===\n")

    # Por outcome (1, X, 2): coleccionar (prob_predicha, hit_real) per partido
    samples = {"1": [], "X": [], "2": []}
    for r in rows:
        pais, p1, px, p2, gl, gv = r
        if gl > gv:
            outcome = "1"
        elif gl == gv:
            outcome = "X"
        else:
            outcome = "2"
        samples["1"].append((p1, 1 if outcome == "1" else 0))
        samples["X"].append((px, 1 if outcome == "X" else 0))
        samples["2"].append((p2, 1 if outcome == "2" else 0))

    # Reliability por outcome + bucket
    BUCKETS = [(i * 0.05, (i + 1) * 0.05) for i in range(20)]
    print(f"{'Outcome':<8} {'Bucket':<10} {'N':>4} {'avg_prob':>9} {'freq_real':>10} {'gap (real-prob)':>16}")
    print("-" * 65)

    reliability_data = {}
    for outcome in ["1", "X", "2"]:
        s = samples[outcome]
        rel = defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0})
        for prob, hit in s:
            for lo, hi in BUCKETS:
                if lo <= prob < hi:
                    rel[(lo, hi)]["sum_prob"] += prob
                    rel[(lo, hi)]["sum_hit"] += hit
                    rel[(lo, hi)]["n"] += 1
                    break
        reliability_data[outcome] = {}
        for lo, hi in BUCKETS:
            d = rel[(lo, hi)]
            if d["n"] < 3:
                continue
            avg_prob = d["sum_prob"] / d["n"]
            freq_real = d["sum_hit"] / d["n"]
            gap = freq_real - avg_prob
            label = f"[{lo:.2f},{hi:.2f})"
            print(f"{outcome:<8} {label:<10} {d['n']:>4} {avg_prob:>9.4f} {freq_real:>10.4f} {gap:>+16.4f}")
            reliability_data[outcome][label] = {
                "n": d["n"], "avg_prob": round(avg_prob, 4),
                "freq_real": round(freq_real, 4), "gap": round(gap, 4),
            }
        print()

    # Murphy decomposition (aprox) y Brier por componente
    print("=== Murphy decomposition (aprox por outcome) ===")
    print(f"{'Outcome':<8} {'Brier':>7} {'Reliability':>11} {'Resolution':>10} {'Uncertainty':>11}")

    base_rates = {"1": 0, "X": 0, "2": 0}
    for r in rows:
        pais, p1, px, p2, gl, gv = r
        if gl > gv:
            base_rates["1"] += 1
        elif gl == gv:
            base_rates["X"] += 1
        else:
            base_rates["2"] += 1
    for k in base_rates:
        base_rates[k] /= n_total

    murphy = {}
    for outcome in ["1", "X", "2"]:
        s = samples[outcome]
        n = len(s)
        # Brier
        brier = sum((p - h) ** 2 for p, h in s) / n
        # Uncertainty = base_rate * (1 - base_rate)
        b = base_rates[outcome]
        unc = b * (1 - b)
        # Reliability via buckets
        rel_sum = 0
        res_sum = 0
        rel_data = reliability_data[outcome]
        for label, d in rel_data.items():
            rel_sum += d["n"] * (d["avg_prob"] - d["freq_real"]) ** 2
            res_sum += d["n"] * (d["freq_real"] - b) ** 2
        rel = rel_sum / n
        res = res_sum / n
        # Brier ~ Reliability - Resolution + Uncertainty (decomposicion aprox)
        brier_recomp = rel - res + unc
        murphy[outcome] = {
            "brier": round(brier, 4),
            "reliability": round(rel, 5),
            "resolution": round(res, 5),
            "uncertainty": round(unc, 5),
            "brier_aprox_decomp": round(brier_recomp, 4),
        }
        print(f"{outcome:<8} {brier:>7.4f} {rel:>11.5f} {res:>10.5f} {unc:>11.5f}")

    print()
    print("=== INTERPRETACION ===")
    print("Reliability LOW (<0.005) = bien calibrado")
    print("Resolution HIGH (>0.04) = modelo discriminativo")
    print()
    rel_total = sum(murphy[o]["reliability"] for o in ["1", "X", "2"]) / 3
    res_total = sum(murphy[o]["resolution"] for o in ["1", "X", "2"]) / 3
    print(f"Reliability promedio: {rel_total:.5f}")
    print(f"Resolution promedio:  {res_total:.5f}")

    if rel_total > 0.005:
        print("=> CALIBRACION (Platt/Isotonic) MEJORARIA Brier")
    else:
        print("=> Modelo ya bien calibrado, gain marginal de calibracion")

    # Save
    out_data = {
        "n_total": n_total,
        "base_rates": base_rates,
        "reliability_per_outcome": reliability_data,
        "murphy_decomposition": murphy,
    }
    OUT.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

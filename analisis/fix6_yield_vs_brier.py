"""Test de yield Fix #6 vs Brier sobre walk-forward + Pinnacle closing real.

Cumple condicion C5 del critico (decision-log adepor-0ll):
  "Antes de aprobar, demostrar que Fix #6 NO degrada yield agregado en backtest
   con cuotas reales. Brier mejora -0.0109 != yield mejora."

Setup:
  - Predicciones: predicciones_walkforward.fuente='walk_forward_sistema_real'
    (probs YA tienen HG + Fix #5 aplicado, segun la nota del critico C4)
  - Cuotas: cuotas_externas_historico.psch/pscd/psca (Pinnacle closing 2022-2024)
  - JOIN: liga + substr(fecha,1,10) + ht + at = N=7868 (8 ligas)

Escenarios:
  A. Sistema actual (HG + Fix #5 ya aplicado, sin Fix #6) -- baseline
  B. + Fix #6 v1 NO shrinkage (11 buckets gap empirico bruto)
  C. + Fix #6 v2 shrink 50% (recomendacion critico C2)
  D. + Fix #6 v3 selectivo (1 bucket robusto = 1_0.30-0.35 corr=-0.0236)

Para cada escenario:
  - Brier promedio sobre TODAS las predicciones (no solo apostadas)
  - Filtros operativos: MARGEN_MIN=0.05, EV_MIN=0.03 (escalonado simplificado),
    KELLY_CAP=0.025
  - n_apost, hit, profit, stake, yield
  - Bootstrap CI95 (B=1000) sobre yield
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
OUT = Path(__file__).resolve().parent / "fix6_yield_vs_brier.json"

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025
N_BOOTSTRAP = 1000

# Fix #6 v1 (gap empirico bruto, sin shrinkage) -- del JSON disenar_fix6_multi_bucket
# Estos son los originales del PROPOSAL Lead que el critico cuestiono.
FIX6_V1_BUCKETS = [
    ("1", 0.25, 0.30, -0.0853),
    ("1", 0.35, 0.40, +0.0319),
    ("1", 0.40, 0.45, +0.0852),
    ("1", 0.45, 0.50, +0.1225),
    ("1", 0.50, 0.55, +0.1853),
    ("1", 0.55, 0.60, +0.2134),
    ("2", 0.20, 0.25, -0.0949),
    ("2", 0.25, 0.30, -0.1007),
    ("2", 0.30, 0.35, -0.0850),
    ("2", 0.40, 0.45, +0.0632),
    ("2", 0.45, 0.50, +0.1505),
]

# Fix #6 v2 shrink 50% (del fix6_v2_sistema_real.json)
# Derivado sobre walk_forward_sistema_real (post-HG/Fix#5), shrink 50%.
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

# Fix #6 v3 selectivo (del fix6_v3_ablation_selectivo.json)
# Solo bucket robusto en ablation por yield.
FIX6_V3_BUCKETS = [
    ("1", 0.30, 0.35, -0.0236),
]


def aplicar_buckets(p1: float, px: float, p2: float, buckets):
    if not buckets:
        return p1, px, p2
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


def kelly_fraction(p: float, cuota: float) -> float:
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_partido(p1, px, p2, c1, cx, c2, outcome):
    """Aplica filtros del motor y devuelve (apostado, ganado, stake, profit, brier).
    apostado=True si pasa MARGEN_MIN + EV_MIN.
    """
    o1 = 1 if outcome == "1" else 0
    ox = 1 if outcome == "X" else 0
    o2 = 1 if outcome == "2" else 0
    brier = (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2

    sorted_p = sorted([p1, px, p2], reverse=True)
    margen = sorted_p[0] - sorted_p[1]
    if margen < MARGEN_MIN:
        return False, False, 0.0, 0.0, brier

    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, False, 0.0, 0.0, brier
    ev = prob * cuota - 1
    if ev < EV_MIN:
        return False, False, 0.0, 0.0, brier

    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, False, 0.0, 0.0, brier
    if label == outcome:
        return True, True, stake, stake * (cuota - 1), brier
    return True, False, stake, -stake, brier


def evaluar_escenario(rows, buckets):
    """Devuelve metricas globales + per-partido para bootstrap."""
    per_partido = []
    n_apost = 0
    n_gano = 0
    sum_stake = 0.0
    sum_profit = 0.0
    sum_brier = 0.0
    n_pred = 0
    for p1, px, p2, c1, cx, c2, outcome in rows:
        q1, qx, q2 = aplicar_buckets(p1, px, p2, buckets)
        ap, gan, stk, prof, br = evaluar_partido(q1, qx, q2, c1, cx, c2, outcome)
        per_partido.append((ap, stk, prof, br))
        if ap:
            n_apost += 1
            if gan:
                n_gano += 1
            sum_stake += stk
            sum_profit += prof
        sum_brier += br
        n_pred += 1
    yield_pct = (sum_profit / sum_stake * 100) if sum_stake > 0 else 0.0
    hit_pct = (n_gano / n_apost * 100) if n_apost > 0 else 0.0
    brier_avg = sum_brier / n_pred if n_pred > 0 else 0.0
    return {
        "n_predicciones": n_pred,
        "n_apost": n_apost,
        "n_gano": n_gano,
        "stake": sum_stake,
        "profit": sum_profit,
        "yield_pct": yield_pct,
        "hit_pct": hit_pct,
        "brier_avg": brier_avg,
        "per_partido": per_partido,
    }


def bootstrap_yield_ci(per_partido, B=N_BOOTSTRAP, seed=42):
    rng = np.random.default_rng(seed)
    n = len(per_partido)
    yields = []
    pp = np.array([(s, p) for _, s, p, _ in per_partido])
    stakes = pp[:, 0]
    profits = pp[:, 1]
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        s = stakes[idx].sum()
        p = profits[idx].sum()
        yields.append((p / s * 100) if s > 0 else 0.0)
    yields = np.array(yields)
    return float(np.percentile(yields, 2.5)), float(np.percentile(yields, 97.5)), float(yields.mean()), float(yields.std())


def per_liga_yield(rows_por_liga, buckets):
    out = {}
    for liga, rows in rows_por_liga.items():
        m = evaluar_escenario(rows, buckets)
        out[liga] = {
            "n_pred": m["n_predicciones"],
            "n_apost": m["n_apost"],
            "n_gano": m["n_gano"],
            "yield_pct": m["yield_pct"],
            "hit_pct": m["hit_pct"],
            "brier_avg": m["brier_avg"],
        }
    return out


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows_raw = cur.execute("""
        SELECT p.liga, p.prob_1, p.prob_x, p.prob_2,
               q.psch, q.pscd, q.psca,
               p.outcome
        FROM predicciones_walkforward p
        JOIN cuotas_externas_historico q
          ON p.liga = q.liga
         AND substr(p.fecha_partido, 1, 10) = q.fecha
         AND p.ht = q.ht
         AND p.at = q.at
        WHERE p.fuente='walk_forward_sistema_real'
          AND q.psch IS NOT NULL AND q.pscd IS NOT NULL AND q.psca IS NOT NULL
          AND p.prob_1 IS NOT NULL AND p.prob_x IS NOT NULL AND p.prob_2 IS NOT NULL
    """).fetchall()
    con.close()

    # Convertir a tuplas (p1,px,p2,c1,cx,c2,outcome) y agrupar por liga
    rows = [(r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows_raw]
    rows_por_liga = defaultdict(list)
    for r in rows_raw:
        liga = r[0]
        rows_por_liga[liga].append((r[1], r[2], r[3], r[4], r[5], r[6], r[7]))

    print(f"=== Fix #6 yield-vs-brier validation (Pinnacle closing) ===")
    print(f"N = {len(rows)} predicciones (8 ligas)")
    print(f"Filtros: MARGEN>={MARGEN_MIN}  EV>={EV_MIN}  KELLY_CAP={KELLY_CAP}")
    print()

    escenarios = [
        ("A. Sistema actual (HG+Fix5)", []),
        ("B. + Fix #6 v1 (sin shrink)", FIX6_V1_BUCKETS),
        ("C. + Fix #6 v2 (shrink 50%)", FIX6_V2_BUCKETS),
        ("D. + Fix #6 v3 (selectivo)",  FIX6_V3_BUCKETS),
    ]

    resultados = {}
    print(f"{'Escenario':<35} {'NPred':>6} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} "
          f"{'CI95_lo':>8} {'CI95_hi':>8} {'Brier':>7}")
    for nombre, buckets in escenarios:
        m = evaluar_escenario(rows, buckets)
        ci_lo, ci_hi, ci_mean, ci_std = bootstrap_yield_ci(m["per_partido"])
        sig = "*" if (ci_lo > 0 or ci_hi < 0) else " "
        print(f"{nombre:<35} {m['n_predicciones']:>6} {m['n_apost']:>7} {m['hit_pct']:>6.2f} "
              f"{m['yield_pct']:>+8.2f} {ci_lo:>+8.2f} {ci_hi:>+8.2f} {m['brier_avg']:>7.4f} {sig}")
        resultados[nombre] = {
            "n_predicciones": m["n_predicciones"],
            "n_apost": m["n_apost"],
            "n_gano": m["n_gano"],
            "stake": m["stake"],
            "profit": m["profit"],
            "yield_pct": m["yield_pct"],
            "hit_pct": m["hit_pct"],
            "brier_avg": m["brier_avg"],
            "yield_ci95_lo": ci_lo,
            "yield_ci95_hi": ci_hi,
            "yield_boot_mean": ci_mean,
            "yield_boot_std": ci_std,
        }

    print()
    print("=== Deltas vs A (baseline sistema actual) ===")
    base = resultados["A. Sistema actual (HG+Fix5)"]
    print(f"{'Escenario':<35} {'dBrier':>9} {'dHit%':>8} {'dYield%':>10} {'dApost':>8}")
    for nombre, _ in escenarios[1:]:
        r = resultados[nombre]
        print(f"{nombre:<35} {r['brier_avg']-base['brier_avg']:>+9.4f} "
              f"{r['hit_pct']-base['hit_pct']:>+8.2f} "
              f"{r['yield_pct']-base['yield_pct']:>+10.2f} "
              f"{r['n_apost']-base['n_apost']:>+8d}")

    # Per-liga sobre el escenario C (v2 shrink 50%) -- el del crítico
    print()
    print("=== Per-liga: A (baseline) vs C (Fix #6 v2 shrink 50%) ===")
    per_liga_a = per_liga_yield(rows_por_liga, [])
    per_liga_c = per_liga_yield(rows_por_liga, FIX6_V2_BUCKETS)
    print(f"{'Liga':<14} {'NPred':>6} {'BrierA':>7} {'BrierC':>7} {'dBrier':>9} "
          f"{'YldA%':>7} {'YldC%':>7} {'dYld%':>8} {'NApA':>5} {'NApC':>5}")
    for liga in sorted(per_liga_a.keys()):
        a = per_liga_a[liga]
        c = per_liga_c[liga]
        print(f"{liga:<14} {a['n_pred']:>6} {a['brier_avg']:>7.4f} {c['brier_avg']:>7.4f} "
              f"{c['brier_avg']-a['brier_avg']:>+9.4f} "
              f"{a['yield_pct']:>+7.2f} {c['yield_pct']:>+7.2f} "
              f"{c['yield_pct']-a['yield_pct']:>+8.2f} "
              f"{a['n_apost']:>5} {c['n_apost']:>5}")

    # Output JSON (sin per_partido para mantener archivo manejable)
    out_payload = {
        "n_total": len(rows),
        "filtros": {"margen_min": MARGEN_MIN, "ev_min": EV_MIN, "kelly_cap": KELLY_CAP},
        "fuente_probs": "walk_forward_sistema_real (HG+Fix5 aplicado)",
        "fuente_cuotas": "cuotas_externas_historico.psch/pscd/psca (Pinnacle closing 2022-2024)",
        "ligas": list(sorted(rows_por_liga.keys())),
        "escenarios": {nombre: {k: v for k, v in res.items()}
                       for nombre, res in resultados.items()},
        "per_liga_baseline_vs_v2": {
            liga: {"baseline": per_liga_a[liga], "fix6_v2": per_liga_c[liga]}
            for liga in sorted(per_liga_a.keys())
        },
    }
    OUT.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

"""(b) Paired bootstrap CI95 + (c) per-liga deep dive sobre Fix #6.

(b) Paired bootstrap:
   En cada iteracion sampleo los MISMOS partidos para A y C, calculo delta yield
   sobre la misma muestra. Captura correlacion (ambos comparten outcomes/cuotas).
   Mas sensible que bootstrap individual.

(c) Per-liga deep dive:
   Para cada liga:
     - reliability del baseline por bucket (avg_prob, freq_real, gap, N)
     - cuantos partidos caen en cada bucket Fix #6 v2
     - subset de ligas donde delta yield > 0 con CI95_lo > 0 (significativo)

Output: analisis/fix6_paired_y_per_liga.json
"""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "fix6_paired_y_per_liga.json"

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025
N_BOOTSTRAP = 2000
BUCKETS_5PP = [(i * 0.05, (i + 1) * 0.05) for i in range(20)]

FIX6_V1_BUCKETS = [
    ("1", 0.25, 0.30, -0.0853), ("1", 0.35, 0.40, +0.0319),
    ("1", 0.40, 0.45, +0.0852), ("1", 0.45, 0.50, +0.1225),
    ("1", 0.50, 0.55, +0.1853), ("1", 0.55, 0.60, +0.2134),
    ("2", 0.20, 0.25, -0.0949), ("2", 0.25, 0.30, -0.1007),
    ("2", 0.30, 0.35, -0.0850), ("2", 0.40, 0.45, +0.0632),
    ("2", 0.45, 0.50, +0.1505),
]
FIX6_V2_BUCKETS = [
    ("1", 0.25, 0.30, -0.0369), ("1", 0.30, 0.35, -0.0236),
    ("1", 0.35, 0.40, +0.0181), ("1", 0.40, 0.45, +0.0198),
    ("1", 0.50, 0.55, +0.0605), ("1", 0.55, 0.60, +0.1067),
    ("2", 0.20, 0.25, -0.0451), ("2", 0.25, 0.30, -0.0348),
    ("2", 0.30, 0.35, -0.0314), ("2", 0.45, 0.50, +0.0536),
    ("2", 0.50, 0.55, +0.1092),
]
FIX6_V3_BUCKETS = [("1", 0.30, 0.35, -0.0236)]


def aplicar_buckets(p1, px, p2, buckets):
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


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_partido(p1, px, p2, c1, cx, c2, outcome):
    """Devuelve (apostado, stake, profit). Cero si no apuesta."""
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < MARGEN_MIN:
        return False, 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0
    if prob * cuota - 1 < EV_MIN:
        return False, 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0
    if label == outcome:
        return True, stake, stake * (cuota - 1)
    return True, stake, -stake


def per_partido_metrics(rows, buckets):
    """Para cada partido devuelve (stake, profit, brier_partido, apostado_bool)."""
    out = []
    for p1, px, p2, c1, cx, c2, outcome in rows:
        q1, qx, q2 = aplicar_buckets(p1, px, p2, buckets)
        ap, stk, prof = evaluar_partido(q1, qx, q2, c1, cx, c2, outcome)
        o1 = 1 if outcome == "1" else 0
        ox = 1 if outcome == "X" else 0
        o2 = 1 if outcome == "2" else 0
        br = (q1 - o1) ** 2 + (qx - ox) ** 2 + (q2 - o2) ** 2
        out.append((stk, prof, br, ap))
    return np.array([(s, p, b, int(a)) for s, p, b, a in out])


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


def paired_bootstrap_delta_yield(arr_a, arr_c, B=N_BOOTSTRAP, seed=42):
    """Paired bootstrap: muestrea los MISMOS indices para A y C, calcula delta yield."""
    rng = np.random.default_rng(seed)
    n = len(arr_a)
    deltas = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        sa = arr_a[idx, 0].sum()
        pa = arr_a[idx, 1].sum()
        sc = arr_c[idx, 0].sum()
        pc = arr_c[idx, 1].sum()
        ya = (pa / sa * 100) if sa > 0 else 0.0
        yc = (pc / sc * 100) if sc > 0 else 0.0
        deltas[b] = yc - ya
    return {
        "delta_yield_obs": yield_de(arr_c) - yield_de(arr_a),
        "delta_yield_mean_boot": float(deltas.mean()),
        "delta_yield_ci95_lo": float(np.percentile(deltas, 2.5)),
        "delta_yield_ci95_hi": float(np.percentile(deltas, 97.5)),
        "p_delta_negativo": float((deltas < 0).mean()),
        "p_delta_positivo": float((deltas > 0).mean()),
    }


def reliability_per_outcome(rows):
    """Para cada outcome 1/X/2, devuelve dict bucket -> {n, avg_prob, freq_real, gap}."""
    rel = {"1": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0}),
           "X": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0}),
           "2": defaultdict(lambda: {"sum_prob": 0, "sum_hit": 0, "n": 0})}
    for p1, px, p2, c1, cx, c2, outcome in rows:
        for label, prob in [("1", p1), ("X", px), ("2", p2)]:
            for lo, hi in BUCKETS_5PP:
                if lo <= prob < hi:
                    hit = 1 if outcome == label else 0
                    rel[label][(lo, hi)]["sum_prob"] += prob
                    rel[label][(lo, hi)]["sum_hit"] += hit
                    rel[label][(lo, hi)]["n"] += 1
                    break
    out = {"1": {}, "X": {}, "2": {}}
    for outcome in ["1", "X", "2"]:
        for (lo, hi), d in rel[outcome].items():
            if d["n"] > 0:
                ap = d["sum_prob"] / d["n"]
                fr = d["sum_hit"] / d["n"]
                out[outcome][f"{lo:.2f}-{hi:.2f}"] = {
                    "lo": lo, "hi": hi, "n": d["n"],
                    "avg_prob": round(ap, 4),
                    "freq_real": round(fr, 4),
                    "gap": round(fr - ap, 4),
                }
    return out


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows_raw = cur.execute("""
        SELECT p.liga, p.prob_1, p.prob_x, p.prob_2,
               q.psch, q.pscd, q.psca, p.outcome
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

    rows = [(r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows_raw]
    rows_por_liga = defaultdict(list)
    for r in rows_raw:
        rows_por_liga[r[0]].append((r[1], r[2], r[3], r[4], r[5], r[6], r[7]))

    print(f"=== Fix #6 paired-bootstrap + per-liga (Pinnacle closing) ===")
    print(f"N global = {len(rows)}  ({len(rows_por_liga)} ligas)")
    print(f"Filtros: MARGEN>={MARGEN_MIN} EV>={EV_MIN} KELLY={KELLY_CAP}  B_boot={N_BOOTSTRAP}")
    print()

    # === (b) Paired bootstrap GLOBAL ===
    print("=== (b) Paired bootstrap delta yield vs A (baseline HG+Fix5) ===")
    arr_a = per_partido_metrics(rows, [])
    paired_global = {}
    print(f"{'Escenario':<28} {'dY_obs':>8} {'dY_boot':>9} {'CI95_lo':>9} {'CI95_hi':>9} "
          f"{'P(dY<0)':>9} {'P(dY>0)':>9} {'sig95':>6}")
    for nombre, buckets in [("B Fix #6 v1", FIX6_V1_BUCKETS),
                              ("C Fix #6 v2 (shrink50)", FIX6_V2_BUCKETS),
                              ("D Fix #6 v3 (selectivo)", FIX6_V3_BUCKETS)]:
        arr_x = per_partido_metrics(rows, buckets)
        res = paired_bootstrap_delta_yield(arr_a, arr_x)
        sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
        print(f"{nombre:<28} {res['delta_yield_obs']:>+8.2f} "
              f"{res['delta_yield_mean_boot']:>+9.2f} "
              f"{res['delta_yield_ci95_lo']:>+9.2f} {res['delta_yield_ci95_hi']:>+9.2f} "
              f"{res['p_delta_negativo']:>9.3f} {res['p_delta_positivo']:>9.3f} {sig:>6}")
        paired_global[nombre] = res
    print()

    # === (c) Per liga: paired bootstrap C vs A + reliability ===
    print("=== (c) Per liga - paired bootstrap (C Fix #6 v2 vs A baseline) ===")
    print(f"{'Liga':<14} {'N':>5} {'Y_A%':>7} {'Y_C%':>7} {'dY_obs':>8} "
          f"{'CI95_lo':>9} {'CI95_hi':>9} {'P(dY>0)':>9} {'sig95':>6}")
    per_liga_results = {}
    for liga in sorted(rows_por_liga.keys()):
        liga_rows = rows_por_liga[liga]
        arr_a_l = per_partido_metrics(liga_rows, [])
        arr_c_l = per_partido_metrics(liga_rows, FIX6_V2_BUCKETS)
        ya = yield_de(arr_a_l)
        yc = yield_de(arr_c_l)
        res = paired_bootstrap_delta_yield(arr_a_l, arr_c_l)
        sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
        print(f"{liga:<14} {len(liga_rows):>5} {ya:>+7.2f} {yc:>+7.2f} "
              f"{res['delta_yield_obs']:>+8.2f} "
              f"{res['delta_yield_ci95_lo']:>+9.2f} {res['delta_yield_ci95_hi']:>+9.2f} "
              f"{res['p_delta_positivo']:>9.3f} {sig:>6}")
        per_liga_results[liga] = {
            "n": len(liga_rows),
            "yield_a": ya,
            "yield_c": yc,
            "hit_a": hit_de(arr_a_l),
            "hit_c": hit_de(arr_c_l),
            "n_apost_a": int(arr_a_l[:, 3].sum()),
            "n_apost_c": int(arr_c_l[:, 3].sum()),
            "brier_a": float(arr_a_l[:, 2].mean()),
            "brier_c": float(arr_c_l[:, 2].mean()),
            "paired": res,
        }
    print()

    # === (c) Reliability del baseline per liga: identificar SESGO sistematico ===
    print("=== (c) Reliability del baseline (HG+Fix5) por liga - buckets criticos ===")
    print("Solo se muestran buckets con N>=30 que coinciden con buckets Fix #6 v2")
    print(f"{'Liga':<14} {'Outcome':<7} {'Bucket':<11} {'N':>4} {'avg_prob':>9} {'freq_real':>10} "
          f"{'gap':>8} {'corr_v2':>9} {'gap*corr':>10}")
    fix6_v2_dict = defaultdict(dict)
    for o, lo, hi, c in FIX6_V2_BUCKETS:
        fix6_v2_dict[o][f"{lo:.2f}-{hi:.2f}"] = c

    reliability_per_liga = {}
    for liga in sorted(rows_por_liga.keys()):
        rel = reliability_per_outcome(rows_por_liga[liga])
        reliability_per_liga[liga] = rel
        for outcome in ["1", "2"]:
            for bucket, info in sorted(rel[outcome].items()):
                if info["n"] < 30:
                    continue
                if bucket not in fix6_v2_dict[outcome]:
                    continue
                corr_v2 = fix6_v2_dict[outcome][bucket]
                # gap*corr_v2 > 0 => correccion va en la direccion del gap empirico de la liga
                # gap*corr_v2 < 0 => correccion va EN CONTRA del sesgo de esa liga
                alignment = info["gap"] * corr_v2
                marker = "OK" if alignment > 0 else "WRONG"
                print(f"{liga:<14} {outcome:<7} {bucket:<11} {info['n']:>4} "
                      f"{info['avg_prob']:>9.4f} {info['freq_real']:>10.4f} "
                      f"{info['gap']:>+8.4f} {corr_v2:>+9.4f} {alignment:>+10.5f} [{marker}]")
        print()

    # === Sintesis: ligas donde Fix #6 v2 va en la direccion correcta ===
    print("=== SINTESIS: ligas con paired CI95 conclusivo ===")
    ligas_pos_sig = []
    ligas_neg_sig = []
    ligas_neutras = []
    for liga, res in per_liga_results.items():
        p = res["paired"]
        if p["delta_yield_ci95_lo"] > 0:
            ligas_pos_sig.append((liga, p["delta_yield_obs"], p["delta_yield_ci95_lo"]))
        elif p["delta_yield_ci95_hi"] < 0:
            ligas_neg_sig.append((liga, p["delta_yield_obs"], p["delta_yield_ci95_hi"]))
        else:
            ligas_neutras.append((liga, p["delta_yield_obs"]))
    print(f"  Ligas con dY > 0 significativo (CI95_lo > 0): {len(ligas_pos_sig)}")
    for liga, dy, lo in ligas_pos_sig:
        print(f"    {liga}: dY={dy:+.2f}pp  CI95_lo={lo:+.2f}")
    print(f"  Ligas con dY < 0 significativo (CI95_hi < 0): {len(ligas_neg_sig)}")
    for liga, dy, hi in ligas_neg_sig:
        print(f"    {liga}: dY={dy:+.2f}pp  CI95_hi={hi:+.2f}")
    print(f"  Ligas neutras (CI95 cruza 0): {len(ligas_neutras)}")
    for liga, dy in ligas_neutras:
        print(f"    {liga}: dY={dy:+.2f}pp")

    # JSON output
    payload = {
        "n_total": len(rows),
        "filtros": {"margen_min": MARGEN_MIN, "ev_min": EV_MIN, "kelly_cap": KELLY_CAP,
                    "n_bootstrap": N_BOOTSTRAP},
        "paired_bootstrap_global": paired_global,
        "per_liga": per_liga_results,
        "reliability_per_liga": reliability_per_liga,
        "sintesis_ligas": {
            "pos_sig": [{"liga": l, "dY": dy, "ci_lo": lo} for l, dy, lo in ligas_pos_sig],
            "neg_sig": [{"liga": l, "dY": dy, "ci_hi": hi} for l, dy, hi in ligas_neg_sig],
            "neutras": [{"liga": l, "dY": dy} for l, dy in ligas_neutras],
        },
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

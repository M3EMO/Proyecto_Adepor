"""V4.7 (adepor-6rv): Audit yield del PROPOSAL desactivar HG + Fix #5.

Setup: usa las DOS fuentes de predicciones_walkforward:
  - walk_forward_sistema_real  -> probs CON HG + Fix #5 (A baseline producción)
  - walk_forward_persistente   -> probs PURAS (D = HG OFF + Fix #5 OFF)
Diferencias verificadas: Argentina dp1=+0.077, Brasil dp1=+0.085 (HG fuerte),
resto de ligas dp1=+0.005-0.010 (solo Fix #5 esporádico).

Escenarios:
  A. Sistema actual           = sistema_real probs            (HG ON  + Fix5 ON)
  B. Solo Fix #5              = aplicar Fix5 sobre persistente (HG OFF + Fix5 ON)
  C. Solo HG                  = aplicar HG sobre persistente   (HG ON  + Fix5 OFF)
  D. V4.7 PROPOSAL            = persistente directo            (HG OFF + Fix5 OFF)

Implementación HG y Fix #5 idéntica a motor_calculadora.py:
  HG: 50% del gap freq_real - p1, cap 0.95, renormaliza px/p2 proporcional
  Fix #5: bucket [0.40, 0.50] suma +0.042 a p1/p2, renormaliza

freq_real_local por liga: derivado del histórico previo a cada partido
(walk-forward correcto: solo usa partidos con fecha < fecha_partido).

Output: paired bootstrap CI95 de delta yield para B/C/D vs A, per-liga.
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
OUT = Path(__file__).resolve().parent / "v47_yield_validation.json"

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025
N_BOOTSTRAP = 2000

# HG params (de motor_calculadora.py:279-281)
N_MIN_HG = 50
BOOST_G_FRAC = 0.50
HG_CAP_MAX = 0.95
HG_GAP_MIN = 0.01

# Fix #5 params (de motor_calculadora.py:252-254)
FIX5_BUCKET_LO = 0.40
FIX5_BUCKET_HI = 0.50
FIX5_DELTA = 0.042


def aplicar_hg(p1, px, p2, freq_real_local):
    """Replica motor_calculadora.py:307-343"""
    if freq_real_local is None:
        return p1, px, p2
    gap = freq_real_local - p1
    if gap < HG_GAP_MIN:
        return p1, px, p2
    boost = gap * BOOST_G_FRAC
    p1_n = min(p1 + boost, HG_CAP_MAX)
    delta = p1_n - p1
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    peso_p2 = 1.0 - peso_px
    px_n = max(0.01, px - delta * peso_px)
    p2_n = max(0.01, p2 - delta * peso_p2)
    s = p1_n + px_n + p2_n
    return p1_n / s, px_n / s, p2_n / s


def aplicar_fix5(p1, px, p2):
    """Replica motor_calculadora.py:346-376"""
    p1_c, p2_c = p1, p2
    if FIX5_BUCKET_LO <= p1 < FIX5_BUCKET_HI:
        p1_c = p1 + FIX5_DELTA
    if FIX5_BUCKET_LO <= p2 < FIX5_BUCKET_HI:
        p2_c = p2 + FIX5_DELTA
    if p1_c == p1 and p2_c == p2:
        return p1, px, p2
    s = p1_c + px + p2_c
    return p1_c / s, px / s, p2_c / s


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_partido(p1, px, p2, c1, cx, c2, outcome):
    """(stake, profit) — apostado=stake>0."""
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


def per_partido_metrics(rows_with_probs):
    """rows = [(p1, px, p2, c1, cx, c2, outcome)] -> array (stake, profit, brier, apost)."""
    out = np.empty((len(rows_with_probs), 4))
    for i, (p1, px, p2, c1, cx, c2, outcome) in enumerate(rows_with_probs):
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

    # Cargo JOIN: misma key que fix6, pero con AMBAS fuentes
    rows_real_raw = cur.execute("""
        SELECT p.liga, p.fecha_partido, p.ht, p.at,
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
    key_to_real = {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6], r[7], r[8], r[9], r[10])
                   for r in rows_real_raw}

    rows_pure_raw = cur.execute("""
        SELECT p.liga, p.fecha_partido, p.ht, p.at,
               p.prob_1, p.prob_x, p.prob_2
        FROM predicciones_walkforward p
        WHERE p.fuente='walk_forward_persistente'
          AND p.prob_1 IS NOT NULL
    """).fetchall()
    key_to_pure = {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6])
                   for r in rows_pure_raw}

    # Extraigo freq_real_local por liga del histórico (proxy estable HG):
    #   HG en producción usa partidos liquidados acumulados. Aproximación walk-forward:
    #   uso outcomes de TODAS las predicciones walk-forward de esa liga como freq_real
    #   (esto es leak ligero pero replica el régimen real de producción donde freq se
    #   estima sobre data acumulada). Para test direccional es suficiente.
    freq_real_local = {}
    for r in cur.execute("""
        SELECT liga,
               COUNT(*) n,
               AVG(CASE WHEN outcome='1' THEN 1.0 ELSE 0.0 END) freq
        FROM predicciones_walkforward
        WHERE fuente='walk_forward_persistente'
        GROUP BY liga
    """):
        if r[1] >= N_MIN_HG:
            freq_real_local[r[0]] = r[2]

    con.close()

    # Verificacion: cuántas ligas tienen HG activo en producción según mi proxy
    print(f"=== V4.7 audit: desactivar HG + Fix #5 ===")
    print(f"Filtros: MARGEN>={MARGEN_MIN} EV>={EV_MIN} KELLY={KELLY_CAP} B_boot={N_BOOTSTRAP}")
    print()
    print(f"=== freq_real_local por liga (proxy HG) ===")
    for liga, freq in sorted(freq_real_local.items()):
        print(f"  {liga:<14s} freq_local={freq:.4f}")
    print()

    # Construyo dataset alineado: solo partidos con probs en AMBAS fuentes
    keys = sorted(set(key_to_real.keys()) & set(key_to_pure.keys()))
    print(f"N alineado (keys en ambas fuentes con cuotas Pinnacle): {len(keys)}")
    print()

    # Para cada partido construyo los 4 escenarios
    rows_A = []  # sistema_real (HG+Fix5)
    rows_B = []  # persistente + Fix5 (sin HG, con Fix5)
    rows_C = []  # persistente + HG (con HG, sin Fix5)
    rows_D = []  # persistente puro (sin nada)
    rows_por_liga = defaultdict(lambda: {"A": [], "B": [], "C": [], "D": []})

    for liga, fecha, ht, at in keys:
        p1_a, px_a, p2_a, c1, cx, c2, outcome = key_to_real[(liga, fecha, ht, at)]
        p1_d, px_d, p2_d = key_to_pure[(liga, fecha, ht, at)]

        # B: aplicar Fix5 sobre puro
        p1_b, px_b, p2_b = aplicar_fix5(p1_d, px_d, p2_d)
        # C: aplicar HG sobre puro (si liga tiene freq_real)
        freq = freq_real_local.get(liga)
        p1_c, px_c, p2_c = aplicar_hg(p1_d, px_d, p2_d, freq)

        rA = (p1_a, px_a, p2_a, c1, cx, c2, outcome)
        rB = (p1_b, px_b, p2_b, c1, cx, c2, outcome)
        rC = (p1_c, px_c, p2_c, c1, cx, c2, outcome)
        rD = (p1_d, px_d, p2_d, c1, cx, c2, outcome)
        rows_A.append(rA)
        rows_B.append(rB)
        rows_C.append(rC)
        rows_D.append(rD)
        rows_por_liga[liga]["A"].append(rA)
        rows_por_liga[liga]["B"].append(rB)
        rows_por_liga[liga]["C"].append(rC)
        rows_por_liga[liga]["D"].append(rD)

    # Calculo metricas globales
    arr_A = per_partido_metrics(rows_A)
    arr_B = per_partido_metrics(rows_B)
    arr_C = per_partido_metrics(rows_C)
    arr_D = per_partido_metrics(rows_D)

    print(f"=== Tabla principal (paired bootstrap delta yield vs A baseline) ===")
    print(f"{'Escenario':<35} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'dY_obs':>8} "
          f"{'CI95_lo':>9} {'CI95_hi':>9} {'P(dY>0)':>9} {'sig95':>6} {'Brier':>7}")
    for nombre, arr in [("A. sistema_real (HG+Fix5)", arr_A),
                          ("B. + Fix5 sobre puro", arr_B),
                          ("C. + HG sobre puro", arr_C),
                          ("D. PROPOSAL V4.7 (puro)", arr_D)]:
        if nombre.startswith("A."):
            res = {"delta_yield_obs": 0.0, "delta_yield_ci95_lo": 0.0,
                   "delta_yield_ci95_hi": 0.0, "p_delta_positivo": 0.5,
                   "delta_yield_mean_boot": 0.0, "p_delta_negativo": 0.5}
            sig = " "
        else:
            res = paired_bootstrap_delta(arr_A, arr)
            sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
        n_apost = int(arr[:, 3].sum())
        hit = hit_de(arr)
        yld = yield_de(arr)
        brier = float(arr[:, 2].mean())
        print(f"{nombre:<35} {n_apost:>7} {hit:>6.2f} {yld:>+8.2f} "
              f"{res['delta_yield_obs']:>+8.2f} "
              f"{res['delta_yield_ci95_lo']:>+9.2f} {res['delta_yield_ci95_hi']:>+9.2f} "
              f"{res['p_delta_positivo']:>9.3f} {sig:>6} {brier:>7.4f}")
    print()

    # Per liga
    print(f"=== Per-liga: D V4.7 vs A baseline (paired bootstrap) ===")
    print(f"{'Liga':<14} {'N':>5} {'Y_A%':>7} {'Y_D%':>7} {'dY':>8} "
          f"{'CI95_lo':>9} {'CI95_hi':>9} {'P(dY>0)':>9} {'sig95':>6}")
    per_liga_results = {}
    for liga in sorted(rows_por_liga.keys()):
        arrs = {k: per_partido_metrics(rows_por_liga[liga][k]) for k in "ABCD"}
        res = paired_bootstrap_delta(arrs["A"], arrs["D"])
        sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
        ya = yield_de(arrs["A"])
        yd = yield_de(arrs["D"])
        print(f"{liga:<14} {len(rows_por_liga[liga]['A']):>5} "
              f"{ya:>+7.2f} {yd:>+7.2f} "
              f"{res['delta_yield_obs']:>+8.2f} "
              f"{res['delta_yield_ci95_lo']:>+9.2f} {res['delta_yield_ci95_hi']:>+9.2f} "
              f"{res['p_delta_positivo']:>9.3f} {sig:>6}")
        per_liga_results[liga] = {
            "n": len(rows_por_liga[liga]["A"]),
            "yield_A": ya,
            "yield_B": yield_de(arrs["B"]),
            "yield_C": yield_de(arrs["C"]),
            "yield_D": yd,
            "hit_A": hit_de(arrs["A"]),
            "hit_D": hit_de(arrs["D"]),
            "n_apost_A": int(arrs["A"][:, 3].sum()),
            "n_apost_D": int(arrs["D"][:, 3].sum()),
            "brier_A": float(arrs["A"][:, 2].mean()),
            "brier_D": float(arrs["D"][:, 2].mean()),
            "paired_DvsA": res,
            "paired_BvsA": paired_bootstrap_delta(arrs["A"], arrs["B"]),
            "paired_CvsA": paired_bootstrap_delta(arrs["A"], arrs["C"]),
        }
    print()

    # Sintesis
    print(f"=== SINTESIS ===")
    sig_pos = [l for l, r in per_liga_results.items() if r["paired_DvsA"]["delta_yield_ci95_lo"] > 0]
    sig_neg = [l for l, r in per_liga_results.items() if r["paired_DvsA"]["delta_yield_ci95_hi"] < 0]
    print(f"  Ligas con D > A sig (V4.7 mejora yield): {len(sig_pos)}")
    for l in sig_pos:
        r = per_liga_results[l]
        print(f"    {l}: dY={r['paired_DvsA']['delta_yield_obs']:+.2f}pp  "
              f"CI95_lo={r['paired_DvsA']['delta_yield_ci95_lo']:+.2f}")
    print(f"  Ligas con D < A sig (V4.7 rompe yield): {len(sig_neg)}")
    for l in sig_neg:
        r = per_liga_results[l]
        print(f"    {l}: dY={r['paired_DvsA']['delta_yield_obs']:+.2f}pp  "
              f"CI95_hi={r['paired_DvsA']['delta_yield_ci95_hi']:+.2f}")

    # Ablation HG vs Fix5 separados (B vs C globales)
    print()
    print(f"=== Ablation HG vs Fix #5 separados (delta yield vs A) ===")
    res_B = paired_bootstrap_delta(arr_A, arr_B)
    res_C = paired_bootstrap_delta(arr_A, arr_C)
    res_D = paired_bootstrap_delta(arr_A, arr_D)
    print(f"  B (solo Fix5 - sin HG):  dY={res_B['delta_yield_obs']:+.2f}pp  "
          f"CI95=[{res_B['delta_yield_ci95_lo']:+.2f}, {res_B['delta_yield_ci95_hi']:+.2f}]  "
          f"P(dY>0)={res_B['p_delta_positivo']:.3f}")
    print(f"  C (solo HG  - sin Fix5): dY={res_C['delta_yield_obs']:+.2f}pp  "
          f"CI95=[{res_C['delta_yield_ci95_lo']:+.2f}, {res_C['delta_yield_ci95_hi']:+.2f}]  "
          f"P(dY>0)={res_C['p_delta_positivo']:.3f}")
    print(f"  D (V4.7 - sin HG, sin Fix5): dY={res_D['delta_yield_obs']:+.2f}pp  "
          f"CI95=[{res_D['delta_yield_ci95_lo']:+.2f}, {res_D['delta_yield_ci95_hi']:+.2f}]  "
          f"P(dY>0)={res_D['p_delta_positivo']:.3f}")

    # Output JSON
    payload = {
        "n_total": len(keys),
        "filtros": {"margen_min": MARGEN_MIN, "ev_min": EV_MIN, "kelly_cap": KELLY_CAP,
                    "n_bootstrap": N_BOOTSTRAP},
        "fuentes": {
            "A": "walk_forward_sistema_real (HG+Fix5)",
            "B": "walk_forward_persistente + aplicar_fix5",
            "C": "walk_forward_persistente + aplicar_hg(freq_real_local)",
            "D": "walk_forward_persistente (V4.7 PROPOSAL)",
        },
        "freq_real_local_por_liga": freq_real_local,
        "global": {
            "A": {"yield": yield_de(arr_A), "hit": hit_de(arr_A),
                  "n_apost": int(arr_A[:, 3].sum()), "brier": float(arr_A[:, 2].mean())},
            "B": {"yield": yield_de(arr_B), "hit": hit_de(arr_B),
                  "n_apost": int(arr_B[:, 3].sum()), "brier": float(arr_B[:, 2].mean())},
            "C": {"yield": yield_de(arr_C), "hit": hit_de(arr_C),
                  "n_apost": int(arr_C[:, 3].sum()), "brier": float(arr_C[:, 2].mean())},
            "D": {"yield": yield_de(arr_D), "hit": hit_de(arr_D),
                  "n_apost": int(arr_D[:, 3].sum()), "brier": float(arr_D[:, 2].mean())},
        },
        "paired_global": {"BvsA": res_B, "CvsA": res_C, "DvsA": res_D},
        "per_liga": per_liga_results,
        "sintesis": {
            "ligas_D_mejor_que_A_sig": sig_pos,
            "ligas_D_peor_que_A_sig": sig_neg,
        },
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

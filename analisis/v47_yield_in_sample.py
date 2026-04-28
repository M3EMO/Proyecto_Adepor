"""V4.7 audit IN-SAMPLE (desde 2026-03-16): 4 escenarios sobre partidos_backtest reales.

Diferencia con v47_yield_validation.py:
  - OOS test: walk_forward 2022-2024 sobre Pinnacle closing (probs aprox). N=7,867.
  - IN-SAMPLE test (este): partidos_backtest 2026-03-16 a 2026-04-27 con cuotas
    REALES del mercado que el motor uso para apostar. N=376.

Escenarios (mismos que OOS):
  A. Sistema actual           = partidos_backtest.prob_1/x/2 (HG+Fix5 aplicado)
  B. Solo Fix5 sobre puro     = aplicar Fix5 sobre Dixon-Coles puro
  C. Solo HG sobre puro       = aplicar HG sobre Dixon-Coles puro
  D. PROPOSAL V4.7 (puro)     = Dixon-Coles puro sin parches

Probs puras (D): re-calcular desde xG + rho_liga via Dixon-Coles tau (igual a
fix6_v3_ablation_selectivo.py). HG usa freq_real_local CUMULATIVA hasta cada
fecha (walk-forward correcto sobre el histórico previo + backtest pre-2026-03-16).
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
OUT = Path(__file__).resolve().parent / "v47_yield_in_sample.json"

FECHA_DESDE = "2026-03-16"

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


def poisson(k, lam):
    if lam <= 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


def tau_dc(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    if i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    if i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    if i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def calcular_probs_puras(xg_l, xg_v, rho):
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    s = p1 + px + p2
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1 / s, px / s, p2 / s


def aplicar_hg(p1, px, p2, freq_real):
    if freq_real is None:
        return p1, px, p2
    gap = freq_real - p1
    if gap < HG_GAP_MIN:
        return p1, px, p2
    boost = gap * BOOST_G_FRAC
    p1_n = min(p1 + boost, HG_CAP_MAX)
    delta = p1_n - p1
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    px_n = max(0.01, px - delta * peso_px)
    p2_n = max(0.01, p2 - delta * (1.0 - peso_px))
    s = p1_n + px_n + p2_n
    return p1_n / s, px_n / s, p2_n / s


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

    # rho por liga
    rho_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    # freq_real_local por liga: histórico externo + backtest pre-FECHA_DESDE (data
    # accesible al motor en el momento de cada decisión durante in-sample)
    freq_real_local = {}
    for r in cur.execute(f"""
        SELECT pais,
               COUNT(*) n,
               AVG(CASE WHEN gl > gv THEN 1.0 ELSE 0.0 END) freq
        FROM (
            SELECT liga AS pais, hg AS gl, ag AS gv FROM partidos_historico_externo
            WHERE hg IS NOT NULL AND ag IS NOT NULL
            UNION ALL
            SELECT pais, goles_l AS gl, goles_v AS gv FROM partidos_backtest
            WHERE estado='Liquidado' AND fecha < '{FECHA_DESDE}'
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        )
        GROUP BY pais
    """):
        if r[1] >= N_MIN_HG:
            freq_real_local[r[0]] = r[2]

    print(f"=== V4.7 audit IN-SAMPLE (partidos_backtest desde {FECHA_DESDE}) ===")
    print(f"Filtros: MARGEN>={MARGEN_MIN} EV>={EV_MIN} KELLY={KELLY_CAP} B_boot={N_BOOTSTRAP}")
    print()
    print(f"=== freq_real_local (cumulativa pre-{FECHA_DESDE}) ===")
    for liga, freq in sorted(freq_real_local.items()):
        print(f"  {liga:<14s} freq={freq:.4f}")
    print()

    # Cargar partidos in-sample
    rows_raw = cur.execute(f"""
        SELECT fecha, pais, local, visita,
               xg_local, xg_visita,
               prob_1, prob_x, prob_2,
               cuota_1, cuota_x, cuota_2,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE fecha >= '{FECHA_DESDE}'
          AND estado='Liquidado'
          AND xg_local > 0 AND xg_visita > 0
          AND cuota_1 > 0 AND cuota_x > 0 AND cuota_2 > 0
          AND prob_1 IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """).fetchall()
    con.close()

    print(f"N partidos in-sample con xG + cuotas + probs: {len(rows_raw)}")
    print()

    # Construir 4 escenarios por partido
    rows_A, rows_B, rows_C, rows_D = [], [], [], []
    rows_por_liga = defaultdict(lambda: {"A": [], "B": [], "C": [], "D": []})

    for fecha, pais, local, visita, xg_l, xg_v, p1_a, px_a, p2_a, c1, cx, c2, gl, gv in rows_raw:
        outcome = "1" if gl > gv else ("X" if gl == gv else "2")

        # D: Dixon-Coles puro
        rho = rho_liga.get(pais, -0.09)
        p1_d, px_d, p2_d = calcular_probs_puras(xg_l, xg_v, rho)

        # B: Fix5 sobre puro
        p1_b, px_b, p2_b = aplicar_fix5(p1_d, px_d, p2_d)
        # C: HG sobre puro
        freq = freq_real_local.get(pais)
        p1_c, px_c, p2_c = aplicar_hg(p1_d, px_d, p2_d, freq)

        rA = (p1_a, px_a, p2_a, c1, cx, c2, outcome)
        rB = (p1_b, px_b, p2_b, c1, cx, c2, outcome)
        rC = (p1_c, px_c, p2_c, c1, cx, c2, outcome)
        rD = (p1_d, px_d, p2_d, c1, cx, c2, outcome)
        rows_A.append(rA); rows_B.append(rB); rows_C.append(rC); rows_D.append(rD)
        rows_por_liga[pais]["A"].append(rA)
        rows_por_liga[pais]["B"].append(rB)
        rows_por_liga[pais]["C"].append(rC)
        rows_por_liga[pais]["D"].append(rD)

    arr_A = per_partido_metrics(rows_A)
    arr_B = per_partido_metrics(rows_B)
    arr_C = per_partido_metrics(rows_C)
    arr_D = per_partido_metrics(rows_D)

    print(f"=== Tabla principal IN-SAMPLE (N={len(rows_A)}) ===")
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

    # Per liga (solo ligas con N>=10 para que tenga sentido)
    print(f"=== Per-liga IN-SAMPLE: D (V4.7) vs A baseline ===")
    print(f"{'Liga':<14} {'N':>4} {'Y_A%':>7} {'Y_D%':>7} {'dY':>8} "
          f"{'CI95_lo':>9} {'CI95_hi':>9} {'P(dY>0)':>9} {'sig95':>6}")
    per_liga_results = {}
    for liga in sorted(rows_por_liga.keys()):
        n_liga = len(rows_por_liga[liga]["A"])
        if n_liga < 10:
            continue
        arrs = {k: per_partido_metrics(rows_por_liga[liga][k]) for k in "ABCD"}
        res = paired_bootstrap_delta(arrs["A"], arrs["D"])
        sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
        ya = yield_de(arrs["A"])
        yd = yield_de(arrs["D"])
        print(f"{liga:<14} {n_liga:>4} {ya:>+7.2f} {yd:>+7.2f} "
              f"{res['delta_yield_obs']:>+8.2f} "
              f"{res['delta_yield_ci95_lo']:>+9.2f} {res['delta_yield_ci95_hi']:>+9.2f} "
              f"{res['p_delta_positivo']:>9.3f} {sig:>6}")
        per_liga_results[liga] = {
            "n": n_liga,
            "yield_A": ya, "yield_D": yd,
            "yield_B": yield_de(arrs["B"]), "yield_C": yield_de(arrs["C"]),
            "n_apost_A": int(arrs["A"][:, 3].sum()),
            "n_apost_D": int(arrs["D"][:, 3].sum()),
            "paired_DvsA": res,
        }

    print()
    print(f"=== Ablation HG vs Fix #5 separados ===")
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

    payload = {
        "n_total": len(rows_A),
        "fecha_desde": FECHA_DESDE,
        "filtros": {"margen_min": MARGEN_MIN, "ev_min": EV_MIN, "kelly_cap": KELLY_CAP,
                    "n_bootstrap": N_BOOTSTRAP},
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
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

"""Ablation COMPLETA — desactivar cada filtro individualmente y en conjunto.

Filtros que probamos:
  Decisionales (gates):
    FLOOR_PROB_MIN = 0.33 (prob minima)
    MARGEN_PREDICTIVO_1X2 = 0.05 (margen top1-top2)
    EV_MIN = 0.03 (EV minimo)
    KELLY_CAP = 0.025 (max stake fraction)

  Correcciones (sumadores a probs):
    HG (boost local Argentina/Brasil)
    Fix #5 (+0.042 bucket 40-50%)

Versiones:
  V_actual         - status quo (todos activos)
  V_sin_FLOOR      - desactiva FLOOR_PROB_MIN (acepta prob<33%)
  V_sin_MARGEN     - desactiva MARGEN (acepta margen<5%)
  V_sin_EV         - desactiva EV_MIN (acepta EV<3%)
  V_sin_KELLY_CAP  - desactiva cap stake (Kelly puro)
  V_sin_FIX5       - desactiva Fix #5
  V_sin_HG         - desactiva HG
  V_sin_FIX5_HG    - sin las 2 correcciones (puro Poisson)
  V_sin_GATES      - sin FLOOR + sin MARGEN + sin EV (todos los filtros decisionales)
  V_NADA           - sin TODOS los filtros (incluye correcciones)
"""
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

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
RANGO_POISSON = 10
N_MIN_HG = 50


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
    boost = (freq_real - p1) * 0.5
    p1_new = min(p1 + boost, 0.95)
    rest = px + p2
    if rest <= 0:
        return p1_new, 0.5*(1-p1_new), 0.5*(1-p1_new)
    target = 1 - p1_new
    return p1_new, px*target/rest, p2*target/rest


def aplicar_fix5(p1, px, p2):
    p1_c, p2_c = p1, p2
    if 0.40 <= p1 < 0.50:
        p1_c = p1 + 0.042
    if 0.40 <= p2 < 0.50:
        p2_c = p2 + 0.042
    s = p1_c + px + p2_c
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1_c/s, px/s, p2_c/s


def kelly_fraction(p, cuota, cap=0.025):
    if cuota <= 1.0 or p <= 0:
        return 0
    f = p - (1 - p) / (cuota - 1)
    if cap is None:
        return max(0, f)
    return max(0, min(f, cap))


def simular_apuesta(p1, px, p2, c1, cx, c2, config):
    """config: dict con flags de filtros activos."""
    floor = config.get("floor", 0.33) if config.get("use_floor", True) else 0.0
    margen_min = config.get("margen_min", 0.05) if config.get("use_margen", True) else 0.0
    ev_min = config.get("ev_min", 0.03) if config.get("use_ev", True) else -10.0
    kelly_cap = config.get("kelly_cap", 0.025) if config.get("use_kelly_cap", True) else None

    sorted_p = sorted([p1, px, p2], reverse=True)
    margen = sorted_p[0] - sorted_p[1]
    if margen < margen_min:
        return None, 0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    argmax_label, argmax_prob, argmax_cuota = max(options, key=lambda x: x[1])
    if argmax_prob < floor:
        return None, 0
    if not argmax_cuota or argmax_cuota <= 1.0:
        return None, 0
    ev = argmax_prob * argmax_cuota - 1
    if ev < ev_min:
        return None, 0
    return argmax_label, kelly_fraction(argmax_prob, argmax_cuota, cap=kelly_cap)


def evaluar(rows, freq_per_liga, rho_per_liga, config):
    sum_profit, sum_stake, n_apost, n_gano = 0, 0, 0, 0
    n_loc = n_emp = n_vis = 0
    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv = r
        rho = rho_per_liga.get(pais, -0.09)
        p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)
        if config.get("use_hg", True):
            freq = freq_per_liga.get(pais)
            if freq is not None:
                p1, px, p2 = aplicar_hg(p1, px, p2, freq)
        if config.get("use_fix5", True):
            p1, px, p2 = aplicar_fix5(p1, px, p2)

        outcome = "1" if gl > gv else ("X" if gl == gv else "2")
        ap, stake = simular_apuesta(p1, px, p2, c1, cx, c2, config)
        if ap:
            cuota = {"1": c1, "X": cx, "2": c2}[ap]
            sum_stake += stake
            n_apost += 1
            if ap == "1": n_loc += 1
            elif ap == "X": n_emp += 1
            else: n_vis += 1
            if ap == outcome:
                sum_profit += stake * (cuota - 1)
                n_gano += 1
            else:
                sum_profit -= stake
    return {
        "n_apost": n_apost, "n_gano": n_gano,
        "n_loc": n_loc, "n_emp": n_emp, "n_vis": n_vis,
        "stake": sum_stake, "profit": sum_profit,
        "yield": (sum_profit/sum_stake*100) if sum_stake > 0 else 0,
        "hit": (n_gano/n_apost*100) if n_apost > 0 else 0,
        "pct_local": (n_loc/n_apost*100) if n_apost > 0 else 0,
        "stake_avg": (sum_stake/n_apost) if n_apost > 0 else 0,
    }


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
    print(f"=== ABLATION COMPLETA — N={n_total} ===\n")

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

    # Configs
    base_actual = {
        "use_floor": True, "use_margen": True, "use_ev": True, "use_kelly_cap": True,
        "use_hg": True, "use_fix5": True,
    }
    versions = {
        "V_actual": dict(base_actual),
        # Filtros decisionales individualmente desactivados
        "V_sin_FLOOR": {**base_actual, "use_floor": False},
        "V_sin_MARGEN": {**base_actual, "use_margen": False},
        "V_sin_EV": {**base_actual, "use_ev": False},
        "V_sin_KELLY_CAP": {**base_actual, "use_kelly_cap": False},
        # Correcciones individualmente desactivadas
        "V_sin_FIX5": {**base_actual, "use_fix5": False},
        "V_sin_HG": {**base_actual, "use_hg": False},
        # Sin las 2 correcciones
        "V_sin_FIX5_HG": {**base_actual, "use_fix5": False, "use_hg": False},
        # Sin gates de decision
        "V_sin_GATES": {**base_actual, "use_floor": False, "use_margen": False, "use_ev": False},
        # Sin TODO
        "V_NADA": {
            "use_floor": False, "use_margen": False, "use_ev": False, "use_kelly_cap": False,
            "use_hg": False, "use_fix5": False,
        },
    }

    print(f"{'Version':<20} {'N_apost':>8} {'%loc':>5} {'%emp':>5} {'%vis':>5} "
          f"{'Hit%':>7} {'Profit':>9} {'Stake':>8} {'Yield%':>9}")
    print("-" * 92)
    results = {}
    for label, cfg in versions.items():
        # 5-fold CV
        np.random.seed(42)
        idx = list(range(n_total))
        np.random.shuffle(idx)
        K = 5
        fs = n_total // K
        agg = {"n_apost": 0, "n_gano": 0, "n_loc": 0, "n_emp": 0, "n_vis": 0, "stake": 0, "profit": 0}
        for f in range(K):
            test_set = set(idx[f*fs:(f+1)*fs])
            test_rows = [rows[j] for j in idx if j in test_set]
            r = evaluar(test_rows, freq_per_liga, rho_per_liga, cfg)
            for k in agg:
                agg[k] += r[k]
        agg["yield"] = (agg["profit"]/agg["stake"]*100) if agg["stake"] > 0 else 0
        agg["hit"] = (agg["n_gano"]/agg["n_apost"]*100) if agg["n_apost"] > 0 else 0
        agg["pct_local"] = (agg["n_loc"]/agg["n_apost"]*100) if agg["n_apost"] > 0 else 0
        agg["pct_emp"] = (agg["n_emp"]/agg["n_apost"]*100) if agg["n_apost"] > 0 else 0
        agg["pct_vis"] = (agg["n_vis"]/agg["n_apost"]*100) if agg["n_apost"] > 0 else 0
        results[label] = agg
        print(f"{label:<20} {agg['n_apost']:>8} {agg['pct_local']:>5.1f} {agg['pct_emp']:>5.1f} {agg['pct_vis']:>5.1f} "
              f"{agg['hit']:>7.2f} {agg['profit']:>+9.4f} {agg['stake']:>8.4f} {agg['yield']:>+9.2f}")

    print()
    print("=== INSIGHTS ===")
    actual = results["V_actual"]
    base_yield = actual["yield"]
    print(f"  V_actual baseline: yield={base_yield:+.2f}%, N={actual['n_apost']}, hit={actual['hit']:.2f}%")
    print()
    print(f"  Top 3 versions por yield:")
    sorted_v = sorted(results.items(), key=lambda x: -x[1]["yield"])
    for i, (label, r) in enumerate(sorted_v[:3]):
        delta = r["yield"] - base_yield
        print(f"    {i+1}. {label:<20} yield={r['yield']:+.2f}% (Δ {delta:+.2f}pp), "
              f"N={r['n_apost']}, hit={r['hit']:.2f}%, %loc={r['pct_local']:.1f}%")

    print()
    print(f"  Comparativa con V_actual (Δyield, Δapost):")
    for label, r in results.items():
        if label == "V_actual": continue
        d_y = r["yield"] - base_yield
        d_n = r["n_apost"] - actual["n_apost"]
        flag = "🟢" if d_y > 5 else ("🟡" if d_y > -5 else "🔴")
        print(f"    {flag} {label:<22} ΔYield={d_y:+.2f}pp  ΔN={d_n:+d}")


if __name__ == "__main__":
    main()

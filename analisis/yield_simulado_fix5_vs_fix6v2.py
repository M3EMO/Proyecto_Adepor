"""C5 PROPOSAL adepor-u4z: yield simulado Fix #5 actual vs Fix #6 v2.

Procedimiento:
  1. Cargar Liquidados con cuotas + xg + rho
  2. Re-computar probs_base (sin HG ni Fix #5/6) via Poisson + tau Dixon-Coles
  3. Aplicar 2 cadenas:
     V_A: probs_base -> HG (si liga aplica) -> Fix #5 (bucket 40-50% +0.042)
     V_B: probs_base -> HG (si liga aplica) -> Fix #6 v2 (11 buckets, shrink 50%)
  4. Para cada version, simular apuesta:
     - argmax de las 3 probs
     - Filtro: margen >= 0.05 (V4.5)
     - Filtro: EV >= 3% (escalado simple)
     - Stake Kelly capado 2.5%
  5. Yield = (sum profit) / (sum stake)

Comparar yield_A vs yield_B.
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "yield_simulado_fix5_vs_fix6v2.json"

RANGO_POISSON = 10
N_MIN_HG = 50
BOOST_G_FRACCION = 0.50
HG_CAP_MAX = 0.95
CALIBRACION_BUCKET_MIN = 0.40
CALIBRACION_BUCKET_MAX = 0.50
CALIBRACION_CORRECCION = 0.042
MARGEN_MIN = 0.05  # V4.5
KELLY_CAP = 0.025  # 2.5%
EV_MIN = 0.03      # 3% threshold simple


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
    boost = (freq_real - p1) * BOOST_G_FRACCION
    p1_new = min(p1 + boost, HG_CAP_MAX)
    rest_old = px + p2
    if rest_old <= 0:
        return p1_new, 0.5 * (1 - p1_new), 0.5 * (1 - p1_new)
    target_rest = 1 - p1_new
    return p1_new, px * target_rest / rest_old, p2 * target_rest / rest_old


def aplicar_fix5(p1, px, p2):
    p1_c, p2_c = p1, p2
    if CALIBRACION_BUCKET_MIN <= p1 < CALIBRACION_BUCKET_MAX:
        p1_c = p1 + CALIBRACION_CORRECCION
    if CALIBRACION_BUCKET_MIN <= p2 < CALIBRACION_BUCKET_MAX:
        p2_c = p2 + CALIBRACION_CORRECCION
    s = p1_c + px + p2_c
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1_c / s, px / s, p2_c / s


# Fix #6 v2 correcciones (del JSON derivado en C4)
FIX6_V2 = {
    "1": [
        (0.25, 0.30, -0.0369),
        (0.30, 0.35, -0.0236),
        (0.35, 0.40, +0.0181),
        (0.40, 0.45, +0.0198),
        (0.50, 0.55, +0.0605),
        (0.55, 0.60, +0.1067),
    ],
    "X": [],
    "2": [
        (0.20, 0.25, -0.0451),
        (0.25, 0.30, -0.0348),
        (0.30, 0.35, -0.0314),
        (0.45, 0.50, +0.0536),
        (0.50, 0.55, +0.1092),
    ],
}


def aplicar_fix6_v2(p1, px, p2):
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for lo, hi, corr in FIX6_V2[outcome]:
            if lo <= prob < hi:
                p_corr[outcome] = max(0.001, prob + corr)
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"] / s, p_corr["X"] / s, p_corr["2"] / s


def kelly_fraction(p, cuota):
    """Kelly fraction: f = (p*(c-1) - (1-p)) / (c-1) = p - (1-p)/(c-1)"""
    if cuota <= 1.0 or p <= 0:
        return 0
    f = p - (1 - p) / (cuota - 1)
    return max(0, min(f, KELLY_CAP))


def ev(prob, cuota):
    """Expected value: prob * cuota - 1."""
    return prob * cuota - 1


def simular_apuesta(p1, px, p2, c1, cx, c2):
    """Aplica filtros del motor (margen + EV) y retorna (apuesta, stake_frac, ev_apostado).
    apuesta: '1', 'X', '2', None.
    """
    sorted_p = sorted([p1, px, p2], reverse=True)
    margen = sorted_p[0] - sorted_p[1]
    if margen < MARGEN_MIN:
        return None, 0, 0

    # Argmax
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    argmax_label, argmax_prob, argmax_cuota = max(options, key=lambda x: x[1])
    if not argmax_cuota or argmax_cuota <= 1.0:
        return None, 0, 0

    ev_argmax = ev(argmax_prob, argmax_cuota)
    if ev_argmax < EV_MIN:
        return None, 0, 0

    stake_frac = kelly_fraction(argmax_prob, argmax_cuota)
    return argmax_label, stake_frac, ev_argmax


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
    print(f"=== Yield simulado A/B Fix #5 vs Fix #6 v2 — N Liquidados con cuotas: {n_total} ===\n")

    # freq_local_real per liga (HG)
    freq_real_per_liga = {}
    for r in cur.execute("""
        SELECT pais, COUNT(*) AS n,
               AVG(CASE WHEN goles_l > goles_v THEN 1.0 ELSE 0.0 END) AS freq
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        GROUP BY pais
    """):
        if r[1] >= N_MIN_HG:
            freq_real_per_liga[r[0]] = r[2]

    # rho per liga
    rho_per_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    con.close()

    # Simular cada partido
    sum_profit_a, sum_stake_a, n_apostados_a, n_gano_a = 0, 0, 0, 0
    sum_profit_b, sum_stake_b, n_apostados_b, n_gano_b = 0, 0, 0, 0
    coincidencias = 0  # picks que coinciden A vs B
    flips = 0  # picks distintos A vs B

    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv = r
        rho = rho_per_liga.get(pais, -0.09)

        # Probs base
        p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)
        # HG si liga aplica
        freq_real = freq_real_per_liga.get(pais)
        if freq_real is not None:
            p1, px, p2 = aplicar_hg(p1, px, p2, freq_real)

        # V_A: + Fix #5
        p1_a, px_a, p2_a = aplicar_fix5(p1, px, p2)
        # V_B: + Fix #6 v2 (sin Fix #5)
        p1_b, px_b, p2_b = aplicar_fix6_v2(p1, px, p2)

        # Resultado real
        if gl > gv:
            outcome = "1"
        elif gl == gv:
            outcome = "X"
        else:
            outcome = "2"

        # Apuesta A
        ap_a, stake_a, ev_a = simular_apuesta(p1_a, px_a, p2_a, c1, cx, c2)
        # Apuesta B
        ap_b, stake_b, ev_b = simular_apuesta(p1_b, px_b, p2_b, c1, cx, c2)

        if ap_a == ap_b:
            coincidencias += 1
        else:
            flips += 1

        # Profit A
        if ap_a:
            cuota_apostada = {"1": c1, "X": cx, "2": c2}[ap_a]
            stake_real = stake_a  # fraccion bankroll, comparable
            sum_stake_a += stake_real
            n_apostados_a += 1
            if ap_a == outcome:
                sum_profit_a += stake_real * (cuota_apostada - 1)
                n_gano_a += 1
            else:
                sum_profit_a -= stake_real
        # Profit B
        if ap_b:
            cuota_apostada = {"1": c1, "X": cx, "2": c2}[ap_b]
            stake_real = stake_b
            sum_stake_b += stake_real
            n_apostados_b += 1
            if ap_b == outcome:
                sum_profit_b += stake_real * (cuota_apostada - 1)
                n_gano_b += 1
            else:
                sum_profit_b -= stake_real

    # Aggregate
    yield_a = (sum_profit_a / sum_stake_a * 100) if sum_stake_a > 0 else 0
    yield_b = (sum_profit_b / sum_stake_b * 100) if sum_stake_b > 0 else 0
    hit_a = (n_gano_a / n_apostados_a * 100) if n_apostados_a > 0 else 0
    hit_b = (n_gano_b / n_apostados_b * 100) if n_apostados_b > 0 else 0

    print(f"=== RESULTADOS POOL ===")
    print(f"  Liquidados con cuotas: {n_total}")
    print(f"  Coincidencias picks A vs B: {coincidencias} ({100*coincidencias/n_total:.1f}%)")
    print(f"  Flips A vs B:               {flips} ({100*flips/n_total:.1f}%)")
    print()
    print(f"  V_A (Fix #5 actual):")
    print(f"    Apuestas:    {n_apostados_a}")
    print(f"    Ganados:     {n_gano_a} ({hit_a:.2f}%)")
    print(f"    Stake total: {sum_stake_a:.4f}")
    print(f"    Profit:      {sum_profit_a:+.4f}")
    print(f"    Yield:       {yield_a:+.2f}%")
    print()
    print(f"  V_B (Fix #6 v2 shrink 50%):")
    print(f"    Apuestas:    {n_apostados_b}")
    print(f"    Ganados:     {n_gano_b} ({hit_b:.2f}%)")
    print(f"    Stake total: {sum_stake_b:.4f}")
    print(f"    Profit:      {sum_profit_b:+.4f}")
    print(f"    Yield:       {yield_b:+.2f}%")
    print()
    print(f"  Δ Yield: {yield_b - yield_a:+.2f}pp  ({'MEJORA' if yield_b > yield_a else 'EMPEORA'})")
    print(f"  Δ Apuestas: {n_apostados_b - n_apostados_a:+d}")
    print(f"  Δ Hit rate apostado: {hit_b - hit_a:+.2f}pp")

    OUT.write_text(json.dumps({
        "n_total": n_total,
        "coincidencias": coincidencias,
        "flips": flips,
        "v_a_fix5": {
            "n_apostados": n_apostados_a, "n_gano": n_gano_a,
            "hit_rate_pct": hit_a, "stake_total": sum_stake_a,
            "profit": sum_profit_a, "yield_pct": yield_a,
        },
        "v_b_fix6v2": {
            "n_apostados": n_apostados_b, "n_gano": n_gano_b,
            "hit_rate_pct": hit_b, "stake_total": sum_stake_b,
            "profit": sum_profit_b, "yield_pct": yield_b,
        },
        "delta_yield_pct": yield_b - yield_a,
        "delta_apuestas": n_apostados_b - n_apostados_a,
        "delta_hit_rate_pp": hit_b - hit_a,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

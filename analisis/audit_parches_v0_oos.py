"""[adepor-2yo] Audit OOS parches del motor V0: Hallazgo G + Fix #5.

Variantes evaluadas:
  V0_raw       = Poisson DC + xG legacy (sin parches)
  V0_HG        = + Hallazgo G (boost p1 segun freq_real_local liga, gap >= 0.01, factor 0.50)
  V0_F5        = + Fix #5 (si p1 o p2 en [0.40, 0.50): suma 0.042, renormaliza)
  V0_HG_F5     = + ambos (motor V0 production sin gamma_display)
  V0_HG_F5_X   = ambos + APUESTA_EMPATE_PERMITIDA = True (deja a X ser argmax)

freq_real_local por liga calibrada sobre TRAIN (2021-2023).
Test OOS 2024 con EMA legacy congelado al 2023-12-31.
"""
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import limpiar_texto

DB = ROOT / "fondo_quant.db"
LIGAS = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
         'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
TRAIN_TEMP = {2021, 2022, 2023}
TEST_TEMP = {2024}
ALFA = 0.15

# Parches del motor (defaults Reglas_IA.txt)
N_MIN_HG = 50            # Hallazgo G activo si N >= 50 partidos liquidados
BOOST_G_FRAC = 0.50
CAL_BUCKET_MIN = 0.40
CAL_BUCKET_MAX = 0.50
CAL_CORRECCION = 0.042


# ============================================================================
# UTILIDADES
# ============================================================================

def poisson_pmf(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError): return 0.0


def tau_dc(i, j, l, v, rho):
    if i == 0 and j == 0: return 1 - l*v*rho
    if i == 0 and j == 1: return 1 + l*rho
    if i == 1 and j == 0: return 1 + v*rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho, max_g=10):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def aplicar_hallazgo_g(p1, px, p2, freq_real, n_liga):
    """[Reproduce motor_calculadora.py:307] Boost p1 si modelo subestima local."""
    if n_liga < N_MIN_HG:
        return p1, px, p2
    gap = freq_real - p1
    if gap < 0.01:
        return p1, px, p2
    boost = gap * BOOST_G_FRAC
    p1_n = min(p1 + boost, 0.95)
    delta = p1_n - p1
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    peso_p2 = 1.0 - peso_px
    px_n = max(0.01, px - delta * peso_px)
    p2_n = max(0.01, p2 - delta * peso_p2)
    total = p1_n + px_n + p2_n
    return p1_n / total, px_n / total, p2_n / total


def aplicar_fix5(p1, px, p2):
    """[Reproduce motor_calculadora.py:346] Boost local/visita si en bucket [0.40, 0.50)."""
    p1_c, p2_c = p1, p2
    if CAL_BUCKET_MIN <= p1 < CAL_BUCKET_MAX:
        p1_c = p1 + CAL_CORRECCION
    if CAL_BUCKET_MIN <= p2 < CAL_BUCKET_MAX:
        p2_c = p2 + CAL_CORRECCION
    if p1_c == p1 and p2_c == p2:
        return p1, px, p2
    total = p1_c + px + p2_c
    if total <= 0:
        return p1, px, p2
    return p1_c / total, px / total, p2_c / total


def calc_xg_legacy(sot, shots, corners, goles, cc=0.03):
    """Manifesto §II.A: SoT*0.30 + shots_off*0.04 + corners*coef_corner."""
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    xg_calc = sot * 0.30 + shots_off * 0.04 + corners * cc
    if xg_calc == 0 and goles > 0: return goles
    return xg_calc * 0.70 + goles * 0.30


def ajustar(xg, gf, gc):
    diff = (gf or 0) - (gc or 0)
    if diff > 0: return xg * min(1.0 + 0.08 * math.log(1 + diff), 1.20)
    if diff < 0: return xg * max(1.0 - 0.05 * math.log(1 + abs(diff)), 0.80)
    return xg


def amax_full(p1, px, p2, permitir_X=False):
    """argmax sobre 1, X, 2. Si permitir_X=False, X queda excluido."""
    if not permitir_X:
        return "1" if p1 >= p2 else "2"
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def real_o(hg, ag): return "1" if hg > ag else ("2" if hg < ag else "X")


def brier(p1, px, p2, r):
    return ((p1 - (1 if r == "1" else 0))**2 +
            (px - (1 if r == "X" else 0))**2 +
            (p2 - (1 if r == "2" else 0))**2)


# ============================================================================
# MAIN
# ============================================================================

def main():
    con = sqlite3.connect(DB); cur = con.cursor()
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_leg_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}

    print("=" * 95)
    print("AUDIT PARCHES V0 OOS  Train 2021-23 / Test 2024")
    print("Variantes: V0_raw | V0_HG | V0_F5 | V0_HG_F5 | V0_HG_F5_X (con APUESTA_EMPATE_PERMITIDA=True)")
    print("=" * 95)

    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha ASC
    """.format(','.join(['?']*len(LIGAS))), LIGAS).fetchall()

    train = [r for r in rows if r[1] in TRAIN_TEMP]
    test = [r for r in rows if r[1] in TEST_TEMP]
    print(f"Train: {len(train)}  Test: {len(test)}\n")

    # === Calibrar freq_real_local por liga sobre TRAIN ===
    n_liga = defaultdict(int)
    n_loc_win = defaultdict(int)
    for liga, _, _, _, _, hg, ag, *_ in train:
        n_liga[liga] += 1
        if hg > ag: n_loc_win[liga] += 1
    freq_real_pl = {}
    print("freq_real_local TRAIN por liga:")
    for liga in LIGAS:
        n = n_liga[liga]
        f = n_loc_win[liga] / n if n else 0
        freq_real_pl[liga] = f
        print(f"  {liga:<13s} N={n:>4d}  freq_local={f:.3f}")
    print()

    # === EMA legacy train-only (xG legacy + score effects) ===
    print("Construyendo EMA legacy train-only...")
    ema_leg = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None, 'n_h': 0, 'n_a': 0})
    for liga, _, _, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        cc = cc_leg_pl.get(liga, 0.02)
        xg_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc), hg, ag)
        xg_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc), ag, hg)
        e_l = ema_leg[ht_n]; e_v = ema_leg[at_n]
        if e_l['fh'] is None:
            e_l['fh'] = xg_l; e_l['ch'] = xg_v
        else:
            e_l['fh'] = ALFA*xg_l + (1-ALFA)*e_l['fh']
            e_l['ch'] = ALFA*xg_v + (1-ALFA)*e_l['ch']
        if e_v['fa'] is None:
            e_v['fa'] = xg_v; e_v['ca'] = xg_l
        else:
            e_v['fa'] = ALFA*xg_v + (1-ALFA)*e_v['fa']
            e_v['ca'] = ALFA*xg_l + (1-ALFA)*e_v['ca']
        e_l['n_h'] += 1; e_v['n_a'] += 1

    # === Eval test ===
    arquitecturas = ['V0_raw', 'V0_HG', 'V0_F5', 'V0_HG_F5', 'V0_HG_F5_X']
    stats = {a: {'n': 0, 'hit': 0, 'br': 0.0, 'argmax': {'1':0,'X':0,'2':0}, 'hit_x': 0, 'changed': 0}
             for a in arquitecturas}
    real_count = {'1': 0, 'X': 0, '2': 0}
    n_eval = 0; n_skip = 0

    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in test:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: n_skip += 1; continue
        e_l = ema_leg.get(ht_n); e_v = ema_leg.get(at_n)
        if not e_l or not e_v: n_skip += 1; continue
        if any(e_l.get(k) is None for k in ('fh','ch')) or any(e_v.get(k) is None for k in ('fa','ca')):
            n_skip += 1; continue
        xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
        xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
        rho = rho_pl.get(liga, -0.04)
        real = real_o(hg, ag)
        n_eval += 1; real_count[real] += 1
        n_l = n_liga.get(liga, 0)
        f_real = freq_real_pl.get(liga, 0.45)

        # V0_raw
        p_raw = probs_dc(xg_l, xg_v, rho)
        # V0_HG
        p_hg = aplicar_hallazgo_g(*p_raw, f_real, n_l)
        # V0_F5
        p_f5 = aplicar_fix5(*p_raw)
        # V0_HG_F5
        p_hgf5_int = aplicar_hallazgo_g(*p_raw, f_real, n_l)
        p_hgf5 = aplicar_fix5(*p_hgf5_int)
        # V0_HG_F5_X = misma prob pero argmax permite X
        p_hgf5_x = p_hgf5

        for arch, pp, permite_x in [
            ('V0_raw', p_raw, False),
            ('V0_HG', p_hg, False),
            ('V0_F5', p_f5, False),
            ('V0_HG_F5', p_hgf5, False),
            ('V0_HG_F5_X', p_hgf5_x, True),  # MISMA probabilidad, distinto argmax
        ]:
            am = amax_full(*pp, permitir_X=permite_x)
            stats[arch]['n'] += 1
            stats[arch]['hit'] += (1 if am == real else 0)
            stats[arch]['br'] += brier(*pp, real)
            stats[arch]['argmax'][am] += 1
            if am == 'X' and real == 'X': stats[arch]['hit_x'] += 1
            # Cambio respecto a V0_raw argmax
            if arch != 'V0_raw':
                am_raw = amax_full(*p_raw, permitir_X=False)
                if am != am_raw:
                    stats[arch]['changed'] += 1

    print(f"Test evaluado: {n_eval}  Skip: {n_skip}\n")

    # === REPORTE ===
    print("=" * 95)
    print(f"OOS TEST 2024 (N={n_eval})")
    print(f"Base: 1={real_count['1']/n_eval:.3f}  X={real_count['X']/n_eval:.3f}  2={real_count['2']/n_eval:.3f}")
    print("=" * 95)

    print(f"\n{'arch':<13s} {'hit':>6s} {'Brier':>7s} {'%1':>6s} {'%X':>6s} {'%2':>6s} "
          f"{'N_X':>5s} {'prec_X':>8s} {'flip_vs_raw':>13s}")
    print("-" * 95)
    for a in arquitecturas:
        s = stats[a]; n = s['n']
        hit = s['hit']/n; br = s['br']/n
        p1 = s['argmax']['1']/n; pX = s['argmax']['X']/n; p2 = s['argmax']['2']/n
        nx = s['argmax']['X']
        prec_x = s['hit_x']/nx if nx else 0
        chg_pct = s['changed']/n*100
        print(f"{a:<13s} {hit:>6.3f} {br:>7.4f} {p1:>6.3f} {pX:>6.3f} {p2:>6.3f} "
              f"{nx:>5d} {prec_x:>8.3f} {chg_pct:>11.1f}%")

    # === Por liga: hit V0_raw vs V0_HG_F5 ===
    print(f"\n=== Por liga: hit V0_raw vs hit V0_HG_F5 (Δparches sobre V0) ===")
    print(f"{'Liga':<13s} {'N':>5s} {'V0_raw':>7s} {'V0_HG':>6s} {'V0_F5':>6s} {'V0_HG_F5':>9s} "
          f"{'Δ_HG':>6s} {'Δ_F5':>6s} {'Δ_FULL':>7s}")
    print("-" * 85)
    stats_liga = defaultdict(lambda: {a: {'n':0,'hit':0} for a in arquitecturas})
    real_per_liga = defaultdict(int)
    # Re-iter
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in test:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e_l = ema_leg.get(ht_n); e_v = ema_leg.get(at_n)
        if not e_l or not e_v: continue
        if any(e_l.get(k) is None for k in ('fh','ch')) or any(e_v.get(k) is None for k in ('fa','ca')):
            continue
        xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
        xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
        rho = rho_pl.get(liga, -0.04)
        real = real_o(hg, ag)
        f_real = freq_real_pl.get(liga, 0.45); n_l_liga = n_liga.get(liga, 0)
        real_per_liga[liga] += 1

        p_raw = probs_dc(xg_l, xg_v, rho)
        p_hg = aplicar_hallazgo_g(*p_raw, f_real, n_l_liga)
        p_f5 = aplicar_fix5(*p_raw)
        p_int = aplicar_hallazgo_g(*p_raw, f_real, n_l_liga)
        p_hgf5 = aplicar_fix5(*p_int)
        for arch, pp, px_ok in [
            ('V0_raw', p_raw, False), ('V0_HG', p_hg, False),
            ('V0_F5', p_f5, False), ('V0_HG_F5', p_hgf5, False),
        ]:
            am = amax_full(*pp, permitir_X=px_ok)
            stats_liga[liga][arch]['n'] += 1
            stats_liga[liga][arch]['hit'] += (1 if am == real else 0)

    for liga in sorted(stats_liga.keys()):
        sl = stats_liga[liga]
        n = sl['V0_raw']['n']
        hr = sl['V0_raw']['hit']/n if n else 0
        hg = sl['V0_HG']['hit']/n if n else 0
        hf = sl['V0_F5']['hit']/n if n else 0
        hhf = sl['V0_HG_F5']['hit']/n if n else 0
        print(f"{liga:<13s} {n:>5d} {hr:>7.3f} {hg:>6.3f} {hf:>6.3f} {hhf:>9.3f} "
              f"{(hg-hr)*100:>+5.1f}pp {(hf-hr)*100:>+5.1f}pp {(hhf-hr)*100:>+6.1f}pp")

    # Veredicto
    print("\n=== VEREDICTO ===")
    raw_hit = stats['V0_raw']['hit']/stats['V0_raw']['n']
    raw_br = stats['V0_raw']['br']/stats['V0_raw']['n']
    for a in ['V0_HG', 'V0_F5', 'V0_HG_F5', 'V0_HG_F5_X']:
        s = stats[a]; n = s['n']
        d_hit = (s['hit']/n - raw_hit) * 100
        d_br = s['br']/n - raw_br
        verdict = "MEJORA" if d_hit > 0.3 and d_br < -0.0005 else (
            "EMPATE" if abs(d_hit) <= 0.3 else "EMPEORA")
        print(f"  {a:<12s}  d_hit={d_hit:+5.2f}pp  d_Brier={d_br:+.4f}  -> {verdict}")

    con.close()


if __name__ == "__main__":
    main()

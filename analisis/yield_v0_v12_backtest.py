"""[adepor-d7h] Yield + Hit OOS sobre partidos_backtest (con cuotas reales).

EMAs construidos sobre partidos_historico_externo COMPLETO (2021-2024) + partidos_backtest
en orden cronologico. Para cada partido test, prediccion ANTES de update de EMA (no leak).

Strategies:
  A: stake=1 sobre argmax SIEMPRE
  B: stake=1 sobre argmax SOLO si prob_modelo * cuota > 1.05 (EV > 5%)

Metrics:
  hit       = % aciertos del argmax (todas las apuestas)
  yield_A   = sum(profit_argmax) / sum(stake_A)
  yield_B   = sum(profit_argmax_filtrado) / sum(stake_B)
  n_picks_B = cuantas apuestas el filtro EV permite
"""
import json
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
LIGAS_HIST = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
              'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}
EV_THRESHOLD = 1.05  # apostar si prob * cuota > 1.05


def poisson(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except: return 0.0

def tau(i, j, l, v, rho):
    if i == 0 and j == 0: return 1 - l*v*rho
    if i == 0 and j == 1: return 1 + l*rho
    if i == 1 and j == 0: return 1 + v*rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0

def probs_dc(xg_l, xg_v, rho):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(10):
        for j in range(10):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)

def probs_skellam(xg_l, xg_v):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p_h = p_d = p_a = 0.0
    for d in range(-10, 11):
        p_d_v = sum(poisson(d + y, xg_l) * poisson(y, xg_v) for y in range(max(0, -d), 11))
        if d > 0: p_h += p_d_v
        elif d == 0: p_d += p_d_v
        else: p_a += p_d_v
    s = p_h + p_d + p_a
    return (p_h/s, p_d/s, p_a/s) if s > 0 else (1/3, 1/3, 1/3)


def predict_lr(feats, payload):
    W = np.array(payload['W']); mean = np.array(payload['mean']); std = np.array(payload['std'])
    x = np.array(feats, dtype=float); xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    L = W @ xs; L -= L.max(); e = np.exp(L); s = e.sum()
    return (e[0]/s, e[1]/s, e[2]/s) if s > 0 else (1/3, 1/3, 1/3)


def feats_v12(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v)/2.0, xg_l*xg_v,
            h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def calc_xg_v6(sot, shots, corners, goles, liga, ols):
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    c = ols.get(liga, OLS_GLOBAL)
    xg_calc = max(0.0, sot*c['beta_sot'] + shots_off*c['beta_off'] + corners*c['coef_corner'] + c['intercept'])
    if xg_calc == 0 and goles > 0: return goles
    return xg_calc * 0.70 + goles * 0.30


def calc_xg_legacy(sot, shots, corners, goles, cc=0.03):
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


def real_o(hg, ag): return "1" if hg > ag else ("2" if hg < ag else "X")


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}

    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                 'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap: ols_pl.setdefault(scope, {})[kmap[clave]] = val

    pesos = {}
    for r in cur.execute("""SELECT clave, scope, valor_texto FROM config_motor_valores
                             WHERE clave IN ('lr_v12_weights','lr_v12b1_weights','lr_v12b2_weights','lr_v12b3_weights')"""):
        clave, scope, txt = r
        if txt: pesos.setdefault(clave, {})[scope] = json.loads(txt)

    print("=" * 90)
    print(f"YIELD + HIT — partidos_backtest con cuotas reales (EV threshold = {EV_THRESHOLD})")
    print("=" * 90)

    # Construir EMAs con TODO histórico (2021-2024) cronológicamente
    print("Construyendo EMAs de histórico completo...")
    rows_hist = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({}) ORDER BY fecha ASC
    """.format(','.join(['?']*len(LIGAS_HIST))), LIGAS_HIST).fetchall()

    ema6 = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    emaL = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)

    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows_hist:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        cc_l = cc_pl.get(liga, 0.02)
        xg6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        xg6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        xgL_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc_l), hg, ag)
        xgL_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc_l), ag, hg)
        for em, lo, vi in [(ema6, xg6_l, xg6_v), (emaL, xgL_l, xgL_v)]:
            el = em[ht_n]; ev = em[at_n]
            if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
            else:
                el['fh'] = ALFA*lo + (1-ALFA)*el['fh']; el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
            if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
            else:
                ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']; ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
        v_l = var_eq[ht_n]; v_v = var_eq[at_n]
        e_l_pre = ema6[ht_n]; e_v_pre = ema6[at_n]
        if e_l_pre['fh'] is not None: v_l['vfh'] = ALFA*(xg6_l - e_l_pre['fh'])**2 + (1-ALFA)*v_l['vfh']
        if e_v_pre['fa'] is not None: v_v['vfa'] = ALFA*(xg6_v - e_v_pre['fa'])**2 + (1-ALFA)*v_v['vfa']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    print(f"  EMAs construidos sobre {len(rows_hist)} partidos histórico (2021-2024).\n")

    # Cargar partidos_backtest cronológicos
    rows_bt = cur.execute("""
        SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
          AND cuota_1 > 1 AND cuota_x > 1 AND cuota_2 > 1
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha ASC
    """).fetchall()
    print(f"Partidos test (con cuotas): {len(rows_bt)}\n")

    archs = ['V0', 'V6', 'V7', 'V12', 'V12b1', 'V12b2', 'V12b3']
    stats = {a: {'n': 0, 'hit': 0, 'profit_A': 0.0, 'n_B': 0, 'hit_B': 0, 'profit_B': 0.0,
                  'argmax': {'1': 0, 'X': 0, '2': 0}} for a in archs}
    n_skip = 0

    for pais, fecha, ht, at, c1, cx, c2, hg, ag, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v in rows_bt:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: n_skip += 1; continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v:
            n_skip += 1; continue
        if any(e6_l.get(k) is None for k in ('fh','ch')) or any(e6_v.get(k) is None for k in ('fa','ca')):
            n_skip += 1; continue
        if any(eL_l.get(k) is None for k in ('fh','ch')) or any(eL_v.get(k) is None for k in ('fa','ca')):
            n_skip += 1; continue

        xg6_l = max(0.10, (e6_l['fh'] + e6_v['ca'])/2.0); xg6_v = max(0.10, (e6_v['fa'] + e6_l['ch'])/2.0)
        xgL_l = max(0.10, (eL_l['fh'] + eL_v['ca'])/2.0); xgL_v = max(0.10, (eL_v['fa'] + eL_l['ch'])/2.0)
        rho = rho_pl.get(pais, -0.04)
        real = real_o(hg, ag)

        prev = []
        for k in [(pais, ht_n, at_n), (pais, at_n, ht_n)]: prev.extend(h2h.get(k, []))
        if prev:
            avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
            n_l = sum(1 for p in prev if (p['home']==ht_n and p['hg']>p['ag']) or (p['home']!=ht_n and p['ag']>p['hg']))
            n_x = sum(1 for p in prev if p['hg']==p['ag'])
            f_loc = n_l/len(prev); f_x = n_x/len(prev)
        else: avg_g, f_loc, f_x = 2.7, 0.45, 0.26
        v_l_t = var_eq.get(ht_n, {'vfh': 0.5}); v_v_t = var_eq.get(at_n, {'vfa': 0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        ff = feats_v12(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)

        # V12 features sin H2H (para V12b2)
        fs = [1.0, xg6_l, xg6_v, xg6_l-xg6_v, abs(xg6_l-xg6_v), (xg6_l+xg6_v)/2, xg6_l*xg6_v,
              v_l_t['vfh'], v_v_t['vfa'], float(mes)]

        probs = {
            'V0': probs_dc(xgL_l, xgL_v, rho),
            'V6': probs_dc(xg6_l, xg6_v, rho),
            'V7': probs_skellam(xg6_l, xg6_v),
            'V12': predict_lr(ff, pesos.get('lr_v12_weights', {}).get(pais, pesos.get('lr_v12_weights', {}).get('global', {}))),
            'V12b1': predict_lr(ff, pesos.get('lr_v12b1_weights', {}).get('global', {})),
            'V12b2': predict_lr(fs, pesos.get('lr_v12b2_weights', {}).get('global', {})),
            'V12b3': predict_lr(ff, pesos.get('lr_v12b3_weights', {}).get('global', {})),
        }
        cuotas = {'1': c1, 'X': cx, '2': c2}

        for a in archs:
            p1, px, p2 = probs[a]
            am = amax(p1, px, p2)
            prob_am = {'1': p1, 'X': px, '2': p2}[am]
            cuota_am = cuotas[am]
            stats[a]['n'] += 1
            stats[a]['argmax'][am] += 1
            won = (am == real)
            if won: stats[a]['hit'] += 1
            # Strategy A: apostar argmax siempre
            profit_A = (cuota_am - 1) if won else -1
            stats[a]['profit_A'] += profit_A
            # Strategy B: apostar solo si prob * cuota > 1.05
            ev = prob_am * cuota_am
            if ev > EV_THRESHOLD:
                stats[a]['n_B'] += 1
                if won: stats[a]['hit_B'] += 1
                stats[a]['profit_B'] += profit_A

        # Update EMAs con resultado real (expanding window)
        cc_l = cc_pl.get(pais, 0.02)
        new_xg6_l = ajustar(calc_xg_v6(sot_l, shots_l, corners_l, hg, pais, ols_pl), hg, ag)
        new_xg6_v = ajustar(calc_xg_v6(sot_v, shots_v, corners_v, ag, pais, ols_pl), ag, hg)
        new_xgL_l = ajustar(calc_xg_legacy(sot_l, shots_l, corners_l, hg, cc_l), hg, ag)
        new_xgL_v = ajustar(calc_xg_legacy(sot_v, shots_v, corners_v, ag, cc_l), ag, hg)
        for em, lo, vi in [(ema6, new_xg6_l, new_xg6_v), (emaL, new_xgL_l, new_xgL_v)]:
            el = em[ht_n]; ev = em[at_n]
            if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
            else:
                el['fh'] = ALFA*lo + (1-ALFA)*el['fh']; el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
            if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
            else:
                ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']; ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
        h2h[(pais, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    print(f"Test evaluado: {sum(s['n'] for s in stats.values())//len(archs)}  Skip: {n_skip}\n")

    # Reporte
    print("=" * 100)
    print(f"{'arch':<8s} {'N':>4s} {'hit':>6s} {'%X':>5s} {'yield_A':>9s} | "
          f"{'N_B':>4s} {'hit_B':>6s} {'yield_B':>9s} | composite_score")
    print("-" * 100)
    for a in archs:
        s = stats[a]; n = s['n']
        if n == 0: continue
        hit = s['hit']/n
        yA = s['profit_A']/n  # stake unitario
        yB = (s['profit_B']/s['n_B']) if s['n_B'] > 0 else 0
        hitB = (s['hit_B']/s['n_B']) if s['n_B'] > 0 else 0
        pX = s['argmax']['X']/n
        # Composite: yield_A weighted + hit
        comp = (yA + hit) / 2  # ad-hoc score combinado
        print(f"{a:<8s} {n:>4d} {hit:>6.3f} {pX:>4.1%} {yA:>+9.3f} | "
              f"{s['n_B']:>4d} {hitB:>6.3f} {yB:>+9.3f} | {comp:>+8.3f}")

    print(f"\nNota: yield_A = stake fijo sobre argmax SIEMPRE. yield_B = solo si prob*cuota > {EV_THRESHOLD}.")
    print(f"      yield positivo = ganancia sobre stake. yield 0 = break-even. <0 = perdida.")
    print(f"      composite_score = (yield_A + hit) / 2 (ad-hoc, balance entre rentabilidad y precision).")

    print(f"\nDistribucion argmax (% picks por outcome):")
    for a in archs:
        s = stats[a]; n = s['n']
        if n == 0: continue
        print(f"  {a:<8s} 1={s['argmax']['1']/n:.2%}  X={s['argmax']['X']/n:.2%}  2={s['argmax']['2']/n:.2%}")

    con.close()


if __name__ == "__main__":
    main()

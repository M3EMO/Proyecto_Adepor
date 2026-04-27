"""[adepor-d7h] Sweep threshold P(X) para H4 V0+X-rescue.

Para cada threshold en [0.25, 0.50] paso 0.025:
  H4 = V0 default + override 'X' si V12 argmax=X y P(X)_v12 > threshold
  Calcular hit, yield_A, yield_B, %X picks
  Identificar threshold optimo por composite score
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
EV_THRESHOLD = 1.05


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
    pesos_v12 = {}
    for r in cur.execute("SELECT scope, valor_texto FROM config_motor_valores WHERE clave='lr_v12_weights'"):
        if r[1]: pesos_v12[r[0]] = json.loads(r[1])

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

    rows_bt = cur.execute("""
        SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
          AND cuota_1 > 1 AND cuota_x > 1 AND cuota_2 > 1
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha ASC
    """).fetchall()

    # Cache predictions per match (avoid recomputing for each threshold)
    print("Computando predicciones por partido (cache)...")
    cache = []
    for pais, fecha, ht, at, c1, cx, c2, hg, ag, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v in rows_bt:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v: continue
        if any(e6_l.get(k) is None for k in ('fh','ch')) or any(e6_v.get(k) is None for k in ('fa','ca')): continue
        if any(eL_l.get(k) is None for k in ('fh','ch')) or any(eL_v.get(k) is None for k in ('fa','ca')): continue

        xg6_l = max(0.10, (e6_l['fh'] + e6_v['ca'])/2.0); xg6_v = max(0.10, (e6_v['fa'] + e6_l['ch'])/2.0)
        xgL_l = max(0.10, (eL_l['fh'] + eL_v['ca'])/2.0); xgL_v = max(0.10, (eL_v['fa'] + eL_l['ch'])/2.0)
        rho = rho_pl.get(pais, -0.04)
        real = "1" if hg > ag else ("2" if hg < ag else "X")

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

        p_v0 = probs_dc(xgL_l, xgL_v, rho)
        payload = pesos_v12.get(pais, pesos_v12.get('global', {}))
        p_v12 = predict_lr(ff, payload) if payload else (1/3, 1/3, 1/3)

        cache.append({
            'p_v0': p_v0, 'p_v12': p_v12, 'real': real,
            'c1': c1, 'cx': cx, 'c2': c2,
        })

        # Update EMAs
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

    print(f"Cache: {len(cache)} partidos\n")

    print("=" * 95)
    print(f"SWEEP threshold P(X) para H4 V0+X-rescue (N={len(cache)})")
    print("=" * 95)
    print(f"{'thresh':>7s} {'N_X':>5s} {'%X':>5s} {'hit':>6s} {'yield_A':>9s} {'N_B':>5s} {'hit_B':>6s} {'yield_B':>9s} {'compA':>7s}")
    print("-" * 95)

    thresholds = [0.25, 0.275, 0.30, 0.325, 0.35, 0.375, 0.40, 0.425, 0.45, 0.475, 0.50]
    best = None
    rows = []
    for thr in thresholds:
        n = len(cache); hit = 0; profit_A = 0.0; n_x = 0; profit_B = 0.0; n_B = 0; hit_B = 0
        for c in cache:
            p_v0 = c['p_v0']; p_v12 = c['p_v12']; real = c['real']
            cuotas = {'1': c['c1'], 'X': c['cx'], '2': c['c2']}
            am_v0 = amax(*p_v0); am_v12 = amax(*p_v12)
            # H4 with this threshold
            if am_v12 == 'X' and p_v12[1] > thr:
                am = 'X'; n_x += 1
                prob_am = p_v12[1]
            else:
                am = am_v0
                prob_am = {'1': p_v0[0], 'X': p_v0[1], '2': p_v0[2]}[am]
            cuota_am = cuotas[am]
            won = (am == real)
            if won: hit += 1
            profit = (cuota_am - 1) if won else -1
            profit_A += profit
            ev = prob_am * cuota_am
            if ev > EV_THRESHOLD:
                n_B += 1
                if won: hit_B += 1
                profit_B += profit
        hit_r = hit / n; yA = profit_A / n
        yB = (profit_B / n_B) if n_B > 0 else 0
        hitB = (hit_B / n_B) if n_B > 0 else 0
        compA = (yA + hit_r) / 2
        rows.append((thr, n_x, hit_r, yA, n_B, hitB, yB, compA))
        print(f"{thr:>7.3f} {n_x:>5d} {n_x/n*100:>4.1f}% {hit_r:>6.3f} {yA:>+9.3f} "
              f"{n_B:>5d} {hitB:>6.3f} {yB:>+9.3f} {compA:>+7.3f}")
        if best is None or compA > best[7]:
            best = (thr, n_x, hit_r, yA, n_B, hitB, yB, compA)

    print(f"\nMEJOR threshold: {best[0]:.3f}  hit={best[2]:.3f}  yield_A={best[3]:+.3f}  compA={best[7]:+.3f}")

    # Comparativa baselines
    print("\n--- Baselines de referencia ---")
    n = len(cache); hit_v0 = 0; profit_v0 = 0.0; hit_v12 = 0; profit_v12 = 0.0
    for c in cache:
        p_v0 = c['p_v0']; p_v12 = c['p_v12']; real = c['real']
        cuotas = {'1': c['c1'], 'X': c['cx'], '2': c['c2']}
        am_v0 = amax(*p_v0); am_v12 = amax(*p_v12)
        if am_v0 == real: hit_v0 += 1
        if am_v12 == real: hit_v12 += 1
        profit_v0 += (cuotas[am_v0] - 1) if am_v0 == real else -1
        profit_v12 += (cuotas[am_v12] - 1) if am_v12 == real else -1
    print(f"V0 baseline:  hit={hit_v0/n:.3f}  yield_A={profit_v0/n:+.3f}  compA={(profit_v0/n + hit_v0/n)/2:+.3f}")
    print(f"V12 baseline: hit={hit_v12/n:.3f}  yield_A={profit_v12/n:+.3f}  compA={(profit_v12/n + hit_v12/n)/2:+.3f}")

    con.close()


if __name__ == "__main__":
    main()

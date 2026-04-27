"""[adepor-d7h] Sub-analisis: en los partidos donde V12 pickea X, como performa V0?

Si V0 tambien pierde en esos partidos, V12 es objetivamente mejor para predecir X.
Si V0 acierta picando 1 o 2 en esos partidos, V12 esta picando X falsos.
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
LIGAS = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
         'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
TRAIN_TEMP = {2021, 2022, 2023}; TEST_TEMP = {2024}
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


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


def feats_v12(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v)/2.0, xg_l*xg_v,
            h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def predict_lr(feats, payload):
    W = np.array(payload['W']); mean = np.array(payload['mean']); std = np.array(payload['std'])
    x = np.array(feats, dtype=float); xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    L = W @ xs; L -= L.max(); e = np.exp(L); s = e.sum()
    return (e[0]/s, e[1]/s, e[2]/s) if s > 0 else (1/3, 1/3, 1/3)


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def real_o(hg, ag): return "1" if hg > ag else ("2" if hg < ag else "X")


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

    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({}) ORDER BY fecha ASC
    """.format(','.join(['?']*len(LIGAS))), LIGAS).fetchall()
    train = [r for r in rows if r[1] in TRAIN_TEMP]
    test = [r for r in rows if r[1] in TEST_TEMP]

    # Build EMAs train
    ema6 = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    emaL = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)
    for liga, _, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train:
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

    # Eval
    casos = {
        'v12_pickea_X': {'n': 0, 'real_X': 0, 'v0_acierta': 0, 'v12_acierta': 0,
                          'real_1': 0, 'real_2': 0,
                          'v0_pickea_1': 0, 'v0_pickea_2': 0},
        'v12_pickea_1': {'n': 0, 'v0_acierta': 0, 'v12_acierta': 0},
        'v12_pickea_2': {'n': 0, 'v0_acierta': 0, 'v12_acierta': 0},
    }

    for liga, _, fecha, ht, at, hg, ag, *_ in test:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v: continue
        if any(e6_l.get(k) is None for k in ('fh','ch')) or any(e6_v.get(k) is None for k in ('fa','ca')): continue
        if any(eL_l.get(k) is None for k in ('fh','ch')) or any(eL_v.get(k) is None for k in ('fa','ca')): continue

        xg6_l = max(0.10, (e6_l['fh'] + e6_v['ca'])/2.0); xg6_v = max(0.10, (e6_v['fa'] + e6_l['ch'])/2.0)
        xgL_l = max(0.10, (eL_l['fh'] + eL_v['ca'])/2.0); xgL_v = max(0.10, (eL_v['fa'] + eL_l['ch'])/2.0)
        rho = rho_pl.get(liga, -0.04)
        real = real_o(hg, ag)

        prev = []
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]: prev.extend(h2h.get(k, []))
        if prev:
            avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
            n_l = sum(1 for p in prev if (p['home']==ht_n and p['hg']>p['ag']) or (p['home']!=ht_n and p['ag']>p['hg']))
            n_x = sum(1 for p in prev if p['hg']==p['ag'])
            f_loc = n_l/len(prev); f_x = n_x/len(prev)
        else: avg_g, f_loc, f_x = 2.7, 0.45, 0.26
        v_l_t = var_eq.get(ht_n, {'vfh': 0.5}); v_v_t = var_eq.get(at_n, {'vfa': 0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6

        ff = feats_v12(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        payload = pesos_v12.get(liga, pesos_v12.get('global', {}))
        if not payload: continue

        p_v0 = probs_dc(xgL_l, xgL_v, rho)
        p_v12 = predict_lr(ff, payload)

        am_v0 = amax(*p_v0)
        am_v12 = amax(*p_v12)

        bucket = f'v12_pickea_{am_v12}'
        casos[bucket]['n'] += 1
        if am_v0 == real: casos[bucket]['v0_acierta'] += 1
        if am_v12 == real: casos[bucket]['v12_acierta'] += 1
        if bucket == 'v12_pickea_X':
            if real == 'X': casos[bucket]['real_X'] += 1
            elif real == '1': casos[bucket]['real_1'] += 1
            else: casos[bucket]['real_2'] += 1
            if am_v0 == '1': casos[bucket]['v0_pickea_1'] += 1
            else: casos[bucket]['v0_pickea_2'] += 1

    print("=" * 80)
    print("V12 vs V0 condicionado al pick de V12  (OOS test 2024)")
    print("=" * 80)

    for bucket, s in casos.items():
        n = s['n']
        if n == 0: continue
        print(f"\n{bucket}: N={n}")
        print(f"  V0 hit en estos partidos: {s['v0_acierta']/n:.3f} ({s['v0_acierta']}/{n})")
        print(f"  V12 hit en estos partidos: {s['v12_acierta']/n:.3f} ({s['v12_acierta']}/{n})")
        if bucket == 'v12_pickea_X':
            print(f"  Real distribution: 1={s['real_1']}/{n}={s['real_1']/n:.3f}  "
                  f"X={s['real_X']}/{n}={s['real_X']/n:.3f}  "
                  f"2={s['real_2']}/{n}={s['real_2']/n:.3f}")
            print(f"  V0 pickea: 1={s['v0_pickea_1']}/{n}={s['v0_pickea_1']/n:.3f}  "
                  f"2={s['v0_pickea_2']}/{n}={s['v0_pickea_2']/n:.3f}  X=0")

    # Resumen estrategia hibrida potencial
    print("\n" + "=" * 80)
    print("ANALISIS HIBRIDO: V0 default + V12 dispara X")
    print("=" * 80)
    n_x_picks = casos['v12_pickea_X']['n']
    if n_x_picks > 0:
        v12_x_hits = casos['v12_pickea_X']['v12_acierta']
        v0_x_hits = casos['v12_pickea_X']['v0_acierta']
        # Calculo: si en N_eval total V0 da hit_v0, y reemplazamos V12 en X-picks:
        # nuevo_hit = (hits_v0_no_x_picks + v12_x_hits) / N_total
        # delta = (v12_x_hits - v0_x_hits) / N_total
        delta = (v12_x_hits - v0_x_hits) / 2768  # N_eval aprox
        print(f"  V12 X picks: N={n_x_picks}, hits V12 = {v12_x_hits}, hits V0 (en mismos) = {v0_x_hits}")
        print(f"  Delta hibrido vs V0 puro: {delta*100:+.2f}pp hit global")
        if delta > 0:
            print(f"  -> HIBRIDO MEJORA (V0 default + V12 dispara X cuando lo predice)")
        else:
            print(f"  -> HIBRIDO EMPEORA (V0 puro mejor que cualquier mezcla)")

    con.close()


if __name__ == "__main__":
    main()

"""[adepor-617] F2 audit pasos 1-2: sweep threshold H4 + bootstrap CI95 por liga.

Recolecta predicciones V0/V12 una sola vez en walk-forward, luego post-procesa:
  - Sweep threshold H4 en [0.20, 0.25, 0.30, 0.35, 0.40]
  - Bootstrap CI95 yield por liga (V0, V12)
"""
import json
import math
import sqlite3
import sys
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import limpiar_texto

DB = ROOT / "fondo_quant.db"
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}
EV_THRESHOLD = 1.05

LIGAS_HIST_FULL = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
                   'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
LIGAS_TEST = ['Alemania', 'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']

H4_THRESHOLDS = [0.20, 0.225, 0.25, 0.275, 0.30, 0.325, 0.35, 0.40]
BOOTSTRAP_N = 1000
SEED = 42


# ============================================================
# Modelos
# ============================================================
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
    if not payload: return 1/3, 1/3, 1/3
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


def bootstrap_ci(profits, n_boot=BOOTSTRAP_N, seed=SEED):
    if not profits: return None, None, None
    rng = random.Random(seed)
    n = len(profits)
    means = []
    for _ in range(n_boot):
        sample = [profits[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    pt = sum(profits) / n
    return pt, lo, hi


# ============================================================
# Walk-forward + recolectar predicciones
# ============================================================
def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_pl  = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}
    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap: ols_pl.setdefault(scope, {})[kmap[clave]] = val
    pesos = {}
    for r in cur.execute("""SELECT clave, scope, valor_texto FROM config_motor_valores
                             WHERE clave='lr_v12_weights'"""):
        if r[2]: pesos.setdefault(r[0], {})[r[1]] = json.loads(r[2])

    # Warmup
    rows_warmup = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats=1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN (2021,2022,2023)
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL).fetchall()

    ema6 = defaultdict(lambda: {'fh':None,'ch':None,'fa':None,'ca':None})
    emaL = defaultdict(lambda: {'fh':None,'ch':None,'fa':None,'ca':None})
    var_eq = defaultdict(lambda: {'vfh':0.5,'vfa':0.5})
    h2h = defaultdict(list)

    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows_warmup:
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

    print(f"Warmup: {len(rows_warmup)} partidos. Equipos con EMA: {len(ema6)}\n")

    # Test 2024 EUR
    rows_test = cur.execute(f"""
        SELECT phe.liga, phe.fecha, phe.ht, phe.at, phe.hg, phe.ag,
               phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
               ce.psch, ce.pscd, ce.psca, ce.avgch, ce.avgcd, ce.avgca
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
            AND ce.ht=phe.ht AND ce.at=phe.at
        WHERE phe.has_full_stats=1 AND phe.temp=2024
          AND phe.liga IN ({','.join(['?']*len(LIGAS_TEST))})
          AND ce.psch IS NOT NULL
        ORDER BY phe.fecha ASC
    """, LIGAS_TEST).fetchall()

    print(f"Test: {len(rows_test)} partidos query.\n")

    # Recolectar predicciones
    preds = []  # lista de dicts con todo lo necesario
    for row in rows_test:
        (liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac,
         psch, pscd, psca, avgch, avgcd, avgca) = row
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v: continue
        if any(e6_l.get(k) is None for k in ('fh','ch')) or any(e6_v.get(k) is None for k in ('fa','ca')): continue
        if any(eL_l.get(k) is None for k in ('fh','ch')) or any(eL_v.get(k) is None for k in ('fa','ca')): continue
        c1 = psch or avgch; cx = pscd or avgcd; c2 = psca or avgca
        if not (c1 and cx and c2 and c1 > 1 and cx > 1 and c2 > 1): continue

        xg6_l = max(0.10, (e6_l['fh']+e6_v['ca'])/2); xg6_v = max(0.10, (e6_v['fa']+e6_l['ch'])/2)
        xgL_l = max(0.10, (eL_l['fh']+eL_v['ca'])/2); xgL_v = max(0.10, (eL_v['fa']+eL_l['ch'])/2)
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
        v_l_t = var_eq.get(ht_n, {'vfh':0.5}); v_v_t = var_eq.get(at_n, {'vfa':0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        ff = feats_v12(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        v12_payload = pesos.get('lr_v12_weights', {}).get(liga, pesos.get('lr_v12_weights', {}).get('global', {}))

        v0_p = probs_dc(xgL_l, xgL_v, rho)
        v12_p = predict_lr(ff, v12_payload)

        preds.append({
            'liga': liga, 'fecha': fecha[:10], 'real': real,
            'cuotas': {'1': c1, 'X': cx, '2': c2},
            'v0_p': v0_p, 'v12_p': v12_p,
        })

        # Update EMAs (idem original)
        cc_l = cc_pl.get(liga, 0.02)
        new_xg6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        new_xg6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        new_xgL_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc_l), hg, ag)
        new_xgL_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc_l), ag, hg)
        for em, lo, vi in [(ema6, new_xg6_l, new_xg6_v), (emaL, new_xgL_l, new_xgL_v)]:
            el = em[ht_n]; ev = em[at_n]
            if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
            else:
                el['fh'] = ALFA*lo + (1-ALFA)*el['fh']; el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
            if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
            else:
                ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']; ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    print(f"Preds recolectadas: {len(preds)}\n")
    con.close()

    # ============================================================
    # PASO 1 — Sweep H4 threshold
    # ============================================================
    print("=" * 100)
    print("PASO 1 — SWEEP THRESHOLD H4 (P_v12(X) > threshold para X-rescue)")
    print("=" * 100)
    print(f"{'thresh':>7} {'n_X':>5} {'hit_h4':>7} {'yield_h4':>10} {'CI95_h4':>22} {'delta_v0':>10}")
    print("-" * 80)

    sweep_results = {}
    # Baseline V0
    profits_v0 = []
    hit_v0 = 0
    for p in preds:
        am = amax(*p['v0_p'])
        won = (am == p['real'])
        profits_v0.append((p['cuotas'][am] - 1) if won else -1)
        if won: hit_v0 += 1
    yield_v0, lo_v0, hi_v0 = bootstrap_ci(profits_v0)
    print(f"{'V0_base':>7} {0:>5} {hit_v0/len(preds):>7.3f} {yield_v0:>+10.4f} "
          f"{f'[{lo_v0:+.3f}, {hi_v0:+.3f}]':>22}     ----")

    for th in H4_THRESHOLDS:
        profits_h4 = []
        hit_h4 = 0
        n_x = 0
        for p in preds:
            am_v0 = amax(*p['v0_p'])
            v12_p = p['v12_p']
            am_v12 = amax(*v12_p)
            if am_v12 == 'X' and v12_p[1] > th:
                am = 'X'
                n_x += 1
            else:
                am = am_v0
            won = (am == p['real'])
            profits_h4.append((p['cuotas'][am] - 1) if won else -1)
            if won: hit_h4 += 1
        yield_h4, lo_h4, hi_h4 = bootstrap_ci(profits_h4)
        delta = yield_h4 - yield_v0
        print(f"{th:>7.3f} {n_x:>5d} {hit_h4/len(preds):>7.3f} {yield_h4:>+10.4f} "
              f"{f'[{lo_h4:+.3f}, {hi_h4:+.3f}]':>22}  {delta:>+10.4f}")
        sweep_results[th] = {
            'n_x_picks': n_x, 'hit': hit_h4/len(preds),
            'yield': yield_h4, 'ci_low': lo_h4, 'ci_high': hi_h4,
            'delta_vs_v0': delta,
        }

    # ============================================================
    # PASO 2 — Bootstrap CI95 yield por liga
    # ============================================================
    print()
    print("=" * 100)
    print("PASO 2 — Bootstrap CI95 yield por liga (V0, V12, H4 con threshold elegido)")
    print("=" * 100)
    # Elegir mejor threshold H4 del sweep
    best_th = max(sweep_results, key=lambda t: sweep_results[t]['yield'])
    print(f"Threshold H4 ganador: {best_th}")
    print()
    print(f"{'liga':<12} {'arch':<5} {'N':>5} {'hit':>6} {'yield':>9} {'CI95':>22} {'sig?':>6}")
    print("-" * 75)

    by_liga = defaultdict(lambda: {'V0': [], 'V12': [], 'H4': [], 'V0_hit': 0, 'V12_hit': 0, 'H4_hit': 0, 'n': 0})
    for p in preds:
        liga = p['liga']
        am_v0 = amax(*p['v0_p'])
        am_v12 = amax(*p['v12_p'])
        if am_v12 == 'X' and p['v12_p'][1] > best_th:
            am_h4 = 'X'
        else:
            am_h4 = am_v0
        for arch, am in [('V0', am_v0), ('V12', am_v12), ('H4', am_h4)]:
            won = (am == p['real'])
            by_liga[liga][arch].append((p['cuotas'][am] - 1) if won else -1)
            if won: by_liga[liga][f'{arch}_hit'] += 1
        by_liga[liga]['n'] += 1

    per_liga_out = {}
    for liga in sorted(by_liga):
        d = by_liga[liga]
        for arch in ['V0', 'V12', 'H4']:
            profits = d[arch]
            if not profits: continue
            yld, lo, hi = bootstrap_ci(profits)
            hit = d[f'{arch}_hit'] / d['n']
            sig = '***' if (lo > 0 or hi < 0) else '.'
            print(f"{liga:<12} {arch:<5} {len(profits):>5d} {hit:>6.3f} {yld:>+9.3f} "
                  f"{f'[{lo:+.3f}, {hi:+.3f}]':>22}  {sig:>6}")
            per_liga_out.setdefault(liga, {})[arch] = {
                'n': len(profits), 'hit': hit, 'yield': yld,
                'ci_low': lo, 'ci_high': hi, 'significant_95': (lo > 0 or hi < 0),
            }
        print()

    # ============================================================
    # Persistir
    # ============================================================
    out_path = ROOT / "analisis" / "audit_yield_F2_sweep_y_ci.json"
    out_path.write_text(json.dumps({
        'fecha': '2026-04-26',
        'bead': 'adepor-617',
        'fase': 'F2_audit_post_extendido',
        'n_test_preds': len(preds),
        'sweep_h4': sweep_results,
        'best_h4_threshold': best_th,
        'per_liga': per_liga_out,
    }, indent=2), encoding='utf-8')
    print(f"\nJSON: {out_path}")
    print(f"\nLeyenda: *** = CI95 no incluye 0 (significativo al 95%). '.' = no significativo.")


if __name__ == "__main__":
    main()

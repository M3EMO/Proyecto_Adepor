"""[adepor-edk] F2 COMPLETO — yield walk-forward sobre 8 ligas (6 EUR + ARG/BRA).

Sucede a yield_v0_v12_backtest_extendido.py (que solo tenia 6 EUR).
Incluye Argentina y Brasil con cuotas Pinnacle closing scraped via /new/{ARG,BRA}.csv.

Reporta:
  - Yield/CI95 por liga
  - Yield/CI95 agregado por politica de filtro
  - Comparativo EUR vs LATAM
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
H4_THRESHOLD = 0.35  # ganador del sweep prev

LIGAS_HIST_FULL = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
                   'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
# 6 EUR + ARG + BRA (todos con cuotas en cuotas_externas_historico Y stats en PHE)
LIGAS_TEST = ['Alemania', 'Argentina', 'Brasil', 'Espana', 'Francia',
              'Inglaterra', 'Italia', 'Turquia']

# Argentina y Brasil en PHE solo cubren 2022-2024 (no 2021). Usamos 2022 como warmup.
TEMPS_WARMUP = [2021, 2022, 2023]
TEMPS_TEST = [2024]

BOOTSTRAP_N = 1000
SEED = 42


# Modelos
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
    return sum(profits) / n, lo, hi


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

    print("=" * 100)
    print("F2 COMPLETO — 8 ligas (6 EUR + ARG + BRA)")
    print(f"Warmup {TEMPS_WARMUP}, Test {TEMPS_TEST}")
    print(f"H4 X-threshold {H4_THRESHOLD}, EV-min {EV_THRESHOLD}")
    print("=" * 100)
    print(f"V12 weights por liga: {sorted(pesos.get('lr_v12_weights', {}).keys())}")
    print(f"rho por liga: {sorted([k for k,v in rho_pl.items() if v is not None])}")
    print()

    # Warmup
    rows_warmup = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats=1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN ({','.join(['?']*len(TEMPS_WARMUP))})
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL + TEMPS_WARMUP).fetchall()

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

    # Test
    rows_test = cur.execute(f"""
        SELECT phe.liga, phe.fecha, phe.ht, phe.at, phe.hg, phe.ag,
               phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
               ce.psch, ce.pscd, ce.psca, ce.avgch, ce.avgcd, ce.avgca
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
            AND ce.ht=phe.ht AND ce.at=phe.at
        WHERE phe.has_full_stats=1 AND phe.temp IN ({','.join(['?']*len(TEMPS_TEST))})
          AND phe.liga IN ({','.join(['?']*len(LIGAS_TEST))})
          AND ce.psch IS NOT NULL
        ORDER BY phe.fecha ASC
    """, TEMPS_TEST + LIGAS_TEST).fetchall()

    print(f"Test: {len(rows_test)} partidos query.\n")

    preds = []
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
        preds.append({'liga': liga, 'real': real, 'cuotas': {'1': c1, 'X': cx, '2': c2},
                      'v0_p': v0_p, 'v12_p': v12_p})

        # Update EMAs
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

    print(f"Preds OK: {len(preds)}\n")

    # === Yield por liga ===
    print("=" * 100)
    print("YIELD POR LIGA (Pinnacle closing 2024)")
    print("=" * 100)
    print(f"{'liga':<12} {'arch':<5} {'N':>5} {'hit':>6} {'yield':>9} {'CI95':>22} {'sig':>4}")
    print("-" * 75)

    by_liga = defaultdict(lambda: {'V0': [], 'V12': [], 'H4': [], 'V0_hit': 0, 'V12_hit': 0, 'H4_hit': 0, 'n': 0})
    for p in preds:
        liga = p['liga']
        am_v0 = amax(*p['v0_p'])
        am_v12 = amax(*p['v12_p'])
        if am_v12 == 'X' and p['v12_p'][1] > H4_THRESHOLD:
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
            if not d[arch]: continue
            yld, lo, hi = bootstrap_ci(d[arch])
            hit = d[f'{arch}_hit'] / d['n']
            sig = '***' if (lo > 0 or hi < 0) else '.'
            print(f"{liga:<12} {arch:<5} {len(d[arch]):>5d} {hit:>6.3f} {yld:>+9.3f} "
                  f"{f'[{lo:+.3f}, {hi:+.3f}]':>22}  {sig:>4}")
            per_liga_out.setdefault(liga, {})[arch] = {
                'n': len(d[arch]), 'hit': hit, 'yield': yld, 'ci_low': lo, 'ci_high': hi,
                'significant_95': (lo > 0 or hi < 0),
            }
        print()

    # === Yield por politica de filtro ===
    print("=" * 100)
    print("YIELD AGREGADO POR POLITICA DE FILTRO")
    print("=" * 100)
    politicas = {
        'All_8_ligas (baseline)':           lambda l: True,
        'Solo_EUR_6':                       lambda l: l not in ('Argentina', 'Brasil'),
        'Solo_LATAM_2':                     lambda l: l in ('Argentina', 'Brasil'),
        'EUR_drop_DE_ES (top4 EUR)':        lambda l: l in ('Turquia','Italia','Francia','Inglaterra'),
        'EUR_top4 + LATAM':                 lambda l: l in ('Turquia','Italia','Francia','Inglaterra','Argentina','Brasil'),
        'Drop_negs (sin DE/ES y sin LATAM neg si aplica)': None,  # se computa post-hoc
    }

    print(f"{'politica':<40} {'arch':<5} {'N':>5} {'hit':>6} {'yield':>9} {'CI95':>22} {'sig':>4}")
    print("-" * 105)

    out_pol = {}
    for nombre_pol, filter_fn in politicas.items():
        if filter_fn is None:
            # post-hoc: drop ligas con yield_V0 negativo en este test
            negs = {l for l, d in per_liga_out.items() if d.get('V0', {}).get('yield', 0) < 0}
            filter_fn = lambda l, neg=negs: l not in neg
        sub = [p for p in preds if filter_fn(p['liga'])]
        if not sub:
            print(f"{nombre_pol:<40} (sin partidos)")
            continue
        for arch in ['V0', 'V12', 'H4']:
            profits = []
            hit = 0
            for p in sub:
                am_v0 = amax(*p['v0_p'])
                am_v12 = amax(*p['v12_p'])
                if arch == 'V0': am = am_v0
                elif arch == 'V12': am = am_v12
                else:
                    if am_v12 == 'X' and p['v12_p'][1] > H4_THRESHOLD:
                        am = 'X'
                    else:
                        am = am_v0
                won = (am == p['real'])
                profits.append((p['cuotas'][am] - 1) if won else -1)
                if won: hit += 1
            yld, lo, hi = bootstrap_ci(profits)
            sig = '***' if (lo > 0 or hi < 0) else '.'
            print(f"{nombre_pol:<40} {arch:<5} {len(profits):>5d} {hit/len(profits):>6.3f} "
                  f"{yld:>+9.3f} {f'[{lo:+.3f}, {hi:+.3f}]':>22}  {sig:>4}")
            out_pol.setdefault(nombre_pol, {})[arch] = {
                'n': len(profits), 'hit': hit/len(profits),
                'yield': yld, 'ci_low': lo, 'ci_high': hi,
                'significant_95': (lo > 0 or hi < 0),
            }
        print()

    # === Persistir ===
    out = {
        'fecha': '2026-04-26', 'bead': 'adepor-edk',
        'fase': 'F2_completo_LATAM',
        'h4_threshold': H4_THRESHOLD,
        'n_warmup': len(rows_warmup),
        'n_test': len(preds),
        'per_liga': per_liga_out,
        'politicas': out_pol,
    }
    out_path = ROOT / "analisis" / "yield_v0_v12_F2_completo_LATAM.json"
    out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"\nJSON: {out_path}")
    con.close()


if __name__ == "__main__":
    main()

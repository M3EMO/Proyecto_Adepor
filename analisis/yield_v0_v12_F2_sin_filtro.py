"""[adepor-edk] F2 — yield SIN FILTRO de liga, evaluando estrategias uniformes
sobre las 8 ligas del test. Decisión del usuario: mantener todas las ligas activas.

Compara:
  - V0 uniforme (statu quo)
  - V12 uniforme (todos los ligas)
  - H4 uniforme con sweep threshold
  - L2 solo (V12 solo Turquía; V0 resto)
  - L2+L3 (V12 solo Turquía; H4 resto)
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

from analisis.yield_v0_v12_F2_completo import (
    probs_dc, predict_lr, feats_v12, calc_xg_legacy, calc_xg_v6,
    ajustar, real_o, amax, bootstrap_ci,
    LIGAS_HIST_FULL, LIGAS_TEST, TEMPS_WARMUP, TEMPS_TEST,
    ALFA, OLS_GLOBAL,
)

DB = ROOT / "fondo_quant.db"


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

    rows_warmup = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats=1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN ({','.join(['?']*len(TEMPS_WARMUP))})
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL + TEMPS_WARMUP).fetchall()

    ema6 = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    emaL = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
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

    print(f"N preds: {len(preds)}\n")
    print("=" * 100)
    print("SIN FILTRO DE LIGA — yield agregado por arquitectura uniforme")
    print("=" * 100)
    print(f'{"estrategia":<55} {"N":>5} {"hit":>6} {"yield":>9} {"CI95":>22} {"sig":>4}')
    print("-" * 100)

    def decidir_v0(p): return amax(*p['v0_p'])
    def decidir_v12(p): return amax(*p['v12_p'])
    def decidir_h4(p, th):
        if amax(*p['v12_p']) == 'X' and p['v12_p'][1] > th:
            return 'X'
        return amax(*p['v0_p'])
    def decidir_l2(p):
        return amax(*p['v12_p']) if p['liga'] == 'Turquia' else amax(*p['v0_p'])
    def decidir_l2_l3(p, th):
        if p['liga'] == 'Turquia':
            return amax(*p['v12_p'])
        return decidir_h4(p, th)

    estrategias = [
        ('V0 uniforme (statu quo)', decidir_v0),
        ('V12 uniforme (todas las ligas)', decidir_v12),
        ('H4 uniforme thresh=0.30', lambda p: decidir_h4(p, 0.30)),
        ('H4 uniforme thresh=0.35', lambda p: decidir_h4(p, 0.35)),
        ('L2 solo: V12 solo TUR; V0 resto', decidir_l2),
        ('L2+L3: V12 solo TUR; H4(0.35) resto', lambda p: decidir_l2_l3(p, 0.35)),
    ]

    out = {}
    for nombre, decisor in estrategias:
        profits = []
        hit = 0
        for p in preds:
            am = decisor(p)
            won = (am == p['real'])
            profits.append((p['cuotas'][am] - 1) if won else -1)
            if won: hit += 1
        yld, lo, hi = bootstrap_ci(profits)
        sig = '***' if (lo > 0 or hi < 0) else '.'
        print(f'{nombre:<55} {len(profits):>5} {hit/len(profits):>6.3f} {yld:>+9.3f} {f"[{lo:+.3f}, {hi:+.3f}]":>22}  {sig:>4}')
        out[nombre] = {'n': len(profits), 'hit': hit/len(profits),
                       'yield': yld, 'ci_low': lo, 'ci_high': hi,
                       'significant_95': (lo > 0 or hi < 0)}

    print()
    print("-" * 100)
    print("Sweep H4 threshold uniforme (todas las ligas):")
    print(f'{"thresh":>8} {"N":>5} {"hit":>6} {"yield":>9} {"CI95":>22} {"sig":>4}')
    sweep_out = {}
    for th in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        profits = []
        hit = 0
        for p in preds:
            am = decidir_h4(p, th)
            won = (am == p['real'])
            profits.append((p['cuotas'][am] - 1) if won else -1)
            if won: hit += 1
        yld, lo, hi = bootstrap_ci(profits)
        sig = '***' if (lo > 0 or hi < 0) else '.'
        print(f'  {th:.2f}    {len(profits):>5} {hit/len(profits):>6.3f} {yld:>+9.3f} {f"[{lo:+.3f}, {hi:+.3f}]":>22}  {sig:>4}')
        sweep_out[f'thresh_{th:.2f}'] = {'n': len(profits), 'yield': yld, 'ci_low': lo, 'ci_high': hi}

    out_path = ROOT / "analisis" / "yield_v0_v12_F2_sin_filtro_liga.json"
    out_path.write_text(json.dumps({
        'fecha': '2026-04-26', 'bead': 'adepor-edk',
        'restriccion': 'Mantener todas las ligas activas (sin gate por liga)',
        'n_preds': len(preds),
        'estrategias': out,
        'sweep_h4_uniforme': sweep_out,
    }, indent=2), encoding='utf-8')
    print(f"\nJSON: {out_path}")
    con.close()


if __name__ == "__main__":
    main()

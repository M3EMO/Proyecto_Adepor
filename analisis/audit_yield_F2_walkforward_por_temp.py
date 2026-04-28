"""[adepor-edk Opcion D] Re-audit Layer 3 (H4 X-rescue) con:

  1. Walk-forward por temp: warmup hasta T-1, test en T para T en {2022, 2023, 2024}.
     Threshold H4 FIJO 0.35 (no re-optimizar por temp -> evita data-snooping).
  2. In-sample 2026: warmup 2021-2024 -> test partidos_backtest 2026.

Pregunta: ¿H4 thresh=0.35 SOSTIENE su mejora marginal cross-temp y en regimen 2026?
  - Si yield H4 > V0 en 2022/2023/2024 + 2026 -> evidencia robusta para Layer 3.
  - Si signo flipea entre temps -> threshold optimizado retrospectivamente, NO aplicar.

Salida: analisis/audit_yield_F2_walkforward_por_temp.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import limpiar_texto

from analisis.yield_v0_v12_F2_completo import (
    probs_dc, predict_lr, feats_v12, calc_xg_legacy, calc_xg_v6,
    ajustar, real_o, amax, bootstrap_ci,
    LIGAS_HIST_FULL, LIGAS_TEST,
    ALFA,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "audit_yield_F2_walkforward_por_temp.json"
H4_THRESH = 0.35


def cargar_pesos_ols(con):
    cur = con.cursor()
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_pl  = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}
    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val
    pesos = {}
    for r in cur.execute("""SELECT scope, valor_texto FROM config_motor_valores
                             WHERE clave='lr_v12_weights'"""):
        if r[1]:
            pesos[r[0]] = json.loads(r[1])
    return rho_pl, cc_pl, ols_pl, pesos


def warmup_emas(con, temps_warmup):
    """Construye estado EMAs/h2h/var sobre temps_warmup. Retorna estado mutable."""
    cur = con.cursor()
    cc_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}
    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val

    rows = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats=1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN ({','.join(['?']*len(temps_warmup))})
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL + list(temps_warmup)).fetchall()

    ema6 = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    emaL = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)

    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows:
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
        if ema6[ht_n]['fh'] is not None: v_l['vfh'] = ALFA*(xg6_l - ema6[ht_n]['fh'])**2 + (1-ALFA)*v_l['vfh']
        if ema6[at_n]['fa'] is not None: v_v['vfa'] = ALFA*(xg6_v - ema6[at_n]['fa'])**2 + (1-ALFA)*v_v['vfa']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    return {'ema6': ema6, 'emaL': emaL, 'var_eq': var_eq, 'h2h': h2h, 'cc_pl': cc_pl, 'ols_pl': ols_pl}


def evaluar_test_oos(con, estado, temp_test, rho_pl, pesos):
    """Test sobre partidos_historico_externo INNER JOIN cuotas_externas_historico."""
    cur = con.cursor()
    rows = cur.execute(f"""
        SELECT phe.liga, phe.fecha, phe.ht, phe.at, phe.hg, phe.ag,
               phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
               ce.psch, ce.pscd, ce.psca, ce.avgch, ce.avgcd, ce.avgca
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
            AND ce.ht=phe.ht AND ce.at=phe.at
        WHERE phe.has_full_stats=1 AND phe.temp = ?
          AND phe.liga IN ({','.join(['?']*len(LIGAS_TEST))})
          AND ce.psch IS NOT NULL
        ORDER BY phe.fecha ASC
    """, [temp_test] + LIGAS_TEST).fetchall()
    return _scoring_loop(rows, estado, rho_pl, pesos, fuente='oos')


def evaluar_test_in_sample(con, estado, rho_pl, pesos):
    """Test sobre partidos_backtest 2026 (in-sample con cuotas reales)."""
    cur = con.cursor()
    rows = cur.execute(f"""
        SELECT pb.pais AS liga, pb.fecha, pb.local, pb.visita, pb.goles_l, pb.goles_v,
               pb.sot_l, pb.shots_l, pb.corners_l, pb.sot_v, pb.shots_v, pb.corners_v,
               pb.cuota_1, pb.cuota_x, pb.cuota_2, NULL, NULL, NULL
        FROM partidos_backtest pb
        WHERE pb.cuota_1>1 AND pb.cuota_x>1 AND pb.cuota_2>1
          AND pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
          AND pb.sot_l IS NOT NULL AND pb.shots_l IS NOT NULL AND pb.corners_l IS NOT NULL
          AND pb.pais IN ({','.join(['?']*len(LIGAS_TEST))})
          AND substr(pb.fecha, 1, 4) = '2026'
        ORDER BY pb.fecha ASC
    """, LIGAS_TEST).fetchall()
    return _scoring_loop(rows, estado, rho_pl, pesos, fuente='in_sample_2026')


def _scoring_loop(rows, estado, rho_pl, pesos, fuente):
    ema6 = estado['ema6']; emaL = estado['emaL']
    var_eq = estado['var_eq']; h2h = estado['h2h']
    cc_pl = estado['cc_pl']; ols_pl = estado['ols_pl']

    preds = []
    for row in rows:
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
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
            prev.extend(h2h.get(k, []))
        if prev:
            avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
            n_l = sum(1 for p in prev if (p['home']==ht_n and p['hg']>p['ag']) or (p['home']!=ht_n and p['ag']>p['hg']))
            n_x = sum(1 for p in prev if p['hg']==p['ag'])
            f_loc = n_l/len(prev); f_x = n_x/len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26
        v_l_t = var_eq.get(ht_n, {'vfh':0.5}); v_v_t = var_eq.get(at_n, {'vfa':0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        ff = feats_v12(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        v12_payload = pesos.get(liga, pesos.get('global', {}))
        v0_p = probs_dc(xgL_l, xgL_v, rho)
        v12_p = predict_lr(ff, v12_payload) if v12_payload else (1/3, 1/3, 1/3)
        preds.append({'liga': liga, 'real': real, 'cuotas': {'1': c1, 'X': cx, '2': c2},
                      'v0_p': v0_p, 'v12_p': v12_p})

        # Update EMAs (walk-forward)
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
    return preds


def decidir_v0(p): return amax(*p['v0_p'])
def decidir_v12(p): return amax(*p['v12_p'])
def decidir_h4(p, th=H4_THRESH):
    if amax(*p['v12_p']) == 'X' and p['v12_p'][1] > th:
        return 'X'
    return amax(*p['v0_p'])
def decidir_l2(p):
    return amax(*p['v12_p']) if p['liga'] == 'Turquia' else amax(*p['v0_p'])
def decidir_l2_l3(p, th=H4_THRESH):
    if p['liga'] == 'Turquia':
        return amax(*p['v12_p'])
    return decidir_h4(p, th)


ARQUITECTURAS = [
    ('V0',    decidir_v0),
    ('V12',   decidir_v12),
    ('H4_035', decidir_h4),
    ('L2',    decidir_l2),
    ('L2_L3', decidir_l2_l3),
]


def calcular_yields(preds):
    """Por arquitectura: yield agregado + por liga."""
    out = {}
    for nombre, decisor in ARQUITECTURAS:
        profits = []; hit = 0
        for p in preds:
            am = decisor(p)
            won = (am == p['real'])
            profits.append((p['cuotas'][am] - 1) if won else -1)
            if won: hit += 1
        if not profits:
            out[nombre] = {'n': 0, 'yield': None, 'ci_low': None, 'ci_high': None}
            continue
        yld, lo, hi = bootstrap_ci(profits)
        out[nombre] = {
            'n': len(profits), 'hit': round(hit/len(profits), 4),
            'yield': round(yld, 4), 'ci_low': round(lo, 4), 'ci_high': round(hi, 4),
            'sig_95': bool(lo > 0 or hi < 0),
        }
    # X-rescue picks counter (V12 argmax X y P_X > 0.35)
    n_x_rescue = sum(1 for p in preds
                     if amax(*p['v12_p']) == 'X' and p['v12_p'][1] > H4_THRESH)
    out['_meta'] = {'n_total': len(preds), 'n_x_rescue': n_x_rescue,
                    'pct_x_rescue': round(100*n_x_rescue/max(1,len(preds)), 2)}
    return out


def calcular_por_liga(preds):
    """Por liga: yield V0 vs H4 (delta clave)."""
    by_liga = defaultdict(list)
    for p in preds:
        by_liga[p['liga']].append(p)
    out = {}
    for liga, sub in by_liga.items():
        sub_out = {}
        for nombre, decisor in ARQUITECTURAS:
            profits = []; hit = 0
            for p in sub:
                am = decisor(p)
                won = (am == p['real'])
                profits.append((p['cuotas'][am] - 1) if won else -1)
                if won: hit += 1
            if not profits:
                continue
            yld, lo, hi = bootstrap_ci(profits)
            sub_out[nombre] = {
                'n': len(profits), 'hit': round(hit/len(profits), 4),
                'yield': round(yld, 4), 'ci_low': round(lo, 4), 'ci_high': round(hi, 4),
                'sig_95': bool(lo > 0 or hi < 0),
            }
        out[liga] = sub_out
    return out


def main():
    con = sqlite3.connect(DB)
    rho_pl, cc_pl, ols_pl, pesos = cargar_pesos_ols(con)

    payload = {
        'fecha': '2026-04-28',
        'bead': 'adepor-edk Opcion D',
        'h4_threshold': H4_THRESH,
        'descripcion': 'Walk-forward year-by-year + in-sample 2026, threshold FIJO',
        'tests': {},
    }

    # ============ WALK-FORWARD POR TEMP ============
    ventanas = [
        ('test_2022', [2021], 2022),
        ('test_2023', [2021, 2022], 2023),
        ('test_2024', [2021, 2022, 2023], 2024),
    ]

    for nombre, warmup, test_temp in ventanas:
        print('=' * 95)
        print(f"VENTANA: warmup={warmup} -> test={test_temp}")
        print('=' * 95)
        estado = warmup_emas(con, warmup)
        preds = evaluar_test_oos(con, estado, test_temp, rho_pl, pesos)
        if not preds:
            print(f"  N=0 — sin partidos test (revisar coverage cuotas_externas_historico)")
            continue
        agregado = calcular_yields(preds)
        print(f"\nN preds: {len(preds)}  | X-rescue picks: {agregado['_meta']['n_x_rescue']} ({agregado['_meta']['pct_x_rescue']}%)")
        print(f"{'arch':<8} {'N':>5} {'hit':>6} {'yield':>9} {'CI95':>22} {'sig':>5}")
        for arq in ['V0', 'V12', 'H4_035', 'L2', 'L2_L3']:
            m = agregado.get(arq)
            if not m or m.get('yield') is None:
                continue
            ci = f"[{m['ci_low']:+.3f}, {m['ci_high']:+.3f}]"
            sig = '***' if m['sig_95'] else '.'
            print(f"{arq:<8} {m['n']:>5} {m['hit']:>6.3f} {m['yield']:>+9.3f} {ci:>22}  {sig:>5}")
        por_liga = calcular_por_liga(preds)
        print(f"\nPor liga (V0 vs H4_035, delta H4-V0):")
        print(f"{'liga':<14} {'N':>5} {'V0_yld':>9} {'H4_yld':>9} {'delta':>8} {'sig_H4':>7}")
        for liga in sorted(por_liga.keys()):
            v0 = por_liga[liga].get('V0')
            h4 = por_liga[liga].get('H4_035')
            if not v0 or not h4: continue
            delta = h4['yield'] - v0['yield']
            sig = '***' if h4['sig_95'] else '.'
            print(f"{liga:<14} {v0['n']:>5} {v0['yield']:>+9.3f} {h4['yield']:>+9.3f} {delta:>+8.3f}  {sig:>7}")

        payload['tests'][nombre] = {
            'warmup_temps': warmup, 'test_temp': test_temp,
            'agregado': agregado, 'por_liga': por_liga,
        }
        print()

    # ============ IN-SAMPLE 2026 ============
    print('=' * 95)
    print("VENTANA: warmup=[2021,2022,2023,2024] -> test=in_sample_2026 (partidos_backtest)")
    print('=' * 95)
    estado = warmup_emas(con, [2021, 2022, 2023, 2024])
    preds_is = evaluar_test_in_sample(con, estado, rho_pl, pesos)
    if not preds_is:
        print("  N=0 — sin partidos in-sample 2026")
    else:
        agregado_is = calcular_yields(preds_is)
        print(f"\nN preds: {len(preds_is)}  | X-rescue picks: {agregado_is['_meta']['n_x_rescue']} ({agregado_is['_meta']['pct_x_rescue']}%)")
        print(f"{'arch':<8} {'N':>5} {'hit':>6} {'yield':>9} {'CI95':>22} {'sig':>5}")
        for arq in ['V0', 'V12', 'H4_035', 'L2', 'L2_L3']:
            m = agregado_is.get(arq)
            if not m or m.get('yield') is None:
                continue
            ci = f"[{m['ci_low']:+.3f}, {m['ci_high']:+.3f}]"
            sig = '***' if m['sig_95'] else '.'
            print(f"{arq:<8} {m['n']:>5} {m['hit']:>6.3f} {m['yield']:>+9.3f} {ci:>22}  {sig:>5}")
        por_liga_is = calcular_por_liga(preds_is)
        print(f"\nPor liga (V0 vs H4_035):")
        print(f"{'liga':<14} {'N':>5} {'V0_yld':>9} {'H4_yld':>9} {'delta':>8}")
        for liga in sorted(por_liga_is.keys()):
            v0 = por_liga_is[liga].get('V0')
            h4 = por_liga_is[liga].get('H4_035')
            if not v0 or not h4: continue
            delta = h4['yield'] - v0['yield']
            print(f"{liga:<14} {v0['n']:>5} {v0['yield']:>+9.3f} {h4['yield']:>+9.3f} {delta:>+8.3f}")
        payload['tests']['in_sample_2026'] = {
            'warmup_temps': [2021, 2022, 2023, 2024],
            'agregado': agregado_is, 'por_liga': por_liga_is,
        }

    # ============ RESUMEN CROSS-TEMP ============
    print('\n' + '=' * 95)
    print("RESUMEN CROSS-TEMP — H4 thresh=0.35 vs V0 (delta y signo)")
    print('=' * 95)
    print(f"{'window':<22} {'N':>5} {'V0_yld':>9} {'H4_yld':>9} {'delta':>8} {'V0_sig':>7} {'H4_sig':>7}")
    deltas = []
    for nombre, _, _ in ventanas:
        if nombre not in payload['tests']: continue
        ag = payload['tests'][nombre]['agregado']
        v0 = ag.get('V0', {}); h4 = ag.get('H4_035', {})
        if v0.get('yield') is None or h4.get('yield') is None: continue
        delta = h4['yield'] - v0['yield']
        deltas.append((nombre, delta))
        sig_v = '***' if v0.get('sig_95') else '.'
        sig_h = '***' if h4.get('sig_95') else '.'
        print(f"{nombre:<22} {h4['n']:>5} {v0['yield']:>+9.3f} {h4['yield']:>+9.3f} {delta:>+8.3f}  {sig_v:>7}  {sig_h:>7}")
    if 'in_sample_2026' in payload['tests']:
        ag = payload['tests']['in_sample_2026']['agregado']
        v0 = ag.get('V0', {}); h4 = ag.get('H4_035', {})
        if v0.get('yield') is not None and h4.get('yield') is not None:
            delta = h4['yield'] - v0['yield']
            deltas.append(('in_sample_2026', delta))
            sig_v = '***' if v0.get('sig_95') else '.'
            sig_h = '***' if h4.get('sig_95') else '.'
            print(f"{'in_sample_2026':<22} {h4['n']:>5} {v0['yield']:>+9.3f} {h4['yield']:>+9.3f} {delta:>+8.3f}  {sig_v:>7}  {sig_h:>7}")

    n_pos = sum(1 for _, d in deltas if d > 0)
    n_neg = sum(1 for _, d in deltas if d < 0)
    n_zero = sum(1 for _, d in deltas if d == 0)
    print(f"\n>>> {n_pos} ventanas con delta > 0, {n_neg} con delta < 0, {n_zero} sin cambio.")
    if n_pos == len(deltas) and len(deltas) >= 3:
        veredicto = "H4_ROBUSTO_CROSS_TEMP — todas las ventanas mejoran sobre V0. Aplicable."
    elif n_pos > n_neg:
        veredicto = f"H4_DIRECCIONAL_PERO_NO_UNANIME — {n_pos}/{len(deltas)} ventanas positivas. Riesgo."
    else:
        veredicto = "H4_NO_ROBUSTO — flips de signo. NO aplicar."
    print(f">>> Veredicto: {veredicto}")
    payload['veredicto'] = veredicto
    payload['deltas_h4_vs_v0'] = [{'window': n, 'delta': d} for n, d in deltas]

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

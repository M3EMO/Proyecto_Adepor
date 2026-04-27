"""[adepor-617] Audit del yield F2 extendido — diagnostico de:
  1. Skips: que partidos se descartan por falta de EMA (sesgo posible)
  2. Reconciliacion con N=127 original sobre partidos_backtest
  3. Distribucion de cuotas (Pinnacle vs avg) y margen bookie
  4. H4 trigger detail: cuando se activa el X-rescue
  5. Performance por liga + por temp
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
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}

# ============================================================
# Audit 1: skips — quien se queda fuera del warmup
# ============================================================
def audit_skips():
    print("=" * 90)
    print("AUDIT 1 — SKIPS: equipos test 2024 sin EMA en warmup 2021-2023")
    print("=" * 90)
    con = sqlite3.connect(DB); cur = con.cursor()

    # Equipos en warmup
    eq_warmup = set()
    for r in cur.execute("""
        SELECT DISTINCT ht FROM partidos_historico_externo
        WHERE has_full_stats=1 AND temp IN (2021,2022,2023)
          AND liga IN ('Alemania','Argentina','Brasil','Chile','Colombia',
                       'Espana','Francia','Inglaterra','Italia','Turquia')
    """).fetchall():
        eq_warmup.add(limpiar_texto(r[0]))
    for r in cur.execute("""
        SELECT DISTINCT at FROM partidos_historico_externo
        WHERE has_full_stats=1 AND temp IN (2021,2022,2023)
          AND liga IN ('Alemania','Argentina','Brasil','Chile','Colombia',
                       'Espana','Francia','Inglaterra','Italia','Turquia')
    """).fetchall():
        eq_warmup.add(limpiar_texto(r[0]))

    print(f"Equipos en warmup: {len(eq_warmup)}\n")

    # Equipos test 2024 EUR con cuotas que NO estan en warmup
    rows = cur.execute("""
        SELECT phe.liga, phe.ht, phe.at, COUNT(*) AS n_partidos
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
            AND ce.ht=phe.ht AND ce.at=phe.at
        WHERE phe.has_full_stats=1 AND phe.temp=2024
          AND phe.liga IN ('Alemania','Espana','Francia','Inglaterra','Italia','Turquia')
          AND ce.psch IS NOT NULL
        GROUP BY phe.liga, phe.ht, phe.at
    """).fetchall()

    skips_por_liga = defaultdict(int)
    eq_no_warmup = defaultdict(set)
    total = 0
    skip = 0
    for liga, ht, at, n in rows:
        total += n
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if ht_n not in eq_warmup or at_n not in eq_warmup:
            skip += n
            skips_por_liga[liga] += n
            if ht_n not in eq_warmup: eq_no_warmup[liga].add(ht)
            if at_n not in eq_warmup: eq_no_warmup[liga].add(at)

    print(f"Total partidos test 2024 EUR con cuotas: {total}")
    print(f"Skips estimados (al menos 1 equipo sin warmup): {skip}")
    print(f"\nSkips por liga:")
    for liga, n in sorted(skips_por_liga.items(), key=lambda x: -x[1]):
        print(f"  {liga:<12} skip={n:>3}  equipos sin warmup: {sorted(eq_no_warmup[liga])}")

    con.close()
    return skip, eq_no_warmup


# ============================================================
# Audit 2: reconciliacion con partidos_backtest N=127
# ============================================================
def audit_reconcile_n127():
    print("\n" + "=" * 90)
    print("AUDIT 2 — RECONCILIACION partidos_backtest N=127 (cuotas internas)")
    print("=" * 90)
    con = sqlite3.connect(DB); cur = con.cursor()

    rows = cur.execute("""
        SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
          AND cuota_1 > 1 AND cuota_x > 1 AND cuota_2 > 1
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha ASC
    """).fetchall()

    # Por liga + comparar cuota_1 contra cuotas externas
    print(f"partidos_backtest con cuotas: {len(rows)}")
    print("\nPor liga:")
    by_liga = defaultdict(int)
    for r in rows:
        by_liga[r[0]] += 1
    for liga, n in sorted(by_liga.items(), key=lambda x: -x[1]):
        print(f"  {liga:<14} N={n}")

    # JOIN partidos_backtest con cuotas_externas para comparar
    print("\nMatch partidos_backtest <-> cuotas_externas (mismas semanas):")
    q = """
        SELECT pb.pais, pb.fecha, pb.local, pb.visita,
               pb.cuota_1, pb.cuota_x, pb.cuota_2,
               ce.psch, ce.pscd, ce.psca, ce.avgch, ce.avgcd, ce.avgca
        FROM partidos_backtest pb
        LEFT JOIN cuotas_externas_historico ce
            ON ce.liga=pb.pais AND ce.fecha=substr(pb.fecha,1,10)
            AND ce.ht=pb.local AND ce.at=pb.visita
        WHERE pb.cuota_1 > 1
    """
    matches = 0; nomatches = 0
    diffs_h = []; diffs_d = []; diffs_a = []
    samples_nomatch = []
    for r in cur.execute(q).fetchall():
        pais, fecha, local, visita, c1, cx, c2, psch, pscd, psca, avgch, avgcd, avgca = r
        if psch is not None:
            matches += 1
            diffs_h.append(c1 - psch)
            diffs_d.append(cx - pscd)
            diffs_a.append(c2 - psca)
        else:
            nomatches += 1
            if len(samples_nomatch) < 5:
                samples_nomatch.append((pais, fecha[:10], local, visita))
    print(f"  match con cuotas externas: {matches}")
    print(f"  no match: {nomatches}")
    if samples_nomatch:
        print("  muestras no match:")
        for s in samples_nomatch:
            print(f"    {s}")
    if diffs_h:
        print(f"\n  Delta (cuota_interna - PSCH) mean / median / std:")
        print(f"    home: {np.mean(diffs_h):+.3f} / {np.median(diffs_h):+.3f} / {np.std(diffs_h):.3f}")
        print(f"    draw: {np.mean(diffs_d):+.3f} / {np.median(diffs_d):+.3f} / {np.std(diffs_d):.3f}")
        print(f"    away: {np.mean(diffs_a):+.3f} / {np.median(diffs_a):+.3f} / {np.std(diffs_a):.3f}")
        # Margen overround comparison
        over_int = []; over_ps = []
        for r in cur.execute(q).fetchall():
            _, _, _, _, c1, cx, c2, psch, pscd, psca, _, _, _ = r
            if c1 and cx and c2:
                over_int.append(1/c1 + 1/cx + 1/c2)
            if psch and pscd and psca:
                over_ps.append(1/psch + 1/pscd + 1/psca)
        print(f"\n  Overround mean (1=fair, 1.05=5% bookie margin):")
        print(f"    interno (cuotas backtest): {np.mean(over_int):.4f}  (n={len(over_int)})")
        print(f"    Pinnacle closing:          {np.mean(over_ps):.4f}  (n={len(over_ps)})")
        print(f"  Diff overround: {np.mean(over_int) - np.mean(over_ps):+.4f}")

    con.close()


# ============================================================
# Audit 3: H4 trigger detail
# ============================================================
def audit_h4_trigger():
    print("\n" + "=" * 90)
    print("AUDIT 3 — H4 X-rescue: cuando se activa")
    print("=" * 90)
    out = json.loads((ROOT / "analisis" / "yield_v0_v12_F2_extendido_1806.json").read_text(encoding='utf-8'))
    h4 = out['resumen']['H4']
    v12 = out['resumen']['V12']
    v0 = out['resumen']['V0']
    print(f"V0  argmax_X: {v0['argmax_dist']['X']:.3%}")
    print(f"V12 argmax_X: {v12['argmax_dist']['X']:.3%}")
    print(f"H4  argmax_X: {h4['argmax_dist']['X']:.3%}")
    print()
    print(f"H4 pickea X cuando: argmax_v12=='X' AND P_v12(X) > 0.30")
    print(f"V12 pickea X en {v12['argmax_dist']['X']*v12['n']:.0f} de {v12['n']} ({v12['argmax_dist']['X']:.1%}).")
    print(f"H4  pickea X en {h4['argmax_dist']['X']*h4['n']:.0f} de {h4['n']} ({h4['argmax_dist']['X']:.1%}).")
    print(f"-> Pasan filtro P_v12(X)>0.30: ~{int(h4['argmax_dist']['X']*h4['n'])} de {int(v12['argmax_dist']['X']*v12['n'])}")
    diff_v12 = (v12['argmax_dist']['X'] - h4['argmax_dist']['X']) * h4['n']
    print(f"   Bloqueados por threshold: ~{int(diff_v12)}")


# ============================================================
# Audit 4: por liga + por mes (heterogeneidad)
# ============================================================
def audit_per_liga():
    print("\n" + "=" * 90)
    print("AUDIT 4 — Yield V0 / V12 / H4 desglosado por liga (test 2024)")
    print("=" * 90)
    print("(Re-corre el walk-forward y agrupa por liga)")

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

    # Importar funciones
    sys.path.insert(0, str(ROOT / "analisis"))
    from yield_v0_v12_backtest_extendido import (
        probs_dc, probs_skellam, predict_lr, feats_v12,
        calc_xg_legacy, calc_xg_v6, ajustar, real_o, amax,
        H4_X_THRESHOLD,
    )

    LIGAS_HIST_FULL = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
                       'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
    LIGAS_TEST = ['Alemania', 'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']

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

    # Test
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

    by_liga = defaultdict(lambda: {'V0': {'n':0,'hit':0,'profit':0.0},
                                    'V12': {'n':0,'hit':0,'profit':0.0,'argmax_x':0},
                                    'H4': {'n':0,'hit':0,'profit':0.0,'argmax_x':0}})

    for row in rows_test:
        liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac, psch, pscd, psca, avgch, avgcd, avgca = row
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
        am_v0 = amax(*v0_p)
        am_v12 = amax(*v12_p)

        # H4
        if am_v12 == 'X' and v12_p[1] > H4_X_THRESHOLD:
            am_h4 = 'X'
        else:
            am_h4 = am_v0
        cuotas = {'1': c1, 'X': cx, '2': c2}

        for arch, am in [('V0', am_v0), ('V12', am_v12), ('H4', am_h4)]:
            d = by_liga[liga][arch]
            d['n'] += 1
            won = (am == real)
            if won: d['hit'] += 1
            d['profit'] += (cuotas[am] - 1) if won else -1
            if 'argmax_x' in d and am == 'X': d['argmax_x'] += 1

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

    print()
    print(f"{'liga':<12} {'arch':<5}  {'N':>4} {'hit':>6} {'yield':>8} {'X%':>6}")
    print("-" * 55)
    for liga in sorted(by_liga):
        for arch in ['V0', 'V12', 'H4']:
            d = by_liga[liga][arch]
            if d['n'] == 0: continue
            x_pct = d.get('argmax_x', 0) / d['n']
            print(f"{liga:<12} {arch:<5}  {d['n']:>4d} {d['hit']/d['n']:>6.3f} "
                  f"{d['profit']/d['n']:>+8.3f} {x_pct:>5.1%}")
        print()

    con.close()


if __name__ == "__main__":
    audit_skips()
    audit_reconcile_n127()
    audit_h4_trigger()
    audit_per_liga()

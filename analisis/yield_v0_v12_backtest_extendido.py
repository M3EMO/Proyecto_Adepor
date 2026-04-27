"""[adepor-617] F2 plan_ampliacion_cuotas — Yield walk-forward extendido N>=500.

Fuente de cuotas: cuotas_externas_historico (8,600 mmz4281 EUR + 967 NOR).
Fuente de stats: partidos_historico_externo (mismo source via JOIN 100% match).

Estrategia walk-forward:
  - Warmup EMA: 2021-2023 (toda la data full_stats, todas las ligas para contexto)
  - Test:       2024 EUR (6 ligas mmz4281 con stats + cuotas: E0,D1,I1,SP1,F1,T1)
  - Para cada partido test: predict ANTES de update EMA -> NO leak.

Arquitecturas evaluadas:
  V0  = Poisson DC con xg_legacy
  V6  = Poisson DC con xg OLS recalibrado (v6_shadow)
  V7  = Skellam con xg OLS recalibrado
  V12 = LR multinomial 13 features (lr_v12_weights por liga + global pool)
  H4  = V0 default + override 'X' si V12 dice argmax=X Y P(X)>0.30 (PROPOSAL adepor-617)

Strategies:
  A: stake=1 sobre argmax SIEMPRE
  B: stake=1 sobre argmax SOLO si prob_modelo * cuota > 1.05 (EV > 5%)

Cuota usada: psch (Pinnacle closing) — gold standard. Fallback: avgch.

Bootstrap CI95 sobre yield via resampling con reposicion (B=1000).
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

# Ligas con full stats Y cuotas externas
LIGAS_HIST_FULL = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
                   'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
# Ligas en test (las 6 EUR mmz4281 con cuotas externas garantizadas)
LIGAS_TEST = ['Alemania', 'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']

ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}
EV_THRESHOLD = 1.05

# Walk-forward split
TEMPS_WARMUP = [2021, 2022, 2023]
TEMPS_TEST   = [2024]

# H4 X-rescue threshold
H4_X_THRESHOLD = 0.30

# Bootstrap
BOOTSTRAP_N = 1000
RANDOM_SEED = 42

# ============================================================
# Modelos (copiados sin cambios del original)
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


# ============================================================
# Bootstrap CI
# ============================================================
def bootstrap_yield_ci(profits, n_boot=BOOTSTRAP_N, seed=RANDOM_SEED):
    """Bootstrap percentil 95% sobre yield = mean(profits)."""
    if not profits:
        return None, None, None
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
# Walk-forward
# ============================================================
def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    # Cargar coefs
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
        clave, scope, txt = r
        if txt: pesos.setdefault(clave, {})[scope] = json.loads(txt)

    print("=" * 100)
    print(f"YIELD F2 EXTENDIDO — partidos_historico_externo + cuotas_externas_historico")
    print(f"Warmup EMAs: {TEMPS_WARMUP}    Test: {TEMPS_TEST}")
    print(f"H4 X-threshold: {H4_X_THRESHOLD}    EV-min: {EV_THRESHOLD}")
    print("=" * 100)

    # Cargar warmup completo (TODA la data 2021-2023 con full_stats)
    rows_warmup = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN ({','.join(['?']*len(TEMPS_WARMUP))})
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL + TEMPS_WARMUP).fetchall()

    print(f"Warmup partidos (2021-2023, todas las ligas full_stats): {len(rows_warmup)}")

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

    print(f"  EMAs warmup OK. Equipos con EMA: {len(ema6)}\n")

    # Cargar test 2024 con cuotas via JOIN
    rows_test = cur.execute(f"""
        SELECT
            phe.liga, phe.fecha, phe.ht, phe.at,
            phe.hg, phe.ag,
            phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
            ce.psch, ce.pscd, ce.psca,
            ce.avgch, ce.avgcd, ce.avgca,
            ce.maxch, ce.maxcd, ce.maxca
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga = phe.liga
           AND ce.fecha = substr(phe.fecha, 1, 10)
           AND ce.ht = phe.ht
           AND ce.at = phe.at
        WHERE phe.has_full_stats = 1
          AND phe.hst IS NOT NULL AND phe.hs IS NOT NULL AND phe.hc IS NOT NULL
          AND phe.hg IS NOT NULL AND phe.ag IS NOT NULL
          AND phe.liga IN ({','.join(['?']*len(LIGAS_TEST))})
          AND phe.temp IN ({','.join(['?']*len(TEMPS_TEST))})
          AND ce.psch IS NOT NULL
        ORDER BY phe.fecha ASC
    """, LIGAS_TEST + TEMPS_TEST).fetchall()

    print(f"Test partidos 2024 EUR con cuotas PSCH: {len(rows_test)}\n")

    archs = ['V0', 'V6', 'V7', 'V12', 'H4']
    stats = {a: {'n': 0, 'hit': 0, 'profits_A': [], 'n_B': 0, 'hit_B': 0, 'profits_B': [],
                  'argmax': {'1': 0, 'X': 0, '2': 0}} for a in archs}
    n_skip = 0

    for row in rows_test:
        (liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac,
         psch, pscd, psca, avgch, avgcd, avgca, maxch, maxcd, maxca) = row

        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: n_skip += 1; continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v:
            n_skip += 1; continue
        if any(e6_l.get(k) is None for k in ('fh', 'ch')) or any(e6_v.get(k) is None for k in ('fa', 'ca')):
            n_skip += 1; continue
        if any(eL_l.get(k) is None for k in ('fh', 'ch')) or any(eL_v.get(k) is None for k in ('fa', 'ca')):
            n_skip += 1; continue

        # Cuotas (PSCH preferida; fallback AVG)
        c1 = psch if psch else avgch
        cx = pscd if pscd else avgcd
        c2 = psca if psca else avgca
        if not (c1 and cx and c2 and c1 > 1 and cx > 1 and c2 > 1):
            n_skip += 1; continue

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

        v12_payload = pesos.get('lr_v12_weights', {}).get(liga, pesos.get('lr_v12_weights', {}).get('global', {}))

        probs = {
            'V0': probs_dc(xgL_l, xgL_v, rho),
            'V6': probs_dc(xg6_l, xg6_v, rho),
            'V7': probs_skellam(xg6_l, xg6_v),
            'V12': predict_lr(ff, v12_payload),
        }
        # H4: V0 default + override X si V12 dice X y P_v12(X) > threshold
        v0_p1, v0_px, v0_p2 = probs['V0']
        v12_p1, v12_px, v12_p2 = probs['V12']
        am_v12 = amax(v12_p1, v12_px, v12_p2)
        if am_v12 == 'X' and v12_px > H4_X_THRESHOLD:
            # H4 picks X usando prob de V12 (mas confiable para EV en X)
            probs['H4'] = (v0_p1, v12_px, v0_p2)  # solo P(X) override
        else:
            probs['H4'] = probs['V0']

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
            profit_A = (cuota_am - 1) if won else -1
            stats[a]['profits_A'].append(profit_A)
            ev = prob_am * cuota_am
            if ev > EV_THRESHOLD:
                stats[a]['n_B'] += 1
                if won: stats[a]['hit_B'] += 1
                stats[a]['profits_B'].append(profit_A)

        # Update EMAs con resultado real (expanding window)
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

    n_eval = sum(s['n'] for s in stats.values())//len(archs)
    print(f"Test evaluado: {n_eval}  Skip: {n_skip}\n")

    # === Reporte ===
    print("=" * 110)
    print(f"{'arch':<6s} {'N':>5s} {'hit':>6s} {'%X':>5s} {'yield_A':>9s} {'CI95_A':>20s} | "
          f"{'N_B':>5s} {'hit_B':>6s} {'yield_B':>9s} {'CI95_B':>20s}")
    print("-" * 110)

    resumen = {}
    for a in archs:
        s = stats[a]; n = s['n']
        if n == 0: continue
        hit = s['hit']/n
        yA, lo_A, hi_A = bootstrap_yield_ci(s['profits_A'])
        yB, lo_B, hi_B = bootstrap_yield_ci(s['profits_B']) if s['n_B'] > 0 else (0, 0, 0)
        hitB = (s['hit_B']/s['n_B']) if s['n_B'] > 0 else 0
        pX = s['argmax']['X']/n
        ci_a_str = f'[{lo_A:+.3f}, {hi_A:+.3f}]'
        ci_b_str = f'[{lo_B:+.3f}, {hi_B:+.3f}]' if s['n_B'] > 0 else 'n/a'
        print(f"{a:<6s} {n:>5d} {hit:>6.3f} {pX:>4.1%} {yA:>+9.3f} {ci_a_str:>20s} | "
              f"{s['n_B']:>5d} {hitB:>6.3f} {yB:>+9.3f} {ci_b_str:>20s}")
        resumen[a] = {
            'n': n, 'hit': hit,
            'yield_A': yA, 'ci_A_low': lo_A, 'ci_A_high': hi_A,
            'n_B': s['n_B'], 'hit_B': hitB,
            'yield_B': yB, 'ci_B_low': lo_B, 'ci_B_high': hi_B,
            'argmax_dist': {k: v/n for k, v in s['argmax'].items()},
        }

    print(f"\nNota: yield_A = stake fijo argmax SIEMPRE. yield_B = solo si prob*cuota > {EV_THRESHOLD}.")
    print(f"      CI95 = bootstrap percentil con B={BOOTSTRAP_N} resamples.")

    print(f"\nDistribucion argmax:")
    for a in archs:
        s = stats[a]; n = s['n']
        if n == 0: continue
        print(f"  {a:<6s} 1={s['argmax']['1']/n:>5.1%}  X={s['argmax']['X']/n:>5.1%}  2={s['argmax']['2']/n:>5.1%}")

    # === Persistir resumen JSON ===
    out_path = ROOT / "analisis" / f"yield_v0_v12_F2_extendido_{n_eval}.json"
    out = {
        'fecha_corrida': '2026-04-26',
        'bead_id': 'adepor-617',
        'fase': 'F2_plan_ampliacion_cuotas',
        'config': {
            'temps_warmup': TEMPS_WARMUP,
            'temps_test': TEMPS_TEST,
            'ligas_test': LIGAS_TEST,
            'ev_threshold': EV_THRESHOLD,
            'h4_x_threshold': H4_X_THRESHOLD,
            'bootstrap_n': BOOTSTRAP_N,
            'cuota_principal': 'PSCH (Pinnacle closing)',
        },
        'n_warmup': len(rows_warmup),
        'n_test_query': len(rows_test),
        'n_test_evaluated': n_eval,
        'n_skip': n_skip,
        'resumen': resumen,
    }
    out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f"\nJSON persistido: {out_path}")

    con.close()


if __name__ == "__main__":
    main()

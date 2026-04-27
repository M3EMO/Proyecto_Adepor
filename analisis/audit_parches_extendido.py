"""[adepor-2yo] Audit parches HG + Fix#5 OOS sobre V0/V6/V7/V12/V12b1/V12b2/V12b3.

Para cada arquitectura, aplicamos:
  raw          = sin parches
  +HG          = + Hallazgo G (boost p1 segun freq_real_local liga, factor 0.50)
  +F5          = + Fix #5 (si p1 o p2 en [0.40, 0.50): suma 0.042, renorm)
  +HG+F5       = ambos

Para V12 y V12b: aplicar parches sobre las probs softmax output.
Test OOS 2024 con EMA legacy + V6 train-only congelado al 2023-12-31.
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
N_MIN_HG = 50
BOOST_G_FRAC = 0.50
CAL_BUCKET_MIN = 0.40; CAL_BUCKET_MAX = 0.50; CAL_CORRECCION = 0.042
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


def poisson(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError): return 0.0


def tau(i, j, l, v, rho):
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
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def probs_skellam(xg_l, xg_v, max_g=10):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p_h = p_d = p_a = 0.0
    for d in range(-max_g, max_g + 1):
        p_d_v = sum(poisson(d + y, xg_l) * poisson(y, xg_v) for y in range(max(0, -d), max_g + 1))
        if d > 0: p_h += p_d_v
        elif d == 0: p_d += p_d_v
        else: p_a += p_d_v
    s = p_h + p_d + p_a
    return (p_h/s, p_d/s, p_a/s) if s > 0 else (1/3, 1/3, 1/3)


def aplicar_HG(p1, px, p2, freq_real, n_liga):
    if n_liga < N_MIN_HG: return p1, px, p2
    gap = freq_real - p1
    if gap < 0.01: return p1, px, p2
    boost = gap * BOOST_G_FRAC
    p1_n = min(p1 + boost, 0.95); delta = p1_n - p1
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    px_n = max(0.01, px - delta * peso_px); p2_n = max(0.01, p2 - delta * (1 - peso_px))
    t = p1_n + px_n + p2_n
    return p1_n / t, px_n / t, p2_n / t


def aplicar_F5(p1, px, p2):
    p1_c, p2_c = p1, p2
    if CAL_BUCKET_MIN <= p1 < CAL_BUCKET_MAX: p1_c = p1 + CAL_CORRECCION
    if CAL_BUCKET_MIN <= p2 < CAL_BUCKET_MAX: p2_c = p2 + CAL_CORRECCION
    if p1_c == p1 and p2_c == p2: return p1, px, p2
    t = p1_c + px + p2_c
    return (p1_c/t, px/t, p2_c/t) if t > 0 else (p1, px, p2)


def predict_lr(feats, payload):
    W = np.array(payload['W']); mean = np.array(payload['mean']); std = np.array(payload['std'])
    x = np.array(feats, dtype=float); xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    L = W @ xs; L -= L.max(); e = np.exp(L); s = e.sum()
    return (e[0]/s, e[1]/s, e[2]/s) if s > 0 else (1/3, 1/3, 1/3)


def feats_full(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v)/2.0, xg_l*xg_v,
            h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def feats_sin_h2h(xg_l, xg_v, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v)/2.0, xg_l*xg_v,
            var_l, var_v, float(mes)]


def calc_xg_v6(sot, shots, corners, goles, liga, ols):
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    c = ols.get(liga, OLS_GLOBAL)
    xg_calc = max(0.0, sot*c['beta_sot'] + shots_off*c['beta_off'] + corners*c['coef_corner'] + c['intercept'])
    if xg_calc == 0 and goles > 0: return goles
    return (xg_calc * 0.70) + (goles * 0.30)


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


def real_o(hg, ag): return "1" if hg > ag else ("2" if hg < ag else "X")


def brier(p1, px, p2, r):
    return ((p1 - (1 if r == "1" else 0))**2 + (px - (1 if r == "X" else 0))**2 +
            (p2 - (1 if r == "2" else 0))**2)


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

    # Cargar V12, V12b1, V12b2, V12b3
    pesos = {}
    for r in cur.execute("""SELECT clave, scope, valor_texto FROM config_motor_valores
                             WHERE clave IN ('lr_v12_weights','lr_v12b1_weights','lr_v12b2_weights','lr_v12b3_weights')"""):
        clave, scope, txt = r
        if txt: pesos.setdefault(clave, {})[scope] = json.loads(txt)

    print("=" * 100)
    print("AUDIT PARCHES OOS sobre V0 / V6 / V7 / V12 / V12b1 / V12b2 / V12b3")
    print("=" * 100)

    # Cargar partidos
    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({}) ORDER BY fecha ASC
    """.format(','.join(['?']*len(LIGAS))), LIGAS).fetchall()

    train = [r for r in rows if r[1] in TRAIN_TEMP]
    test = [r for r in rows if r[1] in TEST_TEMP]

    # freq_real_local por liga sobre train
    n_lg = defaultdict(int); n_lw = defaultdict(int)
    for liga, _, _, _, _, hg, ag, *_ in train:
        n_lg[liga] += 1
        if hg > ag: n_lw[liga] += 1
    freq_pl = {liga: n_lw[liga]/n_lg[liga] if n_lg[liga] else 0.45 for liga in LIGAS}

    # Build EMAs train-only (V6 + legacy)
    print("Construyendo EMAs train-only V6 + legacy...")
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

    # Eval test
    print("Evaluando test 2024...\n")
    archs = ['V0', 'V6', 'V7', 'V12', 'V12b1', 'V12b2', 'V12b3']
    parches = ['raw', 'HG', 'F5', 'HG+F5']
    stats = {a: {p: {'n': 0, 'hit': 0, 'br': 0.0, 'argmax': {'1':0,'X':0,'2':0}} for p in parches} for a in archs}
    real_count = {'1': 0, 'X': 0, '2': 0}; n_eval = 0

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
        real = real_o(hg, ag); n_eval += 1; real_count[real] += 1

        # Compute base probs
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

        ff = feats_full(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        fs = feats_sin_h2h(xg6_l, xg6_v, v_l_t['vfh'], v_v_t['vfa'], mes)

        probs_base = {
            'V0': probs_dc(xgL_l, xgL_v, rho),
            'V6': probs_dc(xg6_l, xg6_v, rho),
            'V7': probs_skellam(xg6_l, xg6_v),
            'V12': predict_lr(ff, pesos.get('lr_v12_weights', {}).get(liga, pesos.get('lr_v12_weights', {}).get('global', {}))),
            'V12b1': predict_lr(ff, pesos.get('lr_v12b1_weights', {}).get('global', {})),
            'V12b2': predict_lr(fs, pesos.get('lr_v12b2_weights', {}).get('global', {})),
            'V12b3': predict_lr(ff, pesos.get('lr_v12b3_weights', {}).get('global', {})),
        }

        f_real = freq_pl.get(liga, 0.45); n_l_liga = n_lg.get(liga, 0)
        for arch in archs:
            p = probs_base[arch]
            for parche in parches:
                if parche == 'raw': pp = p
                elif parche == 'HG': pp = aplicar_HG(*p, f_real, n_l_liga)
                elif parche == 'F5': pp = aplicar_F5(*p)
                else:  # HG+F5
                    pp_int = aplicar_HG(*p, f_real, n_l_liga)
                    pp = aplicar_F5(*pp_int)
                am = amax(*pp)
                s = stats[arch][parche]
                s['n'] += 1; s['hit'] += (1 if am == real else 0); s['br'] += brier(*pp, real)
                s['argmax'][am] += 1

    print(f"N_eval: {n_eval}  Base: 1={real_count['1']/n_eval:.3f} X={real_count['X']/n_eval:.3f} 2={real_count['2']/n_eval:.3f}\n")

    # === REPORTE: hit rate ===
    print("=" * 90)
    print(f"{'arch':<8s} | " + " | ".join(f"{p:^16s}" for p in parches))
    print(f"{'':<8s} | " + " | ".join(f"{'hit':>5s} {'Brier':>5s} {'%X':>4s}" for _ in parches))
    print("-" * 90)
    for a in archs:
        line = f"{a:<8s} |"
        for p in parches:
            s = stats[a][p]
            n = s['n']; hit = s['hit']/n if n else 0
            br = s['br']/n if n else 0
            pX = s['argmax']['X']/n*100 if n else 0
            line += f" {hit:>5.3f} {br:>5.3f} {pX:>3.1f}% |"
        print(line)

    # === Tabla resumen: delta hit y delta Brier ===
    print(f"\n{'arch':<8s} {'hit_raw':>8s} {'Δ_HG':>7s} {'Δ_F5':>7s} {'Δ_HGF5':>8s} {'br_raw':>8s} {'Δbr_HG':>8s} {'Δbr_F5':>8s} {'Δbr_HGF5':>9s}")
    print("-" * 90)
    for a in archs:
        n = stats[a]['raw']['n']
        if n == 0: continue
        hr = stats[a]['raw']['hit']/n; br0 = stats[a]['raw']['br']/n
        d_hg = stats[a]['HG']['hit']/n - hr
        d_f5 = stats[a]['F5']['hit']/n - hr
        d_hgf5 = stats[a]['HG+F5']['hit']/n - hr
        db_hg = stats[a]['HG']['br']/n - br0
        db_f5 = stats[a]['F5']['br']/n - br0
        db_hgf5 = stats[a]['HG+F5']['br']/n - br0
        print(f"{a:<8s} {hr:>8.3f} {d_hg*100:>+5.2f}pp {d_f5*100:>+5.2f}pp {d_hgf5*100:>+6.2f}pp "
              f"{br0:>8.4f} {db_hg:>+8.4f} {db_f5:>+8.4f} {db_hgf5:>+9.4f}")

    print(f"\nVeredicto: HG empeora si Δ_HG < 0. F5 inocuo si Δ_F5 ≈ 0.")
    print(f"Mejor arch sin parches: {max(archs, key=lambda a: stats[a]['raw']['hit']/stats[a]['raw']['n'] if stats[a]['raw']['n'] else 0)}")

    con.close()


if __name__ == "__main__":
    main()

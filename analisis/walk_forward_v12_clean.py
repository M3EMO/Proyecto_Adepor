"""[adepor-2yo] Walk-forward OOS con muestra LIMPIA.

Filtros aplicados sobre walk_forward_v12_oos.py:
  F1: TRAIN exige hst>=1 AND hs>=1 AND hc>=1 (excluir zeros sospechosos)
  F2: TEST evaluado solo si N_home_train_local >= 10 AND N_away_train_visita >= 10
  F3: Reporta tambien sin filtros como referencia
"""
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
TRAIN_TEMP = {2021, 2022, 2023}
TEST_TEMP = {2024}
ALFA = 0.15
N_MIN_TRAIN = 10  # F2: equipo necesita >=10 partidos train EMA-warmup
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


def poisson_pmf(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError): return 0.0


def tau_dc(i, j, l, v, rho):
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
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def softmax(Z):
    Z = Z - Z.max(axis=-1, keepdims=True)
    e = np.exp(Z); return e / e.sum(axis=-1, keepdims=True)


def fit_lr(X, Y, lr=0.05, n_iter=1500, ridge=0.1):
    N, D = X.shape; K = Y.shape[1]
    W = np.zeros((K, D)); losses = []
    for it in range(n_iter):
        P = softmax(X @ W.T)
        loss = -np.mean(np.sum(Y * np.log(np.clip(P, 1e-12, 1)), axis=1)) + 0.5 * ridge * np.sum(W * W)
        losses.append(loss)
        dW = (P - Y).T @ X / N + ridge * W
        W -= lr * dW
        if it > 0 and losses[-1] > losses[-2] * 1.5: lr *= 0.5
    return W, losses[-1]


def stand(X, mean=None, std=None):
    X = np.array(X, dtype=float)
    if mean is None:
        mean = X.mean(axis=0); std = X.std(axis=0)
        std[std == 0] = 1.0; std[0] = 1.0; mean[0] = 0.0
    Xs = X.copy(); Xs[:, 1:] = (X[:, 1:] - mean[1:]) / std[1:]
    return Xs, mean, std


def predict(feats, W, mean, std):
    x = np.array(feats, dtype=float); xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    L = W @ xs; L -= L.max(); e = np.exp(L); s = e.sum()
    return (e[0]/s, e[1]/s, e[2]/s) if s > 0 else (1/3, 1/3, 1/3)


def feats_v12(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v)/2.0, xg_l*xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def real_o(hg, ag): return "1" if hg > ag else ("2" if hg < ag else "X")


def brier(p1, px, p2, r):
    return ((p1 - (1 if r == "1" else 0))**2 + (px - (1 if r == "X" else 0))**2 +
            (p2 - (1 if r == "2" else 0))**2)


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


def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    # OLS coefs
    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                 'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_leg_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}

    print("=" * 100)
    print("WALK-FORWARD OOS LIMPIO  Train 2021-23 / Test 2024")
    print("Filtros: F1 hst>=1 AND hs>=1 AND hc>=1 train | F2 N_train_eq >= 10")
    print("=" * 100)

    # =================== Variante A: SIN filtros (referencia) ===================
    # =================== Variante B: CON filtros F1+F2          ===================

    for variant_name, apply_f1 in [('SIN_FILTROS', False), ('CON_F1_F2', True)]:
        print(f"\n{'='*60}")
        print(f"VARIANTE: {variant_name}")
        print(f"{'='*60}")

        # Load
        sql_filter = "AND hst >= 1 AND hs >= 1 AND hc >= 1" if apply_f1 else ""
        rows = cur.execute(f"""
            SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
            FROM partidos_historico_externo
            WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
              {sql_filter}
              AND liga IN ({','.join(['?']*len(LIGAS))})
            ORDER BY fecha ASC
        """, LIGAS).fetchall()

        train = [r for r in rows if r[1] in TRAIN_TEMP]
        test = [r for r in rows if r[1] in TEST_TEMP]
        print(f"  Train: {len(train)}  Test: {len(test)}")

        # Build EMAs train + var + H2H + train dataset
        ema = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None, 'n_h': 0, 'n_a': 0})
        ema_leg = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
        var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
        h2h = defaultdict(list)
        train_data = []

        for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train:
            ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
            if not ht_n or not at_n: continue
            e_l = ema[ht_n]; e_v = ema[at_n]

            if e_l['fh'] is not None and e_v['fa'] is not None:
                xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
                xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
                prev = []
                for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
                    for p in h2h.get(k, []):
                        if p['fecha'] < fecha: prev.append(p)
                if prev:
                    avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
                    n_l = sum(1 for p in prev if (p['home']==ht_n and p['hg']>p['ag']) or (p['home']!=ht_n and p['ag']>p['hg']))
                    n_x = sum(1 for p in prev if p['hg']==p['ag'])
                    f_loc = n_l/len(prev); f_x = n_x/len(prev)
                else:
                    avg_g, f_loc, f_x = 2.7, 0.45, 0.26
                v_l = var_eq[ht_n]; v_v = var_eq[at_n]
                mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
                ff = feats_v12(xg_l, xg_v, avg_g, f_loc, f_x, v_l['vfh'], v_v['vfa'], mes)
                real = real_o(hg, ag)
                train_data.append((liga, ff, real, ht_n, at_n))

            xg_v6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
            xg_v6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
            cc_leg = cc_leg_pl.get(liga, 0.02)
            xg_leg_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc_leg), hg, ag)
            xg_leg_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc_leg), ag, hg)

            v_l = var_eq[ht_n]; v_v = var_eq[at_n]
            if e_l['fh'] is not None: v_l['vfh'] = ALFA*(xg_v6_l - e_l['fh'])**2 + (1-ALFA)*v_l['vfh']
            if e_v['fa'] is not None: v_v['vfa'] = ALFA*(xg_v6_v - e_v['fa'])**2 + (1-ALFA)*v_v['vfa']

            for em, lo, vi in [(ema, xg_v6_l, xg_v6_v), (ema_leg, xg_leg_l, xg_leg_v)]:
                el = em[ht_n]; ev = em[at_n]
                if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
                else:
                    el['fh'] = ALFA*lo + (1-ALFA)*el['fh']
                    el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
                if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
                else:
                    ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']
                    ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
                if em is ema:
                    el['n_h'] = el.get('n_h', 0) + 1
                    ev['n_a'] = ev.get('n_a', 0) + 1
            h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

        # Train V12 LR pool global con ridge=0.1
        X_tr = np.array([d[1] for d in train_data])
        Y_tr = np.zeros((len(train_data), 3))
        for i, d in enumerate(train_data):
            Y_tr[i, {"1": 0, "X": 1, "2": 2}[d[2]]] = 1.0
        X_s, mean_s, std_s = stand(X_tr)
        W_v12, _ = fit_lr(X_s, Y_tr, ridge=0.1)
        print(f"  V12 LR pool global trained on N={len(train_data)}")

        # Eval test
        stats = {a: {'n': 0, 'hit': 0, 'br': 0.0, 'argmax': {'1':0,'X':0,'2':0}, 'hit_x': 0}
                 for a in ['V0', 'V6', 'V12']}
        n_skip_f2 = 0; n_eval = 0
        real_count = {'1': 0, 'X': 0, '2': 0}

        for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in test:
            ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
            if not ht_n or not at_n: continue
            e_l = ema.get(ht_n); e_v = ema.get(at_n)
            if not e_l or not e_v: continue
            if any(e_l.get(k) is None for k in ('fh', 'ch')) or any(e_v.get(k) is None for k in ('fa', 'ca')):
                continue
            # F2: N_train minimo
            if apply_f1:
                if e_l.get('n_h', 0) < N_MIN_TRAIN or e_v.get('n_a', 0) < N_MIN_TRAIN:
                    n_skip_f2 += 1; continue

            xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
            xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
            rho = rho_pl.get(liga, -0.04)
            real = real_o(hg, ag)
            n_eval += 1; real_count[real] += 1

            # V0 legacy
            el_leg = ema_leg.get(ht_n, {}); ev_leg = ema_leg.get(at_n, {})
            if all(el_leg.get(k) is not None for k in ('fh','ch')) and all(ev_leg.get(k) is not None for k in ('fa','ca')):
                xg_leg_l = max(0.10, (el_leg['fh'] + ev_leg['ca']) / 2.0)
                xg_leg_v = max(0.10, (ev_leg['fa'] + el_leg['ch']) / 2.0)
                p_v0 = probs_dc(xg_leg_l, xg_leg_v, rho)
                am = amax(*p_v0)
                stats['V0']['n'] += 1
                stats['V0']['hit'] += (1 if am == real else 0)
                stats['V0']['br'] += brier(*p_v0, real)
                stats['V0']['argmax'][am] += 1
                if am == 'X' and real == 'X': stats['V0']['hit_x'] += 1

            # V6 OLS+DC
            p_v6 = probs_dc(xg_l, xg_v, rho)
            am = amax(*p_v6)
            stats['V6']['n'] += 1
            stats['V6']['hit'] += (1 if am == real else 0)
            stats['V6']['br'] += brier(*p_v6, real)
            stats['V6']['argmax'][am] += 1
            if am == 'X' and real == 'X': stats['V6']['hit_x'] += 1

            # V12 LR pool global
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
            v_l_t = var_eq.get(ht_n, {'vfh': 0.5}); v_v_t = var_eq.get(at_n, {'vfa': 0.5})
            mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
            ff = feats_v12(xg_l, xg_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
            p_v12 = predict(ff, W_v12, mean_s, std_s)
            am = amax(*p_v12)
            stats['V12']['n'] += 1
            stats['V12']['hit'] += (1 if am == real else 0)
            stats['V12']['br'] += brier(*p_v12, real)
            stats['V12']['argmax'][am] += 1
            if am == 'X' and real == 'X': stats['V12']['hit_x'] += 1

        print(f"  N_eval: {n_eval}  N_skip_F2: {n_skip_f2}")
        print(f"  Base: 1={real_count['1']/n_eval:.3f} X={real_count['X']/n_eval:.3f} 2={real_count['2']/n_eval:.3f}")
        print()
        print(f"  {'arch':<6s} {'N':>5s} {'hit':>6s} {'Brier':>7s} {'%X':>6s} {'prec_X':>8s}")
        for a in ['V0', 'V6', 'V12']:
            s = stats[a]; n = s['n']
            if n == 0: continue
            hit = s['hit']/n; br = s['br']/n; pX = s['argmax']['X']/n
            nx = s['argmax']['X']
            prec = s['hit_x']/nx if nx else 0
            print(f"  {a:<6s} {n:>5d} {hit:>6.3f} {br:>7.4f} {pX:>6.3f} {prec:>8.3f}")

    con.close()


if __name__ == "__main__":
    main()

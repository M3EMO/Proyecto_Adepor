"""[adepor-d7h] Calibrar y persistir V12b1 / V12b2 / V12b3 sobre histórico completo.

V12b1 = V12 features full pero pool global con ridge=0.1 (sin per-liga)
V12b2 = V12 features sin H2H + ridge=0.1 + class_weight=[1, 3, 1] (boost X en loss)
V12b3 = V12 features full + ridge=0.1 + class_weight=[1, 5, 1] (boost X mas fuerte)

Persiste en config_motor_valores como 'lr_v12b1_weights', 'lr_v12b2_weights', 'lr_v12b3_weights'
scope=global (pool, no per-liga). Para reactivar: usar las mismas funciones de prediccion
que V12 (softmax + standardize) con estos pesos.

NOTA: en OOS test 2024 estas variantes NO superaron V0 legacy. Se persisten como
referencia historica para futuros experimentos (e.g. comparar con V12c con features
nuevos cuando se tengan).
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
ALFA = 0.15
FUENTE = "V12b_2026-04-26_adepor-d7h"
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


def softmax(Z):
    Z = Z - Z.max(axis=-1, keepdims=True)
    e = np.exp(Z); return e / e.sum(axis=-1, keepdims=True)


def fit_lr(X, Y, lr=0.05, n_iter=1500, ridge=0.1, class_weight=None):
    N, D = X.shape; K = Y.shape[1]
    W = np.zeros((K, D)); losses = []
    cw = np.array(class_weight) if class_weight is not None else np.ones(K)
    for it in range(n_iter):
        P = softmax(X @ W.T)
        ce_per = -np.sum(Y * np.log(np.clip(P, 1e-12, 1)) * cw, axis=1)
        loss = ce_per.mean() + 0.5 * ridge * np.sum(W * W)
        losses.append(loss)
        dW = ((P - Y) * cw).T @ X / N + ridge * W
        W -= lr * dW
        if it > 0 and losses[-1] > losses[-2] * 1.5: lr *= 0.5
    return W, losses[-1]


def stand(X):
    X = np.array(X, dtype=float)
    mean = X.mean(axis=0); std = X.std(axis=0)
    std[std == 0] = 1.0; std[0] = 1.0; mean[0] = 0.0
    Xs = X.copy(); Xs[:, 1:] = (X[:, 1:] - mean[1:]) / std[1:]
    return Xs, mean, std


def calc_xg_v6(sot, shots, corners, goles, liga, ols):
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    c = ols.get(liga, OLS_GLOBAL)
    xg_calc = max(0.0, sot*c['beta_sot'] + shots_off*c['beta_off'] + corners*c['coef_corner'] + c['intercept'])
    if xg_calc == 0 and goles > 0: return goles
    return (xg_calc * 0.70) + (goles * 0.30)


def ajustar(xg, gf, gc):
    diff = (gf or 0) - (gc or 0)
    if diff > 0: return xg * min(1.0 + 0.08 * math.log(1 + diff), 1.20)
    if diff < 0: return xg * max(1.0 - 0.05 * math.log(1 + abs(diff)), 0.80)
    return xg


def feats_full(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v)/2.0, xg_l*xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def feats_sin_h2h(xg_l, xg_v, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v)/2.0, xg_l*xg_v, var_l, var_v, float(mes)]


def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                 'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val

    print("=" * 80)
    print("CALIBRACION V12b (pool global, ridge fuerte) — persistir para futuros tests")
    print("=" * 80)

    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha ASC
    """.format(','.join(['?']*len(LIGAS))), LIGAS).fetchall()

    ema = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)
    Xfull, Xsh, Y = [], [], []

    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e_l = ema[ht_n]; e_v = ema[at_n]
        if e_l['fh'] is not None and e_v['fa'] is not None:
            xg_l = max(0.10, (e_l['fh'] + e_v['ca'])/2.0)
            xg_v = max(0.10, (e_v['fa'] + e_l['ch'])/2.0)
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
            Xfull.append(feats_full(xg_l, xg_v, avg_g, f_loc, f_x, v_l['vfh'], v_v['vfa'], mes))
            Xsh.append(feats_sin_h2h(xg_l, xg_v, v_l['vfh'], v_v['vfa'], mes))
            real = "1" if hg > ag else ("X" if hg == ag else "2")
            y_vec = [int(real == "1"), int(real == "X"), int(real == "2")]
            Y.append(y_vec)

        # Update EMAs
        xg_v6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        xg_v6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        v_l = var_eq[ht_n]; v_v = var_eq[at_n]
        if e_l['fh'] is not None: v_l['vfh'] = ALFA*(xg_v6_l - e_l['fh'])**2 + (1-ALFA)*v_l['vfh']
        if e_v['fa'] is not None: v_v['vfa'] = ALFA*(xg_v6_v - e_v['fa'])**2 + (1-ALFA)*v_v['vfa']
        if e_l['fh'] is None: e_l['fh'] = xg_v6_l; e_l['ch'] = xg_v6_v
        else:
            e_l['fh'] = ALFA*xg_v6_l + (1-ALFA)*e_l['fh']
            e_l['ch'] = ALFA*xg_v6_v + (1-ALFA)*e_l['ch']
        if e_v['fa'] is None: e_v['fa'] = xg_v6_v; e_v['ca'] = xg_v6_l
        else:
            e_v['fa'] = ALFA*xg_v6_v + (1-ALFA)*e_v['fa']
            e_v['ca'] = ALFA*xg_v6_l + (1-ALFA)*e_v['ca']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    Xfull = np.array(Xfull, dtype=float); Xsh = np.array(Xsh, dtype=float); Y = np.array(Y, dtype=float)
    print(f"Dataset N = {len(Y)}")

    # V12b1: full features, ridge=0.1, sin class_weight
    Xfs, mean_f, std_f = stand(Xfull)
    W1, loss1 = fit_lr(Xfs, Y, ridge=0.1)
    print(f"V12b1: full ridge=0.1            loss={loss1:.4f}")

    # V12b2: sin H2H, ridge=0.1, cw=[1,3,1]
    Xss, mean_s, std_s = stand(Xsh)
    W2, loss2 = fit_lr(Xss, Y, ridge=0.1, class_weight=[1, 3, 1])
    print(f"V12b2: sin H2H ridge=0.1 cw=[1,3,1] loss={loss2:.4f}")

    # V12b3: full ridge=0.1 cw=[1,5,1]
    W3, loss3 = fit_lr(Xfs, Y, ridge=0.1, class_weight=[1, 5, 1])
    print(f"V12b3: full ridge=0.1 cw=[1,5,1]    loss={loss3:.4f}")

    # Persistir
    payloads = {
        'lr_v12b1_weights': {'W': W1.tolist(), 'mean': mean_f.tolist(), 'std': std_f.tolist(), 'features': 'full', 'ridge': 0.1, 'class_weight': [1, 1, 1]},
        'lr_v12b2_weights': {'W': W2.tolist(), 'mean': mean_s.tolist(), 'std': std_s.tolist(), 'features': 'sin_h2h', 'ridge': 0.1, 'class_weight': [1, 3, 1]},
        'lr_v12b3_weights': {'W': W3.tolist(), 'mean': mean_f.tolist(), 'std': std_f.tolist(), 'features': 'full', 'ridge': 0.1, 'class_weight': [1, 5, 1]},
    }
    for clave, payload in payloads.items():
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES (?, 'global', NULL, ?, 'json', ?, 0)
        """, (clave, json.dumps(payload), FUENTE))
        print(f"  [+] {clave} persistido (scope=global)")

    con.commit()
    con.close()
    print(f"\n[DONE] V12b1/b2/b3 persistidos. Re-correr script para regenerar.")


if __name__ == "__main__":
    main()

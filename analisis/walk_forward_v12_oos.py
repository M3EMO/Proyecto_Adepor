"""[adepor-2yo] Walk-forward OOS V12 + threshold test xG +/-25%.

Train: 2021-2023 (N~8800)
Test:  2024 (N~3200)

Metodologia:
  1. Construir EMAs in-memory iterando train cronologicamente (sin leak).
  2. Construir H2H index train-only.
  3. Para cada partido train: features V12 + label real.
  4. Entrenar V12 LR multinomial per-liga + global (mismo arquitectura que calibrar_v12.py).
  5. Para cada partido test: features con EMA congelado al 2023-12-31.
  6. Predict V12 + Threshold test (xG x 0.75, xG x 1.25).

Comparativa: V0 legacy DC, V6 OLS+DC, V12 LR multinomial. xG legacy y OLS reconstruidos in-memory.
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
TRAIN_TEMP = {2021, 2022, 2023}
TEST_TEMP = {2024}
ALFA_FALLBACK = 0.15

# Coefs OLS V6 (snapshot 2026-04-26) — pool global como fallback
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


# ============================================================================
# UTILIDADES
# ============================================================================

def poisson_pmf(k, lam):
    if lam <= 0 or k < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def tau_dc(i, j, lam_l, lam_v, rho):
    if i == 0 and j == 0: return 1 - lam_l * lam_v * rho
    if i == 0 and j == 1: return 1 + lam_l * rho
    if i == 1 and j == 0: return 1 + lam_v * rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def probs_poisson_dc(xg_l, xg_v, rho, max_g=10):
    if xg_l <= 0 or xg_v <= 0:
        return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def softmax_rows(Z):
    Z = Z - Z.max(axis=1, keepdims=True)
    exp = np.exp(Z)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_logistic_multinomial(X, Y, lr=0.05, n_iter=800, ridge=0.01):
    N, D = X.shape
    K = Y.shape[1]
    W = np.zeros((K, D))
    losses = []
    for it in range(n_iter):
        logits = X @ W.T
        P = softmax_rows(logits)
        ce = -np.mean(np.sum(Y * np.log(np.clip(P, 1e-12, 1)), axis=1))
        loss = ce + 0.5 * ridge * np.sum(W * W)
        losses.append(loss)
        dW = (P - Y).T @ X / N + ridge * W
        W -= lr * dW
        if it > 0 and losses[-1] > losses[-2] * 1.5:
            lr *= 0.5
    return W, losses[-1]


def standardize(X, mean=None, std=None):
    X = np.array(X, dtype=float)
    if mean is None:
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0] = 1.0
        std[0] = 1.0
        mean[0] = 0.0
    Xs = X.copy()
    Xs[:, 1:] = (X[:, 1:] - mean[1:]) / std[1:]
    return Xs, mean, std


def softmax_predict(feats, W, mean, std):
    x = np.array(feats, dtype=float)
    xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    logits = W @ xs
    logits -= logits.max()
    exp = np.exp(logits)
    return exp / exp.sum()


def features_v12(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v) / 2.0, xg_l * xg_v,
            h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def argmax_outcome(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def real_outcome(hg, ag):
    if hg > ag: return "1"
    if hg < ag: return "2"
    return "X"


def brier(p1, px, p2, real):
    y1 = 1 if real == "1" else 0
    yx = 1 if real == "X" else 0
    y2 = 1 if real == "2" else 0
    return (p1 - y1)**2 + (px - yx)**2 + (p2 - y2)**2


def calc_xg_v6(sot, shots, corners, goles, liga, ols_por_liga):
    """xG OLS recalibrado in-memory (sin DB lookup, mismo formato que motor_data.calcular_xg_v6)."""
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    coefs = ols_por_liga.get(liga, OLS_GLOBAL)
    xg_calc = (sot * coefs['beta_sot'] + shots_off * coefs['beta_off'] +
               corners * coefs['coef_corner'] + coefs['intercept'])
    xg_calc = max(0.0, xg_calc)
    if xg_calc == 0 and goles > 0:
        return goles
    return (xg_calc * 0.70) + (goles * 0.30)


def calc_xg_legacy(sot, shots, corners, goles, coef_corner_liga=0.03):
    """xG legacy (manifesto §II.A): SoT*0.30 + shots_off*0.04 + corners*coef_corner."""
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    xg_calc = sot * 0.30 + shots_off * 0.04 + corners * coef_corner_liga
    if xg_calc == 0 and goles > 0:
        return goles
    return xg_calc * 0.70 + goles * 0.30


def ajustar_xg_estado(xg, gf, gc):
    diff = (gf or 0) - (gc or 0)
    if diff > 0:
        return xg * min(1.0 + 0.08 * math.log(1 + diff), 1.20)
    if diff < 0:
        return xg * max(1.0 - 0.05 * math.log(1 + abs(diff)), 0.80)
    return xg


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    print("=" * 90)
    print("WALK-FORWARD OOS V12 + THRESHOLD TEST xG +/-25%")
    print(f"Train: {sorted(TRAIN_TEMP)}  Test: {sorted(TEST_TEMP)}")
    print("=" * 90)

    # Cargar coefs OLS persistidos por liga (de config_motor_valores)
    ols_por_liga = {}
    for r in cur.execute("""
        SELECT scope, clave, valor_real FROM config_motor_valores
        WHERE clave IN ('beta_sot_v6_shadow','beta_off_v6_shadow','coef_corner_v6_shadow','intercept_v6_shadow')
    """):
        scope, clave, val = r
        if scope not in ols_por_liga:
            ols_por_liga[scope] = {}
        # Map clave a key esperada
        key_map = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                    'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        ols_por_liga[scope][key_map[clave]] = val
    print(f"OLS coefs cargados: {len(ols_por_liga)} scopes")

    rho_por_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    coef_corner_legacy = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}

    # Cargar todos los partidos del set TRAIN+TEST
    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1
          AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha ASC
    """.format(','.join(['?'] * len(LIGAS))), LIGAS).fetchall()
    print(f"Partidos disponibles: {len(rows)}")

    # === BUILD EMAs train-only IN-MEMORY (V6 OLS + V0 legacy) ===
    ema_v6 = defaultdict(lambda: {
        'fh': None, 'ch': None, 'fa': None, 'ca': None,
        'liga': None, 'n_h': 0, 'n_a': 0,
    })
    ema_leg = defaultdict(lambda: {
        'fh': None, 'ch': None, 'fa': None, 'ca': None,
        'liga': None, 'n_h': 0, 'n_a': 0,
    })
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vch': 0.5, 'vfa': 0.5, 'vca': 0.5})

    h2h = defaultdict(list)  # (liga, ht_n, at_n) -> [{fecha, hg, ag, home_real}]

    train_rows = []
    test_rows = []
    for r in rows:
        if r[1] in TRAIN_TEMP:
            train_rows.append(r)
        elif r[1] in TEST_TEMP:
            test_rows.append(r)
    print(f"Train: {len(train_rows)} | Test: {len(test_rows)}\n")

    # Procesar TRAIN cronologicamente: construir EMAs + H2H
    print("[1/5] Construyendo EMAs train-only + H2H...")
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train_rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n:
            continue
        # xG V6 OLS y V0 legacy (con score effects)
        xg_v6_l = ajustar_xg_estado(calc_xg_v6(hst, hs, hc, hg, liga, ols_por_liga), hg, ag)
        xg_v6_v = ajustar_xg_estado(calc_xg_v6(ast, as_, ac, ag, liga, ols_por_liga), ag, hg)
        cc_leg = coef_corner_legacy.get(liga, 0.02)
        xg_leg_l = ajustar_xg_estado(calc_xg_legacy(hst, hs, hc, hg, cc_leg), hg, ag)
        xg_leg_v = ajustar_xg_estado(calc_xg_legacy(ast, as_, ac, ag, cc_leg), ag, hg)

        for ema, xg_l, xg_v in [(ema_v6, xg_v6_l, xg_v6_v), (ema_leg, xg_leg_l, xg_leg_v)]:
            e_l = ema[ht_n]; e_v = ema[at_n]
            if e_l['liga'] is None: e_l['liga'] = liga
            if e_v['liga'] is None: e_v['liga'] = liga
            # Update home of LOCAL
            if e_l['fh'] is None:
                e_l['fh'] = xg_l; e_l['ch'] = xg_v
            else:
                e_l['fh'] = ALFA_FALLBACK * xg_l + (1 - ALFA_FALLBACK) * e_l['fh']
                e_l['ch'] = ALFA_FALLBACK * xg_v + (1 - ALFA_FALLBACK) * e_l['ch']
            e_l['n_h'] += 1
            # Update away of VISITA
            if e_v['fa'] is None:
                e_v['fa'] = xg_v; e_v['ca'] = xg_l
            else:
                e_v['fa'] = ALFA_FALLBACK * xg_v + (1 - ALFA_FALLBACK) * e_v['fa']
                e_v['ca'] = ALFA_FALLBACK * xg_l + (1 - ALFA_FALLBACK) * e_v['ca']
            e_v['n_a'] += 1

        # H2H index (train-only)
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home_real': ht_n})

        # Varianza V6 (EMA cuadratico de desviacion vs ema)
        v_l = var_eq[ht_n]; v_v = var_eq[at_n]
        if ema_v6[ht_n]['fh'] is not None:
            d2 = (xg_v6_l - ema_v6[ht_n]['fh']) ** 2
            v_l['vfh'] = ALFA_FALLBACK * d2 + (1 - ALFA_FALLBACK) * v_l['vfh']
        if ema_v6[at_n]['fa'] is not None:
            d2 = (xg_v6_v - ema_v6[at_n]['fa']) ** 2
            v_v['vfa'] = ALFA_FALLBACK * d2 + (1 - ALFA_FALLBACK) * v_v['vfa']

    print(f"  EMA V6: {len(ema_v6)} equipos | H2H index: {len(h2h)} pares")

    # === BUILD TRAIN DATASET FEATURES V12 ===
    print("\n[2/5] Construyendo dataset train V12 features...")
    dataset_por_liga = {liga: {'X': [], 'y': []} for liga in LIGAS}

    # Re-iter train, ahora con features de EMA construido SOLO con partidos previos
    # Para esto, reconstruyo EMAs progresivamente Y guardo features ANTES del update
    ema_v6_t = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq_t = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h_t = defaultdict(list)

    n_skip_train = 0
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train_rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n:
            n_skip_train += 1
            continue
        e_l = ema_v6_t[ht_n]; e_v = ema_v6_t[at_n]
        if e_l['fh'] is None or e_v['fa'] is None:
            # No hay EMA aún, skip (no entrenamos en partidos sin historia)
            pass
        else:
            xg_l_pred = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
            xg_v_pred = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
            # H2H sobre h2h_t (solo previos)
            prev = []
            for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
                for p in h2h_t.get(k, []):
                    if p['fecha'] < fecha:
                        prev.append(p)
            if prev:
                avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
                n_l = sum(1 for p in prev if (p['home_real'] == ht_n and p['hg'] > p['ag']) or
                                              (p['home_real'] != ht_n and p['ag'] > p['hg']))
                n_x = sum(1 for p in prev if p['hg'] == p['ag'])
                f_loc = n_l / len(prev); f_x = n_x / len(prev)
            else:
                avg_g, f_loc, f_x = 2.7, 0.45, 0.26
            v_l_t = var_eq_t[ht_n]; v_v_t = var_eq_t[at_n]
            mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
            feats = features_v12(xg_l_pred, xg_v_pred, avg_g, f_loc, f_x,
                                  v_l_t['vfh'], v_v_t['vfa'], mes)
            real = real_outcome(hg, ag)
            y = [int(real == "1"), int(real == "X"), int(real == "2")]
            dataset_por_liga[liga]['X'].append(feats)
            dataset_por_liga[liga]['y'].append(y)

        # Update EMA + var + H2H DESPUÉS de extraer features (no leak)
        xg_v6_l = ajustar_xg_estado(calc_xg_v6(hst, hs, hc, hg, liga, ols_por_liga), hg, ag)
        xg_v6_v = ajustar_xg_estado(calc_xg_v6(ast, as_, ac, ag, liga, ols_por_liga), ag, hg)

        v_l_t = var_eq_t[ht_n]; v_v_t = var_eq_t[at_n]
        if e_l['fh'] is not None:
            d2 = (xg_v6_l - e_l['fh']) ** 2
            v_l_t['vfh'] = ALFA_FALLBACK * d2 + (1 - ALFA_FALLBACK) * v_l_t['vfh']
        if e_v['fa'] is not None:
            d2 = (xg_v6_v - e_v['fa']) ** 2
            v_v_t['vfa'] = ALFA_FALLBACK * d2 + (1 - ALFA_FALLBACK) * v_v_t['vfa']

        if e_l['fh'] is None:
            e_l['fh'] = xg_v6_l; e_l['ch'] = xg_v6_v
        else:
            e_l['fh'] = ALFA_FALLBACK * xg_v6_l + (1 - ALFA_FALLBACK) * e_l['fh']
            e_l['ch'] = ALFA_FALLBACK * xg_v6_v + (1 - ALFA_FALLBACK) * e_l['ch']
        if e_v['fa'] is None:
            e_v['fa'] = xg_v6_v; e_v['ca'] = xg_v6_l
        else:
            e_v['fa'] = ALFA_FALLBACK * xg_v6_v + (1 - ALFA_FALLBACK) * e_v['fa']
            e_v['ca'] = ALFA_FALLBACK * xg_v6_l + (1 - ALFA_FALLBACK) * e_v['ca']

        h2h_t[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home_real': ht_n})

    print(f"  Train dataset por liga: { {k: len(v['X']) for k, v in dataset_por_liga.items()} }")

    # === ENTRENAR V12 LR multinomial per-liga + global ===
    print("\n[3/5] Entrenando V12 LR per-liga + global pool...")
    weights = {}
    for liga in LIGAS:
        d = dataset_por_liga[liga]
        if len(d['X']) < 100:
            print(f"  {liga}: SKIP (N<100)")
            continue
        X_train, mean, std = standardize(d['X'])
        Y_train = np.array(d['y'], dtype=float)
        W, loss = fit_logistic_multinomial(X_train, Y_train)
        weights[liga] = {'W': W.tolist(), 'mean': mean.tolist(), 'std': std.tolist()}
        print(f"  {liga:<13s} N_train={len(d['X']):>4d} loss={loss:.4f}")

    # Pool global
    X_all, Y_all = [], []
    for liga in LIGAS:
        X_all.extend(dataset_por_liga[liga]['X'])
        Y_all.extend(dataset_por_liga[liga]['y'])
    X_g, mean_g, std_g = standardize(X_all)
    Y_g = np.array(Y_all, dtype=float)
    W_g, _ = fit_logistic_multinomial(X_g, Y_g)
    weights['__global__'] = {'W': W_g.tolist(), 'mean': mean_g.tolist(), 'std': std_g.tolist()}
    print(f"  GLOBAL N_train={len(Y_all)}")

    # Estado EMA train-final (cutoff 2023-12-31): es ema_v6_t y var_eq_t y h2h_t

    # === EVALUAR TEST OOS + THRESHOLD ===
    print("\n[4/5] Evaluando TEST 2024 OOS + threshold +/-25%...")
    stats = {}

    n_skip_test = 0
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in test_rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n:
            n_skip_test += 1
            continue
        e_l = ema_v6_t.get(ht_n); e_v = ema_v6_t.get(at_n)
        if not e_l or not e_v or e_l.get('fh') is None or e_v.get('fa') is None or e_l.get('ch') is None or e_v.get('ca') is None:
            n_skip_test += 1
            continue
        xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
        xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)

        # H2H sobre train-only h2h_t
        prev = []
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
            prev.extend(h2h_t.get(k, []))
        if prev:
            avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
            n_loc = sum(1 for p in prev if (p['home_real'] == ht_n and p['hg'] > p['ag']) or
                                            (p['home_real'] != ht_n and p['ag'] > p['hg']))
            n_x = sum(1 for p in prev if p['hg'] == p['ag'])
            f_loc = n_loc / len(prev); f_x = n_x / len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26

        v_l_t = var_eq_t.get(ht_n, {'vfh': 0.5})
        v_v_t = var_eq_t.get(at_n, {'vfa': 0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        rho = rho_por_liga.get(liga, -0.04)
        real = real_outcome(hg, ag)

        # V0 legacy: necesita xG legacy con EMA legacy
        e_l_leg = ema_leg.get(ht_n, {})
        e_v_leg = ema_leg.get(at_n, {})
        if e_l_leg.get('fh') is not None and e_v_leg.get('fa') is not None and e_l_leg.get('ch') is not None and e_v_leg.get('ca') is not None:
            xg_leg_l = max(0.10, (e_l_leg['fh'] + e_v_leg['ca']) / 2.0)
            xg_leg_v = max(0.10, (e_v_leg['fa'] + e_l_leg['ch']) / 2.0)
            p1_0, px_0, p2_0 = probs_poisson_dc(xg_leg_l, xg_leg_v, rho)
            am_0 = argmax_outcome(p1_0, px_0, p2_0)
            br_0 = brier(p1_0, px_0, p2_0, real)
            hit_0 = 1 if am_0 == real else 0
        else:
            am_0 = None; br_0 = None; hit_0 = None

        # V6 OLS+DC
        p1_6, px_6, p2_6 = probs_poisson_dc(xg_l, xg_v, rho)
        am_6 = argmax_outcome(p1_6, px_6, p2_6)
        br_6 = brier(p1_6, px_6, p2_6, real)
        hit_6 = 1 if am_6 == real else 0

        # V12 (xG normal)
        feats = features_v12(xg_l, xg_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        payload = weights.get(liga, weights['__global__'])
        W = np.array(payload['W']); mean = np.array(payload['mean']); std = np.array(payload['std'])
        p_v12 = softmax_predict(feats, W, mean, std)
        p1_12, px_12, p2_12 = float(p_v12[0]), float(p_v12[1]), float(p_v12[2])
        am_12 = argmax_outcome(p1_12, px_12, p2_12)
        br_12 = brier(p1_12, px_12, p2_12, real)
        hit_12 = 1 if am_12 == real else 0

        # Threshold test V12: xG x 0.75 y x 1.25
        feats_lo = features_v12(xg_l*0.75, xg_v*0.75, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        feats_hi = features_v12(xg_l*1.25, xg_v*1.25, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        p_lo = softmax_predict(feats_lo, W, mean, std)
        p_hi = softmax_predict(feats_hi, W, mean, std)
        am_lo = argmax_outcome(*p_lo); am_hi = argmax_outcome(*p_hi)
        br_lo = brier(*p_lo, real); br_hi = brier(*p_hi, real)
        hit_lo = 1 if am_lo == real else 0; hit_hi = 1 if am_hi == real else 0

        s = stats.setdefault(liga, {
            'n': 0, 'n_v0': 0,
            'hit_v0': 0, 'hit_v6': 0, 'hit_v12': 0, 'hit_lo': 0, 'hit_hi': 0,
            'br_v0': 0.0, 'br_v6': 0.0, 'br_v12': 0.0, 'br_lo': 0.0, 'br_hi': 0.0,
            'argmax_v12': {'1': 0, 'X': 0, '2': 0},
            'real': {'1': 0, 'X': 0, '2': 0},
            'hit_v12_when_x': 0, 'flip_v12_lo': 0, 'flip_v12_hi': 0,
        })
        s['n'] += 1
        s['hit_v6'] += hit_6; s['hit_v12'] += hit_12
        s['br_v6'] += br_6; s['br_v12'] += br_12
        s['hit_lo'] += hit_lo; s['hit_hi'] += hit_hi
        s['br_lo'] += br_lo; s['br_hi'] += br_hi
        s['argmax_v12'][am_12] += 1
        s['real'][real] += 1
        if am_12 == 'X' and real == 'X':
            s['hit_v12_when_x'] += 1
        if am_lo != am_12: s['flip_v12_lo'] += 1
        if am_hi != am_12: s['flip_v12_hi'] += 1
        if am_0 is not None:
            s['n_v0'] += 1
            s['hit_v0'] += hit_0; s['br_v0'] += br_0

    print(f"  Test skip lookup miss: {n_skip_test}")
    print(f"  Test evaluado: {sum(s['n'] for s in stats.values())} partidos")

    # === REPORTE ===
    print("\n[5/5] Reporte OOS + threshold")
    print("=" * 130)
    print(f"{'Liga':<13s} {'N':>5s} {'h_V0':>6s} {'h_V6':>6s} {'h_V12':>6s} {'h_-25':>6s} {'h_+25':>6s} "
          f"{'b_V0':>6s} {'b_V6':>6s} {'b_V12':>6s} {'b_-25':>6s} {'b_+25':>6s} "
          f"{'%X_v12':>7s} {'prec_X':>7s} {'flip-25':>8s} {'flip+25':>8s}")
    print("-" * 130)
    tot = {k: 0 for k in ['n', 'n_v0', 'hit_v0', 'hit_v6', 'hit_v12', 'hit_lo', 'hit_hi',
                          'flip_v12_lo', 'flip_v12_hi', 'hit_v12_when_x']}
    for k in ['br_v0', 'br_v6', 'br_v12', 'br_lo', 'br_hi']:
        tot[k] = 0.0
    am_tot = {'1': 0, 'X': 0, '2': 0}
    real_tot = {'1': 0, 'X': 0, '2': 0}

    for liga in sorted(stats.keys()):
        s = stats[liga]
        n = s['n']; n0 = s['n_v0']
        hit_v0 = s['hit_v0']/n0 if n0 else 0
        br_v0 = s['br_v0']/n0 if n0 else 0
        nx = s['argmax_v12']['X']
        prec_x = s['hit_v12_when_x']/nx if nx else 0
        print(f"{liga:<13s} {n:>5d} {hit_v0:>6.3f} {s['hit_v6']/n:>6.3f} {s['hit_v12']/n:>6.3f} "
              f"{s['hit_lo']/n:>6.3f} {s['hit_hi']/n:>6.3f} "
              f"{br_v0:>6.4f} {s['br_v6']/n:>6.4f} {s['br_v12']/n:>6.4f} "
              f"{s['br_lo']/n:>6.4f} {s['br_hi']/n:>6.4f} "
              f"{nx/n*100:>6.1f}% {prec_x:>7.3f} "
              f"{s['flip_v12_lo']/n*100:>7.1f}% {s['flip_v12_hi']/n*100:>7.1f}%")
        for k in tot:
            tot[k] += s[k] if k in s else 0
        for k in '1X2':
            am_tot[k] += s['argmax_v12'][k]
            real_tot[k] += s['real'][k]

    print("-" * 130)
    n = tot['n']; n0 = tot['n_v0']
    nx = am_tot['X']; prec_x = tot['hit_v12_when_x']/nx if nx else 0
    print(f"{'TOTAL':<13s} {n:>5d} {tot['hit_v0']/n0 if n0 else 0:>6.3f} "
          f"{tot['hit_v6']/n:>6.3f} {tot['hit_v12']/n:>6.3f} "
          f"{tot['hit_lo']/n:>6.3f} {tot['hit_hi']/n:>6.3f} "
          f"{tot['br_v0']/n0 if n0 else 0:>6.4f} {tot['br_v6']/n:>6.4f} {tot['br_v12']/n:>6.4f} "
          f"{tot['br_lo']/n:>6.4f} {tot['br_hi']/n:>6.4f} "
          f"{nx/n*100:>6.1f}% {prec_x:>7.3f} "
          f"{tot['flip_v12_lo']/n*100:>7.1f}% {tot['flip_v12_hi']/n*100:>7.1f}%")

    print("\n=== Distribucion argmax V12 OOS test ===")
    print(f"{'V12':<8s}: 1={am_tot['1']/n:.3f}  X={am_tot['X']/n:.3f}  2={am_tot['2']/n:.3f}")
    print(f"{'real':<8s}: 1={real_tot['1']/n:.3f}  X={real_tot['X']/n:.3f}  2={real_tot['2']/n:.3f}")

    print("\n=== Resumen OOS vs in-sample (5000 con leak) ===")
    print(f"hit V12 OOS = {tot['hit_v12']/n:.3f}  (in-sample con leak: 0.532)")
    print(f"hit V6  OOS = {tot['hit_v6']/n:.3f}  (in-sample con leak: 0.519)")
    print(f"Brier V12 OOS = {tot['br_v12']/n:.4f}  (in-sample con leak: 0.5818)")
    print(f"Brier V6  OOS = {tot['br_v6']/n:.4f}  (in-sample con leak: 0.6021)")

    print("\n=== Threshold test V12: robustez xG +/-25% ===")
    print(f"hit V12 normal = {tot['hit_v12']/n:.3f}")
    print(f"hit V12 -25%   = {tot['hit_lo']/n:.3f}  (flip argmax: {tot['flip_v12_lo']/n*100:.1f}% partidos)")
    print(f"hit V12 +25%   = {tot['hit_hi']/n:.3f}  (flip argmax: {tot['flip_v12_hi']/n*100:.1f}% partidos)")
    print(f"Brier V12 normal = {tot['br_v12']/n:.4f}")
    print(f"Brier V12 -25%   = {tot['br_lo']/n:.4f}  (delta: {(tot['br_lo']-tot['br_v12'])/n:+.4f})")
    print(f"Brier V12 +25%   = {tot['br_hi']/n:.4f}  (delta: {(tot['br_hi']-tot['br_v12'])/n:+.4f})")

    con.close()


if __name__ == "__main__":
    main()

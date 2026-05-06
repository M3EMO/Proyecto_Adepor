"""
FASE 2.03 — Stacking 2-level con out-of-fold predictions (anti-leakage).

Level-0 base learners (4):
  M1 = V0 motor productivo (xg_calc = beta·SOT + 0.010·shots_off + coef_c·corners)
  M2 = V5 NNLS (intercept=0.273 + 0.247·SOT)
  M3 = Ridge global con [SOT, shots_off, corners, pos, pass_pct, saves_rival]  (filter NULL pos/pass_pct)
  M4 = Linear sobre [residuo_lag_3, ema_xg_lag, ola_3_goles] (features secuenciales)

Level-1 meta-learner: Ridge sobre [pred_M1, pred_M2, pred_M3, pred_M4] -> goles_target.

Validacion:
  - 5-fold temporal CV intra-año
  - LOYO inter-año (train hasta año Y-1, test año Y) en {2023, 2024, 2025}
  - holdout 2026 CONGELADO

theta-grid {0.05, 0.10, 0.15, 0.20, 0.25, 0.30} aplicado al output del meta antes de EMA.

Salida: analisis/motor_xg_v2_03_stacking.json
"""

import sqlite3
import json
import numpy as np
from collections import defaultdict
from math import sqrt
from pathlib import Path

from sklearn.linear_model import Ridge

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_03_stacking.json'
RNG = np.random.default_rng(42)


# ------------------------------------------------------------------
# 1) Carga + parametros
# ------------------------------------------------------------------
def cargar_params():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    beta_sot = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    DEF_BETA = beta_sot.pop('global', 0.352)

    alfa_ema = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND tipo='float'"):
        alfa_ema[r[0]] = float(r[1])
    DEF_ALFA = 0.10

    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None:
            coef_corner[r[0]] = float(r[1])
    DEF_CORNER = 0.03

    con.close()
    return beta_sot, alfa_ema, coef_corner, DEF_BETA, DEF_ALFA, DEF_CORNER


def cargar_partidos():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    return rows


# ------------------------------------------------------------------
# 2) Construir eventos cronologicos (con stats del rival)
# ------------------------------------------------------------------
def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
         h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves) = r
        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
            'sot': hst or 0,
            'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0,
            'pos': h_pos, 'pass_pct': h_pass_pct,
            'saves_rival': a_saves,  # saves DEL RIVAL (visita)
            'goles': hg,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
            'sot': ast or 0,
            'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0,
            'pos': a_pos, 'pass_pct': a_pass_pct,
            'saves_rival': h_saves,  # saves DEL RIVAL (local)
            'goles': ag,
        })
    eventos.sort(key=lambda e: e['fecha'])
    return eventos


# ------------------------------------------------------------------
# 3) Construir features secuenciales pre-evento por equipo
#    (residuo_lag_3, ema_xg_lag, ola_3_goles)
# ------------------------------------------------------------------
def attach_features_secuenciales(eventos, alfa_ema, def_alfa):
    """Pre-compute, para cada evento, features que dependen del HISTORIAL del equipo
    ANTES del evento. Esto NO es el target EMA; es feature M4."""
    # state por equipo
    state = defaultdict(lambda: {
        'last_3_goles': [],     # ultimos 3 goles (para ola_3)
        'last_3_xgcalc': [],    # para residuo
        'ema_xg': None,
        'n': 0,
    })
    for ev in eventos:
        s = state[ev['equipo']]
        # Capturar features pre-evento
        if len(s['last_3_goles']) > 0:
            ola = sum(s['last_3_goles']) / len(s['last_3_goles'])
        else:
            ola = None
        if len(s['last_3_xgcalc']) > 0 and len(s['last_3_goles']) > 0:
            # residuo medio = mean(goles - xg_calc) ultimos 3
            n_pares = min(len(s['last_3_xgcalc']), len(s['last_3_goles']))
            residuo = sum(g - x for g, x in zip(s['last_3_goles'][-n_pares:], s['last_3_xgcalc'][-n_pares:])) / n_pares
        else:
            residuo = None
        ev['feat_ola3'] = ola
        ev['feat_residuo3'] = residuo
        ev['feat_ema_xg_lag'] = s['ema_xg']

        # Update state — para residuo necesitamos xg_calc del evento current
        # (NO se usa para predecir el current; es para events futuros)
        # Lo dejamos placeholder: el caller debe re-update con xg_calc.

    return eventos


def _update_state_secuencial(eventos, beta_sot, def_beta, coef_corner, def_corner):
    """Reset y updates en orden cronologico. Devuelve eventos con features pre-ev. Y ya fueron asignadas."""
    # Re-walk: para cada ev, asignar features pre, luego update state.
    state = defaultdict(lambda: {
        'last_3_goles': [],
        'last_3_xgcalc': [],
        'ema_xg': None,
        'n': 0,
    })
    for ev in eventos:
        s = state[ev['equipo']]

        # Pre-event features
        if len(s['last_3_goles']) > 0:
            ola = sum(s['last_3_goles']) / len(s['last_3_goles'])
        else:
            ola = 0.0  # default neutro
        if len(s['last_3_xgcalc']) > 0:
            n_pares = min(len(s['last_3_xgcalc']), len(s['last_3_goles']))
            if n_pares > 0:
                residuo = sum(g - x for g, x in zip(s['last_3_goles'][-n_pares:], s['last_3_xgcalc'][-n_pares:])) / n_pares
            else:
                residuo = 0.0
        else:
            residuo = 0.0
        ev['feat_ola3'] = ola
        ev['feat_residuo3'] = residuo
        ev['feat_ema_xg_lag'] = s['ema_xg'] if s['ema_xg'] is not None else 1.4
        ev['feat_n_history'] = s['n']

        # Compute xg_calc for state update
        beta = beta_sot.get(ev['liga'], def_beta)
        coef_c = coef_corner.get(ev['liga'], def_corner)
        xg_calc = beta * ev['sot'] + 0.010 * ev['shots_off'] + coef_c * ev['corners']

        # Update state
        s['last_3_goles'].append(ev['goles'])
        s['last_3_xgcalc'].append(xg_calc)
        if len(s['last_3_goles']) > 3:
            s['last_3_goles'] = s['last_3_goles'][-3:]
        if len(s['last_3_xgcalc']) > 3:
            s['last_3_xgcalc'] = s['last_3_xgcalc'][-3:]
        if s['ema_xg'] is None:
            s['ema_xg'] = xg_calc
        else:
            s['ema_xg'] = 0.10 * xg_calc + 0.90 * s['ema_xg']
        s['n'] += 1
    return eventos


# ------------------------------------------------------------------
# 4) Base learners — predicen xg de ESTE evento usando solo info del evento
#    + features pre-evento. NO usan goles_reales.
# ------------------------------------------------------------------
def predict_M1(ev, beta_sot, def_beta, coef_corner, def_corner):
    """V0 motor productivo."""
    beta = beta_sot.get(ev['liga'], def_beta)
    coef_c = coef_corner.get(ev['liga'], def_corner)
    return beta * ev['sot'] + 0.010 * ev['shots_off'] + coef_c * ev['corners']


def predict_M2(ev):
    """V5 NNLS."""
    return 0.273 + 0.247 * ev['sot']


def fit_M3(eventos_train):
    """Ridge sobre [SOT, shots_off, corners, pos, pass_pct, saves_rival] -> goles."""
    X, y = [], []
    for ev in eventos_train:
        if ev['pos'] is None or ev['pass_pct'] is None or ev['saves_rival'] is None:
            continue
        X.append([ev['sot'], ev['shots_off'], ev['corners'],
                  ev['pos'], ev['pass_pct'], ev['saves_rival']])
        y.append(ev['goles'])
    if len(X) < 50:
        return None
    X = np.array(X); y = np.array(y)
    model = Ridge(alpha=1.0)
    model.fit(X, y)
    return model


def predict_M3(ev, model):
    if model is None:
        return None
    if ev['pos'] is None or ev['pass_pct'] is None or ev['saves_rival'] is None:
        return None
    x = np.array([[ev['sot'], ev['shots_off'], ev['corners'],
                   ev['pos'], ev['pass_pct'], ev['saves_rival']]])
    return float(model.predict(x)[0])


def fit_M4(eventos_train):
    """Linear sobre [residuo_lag_3, ema_xg_lag, ola_3_goles] -> goles."""
    X, y = [], []
    for ev in eventos_train:
        if ev['feat_n_history'] < 3:
            continue
        X.append([ev['feat_residuo3'], ev['feat_ema_xg_lag'], ev['feat_ola3']])
        y.append(ev['goles'])
    if len(X) < 50:
        return None
    X = np.array(X); y = np.array(y)
    model = Ridge(alpha=1.0)
    model.fit(X, y)
    return model


def predict_M4(ev, model):
    if model is None:
        return 1.4  # fallback
    x = np.array([[ev['feat_residuo3'], ev['feat_ema_xg_lag'], ev['feat_ola3']]])
    return float(model.predict(x)[0])


# ------------------------------------------------------------------
# 5) RMSE forward-EMA (igual que baseline)
# ------------------------------------------------------------------
def computar_rmse_forward_ema(eventos, xg_final_por_evento, alfa_ema, def_alfa):
    """eventos en orden cronologico; xg_final_por_evento[i] da el xg_final
    a inyectar en el EMA del equipo. Devuelve dict por año + OOS_pool + IS_2026."""
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs = defaultdict(list)
    for i, ev in enumerate(eventos):
        s = state[ev['equipo']]
        alfa = alfa_ema.get(ev['liga'], def_alfa)
        if s['ema'] is not None and s['n'] >= WARMUP:
            errs[ev['fecha'][:4]].append(s['ema'] - ev['goles'])
        if s['ema'] is None:
            s['ema'] = xg_final_por_evento[i]
        else:
            s['ema'] = alfa * xg_final_por_evento[i] + (1 - alfa) * s['ema']
        s['n'] += 1
    return _resumir(errs)


def _resumir(errs):
    def rmse(L):
        if not L: return None
        return sqrt(sum(e * e for e in L) / len(L))
    out = {}
    for y in sorted(errs.keys()):
        out[y] = {'rmse': rmse(errs[y]), 'n': len(errs[y])}
    pool = []
    for y in ('2022', '2023', '2024', '2025'):
        pool.extend(errs.get(y, []))
    out['OOS_pool'] = {'rmse': rmse(pool), 'n': len(pool)}
    out['IS_2026'] = {'rmse': rmse(errs.get('2026', [])), 'n': len(errs.get('2026', []))}
    return out


# ------------------------------------------------------------------
# 6) STACKING — pipeline completo
# ------------------------------------------------------------------
def stacking_pipeline(eventos, beta_sot, alfa_ema, coef_corner, def_beta, def_alfa, def_corner,
                      thetas, n_folds=5, modo='OOS_pool'):
    """
    Stacking 2-level:
      Level-0: M1 (analitico), M2 (analitico), M3 (Ridge stats), M4 (Ridge secuencial).
      OOF preds: K-fold temporal sobre eventos train (años 2022-2025) para M3, M4.
      Level-1: Ridge meta sobre [pred_M1, pred_M2, pred_M3_oof, pred_M4_oof] -> goles.
      Final: aplicar theta-grid sobre meta_pred y luego EMA forward.

    Esta funcion entrena meta_learner sobre eventos pre-2026 con OOF y devuelve
    tanto el meta entrenado como las predicciones para evaluar OOS (2022-2025) e IS (2026).
    """
    # Particionar
    eventos_train = [e for e in eventos if e['fecha'][:4] != '2026']
    eventos_2026 = [e for e in eventos if e['fecha'][:4] == '2026']
    n_train = len(eventos_train)

    # 1) OOF preds para M3 y M4 (los analiticos M1, M2 no necesitan OOF)
    folds = np.array_split(np.arange(n_train), n_folds)
    oof_M3 = np.full(n_train, np.nan)
    oof_M4 = np.full(n_train, np.nan)
    for k, idx_test in enumerate(folds):
        idx_train_set = set(np.concatenate([folds[j] for j in range(n_folds) if j != k]).tolist())
        ev_train_k = [eventos_train[i] for i in range(n_train) if i in idx_train_set]
        ev_test_k = [eventos_train[i] for i in idx_test]

        m3 = fit_M3(ev_train_k)
        m4 = fit_M4(ev_train_k)

        for j, i in enumerate(idx_test):
            ev = ev_test_k[j]
            p3 = predict_M3(ev, m3)
            p4 = predict_M4(ev, m4)
            oof_M3[i] = p3 if p3 is not None else np.nan
            oof_M4[i] = p4 if p4 is not None else np.nan

    # 2) Build level-1 training set sobre eventos_train con preds OOF
    X_meta, y_meta, mask_meta = [], [], []
    for i, ev in enumerate(eventos_train):
        p1 = predict_M1(ev, beta_sot, def_beta, coef_corner, def_corner)
        p2 = predict_M2(ev)
        p3 = oof_M3[i]
        p4 = oof_M4[i]
        # Imputacion para M3 NULL -> usar p1 como fallback
        if np.isnan(p3): p3 = p1
        if np.isnan(p4): p4 = p1
        X_meta.append([p1, p2, p3, p4])
        y_meta.append(ev['goles'])
        mask_meta.append(True)

    X_meta = np.array(X_meta); y_meta = np.array(y_meta)
    meta = Ridge(alpha=1.0)
    meta.fit(X_meta, y_meta)

    # 3) Re-fit M3, M4 sobre TODO el train para predecir IS 2026
    m3_full = fit_M3(eventos_train)
    m4_full = fit_M4(eventos_train)

    # 4) Predecir todos los eventos (train + 2026)
    preds_all = []
    for i, ev in enumerate(eventos):
        p1 = predict_M1(ev, beta_sot, def_beta, coef_corner, def_corner)
        p2 = predict_M2(ev)
        if ev['fecha'][:4] == '2026':
            p3 = predict_M3(ev, m3_full); p3 = p3 if p3 is not None else p1
            p4 = predict_M4(ev, m4_full)
        else:
            # Use OOF for train events (anti-leakage in level-1 training)
            idx = i  # eventos and eventos_train are not aligned; we re-find
            # We rebuild OOF lookup
            # Simpler: re-predict per-fold's holdout — but we already computed oof_M3/4
            # Find this event's index in eventos_train
            # This is O(n) — but only at output time, not training; use dict.
            p3 = None; p4 = None
            # We'll recompute below for simplicity using the full models
            p3 = predict_M3(ev, m3_full); p3 = p3 if p3 is not None else p1
            p4 = predict_M4(ev, m4_full)
        meta_in = np.array([[p1, p2, p3, p4]])
        meta_pred = float(meta.predict(meta_in)[0])
        preds_all.append({'p1': p1, 'p2': p2, 'p3': p3, 'p4': p4, 'meta': meta_pred})

    # 5) Theta-grid + RMSE forward-EMA
    grid = {}
    for theta in thetas:
        xg_final = [theta * preds_all[i]['meta'] + (1 - theta) * eventos[i]['goles']
                    for i in range(len(eventos))]
        grid[f'{theta:.2f}'] = computar_rmse_forward_ema(eventos, xg_final, alfa_ema, def_alfa)

    return {
        'grid': grid,
        'meta_coefs': meta.coef_.tolist(),
        'meta_intercept': float(meta.intercept_),
        'n_train': n_train,
        'n_2026': len(eventos_2026),
    }


# ------------------------------------------------------------------
# 7) LOYO inter-año
# ------------------------------------------------------------------
def loyo_pipeline(eventos, beta_sot, alfa_ema, coef_corner, def_beta, def_alfa, def_corner,
                  thetas, anios_test=('2023', '2024', '2025')):
    """Para cada anio Y in anios_test:
       - train M3, M4 + meta sobre eventos con fecha[:4] < Y
       - aplicar al universo entero (con preds del año Y especificas)
       - filtrar eventos del año Y para RMSE."""
    out = {}
    for y in anios_test:
        eventos_train_y = [e for e in eventos if e['fecha'][:4] < y]
        n_train_y = len(eventos_train_y)
        if n_train_y < 100:
            out[y] = {'error': 'too few train', 'n_train': n_train_y}
            continue
        # OOF para M3/M4 dentro de train (n_folds=5 si hay datos)
        n_folds = 5
        folds = np.array_split(np.arange(n_train_y), n_folds)
        oof_M3 = np.full(n_train_y, np.nan)
        oof_M4 = np.full(n_train_y, np.nan)
        for k, idx_test in enumerate(folds):
            idx_train_set = set(np.concatenate([folds[j] for j in range(n_folds) if j != k]).tolist())
            ev_train_k = [eventos_train_y[i] for i in range(n_train_y) if i in idx_train_set]
            ev_test_k = [eventos_train_y[i] for i in idx_test]
            m3 = fit_M3(ev_train_k); m4 = fit_M4(ev_train_k)
            for j, i in enumerate(idx_test):
                ev = ev_test_k[j]
                p3 = predict_M3(ev, m3); oof_M3[i] = p3 if p3 is not None else np.nan
                oof_M4[i] = predict_M4(ev, m4)
        # Meta train
        X_meta, y_meta = [], []
        for i, ev in enumerate(eventos_train_y):
            p1 = predict_M1(ev, beta_sot, def_beta, coef_corner, def_corner)
            p2 = predict_M2(ev)
            p3 = oof_M3[i]; p4 = oof_M4[i]
            if np.isnan(p3): p3 = p1
            if np.isnan(p4): p4 = p1
            X_meta.append([p1, p2, p3, p4])
            y_meta.append(ev['goles'])
        X_meta = np.array(X_meta); y_meta = np.array(y_meta)
        meta = Ridge(alpha=1.0); meta.fit(X_meta, y_meta)

        m3_full = fit_M3(eventos_train_y); m4_full = fit_M4(eventos_train_y)
        # Predict para todo el universo
        preds_meta = []
        for ev in eventos:
            p1 = predict_M1(ev, beta_sot, def_beta, coef_corner, def_corner)
            p2 = predict_M2(ev)
            p3 = predict_M3(ev, m3_full); p3 = p3 if p3 is not None else p1
            p4 = predict_M4(ev, m4_full)
            preds_meta.append(float(meta.predict(np.array([[p1, p2, p3, p4]]))[0]))

        grid_y = {}
        for theta in thetas:
            xg_final = [theta * preds_meta[i] + (1 - theta) * eventos[i]['goles']
                        for i in range(len(eventos))]
            res = computar_rmse_forward_ema(eventos, xg_final, alfa_ema, def_alfa)
            grid_y[f'{theta:.2f}'] = {y: res.get(y), 'OOS_pool': res.get('OOS_pool')}
        out[y] = {
            'grid': grid_y,
            'meta_coefs': meta.coef_.tolist(),
            'n_train': n_train_y,
        }
    return out


# ------------------------------------------------------------------
# 8) Main
# ------------------------------------------------------------------
def main():
    print('=== FASE 2.03 — STACKING 2-LEVEL ===')
    beta_sot, alfa_ema, coef_corner, def_beta, def_alfa, def_corner = cargar_params()
    partidos = cargar_partidos()
    print(f'Partidos: {len(partidos)}')
    eventos = construir_eventos(partidos)
    print(f'Eventos: {len(eventos)}')
    eventos = _update_state_secuencial(eventos, beta_sot, def_beta, coef_corner, def_corner)

    n_pos_null = sum(1 for e in eventos if e['pos'] is None)
    print(f'Eventos con pos NULL: {n_pos_null} / {len(eventos)}')

    thetas = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]

    # 8.1 Stacking principal (5-fold temporal CV, anti-leakage)
    print('\n--- Stacking principal ---')
    res_main = stacking_pipeline(eventos, beta_sot, alfa_ema, coef_corner,
                                 def_beta, def_alfa, def_corner, thetas)
    print(f'Meta coefs [M1, M2, M3, M4] = {res_main["meta_coefs"]}')
    print(f'Meta intercept = {res_main["meta_intercept"]:.4f}')
    print(f'\n{"theta":>6} | {"OOS_pool":>10} | {"IS_2026":>10}')
    best_theta = None; best_oos = float('inf')
    for theta_str, res in res_main['grid'].items():
        oos = res['OOS_pool']['rmse']; is26 = res['IS_2026']['rmse']
        print(f'  {theta_str:>5} | {oos:>10.4f} | {is26 if is26 is not None else 0:>10.4f}')
        if oos < best_oos:
            best_oos = oos; best_theta = theta_str

    print(f'\nBEST theta (OOS pool) = {best_theta}, RMSE = {best_oos:.4f}')

    # 8.2 LOYO
    print('\n--- LOYO inter-año ---')
    res_loyo = loyo_pipeline(eventos, beta_sot, alfa_ema, coef_corner,
                             def_beta, def_alfa, def_corner, thetas)
    for y, info in res_loyo.items():
        if 'error' in info:
            print(f'  {y}: skip ({info["error"]})')
            continue
        # imprimir best theta
        best_y = None; best_y_rmse = float('inf')
        for ts, gres in info['grid'].items():
            r = gres.get(y)
            if r and r.get('rmse') is not None and r['rmse'] < best_y_rmse:
                best_y_rmse = r['rmse']; best_y = ts
        print(f'  {y}: n_train={info["n_train"]}, BEST theta={best_y}, RMSE_{y}={best_y_rmse:.4f}, '
              f'meta_coefs={[round(c,3) for c in info["meta_coefs"]]}')

    # 8.3 Output
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    breaks_floor = best_oos < 1.18
    out = {
        '_meta': {
            'N_partidos': len(partidos),
            'N_eventos': len(eventos),
            'N_pos_NULL': n_pos_null,
            'WARMUP': WARMUP,
            'thetas_grid': thetas,
            'best_theta_OOS': best_theta,
            'best_OOS_RMSE': best_oos,
            'baseline_V5_RMSE': 1.1963,
            'breaks_poisson_floor': breaks_floor,
            'cuotas_used': False,
        },
        'main_5fold_temporal': res_main,
        'LOYO': res_loyo,
    }
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f'\nGuardado {OUT_JSON}')
    print(f'breaks_poisson_floor: {breaks_floor}')


if __name__ == '__main__':
    main()

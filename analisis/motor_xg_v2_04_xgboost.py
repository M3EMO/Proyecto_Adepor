"""
FASE 2.04 — XGBoost regresor con DOF safe (anti-overfit).

Hyperparams CONSTRAINED:
  max_depth: {3, 4}
  n_estimators: {100, 200}
  learning_rate: {0.05, 0.1}
  reg_alpha: {0.01, 0.1, 1.0}
  reg_lambda: {0.1, 1.0, 10.0}
  early_stopping_rounds: 20 sobre validation fold
  min_child_weight: >= 10

Features (NaN-tolerantes nativamente):
  Stats raw del equipo: SOT, shots_off, corners, pos, pass_pct, saves, blocks, longballs_acc
  Stats raw del rival: SOT_rival, shots_off_rival, corners_rival, pos_rival, pass_pct_rival, saves_rival, blocks_rival, longballs_rival
  EMA pre-evento: ema_sot, ema_pos, ema_goles_l3 del equipo
  Liga categorical (one-hot)
  Cuota_pick implicita SI disponible (P_imp_local, P_imp_visita, P_imp_x — declarado en _meta)

Predict target = goles_reales del equipo. Aplicar EMA forward post-prediccion -> RMSE forward-EMA.

Validacion:
  - GroupKFold por equipo (anti-leakage cross-equipo dentro del fold)
  - LOYO inter-año (2023, 2024, 2025) — train hasta Y-1
  - holdout 2026 CONGELADO

DOF check: tree_count * leaves_avg < N_train/10. Alertar si excede.

Salida: analisis/motor_xg_v2_04_xgboost.json
"""

import sqlite3
import json
import numpy as np
from collections import defaultdict
from math import sqrt
from pathlib import Path

from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_04_xgboost.json'
RNG = np.random.default_rng(42)


# ------------------------------------------------------------------
# 1) Carga datos
# ------------------------------------------------------------------
def cargar_params():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    alfa_ema = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND tipo='float'"):
        alfa_ema[r[0]] = float(r[1])
    DEF_ALFA = 0.10
    con.close()
    return alfa_ema, DEF_ALFA


def cargar_partidos_full():
    """Carga partidos con stats COMPLETAS (raw del equipo + rival) y opcional cuotas."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT s.liga, s.fecha, s.ht, s.at,
               s.hg, s.ag,
               s.hst, s.ast, s.hs, s.as_v, s.hc, s.ac,
               s.h_pos, s.a_pos,
               s.h_pass_pct, s.a_pass_pct,
               s.h_saves, s.a_saves,
               s.h_blocks, s.a_blocks,
               s.h_longballs_acc, s.a_longballs_acc,
               s.ht_fdco_norm, s.at_fdco_norm, s.fecha_fdco,
               c.cuota_1, c.cuota_x, c.cuota_2
        FROM stats_partido_espn s
        LEFT JOIN cuotas_historicas_fdco c
          ON s.ht_fdco_norm = c.equipo_local_norm
         AND s.at_fdco_norm = c.equipo_visita_norm
         AND s.fecha_fdco = c.fecha
        WHERE s.hg IS NOT NULL AND s.ag IS NOT NULL
          AND s.hst IS NOT NULL AND s.ast IS NOT NULL
        ORDER BY s.fecha ASC, s.ht ASC
    """).fetchall()
    con.close()
    return rows


# ------------------------------------------------------------------
# 2) Construccion eventos + EMAs pre-evento + cuotas implicitas
# ------------------------------------------------------------------
def imp_probs(c1, cx, c2):
    """Probabilidades implicitas overround-removed."""
    if c1 is None or cx is None or c2 is None:
        return None, None, None
    try:
        c1, cx, c2 = float(c1), float(cx), float(c2)
        s = 1.0/c1 + 1.0/cx + 1.0/c2
        return (1.0/c1)/s, (1.0/cx)/s, (1.0/c2)/s
    except Exception:
        return None, None, None


def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
         h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
         h_blocks, a_blocks, h_longballs_acc, a_longballs_acc,
         ht_fdco, at_fdco, fdate, c1, cx, c2) = r

        p1, px, p2 = imp_probs(c1, cx, c2)

        shots_off_h = max(0, (hs or 0) - (hst or 0))
        shots_off_a = max(0, (as_v or 0) - (ast or 0))

        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at, 'es_local': 1,
            # Stats del equipo
            'sot': hst or 0,
            'shots_off': shots_off_h,
            'corners': hc or 0,
            'pos': h_pos, 'pass_pct': h_pass_pct,
            'saves': h_saves, 'blocks': h_blocks,
            'longballs_acc': h_longballs_acc,
            # Stats del rival
            'sot_rival': ast or 0,
            'shots_off_rival': shots_off_a,
            'corners_rival': ac or 0,
            'pos_rival': a_pos, 'pass_pct_rival': a_pass_pct,
            'saves_rival': a_saves, 'blocks_rival': a_blocks,
            'longballs_acc_rival': a_longballs_acc,
            # Cuota implicita (perspectiva local)
            'p_imp_propio': p1, 'p_imp_x': px, 'p_imp_rival': p2,
            'goles': hg,
            'has_cuota': p1 is not None,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht, 'es_local': 0,
            'sot': ast or 0,
            'shots_off': shots_off_a,
            'corners': ac or 0,
            'pos': a_pos, 'pass_pct': a_pass_pct,
            'saves': a_saves, 'blocks': a_blocks,
            'longballs_acc': a_longballs_acc,
            'sot_rival': hst or 0,
            'shots_off_rival': shots_off_h,
            'corners_rival': hc or 0,
            'pos_rival': h_pos, 'pass_pct_rival': h_pass_pct,
            'saves_rival': h_saves, 'blocks_rival': h_blocks,
            'longballs_acc_rival': h_longballs_acc,
            'p_imp_propio': p2, 'p_imp_x': px, 'p_imp_rival': p1,
            'goles': ag,
            'has_cuota': p2 is not None,
        })
    eventos.sort(key=lambda e: e['fecha'])
    return eventos


def attach_emas_pre_evento(eventos):
    """EMAs pre-evento por equipo: ema_sot, ema_pos, ema_goles_l3, n_history."""
    state = defaultdict(lambda: {
        'ema_sot': None, 'ema_pos': None, 'last_3_goles': [], 'n': 0,
    })
    alfa = 0.10
    for ev in eventos:
        s = state[ev['equipo']]
        ev['ema_sot'] = s['ema_sot'] if s['ema_sot'] is not None else 4.0
        ev['ema_pos'] = s['ema_pos'] if s['ema_pos'] is not None else 50.0
        ev['ema_goles_l3'] = (sum(s['last_3_goles']) / len(s['last_3_goles'])) if s['last_3_goles'] else 1.4
        ev['n_history'] = s['n']

        # Update
        sot = ev['sot']
        if s['ema_sot'] is None:
            s['ema_sot'] = sot
        else:
            s['ema_sot'] = alfa * sot + (1 - alfa) * s['ema_sot']
        pos = ev['pos']
        if pos is not None:
            if s['ema_pos'] is None:
                s['ema_pos'] = pos
            else:
                s['ema_pos'] = alfa * pos + (1 - alfa) * s['ema_pos']
        s['last_3_goles'].append(ev['goles'])
        if len(s['last_3_goles']) > 3:
            s['last_3_goles'] = s['last_3_goles'][-3:]
        s['n'] += 1
    return eventos


# ------------------------------------------------------------------
# 3) Build feature matrix
# ------------------------------------------------------------------
LIGAS_ALL = [
    'Argentina', 'Brasil', 'Inglaterra', 'Espana', 'Italia', 'Turquia',
    'Francia', 'Alemania', 'Noruega', 'Chile', 'Colombia', 'Bolivia',
    'Venezuela', 'Peru', 'Ecuador', 'Uruguay'
]


def build_X_y(eventos, use_cuotas=False):
    """X (numpy float, NaN allowed), y (numpy), grupos (equipo) + fecha (yr)."""
    feat_cols = [
        'sot', 'shots_off', 'corners', 'pos', 'pass_pct', 'saves', 'blocks', 'longballs_acc',
        'sot_rival', 'shots_off_rival', 'corners_rival', 'pos_rival', 'pass_pct_rival',
        'saves_rival', 'blocks_rival', 'longballs_acc_rival',
        'ema_sot', 'ema_pos', 'ema_goles_l3', 'es_local',
    ]
    if use_cuotas:
        feat_cols += ['p_imp_propio', 'p_imp_x', 'p_imp_rival']

    # one-hot liga
    liga_cols = [f'liga_{lg}' for lg in LIGAS_ALL]
    feat_cols += liga_cols

    X = np.full((len(eventos), len(feat_cols)), np.nan, dtype=np.float64)
    y = np.zeros(len(eventos), dtype=np.float64)
    grupos = np.empty(len(eventos), dtype=object)
    fechas = np.empty(len(eventos), dtype=object)

    base_n = 20 if not use_cuotas else 23

    for i, ev in enumerate(eventos):
        # raw
        X[i, 0] = ev['sot']
        X[i, 1] = ev['shots_off']
        X[i, 2] = ev['corners']
        X[i, 3] = ev['pos'] if ev['pos'] is not None else np.nan
        X[i, 4] = ev['pass_pct'] if ev['pass_pct'] is not None else np.nan
        X[i, 5] = ev['saves'] if ev['saves'] is not None else np.nan
        X[i, 6] = ev['blocks'] if ev['blocks'] is not None else np.nan
        X[i, 7] = ev['longballs_acc'] if ev['longballs_acc'] is not None else np.nan
        X[i, 8] = ev['sot_rival']
        X[i, 9] = ev['shots_off_rival']
        X[i, 10] = ev['corners_rival']
        X[i, 11] = ev['pos_rival'] if ev['pos_rival'] is not None else np.nan
        X[i, 12] = ev['pass_pct_rival'] if ev['pass_pct_rival'] is not None else np.nan
        X[i, 13] = ev['saves_rival'] if ev['saves_rival'] is not None else np.nan
        X[i, 14] = ev['blocks_rival'] if ev['blocks_rival'] is not None else np.nan
        X[i, 15] = ev['longballs_acc_rival'] if ev['longballs_acc_rival'] is not None else np.nan
        X[i, 16] = ev['ema_sot']
        X[i, 17] = ev['ema_pos']
        X[i, 18] = ev['ema_goles_l3']
        X[i, 19] = ev['es_local']
        if use_cuotas:
            X[i, 20] = ev['p_imp_propio'] if ev['p_imp_propio'] is not None else np.nan
            X[i, 21] = ev['p_imp_x'] if ev['p_imp_x'] is not None else np.nan
            X[i, 22] = ev['p_imp_rival'] if ev['p_imp_rival'] is not None else np.nan

        # one-hot liga
        for j, lg in enumerate(LIGAS_ALL):
            X[i, base_n + j] = 1.0 if ev['liga'] == lg else 0.0

        y[i] = ev['goles']
        grupos[i] = ev['equipo']
        fechas[i] = ev['fecha']

    return X, y, grupos, fechas, feat_cols


# ------------------------------------------------------------------
# 4) RMSE forward-EMA
# ------------------------------------------------------------------
def computar_rmse_forward_ema(eventos, xg_final_por_evento, alfa_ema, def_alfa):
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
# 5) DOF check
# ------------------------------------------------------------------
def estimar_dof(model, n_train):
    """tree_count * leaves_avg como proxy de DOF efectivo."""
    booster = model.get_booster()
    df_dump = booster.trees_to_dataframe()
    n_trees = df_dump['Tree'].nunique()
    # leaves = nodos sin children (Yes=='Leaf')
    leaves = df_dump[df_dump['Feature'] == 'Leaf']
    leaves_per_tree = leaves.groupby('Tree').size()
    avg_leaves = float(leaves_per_tree.mean()) if len(leaves_per_tree) > 0 else 0.0
    dof = int(n_trees * avg_leaves)
    cap = n_train / 10
    return {
        'n_trees': int(n_trees),
        'avg_leaves': avg_leaves,
        'dof_estimado': dof,
        'dof_cap_10:1': int(cap),
        'dof_safe': dof < cap,
    }


# ------------------------------------------------------------------
# 6) Grid search XGBoost (mini, anti-overfit)
# ------------------------------------------------------------------
def grid_search_xgb(X_tr, y_tr, X_val, y_val, max_iter=12, seed=42):
    """Mini-grid search, anti-overfit. Devuelve mejor modelo + best_params + RMSE_val."""
    grid = []
    for max_depth in (3, 4):
        for n_est in (100, 200):
            for lr in (0.05, 0.10):
                for ra in (0.01, 0.10, 1.0):
                    for rl in (0.10, 1.0, 10.0):
                        grid.append({
                            'max_depth': max_depth, 'n_estimators': n_est,
                            'learning_rate': lr, 'reg_alpha': ra, 'reg_lambda': rl,
                            'min_child_weight': 10, 'random_state': seed,
                        })
    # Reducir grid: muestreo
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(grid), size=min(max_iter, len(grid)), replace=False)
    grid = [grid[i] for i in idx]

    best_rmse = float('inf'); best_model = None; best_params = None
    for params in grid:
        m = XGBRegressor(
            objective='reg:squarederror',
            tree_method='hist',
            early_stopping_rounds=20,
            eval_metric='rmse',
            verbosity=0,
            **params
        )
        try:
            m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
        except Exception as e:
            print(f'  fit error: {e}')
            continue
        pred_val = m.predict(X_val)
        rmse_val = float(np.sqrt(np.mean((pred_val - y_val) ** 2)))
        if rmse_val < best_rmse:
            best_rmse = rmse_val; best_model = m; best_params = params
    return best_model, best_params, best_rmse


# ------------------------------------------------------------------
# 7) GroupKFold por equipo (anti-leakage cross-equipo dentro del fold)
# ------------------------------------------------------------------
def groupkfold_xgb(X, y, grupos, eventos, alfa_ema, def_alfa, thetas, use_cuotas, seed=42):
    """5-fold GroupKFold por equipo. Fit XGBoost en train folds; predict en test fold;
    aplicar theta-grid + EMA forward para RMSE."""
    gkf = GroupKFold(n_splits=5)
    n = len(eventos)
    preds_oof = np.full(n, np.nan)

    fold_info = []
    for k, (idx_tr, idx_te) in enumerate(gkf.split(X, y, groups=grupos)):
        # Dentro del fold de train, 80/20 para early stopping
        rng = np.random.default_rng(seed + k)
        perm = rng.permutation(len(idx_tr))
        cutoff = int(0.8 * len(idx_tr))
        tr_idx2 = idx_tr[perm[:cutoff]]; val_idx2 = idx_tr[perm[cutoff:]]

        m, p, rmse_val = grid_search_xgb(X[tr_idx2], y[tr_idx2], X[val_idx2], y[val_idx2],
                                          max_iter=8, seed=seed + k)
        if m is None:
            continue
        preds_oof[idx_te] = m.predict(X[idx_te])
        dof = estimar_dof(m, len(tr_idx2))
        fold_info.append({
            'fold': k, 'n_train': len(idx_tr), 'n_test': len(idx_te),
            'best_params': p, 'rmse_val': rmse_val, 'dof': dof,
        })

    # Para eventos sin pred (raros, si grupo no quedó en ningun test fold), fallback a ema_goles_l3
    nan_mask = np.isnan(preds_oof)
    if nan_mask.sum() > 0:
        for i in np.where(nan_mask)[0]:
            preds_oof[i] = eventos[i].get('ema_goles_l3', 1.4)

    # Theta-grid
    grid_res = {}
    for theta in thetas:
        xg_final = [theta * preds_oof[i] + (1 - theta) * eventos[i]['goles']
                    for i in range(n)]
        grid_res[f'{theta:.2f}'] = computar_rmse_forward_ema(eventos, xg_final, alfa_ema, def_alfa)
    return {'fold_info': fold_info, 'grid': grid_res, 'n_total': n,
            'use_cuotas': use_cuotas, 'n_nan_imputed': int(nan_mask.sum())}


# ------------------------------------------------------------------
# 8) LOYO inter-año
# ------------------------------------------------------------------
def loyo_xgb(X, y, eventos, fechas, feat_cols, alfa_ema, def_alfa, thetas, anios=('2023', '2024', '2025'), seed=42):
    """Para cada Y, entrenar en eventos con fecha < Y y predecir TODO el universo."""
    out = {}
    yrs = np.array([f[:4] for f in fechas])
    for y_ in anios:
        mask_train = yrs < y_
        mask_other = ~mask_train  # incluye Y y todos los posteriores
        X_tr = X[mask_train]; y_tr = y[mask_train]
        if len(X_tr) < 100:
            out[y_] = {'error': 'too few train', 'n_train': int(mask_train.sum())}
            continue
        # split 80/20 internal
        rng = np.random.default_rng(seed)
        perm = rng.permutation(len(X_tr))
        cutoff = int(0.8 * len(X_tr))
        Xtr2 = X_tr[perm[:cutoff]]; ytr2 = y_tr[perm[:cutoff]]
        Xv = X_tr[perm[cutoff:]]; yv = y_tr[perm[cutoff:]]
        m, p, rmse_v = grid_search_xgb(Xtr2, ytr2, Xv, yv, max_iter=8, seed=seed)
        if m is None:
            out[y_] = {'error': 'fit failed'}
            continue
        preds = m.predict(X)
        dof = estimar_dof(m, len(Xtr2))
        grid_y = {}
        for theta in thetas:
            xg_final = [theta * preds[i] + (1 - theta) * eventos[i]['goles']
                        for i in range(len(eventos))]
            res = computar_rmse_forward_ema(eventos, xg_final, alfa_ema, def_alfa)
            grid_y[f'{theta:.2f}'] = {y_: res.get(y_), 'OOS_pool': res.get('OOS_pool')}
        # feature importances
        importances = m.feature_importances_
        top_feats = sorted(zip(feat_cols, importances.tolist()), key=lambda kv: -kv[1])[:10]
        out[y_] = {'n_train': int(mask_train.sum()), 'best_params': p,
                   'rmse_val_internal': rmse_v, 'dof': dof,
                   'top_features': top_feats, 'grid': grid_y}
    return out


# ------------------------------------------------------------------
# 9) Main
# ------------------------------------------------------------------
def main():
    print('=== FASE 2.04 — XGBOOST DOF SAFE ===')
    alfa_ema, def_alfa = cargar_params()
    partidos = cargar_partidos_full()
    print(f'Partidos: {len(partidos)}')
    eventos = construir_eventos(partidos)
    print(f'Eventos: {len(eventos)}')
    eventos = attach_emas_pre_evento(eventos)

    n_cuotas = sum(1 for e in eventos if e['has_cuota'])
    print(f'Eventos con cuota: {n_cuotas} / {len(eventos)}')

    thetas = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]

    # Cuotas matched: el N efectivo subset = los que tienen cuota matched
    # 8892 partidos matched -> 17784 eventos. Pero hay que calcular sobre el subset.

    # ---- 9.1 GroupKFold por equipo, SIN cuotas (N=13430 partidos / 26860 eventos) ----
    print('\n--- GroupKFold por equipo, SIN cuotas (N=26860 eventos) ---')
    X, y, grupos, fechas, feat_cols = build_X_y(eventos, use_cuotas=False)
    print(f'X.shape = {X.shape}, n_features = {len(feat_cols)}')
    res_gkf_nocuotas = groupkfold_xgb(X, y, grupos, eventos, alfa_ema, def_alfa, thetas, use_cuotas=False)
    print(f'\n{"theta":>6} | {"OOS_pool":>10} | {"IS_2026":>10}')
    best_t_nc = None; best_rmse_nc = float('inf')
    for ts, r in res_gkf_nocuotas['grid'].items():
        oos = r['OOS_pool']['rmse']; is26 = r['IS_2026']['rmse']
        print(f'  {ts:>5} | {oos:>10.4f} | {is26 if is26 is not None else 0:>10.4f}')
        if oos < best_rmse_nc:
            best_rmse_nc = oos; best_t_nc = ts
    print(f'BEST theta (no cuotas) = {best_t_nc}, RMSE = {best_rmse_nc:.4f}')

    # ---- 9.2 GroupKFold por equipo, CON cuotas (subset N=8892 partidos / 17784 eventos) ----
    print('\n--- GroupKFold por equipo, CON cuotas (subset N=17784 eventos matched) ---')
    eventos_cuotas = [e for e in eventos if e['has_cuota']]
    print(f'Eventos cuotas: {len(eventos_cuotas)}')
    X_c, y_c, grupos_c, fechas_c, feat_cols_c = build_X_y(eventos_cuotas, use_cuotas=True)
    print(f'X.shape = {X_c.shape}')
    res_gkf_cuotas = groupkfold_xgb(X_c, y_c, grupos_c, eventos_cuotas, alfa_ema, def_alfa, thetas, use_cuotas=True)
    print(f'\n{"theta":>6} | {"OOS_pool":>10} | {"IS_2026":>10}')
    best_t_c = None; best_rmse_c = float('inf')
    for ts, r in res_gkf_cuotas['grid'].items():
        oos = r['OOS_pool']['rmse']; is26 = r['IS_2026']['rmse']
        print(f'  {ts:>5} | {oos:>10.4f} | {is26 if is26 is not None else 0:>10.4f}')
        if oos < best_rmse_c:
            best_rmse_c = oos; best_t_c = ts
    print(f'BEST theta (con cuotas) = {best_t_c}, RMSE = {best_rmse_c:.4f}')

    # ---- 9.3 LOYO sin cuotas (más comparable a baseline) ----
    print('\n--- LOYO inter-año, SIN cuotas ---')
    res_loyo = loyo_xgb(X, y, eventos, fechas, feat_cols, alfa_ema, def_alfa, thetas)
    for y_, info in res_loyo.items():
        if 'error' in info:
            print(f'  {y_}: skip ({info["error"]})')
            continue
        # Best theta para Y
        best_y = None; best_y_rmse = float('inf')
        for ts, gres in info['grid'].items():
            r = gres.get(y_)
            if r and r.get('rmse') is not None and r['rmse'] < best_y_rmse:
                best_y_rmse = r['rmse']; best_y = ts
        top_feat_str = ', '.join(f'{k}({v:.3f})' for k, v in info['top_features'][:5])
        print(f'  {y_}: n_train={info["n_train"]}, BEST theta={best_y}, RMSE_{y_}={best_y_rmse:.4f}')
        print(f'        top5_feat: {top_feat_str}')
        print(f'        DOF: {info["dof"]}')

    # ---- 9.4 Top features GLOBAL (modelo entero sobre train pre-2026, sin cuotas) ----
    print('\n--- Feature importances GLOBAL (train 2022-2025, sin cuotas) ---')
    yrs = np.array([f[:4] for f in fechas])
    mask_pre2026 = yrs != '2026'
    X_pre = X[mask_pre2026]; y_pre = y[mask_pre2026]
    rng = np.random.default_rng(42)
    perm = rng.permutation(len(X_pre))
    cutoff = int(0.8 * len(X_pre))
    Xtr2 = X_pre[perm[:cutoff]]; ytr2 = y_pre[perm[:cutoff]]
    Xv = X_pre[perm[cutoff:]]; yv = y_pre[perm[cutoff:]]
    m_global, p_global, rmse_v_global = grid_search_xgb(Xtr2, ytr2, Xv, yv, max_iter=8)
    dof_global = estimar_dof(m_global, len(Xtr2))
    importances = m_global.feature_importances_
    top_feats = sorted(zip(feat_cols, importances.tolist()), key=lambda kv: -kv[1])[:10]
    print(f'best_params = {p_global}')
    print(f'rmse_val_internal = {rmse_v_global:.4f}')
    print(f'DOF = {dof_global}')
    print('Top 10 feats:')
    for f_, w in top_feats:
        print(f'  {f_:<30s} {w:.4f}')

    # Output
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    breaks_floor_nc = best_rmse_nc < 1.18
    breaks_floor_c = best_rmse_c < 1.18
    out = {
        '_meta': {
            'N_partidos': len(partidos),
            'N_eventos_total': len(eventos),
            'N_partidos_cuotas_matched': sum(1 for e in eventos if e['has_cuota']) // 2,
            'N_eventos_cuotas_matched': sum(1 for e in eventos if e['has_cuota']),
            'WARMUP': WARMUP,
            'thetas_grid': thetas,
            'best_theta_OOS_no_cuotas': best_t_nc,
            'best_OOS_RMSE_no_cuotas': best_rmse_nc,
            'best_theta_OOS_con_cuotas': best_t_c,
            'best_OOS_RMSE_con_cuotas': best_rmse_c,
            'baseline_V5_RMSE': 1.1963,
            'breaks_poisson_floor_no_cuotas': breaks_floor_nc,
            'breaks_poisson_floor_con_cuotas': breaks_floor_c,
            'feat_cols': feat_cols,
            'feat_cols_cuotas': feat_cols_c,
        },
        'GroupKFold_NO_cuotas': res_gkf_nocuotas,
        'GroupKFold_CON_cuotas': res_gkf_cuotas,
        'LOYO_no_cuotas': res_loyo,
        'global_model': {
            'best_params': p_global,
            'rmse_val_internal': rmse_v_global,
            'dof': dof_global,
            'top_features': top_feats,
        },
    }
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f'\nGuardado {OUT_JSON}')
    print(f'breaks_poisson_floor (no cuotas): {breaks_floor_nc}')
    print(f'breaks_poisson_floor (con cuotas): {breaks_floor_c}')


if __name__ == '__main__':
    main()

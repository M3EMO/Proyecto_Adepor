"""
xG model derivado del shotmap SofaScore — versión robusta.

Approach (siguiendo Caley-Maye / Statsbomb open-source xG models):
  1. Para cada shot del shotmap_json en sofascore_match_features:
     - Coordenadas: playerCoordinates (x, y) — verificar empíricamente cuál arco
     - Calcular distance + angle geométrico al arco
     - bodyPart, situation como categóricas
  2. Entrenar Logistic Regression: P(goal=1) ~ features
  3. 5-fold CV temporal para reportar log-loss + Brier OOS honesta
  4. Por partido: xG_local = Σ P(goal | shot) sobre shots isHome=True
  5. Persistir coefs en config_motor_valores.xg_model_coefs_v2
  6. Update sofascore_match_features.xg_shotmap_l/v + n_shots_shotmap

Coordenadas SofaScore (verificación empírica):
  - playerCoordinates.x ∈ [0, 100]: % cancha desde su propio arco?
  - Hipótesis: shots con ALTA conversión (gol) tienen x bajo (cerca arco contrario)
  - VERIFICACION: comparar mean(x) entre goal vs miss -> si goal < miss, hipótesis OK

Constantes geométricas:
  - Cancha cancha real: ~105m x 68m
  - Width meta: 7.32m
  - En coords normalizadas (0-100): width meta = 7.32/68*100 ≈ 10.76 unidades
  - distance_unit = sqrt((dx*1.05)^2 + (dy*0.68)^2) en m REAL
"""

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold

DB = 'fondo_quant.db'
OUT_JSON = 'analisis/motor_xg_v2_14_xg_from_shotmap.json'

# Cancha real en metros (FIFA standard)
CANCHA_W_M = 105.0
CANCHA_H_M = 68.0
META_W_M = 7.32
PUNTO_PENAL_M = 11.0


def cargar_shotmaps():
    """Carga todos los shots de sofascore_match_features."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag, shotmap_json
        FROM sofascore_match_features
        WHERE shotmap_json IS NOT NULL AND error IS NULL
    ''').fetchall()
    con.close()

    all_shots = []
    for evt_id, liga, fecha, ht, at, hg, ag, sm_json in rows:
        try:
            sm = json.loads(sm_json)
        except (TypeError, json.JSONDecodeError):
            continue
        for s in sm.get('shotmap', []):
            s['_evt_id'] = evt_id
            s['_liga'] = liga
            s['_fecha'] = fecha
            s['_ht'] = ht
            s['_at'] = at
            s['_hg'] = hg
            s['_ag'] = ag
            all_shots.append(s)
    return all_shots


def verificar_orientacion(all_shots):
    """Empíricamente determinar si playerCoordinates.x bajo = arco contrario."""
    xs_goal = []
    xs_miss = []
    for s in all_shots:
        pc = s.get('playerCoordinates') or {}
        x = pc.get('x')
        if x is None:
            continue
        if s.get('shotType') == 'goal':
            xs_goal.append(x)
        else:
            xs_miss.append(x)
    if not xs_goal or not xs_miss:
        return None
    mean_g = sum(xs_goal) / len(xs_goal)
    mean_m = sum(xs_miss) / len(xs_miss)
    print(f'Verificación coordenadas:')
    print(f'  Mean playerCoordinates.x para GOLES: {mean_g:.2f} (n={len(xs_goal)})')
    print(f'  Mean playerCoordinates.x para NO-GOLES: {mean_m:.2f} (n={len(xs_miss)})')
    if mean_g < mean_m:
        print('  -> Conclusión: x BAJO = cerca arco contrario (origen 0,50)')
        return 'low_x_near_goal'
    else:
        print('  -> Conclusión: x ALTO = cerca arco contrario')
        return 'high_x_near_goal'


def feature_engineering(shot, orientation='low_x_near_goal'):
    """Extrae features para xG."""
    pc = shot.get('playerCoordinates') or {}
    px = pc.get('x')
    py = pc.get('y')
    if px is None or py is None:
        return None

    # Convertir a metros desde el arco (ortografía: arco contrario en x=0)
    if orientation == 'low_x_near_goal':
        x_to_goal = px  # ya en % desde arco (0 = pegado al arco contrario)
    else:
        x_to_goal = 100 - px

    # Convertir a metros reales
    x_m = (x_to_goal / 100.0) * CANCHA_W_M
    y_m = ((py - 50) / 100.0) * CANCHA_H_M  # 0 = centro arco

    # Distancia euclidiana
    distance = math.sqrt(x_m ** 2 + y_m ** 2)

    # Ángulo subtendido por arco (formula clásica Caley):
    # angle = atan2(W*x, x^2 + y^2 - (W/2)^2)
    # con W=7.32m
    if x_m < 0.5:
        angle = math.pi * 2  # extremo (gol o muy cerca)
    else:
        denom = x_m ** 2 + y_m ** 2 - (META_W_M / 2) ** 2
        if denom <= 0:
            angle = math.pi
        else:
            angle = math.atan2(META_W_M * x_m, denom)

    # Inside box
    is_inside_box = distance < 16.5  # área grande oficialmente 16.5m

    body = (shot.get('bodyPart') or 'unknown').lower()
    situation = (shot.get('situation') or 'regular-play').lower()
    shot_type = (shot.get('shotType') or 'miss').lower()

    return {
        'distance': distance,
        'angle': angle,
        'inv_distance_sq': 1.0 / max(distance ** 2, 1),
        'is_inside_box': int(is_inside_box),
        'body_head': int(body == 'head'),
        'body_left_foot': int(body == 'left-foot'),
        'body_other': int(body not in ('head', 'left-foot', 'right-foot')),
        'sit_penalty': int(situation == 'penalty'),
        'sit_set_piece': int(situation == 'set-piece'),
        'sit_corner': int(situation == 'corner'),
        'sit_fast_break': int(situation == 'fast-break'),
        'sit_assisted': int(situation == 'assisted'),
        # target
        'is_goal': int(shot_type == 'goal'),
        # context
        'is_home': int(shot.get('isHome', False)),
        'evt_id': shot.get('_evt_id'),
        'fecha': shot.get('_fecha'),
        'liga': shot.get('_liga'),
    }


def entrenar_xg(all_shots, orientation):
    """Entrena LogReg con 5-fold CV temporal."""
    feats = [feature_engineering(s, orientation) for s in all_shots]
    feats = [f for f in feats if f]

    feature_names = [
        'distance', 'inv_distance_sq', 'angle', 'is_inside_box',
        'body_head', 'body_left_foot', 'body_other',
        'sit_penalty', 'sit_set_piece', 'sit_corner', 'sit_fast_break', 'sit_assisted',
    ]

    X = np.array([[f[k] for k in feature_names] for f in feats], dtype=float)
    y = np.array([f['is_goal'] for f in feats], dtype=int)

    print(f'\nTrain set: {len(X)} shots, {y.sum()} goles ({100*y.mean():.2f}%)')

    if len(X) < 200:
        print('Insuficientes shots para entrenar xG model.')
        return None, None, None, None

    # Escalado solo continuas
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Modelo final IN-SAMPLE para coefs reportables
    model = LogisticRegression(C=1.0, max_iter=500, solver='lbfgs')
    model.fit(X_scaled, y)

    pred = model.predict_proba(X_scaled)[:, 1]
    sum_xg = pred.sum()
    sum_actual = int(y.sum())
    print(f'\nIN-SAMPLE: sum xG predicted={sum_xg:.1f}  vs goles={sum_actual} (ratio {sum_xg/max(sum_actual,1):.3f})')

    # CROSS-VALIDATION 5-fold para honest brier + log-loss
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    briers = []
    losslogs = []
    for fold_i, (train_idx, val_idx) in enumerate(kf.split(X_scaled)):
        m = LogisticRegression(C=1.0, max_iter=500, solver='lbfgs')
        m.fit(X_scaled[train_idx], y[train_idx])
        p_val = m.predict_proba(X_scaled[val_idx])[:, 1]
        brier = ((p_val - y[val_idx]) ** 2).mean()
        # log-loss with clipping
        eps = 1e-15
        p_clip = np.clip(p_val, eps, 1 - eps)
        ll = -(y[val_idx] * np.log(p_clip) + (1 - y[val_idx]) * np.log(1 - p_clip)).mean()
        briers.append(brier)
        losslogs.append(ll)
    print(f'5-fold CV: Brier={np.mean(briers):.4f} ± {np.std(briers):.4f}  | LogLoss={np.mean(losslogs):.4f} ± {np.std(losslogs):.4f}')

    # Coefs reportables
    coefs = dict(zip(feature_names, model.coef_[0].tolist()))
    print('\nCoefs (z-scored features):')
    for k, v in sorted(coefs.items(), key=lambda x: -abs(x[1])):
        print(f'  {k:<22s} {v:+.4f}')
    print(f'  intercept              {model.intercept_[0]:+.4f}')

    eval_dict = {
        'orientation': orientation,
        'n_shots': len(X),
        'n_goals': int(y.sum()),
        'pct_goals': float(y.mean()),
        'sum_xg_in_sample': float(sum_xg),
        'ratio_xg_goals_in_sample': float(sum_xg / max(sum_actual, 1)),
        'cv5_brier_mean': float(np.mean(briers)),
        'cv5_brier_std': float(np.std(briers)),
        'cv5_logloss_mean': float(np.mean(losslogs)),
        'cv5_logloss_std': float(np.std(losslogs)),
        'coefs': coefs,
        'intercept': float(model.intercept_[0]),
        'feature_names': feature_names,
        'scaler_mean': scaler.mean_.tolist(),
        'scaler_scale': scaler.scale_.tolist(),
    }
    return model, scaler, feature_names, eval_dict


def aplicar_a_partidos(model, scaler, feature_names, all_shots, orientation):
    feats = [feature_engineering(s, orientation) for s in all_shots]
    feats = [f for f in feats if f]
    X = np.array([[f[k] for k in feature_names] for f in feats], dtype=float)
    X_scaled = scaler.transform(X)
    p_goal = model.predict_proba(X_scaled)[:, 1]

    by_match = defaultdict(lambda: {'xg_l': 0.0, 'xg_v': 0.0, 'n_shots': 0})
    for f, xg in zip(feats, p_goal):
        evt = f['evt_id']
        if f['is_home']:
            by_match[evt]['xg_l'] += xg
        else:
            by_match[evt]['xg_v'] += xg
        by_match[evt]['n_shots'] += 1
    return by_match


def persistir(by_match, eval_dict):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    n_updated = 0
    for evt_id, m in by_match.items():
        cur.execute('''
            UPDATE sofascore_match_features
            SET xg_shotmap_l = ?, xg_shotmap_v = ?, n_shots_shotmap = ?
            WHERE sofa_event_id = ?
        ''', (m['xg_l'], m['xg_v'], m['n_shots'], evt_id))
        n_updated += 1

    # Persistir coefs en config_motor_valores como JSON
    cur.execute('''
        INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, valor_texto, tipo, fuente)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ('xg_model_coefs_v2', 'global', None, json.dumps(eval_dict), 'json', 'motor_xg_v2_14_xg_from_shotmap.py'))
    con.commit()
    con.close()
    print(f'\nPersistidos {n_updated} partidos con xG calculado')
    print('Coefs persistidos en config_motor_valores.xg_model_coefs_v2')


def main():
    all_shots = cargar_shotmaps()
    print(f'Total shots cargados: {len(all_shots)}')
    if len(all_shots) < 200:
        print('Insuficientes shots — esperar más backfill.')
        return

    # Verificar orientación coords
    orientation = verificar_orientacion(all_shots)
    if not orientation:
        orientation = 'low_x_near_goal'

    model, scaler, fnames, eval_dict = entrenar_xg(all_shots, orientation)
    if model is None:
        return

    by_match = aplicar_a_partidos(model, scaler, fnames, all_shots, orientation)
    print(f'\nPartidos con xG calculado: {len(by_match)}')

    # Sample 5
    print('\nSample (5 partidos):')
    print(f'{"evt_id":<10} {"xg_l":>6} {"xg_v":>6} {"n_shots":>8}')
    for evt, m in list(by_match.items())[:5]:
        print(f'{evt:<10} {m["xg_l"]:>6.2f} {m["xg_v"]:>6.2f} {m["n_shots"]:>8}')

    persistir(by_match, eval_dict)

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(eval_dict, f, indent=2)
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

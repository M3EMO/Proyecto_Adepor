"""
xG v3 — modelo híbrido shot-level: SOFA xgot directo + custom LogReg fallback.

Lógica:
  xg_v3_per_shot = shot.xgot if shot.xgot != None else logreg_custom(shot)
  xg_v3_team = sum(xg_v3_per_shot) for shots of team

Validación empírica esperada:
  - EUR + Brasil + Uruguay: SOFA xgot domina (RMSE -30% vs custom)
  - LATAM exóticas (ARG/BOL/ECU/PER/VEN): custom LogReg sigue (SOFA 0% populated)
  - Global: mejor que ambos por separado

Persistir en sofascore_match_features.xg_v3_l/v.
Comparar contra xg_shotmap_l/v (V_custom) sobre 762 partidos.
"""
import sqlite3, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')
OUT_JSON = str(ROOT / 'analisis' / 'xg_v3_hibrido_sofa_custom.json')

CANCHA_W_M = 105.0
CANCHA_H_M = 68.0
META_W_M = 7.32


def feature_engineering(shot):
    pc = shot.get('playerCoordinates') or {}
    px = pc.get('x')
    py = pc.get('y')
    if px is None or py is None:
        return None
    x_to_goal = px
    x_m = (x_to_goal / 100.0) * CANCHA_W_M
    y_m = ((py - 50) / 100.0) * CANCHA_H_M
    distance = math.sqrt(x_m ** 2 + y_m ** 2)
    if x_m < 0.5:
        angle = math.pi * 2
    else:
        denom = x_m ** 2 + y_m ** 2 - (META_W_M / 2) ** 2
        if denom <= 0:
            angle = math.pi
        else:
            angle = math.atan2(META_W_M * x_m, denom)
    is_inside_box = distance < 16.5
    body = (shot.get('bodyPart') or 'unknown').lower()
    situation = (shot.get('situation') or 'regular-play').lower()
    shot_type = (shot.get('shotType') or 'miss').lower()
    return {
        'distance': distance,
        'inv_distance_sq': 1.0 / max(distance ** 2, 1),
        'angle': angle,
        'is_inside_box': int(is_inside_box),
        'body_head': int(body == 'head'),
        'body_left_foot': int(body == 'left-foot'),
        'body_other': int(body not in ('head', 'left-foot', 'right-foot')),
        'sit_penalty': int(situation == 'penalty'),
        'sit_set_piece': int(situation == 'set-piece'),
        'sit_corner': int(situation == 'corner'),
        'sit_fast_break': int(situation == 'fast-break'),
        'sit_assisted': int(situation == 'assisted'),
        'is_goal': int(shot_type == 'goal'),
    }


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar coefs custom v2 ya entrenados
    coefs_row = cur.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='xg_model_coefs_v2'").fetchone()
    if not coefs_row:
        print('xg_model_coefs_v2 no encontrado')
        return
    coefs_data = json.loads(coefs_row[0])
    feature_names = coefs_data['feature_names']
    coefs_arr = np.array([coefs_data['coefs'][f] for f in feature_names])
    intercept = coefs_data['intercept']
    scaler_mean = np.array(coefs_data['scaler_mean'])
    scaler_scale = np.array(coefs_data['scaler_scale'])

    def predict_custom(shot):
        f = feature_engineering(shot)
        if f is None:
            return None
        x = np.array([f[k] for k in feature_names])
        x_scaled = (x - scaler_mean) / scaler_scale
        z = np.dot(x_scaled, coefs_arr) + intercept
        return 1.0 / (1.0 + math.exp(-z))

    # Cargar partidos
    rows = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               xg_shotmap_l, xg_shotmap_v, shotmap_json
        FROM sofascore_match_features
        WHERE error IS NULL AND shotmap_json IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
    ''').fetchall()
    print(f'Partidos: {len(rows)}')

    # Agregar columnas xg_v3 si no existen
    cols = [r[1] for r in cur.execute('PRAGMA table_info(sofascore_match_features)')]
    if 'xg_v3_l' not in cols:
        cur.execute('ALTER TABLE sofascore_match_features ADD COLUMN xg_v3_l REAL')
        cur.execute('ALTER TABLE sofascore_match_features ADD COLUMN xg_v3_v REAL')
        con.commit()

    # Compute xg_v3 per partido
    n_xgot_used = 0
    n_custom_fallback = 0
    eventos = []  # para comparación

    for r in rows:
        sofa_id, liga, fecha, ht, at, hg, ag, xg_c_l, xg_c_v, sm_json = r
        try:
            sm = json.loads(sm_json)
        except:
            continue
        shots = sm.get('shotmap', [])
        if not shots:
            continue

        xg_v3_l = 0
        xg_v3_v = 0
        for s in shots:
            xgot = s.get('xgot')
            if xgot is not None:
                xg_per_shot = xgot
                n_xgot_used += 1
            else:
                xg_per_shot = predict_custom(s)
                if xg_per_shot is None:
                    continue
                n_custom_fallback += 1
            if s.get('isHome'):
                xg_v3_l += xg_per_shot
            else:
                xg_v3_v += xg_per_shot

        # Persist
        cur.execute('UPDATE sofascore_match_features SET xg_v3_l=?, xg_v3_v=? WHERE sofa_event_id=?',
                    (xg_v3_l, xg_v3_v, sofa_id))

        eventos.append({
            'liga': liga, 'fecha': fecha, 'hg': hg, 'ag': ag,
            'xg_v_custom_l': xg_c_l, 'xg_v_custom_v': xg_c_v,
            'xg_v3_l': xg_v3_l, 'xg_v3_v': xg_v3_v,
        })

    con.commit()
    print(f'xgot used: {n_xgot_used}')
    print(f'custom fallback: {n_custom_fallback}')
    print(f'Pct xgot direct: {100*n_xgot_used/(n_xgot_used+n_custom_fallback):.1f}%')

    # ============ Comparación V_custom vs V_v3 ============
    print('\n=== Comparación V_custom vs V_v3 ===')
    print(f'{"Modelo":<10s} {"sum_xG":>10s} {"sum_g":>8s} {"ratio":>7s} {"RMSE":>7s} {"corr":>7s}')
    for ver_name, key_l, key_v in [('V_custom', 'xg_v_custom_l', 'xg_v_custom_v'),
                                    ('V_v3', 'xg_v3_l', 'xg_v3_v')]:
        all_xg = []
        all_g = []
        for d in eventos:
            for side in ('l', 'v'):
                key = key_l if side == 'l' else key_v
                xg = d[key]
                g = d['hg'] if side == 'l' else d['ag']
                if xg is not None:
                    all_xg.append(xg)
                    all_g.append(g)
        all_xg = np.array(all_xg)
        all_g = np.array(all_g)
        sum_xg = all_xg.sum()
        sum_g = all_g.sum()
        ratio = sum_xg / max(sum_g, 1)
        rmse = math.sqrt(np.mean((all_xg - all_g) ** 2))
        corr = np.corrcoef(all_xg, all_g)[0, 1]
        print(f'{ver_name:<10s} {sum_xg:>10.1f} {sum_g:>8d} {ratio:>7.3f} {rmse:>7.4f} {corr:>+7.4f}')

    # Per liga
    print('\n=== Per liga (RMSE) ===')
    print(f'{"Liga":<14s} {"N":>4s} {"V_custom":>10s} {"V_v3":>8s} {"Delta":>8s}')
    by_liga = defaultdict(list)
    for d in eventos:
        by_liga[d['liga']].append(d)
    by_liga_results = {}
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        evs = by_liga[liga]
        if len(evs) < 10:
            continue
        rmses = {}
        for ver in ('custom', 'v3'):
            errs = []
            for d in evs:
                for side in ('l', 'v'):
                    if ver == 'custom':
                        xg = d[f'xg_v_custom_{side}']
                    else:
                        xg = d[f'xg_v3_{side}']
                    g = d['hg'] if side == 'l' else d['ag']
                    if xg is not None:
                        errs.append(xg - g)
            rmses[ver] = math.sqrt(np.mean(np.array(errs) ** 2)) if errs else None
        delta = rmses['v3'] - rmses['custom']
        flag = 'WIN' if delta < -0.05 else ('LOSS' if delta > 0.05 else 'TIE ')
        print(f'{liga:<14s} {len(evs):>4d} {rmses["custom"]:>10.4f} {rmses["v3"]:>8.4f} {delta:>+8.4f} {flag}')
        by_liga_results[liga] = {**rmses, 'delta': delta, 'n': len(evs)}

    # Save
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'n_eventos': len(eventos),
            'n_xgot_used': n_xgot_used,
            'n_custom_fallback': n_custom_fallback,
            'pct_xgot': 100 * n_xgot_used / (n_xgot_used + n_custom_fallback),
            'by_liga': by_liga_results,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')
    con.close()


if __name__ == '__main__':
    main()

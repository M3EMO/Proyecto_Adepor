"""Extrae features espaciales de shotmap_json a tabla wide.

Por cada (liga, fecha, ht, at) computa per-equipo (l, v):
  - n_shots, n_shots_inside_box, n_shots_outside_box
  - n_shots_central, n_shots_wide_left, n_shots_wide_right
  - mean_dist_goal (avg playerCoordinates.x)
  - mean_xg_per_shot
  - max_xg_shot
  - n_high_xg (xg > 0.3)
  - hi_xg_concentration (n_high_xg / n_shots)
  - n_shots_first15, n_shots_last15
  - n_shots_set_piece, n_shots_assisted
  - body_part_diversity (1=solo pies, 2=pies+cabeza)
  - cluster_zone_top (feature dominante)

Persiste en tabla `sofascore_shotmap_features` (un row per partido).
"""
import json
import sqlite3
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'
TABLA = 'sofascore_shotmap_features'

# Convención SOFA inferida de samples (a verificar empíricamente):
#   playerCoordinates.x ∈ [0, 100] = % campo desde arco rival
#     x ≤ 18 -> dentro del área (caja 16.5 yards ~18%)
#     x ∈ (18, 30] -> media luna / borde área
#     x > 30 -> fuera del área lejos
#   playerCoordinates.y ∈ [0, 100] lateral
#     y ∈ (35, 65) -> central
#     y ≤ 35 o y ≥ 65 -> wide
#   periodTimeSeconds: segundos dentro del período
#     period 1ST: ≤ 2700 (45min*60)
#     last 15: > 2700 - 900 = 1800
#   time (minuto): 1..90+

FEATURES_COLS = [
    'n_shots',
    'n_shots_inside_box',
    'n_shots_outside_box',
    'n_shots_central',
    'n_shots_wide',
    'mean_dist_goal',
    'mean_xg_per_shot',
    'max_xg_shot',
    'n_high_xg',
    'hi_xg_ratio',
    'n_shots_first15',
    'n_shots_last15',
    'n_shots_set_piece',
    'n_shots_assisted',
    'body_part_diversity',
    'goal_y_spread',
]


def computar_features(shots, is_home):
    """Computa features para shots de un equipo (filter por isHome)."""
    eq_shots = [s for s in shots if s.get('isHome') == is_home]
    n = len(eq_shots)
    if n == 0:
        return {c: None for c in FEATURES_COLS}

    n_inside = sum(1 for s in eq_shots if s.get('playerCoordinates', {}).get('x', 100) <= 18)
    n_outside = n - n_inside
    n_central = sum(1 for s in eq_shots if 35 < s.get('playerCoordinates', {}).get('y', 50) < 65)
    n_wide = n - n_central
    dists = [s.get('playerCoordinates', {}).get('x', 0) for s in eq_shots if s.get('playerCoordinates', {}).get('x') is not None]
    xgs = [s.get('xg', 0) for s in eq_shots if s.get('xg') is not None]
    n_first15 = sum(1 for s in eq_shots if (s.get('time') or 99) <= 15)
    n_last15 = sum(1 for s in eq_shots if (s.get('time') or 0) >= 76)
    n_set_piece = sum(1 for s in eq_shots if 'set-piece' in (s.get('situation') or '') or s.get('situation') in ('corner', 'free-kick'))
    n_assisted = sum(1 for s in eq_shots if s.get('situation') == 'assisted')
    bps = {s.get('bodyPart') for s in eq_shots if s.get('bodyPart')}
    body_div = 1
    if bps & {'head'}:
        body_div = 2
    if bps & {'other'}:
        body_div = 3
    goal_ys = [s.get('goalMouthCoordinates', {}).get('y', 50) for s in eq_shots]
    goal_y_spread = (max(goal_ys) - min(goal_ys)) if len(goal_ys) >= 2 else 0
    high_xg = [x for x in xgs if x > 0.3]
    return {
        'n_shots': n,
        'n_shots_inside_box': n_inside,
        'n_shots_outside_box': n_outside,
        'n_shots_central': n_central,
        'n_shots_wide': n_wide,
        'mean_dist_goal': sum(dists) / len(dists) if dists else None,
        'mean_xg_per_shot': sum(xgs) / len(xgs) if xgs else None,
        'max_xg_shot': max(xgs) if xgs else None,
        'n_high_xg': len(high_xg),
        'hi_xg_ratio': len(high_xg) / n if n else 0,
        'n_shots_first15': n_first15,
        'n_shots_last15': n_last15,
        'n_shots_set_piece': n_set_piece,
        'n_shots_assisted': n_assisted,
        'body_part_diversity': body_div,
        'goal_y_spread': goal_y_spread,
    }


def construir(conn):
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {TABLA}')
    cols_l = ', '.join(f'{c}_l REAL' for c in FEATURES_COLS)
    cols_v = ', '.join(f'{c}_v REAL' for c in FEATURES_COLS)
    cur.execute(f'''
        CREATE TABLE {TABLA} (
            liga TEXT NOT NULL,
            fecha TEXT NOT NULL,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            sofa_event_id INTEGER,
            {cols_l},
            {cols_v},
            PRIMARY KEY (liga, fecha, ht, at)
        )
    ''')
    cur.execute(f'CREATE INDEX idx_{TABLA}_lf ON {TABLA}(liga, fecha)')

    rows = cur.execute('''
        SELECT liga, fecha, ht, at, sofa_event_id, shotmap_json
        FROM sofascore_match_features
        WHERE shotmap_json IS NOT NULL AND error IS NULL
    ''').fetchall()

    n_ok = 0
    for liga, fecha, ht, at, eid, raw in rows:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        shots = data.get('shotmap', [])
        if not shots:
            continue
        feat_l = computar_features(shots, True)
        feat_v = computar_features(shots, False)
        cols = list(feat_l.keys())
        l_vals = [feat_l[c] for c in cols]
        v_vals = [feat_v[c] for c in cols]
        cols_sql_l = ', '.join(f'{c}_l' for c in cols)
        cols_sql_v = ', '.join(f'{c}_v' for c in cols)
        ph = ', '.join(['?'] * (5 + len(cols) * 2))
        cur.execute(
            f'INSERT OR REPLACE INTO {TABLA} (liga, fecha, ht, at, sofa_event_id, {cols_sql_l}, {cols_sql_v}) VALUES ({ph})',
            (liga, fecha, ht, at, eid, *l_vals, *v_vals)
        )
        n_ok += 1
    conn.commit()
    return n_ok


if __name__ == '__main__':
    conn = sqlite3.connect(DB)
    n = construir(conn)
    print(f'Shotmap features extraídos: {n} partidos')
    cur = conn.cursor()
    n_cols = len(cur.execute(f'PRAGMA table_info({TABLA})').fetchall())
    print(f'Columnas: {n_cols}')
    n_with = cur.execute(f'SELECT COUNT(*) FROM {TABLA} WHERE n_shots_l IS NOT NULL AND n_shots_v IS NOT NULL').fetchone()[0]
    print(f'Con n_shots no-NULL ambos lados: {n_with}')
    conn.close()

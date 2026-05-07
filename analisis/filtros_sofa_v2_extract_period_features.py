"""Extrae features 1ST/2ND de statistics_json a tabla wide.

Resultado: tabla `sofascore_period_features` con un row por partido,
~80 features per period (1ST + 2ND) × {l, v} = ~160 cols numéricas
+ deltas/ratios derivados.

Idempotente. Reproducible.
"""
import json
import sqlite3
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'

TABLA = 'sofascore_period_features'

# items a extraer: name (en JSON) → snake_case col
NAMES_TO_COL = {
    # Match overview
    'Ball possession': 'possession',
    'Expected goals': 'xg',
    'Big chances': 'big_chances',
    'Total shots': 'shots_total',
    'Goalkeeper saves': 'gk_saves',
    'Corner kicks': 'corners',
    'Fouls': 'fouls',
    'Passes': 'passes',
    'Tackles': 'tackles',
    'Free kicks': 'free_kicks',
    'Yellow cards': 'yellow',
    'Red cards': 'red',
    # Shots
    'Shots on target': 'sot',
    'Hit woodwork': 'hit_woodwork',
    'Shots off target': 'shots_off',
    'Blocked shots': 'blocked_shots',
    'Shots inside box': 'shots_inside',
    'Shots outside box': 'shots_outside',
    # Attack
    'Big chances missed': 'big_chances_missed',
    'Through balls': 'through_balls',
    'Fouled in final third': 'fouled_third',
    'Offsides': 'offsides',
    'Touches in penalty area': 'touches_box',
    # Passes
    'Accurate passes': 'accurate_passes',
    'Throw-ins': 'throw_ins',
    'Final third entries': 'third_entries',
    'Long balls': 'long_balls',
    'Crosses': 'crosses',
    # Duels
    'Duels': 'duels',
    'Dispossessed': 'dispossessed',
    'Ground duels': 'ground_duels',
    'Aerial duels': 'aerial_duels',
    'Dribbles': 'dribbles',
    # Defending
    'Tackles won': 'tackles_won',
    'Total tackles': 'tackles_total',
    'Interceptions': 'interceptions',
    'Recoveries': 'recoveries',
    'Clearances': 'clearances',
    'Errors lead to shot': 'errors_lead_shot',
    'Errors lead to goal': 'errors_lead_goal',
    # Goalkeeping
    'Total saves': 'total_saves',
    'Goal kicks': 'goal_kicks',
    'High claim': 'high_claim',
}


def parse_value(v):
    """Convierte '61%' o '4 (5)' o int a float."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.endswith('%'):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    # '4 (5)' → tomar primer número
    m = re.match(r'(-?\d+\.?\d*)', s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def extraer_periodo(stats_json, periodo):
    """Devuelve dict {col: (h_val, a_val)} del periodo dado."""
    out = {}
    try:
        data = json.loads(stats_json) if isinstance(stats_json, str) else stats_json
    except Exception:
        return out
    for p in data.get('statistics', []):
        if p.get('period') != periodo:
            continue
        for g in p.get('groups', []):
            for it in g.get('statisticsItems', []):
                name = it.get('name', '')
                col = NAMES_TO_COL.get(name)
                if col is None:
                    continue
                h = parse_value(it.get('homeValue'))
                a = parse_value(it.get('awayValue'))
                out[col] = (h, a)
    return out


def construir(conn):
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {TABLA}')
    # Construir schema dinámico: dos sufijos de periodo (_1st, _2nd) × 2 lados (_l, _v)
    cols_dinamicas = []
    for col in NAMES_TO_COL.values():
        for periodo_suf in ('1st', '2nd'):
            for lado in ('l', 'v'):
                cols_dinamicas.append(f'{col}_{periodo_suf}_{lado} REAL')
    cols_sql = ',\n  '.join(cols_dinamicas)
    cur.execute(f'''
        CREATE TABLE {TABLA} (
            liga TEXT NOT NULL,
            fecha TEXT NOT NULL,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            sofa_event_id INTEGER,
            {cols_sql},
            PRIMARY KEY (liga, fecha, ht, at)
        )
    ''')
    cur.execute(f'CREATE INDEX idx_{TABLA}_lf ON {TABLA}(liga, fecha)')

    rows = cur.execute('''
        SELECT liga, fecha, ht, at, sofa_event_id, statistics_json
        FROM sofascore_match_features
        WHERE statistics_json IS NOT NULL AND error IS NULL
    ''').fetchall()

    n_ok = 0
    n_skip = 0
    for liga, fecha, ht, at, eid, stats_json in rows:
        feat_1st = extraer_periodo(stats_json, '1ST')
        feat_2nd = extraer_periodo(stats_json, '2ND')
        if not feat_1st or not feat_2nd:
            n_skip += 1
            continue
        valores = {}
        for col in NAMES_TO_COL.values():
            h1, a1 = feat_1st.get(col, (None, None))
            h2, a2 = feat_2nd.get(col, (None, None))
            valores[f'{col}_1st_l'] = h1
            valores[f'{col}_1st_v'] = a1
            valores[f'{col}_2nd_l'] = h2
            valores[f'{col}_2nd_v'] = a2
        cols = list(valores.keys())
        placeholders = ', '.join(['?'] * (5 + len(cols)))
        cur.execute(
            f'INSERT OR REPLACE INTO {TABLA} (liga, fecha, ht, at, sofa_event_id, {", ".join(cols)}) VALUES ({placeholders})',
            (liga, fecha, ht, at, eid, *[valores[c] for c in cols])
        )
        n_ok += 1
    conn.commit()
    return n_ok, n_skip, len(rows)


if __name__ == '__main__':
    conn = sqlite3.connect(DB)
    n_ok, n_skip, n_total = construir(conn)
    print(f'Extracción 1ST/2ND completa: {n_ok}/{n_total} ok, {n_skip} skip (sin períodos)')
    cur = conn.cursor()
    n_cols = len([r for r in cur.execute(f'PRAGMA table_info({TABLA})').fetchall()])
    print(f'Columnas: {n_cols}')
    # Sanity: cuántos partidos tienen xg_1st_l y xg_2nd_l no-NULL
    n_xg = cur.execute(f'SELECT COUNT(*) FROM {TABLA} WHERE xg_1st_l IS NOT NULL AND xg_2nd_l IS NOT NULL').fetchone()[0]
    print(f'Con xg 1ST + 2ND no-NULL: {n_xg}')
    n_pos = cur.execute(f'SELECT COUNT(*) FROM {TABLA} WHERE possession_1st_l IS NOT NULL').fetchone()[0]
    print(f'Con possession 1ST no-NULL: {n_pos}')
    conn.close()

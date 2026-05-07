"""Persist 4 filtros Fase B (period features) en SHADOW table.

Crea tabla `picks_shadow_filtros_sofa_v2_periods` y backfilla todos los
picks que cumplen las 4 condiciones sobre `_fase2_universo_periods`.
aplicado_produccion=0 para todos.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'
TABLA = 'picks_shadow_filtros_sofa_v2_periods'

FILTROS = [
    {
        'id': 'F2P_01_xg_lag1_v_2nd_q2_X',
        'desc': 'xg_lag1_v_2nd_team in (0.36, 0.77] -> empate',
        'feat': 'xg_lag1_v_2nd_team', 'pick': 'X',
        'lo': 0.36, 'hi': 0.77,
        'yield_pool': 0.531, 'n_pool': 59, 'ci95_lo': 0.038, 'ci95_hi': 1.032,
        'loyo_pos': 1, 'loyo_total': 2,
    },
    {
        'id': 'F2P_02_accurate_passes_lag1_l_2nd_q4_O',
        'desc': 'accurate_passes_lag1_l_2nd_team > 186 -> over25',
        'feat': 'accurate_passes_lag1_l_2nd_team', 'pick': 'O',
        'lo': 186.00, 'hi': None,
        'yield_pool': 0.355, 'n_pool': 36, 'ci95_lo': 0.034, 'ci95_hi': 0.652,
        'loyo_pos': 2, 'loyo_total': 2,
    },
    {
        'id': 'F2P_03_fouls_lag1_v_delta_q2_O',
        'desc': 'fouls_lag1_v_delta in (-2, 1] -> over25',
        'feat': 'fouls_lag1_v_delta', 'pick': 'O',
        'lo': -2.00, 'hi': 1.00,
        'yield_pool': 0.309, 'n_pool': 40, 'ci95_lo': 0.019, 'ci95_hi': 0.569,
        'loyo_pos': 2, 'loyo_total': 2,
    },
    {
        'id': 'F2P_04_shots_outside_lag1_v_dom_2nd_q3_O',
        'desc': 'shots_outside_lag1_v_dom_2nd in (0.53, 0.71] -> over25',
        'feat': 'shots_outside_lag1_v_dom_2nd', 'pick': 'O',
        'lo': 0.53, 'hi': 0.71,
        'yield_pool': 0.301, 'n_pool': 37, 'ci95_lo': 0.001, 'ci95_hi': 0.578,
        'loyo_pos': 2, 'loyo_total': 2,
    },
]


def crear_tabla(cur):
    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT NOT NULL,
            id_partido TEXT NOT NULL,
            liga TEXT NOT NULL,
            fecha TEXT NOT NULL,
            local TEXT NOT NULL,
            visita TEXT NOT NULL,
            filtro_id TEXT NOT NULL,
            filtro_descripcion TEXT,
            feat_value REAL,
            pick TEXT,
            cuota REAL,
            hit_real INTEGER,
            yield_real REAL,
            yield_pool_validation REAL,
            n_pool_validation INTEGER,
            ci95_lo REAL, ci95_hi REAL,
            loyo_pos INTEGER, loyo_total INTEGER,
            aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    ''')


def backfill(conn):
    cur = conn.cursor()
    crear_tabla(cur)
    cur.execute(f'DELETE FROM {TABLA}')
    rows = cur.execute('SELECT * FROM _fase2_universo_periods').fetchall()
    cols = [r[1] for r in cur.execute('PRAGMA table_info(_fase2_universo_periods)').fetchall()]
    ts = datetime.now().isoformat()
    n_persisted = 0
    for f in FILTROS:
        for row in rows:
            d = dict(zip(cols, row))
            v = d.get(f['feat'])
            if v is None:
                continue
            if f['lo'] is not None and v <= f['lo']:
                continue
            if f['hi'] is not None and v > f['hi']:
                continue
            outcome = d['outcome_1x2']
            over25 = d['over25']
            cuota = {
                '1': d['cuota_1'], 'X': d['cuota_x'], '2': d['cuota_2'],
                'O': d['cuota_o25'], 'U': d['cuota_u25'],
            }.get(f['pick'])
            if cuota is None or cuota <= 1.0:
                continue
            if f['pick'] in ('1', 'X', '2'):
                hit = 1 if outcome == f['pick'] else 0
            elif f['pick'] == 'O':
                hit = 1 if over25 == 1 else 0
            elif f['pick'] == 'U':
                hit = 1 if over25 == 0 else 0
            yield_real = (cuota - 1.0) if hit else -1.0
            cur.execute(f'''
                INSERT INTO {TABLA} (
                    ts_log, id_partido, liga, fecha, local, visita,
                    filtro_id, filtro_descripcion, feat_value, pick, cuota,
                    hit_real, yield_real,
                    yield_pool_validation, n_pool_validation,
                    ci95_lo, ci95_hi, loyo_pos, loyo_total,
                    aplicado_produccion, razon_no_aplicado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'esperando_n80_y_oos_o_bonferroni_estricto')
            ''', (
                ts, d['id_partido'], d['liga'], d['fecha'], d['local'], d['visita'],
                f['id'], f['desc'], v, f['pick'], cuota,
                hit, yield_real,
                f['yield_pool'], f['n_pool'],
                f['ci95_lo'], f['ci95_hi'], f['loyo_pos'], f['loyo_total'],
            ))
            n_persisted += 1
    conn.commit()
    print(f'SHADOW backfill {TABLA}: {n_persisted} picks loggeados (4 filtros, aplicado_produccion=0)')


if __name__ == '__main__':
    conn = sqlite3.connect(DB)
    backfill(conn)
    conn.close()

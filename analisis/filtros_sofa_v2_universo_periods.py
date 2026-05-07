"""Construye universo Fase 2 con features periodo 1ST/2ND lag-1.

Para cada (liga, fecha, equipo) en `partidos_backtest` con cuotas + outcome:
busca su PARTIDO ANTERIOR en `sofascore_period_features` (lag-1 stricto:
partido más reciente del equipo previo a `fecha` actual). Persiste en
`_fase2_universo_periods` con:
  - cuotas_*, goles_*, outcome_1x2, total_goles, over25
  - lag-1 stats 1ST + 2ND para LOCAL (perspectiva equipo local)
  - lag-1 stats 1ST + 2ND para VISITA
  - deltas/ratios pre-computados 2ND-1ST y dominance

Uso:
  py analisis/filtros_sofa_v2_universo_periods.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analisis.aliases_sofa_espn import norm_team_name

DB = ROOT / 'fondo_quant.db'
TABLA = '_fase2_universo_periods'

# Features clave para lag-1 (priorizadas: alto info content + cobertura)
FEATURES_BASE = [
    'possession', 'xg', 'big_chances', 'shots_total', 'sot',
    'corners', 'fouls', 'tackles', 'recoveries', 'interceptions',
    'big_chances_missed', 'shots_inside', 'shots_outside', 'blocked_shots',
    'accurate_passes', 'third_entries', 'long_balls', 'crosses',
    'duels', 'aerial_duels', 'tackles_won', 'clearances',
    'errors_lead_shot', 'gk_saves',
]


def crear_schema(cur):
    cur.execute(f'DROP TABLE IF EXISTS {TABLA}')
    base_cols = [
        'id_partido TEXT PRIMARY KEY',
        'liga TEXT NOT NULL',
        'fecha TEXT NOT NULL',
        'local TEXT NOT NULL',
        'visita TEXT NOT NULL',
        'cuota_1 REAL', 'cuota_x REAL', 'cuota_2 REAL',
        'cuota_o25 REAL', 'cuota_u25 REAL',
        'goles_l INTEGER', 'goles_v INTEGER',
        'outcome_1x2 TEXT', 'total_goles INTEGER', 'over25 INTEGER',
    ]
    feat_cols = []
    # Lag-1 LOCAL (perspectiva equipo local en su partido anterior)
    for f in FEATURES_BASE:
        # Stats lag-1 LOCAL: en su partido prev, su rol fue local o visita.
        # Persistimos su row directa sin presunción de rol — usaremos ambas
        # vistas (lag1_team_l = stat propio del local en su prev, lag1_team_v
        # = stat propio del visita en su prev).
        feat_cols.append(f'{f}_lag1_l_1st_team REAL')   # local equipo, su mitad 1ST
        feat_cols.append(f'{f}_lag1_l_2nd_team REAL')   # local equipo, su mitad 2ND
        feat_cols.append(f'{f}_lag1_l_delta REAL')      # local equipo, 2ND - 1ST
        feat_cols.append(f'{f}_lag1_l_dom_2nd REAL')    # local equipo, ratio 2nd/(1st+2nd)
        feat_cols.append(f'{f}_lag1_v_1st_team REAL')
        feat_cols.append(f'{f}_lag1_v_2nd_team REAL')
        feat_cols.append(f'{f}_lag1_v_delta REAL')
        feat_cols.append(f'{f}_lag1_v_dom_2nd REAL')
    cols_sql = ',\n  '.join(base_cols + feat_cols)
    cur.execute(f'CREATE TABLE {TABLA} (\n  {cols_sql}\n)')
    cur.execute(f'CREATE INDEX idx_{TABLA}_lf ON {TABLA}(liga, fecha)')
    return feat_cols


def obtener_lag1(cur, liga, equipo_norm, fecha_cutoff):
    """Devuelve dict de features 1ST + 2ND del PARTIDO ANTERIOR del equipo
    (ya sea local o visita en ese partido). None si no hay partido prev.
    """
    # Buscar el partido más reciente donde equipo aparece, anterior a fecha_cutoff
    rows = cur.execute(f'''
        SELECT ht, at,
               {", ".join(f"{f}_1st_l, {f}_1st_v, {f}_2nd_l, {f}_2nd_v" for f in FEATURES_BASE)}
        FROM sofascore_period_features
        WHERE liga=? AND fecha < ?
        ORDER BY fecha DESC LIMIT 50
    ''', (liga, fecha_cutoff)).fetchall()
    for row in rows:
        ht_n = norm_team_name(row[0], liga)
        at_n = norm_team_name(row[1], liga)
        if ht_n == equipo_norm:
            es_local = True
        elif at_n == equipo_norm:
            es_local = False
        else:
            continue
        # Extraer features del equipo (l si fue local en prev, v si fue visita)
        idx = 2  # offset post ht, at
        feats = {}
        for f in FEATURES_BASE:
            v_1st_l, v_1st_v, v_2nd_l, v_2nd_v = row[idx:idx+4]
            idx += 4
            if es_local:
                f1, f2 = v_1st_l, v_2nd_l
            else:
                f1, f2 = v_1st_v, v_2nd_v
            feats[f'{f}_1st_team'] = f1
            feats[f'{f}_2nd_team'] = f2
            if f1 is not None and f2 is not None:
                feats[f'{f}_delta'] = f2 - f1
                tot = f1 + f2
                feats[f'{f}_dom_2nd'] = (f2 / tot) if tot != 0 else None
            else:
                feats[f'{f}_delta'] = None
                feats[f'{f}_dom_2nd'] = None
        return feats
    return None


def construir(conn):
    cur = conn.cursor()
    feat_cols = crear_schema(cur)

    # Universe driver: partidos_backtest 2026 con cuotas + outcome
    pb_rows = cur.execute('''
        SELECT id_partido, fecha, pais, local, visita,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE cuota_1 IS NOT NULL AND goles_l IS NOT NULL
          AND fecha >= '2026-01-01'
        ORDER BY fecha ASC
    ''').fetchall()
    print(f'Driver universe: {len(pb_rows)} partidos backtest 2026 con cuotas+outcome')

    n_ok = 0
    n_no_lag = 0
    per_liga = {}
    for pb in pb_rows:
        id_p, fecha_full, liga, local, visita, c1, cx, c2, co, cu, gl, gv = pb
        fecha = fecha_full[:10]

        local_n = norm_team_name(local, liga)
        visita_n = norm_team_name(visita, liga)

        feats_l = obtener_lag1(cur, liga, local_n, fecha)
        feats_v = obtener_lag1(cur, liga, visita_n, fecha)
        if feats_l is None or feats_v is None:
            n_no_lag += 1
            continue

        outcome = '1' if gl > gv else ('2' if gv > gl else 'X')
        total_g = gl + gv

        # Build INSERT: base + feat cols
        base_vals = [
            id_p, liga, fecha, local, visita,
            c1, cx, c2, co, cu, gl, gv,
            outcome, total_g, 1 if total_g > 2 else 0,
        ]
        feat_vals = []
        for f in FEATURES_BASE:
            feat_vals.append(feats_l.get(f'{f}_1st_team'))
            feat_vals.append(feats_l.get(f'{f}_2nd_team'))
            feat_vals.append(feats_l.get(f'{f}_delta'))
            feat_vals.append(feats_l.get(f'{f}_dom_2nd'))
            feat_vals.append(feats_v.get(f'{f}_1st_team'))
            feat_vals.append(feats_v.get(f'{f}_2nd_team'))
            feat_vals.append(feats_v.get(f'{f}_delta'))
            feat_vals.append(feats_v.get(f'{f}_dom_2nd'))

        all_vals = base_vals + feat_vals
        placeholders = ', '.join(['?'] * len(all_vals))
        cur.execute(f'INSERT OR REPLACE INTO {TABLA} VALUES ({placeholders})', all_vals)
        n_ok += 1
        per_liga[liga] = per_liga.get(liga, 0) + 1

    conn.commit()
    print(f'\nUniverso Fase 2 periods: N={n_ok} (sin lag-1: {n_no_lag})')
    for liga, n in sorted(per_liga.items(), key=lambda x: -x[1]):
        print(f'  {liga:<15s} N={n}')
    return n_ok


if __name__ == '__main__':
    conn = sqlite3.connect(DB)
    construir(conn)
    conn.close()

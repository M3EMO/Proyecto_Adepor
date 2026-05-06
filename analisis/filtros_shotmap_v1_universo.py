"""
Fase 2 — Construir universo_filtros_shotmap_v1.

Cruza historial_equipos_shotmap_ema (snapshot pre-partido) con cuotas reales:
  - partidos_backtest 2026 (cuotas live)
  - cuotas_historicas_fdco (universo histórico)

Para cada partido SOFA con shotmap features pre-partido + cuotas, persistir:
  - liga, fecha, ht, at, sofa_event_id
  - EMA features pre-partido local + visita
  - Diff features (l-v), ratio (l/v)
  - Cuotas + outcome real

Output: universo_filtros_shotmap_v1
"""
import sqlite3
import sys
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analisis.aliases_sofa_espn import norm_team_name

DB = str(ROOT / 'fondo_quant.db')
WARMUP = 3


def crear_schema(con):
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS universo_filtros_shotmap_v1')
    cur.execute('''
        CREATE TABLE universo_filtros_shotmap_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sofa_event_id INTEGER,
            liga TEXT NOT NULL,
            fecha TEXT NOT NULL,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            hg INTEGER, ag INTEGER,
            -- EMA local
            ema_xg_perf_l REAL, ema_bcc_l REAL, ema_pct_danger_l REAL,
            ema_sp_dep_l REAL, ema_late_pct_l REAL, ema_shooter_gini_l REAL, n_acum_l INTEGER,
            -- EMA visita
            ema_xg_perf_v REAL, ema_bcc_v REAL, ema_pct_danger_v REAL,
            ema_sp_dep_v REAL, ema_late_pct_v REAL, ema_shooter_gini_v REAL, n_acum_v INTEGER,
            -- Diffs (l - v)
            diff_xg_perf REAL, diff_bcc REAL, diff_pct_danger REAL,
            diff_sp_dep REAL, diff_late_pct REAL, diff_shooter_gini REAL,
            -- Cuotas
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL, cuota_o25 REAL, cuota_u25 REAL,
            fuente_cuota TEXT,
            -- Outcomes
            res_1x2 TEXT, res_o25 INTEGER
        )
    ''')
    cur.execute('CREATE INDEX idx_uni_shot_liga_fecha ON universo_filtros_shotmap_v1(liga, fecha)')
    cur.execute('CREATE INDEX idx_uni_shot_evt ON universo_filtros_shotmap_v1(sofa_event_id)')
    con.commit()


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    crear_schema(con)

    # 1. Index EMA shotmap snapshots por (liga, equipo_norm, fecha)
    ema_idx = {}
    for r in cur.execute('''
        SELECT liga, equipo_norm, fecha, sofa_event_id, es_local, n_acum,
               ema_xg_perf, ema_bcc, ema_pct_danger,
               ema_sp_dep, ema_late_pct, ema_shooter_gini
        FROM historial_equipos_shotmap_ema
        WHERE n_acum >= ?
    ''', (WARMUP,)):
        liga, eq_n, fecha, sofa_id, es_local, n_acum, xp, bc, pd, sp, lp, gi = r
        key = (sofa_id, es_local)
        ema_idx[key] = {
            'ema_xg_perf': xp, 'ema_bcc': bc, 'ema_pct_danger': pd,
            'ema_sp_dep': sp, 'ema_late_pct': lp, 'ema_shooter_gini': gi,
            'n_acum': n_acum, 'liga': liga, 'fecha': fecha,
        }
    print(f'EMA shotmap snapshots indexados: {len(ema_idx)}')

    # 2. Index cuotas (partidos_backtest 2026 + cuotas_historicas_fdco)
    cuotas_idx = {}  # (liga, fecha_norm, ht_norm, at_norm) -> dict cuotas

    # 2.a partidos_backtest (estado='Calculado' o 'Liquidado' tienen cuotas)
    pb_rows = cur.execute('''
        SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2,
               cuota_o25, cuota_u25, goles_l, goles_v, estado
        FROM partidos_backtest
        WHERE cuota_1 IS NOT NULL
    ''').fetchall()
    for r in pb_rows:
        liga, fecha, local, visita, c1, cx, c2, co25, cu25, gl, gv, est = r
        if not all([liga, fecha, local, visita]):
            continue
        ht_n = norm_team_name(local, liga)
        at_n = norm_team_name(visita, liga)
        cuotas_idx[(liga, fecha, ht_n, at_n)] = {
            'c1': c1, 'cx': cx, 'c2': c2, 'co25': co25, 'cu25': cu25,
            'gl': gl, 'gv': gv, 'fuente': f'pb_{est}',
        }
    print(f'Cuotas partidos_backtest indexadas: {len(cuotas_idx)}')

    # 2.b cuotas_historicas_fdco
    n_pre_fdco = len(cuotas_idx)
    fdco_rows = cur.execute('''
        SELECT liga, fecha, equipo_local, equipo_visita,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               goles_l, goles_v
        FROM cuotas_historicas_fdco
        WHERE cuota_1 IS NOT NULL AND fecha >= '2026-01-01'
    ''').fetchall()
    for r in fdco_rows:
        liga, fecha, ht, at, c1, cx, c2, co25, cu25, gl, gv = r
        ht_n = norm_team_name(ht, liga)
        at_n = norm_team_name(at, liga)
        key = (liga, fecha, ht_n, at_n)
        if key not in cuotas_idx:  # backtest tiene prioridad
            cuotas_idx[key] = {
                'c1': c1, 'cx': cx, 'c2': c2, 'co25': co25, 'cu25': cu25,
                'gl': gl, 'gv': gv, 'fuente': 'fdco',
            }
    print(f'Cuotas fdco agregadas: {len(cuotas_idx) - n_pre_fdco}')

    # 3. Para cada partido SOFA con cuotas, persistir universe row
    sofa_partidos = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag
        FROM sofascore_match_features
        WHERE error IS NULL
    ''').fetchall()
    print(f'Partidos SOFA: {len(sofa_partidos)}')

    n_inserted = 0
    n_no_ema = 0
    n_no_cuotas = 0

    for r in sofa_partidos:
        sofa_id, liga, fecha, ht, at, hg, ag = r
        if hg is None or ag is None:
            continue

        # EMAs pre-partido local + visita
        ema_l = ema_idx.get((sofa_id, 1))
        ema_v = ema_idx.get((sofa_id, 0))
        if not ema_l or not ema_v:
            n_no_ema += 1
            continue

        # Cuotas (con fuzzy fechas ±2)
        ht_n = norm_team_name(ht, liga)
        at_n = norm_team_name(at, liga)
        cuotas = None
        try:
            d0 = datetime.fromisoformat(fecha).date()
            for delta in (0, -1, 1, -2, 2):
                f_alt = (d0 + timedelta(days=delta)).isoformat()
                key = (liga, f_alt, ht_n, at_n)
                if key in cuotas_idx:
                    cuotas = cuotas_idx[key]
                    break
        except (ValueError, TypeError):
            pass
        if not cuotas:
            n_no_cuotas += 1
            continue

        # Diffs y outcomes
        diffs = {}
        for fld in ('xg_perf', 'bcc', 'pct_danger', 'sp_dep', 'late_pct', 'shooter_gini'):
            l_v = ema_l.get(f'ema_{fld}')
            v_v = ema_v.get(f'ema_{fld}')
            if l_v is not None and v_v is not None:
                diffs[fld] = l_v - v_v
            else:
                diffs[fld] = None

        # res 1X2
        res_1x2 = '1' if hg > ag else ('2' if ag > hg else 'X')
        res_o25 = 1 if (hg + ag) > 2 else 0

        cur.execute('''
            INSERT INTO universo_filtros_shotmap_v1
            (sofa_event_id, liga, fecha, ht, at, hg, ag,
             ema_xg_perf_l, ema_bcc_l, ema_pct_danger_l, ema_sp_dep_l, ema_late_pct_l, ema_shooter_gini_l, n_acum_l,
             ema_xg_perf_v, ema_bcc_v, ema_pct_danger_v, ema_sp_dep_v, ema_late_pct_v, ema_shooter_gini_v, n_acum_v,
             diff_xg_perf, diff_bcc, diff_pct_danger, diff_sp_dep, diff_late_pct, diff_shooter_gini,
             cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, fuente_cuota, res_1x2, res_o25)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (sofa_id, liga, fecha, ht, at, hg, ag,
              ema_l['ema_xg_perf'], ema_l['ema_bcc'], ema_l['ema_pct_danger'],
              ema_l['ema_sp_dep'], ema_l['ema_late_pct'], ema_l['ema_shooter_gini'], ema_l['n_acum'],
              ema_v['ema_xg_perf'], ema_v['ema_bcc'], ema_v['ema_pct_danger'],
              ema_v['ema_sp_dep'], ema_v['ema_late_pct'], ema_v['ema_shooter_gini'], ema_v['n_acum'],
              diffs['xg_perf'], diffs['bcc'], diffs['pct_danger'],
              diffs['sp_dep'], diffs['late_pct'], diffs['shooter_gini'],
              cuotas['c1'], cuotas['cx'], cuotas['c2'], cuotas['co25'], cuotas['cu25'],
              cuotas['fuente'], res_1x2, res_o25))
        n_inserted += 1

    con.commit()
    print(f'\nUniverso shotmap_v1: {n_inserted} partidos')
    print(f'  Sin EMA pre-partido (warmup<3): {n_no_ema}')
    print(f'  Sin cuotas matched: {n_no_cuotas}')

    # Cobertura per liga
    print('\nCobertura per liga:')
    for r in cur.execute('SELECT liga, COUNT(*) FROM universo_filtros_shotmap_v1 GROUP BY liga ORDER BY 2 DESC'):
        print(f'  {r[0]:<14s} {r[1]:>4d}')

    # Cobertura por mes
    print('\nCobertura por mes 2026:')
    for r in cur.execute("SELECT SUBSTR(fecha,1,7), COUNT(*) FROM universo_filtros_shotmap_v1 GROUP BY SUBSTR(fecha,1,7) ORDER BY 1"):
        print(f'  {r[0]} {r[1]:>4d}')

    # Distribución cuotas (sanity)
    cnt_o25 = cur.execute('SELECT COUNT(*) FROM universo_filtros_shotmap_v1 WHERE cuota_o25 IS NOT NULL').fetchone()[0]
    print(f'\nCon cuota O/U disponible: {cnt_o25}')

    con.close()


if __name__ == '__main__':
    main()

"""
Fase 6 — SHADOW persistence (incluso con resultados negativos, persistir picks).

Sobre universo_filtros_shotmap_v1 (N=61), persistir picks de los filtros que
pasaron el criterio mínimo "N>=10 con yield_mean computado" para auditoría longitudinal.

Crea picks_shadow_filtros_shotmap_v1 con aplicado_produccion=0 SIEMPRE.

Output:
  - Tabla picks_shadow_filtros_shotmap_v1
  - JSON con resumen
"""
import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')


def yield_pick(cuota, hit):
    return (cuota - 1.0) if hit else -1.0


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar resumen exploration
    with open(ROOT / 'analisis' / 'filtros_shotmap_v1_exploration.json') as f:
        explo = json.load(f)

    # Crear schema (drop+recreate idempotente)
    cur.execute('DROP TABLE IF EXISTS picks_shadow_filtros_shotmap_v1')
    cur.execute('''
        CREATE TABLE picks_shadow_filtros_shotmap_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT NOT NULL,
            sofa_event_id INTEGER,
            liga TEXT,
            fecha TEXT,
            ht TEXT,
            at TEXT,
            fuente_cuota TEXT,
            filtro_id TEXT NOT NULL,
            filtro_descripcion TEXT,
            filtro_feature TEXT,
            filtro_lo REAL,
            filtro_hi REAL,
            pick TEXT,
            cuota REAL,
            hit_real INTEGER,
            yield_real REAL,
            n_acum_filtro INTEGER,
            ci95_lo_pool REAL,
            yield_pool_validation REAL,
            n_pool_validation INTEGER,
            avg_oos_yield REAL,
            n_pos_oos INTEGER,
            n_with_oos INTEGER,
            liga_es_whitelist INTEGER,
            yield_per_liga_estimado REAL,
            n_per_liga_estimado INTEGER,
            bonferroni_alpha REAL,
            validacion_metodo TEXT,
            aplicado_produccion INTEGER NOT NULL DEFAULT 0,
            razon_no_aplicado TEXT
        )
    ''')
    cur.execute('CREATE INDEX idx_psf_shotmap_filtro ON picks_shadow_filtros_shotmap_v1(filtro_id)')
    cur.execute('CREATE INDEX idx_psf_shotmap_liga ON picks_shadow_filtros_shotmap_v1(liga)')
    con.commit()

    # Definiciones filtros (replicar exploration)
    hypotheses = [
        ('F1a_xg_perf_l_high_->_2', '1', 'cuota_2', 'ema_xg_perf_l > 0.5', 'ema_xg_perf_l', 0.5, None,
         lambda r: r['ema_xg_perf_l'] is not None and r['ema_xg_perf_l'] > 0.5),
        ('F1b_xg_perf_l_low_->_1', '1', 'cuota_1', 'ema_xg_perf_l < -0.5', 'ema_xg_perf_l', None, -0.5,
         lambda r: r['ema_xg_perf_l'] is not None and r['ema_xg_perf_l'] < -0.5),
        ('F1c_xg_perf_v_high_->_1', '1', 'cuota_1', 'ema_xg_perf_v > 0.5', 'ema_xg_perf_v', 0.5, None,
         lambda r: r['ema_xg_perf_v'] is not None and r['ema_xg_perf_v'] > 0.5),
        ('F1d_xg_perf_v_low_->_2', '2', 'cuota_2', 'ema_xg_perf_v < -0.5', 'ema_xg_perf_v', None, -0.5,
         lambda r: r['ema_xg_perf_v'] is not None and r['ema_xg_perf_v'] < -0.5),
        ('F2c_bcc_v_low_->_2', '2', 'cuota_2', 'ema_bcc_v < 0.4', 'ema_bcc_v', None, 0.4,
         lambda r: r['ema_bcc_v'] is not None and r['ema_bcc_v'] < 0.4),
        ('F4b_sp_dep_v_high_->_X_ANTI', 'X', 'cuota_x', 'ANTI: sp_dep_v > 0.5 NO apostar X', 'ema_sp_dep_v', 0.5, None,
         lambda r: r['ema_sp_dep_v'] is not None and r['ema_sp_dep_v'] > 0.5),
    ]

    # Cargar universo
    cols = [r[1] for r in cur.execute('PRAGMA table_info(universo_filtros_shotmap_v1)')]
    raw = cur.execute(f'SELECT {",".join(cols)} FROM universo_filtros_shotmap_v1').fetchall()
    rows = [dict(zip(cols, r)) for r in raw]

    bonferroni_alpha = 0.05 / 18
    ts_now = datetime.now().isoformat()
    n_picks_inserted = 0

    # Lookup yield pool de exploration
    yield_pool_map = {h['name']: h for h in explo['hypotheses']}

    for filtro_id, pick, cuota_f, desc, feat, lo, hi, cond in hypotheses:
        # Encontrar resultados pool
        pool_res = yield_pool_map.get(filtro_id, {})
        ci_lo = pool_res.get('ci_lo')
        yield_pool = pool_res.get('yield_mean')
        n_pool = pool_res.get('n')

        for r in rows:
            if not cond(r):
                continue
            cuota = r.get(cuota_f)
            if cuota is None or cuota < 1.01:
                continue
            if pick in ('1', 'X', '2'):
                hit = (r['res_1x2'] == pick)
            elif pick == 'O25':
                hit = (r['res_o25'] == 1)
            elif pick == 'U25':
                hit = (r['res_o25'] == 0)
            else:
                continue
            yld = yield_pick(cuota, hit)

            cur.execute('''
                INSERT INTO picks_shadow_filtros_shotmap_v1
                (ts_log, sofa_event_id, liga, fecha, ht, at, fuente_cuota,
                 filtro_id, filtro_descripcion, filtro_feature, filtro_lo, filtro_hi,
                 pick, cuota, hit_real, yield_real, n_acum_filtro,
                 ci95_lo_pool, yield_pool_validation, n_pool_validation,
                 avg_oos_yield, n_pos_oos, n_with_oos, liga_es_whitelist,
                 yield_per_liga_estimado, n_per_liga_estimado,
                 bonferroni_alpha, validacion_metodo,
                 aplicado_produccion, razon_no_aplicado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ts_now, r['sofa_event_id'], r['liga'], r['fecha'], r['ht'], r['at'], r['fuente_cuota'],
                  filtro_id, desc, feat, lo, hi,
                  pick, cuota, int(hit), yld, n_pool,
                  ci_lo, yield_pool, n_pool,
                  None, 0, 0, 0,
                  None, None,
                  bonferroni_alpha, 'pool_only_no_walkforward',
                  0, 'N=61 universo limitado, walk-forward inter-año imposible (SOFA solo 2026), 0 filtros pasan Bonferroni'))
            n_picks_inserted += 1

    con.commit()
    print(f'Picks logueados SHADOW: {n_picks_inserted}')
    print(f'aplicado_produccion = 0 SIEMPRE')

    # Resumen per filtro
    print('\nResumen per filtro:')
    for r in cur.execute('''
        SELECT filtro_id, COUNT(*), AVG(yield_real)*100, AVG(hit_real)*100
        FROM picks_shadow_filtros_shotmap_v1 GROUP BY filtro_id ORDER BY filtro_id
    '''):
        print(f'  {r[0]:<32s} N={r[1]:>3d} yield={r[2]:>+6.1f}% hit={r[3]:>4.0f}%')

    con.close()


if __name__ == '__main__':
    main()

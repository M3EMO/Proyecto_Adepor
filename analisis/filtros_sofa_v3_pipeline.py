"""Pipeline Fase C: shotmap cluster espacial — lag-1 + validación.

Construye universo Fase 3 con lag-1 features espaciales sobre 393 driver
del backtest 2026 + ML feature importance + binning q4 + Bonferroni +
SHADOW persist.
"""
import json
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analisis.aliases_sofa_espn import norm_team_name

DB = ROOT / 'fondo_quant.db'
OUT = ROOT / 'analisis' / 'filtros_sofa_v3_pipeline.json'
TABLA_UNI = '_fase3_universo_shotmap'
TABLA_SHADOW = 'picks_shadow_filtros_sofa_v3_shotmap'

ALPHA_BONF_BASE = 0.05
N_BOOTSTRAP = 2000
MIN_N_BIN = 30
TOP_K_FEATURES = 20

FEATURES_BASE = [
    'n_shots', 'n_shots_inside_box', 'n_shots_outside_box',
    'n_shots_central', 'n_shots_wide',
    'mean_dist_goal', 'mean_xg_per_shot', 'max_xg_shot',
    'n_high_xg', 'hi_xg_ratio',
    'n_shots_first15', 'n_shots_last15',
    'n_shots_set_piece', 'n_shots_assisted',
    'body_part_diversity', 'goal_y_spread',
]


def construir_universo(conn):
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {TABLA_UNI}')
    base_cols = [
        'id_partido TEXT PRIMARY KEY',
        'liga TEXT NOT NULL', 'fecha TEXT NOT NULL',
        'local TEXT NOT NULL', 'visita TEXT NOT NULL',
        'cuota_1 REAL', 'cuota_x REAL', 'cuota_2 REAL',
        'cuota_o25 REAL', 'cuota_u25 REAL',
        'goles_l INTEGER', 'goles_v INTEGER',
        'outcome_1x2 TEXT', 'over25 INTEGER',
    ]
    feat_cols = []
    for f in FEATURES_BASE:
        # lag-1 LOCAL (su shot stats en su prev match) y lag-1 VISITA
        feat_cols.append(f'{f}_lag1_l REAL')
        feat_cols.append(f'{f}_lag1_v REAL')
    cols_sql = ',\n  '.join(base_cols + feat_cols)
    cur.execute(f'CREATE TABLE {TABLA_UNI} (\n  {cols_sql}\n)')
    cur.execute(f'CREATE INDEX idx_{TABLA_UNI}_lf ON {TABLA_UNI}(liga, fecha)')

    pb_rows = cur.execute('''
        SELECT id_partido, fecha, pais, local, visita,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE cuota_1 IS NOT NULL AND goles_l IS NOT NULL
          AND fecha >= '2026-01-01'
        ORDER BY fecha ASC
    ''').fetchall()

    n_ok = 0
    n_no_lag = 0
    per_liga = {}
    cols_sm_l = ', '.join(f'{f}_l' for f in FEATURES_BASE)
    cols_sm_v = ', '.join(f'{f}_v' for f in FEATURES_BASE)
    for pb in pb_rows:
        id_p, fecha_full, liga, local, visita, c1, cx, c2, co, cu, gl, gv = pb
        fecha = fecha_full[:10]
        local_n = norm_team_name(local, liga)
        visita_n = norm_team_name(visita, liga)

        sm_rows = cur.execute(f'''
            SELECT ht, at, {cols_sm_l}, {cols_sm_v}
            FROM sofascore_shotmap_features
            WHERE liga=? AND fecha < ?
            ORDER BY fecha DESC LIMIT 50
        ''', (liga, fecha)).fetchall()

        feat_l = None
        feat_v = None
        for row in sm_rows:
            ht_n = norm_team_name(row[0], liga)
            at_n = norm_team_name(row[1], liga)
            if feat_l is None:
                if ht_n == local_n:
                    feat_l = {f: row[2 + i] for i, f in enumerate(FEATURES_BASE)}
                elif at_n == local_n:
                    feat_l = {f: row[2 + len(FEATURES_BASE) + i] for i, f in enumerate(FEATURES_BASE)}
            if feat_v is None:
                if ht_n == visita_n:
                    feat_v = {f: row[2 + i] for i, f in enumerate(FEATURES_BASE)}
                elif at_n == visita_n:
                    feat_v = {f: row[2 + len(FEATURES_BASE) + i] for i, f in enumerate(FEATURES_BASE)}
            if feat_l is not None and feat_v is not None:
                break

        if feat_l is None or feat_v is None:
            n_no_lag += 1
            continue

        outcome = '1' if gl > gv else ('2' if gv > gl else 'X')
        total_g = gl + gv
        feat_vals = []
        for f in FEATURES_BASE:
            feat_vals.append(feat_l.get(f))
            feat_vals.append(feat_v.get(f))
        all_vals = [
            id_p, liga, fecha, local, visita,
            c1, cx, c2, co, cu, gl, gv,
            outcome, 1 if total_g > 2 else 0,
        ] + feat_vals
        ph = ', '.join(['?'] * len(all_vals))
        cur.execute(f'INSERT OR REPLACE INTO {TABLA_UNI} VALUES ({ph})', all_vals)
        n_ok += 1
        per_liga[liga] = per_liga.get(liga, 0) + 1

    conn.commit()
    return n_ok, n_no_lag, per_liga


def calcular_yield_pick(row, pick):
    outcome = row['outcome_1x2']
    over25 = row['over25']
    cuota_map = {
        '1': row['cuota_1'], 'X': row['cuota_x'], '2': row['cuota_2'],
        'O': row['cuota_o25'], 'U': row['cuota_u25'],
    }
    c = cuota_map.get(pick)
    if c is None or c <= 1.0:
        return None
    if pick in ('1', 'X', '2'):
        hit = (outcome == pick)
    elif pick == 'O':
        hit = (over25 == 1)
    elif pick == 'U':
        hit = (over25 == 0)
    else:
        return None
    return (c - 1.0) if hit else -1.0


def bootstrap_ci(values, n_resamples=N_BOOTSTRAP):
    if not values:
        return (None, None)
    arr = np.array(values, dtype=float)
    n = len(arr)
    rng = np.random.default_rng(42)
    means = []
    for _ in range(n_resamples):
        means.append(arr[rng.integers(0, n, size=n)].mean())
    means.sort()
    return means[int(n_resamples * 0.025)], means[int(n_resamples * 0.975)]


def feature_importance(data, feat_cols, target_pick):
    X_list, y_list = [], []
    for r in data:
        y = calcular_yield_pick(r, target_pick)
        if y is None:
            continue
        X_list.append([r.get(c) for c in feat_cols])
        y_list.append(y)
    if len(X_list) < 50:
        return []
    X = np.array(X_list, dtype=object)
    y = np.array(y_list, dtype=float)
    X_num = np.full(X.shape, np.nan, dtype=float)
    for j in range(X.shape[1]):
        col = np.array([v if v is not None else np.nan for v in X[:, j]], dtype=float)
        med = np.nanmedian(col)
        if np.isnan(med):
            med = 0.0
        col[np.isnan(col)] = med
        X_num[:, j] = col
    X = X_num
    mu = X.mean(axis=0)
    sd = X.std(axis=0) + 1e-8
    Xs = (X - mu) / sd
    XtX = Xs.T @ Xs + 1.0 * np.eye(Xs.shape[1])
    Xty = Xs.T @ y
    try:
        w = np.linalg.solve(XtX, Xty)
    except np.linalg.LinAlgError:
        return []
    base_pred = Xs @ w
    base_mse = ((y - base_pred) ** 2).mean()
    rng = np.random.default_rng(42)
    importances = []
    for i, fc in enumerate(feat_cols):
        Xp = Xs.copy()
        rng.shuffle(Xp[:, i])
        pred = Xp @ w
        mse = ((y - pred) ** 2).mean()
        importances.append((fc, mse - base_mse))
    importances.sort(key=lambda x: -x[1])
    return importances


def test_bins(data, feat, target):
    valid = [(r.get(feat), calcular_yield_pick(r, target), r.get('fecha'), r['id_partido'])
             for r in data
             if r.get(feat) is not None and calcular_yield_pick(r, target) is not None]
    if len(valid) < 80:
        return []
    vals = np.array([x[0] for x in valid])
    qs = np.quantile(vals, [0.25, 0.50, 0.75])
    bins = [
        (None, qs[0], f'q1<={qs[0]:.2f}'),
        (qs[0], qs[1], f'q2({qs[0]:.2f},{qs[1]:.2f}]'),
        (qs[1], qs[2], f'q3({qs[1]:.2f},{qs[2]:.2f}]'),
        (qs[2], None, f'q4>{qs[2]:.2f}'),
    ]
    out = []
    for lo, hi, label in bins:
        bucket = []
        fechas = []
        ids = []
        for v, y, f, id_p in valid:
            if (lo is None or v > lo) and (hi is None or v <= hi):
                bucket.append(y)
                fechas.append(f)
                ids.append(id_p)
        if len(bucket) < MIN_N_BIN:
            continue
        ymean = np.mean(bucket)
        ci_lo, ci_hi = bootstrap_ci(bucket)
        bucket_yields_by_month = defaultdict(list)
        for y, f in zip(bucket, fechas):
            m = int(f[5:7])
            b = 'ene-feb' if m <= 2 else ('mar' if m == 3 else 'abr-may')
            bucket_yields_by_month[b].append(y)
        loyo_pos = sum(1 for ys in bucket_yields_by_month.values() if np.mean(ys) > 0)
        loyo_total = len(bucket_yields_by_month)
        out.append({
            'feat': feat, 'pick': target, 'bin': label,
            'lo': lo, 'hi': hi,
            'n': len(bucket), 'yield': ymean,
            'ci95_lo': ci_lo, 'ci95_hi': ci_hi,
            'loyo_pos': loyo_pos, 'loyo_total': loyo_total,
            'ids': ids,
        })
    return out


def shadow_persist(conn, candidatos, data):
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {TABLA_SHADOW}')
    cur.execute(f'''
        CREATE TABLE {TABLA_SHADOW} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT, id_partido TEXT, liga TEXT, fecha TEXT,
            local TEXT, visita TEXT,
            filtro_id TEXT, filtro_descripcion TEXT,
            feat_value REAL, pick TEXT, cuota REAL,
            hit_real INTEGER, yield_real REAL,
            yield_pool_validation REAL, n_pool_validation INTEGER,
            ci95_lo REAL, ci95_hi REAL,
            loyo_pos INTEGER, loyo_total INTEGER,
            aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    ''')
    ts = datetime.now().isoformat()
    rows_by_id = {r['id_partido']: r for r in data}
    n = 0
    for i, c in enumerate(candidatos):
        fid = f'F3SM_{i+1:02d}_{c["feat"]}_{c["bin"]}_{c["pick"]}'
        for id_p in c['ids']:
            r = rows_by_id.get(id_p)
            if r is None:
                continue
            v = r.get(c['feat'])
            yr = calcular_yield_pick(r, c['pick'])
            if yr is None:
                continue
            cuota_map = {
                '1': r['cuota_1'], 'X': r['cuota_x'], '2': r['cuota_2'],
                'O': r['cuota_o25'], 'U': r['cuota_u25'],
            }
            cu = cuota_map[c['pick']]
            hit = 1 if yr > 0 else 0
            cur.execute(f'''INSERT INTO {TABLA_SHADOW} (
                ts_log, id_partido, liga, fecha, local, visita,
                filtro_id, filtro_descripcion, feat_value, pick, cuota,
                hit_real, yield_real,
                yield_pool_validation, n_pool_validation, ci95_lo, ci95_hi,
                loyo_pos, loyo_total, aplicado_produccion, razon_no_aplicado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'esperando_n80_y_oos_o_bonferroni')''',
                (ts, id_p, r['liga'], r['fecha'], r['local'], r['visita'],
                 fid, c['bin'], v, c['pick'], cu, hit, yr,
                 c['yield'], c['n'], c['ci95_lo'], c['ci95_hi'],
                 c['loyo_pos'], c['loyo_total']))
            n += 1
    conn.commit()
    return n


def main():
    conn = sqlite3.connect(DB)
    print('=== Construyendo universo Fase 3 (shotmap lag-1) ===')
    n_ok, n_no_lag, per_liga = construir_universo(conn)
    print(f'N={n_ok} (sin lag-1: {n_no_lag})')
    for liga, n in sorted(per_liga.items(), key=lambda x: -x[1]):
        print(f'  {liga:<15s} N={n}')

    cur = conn.cursor()
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info({TABLA_UNI})').fetchall()]
    rows = cur.execute(f'SELECT {", ".join(cols)} FROM {TABLA_UNI}').fetchall()
    data = [dict(zip(cols, r)) for r in rows]
    feat_cols = [c for c in cols if c.startswith(tuple(f + '_lag1' for f in FEATURES_BASE))]
    print(f'\nUniverse: {len(data)} partidos, {len(feat_cols)} features lag-1')

    print('\n=== ML feature importance ===')
    targets = ['1', 'X', '2', 'O', 'U']
    importance = {}
    for tgt in targets:
        imp = feature_importance(data, feat_cols, tgt)
        importance[tgt] = imp
        if imp:
            print(f'\nTop 5 pick={tgt}:')
            for f, s in imp[:5]:
                print(f'  {f:<40s} {s:.6f}')

    print('\n=== Test binning q4 ===')
    all_filters = []
    n_tests = 0
    for tgt in targets:
        for feat, _ in importance.get(tgt, [])[:TOP_K_FEATURES]:
            results = test_bins(data, feat, tgt)
            all_filters.extend(results)
            n_tests += len(results)

    alpha_bonf = ALPHA_BONF_BASE / max(n_tests, 1)
    print(f'\nN tests: {n_tests}, Bonferroni alpha: {alpha_bonf:.6f}')

    promovibles = [f for f in all_filters
                   if f['yield'] > 0.05 and f['ci95_lo'] is not None
                   and f['ci95_lo'] > 0 and f['n'] >= MIN_N_BIN]
    promovibles.sort(key=lambda x: -x['yield'])

    print(f'\n=== TOP filtros (yield>+5%, CI95 lo>0, N>=30) ===')
    print(f'Encontrados: {len(promovibles)}')
    for f in promovibles[:15]:
        print(f"  pick={f['pick']:<2s} feat={f['feat']:<35s} bin={f['bin']:<25s} N={f['n']:<4d} yield={f['yield']*100:>6.1f}% CI95=[{f['ci95_lo']*100:.1f},{f['ci95_hi']*100:.1f}] LOYO={f['loyo_pos']}/{f['loyo_total']}")

    n_persisted = shadow_persist(conn, promovibles, data)
    print(f'\nSHADOW persisted: {n_persisted} picks en {TABLA_SHADOW}')

    out = {
        'universo_n': len(data),
        'n_features': len(feat_cols),
        'n_tests': n_tests,
        'alpha_bonferroni': alpha_bonf,
        'top_features_by_target': {
            tgt: [{'feat': f, 'importance': float(s)} for f, s in imp[:10]]
            for tgt, imp in importance.items()
        },
        'promovibles': [{k: v for k, v in f.items() if k != 'ids'} for f in promovibles],
        'shadow_persisted': n_persisted,
    }
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'\nPersisted: {OUT}')
    conn.close()


if __name__ == '__main__':
    main()

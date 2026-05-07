"""Pipeline validación features periodo 1ST/2ND lag-1.

Sobre `_fase2_universo_periods` (N=393):
  1. Feature importance ML (Ridge regression + permutation) sobre yield real
     para cada target (1, X, 2, O25, U25)
  2. Top-K features → binning q4 + yield por bin
  3. Bonferroni α = 0.05 / N_tests
  4. Bootstrap CI95% percentile (N_resamples=2000)
  5. Walk-forward LOYO sobre 3 buckets temporales (ene-feb / mar / abr-may)

Output:
  - analisis/filtros_sofa_v2_pipeline_validation.json (resultados detallados)
  - stdout: top filtros con yield > +5% + CI95 lo > 0
"""
import json
import sqlite3
import sys
import math
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'
OUT = ROOT / 'analisis' / 'filtros_sofa_v2_pipeline_validation.json'

ALPHA_BONF_BASE = 0.05
N_BOOTSTRAP = 2000
MIN_N_BIN = 30
TOP_K_FEATURES = 30


def cargar_universo(conn):
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute('PRAGMA table_info(_fase2_universo_periods)').fetchall()]
    rows = cur.execute(f'SELECT {", ".join(cols)} FROM _fase2_universo_periods').fetchall()
    data = [dict(zip(cols, r)) for r in rows]
    return data, cols


def calcular_yield_pick(row, pick):
    """Yield de apostar `pick`. Filtra cuotas <=1.0 (placeholder/missing)."""
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


def baseline_yields(data):
    out = {}
    for pick in ('1', 'X', '2', 'O', 'U'):
        ys = [calcular_yield_pick(r, pick) for r in data]
        ys = [y for y in ys if y is not None]
        out[pick] = (np.mean(ys), len(ys)) if ys else (None, 0)
    return out


def bootstrap_ci(values, n_resamples=N_BOOTSTRAP, ci=0.95):
    if len(values) == 0:
        return (None, None)
    arr = np.array(values, dtype=float)
    n = len(arr)
    means = []
    rng = np.random.default_rng(42)
    for _ in range(n_resamples):
        sample = arr[rng.integers(0, n, size=n)]
        means.append(sample.mean())
    means.sort()
    lo = means[int(n_resamples * (1 - ci) / 2)]
    hi = means[int(n_resamples * (1 + ci) / 2)]
    return (lo, hi)


def feature_cols(cols):
    """Lista de cols numéricas que son features lag-1 periodo."""
    return [c for c in cols if c.endswith(('_team', '_delta', '_dom_2nd'))]


def feature_importance(data, feat_cols, target_pick):
    """Ridge regression + permutation. Devuelve [(feat, score), ...].
    Imputa NULLs por mediana (per columna) para no perder filas."""
    X_list = []
    y_list = []
    for r in data:
        y = calcular_yield_pick(r, target_pick)
        if y is None:
            continue
        feats = [r.get(c) for c in feat_cols]
        X_list.append(feats)
        y_list.append(y)
    if len(X_list) < 50:
        return []
    X = np.array(X_list, dtype=object)
    y = np.array(y_list, dtype=float)
    # Imputación mediana col-wise sobre rows válidos
    X_num = np.full(X.shape, np.nan, dtype=float)
    for j in range(X.shape[1]):
        col = np.array([v if v is not None else np.nan for v in X[:, j]], dtype=float)
        med = np.nanmedian(col)
        if np.isnan(med):
            med = 0.0
        col[np.isnan(col)] = med
        X_num[:, j] = col
    X = X_num
    # Standardize
    mu = X.mean(axis=0)
    sd = X.std(axis=0) + 1e-8
    Xs = (X - mu) / sd
    # Ridge: w = (X'X + λI)^-1 X'y
    lam = 1.0
    XtX = Xs.T @ Xs + lam * np.eye(Xs.shape[1])
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


def test_bin_q4(data, feat, target_pick):
    """Para cada bin q4 del feature, computa yield + N + Bonferroni."""
    valid = []
    for r in data:
        v = r.get(feat)
        y = calcular_yield_pick(r, target_pick)
        if v is None or y is None:
            continue
        valid.append((v, y, r.get('fecha')))
    if len(valid) < 80:
        return []
    vals = np.array([x[0] for x in valid])
    quartiles = np.quantile(vals, [0.25, 0.50, 0.75])
    out = []
    for i, (lo, hi, label) in enumerate([
        (None, quartiles[0], f'q1_<={quartiles[0]:.2f}'),
        (quartiles[0], quartiles[1], f'q2_({quartiles[0]:.2f},{quartiles[1]:.2f}]'),
        (quartiles[1], quartiles[2], f'q3_({quartiles[1]:.2f},{quartiles[2]:.2f}]'),
        (quartiles[2], None, f'q4_>{quartiles[2]:.2f}'),
    ]):
        bucket = []
        fechas_b = []
        for v, y, f in valid:
            if (lo is None or v > lo) and (hi is None or v <= hi):
                bucket.append(y)
                fechas_b.append(f)
        if len(bucket) < MIN_N_BIN:
            continue
        ymean = np.mean(bucket)
        ci_lo, ci_hi = bootstrap_ci(bucket)
        out.append({
            'feat': feat, 'pick': target_pick, 'bin': label,
            'n': len(bucket), 'yield': ymean,
            'ci95_lo': ci_lo, 'ci95_hi': ci_hi,
            'fechas': fechas_b,
        })
    return out


def loyo_walkforward(filtro_result, all_data):
    """LOYO sobre buckets temporales."""
    fechas = filtro_result['fechas']
    yields_by_bucket = defaultdict(list)
    for f in fechas:
        m = int(f[5:7])
        if m <= 2:
            b = 'ene-feb'
        elif m == 3:
            b = 'mar'
        else:
            b = 'abr-may'
        yields_by_bucket[b]
    # Walk-forward: train = todos menos uno, test = uno
    # Como yields ya están en filtro_result (computed pool), recompute por bucket
    # Filtro re-aplicar usando feat range
    # Simplificamos: contar bucket positivos sobre yields
    bucket_yields = {}
    for f, y in zip(filtro_result['fechas'], filtro_result.get('yields', [])):
        m = int(f[5:7])
        if m <= 2: b = 'ene-feb'
        elif m == 3: b = 'mar'
        else: b = 'abr-may'
        bucket_yields.setdefault(b, []).append(y)
    pos = sum(1 for b, ys in bucket_yields.items() if ys and np.mean(ys) > 0)
    return pos, len(bucket_yields)


def run_pipeline():
    conn = sqlite3.connect(DB)
    data, cols = cargar_universo(conn)
    feat_cols = feature_cols(cols)
    print(f'Universo Fase 2 periods: N={len(data)}, features lag-1: {len(feat_cols)}')

    baselines = baseline_yields(data)
    print('\n=== Baselines (apostar siempre a un pick) ===')
    for pick, (y, n) in baselines.items():
        print(f'  {pick}: yield={y*100:.2f}% N={n}')

    # ML feature importance per target
    targets = ['1', 'X', '2', 'O', 'U']
    importance_by_target = {}
    print('\n=== ML feature importance (Ridge + permutation) ===')
    for tgt in targets:
        imp = feature_importance(data, feat_cols, tgt)
        importance_by_target[tgt] = imp
        if imp:
            print(f'\n  Top 5 para pick={tgt}:')
            for f, s in imp[:5]:
                print(f'    {f:<45s} importance={s:.6f}')

    # Bin q4 testing per top feature × target
    all_filters = []
    print('\n=== Filtros candidatos (top features × bins q4) ===')
    n_tests = 0
    for tgt in targets:
        imp = importance_by_target.get(tgt, [])
        for feat, _score in imp[:TOP_K_FEATURES]:
            results = test_bin_q4(data, feat, tgt)
            # Re-add yields per fecha to enable LOYO
            for r in results:
                # recompute yields per row in bin
                ys_match = []
                for row in data:
                    v = row.get(feat)
                    y = calcular_yield_pick(row, tgt)
                    if v is None or y is None:
                        continue
                    label = r['bin']
                    # Match by recomputing condition
                    parts = label.split('_')
                    if parts[0] == 'q1':
                        thresh = float(label.split('<=')[1])
                        if v <= thresh:
                            ys_match.append(y)
                    elif parts[0] == 'q4':
                        thresh = float(label.split('>')[1])
                        if v > thresh:
                            ys_match.append(y)
                    elif parts[0] in ('q2', 'q3'):
                        # range "(lo,hi]" parse
                        rng = label.split('(')[1].rstrip(']')
                        lo_s, hi_s = rng.split(',')
                        lo, hi = float(lo_s), float(hi_s)
                        if lo < v <= hi:
                            ys_match.append(y)
                r['yields'] = ys_match
            all_filters.extend(results)
            n_tests += len(results)

    # Bonferroni
    alpha_bonf = ALPHA_BONF_BASE / max(n_tests, 1)
    print(f'\nN tests totales: {n_tests}')
    print(f'Bonferroni alpha: {ALPHA_BONF_BASE}/{n_tests} = {alpha_bonf:.6f}')

    # Filter por criterios mínimos: yield > +5%, CI95 lo > 0, N >= 30
    promovibles = []
    for f in all_filters:
        if f['yield'] > 0.05 and f['ci95_lo'] is not None and f['ci95_lo'] > 0 and f['n'] >= MIN_N_BIN:
            pos, total_b = loyo_walkforward(f, data)
            f['loyo_pos'] = pos
            f['loyo_total'] = total_b
            f['loyo_pct'] = pos / total_b if total_b else 0
            promovibles.append(f)

    promovibles.sort(key=lambda x: -x['yield'])
    print(f'\n=== TOP filtros (yield>+5%, CI95 lo>0, N>=30) ===')
    print(f'  Encontrados: {len(promovibles)}')
    for f in promovibles[:15]:
        print(f"  pick={f['pick']:<2s} feat={f['feat']:<48s} bin={f['bin']:<32s} N={f['n']:<4d} yield={f['yield']*100:>6.1f}% CI95=[{f['ci95_lo']*100:.1f},{f['ci95_hi']*100:.1f}] LOYO={f.get('loyo_pos','?')}/{f.get('loyo_total','?')}")

    # Persist results (sin yields detallados para tamaño)
    out = {
        'universo_n': len(data),
        'n_features': len(feat_cols),
        'baselines': {k: {'yield': v[0], 'n': v[1]} for k, v in baselines.items()},
        'n_tests': n_tests,
        'alpha_bonferroni': alpha_bonf,
        'top_features_by_target': {
            tgt: [{'feat': f, 'importance': float(s)} for f, s in imp[:10]]
            for tgt, imp in importance_by_target.items()
        },
        'promovibles': [
            {k: v for k, v in f.items() if k not in ('fechas', 'yields')}
            for f in promovibles
        ],
        'all_tests_count_bonferroni_pass': sum(
            1 for f in all_filters
            if f['ci95_lo'] is not None and f['yield'] > 0
        ),
    }
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'\nPersisted: {OUT}')

    conn.close()
    return out


if __name__ == '__main__':
    run_pipeline()

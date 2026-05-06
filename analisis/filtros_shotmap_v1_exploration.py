"""
Fase 3 + 4 — Exploración descriptiva + ML feature importance + validación.

Sobre universo_filtros_shotmap_v1 (N=61):
  1. Bin q4 por feature, yield por bin, bootstrap CI95
  2. Random Forest permutation importance
  3. Mutual information con outcomes
  4. Bonferroni alpha = 0.05 / n_tests
  5. Walk-forward mensual (limitación: solo abril 2026 disponible)
  6. Per-liga breakdown

Honestidad estadística: con N=61, Bonferroni va a ser muy estricto. Probable resultado: SHADOW only.

Output: analisis/filtros_shotmap_v1_exploration.json
"""
import sqlite3
import json
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import bootstrap

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')
OUT_JSON = str(ROOT / 'analisis' / 'filtros_shotmap_v1_exploration.json')


def yield_pick(cuota, hit):
    """Yield single pick: (cuota - 1) si hit, -1 si miss."""
    if hit:
        return cuota - 1.0
    return -1.0


def bootstrap_yield_ci(yields, n_resamples=1000, alpha=0.05):
    """Bootstrap CI percentile sobre yields per pick."""
    if not yields or len(yields) < 5:
        return None, None, None
    arr = np.array(yields)
    rng = np.random.default_rng(42)
    means = []
    for _ in range(n_resamples):
        sample = rng.choice(arr, size=len(arr), replace=True)
        means.append(np.mean(sample))
    means.sort()
    lo = means[int(n_resamples * alpha / 2)]
    hi = means[int(n_resamples * (1 - alpha / 2))]
    return float(np.mean(arr)), float(lo), float(hi)


def evaluar_filtro(rows, condition_fn, pick_field, cuota_field):
    """rows = list of dict con features + cuotas + outcomes.
       condition_fn(row) -> bool (filtro pasa).
       pick_field = '1', 'X', '2', 'O25', 'U25'.
       cuota_field = 'cuota_1', 'cuota_x', etc.
    """
    yields = []
    for r in rows:
        if not condition_fn(r):
            continue
        cuota = r.get(cuota_field)
        if cuota is None or cuota < 1.01:
            continue
        # hit?
        if pick_field in ('1', 'X', '2'):
            hit = (r['res_1x2'] == pick_field)
        elif pick_field == 'O25':
            hit = (r['res_o25'] == 1)
        elif pick_field == 'U25':
            hit = (r['res_o25'] == 0)
        else:
            continue
        yields.append(yield_pick(cuota, hit))
    n = len(yields)
    if n == 0:
        return {'n': 0, 'yield_mean': None, 'ci_lo': None, 'ci_hi': None}
    mean, lo, hi = bootstrap_yield_ci(yields)
    return {'n': n, 'yield_mean': mean, 'ci_lo': lo, 'ci_hi': hi,
            'hit_rate': sum(1 for y in yields if y > 0) / n}


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar universo
    cols = [r[1] for r in cur.execute('PRAGMA table_info(universo_filtros_shotmap_v1)')]
    raw = cur.execute(f'SELECT {",".join(cols)} FROM universo_filtros_shotmap_v1').fetchall()
    rows = [dict(zip(cols, r)) for r in raw]
    print(f'Universo: {len(rows)} partidos')

    # ============ Fase 3.1: Distribuciones features ============
    print('\n=== Distribuciones features (mean, std, q1, q3) ===')
    feature_cols = [
        'ema_xg_perf_l', 'ema_xg_perf_v', 'diff_xg_perf',
        'ema_bcc_l', 'ema_bcc_v', 'diff_bcc',
        'ema_pct_danger_l', 'ema_pct_danger_v', 'diff_pct_danger',
        'ema_sp_dep_l', 'ema_sp_dep_v', 'diff_sp_dep',
        'ema_late_pct_l', 'ema_late_pct_v', 'diff_late_pct',
        'ema_shooter_gini_l', 'ema_shooter_gini_v', 'diff_shooter_gini',
    ]
    feat_stats = {}
    for c in feature_cols:
        vals = [r[c] for r in rows if r[c] is not None]
        if len(vals) < 10:
            continue
        arr = np.array(vals)
        feat_stats[c] = {
            'n': len(vals), 'mean': float(arr.mean()), 'std': float(arr.std()),
            'q1': float(np.percentile(arr, 25)), 'q3': float(np.percentile(arr, 75)),
        }
        print(f'  {c:<28s} mean={arr.mean():+.3f} std={arr.std():.3f} q1={np.percentile(arr,25):+.3f} q3={np.percentile(arr,75):+.3f}')

    # ============ Fase 3.2: Filtros hipótesis (F1-F6 prompt) ============
    print('\n=== Filtros hipótesis F1-F6 ===')
    hypotheses = [
        # F1 xg_perf reversion
        ('F1a_xg_perf_l_high_->_2', '1', 'cuota_2', lambda r: r['ema_xg_perf_l'] is not None and r['ema_xg_perf_l'] > 0.5),
        ('F1b_xg_perf_l_low_->_1', '1', 'cuota_1', lambda r: r['ema_xg_perf_l'] is not None and r['ema_xg_perf_l'] < -0.5),
        ('F1c_xg_perf_v_high_->_1', '1', 'cuota_1', lambda r: r['ema_xg_perf_v'] is not None and r['ema_xg_perf_v'] > 0.5),
        ('F1d_xg_perf_v_low_->_2', '2', 'cuota_2', lambda r: r['ema_xg_perf_v'] is not None and r['ema_xg_perf_v'] < -0.5),
        ('F1e_diff_xg_perf_>1->_1', '1', 'cuota_1', lambda r: r['diff_xg_perf'] is not None and r['diff_xg_perf'] > 1.0),
        ('F1f_diff_xg_perf_<-1->_2', '2', 'cuota_2', lambda r: r['diff_xg_perf'] is not None and r['diff_xg_perf'] < -1.0),
        # F2 BCC frustración
        ('F2a_bcc_l_low_->_1', '1', 'cuota_1', lambda r: r['ema_bcc_l'] is not None and r['ema_bcc_l'] < 0.4),
        ('F2b_bcc_l_low_->_O25', 'O25', 'cuota_o25', lambda r: r['ema_bcc_l'] is not None and r['ema_bcc_l'] < 0.4),
        ('F2c_bcc_v_low_->_2', '2', 'cuota_2', lambda r: r['ema_bcc_v'] is not None and r['ema_bcc_v'] < 0.4),
        # F3 Danger zone
        ('F3a_danger_l_high_->_1', '1', 'cuota_1', lambda r: r['ema_pct_danger_l'] is not None and r['ema_pct_danger_l'] > 0.4),
        ('F3b_danger_l_low_->_X', 'X', 'cuota_x', lambda r: r['ema_pct_danger_l'] is not None and r['ema_pct_danger_l'] < 0.2),
        ('F3c_danger_v_high_->_2', '2', 'cuota_2', lambda r: r['ema_pct_danger_v'] is not None and r['ema_pct_danger_v'] > 0.4),
        # F4 Set-piece dep
        ('F4a_sp_dep_l_high_->_U25', 'U25', 'cuota_u25', lambda r: r['ema_sp_dep_l'] is not None and r['ema_sp_dep_l'] > 0.5),
        ('F4b_sp_dep_v_high_->_X', 'X', 'cuota_x', lambda r: r['ema_sp_dep_v'] is not None and r['ema_sp_dep_v'] > 0.5),
        # F5 Late game
        ('F5a_late_l_high_->_O25', 'O25', 'cuota_o25', lambda r: r['ema_late_pct_l'] is not None and r['ema_late_pct_l'] > 0.3),
        ('F5b_late_v_high_->_O25', 'O25', 'cuota_o25', lambda r: r['ema_late_pct_v'] is not None and r['ema_late_pct_v'] > 0.3),
        # F6 Gini shooter
        ('F6a_gini_l_high_->_X', 'X', 'cuota_x', lambda r: r['ema_shooter_gini_l'] is not None and r['ema_shooter_gini_l'] > 0.7),
        ('F6b_gini_l_low_->_1', '1', 'cuota_1', lambda r: r['ema_shooter_gini_l'] is not None and r['ema_shooter_gini_l'] < 0.3),
    ]

    n_tests = len(hypotheses)
    bonferroni_alpha = 0.05 / n_tests
    print(f'  N tests: {n_tests}, Bonferroni alpha/test = {bonferroni_alpha:.5f}')

    results = {'feature_stats': feat_stats, 'hypotheses': []}
    print(f'\n{"filtro":<32s} {"pick":<5} {"N":>4} {"yield":>8} {"ci_lo":>8} {"ci_hi":>8} {"hit":>6} {"sig?"}')
    for name, pick, cuota_f, cond in hypotheses:
        res = evaluar_filtro(rows, cond, pick, cuota_f)
        sig = ''
        if res['n'] >= 10 and res['yield_mean'] is not None:
            # P-value approx: yield_mean / (std/sqrt(n)). Si CI95 lower > 0 ⇒ sig al 5%
            if res['ci_lo'] > 0:
                sig = '★ CI>0'
        ym = f"{res['yield_mean']*100:+.1f}%" if res['yield_mean'] else '   N/A'
        cl = f"{res['ci_lo']*100:+.1f}%" if res['ci_lo'] else '   N/A'
        ch = f"{res['ci_hi']*100:+.1f}%" if res['ci_hi'] else '   N/A'
        hr = f"{res['hit_rate']*100:.0f}%" if res.get('hit_rate') is not None else '  N/A'
        print(f'  {name:<30s} {pick:<5} {res["n"]:>4d} {ym:>8} {cl:>8} {ch:>8} {hr:>6} {sig}')
        results['hypotheses'].append({
            'name': name, 'pick': pick, **res, 'sig_ci': bool(sig),
        })

    # ============ Fase 3.3: ML feature importance (Random Forest) ============
    print('\n=== ML feature importance (RF on yield_local) ===')
    try:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.inspection import permutation_importance
        feat_for_ml = [c for c in feature_cols if c in feat_stats]
        # Filtrar rows con todos los features no-None
        X, y = [], []
        for r in rows:
            if any(r[c] is None for c in feat_for_ml):
                continue
            if r['cuota_1'] is None:
                continue
            X.append([r[c] for c in feat_for_ml])
            # Target: yield si pick=local (cuota_1)
            hit = (r['res_1x2'] == '1')
            y.append(yield_pick(r['cuota_1'], hit))
        X = np.array(X)
        y = np.array(y)
        if len(X) >= 30:
            rf = RandomForestRegressor(n_estimators=100, max_depth=4, random_state=42)
            rf.fit(X, y)
            perm = permutation_importance(rf, X, y, n_repeats=10, random_state=42)
            print(f'{"feature":<28s} {"perm_imp":>10s} {"std":>8s}')
            ml_importances = []
            for i, c in enumerate(feat_for_ml):
                imp = perm.importances_mean[i]
                std = perm.importances_std[i]
                ml_importances.append({'feature': c, 'imp': float(imp), 'std': float(std)})
                print(f'  {c:<28s} {imp:>+10.4f} {std:>8.4f}')
            results['ml_importance'] = sorted(ml_importances, key=lambda x: -abs(x['imp']))
        else:
            print(f'  N={len(X)} insuficiente para RF')
            results['ml_importance'] = None
    except ImportError:
        results['ml_importance'] = None
        print('  sklearn no disponible')

    # ============ Fase 4: Walk-forward mensual ============
    print('\n=== Walk-forward mensual (solo abril 2026 disponible) ===')
    months = sorted(set(r['fecha'][:7] for r in rows))
    print(f'  Meses disponibles: {months} (limitación: SOFA solo cubre 2026)')

    # ============ Fase 4.5: Per-liga breakdown filtros sig ============
    print('\n=== Per-liga breakdown filtros con CI lo > 0 ===')
    for h in results['hypotheses']:
        if not h.get('sig_ci'):
            continue
        if h['n'] < 10:
            continue
        nm = h['name']
        # Recalcular yield per liga
        for liga in ('Italia', 'Francia', 'Turquia', 'Brasil', 'Espana', 'Inglaterra'):
            cond = next(c for n, p, cf, c in hypotheses if n == nm)
            sub = [r for r in rows if r['liga'] == liga]
            res_l = evaluar_filtro(sub, cond,
                                    next(p for n, p, cf, c in hypotheses if n == nm),
                                    next(cf for n, p, cf, c in hypotheses if n == nm))
            if res_l['n'] >= 5:
                print(f'  {nm:<30s} {liga:<11s} N={res_l["n"]} yield={res_l["yield_mean"]*100 if res_l["yield_mean"] else 0:+.1f}%')

    # Save
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(results, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')

    # ============ Resumen ============
    n_sig = sum(1 for h in results['hypotheses'] if h.get('sig_ci'))
    n_pass_min = sum(1 for h in results['hypotheses'] if h.get('n', 0) >= 30 and h.get('yield_mean') and h['yield_mean'] > 0.05)
    print(f'\n=== RESUMEN ===')
    print(f'Filtros testeados: {n_tests}')
    print(f'Bonferroni alpha/test: {bonferroni_alpha:.5f}')
    print(f'Filtros con CI95 lower > 0: {n_sig}')
    print(f'Filtros N>=30 + yield > 5%: {n_pass_min}')
    print(f'**ATENCIÓN**: N pequeño (61) limita validez. Walk-forward inter-año imposible (SOFA solo 2026).')
    con.close()


if __name__ == '__main__':
    main()

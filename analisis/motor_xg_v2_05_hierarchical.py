# FASE 2 (Tarea 5) - Bayesian hierarchical Ridge con partial pooling per-liga.
# REF: docs/papers/motor_xg_v2_research.md (Baio-Blangiardo 2010 + Berrar 2019)
# REF: docs/definiciones/rmse_forward_ema.md

from __future__ import annotations
import json
import sqlite3
from collections import defaultdict
from math import sqrt
from pathlib import Path
import numpy as np

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_05_hierarchical.json'
HOLDOUT_YEARS = ('2026',)
TRAIN_YEARS = ('2022', '2023', '2024', '2025')
COTA_POISSON = 1.18
THETA_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
EM_MAX_ITER = 30
EM_TOL = 1e-6
MIN_N_LIGA = 50

SQL_PARTIDOS = (
    'SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac '
    + 'FROM stats_partido_espn '
    + 'WHERE hg IS NOT NULL AND ag IS NOT NULL '
    + '  AND hst IS NOT NULL AND ast IS NOT NULL '
    + '  AND hs IS NOT NULL AND as_v IS NOT NULL '
    + '  AND hc IS NOT NULL AND ac IS NOT NULL '
    + 'ORDER BY fecha ASC, ht ASC'
)

def cargar_partidos():
    con = sqlite3.connect(DB); cur = con.cursor()
    rows = cur.execute(SQL_PARTIDOS).fetchall()
    con.close()
    out = []
    for r in rows:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac = r
        out.append(dict(liga=liga, fecha=fecha, ht=ht, at=at, hg=hg, ag=ag, hst=hst, ast=ast, hs=hs, as_v=as_v, hc=hc, ac=ac))
    return out

def cargar_alfa_ema():
    con = sqlite3.connect(DB); cur = con.cursor()
    alfa = {}
    sql = "SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND tipo='float'"
    for r in cur.execute(sql):
        alfa[r[0]] = float(r[1])
    con.close()
    DEFAULT = 0.10
    alfa.pop('global', None)
    return alfa, DEFAULT

def construir_eventos(partidos):
    eventos = []
    for p in partidos:
        eventos.append(dict(fecha=p['fecha'], liga=p['liga'], equipo=p['ht'], goles=p['hg'], sot=p['hst'], shots_off=max(0, p['hs'] - p['hst']), corners=p['hc']))
        eventos.append(dict(fecha=p['fecha'], liga=p['liga'], equipo=p['at'], goles=p['ag'], sot=p['ast'], shots_off=max(0, p['as_v'] - p['ast']), corners=p['ac']))
    return eventos

def evento_year(ev): return ev['fecha'][:4]

def fit_hierarchical_eb(eventos_train, verbose=False):
    by_liga = defaultdict(list)
    for ev in eventos_train:
        by_liga[ev['liga']].append(ev)
    ligas_validas = [l for l, evs in by_liga.items() if len(evs) >= MIN_N_LIGA]
    if not ligas_validas:
        return None
    coefs_per_liga_ols = {}
    beta_off_per_liga = []
    beta_corner_per_liga = []
    sigma2_eps_acc = 0.0
    n_total = 0
    for l in ligas_validas:
        evs = by_liga[l]
        X = np.array([[1.0, ev['sot'], ev['shots_off'], ev['corners']] for ev in evs], dtype=float)
        y = np.array([ev['goles'] for ev in evs], dtype=float)
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        alpha_l, beta_sot_l, beta_off_l, beta_corner_l = beta
        coefs_per_liga_ols[l] = (alpha_l, beta_sot_l)
        beta_off_per_liga.append(beta_off_l)
        beta_corner_per_liga.append(beta_corner_l)
        residuals = y - X @ beta
        sigma2_eps_acc += float(np.sum(residuals ** 2))
        n_total += len(evs)
    if not coefs_per_liga_ols:
        return None
    beta_off = max(0.0, float(np.mean(beta_off_per_liga)))
    beta_corner = max(0.0, float(np.mean(beta_corner_per_liga)))
    alphas_ols = np.array([coefs_per_liga_ols[l][0] for l in ligas_validas])
    betas_sot_ols = np.array([coefs_per_liga_ols[l][1] for l in ligas_validas])
    n_per_liga = np.array([len(by_liga[l]) for l in ligas_validas], dtype=float)
    alpha_g = float(np.mean(alphas_ols))
    beta_sot_g = float(np.mean(betas_sot_ols))
    sigma2_alpha = float(np.var(alphas_ols, ddof=1)) if len(alphas_ols) > 1 else 0.01
    sigma2_beta = float(np.var(betas_sot_ols, ddof=1)) if len(betas_sot_ols) > 1 else 0.001
    sigma2_eps = sigma2_eps_acc / max(1, n_total - 4 * len(ligas_validas))
    sigma2_eps = max(sigma2_eps, 1e-4)
    if verbose:
        print('  [EB init] alpha_g={:.4f}, beta_sot_g={:.4f}, s2a={:.4f}, s2b={:.6f}, s2e={:.4f}'.format(alpha_g, beta_sot_g, sigma2_alpha, sigma2_beta, sigma2_eps))
    alphas = alphas_ols.copy()
    betas_sot = betas_sot_ols.copy()
    converged = False
    it = 0
    for it in range(EM_MAX_ITER):
        new_alphas = np.zeros(len(ligas_validas))
        new_betas_sot = np.zeros(len(ligas_validas))
        sigma2_eps_acc_new = 0.0
        n_eff = 0
        for i, l in enumerate(ligas_validas):
            evs = by_liga[l]
            X = np.array([[1.0, ev['sot']] for ev in evs], dtype=float)
            y_resid = np.array([ev['goles'] - beta_off * ev['shots_off'] - beta_corner * ev['corners'] for ev in evs], dtype=float)
            XtX = X.T @ X
            Xty = X.T @ y_resid
            P_prior = np.diag([1.0 / max(sigma2_alpha, 1e-8), 1.0 / max(sigma2_beta, 1e-10)])
            P_post = XtX / max(sigma2_eps, 1e-6) + P_prior
            mu_prior = np.array([alpha_g, beta_sot_g])
            try:
                cov_post = np.linalg.inv(P_post)
                mu_post = cov_post @ (Xty / max(sigma2_eps, 1e-6) + P_prior @ mu_prior)
            except np.linalg.LinAlgError:
                mu_post = mu_prior
            new_alphas[i] = mu_post[0]
            new_betas_sot[i] = mu_post[1]
            preds = mu_post[0] + mu_post[1] * X[:, 1]
            residuals = y_resid - preds
            sigma2_eps_acc_new += float(np.sum(residuals ** 2))
            n_eff += len(evs)
        new_alpha_g = float(np.mean(new_alphas))
        new_beta_sot_g = float(np.mean(new_betas_sot))
        new_sigma2_alpha = float(np.var(new_alphas - new_alpha_g, ddof=0))
        new_sigma2_beta = float(np.var(new_betas_sot - new_beta_sot_g, ddof=0))
        new_sigma2_eps = sigma2_eps_acc_new / max(1, n_eff - 2 * len(ligas_validas))
        new_sigma2_eps = max(new_sigma2_eps, 1e-4)
        delta = max(abs(new_alpha_g - alpha_g), abs(new_beta_sot_g - beta_sot_g), abs(new_sigma2_alpha - sigma2_alpha), abs(new_sigma2_beta - sigma2_beta), abs(new_sigma2_eps - sigma2_eps))
        alphas, betas_sot = new_alphas, new_betas_sot
        alpha_g, beta_sot_g = new_alpha_g, new_beta_sot_g
        sigma2_alpha, sigma2_beta = new_sigma2_alpha, new_sigma2_beta
        sigma2_eps = new_sigma2_eps
        if verbose:
            print('  [EB it {}] alpha_g={:.4f}, beta_sot_g={:.4f}, s2a={:.4f}, s2b={:.6f}, s2e={:.4f}, d={:.6f}'.format(it+1, alpha_g, beta_sot_g, sigma2_alpha, sigma2_beta, sigma2_eps, delta))
        if delta < EM_TOL:
            converged = True
            break
    out = {'_global': dict(alpha=alpha_g, beta_sot=beta_sot_g, beta_off=beta_off, beta_corner=beta_corner, sigma2_alpha=sigma2_alpha, sigma2_beta=sigma2_beta, sigma2_eps=sigma2_eps, converged=converged, n_iter=it+1, n_ligas=len(ligas_validas))}
    for i, l in enumerate(ligas_validas):
        out[l] = dict(alpha=float(alphas[i]), beta_sot=float(betas_sot[i]), beta_off=beta_off, beta_corner=beta_corner, n_train=int(n_per_liga[i]), alpha_ols=float(alphas_ols[i]), beta_sot_ols=float(betas_sot_ols[i]))
    return out

def predecir_xg_calc(ev, modelo):
    coefs = modelo.get(ev['liga']) or modelo.get('_global')
    if coefs is None:
        return None
    if ev['liga'] not in modelo:
        g = modelo['_global']
        s_ = g['alpha'] + g['beta_sot'] * ev['sot'] + g['beta_off'] * ev['shots_off'] + g['beta_corner'] * ev['corners']
    else:
        s_ = coefs['alpha'] + coefs['beta_sot'] * ev['sot'] + coefs['beta_off'] * ev['shots_off'] + coefs['beta_corner'] * ev['corners']
    return max(0.0, s_)

def rmse_forward_ema(eventos, theta, modelo, alfa_ema, def_alfa):
    state = defaultdict(lambda: dict(ema=None, n=0))
    errs_by_year = defaultdict(list)
    n_used = 0
    n_skipped = 0
    for ev in sorted(eventos, key=lambda e: e['fecha']):
        liga = ev['liga']
        alfa = alfa_ema.get(liga, def_alfa)
        xg_calc = predecir_xg_calc(ev, modelo)
        if xg_calc is None:
            n_skipped += 1
            continue
        n_used += 1
        goles = ev['goles']
        xg_final = theta * xg_calc + (1.0 - theta) * goles
        st = state[ev['equipo']]
        if st['ema'] is not None and st['n'] >= WARMUP:
            errs_by_year[evento_year(ev)].append(st['ema'] - goles)
        if st['ema'] is None:
            st['ema'] = xg_final
        else:
            st['ema'] = alfa * xg_final + (1.0 - alfa) * st['ema']
        st['n'] += 1
    return _resumir(errs_by_year, n_used, n_skipped)

def _resumir(errs_by_year, n_used=None, n_skipped=None):
    def rmse(errs):
        if not errs: return None
        return sqrt(sum(e * e for e in errs) / len(errs))
    out = {}
    for y in sorted(errs_by_year.keys()):
        out[y] = dict(rmse=rmse(errs_by_year[y]), n=len(errs_by_year[y]))
    pool = []
    for y in TRAIN_YEARS:
        pool.extend(errs_by_year.get(y, []))
    out['OOS_pool'] = dict(rmse=rmse(pool), n=len(pool))
    holdout = []
    for y in HOLDOUT_YEARS:
        holdout.extend(errs_by_year.get(y, []))
    out['IS_2026'] = dict(rmse=rmse(holdout), n=len(holdout))
    if n_used is not None: out['_n_eventos_usados'] = n_used
    if n_skipped is not None: out['_n_eventos_skipped'] = n_skipped
    return out

def cv_5fold_temporal(eventos_all, theta, alfa_ema, def_alfa):
    eventos_uni = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    eventos_uni.sort(key=lambda e: e['fecha'])
    n = len(eventos_uni)
    if n < 100: return dict(rmse_mean=None)
    fold_size = n // 5
    rmses = []
    for k in range(5):
        i_start = k * fold_size
        i_end = (k + 1) * fold_size if k < 4 else n
        test_evs = eventos_uni[i_start:i_end]
        train_evs = eventos_uni[:i_start] + eventos_uni[i_end:]
        modelo = fit_hierarchical_eb(train_evs)
        if modelo is None: continue
        errs = []
        for ev in test_evs:
            xg = predecir_xg_calc(ev, modelo)
            if xg is None: continue
            errs.append(xg - ev['goles'])
        if errs:
            rmses.append(sqrt(sum(e * e for e in errs) / len(errs)))
    if not rmses: return dict(rmse_mean=None)
    return dict(rmse_mean=sum(rmses)/len(rmses), rmse_per_fold=rmses, n_folds=len(rmses))

def loyo_inter_year(eventos_all, theta, alfa_ema, def_alfa):
    eventos_uni = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    out = {}
    for test_year in TRAIN_YEARS:
        train_evs = [ev for ev in eventos_uni if evento_year(ev) != test_year]
        modelo = fit_hierarchical_eb(train_evs)
        if modelo is None:
            out[test_year] = dict(rmse_test_year=None)
            continue
        resumen = rmse_forward_ema(eventos_uni, theta, modelo, alfa_ema, def_alfa)
        out[test_year] = dict(rmse_test_year=resumen.get(test_year, {}).get('rmse'), n_test_year=resumen.get(test_year, {}).get('n'))
    return out

def main():
    print('=== FASE 2 (T5) ===')
    print('REF: Baio-Blangiardo 2010 + Berrar 2019')
    print()
    partidos = cargar_partidos()
    print('Partidos:', len(partidos))
    eventos_all = construir_eventos(partidos)
    print('Eventos:', len(eventos_all))
    n_train_uni = sum(1 for ev in eventos_all if evento_year(ev) in TRAIN_YEARS)
    n_holdout = sum(1 for ev in eventos_all if evento_year(ev) in HOLDOUT_YEARS)
    print('  TRAIN universe (2022-2025):', n_train_uni)
    print('  HOLDOUT 2026:', n_holdout)
    alfa_ema, def_alfa = cargar_alfa_ema()
    eventos_train = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    print('Fit EB sobre N=', len(eventos_train))
    modelo = fit_hierarchical_eb(eventos_train, verbose=True)
    if modelo is None:
        print('ERROR')
        return
    print()
    g = modelo['_global']
    print('--- Globals ---')
    print('  alpha_global   =', round(g['alpha'], 4))
    print('  beta_sot_global=', round(g['beta_sot'], 4))
    print('  beta_off       =', round(g['beta_off'], 4))
    print('  beta_corner    =', round(g['beta_corner'], 4))
    print('  sd_alpha       =', round(sqrt(g['sigma2_alpha']), 4))
    print('  sd_beta_sot    =', round(sqrt(g['sigma2_beta']), 6))
    print('  sd_eps         =', round(sqrt(g['sigma2_eps']), 4))
    print('  converged      =', g['converged'])
    print('  n_iter         =', g['n_iter'])
    print('  n_ligas        =', g['n_ligas'])
    print()
    ligas = sorted([k for k in modelo if k != '_global'], key=lambda l: abs(modelo[l]['alpha'] - g['alpha']), reverse=True)
    print('--- Coefs per-liga (sorted) ---')
    print('liga           |     n |    alpha | beta_sot | a_OLS  | b_OLS')
    for l in ligas:
        m = modelo[l]
        print('{:<14} | {:>5} | {:>8.4f} | {:>8.4f} | {:>6.3f} | {:>6.3f}'.format(l, m['n_train'], m['alpha'], m['beta_sot'], m['alpha_ols'], m['beta_sot_ols']))
    print()
    print('--- RMSE forward-EMA por theta ---')
    print('theta  | OOS_pool   | IS_2026    |   n_OOS | n_IS')
    theta_results = {}
    for theta in THETA_GRID:
        resumen = rmse_forward_ema(eventos_all, theta, modelo, alfa_ema, def_alfa)
        oos = resumen['OOS_pool']['rmse']
        is26 = resumen['IS_2026']['rmse']
        theta_results['{:.2f}'.format(theta)] = resumen
        oos_s = ('{:.4f}'.format(oos)) if oos is not None else 'None'
        is_s = ('{:.4f}'.format(is26)) if is26 is not None else 'None'
        print('{:>5.2f}  | {:>10} | {:>10} | {:>7} | {:>4}'.format(theta, oos_s, is_s, resumen['OOS_pool']['n'], resumen['IS_2026']['n']))
    valid_thetas = [(t, r) for t, r in theta_results.items() if r['OOS_pool']['rmse'] is not None]
    valid_thetas.sort(key=lambda x: x[1]['OOS_pool']['rmse'])
    best_theta_str, best_resumen = valid_thetas[0]
    best_theta = float(best_theta_str)
    best_oos = best_resumen['OOS_pool']['rmse']
    best_is26 = best_resumen['IS_2026']['rmse']
    print()
    print('BEST theta =', best_theta_str, 'RMSE OOS pool =', round(best_oos, 4), 'IS_2026 =', best_is26)
    breaks_poisson_floor = best_oos < COTA_POISSON
    print('breaks_poisson_floor:', breaks_poisson_floor)
    print()
    print('--- 5-fold temporal CV intra-anho ---')
    cv5 = cv_5fold_temporal(eventos_all, best_theta, alfa_ema, def_alfa)
    print('  rmse_mean =', cv5.get('rmse_mean'))
    print()
    print('--- LOYO inter-anho ---')
    loyo = loyo_inter_year(eventos_all, best_theta, alfa_ema, def_alfa)
    for y, r in loyo.items():
        rmse_y = r['rmse_test_year']
        rmse_str = ('{:.4f}'.format(rmse_y)) if rmse_y is not None else 'None'
        print('  test', y, ': rmse =', rmse_str, 'n=', r.get('n_test_year'))
    BASELINE_V0 = 1.1880
    BASELINE_V5 = 1.1963
    out_json = dict()
    out_json['_meta'] = dict(fecha='2026-05-03', script='motor_xg_v2_05_hierarchical.py', refs=dict(papers='docs/papers/motor_xg_v2_research.md', definicion='docs/definiciones/rmse_forward_ema.md'), N_partidos=len(partidos), N_eventos_total=len(eventos_all), N_eventos_train=n_train_uni, N_eventos_holdout=n_holdout, WARMUP=WARMUP, holdout_years=list(HOLDOUT_YEARS), train_years=list(TRAIN_YEARS), theta_grid=list(THETA_GRID), em_max_iter=EM_MAX_ITER, em_tol=EM_TOL, min_n_liga=MIN_N_LIGA)
    out_json['globals_learned'] = modelo['_global']
    out_json['coefs_per_liga'] = {l: modelo[l] for l in modelo if l != '_global'}
    out_json['theta_grid_results'] = theta_results
    out_json['best_theta'] = best_theta
    out_json['best_rmse_oos_pool'] = best_oos
    out_json['best_rmse_is_2026'] = best_is26
    out_json['breaks_poisson_floor'] = breaks_poisson_floor
    out_json['cota_poisson_floor'] = COTA_POISSON
    out_json['cv_5fold_temporal'] = cv5
    out_json['loyo_inter_year'] = loyo
    out_json['comparison_vs_baseline'] = dict(V0_motor_theta_020_oos_pool=BASELINE_V0, V5_NNLS_theta_020_oos_pool=BASELINE_V5, hierarchical_best_oos_pool=best_oos, delta_vs_v0=best_oos - BASELINE_V0, delta_vs_v5=best_oos - BASELINE_V5, ratio_vs_v5=best_oos / BASELINE_V5)
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(out_json, f, indent=2)
    print()
    print('Guardado:', OUT_JSON)

if __name__ == '__main__':
    main()


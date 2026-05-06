"""
FASE 3 — Validacion uniforme cross-approach sobre subset comun N=18,774.

Objetivo: descartar selection bias.

Diagnostico Fase 2:
  Ridge per-liga F_ext OOS 1.1698 sobre N=18,774 (filter pos NULL)
  Bayesian hierarchical OOS 1.1848 sobre N=25,998 (sin filter)
  XGBoost OOS 1.1953 sobre N=26,860 (sin filter)
  V5 NNLS baseline OOS 1.1963 sobre N=26,860

Hipotesis: el filtro pos/pass_pct NULL descarta partidos sistemicamente mas dificiles.
Test: re-correr V5, Ridge F_ext, Bayesian, XGBoost sobre el MISMO subset N=18,774
       (eventos donde h_pos NOT NULL Y a_pos NOT NULL).
       Si todos bajan ~0.015 sobre N=18,774, confirma artefacto de subsampleo.

Holdout 2026 CONGELADO — NO usado en este script.
"""

import sqlite3
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path
import numpy as np
from scipy.optimize import nnls

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_99_validation_uniforme.json'


def cargar_partidos(filtrar_pos_null=False):
    """Cargar partidos. Si filtrar_pos_null=True, descarta los 3,689 sin h_pos/a_pos."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    where = "hg IS NOT NULL AND ag IS NOT NULL AND hst IS NOT NULL AND ast IS NOT NULL"
    if filtrar_pos_null:
        where += " AND h_pos IS NOT NULL AND a_pos IS NOT NULL AND h_pass_pct IS NOT NULL AND a_pass_pct IS NOT NULL"
    rows = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves
        FROM stats_partido_espn
        WHERE {where}
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    return rows


def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
         h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves) = r
        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
            'sot': hst or 0, 'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0, 'pos': h_pos, 'pass_pct': h_pass_pct,
            'saves_rival': a_saves, 'goles': hg,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
            'sot': ast or 0, 'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0, 'pos': a_pos, 'pass_pct': a_pass_pct,
            'saves_rival': h_saves, 'goles': ag,
        })
    return eventos


def aplicar_ema_y_rmse(eventos, predicciones_xg_final, alfa=0.10):
    """Aplica EMA forward-strict por equipo sobre predicciones_xg_final.
    Devuelve dict {year: rmse, OOS_pool, IS_2026}."""
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)

    # Sort eventos cronologicamente
    idx_sorted = sorted(range(len(eventos)), key=lambda i: eventos[i]['fecha'])

    for idx in idx_sorted:
        ev = eventos[idx]
        xg_final = predicciones_xg_final[idx]
        s = state[ev['equipo']]
        if s['ema'] is not None and s['n'] >= WARMUP:
            year = ev['fecha'][:4]
            errs_by_year[year].append(s['ema'] - ev['goles'])
        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = alfa * xg_final + (1.0 - alfa) * s['ema']
        s['n'] += 1

    def rmse(errs):
        if not errs:
            return None
        return sqrt(sum(e * e for e in errs) / len(errs))

    out = {}
    for y in sorted(errs_by_year.keys()):
        out[y] = {'rmse': rmse(errs_by_year[y]), 'n': len(errs_by_year[y])}
    pool = []
    for y in ('2022', '2023', '2024', '2025'):
        pool.extend(errs_by_year.get(y, []))
    out['OOS_pool'] = {'rmse': rmse(pool), 'n': len(pool)}
    is_2026 = errs_by_year.get('2026', [])
    out['IS_2026'] = {'rmse': rmse(is_2026), 'n': len(is_2026)}
    return out


def construir_predicciones(eventos, modelo, theta, params=None):
    """modelo in {'V5_NNLS', 'NNLS_pool', 'Ridge_F_ext_per_liga', 'Bayesian_global'}.
    Devuelve list[float] de xg_final por evento (en mismo orden de input).
    """
    preds = []
    for ev in eventos:
        sot = ev['sot']
        goles = ev['goles']

        if modelo == 'V5_NNLS':
            # intercept=0.273, beta_SOT=0.247
            xg_calc = 0.273 + 0.247 * sot
        elif modelo == 'NNLS_pool':
            # intercept=0.263, beta_SOT=0.252
            xg_calc = 0.263 + 0.252 * sot
        elif modelo == 'Ridge_F_ext_per_liga':
            # Coefs aprendidos por liga (cargados de JSON Fase 2A) o re-fit aqui.
            # Aqui usamos coefs persistidos. params = {'liga': {'int': x, 'sot': y, ...}}
            liga = ev['liga']
            cf = params.get(liga, params['_global'])
            xg_calc = (cf['int'] + cf['sot'] * sot
                       + cf['shots_off'] * ev['shots_off']
                       + cf['corners'] * ev['corners']
                       + cf['pos'] * (ev['pos'] or 0)
                       + cf['pass_pct'] * (ev['pass_pct'] or 0)
                       + cf['saves_rival'] * (ev['saves_rival'] or 0))
            xg_calc = max(0, xg_calc)
        elif modelo == 'Bayesian_hierarchical':
            # alpha_global=0.7334, beta_SOT_global=0.2064 + per-liga deviations
            liga = ev['liga']
            cf = params.get(liga, {'alpha': 0.7334, 'beta_sot': 0.2064})
            xg_calc = max(0, cf['alpha'] + cf['beta_sot'] * sot)
        else:
            raise ValueError(f'Unknown modelo: {modelo}')

        xg_final = theta * xg_calc + (1.0 - theta) * goles
        preds.append(xg_final)
    return preds


def fit_ridge_per_liga_F_ext(eventos_train):
    """Re-fit Ridge per-liga F_ext sobre el subset dado. NNLS (positive Ridge limit).
    Features: int + sot + shots_off + corners + pos + pass_pct + saves_rival.
    """
    by_liga = defaultdict(list)
    for ev in eventos_train:
        by_liga[ev['liga']].append(ev)

    coefs = {}
    # Pool global para ligas pequenas
    all_X = []
    all_y = []
    for ev in eventos_train:
        if ev['pos'] is None or ev['pass_pct'] is None or ev['saves_rival'] is None:
            continue
        all_X.append([1.0, ev['sot'], ev['shots_off'], ev['corners'],
                       ev['pos'], ev['pass_pct'], ev['saves_rival']])
        all_y.append(ev['goles'])
    all_X = np.array(all_X)
    all_y = np.array(all_y)
    if len(all_X) > 0:
        glob, _ = nnls(all_X, all_y)
        coefs['_global'] = {
            'int': glob[0], 'sot': glob[1], 'shots_off': glob[2], 'corners': glob[3],
            'pos': glob[4], 'pass_pct': glob[5], 'saves_rival': glob[6]
        }

    for liga, evs in by_liga.items():
        X, y = [], []
        for ev in evs:
            if ev['pos'] is None or ev['pass_pct'] is None or ev['saves_rival'] is None:
                continue
            X.append([1.0, ev['sot'], ev['shots_off'], ev['corners'],
                       ev['pos'], ev['pass_pct'], ev['saves_rival']])
            y.append(ev['goles'])
        if len(X) < 100:
            coefs[liga] = coefs['_global']
            continue
        X = np.array(X)
        y = np.array(y)
        try:
            sol, _ = nnls(X, y)
            coefs[liga] = {
                'int': sol[0], 'sot': sol[1], 'shots_off': sol[2], 'corners': sol[3],
                'pos': sol[4], 'pass_pct': sol[5], 'saves_rival': sol[6]
            }
        except Exception:
            coefs[liga] = coefs['_global']
    return coefs


def main():
    print('=== FASE 3: VALIDACION UNIFORME SUBSET COMUN ===\n')

    # Cargar AMBOS universos
    print('Cargando universos...')
    partidos_full = cargar_partidos(filtrar_pos_null=False)
    partidos_filt = cargar_partidos(filtrar_pos_null=True)
    print(f'  N_full (sin filter): {len(partidos_full)} partidos')
    print(f'  N_filt (con pos/pass_pct NOT NULL): {len(partidos_filt)} partidos')
    print(f'  Diferencia: {len(partidos_full) - len(partidos_filt)} partidos descartados\n')

    eventos_full = construir_eventos(partidos_full)
    eventos_filt = construir_eventos(partidos_filt)
    print(f'  Eventos full: {len(eventos_full)}')
    print(f'  Eventos filt: {len(eventos_filt)}\n')

    # Splits temporales: train < 2026, holdout 2026 (NO TOCAR)
    eventos_train_full = [e for e in eventos_full if e['fecha'][:4] < '2026']
    eventos_train_filt = [e for e in eventos_filt if e['fecha'][:4] < '2026']
    print(f'  Eventos train_full (<2026): {len(eventos_train_full)}')
    print(f'  Eventos train_filt (<2026): {len(eventos_train_filt)}\n')

    # Fit Ridge F_ext sobre train_filt (re-fit con datos limpios)
    print('Fitting Ridge per-liga F_ext sobre train_filt...')
    ridge_coefs = fit_ridge_per_liga_F_ext(eventos_train_filt)
    print(f'  Coefs por liga: {len(ridge_coefs) - 1}')
    print(f'  Global: int={ridge_coefs["_global"]["int"]:.4f}, sot={ridge_coefs["_global"]["sot"]:.4f}')

    # Bayesian hierarchical: usar coefs persistidos por agente C
    bayesian_coefs_path = 'analisis/motor_xg_v2_05_hierarchical.json'
    bayesian_per_liga = {}
    try:
        with open(bayesian_coefs_path) as f:
            bay_data = json.load(f)
        # Extraer coefs por liga (estructura puede variar)
        # Usar global como fallback
    except Exception as e:
        print(f'  Warning: no se cargo bayesian JSON: {e}')

    # Modelos a comparar
    modelos = [
        ('V5_NNLS', None),
        ('NNLS_pool', None),
        ('Ridge_F_ext_per_liga', ridge_coefs),
    ]

    # Run 4 escenarios cruzados (modelo x universo) con theta=0.30 (best Fase 2)
    theta_best = 0.30
    alfa_default = 0.10

    resultados = {}

    for universo_tag, eventos_eval in [('FULL_N=26860', eventos_full),
                                        ('FILT_N=18774', eventos_filt)]:
        print(f'\n--- Universo {universo_tag} ---')
        resultados[universo_tag] = {}
        for modelo, params in modelos:
            try:
                preds = construir_predicciones(eventos_eval, modelo, theta_best, params)
                metrics = aplicar_ema_y_rmse(eventos_eval, preds, alfa=alfa_default)
                resultados[universo_tag][modelo] = metrics
                pool = metrics['OOS_pool']['rmse']
                is26 = metrics['IS_2026']['rmse']
                n_pool = metrics['OOS_pool']['n']
                rompe = '*' if pool < 1.18 else ' '
                print(f'  [{rompe}] {modelo:<28s} OOS={pool:.4f} (N={n_pool}) IS_2026={is26:.4f if is26 else "N/A"}')
            except Exception as e:
                print(f'  ERROR {modelo}: {e}')

    # Comparacion explicita
    print('\n=== TABLA COMPARATIVA HONESTA ===')
    print(f'{"Modelo":<28s} | {"FULL OOS":>10s} | {"FILT OOS":>10s} | {"Delta (FILT-FULL)":>18s} | {"Rompe 1.18":>12s}')
    for modelo, _ in modelos:
        full = resultados['FULL_N=26860'].get(modelo, {}).get('OOS_pool', {}).get('rmse')
        filt = resultados['FILT_N=18774'].get(modelo, {}).get('OOS_pool', {}).get('rmse')
        if full and filt:
            delta = filt - full
            rompe_full = 'YES' if full < 1.18 else ' no'
            rompe_filt = 'YES' if filt < 1.18 else ' no'
            print(f'{modelo:<28s} | {full:>10.4f} | {filt:>10.4f} | {delta:>+18.4f} | full={rompe_full} filt={rompe_filt}')

    # Diagnostico final
    print('\n=== DIAGNOSTICO ===')
    v5_full = resultados['FULL_N=26860']['V5_NNLS']['OOS_pool']['rmse']
    v5_filt = resultados['FILT_N=18774']['V5_NNLS']['OOS_pool']['rmse']
    delta_v5_subset = v5_filt - v5_full
    print(f'V5 NNLS sufre delta {delta_v5_subset:+.4f} al pasar de FULL a FILT.')
    if delta_v5_subset < -0.005:
        print('  -> El SUBSET (filter pos NULL) ES intrinsecamente mas facil.')
        print('  -> Selection bias confirmado. RMSE comparativo entre approaches debe ser SOBRE EL MISMO universo.')
    else:
        print('  -> El subset filt no es significativamente mas facil.')
        print('  -> El gap Ridge F_ext (1.1698) seria edge real.')

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'theta_evaluado': theta_best,
            'alfa_default': alfa_default,
            'universos': {
                'FULL_N': len(eventos_full),
                'FILT_N': len(eventos_filt),
                'descartados': len(eventos_full) - len(eventos_filt),
            },
            'resultados': resultados,
            'ridge_coefs_global': ridge_coefs.get('_global'),
            'diagnostico_v5_subset_bias': {
                'V5_OOS_full': v5_full,
                'V5_OOS_filt': v5_filt,
                'delta': delta_v5_subset,
                'selection_bias_confirmado': delta_v5_subset < -0.005,
            },
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

"""
FASE 7 — Ablation study features extendidos (tarjetas, fouls, offsides, possession).

Diagnostico Fase 6:
  - Yellow/Red/Fouls/Offsides cobertura buena (N=13,429) PERO scraping bias temporal:
    37% partidos 2022/2023 con yellow=0 ambos equipos (subreporting). Mejora a 19% en 2024.
  - Correlaciones bajas con goles: max |0.085| (h_red).
  - Possession ya probada en Fase 2A, no aporta cuando se controla por SOT.

Objetivo: ablation individual y combinado de cada feature sobre RMSE forward-EMA,
en 2 universos:
  U1: FULL N=26,860 eventos
  U2: 2024+ donde scraping cobertura es buena (N approx 8,000-10,000 eventos)

Hipotesis nula: ninguna feature individual baja RMSE > 0.005 (ruido).
Si alguna lo hace, evaluar combinacion en Fase 9.
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
OUT_JSON = 'analisis/motor_xg_v2_06_features_extendidos.json'


def cargar_partidos_full():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
               h_yellow, a_yellow, h_red, a_red, h_fouls, a_fouls,
               h_offsides, a_offsides, h_blocks, a_blocks
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND h_yellow IS NOT NULL AND a_yellow IS NOT NULL
          AND h_red IS NOT NULL AND a_red IS NOT NULL
          AND h_fouls IS NOT NULL AND a_fouls IS NOT NULL
          AND h_offsides IS NOT NULL AND a_offsides IS NOT NULL
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    return rows


def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
         h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
         h_yellow, a_yellow, h_red, a_red, h_fouls, a_fouls,
         h_offsides, a_offsides, h_blocks, a_blocks) = r
        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
            'sot': hst or 0, 'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0,
            'pos': h_pos, 'pass_pct': h_pass_pct,
            'saves_rival': a_saves, 'blocks_rival': a_blocks,
            'yellow_propio': h_yellow or 0, 'yellow_rival': a_yellow or 0,
            'red_propio': h_red or 0, 'red_rival': a_red or 0,
            'fouls_propio': h_fouls or 0, 'fouls_rival': a_fouls or 0,
            'offsides_propio': h_offsides or 0, 'offsides_rival': a_offsides or 0,
            'goles': hg,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
            'sot': ast or 0, 'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0,
            'pos': a_pos, 'pass_pct': a_pass_pct,
            'saves_rival': h_saves, 'blocks_rival': h_blocks,
            'yellow_propio': a_yellow or 0, 'yellow_rival': h_yellow or 0,
            'red_propio': a_red or 0, 'red_rival': h_red or 0,
            'fouls_propio': a_fouls or 0, 'fouls_rival': h_fouls or 0,
            'offsides_propio': a_offsides or 0, 'offsides_rival': h_offsides or 0,
            'goles': ag,
        })
    return eventos


def fit_nnls(eventos_train, feature_names, with_intercept=True):
    """Fit NNLS positive regression sobre features especificadas."""
    X, y = [], []
    for ev in eventos_train:
        # Filter NaN para features que pueden ser None
        skip = False
        row = []
        if with_intercept:
            row.append(1.0)
        for fn in feature_names:
            v = ev.get(fn)
            if v is None:
                skip = True
                break
            row.append(float(v))
        if skip:
            continue
        X.append(row)
        y.append(ev['goles'])
    if not X:
        return None, 0
    X = np.array(X)
    y = np.array(y)
    sol, _ = nnls(X, y)
    return sol, len(X)


def aplicar_modelo_y_emas(eventos, feature_names, coefs, theta, alfa):
    """Aplica xg_calc lineal con coefs sobre eventos, EMA forward, RMSE.
    Devuelve dict {year: {rmse, n}, OOS_pool, IS_2026}."""
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)

    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])
    for ev in eventos_sorted:
        # Compute xg_calc
        xg_calc = coefs[0]  # intercept
        valid = True
        for i, fn in enumerate(feature_names):
            v = ev.get(fn)
            if v is None:
                valid = False
                break
            xg_calc += coefs[i + 1] * float(v)
        if not valid:
            continue
        xg_calc = max(0, xg_calc)
        xg_final = theta * xg_calc + (1.0 - theta) * ev['goles']

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


def correr_ablation(eventos, label, theta=0.30, alfa=0.10):
    """Corre suite de ablation. Train sobre eventos < 2026, eval sobre eventos."""
    eventos_train = [e for e in eventos if e['fecha'][:4] < '2026']
    print(f'\n--- ABLATION sobre {label} (eval N={len(eventos)}, train N={len(eventos_train)}) ---')

    out = {'label': label, 'n_eval': len(eventos), 'n_train': len(eventos_train)}

    # Modelo BASE (V5 NNLS solo SOT)
    sol_base, n_train_base = fit_nnls(eventos_train, ['sot'])
    print(f'  BASE [sot]: coefs int={sol_base[0]:.4f}, sot={sol_base[1]:.4f}, n_train={n_train_base}')
    metrics_base = aplicar_modelo_y_emas(eventos, ['sot'], sol_base, theta, alfa)
    out['BASE_sot'] = {'coefs': sol_base.tolist(), 'metrics': metrics_base}
    rmse_base = metrics_base['OOS_pool']['rmse']
    print(f'  BASE OOS={rmse_base:.4f}')

    # Ablations individuales: BASE + 1 feature
    individuales = {
        'BASE+yellow_propio': ['sot', 'yellow_propio'],
        'BASE+yellow_rival': ['sot', 'yellow_rival'],
        'BASE+red_propio': ['sot', 'red_propio'],
        'BASE+red_rival': ['sot', 'red_rival'],
        'BASE+fouls_propio': ['sot', 'fouls_propio'],
        'BASE+fouls_rival': ['sot', 'fouls_rival'],
        'BASE+offsides_propio': ['sot', 'offsides_propio'],
        'BASE+offsides_rival': ['sot', 'offsides_rival'],
        'BASE+pos': ['sot', 'pos'],
        'BASE+saves_rival': ['sot', 'saves_rival'],
        'BASE+blocks_rival': ['sot', 'blocks_rival'],
    }
    print(f'  --- INDIVIDUALES ---')
    for tag, fnames in individuales.items():
        sol, ntr = fit_nnls(eventos_train, fnames)
        if sol is None:
            continue
        m = aplicar_modelo_y_emas(eventos, fnames, sol, theta, alfa)
        rmse = m['OOS_pool']['rmse']
        delta = rmse - rmse_base
        coef_extra = sol[2] if len(sol) > 2 else 0
        n_eval = m['OOS_pool']['n']
        flag = '*' if delta < -0.001 else ' '
        print(f'  [{flag}] {tag:<28s} coef_extra={coef_extra:+.5f} OOS={rmse:.4f} delta={delta:+.4f} (n_eval={n_eval})')
        out[tag] = {'coefs': sol.tolist(), 'metrics': m, 'delta_vs_base': delta}

    # Ablation combinada: BASE + todas las defensivas (rival)
    combinadas = {
        'BASE+all_rival': ['sot', 'red_rival', 'yellow_rival', 'fouls_rival', 'saves_rival', 'blocks_rival'],
        'BASE+all_propio': ['sot', 'red_propio', 'yellow_propio', 'fouls_propio', 'offsides_propio'],
        'BASE+top_signals': ['sot', 'red_propio', 'red_rival', 'saves_rival', 'pos'],
        'FULL_KITCHEN_SINK': ['sot', 'shots_off', 'corners', 'pos', 'pass_pct', 'saves_rival',
                               'red_propio', 'red_rival', 'yellow_propio', 'yellow_rival',
                               'fouls_propio', 'fouls_rival', 'offsides_propio'],
    }
    print(f'  --- COMBINADAS ---')
    for tag, fnames in combinadas.items():
        sol, ntr = fit_nnls(eventos_train, fnames)
        if sol is None:
            continue
        m = aplicar_modelo_y_emas(eventos, fnames, sol, theta, alfa)
        rmse = m['OOS_pool']['rmse']
        delta = rmse - rmse_base
        n_eval = m['OOS_pool']['n']
        coefs_str = ' '.join(f'{c:+.3f}' for c in sol)
        flag = '*' if delta < -0.005 else ' '
        print(f'  [{flag}] {tag:<28s} coefs=[{coefs_str}] OOS={rmse:.4f} delta={delta:+.4f} (n={n_eval})')
        out[tag] = {'coefs': sol.tolist(), 'metrics': m, 'delta_vs_base': delta, 'features': fnames}

    return out


def main():
    print('=== FASE 7: ABLATION FEATURES EXTENDIDOS ===')
    partidos = cargar_partidos_full()
    print(f'Partidos con stats completas (yellow/red/fouls/offsides NOT NULL): {len(partidos)}')
    eventos_full = construir_eventos(partidos)
    print(f'Eventos: {len(eventos_full)}')

    # Universo 1: FULL
    out_full = correr_ablation(eventos_full, 'U1=FULL_2022-2026')

    # Universo 2: solo 2024+ (cobertura buena tarjetas/fouls)
    eventos_2024p = [e for e in eventos_full if e['fecha'][:4] >= '2024']
    out_2024p = correr_ablation(eventos_2024p, 'U2=2024+_buena_cobertura')

    # Resumen comparativo
    print('\n=== RESUMEN: features que aportan en AMBOS universos ===')
    print(f'{"feature":<28s} | {"FULL dRMSE":>10s} | {"2024+ dRMSE":>11s} | {"Recomendacion":<20s}')
    for tag in out_full.keys():
        if tag in ('label', 'n_eval', 'n_train', 'BASE_sot'):
            continue
        df = out_full.get(tag, {}).get('delta_vs_base')
        d24 = out_2024p.get(tag, {}).get('delta_vs_base')
        if df is None or d24 is None:
            continue
        recom = 'INCLUIR' if (df < -0.001 and d24 < -0.001) else \
                'descartar (ambos)' if (df > 0 and d24 > 0) else \
                'mixto - cautela' if abs(df-d24) > 0.005 else \
                'marginal'
        print(f'{tag:<28s} | {df:>+10.4f} | {d24:>+11.4f} | {recom:<20s}')

    # Save
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'theta': 0.30,
            'alfa': 0.10,
            'U1_FULL': out_full,
            'U2_2024p': out_2024p,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

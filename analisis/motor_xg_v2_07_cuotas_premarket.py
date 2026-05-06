"""
FASE 7B - Probar P_implicita_mercado pre-match como feature.

Hipotesis: las cuotas 1X2 son la unica info pre-match de alta calidad disponible.
Si P_imp como feature aporta a NNLS sobre SOT, vamos por buen camino.
Si NNLS la shrinka a 0, queda confirmado que post-match SOT captura todo y necesitamos
features no-derivables (arbitros/formaciones/lineups).

N=8,892 partidos con cuotas matched.
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
OUT_JSON = 'analisis/motor_xg_v2_07_cuotas_premarket.json'


def cargar_partidos_con_cuotas():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT s.liga, s.fecha, s.ht, s.at, s.hg, s.ag, s.hst, s.ast, s.hs, s.as_v, s.hc, s.ac,
               c.cuota_1, c.cuota_x, c.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco c
          ON s.ht_fdco_norm = c.equipo_local_norm
         AND s.at_fdco_norm = c.equipo_visita_norm
         AND s.fecha_fdco = c.fecha
        WHERE s.hg IS NOT NULL AND s.ag IS NOT NULL
          AND s.hst IS NOT NULL AND s.ast IS NOT NULL
          AND c.cuota_1 IS NOT NULL AND c.cuota_x IS NOT NULL AND c.cuota_2 IS NOT NULL
          AND c.cuota_1 > 1.0 AND c.cuota_x > 1.0 AND c.cuota_2 > 1.0
        ORDER BY s.fecha ASC, s.ht ASC
    """).fetchall()
    con.close()
    return rows


def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
         c1, cx, c2) = r
        # P_implicita normalizada por overround
        p1_raw = 1.0 / c1
        px_raw = 1.0 / cx
        p2_raw = 1.0 / c2
        overround = p1_raw + px_raw + p2_raw
        p_local = p1_raw / overround
        p_empate = px_raw / overround
        p_visita = p2_raw / overround
        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
            'sot': hst or 0, 'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0,
            'p_propio_pre': p_local, 'p_empate_pre': p_empate, 'p_rival_pre': p_visita,
            'cuota_propia': c1, 'cuota_rival': c2,
            'es_local': 1.0,
            'goles': hg,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
            'sot': ast or 0, 'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0,
            'p_propio_pre': p_visita, 'p_empate_pre': p_empate, 'p_rival_pre': p_local,
            'cuota_propia': c2, 'cuota_rival': c1,
            'es_local': 0.0,
            'goles': ag,
        })
    return eventos


def fit_nnls(eventos_train, feature_names):
    X, y = [], []
    for ev in eventos_train:
        row = [1.0]
        skip = False
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
    X = np.array(X)
    y = np.array(y)
    sol, _ = nnls(X, y)
    return sol, len(X)


def aplicar_y_eval(eventos, fnames, coefs, theta, alfa=0.10):
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)

    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])
    for ev in eventos_sorted:
        xg_calc = coefs[0]
        for i, fn in enumerate(fnames):
            v = ev.get(fn)
            if v is None:
                xg_calc = None
                break
            xg_calc += coefs[i + 1] * float(v)
        if xg_calc is None:
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
        return sqrt(sum(e * e for e in errs) / len(errs)) if errs else None

    out = {}
    for y in sorted(errs_by_year.keys()):
        out[y] = {'rmse': rmse(errs_by_year[y]), 'n': len(errs_by_year[y])}
    pool = []
    for y in ('2022', '2023', '2024', '2025'):
        pool.extend(errs_by_year.get(y, []))
    out['OOS_pool'] = {'rmse': rmse(pool), 'n': len(pool)}
    out['IS_2026'] = {'rmse': rmse(errs_by_year.get('2026', [])), 'n': len(errs_by_year.get('2026', []))}
    return out


def main():
    print('=== FASE 7B: P_implicita pre-match como feature ===')
    partidos = cargar_partidos_con_cuotas()
    print(f'Partidos con stats + cuotas matched: {len(partidos)}')
    eventos = construir_eventos(partidos)
    print(f'Eventos: {len(eventos)}')
    eventos_train = [e for e in eventos if e['fecha'][:4] < '2026']
    print(f'Eventos train (<2026): {len(eventos_train)}\n')

    # Cor sanity check: P_propio_pre vs goles
    Ps = np.array([e['p_propio_pre'] for e in eventos_train])
    Gs = np.array([e['goles'] for e in eventos_train])
    corr = np.corrcoef(Ps, Gs)[0, 1]
    print(f'Correlacion P_propio_pre vs goles: {corr:+.4f} (vs SOT corr ~0.30)\n')

    theta = 0.30
    alfa = 0.10
    results = {}

    suite = {
        'BASE_sot': ['sot'],
        'BASE_sot_p_propio': ['sot', 'p_propio_pre'],
        'BASE_sot_p_propio_p_rival': ['sot', 'p_propio_pre', 'p_rival_pre'],
        'BASE_sot_es_local': ['sot', 'es_local'],
        'BASE_sot_p_propio_es_local': ['sot', 'p_propio_pre', 'es_local'],
        'BASE_sot_p_diff': ['sot', 'p_propio_pre', 'p_rival_pre', 'es_local'],
        'PURE_p_propio': ['p_propio_pre'],
        'PURE_p_diff': ['p_propio_pre', 'p_rival_pre', 'es_local'],
    }

    print(f'{"Modelo":<32s} | {"int":>7s} {"sot":>7s} {"p_pr":>7s} {"p_riv":>7s} {"es_l":>7s} | {"OOS":>8s} {"IS_26":>8s} {"d_BASE":>8s}')
    rmse_base = None
    for tag, fnames in suite.items():
        sol, ntr = fit_nnls(eventos_train, fnames)
        m = aplicar_y_eval(eventos, fnames, sol, theta, alfa)
        pool = m['OOS_pool']['rmse']
        is26 = m['IS_2026']['rmse']
        if tag == 'BASE_sot':
            rmse_base = pool
        delta = pool - rmse_base if rmse_base else 0

        # Format coefs
        coefs_d = {'int': sol[0]}
        for i, fn in enumerate(fnames):
            coefs_d[fn] = sol[i + 1]
        cint = coefs_d.get('int', 0)
        csot = coefs_d.get('sot', 0)
        cppr = coefs_d.get('p_propio_pre', 0)
        cpri = coefs_d.get('p_rival_pre', 0)
        cesl = coefs_d.get('es_local', 0)
        is26_str = f'{is26:.4f}' if is26 else 'N/A'
        flag = '*' if delta < -0.005 else ' '
        print(f'[{flag}] {tag:<30s}| {cint:>7.4f} {csot:>7.4f} {cppr:>7.4f} {cpri:>7.4f} {cesl:>7.4f} | {pool:>8.4f} {is26_str:>8s} {delta:>+8.4f}')
        results[tag] = {'coefs': sol.tolist(), 'features': fnames, 'metrics': m}

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'theta': theta,
            'alfa': alfa,
            'corr_p_propio_goles': float(corr),
            'n_partidos': len(partidos),
            'n_eventos': len(eventos),
            'results': results,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

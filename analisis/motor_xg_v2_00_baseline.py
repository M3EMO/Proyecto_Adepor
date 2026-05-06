"""
FASE 1 — Baseline reproducible motor xG v2.

Objetivo: replicar la tabla de referencia en docs/definiciones/rmse_forward_ema.md
(lineas 199-208) sobre N=13,430 stats_partido_espn. Si replica, la metrica
forward-EMA esta bien definida y procedemos a Fase 2.

Baseline a replicar (sobre N=13,430 todas ligas):
  theta=0.10  -> OOS=1.1885 IS_2026=1.1730
  theta=0.15  -> OOS=1.1868 IS_2026=1.1956
  theta=0.20  -> OOS=1.1880 IS_2026=1.1665
  theta=0.30  -> OOS=1.2128 IS_2026=1.2034
  theta=0.50  -> OOS=1.2479 IS_2026=1.2274
  theta=0.70  -> OOS=1.2890 IS_2026=1.2583  (motor productivo)
  theta=1.00  -> OOS=1.4143 IS_2026=1.3832

Ademas computa RMSE V5 NNLS (intercept=0.273, beta_SOT=0.247) con theta=0.10.
"""

import sqlite3
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_00_baseline.json'


def cargar_params(alfa_default=0.10):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    beta_sot = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    DEFAULT_BETA = beta_sot.pop('global', 0.352)

    alfa_ema = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND tipo='float'"):
        alfa_ema[r[0]] = float(r[1])
    # alfa_default override (doc dice 0.10, DB dice 0.15)
    DEFAULT_ALFA = alfa_default

    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None:
            coef_corner[r[0]] = float(r[1])
    DEFAULT_CORNER = 0.03

    con.close()
    return beta_sot, alfa_ema, coef_corner, DEFAULT_BETA, DEFAULT_ALFA, DEFAULT_CORNER


def cargar_partidos():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    return rows


def construir_eventos(partidos):
    eventos = []
    for r in partidos:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac = r
        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht,
            'sot': hst or 0,
            'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0, 'goles': hg,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at,
            'sot': ast or 0,
            'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0, 'goles': ag,
        })
    return eventos


def computar_rmse_motor_v0(eventos, theta, beta_sot, alfa_ema, coef_corner,
                           def_beta, def_alfa, def_corner):
    """Motor V0: xg_calc = beta*SOT + 0.010*shots_off + coef_c*corners,
    xg_final = theta*xg_calc + (1-theta)*goles."""
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)

    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])

    for ev in eventos_sorted:
        liga = ev['liga']
        beta = beta_sot.get(liga, def_beta)
        coef_c = coef_corner.get(liga, def_corner)
        alfa = alfa_ema.get(liga, def_alfa)

        sot = ev['sot']
        shots_off = ev['shots_off']
        corners = ev['corners']
        goles = ev['goles']

        xg_calc = beta * sot + 0.010 * shots_off + coef_c * corners
        xg_final = theta * xg_calc + (1.0 - theta) * goles

        s = state[ev['equipo']]
        if s['ema'] is not None and s['n'] >= WARMUP:
            year = ev['fecha'][:4]
            errs_by_year[year].append(s['ema'] - goles)

        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = alfa * xg_final + (1.0 - alfa) * s['ema']
        s['n'] += 1

    return _resumir(errs_by_year)


def computar_rmse_v5_nnls(eventos, theta, intercept, beta_sot_v5, alfa_ema, def_alfa):
    """V5 NNLS: xg_calc = intercept + beta_SOT * SOT (resto shrinka a 0).
    xg_final = theta*xg_calc + (1-theta)*goles."""
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)

    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])

    for ev in eventos_sorted:
        liga = ev['liga']
        alfa = alfa_ema.get(liga, def_alfa)
        sot = ev['sot']
        goles = ev['goles']

        xg_calc = intercept + beta_sot_v5 * sot
        xg_final = theta * xg_calc + (1.0 - theta) * goles

        s = state[ev['equipo']]
        if s['ema'] is not None and s['n'] >= WARMUP:
            year = ev['fecha'][:4]
            errs_by_year[year].append(s['ema'] - goles)

        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = alfa * xg_final + (1.0 - alfa) * s['ema']
        s['n'] += 1

    return _resumir(errs_by_year)


def _resumir(errs_by_year):
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


def main():
    print('=== FASE 1 BASELINE — motor xG v2 ===')
    partidos = cargar_partidos()
    print(f'Partidos: {len(partidos)}')
    eventos = construir_eventos(partidos)
    print(f'Eventos (pre-warmup): {len(eventos)}')

    resultados = {}

    # --- Probar con alfa_default=0.10 (segun doc) y alfa_default=0.15 (segun DB global)
    for alfa_def in (0.10, 0.15):
        beta_sot, alfa_ema, coef_corner, def_beta, def_alfa, def_corner = cargar_params(alfa_default=alfa_def)
        # NO sobreescribir alfa_ema per liga, solo el default global
        # alfa_ema['global'] esta poppeado en alfa_default

        # Motor V0 a varios theta
        v0_grid = {}
        for theta in (0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.00):
            out = computar_rmse_motor_v0(
                eventos, theta, beta_sot, alfa_ema, coef_corner,
                def_beta, def_alfa, def_corner
            )
            v0_grid[f'{theta:.2f}'] = out

        # V5 NNLS a varios theta
        v5_grid = {}
        for theta in (0.10, 0.15, 0.20, 0.30, 0.50, 0.70):
            out = computar_rmse_v5_nnls(
                eventos, theta, intercept=0.273, beta_sot_v5=0.247,
                alfa_ema=alfa_ema, def_alfa=def_alfa
            )
            v5_grid[f'{theta:.2f}'] = out

        resultados[f'alfa_default_{alfa_def}'] = {
            'V0_motor': v0_grid,
            'V5_NNLS': v5_grid,
        }

        # Reporte CONSOLA
        print(f'\n--- alfa_default = {alfa_def} ---')
        print(f'{"theta":>6} | {"OOS_pool":>10} | {"IS_2026":>10} | {"2022":>8} | {"2023":>8} | {"2024":>8} | {"2025":>8}')
        for tag, grid in (('V0', v0_grid), ('V5', v5_grid)):
            print(f'  {tag} motor:')
            for theta_str, out in grid.items():
                pool = out['OOS_pool']['rmse']
                is26 = out['IS_2026']['rmse']
                y22 = out.get('2022', {}).get('rmse')
                y23 = out.get('2023', {}).get('rmse')
                y24 = out.get('2024', {}).get('rmse')
                y25 = out.get('2025', {}).get('rmse')
                fmt = lambda v: f'{v:.4f}' if v is not None else '   None'
                print(f'   {theta_str:>5} | {fmt(pool):>10} | {fmt(is26):>10} | {fmt(y22):>8} | {fmt(y23):>8} | {fmt(y24):>8} | {fmt(y25):>8}')

    # --- Validar replicacion contra doc
    print('\n=== VALIDACION REPLICA (esperado del doc) ===')
    esperado = {
        '0.10': {'OOS_pool': 1.1885, 'IS_2026': 1.1730},
        '0.15': {'OOS_pool': 1.1868, 'IS_2026': 1.1956},
        '0.20': {'OOS_pool': 1.1880, 'IS_2026': 1.1665},
        '0.70': {'OOS_pool': 1.2890, 'IS_2026': 1.2583},
        '1.00': {'OOS_pool': 1.4143, 'IS_2026': 1.3832},
    }
    print(f'{"theta":>6} | {"alfa_def":>8} | {"OOS exp":>8} | {"OOS real":>9} | {"diff":>7} | {"IS exp":>7} | {"IS real":>8} | {"diff":>7}')
    best_alfa = None
    best_total_err = float('inf')
    for alfa_def in (0.10, 0.15):
        v0 = resultados[f'alfa_default_{alfa_def}']['V0_motor']
        total_err = 0.0
        for theta_str, exp in esperado.items():
            real_oos = v0[theta_str]['OOS_pool']['rmse']
            real_is = v0[theta_str]['IS_2026']['rmse']
            d_oos = real_oos - exp['OOS_pool'] if real_oos else 0
            d_is = real_is - exp['IS_2026'] if real_is else 0
            total_err += abs(d_oos) + abs(d_is)
            print(f'  {theta_str:>5} | {alfa_def:>8} | {exp["OOS_pool"]:>8.4f} | {real_oos:>9.4f} | {d_oos:>+7.4f} | {exp["IS_2026"]:>7.4f} | {real_is:>8.4f} | {d_is:>+7.4f}')
        if total_err < best_total_err:
            best_total_err = total_err
            best_alfa = alfa_def
    print(f'\nMejor alfa_default = {best_alfa} (err total acumulado = {best_total_err:.4f})')

    # --- Guardar JSON
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    resultados['_meta'] = {
        'N_partidos': len(partidos),
        'N_eventos': len(eventos),
        'WARMUP': WARMUP,
        'mejor_alfa_default': best_alfa,
        'err_replica_acumulado': best_total_err,
    }
    with open(OUT_JSON, 'w') as f:
        json.dump(resultados, f, indent=2)
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

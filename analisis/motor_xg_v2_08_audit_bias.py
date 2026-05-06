"""
AUDIT BIAS - goles reales vs xG predicho forward-EMA.

Objetivo: detectar sub/sobre-estimaciones sistematicas por (liga, anio, equipo).
Si encontramos patrones consistentes -> aplicar correccion bias por bucket.

Estructura:
  Para cada evento (equipo, partido_t):
    pred = EMA forward de xg_final hasta antes del partido t
    real = goles_t
    residuo = real - pred  (positivo = modelo SUBESTIMA, negativo = SOBRESTIMA)

  Agregamos:
    A) Por liga: mean residuo, std residuo, N
    B) Por liga x anio: detectar drift temporal
    C) Por equipo (top N por participacion): equipos con bias persistente
    D) Magnitud del bias: si |bias| > 0.10 goles -> correccion vale la pena
"""

import sqlite3
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path
import numpy as np

DB = 'fondo_quant.db'
WARMUP = 5
OUT_JSON = 'analisis/motor_xg_v2_08_audit_bias.json'


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
        eventos.append({'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
                         'sot': hst or 0, 'shots_off': max(0, (hs or 0) - (hst or 0)),
                         'corners': hc or 0, 'goles': hg, 'es_local': True})
        eventos.append({'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
                         'sot': ast or 0, 'shots_off': max(0, (as_v or 0) - (ast or 0)),
                         'corners': ac or 0, 'goles': ag, 'es_local': False})
    return eventos


def cargar_params():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    beta_sot = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    DEFAULT_BETA = beta_sot.pop('global', 0.352)
    alfa_ema = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND tipo='float'"):
        alfa_ema[r[0]] = float(r[1])
    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None:
            coef_corner[r[0]] = float(r[1])
    con.close()
    return beta_sot, alfa_ema, coef_corner, DEFAULT_BETA


def computar_residuos(eventos, theta=0.20, alfa_default=0.10, modelo='V5_NNLS'):
    """
    Devuelve list de dicts {fecha, liga, equipo, rival, es_local, anio,
                            pred (EMA pre-partido), real (goles), residuo (real-pred)}.
    Solo eventos post-WARMUP.
    """
    beta_sot, alfa_ema, coef_corner, DEFAULT_BETA = cargar_params()
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    residuos = []
    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])

    for ev in eventos_sorted:
        liga = ev['liga']
        beta = beta_sot.get(liga, DEFAULT_BETA)
        coef_c = coef_corner.get(liga, 0.03)
        alfa = alfa_ema.get(liga, alfa_default)

        if modelo == 'V5_NNLS':
            xg_calc = 0.273 + 0.247 * ev['sot']
        elif modelo == 'V0_motor':
            xg_calc = beta * ev['sot'] + 0.010 * ev['shots_off'] + coef_c * ev['corners']
        else:
            raise ValueError(f'Unknown modelo {modelo}')

        xg_final = theta * xg_calc + (1.0 - theta) * ev['goles']

        s = state[ev['equipo']]
        if s['ema'] is not None and s['n'] >= WARMUP:
            residuos.append({
                'fecha': ev['fecha'],
                'liga': liga,
                'equipo': ev['equipo'],
                'rival': ev['rival'],
                'es_local': ev['es_local'],
                'anio': ev['fecha'][:4],
                'pred': s['ema'],
                'real': ev['goles'],
                'residuo': ev['goles'] - s['ema'],
            })

        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = alfa * xg_final + (1.0 - alfa) * s['ema']
        s['n'] += 1

    return residuos


def stats_grupo(rows):
    if not rows:
        return None
    arr = np.array([r['residuo'] for r in rows])
    return {
        'n': len(arr),
        'mean': float(arr.mean()),
        'std': float(arr.std()),
        'rmse': float(sqrt((arr**2).mean())),
        'pct_subestima': float((arr > 0).mean()),  # % que real > pred
    }


def main():
    print('=== AUDIT BIAS goles vs xG predicho forward-EMA ===\n')
    print('Modelo de referencia: V5_NNLS (intercept=0.273, beta_SOT=0.247, theta=0.20)\n')

    partidos = cargar_partidos()
    eventos = construir_eventos(partidos)
    residuos = computar_residuos(eventos, theta=0.20, modelo='V5_NNLS')
    print(f'Eventos post-warmup: {len(residuos)}\n')

    # Resumen global
    glob = stats_grupo(residuos)
    print(f'GLOBAL: n={glob["n"]}, mean(residuo)={glob["mean"]:+.4f}, std={glob["std"]:.4f}')
    print(f'        RMSE={glob["rmse"]:.4f}, pct_subestima={100*glob["pct_subestima"]:.1f}%\n')

    if abs(glob['mean']) > 0.05:
        print(f'>>> SESGO GLOBAL DETECTADO: {glob["mean"]:+.4f} goles. Modelo {("SUBESTIMA" if glob["mean"]>0 else "SOBREESTIMA")} sistematicamente.\n')
    else:
        print('>>> Sin sesgo global. Pero puede haber sesgos por subgrupo.\n')

    # A) Por liga
    print('--- A) Por liga ---')
    print(f'{"liga":<14} {"n":>6} {"mean_res":>10} {"std":>7} {"rmse":>7} {"sub%":>6} {"flag":>10}')
    by_liga = defaultdict(list)
    for r in residuos:
        by_liga[r['liga']].append(r)
    by_liga_stats = {}
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        s = stats_grupo(by_liga[liga])
        flag = ''
        if abs(s['mean']) > 0.10:
            flag = '** BIAS' if s['mean'] > 0 else '** OVER'
        elif abs(s['mean']) > 0.05:
            flag = '? leve'
        print(f'{liga:<14} {s["n"]:>6} {s["mean"]:>+10.4f} {s["std"]:>7.4f} {s["rmse"]:>7.4f} {100*s["pct_subestima"]:>5.1f}% {flag:>10}')
        by_liga_stats[liga] = s

    # B) Por liga x anio
    print('\n--- B) Por liga x anio (deteccion drift temporal) ---')
    by_liga_anio = defaultdict(list)
    for r in residuos:
        by_liga_anio[(r['liga'], r['anio'])].append(r)

    print(f'{"liga":<14} {"anio":>4} {"n":>6} {"mean_res":>10} {"flag":>10}')
    by_la_stats = {}
    drift_detectado = []
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l]))[:10]:  # top 10 ligas
        for anio in ('2022','2023','2024','2025','2026'):
            grp = by_liga_anio.get((liga, anio), [])
            if len(grp) < 30:
                continue
            s = stats_grupo(grp)
            flag = ''
            if abs(s['mean']) > 0.15:
                flag = '*** DRIFT' if s['mean'] > 0 else '*** OVER'
                drift_detectado.append({'liga': liga, 'anio': anio, 'mean_res': s['mean'], 'n': s['n']})
            elif abs(s['mean']) > 0.10:
                flag = '** leve'
            print(f'{liga:<14} {anio:>4} {s["n"]:>6} {s["mean"]:>+10.4f} {flag:>10}')
            by_la_stats[f'{liga}_{anio}'] = s

    # C) Por equipo (top N por participacion)
    print('\n--- C) Por equipo (top 30 con bias > 0.20 goles) ---')
    by_equipo = defaultdict(list)
    for r in residuos:
        by_equipo[(r['liga'], r['equipo'])].append(r)

    eq_stats = []
    for (liga, equipo), rows in by_equipo.items():
        if len(rows) < 30:
            continue
        s = stats_grupo(rows)
        if abs(s['mean']) >= 0.20:
            eq_stats.append({'liga': liga, 'equipo': equipo, **s})

    eq_stats.sort(key=lambda x: x['mean'], reverse=True)
    print(f'{"liga":<14} {"equipo":<25} {"n":>5} {"mean_res":>10} {"std":>7} {"recomendacion":<30}')
    inflar = []
    desinflar = []
    for e in eq_stats[:15]:  # top 15 sub
        rec = f'INFLAR xG +{e["mean"]:.2f}' if e['mean'] > 0.20 else 'OK'
        if e['mean'] >= 0.20:
            inflar.append(e)
        print(f'{e["liga"]:<14} {e["equipo"]:<25} {e["n"]:>5} {e["mean"]:>+10.4f} {e["std"]:>7.4f} {rec:<30}')

    print(f'\n{"liga":<14} {"equipo":<25} {"n":>5} {"mean_res":>10} {"std":>7} {"recomendacion":<30}')
    for e in eq_stats[-15:]:  # bottom 15 over
        rec = f'DESINFLAR xG {e["mean"]:.2f}' if e['mean'] < -0.20 else 'OK'
        if e['mean'] <= -0.20:
            desinflar.append(e)
        print(f'{e["liga"]:<14} {e["equipo"]:<25} {e["n"]:>5} {e["mean"]:>+10.4f} {e["std"]:>7.4f} {rec:<30}')

    print(f'\n>>> Equipos con bias sistematico (|mean|>=0.20, N>=30):')
    print(f'    INFLAR  (modelo subestima): {len(inflar)} equipos')
    print(f'    DESINFLAR (modelo sobreestima): {len(desinflar)} equipos')

    # D) Test de impacto: si aplicamos correccion equipo-especifica, cuanto baja RMSE?
    print('\n--- D) Test impacto: correccion bias equipo-especifica ---')
    # Aplicar correccion = pred_corregido = pred + mean_residuo_equipo
    # Re-computar RMSE con correccion
    correccion_por_equipo = {}
    for (liga, equipo), rows in by_equipo.items():
        if len(rows) >= 30:
            arr = np.array([r['residuo'] for r in rows])
            correccion_por_equipo[(liga, equipo)] = float(arr.mean())

    # IN-SAMPLE (full data) - SOLO referencia, NO predictivo
    errs_orig = np.array([r['residuo'] for r in residuos])
    errs_corr = []
    for r in residuos:
        c = correccion_por_equipo.get((r['liga'], r['equipo']), 0)
        errs_corr.append(r['residuo'] - c)
    errs_corr = np.array(errs_corr)
    print(f'  IS RMSE original: {sqrt((errs_orig**2).mean()):.4f}')
    print(f'  IS RMSE corregido (in-sample): {sqrt((errs_corr**2).mean()):.4f}')
    print('  NOTA: in-sample, esta correccion siempre baja el RMSE (overfit).')
    print('        El test honesto es: train correcciones < 2026, eval 2026.\n')

    # WALK-FORWARD: train correcciones con eventos < 2026, eval 2026
    by_eq_train = defaultdict(list)
    for r in residuos:
        if r['anio'] != '2026':
            by_eq_train[(r['liga'], r['equipo'])].append(r)

    correccion_train = {}
    for k, rows in by_eq_train.items():
        if len(rows) >= 30:
            arr = np.array([rr['residuo'] for rr in rows])
            correccion_train[k] = float(arr.mean())

    res_2026 = [r for r in residuos if r['anio'] == '2026']
    errs_2026_orig = np.array([r['residuo'] for r in res_2026])
    errs_2026_corr = []
    for r in res_2026:
        c = correccion_train.get((r['liga'], r['equipo']), 0)
        errs_2026_corr.append(r['residuo'] - c)
    errs_2026_corr = np.array(errs_2026_corr)
    rmse_orig = sqrt((errs_2026_orig**2).mean()) if len(errs_2026_orig) else None
    rmse_corr = sqrt((errs_2026_corr**2).mean()) if len(errs_2026_corr) else None
    print(f'  WALK-FORWARD test 2026 (train_correccion < 2026):')
    print(f'    N=2026: {len(res_2026)}')
    print(f'    RMSE original: {rmse_orig:.4f}')
    print(f'    RMSE con correccion equipo-especifica: {rmse_corr:.4f}')
    if rmse_orig and rmse_corr:
        delta_pct = 100 * (rmse_corr - rmse_orig) / rmse_orig
        print(f'    Delta: {(rmse_corr-rmse_orig):+.4f} ({delta_pct:+.2f}%)')
        if rmse_corr < rmse_orig:
            print(f'    >>> CORRECCION VALIDA (mejora OOS)')
        else:
            print(f'    >>> CORRECCION OVERFIT (no transfiere a 2026)')

    # Save
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'modelo_referencia': 'V5_NNLS theta=0.20',
            'n_eventos': len(residuos),
            'global': glob,
            'por_liga': by_liga_stats,
            'por_liga_anio': by_la_stats,
            'equipos_inflar': inflar,
            'equipos_desinflar': desinflar,
            'drift_detectado': drift_detectado,
            'walk_forward_test': {
                'n_2026': len(res_2026),
                'rmse_orig_2026': rmse_orig,
                'rmse_corregido_2026': rmse_corr,
                'mejora_OOS': bool(rmse_corr and rmse_orig and rmse_corr < rmse_orig),
            }
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

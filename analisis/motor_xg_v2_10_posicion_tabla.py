"""
FASE 9 - Posicion tabla como feature pre-match no-Poisson.

Tabla disponible: posiciones_tabla_snapshot (32,394 filas).
Cobertura: 16 ligas excepto Noruega (86 - excluir) y copas (tiny).

Tests:
  A) Descriptivo: goles promedio por (bin_posicion, es_local).
  B) Ablation NNLS: BASE_sot + (posicion_norm, dif_pos) -> RMSE forward-EMA.
  C) Walk-forward: train_correccion_bias_por_bin_pos < year_test, eval == year_test.
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
OUT_JSON = 'analisis/motor_xg_v2_10_posicion_tabla.json'


def cargar_snapshots():
    """Devuelve dict (liga, equipo) -> list de (fecha, posicion, n_equipos_liga, puntos, dif_gol)
    ordenado por fecha. n_equipos_liga calculado por (liga, temp, formato, fecha)."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # N equipos por (liga, temp, formato, fecha)
    n_eq_by_snap = {}
    for r in cur.execute('''
        SELECT liga, temp, formato, fecha_snapshot, COUNT(DISTINCT equipo)
        FROM posiciones_tabla_snapshot
        GROUP BY liga, temp, formato, fecha_snapshot
    ''').fetchall():
        liga, temp, fmt, fecha, n_eq = r
        n_eq_by_snap[(liga, temp, fmt, fecha)] = n_eq

    # Cargar snapshots
    snap_by_eq = defaultdict(list)  # (liga, equipo) -> [(fecha, formato, posicion, n_eq, puntos, dif_gol)]
    for r in cur.execute('''
        SELECT liga, temp, formato, fecha_snapshot, equipo, posicion, puntos, dif_gol
        FROM posiciones_tabla_snapshot
        WHERE liga NOT IN ('Sudamericana', 'Libertadores', 'Champions League', 'Conference League', 'Europa League', 'Copa Argentina')
        ORDER BY equipo, fecha_snapshot
    ''').fetchall():
        liga, temp, fmt, fecha, equipo, pos, ptos, dif = r
        n_eq = n_eq_by_snap.get((liga, temp, fmt, fecha), 20)
        snap_by_eq[(liga, equipo)].append({
            'fecha': fecha, 'formato': fmt, 'posicion': pos,
            'n_equipos': n_eq, 'puntos': ptos, 'dif_gol': dif,
        })
    con.close()
    return snap_by_eq


def get_pos_pre_partido(snap_by_eq, liga, equipo, fecha_partido, formato_default='liga'):
    """Devuelve el snapshot mas reciente pre-fecha_partido para (liga, equipo).
    None si no hay datos."""
    snaps = snap_by_eq.get((liga, equipo), [])
    if not snaps:
        return None
    # Filtrar pre-fecha y formato
    # Si Argentina con formatos apertura/clausura/anual, usar 'liga' como fallback
    candidates = [s for s in snaps if s['fecha'] < fecha_partido and s['formato'] in ('liga', 'anual')]
    if not candidates:
        # Fallback a cualquier formato
        candidates = [s for s in snaps if s['fecha'] < fecha_partido]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s['fecha'])


def cargar_partidos():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND liga NOT IN ('Noruega')  -- Cobertura tabla insuficiente
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    return rows


def construir_eventos(partidos, snap_by_eq):
    eventos = []
    skipped = 0
    for r in partidos:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac = r
        # Pos pre-partido
        pos_l = get_pos_pre_partido(snap_by_eq, liga, ht, fecha)
        pos_v = get_pos_pre_partido(snap_by_eq, liga, at, fecha)
        if pos_l is None or pos_v is None:
            skipped += 1
            continue

        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': ht, 'rival': at,
            'sot': hst or 0, 'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0, 'goles': hg, 'es_local': 1.0,
            'pos_propia': pos_l['posicion'], 'pos_rival': pos_v['posicion'],
            'pos_norm_propia': pos_l['posicion'] / pos_l['n_equipos'],
            'pos_norm_rival': pos_v['posicion'] / pos_v['n_equipos'],
            'dif_pos': pos_v['posicion'] - pos_l['posicion'],  # rival - propio (negativo si rival es mejor)
            'puntos_propio': pos_l['puntos'] or 0,
            'puntos_rival': pos_v['puntos'] or 0,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': at, 'rival': ht,
            'sot': ast or 0, 'shots_off': max(0, (as_v or 0) - (ast or 0)),
            'corners': ac or 0, 'goles': ag, 'es_local': 0.0,
            'pos_propia': pos_v['posicion'], 'pos_rival': pos_l['posicion'],
            'pos_norm_propia': pos_v['posicion'] / pos_v['n_equipos'],
            'pos_norm_rival': pos_l['posicion'] / pos_l['n_equipos'],
            'dif_pos': pos_l['posicion'] - pos_v['posicion'],
            'puntos_propio': pos_v['puntos'] or 0,
            'puntos_rival': pos_l['puntos'] or 0,
        })
    print(f'Skipped {skipped} partidos sin snapshot tabla pre-fecha')
    return eventos


def analisis_descriptivo(eventos):
    """Goles promedio por bin de posicion + es_local."""
    print('\n=== A) DESCRIPTIVO: goles por bin posicion x es_local ===')
    print(f'{"bin_pos":<10} {"es_local":>10} {"n":>6} {"avg_goles":>10} {"avg_sot":>10}')

    by_bin = defaultdict(list)
    for e in eventos:
        # Bin: top3, mid, bottom3
        rank = e['pos_norm_propia']
        if rank <= 0.20:
            b = 'top20%'
        elif rank >= 0.80:
            b = 'bot20%'
        elif rank <= 0.40:
            b = 'top21-40'
        elif rank >= 0.60:
            b = 'bot21-40'
        else:
            b = 'mid'
        by_bin[(b, int(e['es_local']))].append(e)

    bins_orden = ['top20%', 'top21-40', 'mid', 'bot21-40', 'bot20%']
    for b in bins_orden:
        for el in (1, 0):
            grp = by_bin.get((b, el), [])
            if not grp:
                continue
            avg_g = np.mean([e['goles'] for e in grp])
            avg_sot = np.mean([e['sot'] for e in grp])
            print(f'{b:<10} {("local" if el else "visita"):>10} {len(grp):>6d} {avg_g:>10.4f} {avg_sot:>10.4f}')

    # Diferenciales
    print('\n  Patrones key:')
    top_local = np.mean([e['goles'] for e in by_bin.get(('top20%', 1), [])])
    bot_local = np.mean([e['goles'] for e in by_bin.get(('bot20%', 1), [])])
    print(f'    top20% local: {top_local:.3f} goles vs bot20% local: {bot_local:.3f} | diff: {top_local-bot_local:+.3f}')
    top_visita = np.mean([e['goles'] for e in by_bin.get(('top20%', 0), [])])
    bot_visita = np.mean([e['goles'] for e in by_bin.get(('bot20%', 0), [])])
    print(f'    top20% visita: {top_visita:.3f} goles vs bot20% visita: {bot_visita:.3f} | diff: {top_visita-bot_visita:+.3f}')


def fit_nnls(eventos_train, fnames):
    X, y = [], []
    for ev in eventos_train:
        row = [1.0]
        skip = False
        for fn in fnames:
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


def aplicar_y_eval(eventos, fnames, coefs, theta=0.20, alfa=0.10):
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs_by_year = defaultdict(list)
    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])
    for ev in eventos_sorted:
        xg_calc = coefs[0]
        skip = False
        for i, fn in enumerate(fnames):
            v = ev.get(fn)
            if v is None:
                skip = True
                break
            xg_calc += coefs[i + 1] * float(v)
        if skip:
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
    print('=== FASE 9: POSICION TABLA COMO FEATURE PRE-MATCH ===\n')
    print('Cargando snapshots tabla...')
    snap_by_eq = cargar_snapshots()
    print(f'(liga, equipo) con snapshots: {len(snap_by_eq)}\n')

    partidos = cargar_partidos()
    print(f'Partidos cargados (excl Noruega): {len(partidos)}')
    eventos = construir_eventos(partidos, snap_by_eq)
    print(f'Eventos con pos tabla disponible: {len(eventos)}\n')

    # A) Descriptivo
    analisis_descriptivo(eventos)

    # B) Ablation NNLS
    print('\n=== B) ABLATION NNLS sobre eventos con pos tabla ===')
    eventos_train = [e for e in eventos if e['fecha'][:4] < '2026']
    print(f'Eventos train (<2026): {len(eventos_train)}\n')

    suite = {
        'BASE_sot': ['sot'],
        'BASE_sot_pos_norm_propia': ['sot', 'pos_norm_propia'],
        'BASE_sot_pos_norm_rival': ['sot', 'pos_norm_rival'],
        'BASE_sot_pos_diff': ['sot', 'pos_norm_propia', 'pos_norm_rival'],
        'BASE_sot_dif_pos': ['sot', 'dif_pos'],
        'BASE_sot_es_local_dif_pos': ['sot', 'es_local', 'dif_pos'],
        'BASE_sot_puntos': ['sot', 'puntos_propio', 'puntos_rival'],
        'PURE_dif_pos_es_local': ['es_local', 'dif_pos'],
        'FULL_pos_features': ['sot', 'es_local', 'pos_norm_propia', 'pos_norm_rival', 'puntos_propio', 'puntos_rival'],
    }

    print(f'{"Modelo":<32s} | {"OOS":>8s} {"IS_26":>8s} {"d_BASE":>8s}')
    rmse_base = None
    results = {}
    for tag, fnames in suite.items():
        sol, ntr = fit_nnls(eventos_train, fnames)
        m = aplicar_y_eval(eventos, fnames, sol)
        pool = m['OOS_pool']['rmse']
        is26 = m['IS_2026']['rmse']
        if tag == 'BASE_sot':
            rmse_base = pool
        delta = pool - rmse_base if rmse_base else 0
        flag = '*' if delta < -0.005 else ' '
        is26_str = f'{is26:.4f}' if is26 else 'N/A'
        coefs_str = ' '.join(f'{c:+.3f}' for c in sol)
        print(f'[{flag}] {tag:<30s}| {pool:>8.4f} {is26_str:>8s} {delta:>+8.4f}  coefs=[{coefs_str}]')
        results[tag] = {
            'features': fnames, 'coefs': sol.tolist(),
            'metrics': m, 'delta_vs_base': delta,
        }

    # C) Walk-forward
    print('\n=== C) WALK-FORWARD: best model con pos features ===')
    best_tag = min(
        [(tag, r['metrics']['OOS_pool']['rmse']) for tag, r in results.items() if r['metrics']['OOS_pool']['rmse']],
        key=lambda x: x[1]
    )[0]
    print(f'Best model: {best_tag}')
    best_fnames = results[best_tag]['features']
    print(f'Features: {best_fnames}\n')

    print(f'{"year_test":<10} {"N":>6} {"RMSE":>8} {"flag":<10}')
    wf_results = {}
    for year_test in ('2023', '2024', '2025', '2026'):
        train = [e for e in eventos if e['fecha'][:4] < year_test]
        test = [e for e in eventos if e['fecha'][:4] == year_test]
        if not train or not test:
            continue
        sol, ntr = fit_nnls(train, best_fnames)

        # Eval over only test events (re-run aplicar with EMA build but only collect errs for year_test)
        state = defaultdict(lambda: {'ema': None, 'n': 0})
        errs_test = []
        eventos_full_sorted = sorted(eventos, key=lambda e: e['fecha'])
        for ev in eventos_full_sorted:
            xg_calc = sol[0]
            skip = False
            for i, fn in enumerate(best_fnames):
                v = ev.get(fn)
                if v is None:
                    skip = True
                    break
                xg_calc += sol[i + 1] * float(v)
            if skip:
                continue
            xg_calc = max(0, xg_calc)
            xg_final = 0.20 * xg_calc + 0.80 * ev['goles']
            s = state[ev['equipo']]
            if s['ema'] is not None and s['n'] >= WARMUP and ev['fecha'][:4] == year_test:
                errs_test.append(s['ema'] - ev['goles'])
            if s['ema'] is None:
                s['ema'] = xg_final
            else:
                s['ema'] = 0.10 * xg_final + 0.90 * s['ema']
            s['n'] += 1

        rmse = sqrt(sum(e * e for e in errs_test) / len(errs_test)) if errs_test else None
        flag = ''
        rmse_str = f'{rmse:.4f}' if rmse else 'N/A'
        print(f'{year_test:<10} {len(errs_test):>6} {rmse_str:>8s} {flag:<10}')
        wf_results[year_test] = {'n': len(errs_test), 'rmse': rmse}

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'n_eventos': len(eventos),
            'descriptivo': 'ver consola',
            'ablation': results,
            'walk_forward': wf_results,
            'best_tag': best_tag,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

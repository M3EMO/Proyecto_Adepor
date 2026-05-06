"""
Análisis empírico: xG SOFA directo vs xG custom (motor_xg_v2_14 LogReg).

Hipótesis: SOFA expone xg + xgot POR SHOT. Sumar xg shots por equipo podría dar
xG model superior al nuestro LogReg N=19,660. SOFA entrena con N enorme cross-liga.

Comparar 3 modelos:
  V_custom: motor_xg_v2_14 LogReg sobre coords + situation + body (ya en xg_shotmap_l/v)
  V_sofa_xg: sum(shot.xg) por equipo del partido
  V_sofa_xgot: sum(shot.xgot) por equipo (xG on target solamente)

Métricas:
  - RMSE vs goles reales (point estimate, sin EMA)
  - Calibración: ratio sum(xG)/sum(goals) (debe ser ~1.0)
  - Correlación xG vs goles
  - Brier 1X2 sobre Poisson DC con cada modelo
  - RMSE forward-EMA usando cada modelo

Si V_sofa_xg gana → reemplazar motor_xg_v2_14 con SOFA xg directo.
"""
import sqlite3, json, math
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')
OUT_JSON = str(ROOT / 'analisis' / 'xg_v3_sofa_vs_custom_comparativa.json')


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar partidos con shotmap
    rows = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               xg_shotmap_l, xg_shotmap_v, shotmap_json
        FROM sofascore_match_features
        WHERE error IS NULL AND shotmap_json IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND xg_shotmap_l IS NOT NULL
        ORDER BY fecha ASC
    ''').fetchall()
    print(f'Partidos con shotmap + xG custom: {len(rows)}')

    # Extraer 3 versiones de xG por partido
    data = []
    for r in rows:
        sofa_id, liga, fecha, ht, at, hg, ag, xg_custom_l, xg_custom_v, sm_json = r
        try:
            sm = json.loads(sm_json)
        except (TypeError, json.JSONDecodeError):
            continue
        shots = sm.get('shotmap', [])
        if not shots:
            continue

        # V_sofa_xg: sum xg directo
        xg_sofa_l = sum((s.get('xg') or 0) for s in shots if s.get('isHome'))
        xg_sofa_v = sum((s.get('xg') or 0) for s in shots if not s.get('isHome'))

        # V_sofa_xgot: sum xgot
        xgot_l = sum((s.get('xgot') or 0) for s in shots if s.get('isHome'))
        xgot_v = sum((s.get('xgot') or 0) for s in shots if not s.get('isHome'))

        # Verificar si shots tienen xg field populated
        n_with_xg = sum(1 for s in shots if s.get('xg') is not None)
        n_total = len(shots)
        pct_xg_pop = n_with_xg / n_total if n_total > 0 else 0

        data.append({
            'liga': liga, 'fecha': fecha,
            'hg': hg, 'ag': ag,
            'xg_custom_l': xg_custom_l, 'xg_custom_v': xg_custom_v,
            'xg_sofa_l': xg_sofa_l, 'xg_sofa_v': xg_sofa_v,
            'xgot_l': xgot_l, 'xgot_v': xgot_v,
            'n_shots_total': n_total, 'pct_xg_pop': pct_xg_pop,
        })

    print(f'Eventos: {len(data)}')

    # Cobertura xg field SOFA
    avg_pct = np.mean([d['pct_xg_pop'] for d in data])
    print(f'Cobertura xg field per shot: {avg_pct*100:.1f}%')

    # ============ COMPARACIÓN POINT ESTIMATE ============
    print('\n=== POINT ESTIMATE (sin EMA, partido individual) ===')
    print(f'{"Modelo":<14s} {"sum_xG":>10s} {"sum_goals":>10s} {"ratio":>7s} {"RMSE":>7s} {"corr":>7s}')

    versiones = ['custom', 'sofa', 'xgot']
    for ver in versiones:
        all_xg = []
        all_g = []
        for d in data:
            for side in ('l', 'v'):
                if ver == 'custom':
                    xg = d[f'xg_custom_{side}']
                elif ver == 'sofa':
                    xg = d[f'xg_sofa_{side}']
                elif ver == 'xgot':
                    xg = d[f'xgot_{side}']
                g = d[f'h{"g" if side=="l" else ""}'] if side == 'l' else d['ag']
                if xg is not None:
                    all_xg.append(xg)
                    all_g.append(g)
        all_xg = np.array(all_xg)
        all_g = np.array(all_g)
        sum_xg = all_xg.sum()
        sum_g = all_g.sum()
        ratio = sum_xg / max(sum_g, 1)
        rmse = math.sqrt(np.mean((all_xg - all_g) ** 2))
        corr = np.corrcoef(all_xg, all_g)[0, 1]
        print(f'V_{ver:<12s} {sum_xg:>10.1f} {sum_g:>10d} {ratio:>7.3f} {rmse:>7.4f} {corr:>+7.4f}')

    # ============ FORWARD-EMA RMSE ============
    print('\n=== RMSE FORWARD-EMA (predict goles próximo partido del equipo) ===')
    print(f'{"Modelo":<14s} {"N_eventos":>10s} {"RMSE":>8s}')

    ALFA = 0.10
    WARMUP = 5

    for ver in versiones:
        # Construir eventos por equipo cronológicamente
        eventos = []
        for d in data:
            for side, equipo, goles in [('l', d['liga'] + '|' + 'home_proxy', d['hg']),
                                          ('v', d['liga'] + '|' + 'away_proxy', d['ag'])]:
                # Necesitamos identificar equipo realmente. Usar (liga, fecha, side) tag es proxy malo.
                # Mejor: cargar ht/at de la query original
                pass
        # Re-cargar con ht/at
        eventos = []
        for d in data:
            for side, equipo, goles in [('l', None, d['hg']), ('v', None, d['ag'])]:
                if ver == 'custom':
                    xg = d[f'xg_custom_{side}']
                elif ver == 'sofa':
                    xg = d[f'xg_sofa_{side}']
                elif ver == 'xgot':
                    xg = d[f'xgot_{side}']
                eventos.append({'fecha': d['fecha'], 'liga': d['liga'], 'side': side, 'xg': xg, 'g': goles})
        # Necesitamos ht/at — re-query
        eventos = []
        for r2 in rows:
            sofa_id, liga, fecha, ht, at, hg, ag, xg_c_l, xg_c_v, sm_json = r2
            try:
                sm = json.loads(sm_json)
            except:
                continue
            shots = sm.get('shotmap', [])
            if not shots:
                continue
            if ver == 'custom':
                xg_l = xg_c_l
                xg_v = xg_c_v
            elif ver == 'sofa':
                xg_l = sum((s.get('xg') or 0) for s in shots if s.get('isHome'))
                xg_v = sum((s.get('xg') or 0) for s in shots if not s.get('isHome'))
            elif ver == 'xgot':
                xg_l = sum((s.get('xgot') or 0) for s in shots if s.get('isHome'))
                xg_v = sum((s.get('xgot') or 0) for s in shots if not s.get('isHome'))
            eventos.append({'fecha': fecha, 'equipo': ht, 'liga': liga, 'xg': xg_l, 'g': hg})
            eventos.append({'fecha': fecha, 'equipo': at, 'liga': liga, 'xg': xg_v, 'g': ag})

        # EMA forward-strict
        state = defaultdict(lambda: {'ema': None, 'n': 0})
        errs = []
        eventos.sort(key=lambda e: e['fecha'])
        for ev in eventos:
            xg = ev['xg']
            if xg is None:
                continue
            # Hibridado theta=0.20 (óptimo motor productivo)
            xg_final = 0.20 * xg + 0.80 * ev['g']
            s = state[(ev['liga'], ev['equipo'])]
            if s['ema'] is not None and s['n'] >= WARMUP:
                errs.append(s['ema'] - ev['g'])
            if s['ema'] is None:
                s['ema'] = xg_final
            else:
                s['ema'] = ALFA * xg_final + (1 - ALFA) * s['ema']
            s['n'] += 1

        if errs:
            rmse = math.sqrt(np.mean(np.array(errs) ** 2))
            print(f'V_{ver:<12s} {len(errs):>10d} {rmse:>8.4f}')

    # ============ Per liga ============
    print('\n=== POINT ESTIMATE per liga (RMSE goles vs xG) ===')
    print(f'{"Liga":<14s} {"N":>4s} {"V_custom":>9s} {"V_sofa":>9s} {"V_xgot":>9s}')
    by_liga = defaultdict(list)
    for d in data:
        by_liga[d['liga']].append(d)
    by_liga_results = {}
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        evs = by_liga[liga]
        if len(evs) < 10:
            continue
        rmses = {}
        for ver in versiones:
            errs = []
            for d in evs:
                for side in ('l', 'v'):
                    if ver == 'custom':
                        xg = d[f'xg_custom_{side}']
                    elif ver == 'sofa':
                        xg = d[f'xg_sofa_{side}']
                    elif ver == 'xgot':
                        xg = d[f'xgot_{side}']
                    g = d['hg'] if side == 'l' else d['ag']
                    if xg is not None:
                        errs.append(xg - g)
            rmses[ver] = math.sqrt(np.mean(np.array(errs) ** 2)) if errs else None
        print(f'{liga:<14s} {len(evs):>4d} {rmses["custom"]:>9.4f} {rmses["sofa"]:>9.4f} {rmses["xgot"]:>9.4f}')
        by_liga_results[liga] = rmses

    # ============ Save ============
    out = {
        'n_eventos_total': len(data),
        'pct_xg_field_populated': float(avg_pct),
        'by_liga_rmse': by_liga_results,
        'data_sample': data[:5],
    }
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')

    con.close()


if __name__ == '__main__':
    main()

"""
Exploración EXHAUSTIVA de features SOFA NO usadas todavía.

Pregunta: ¿hay otra stat SOFA con valor predictivo similar a xgot que pueda
aportar boost RMSE incremental sobre xg_v3?

Buscar en 3 fuentes:
  1. shotmap_json: fields per shot NO usados todavía
  2. statistics_json: stats partido por período
  3. lineups_json: per jugador (ratings, VAEP-like, keeper save value)

Para cada feature candidata:
  - Computar correlación con goles_real (point estimate)
  - RMSE incremental: V3 + feature como regresor lineal
  - Identificar top-10 features

Validación: si feature mejora RMSE > 0.05 sobre V3 → candidato V4.
"""
import sqlite3, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')
OUT_JSON = str(ROOT / 'analisis' / 'xg_v4_features_unused.json')


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar partidos con TODOS los JSONs
    rows = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               xg_v3_l, xg_v3_v, n_shots_shotmap,
               shotmap_json, statistics_json, lineups_json,
               -- Stats partido directos
               big_chances_l, big_chances_v,
               big_chances_missed_l, big_chances_missed_v,
               shots_inside_box_l, shots_inside_box_v,
               shots_outside_box_l, shots_outside_box_v,
               blocked_shots_l, blocked_shots_v,
               hit_woodwork_l, hit_woodwork_v,
               touches_penalty_area_l, touches_penalty_area_v,
               corners_l, corners_v,
               saves_l, saves_v,
               errors_lead_to_shot_l, errors_lead_to_shot_v,
               recoveries_l, recoveries_v,
               keeper_save_value_l, keeper_save_value_v,
               avg_rating_l, avg_rating_v,
               max_rating_l, max_rating_v,
               ball_possession_l, ball_possession_v,
               duels_pct_l, duels_pct_v,
               tackles_won_pct_l, tackles_won_pct_v
        FROM sofascore_match_features
        WHERE error IS NULL AND xg_v3_l IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY fecha
    ''').fetchall()
    print(f'Partidos: {len(rows)}')

    # Construir dataset eventos (1 partido = 2 eventos)
    eventos = []
    for r in rows:
        sofa_id = r[0]
        liga = r[1]
        fecha = r[2]
        hg, ag = r[5], r[6]
        xg_v3_l, xg_v3_v = r[7], r[8]
        n_shots = r[9]

        # Parse shotmap para shot-level features
        try:
            sm = json.loads(r[10]) if r[10] else None
        except:
            sm = None
        try:
            stats = json.loads(r[11]) if r[11] else None
        except:
            stats = None
        try:
            lineups = json.loads(r[12]) if r[12] else None
        except:
            lineups = None

        # Index columnas directas (SQL row order)
        col_map = {
            'big_chances': (13, 14),
            'big_chances_missed': (15, 16),
            'shots_inside_box': (17, 18),
            'shots_outside_box': (19, 20),
            'blocked_shots': (21, 22),
            'hit_woodwork': (23, 24),
            'touches_penalty_area': (25, 26),
            'corners': (27, 28),
            'saves': (29, 30),
            'errors_lead_to_shot': (31, 32),
            'recoveries': (33, 34),
            'keeper_save_value': (35, 36),
            'avg_rating': (37, 38),
            'max_rating': (39, 40),
            'ball_possession': (41, 42),
            'duels_pct': (43, 44),
            'tackles_won_pct': (45, 46),
        }

        # SHOT-LEVEL features extra (avg per shot)
        for side, is_home, goles, xg_v3_team in [(1, True, hg, xg_v3_l), (0, False, ag, xg_v3_v)]:
            f = {
                'liga': liga, 'fecha': fecha, 'goles': goles, 'xg_v3': xg_v3_team,
                'n_shots': 0,
            }
            # Direct cols
            for fld, (idx_l, idx_v) in col_map.items():
                f[fld] = r[idx_l] if is_home else r[idx_v]

            # Shotmap-derived NEW features
            if sm:
                shots = [s for s in sm.get('shotmap', []) if s.get('isHome') == is_home]
                f['n_shots'] = len(shots)
                if shots:
                    # Features POR shot
                    avg_xg_per_shot = np.mean([(s.get('xg') or 0) for s in shots])
                    avg_xgot_per_shot = np.mean([(s.get('xgot') or 0) for s in shots if s.get('xgot') is not None]) if any(s.get('xgot') is not None for s in shots) else 0
                    n_shots_assisted = sum(1 for s in shots if s.get('situation') == 'assisted')
                    n_shots_fast_break = sum(1 for s in shots if s.get('situation') == 'fast-break')
                    n_shots_penalty = sum(1 for s in shots if s.get('situation') == 'penalty')
                    n_shots_set_piece = sum(1 for s in shots if s.get('situation') in ('set-piece', 'free-kick', 'corner'))
                    n_shots_head = sum(1 for s in shots if s.get('bodyPart') == 'head')
                    n_shots_on_target = sum(1 for s in shots if s.get('shotType') == 'save')
                    n_shots_blocked = sum(1 for s in shots if s.get('shotType') == 'block')
                    n_shots_post = sum(1 for s in shots if s.get('shotType') == 'post')
                    # xG sum on target
                    xg_on_target = sum((s.get('xg') or 0) for s in shots if s.get('shotType') in ('goal', 'save'))
                    f['avg_xg_per_shot'] = avg_xg_per_shot
                    f['avg_xgot_per_shot'] = avg_xgot_per_shot
                    f['n_shots_assisted'] = n_shots_assisted
                    f['n_shots_fast_break'] = n_shots_fast_break
                    f['n_shots_penalty'] = n_shots_penalty
                    f['n_shots_set_piece'] = n_shots_set_piece
                    f['n_shots_head'] = n_shots_head
                    f['n_shots_on_target'] = n_shots_on_target
                    f['n_shots_blocked'] = n_shots_blocked
                    f['xg_on_target_sum'] = xg_on_target
                    # xG concentrado: % de xG en top-3 shots (calidad shooter)
                    xgs = sorted([(s.get('xg') or 0) for s in shots], reverse=True)
                    f['xg_top3_pct'] = sum(xgs[:3]) / sum(xgs) if sum(xgs) > 0 else 0
                    # Avg distance shots
                    dists = []
                    for s in shots:
                        pc = s.get('playerCoordinates') or {}
                        px = pc.get('x', 50)
                        py = pc.get('y', 50)
                        if px is not None and py is not None:
                            d = math.sqrt((px * 1.05) ** 2 + ((py - 50) * 0.68) ** 2)
                            dists.append(d)
                    f['avg_shot_distance_m'] = np.mean(dists) if dists else None

            # Lineup features extra
            if lineups:
                team_lineup = lineups.get('home' if is_home else 'away', {})
                players = team_lineup.get('players', [])
                if players:
                    # Sumas avanzadas (VAEP-like cuando disponibles)
                    sum_def_value = 0
                    sum_pass_value = 0
                    sum_dribble_value = 0
                    sum_keypass = 0
                    sum_goals_assist = 0
                    sum_total_pass = 0
                    sum_accurate_pass = 0
                    sum_progressive_carries = 0
                    sum_minutes = 0
                    n_starters = 0
                    for p in players:
                        pstats = p.get('statistics') or {}
                        if pstats.get('minutesPlayed', 0) > 0 and not p.get('substitute'):
                            n_starters += 1
                        try:
                            sum_def_value += float(pstats.get('defensiveValueNormalized') or 0)
                            sum_pass_value += float(pstats.get('passValueNormalized') or 0)
                            sum_dribble_value += float(pstats.get('dribbleValueNormalized') or 0)
                            sum_keypass += int(pstats.get('keyPass') or 0)
                            sum_goals_assist += int(pstats.get('goalAssist') or 0)
                            sum_total_pass += int(pstats.get('totalPass') or 0)
                            sum_accurate_pass += int(pstats.get('accuratePass') or 0)
                            sum_progressive_carries += int(pstats.get('progressiveBallCarriesCount') or 0)
                            sum_minutes += int(pstats.get('minutesPlayed') or 0)
                        except:
                            pass
                    f['sum_def_value_norm'] = sum_def_value
                    f['sum_pass_value_norm'] = sum_pass_value
                    f['sum_dribble_value_norm'] = sum_dribble_value
                    f['sum_keypass'] = sum_keypass
                    f['sum_goals_assist'] = sum_goals_assist
                    f['accurate_pass_pct'] = (sum_accurate_pass / sum_total_pass) if sum_total_pass > 0 else None
                    f['sum_progressive_carries'] = sum_progressive_carries
                    f['n_starters'] = n_starters

            eventos.append(f)

    print(f'Eventos: {len(eventos)}')

    # ============ Análisis univariado: corr con goles + RMSE incremental ============
    # Para cada feature, computar:
    # 1. Pearson corr con goles_real
    # 2. Mejora RMSE: ¿xg_v3 + alpha*feature reduce RMSE vs solo xg_v3?
    candidate_features = [
        # Stats partido
        'big_chances', 'big_chances_missed',
        'shots_inside_box', 'shots_outside_box',
        'blocked_shots', 'hit_woodwork', 'touches_penalty_area',
        'corners', 'saves', 'errors_lead_to_shot', 'recoveries',
        'keeper_save_value', 'avg_rating', 'max_rating',
        'ball_possession', 'duels_pct', 'tackles_won_pct',
        # Shotmap-derived
        'avg_xg_per_shot', 'avg_xgot_per_shot', 'xg_top3_pct',
        'avg_shot_distance_m', 'xg_on_target_sum',
        'n_shots_assisted', 'n_shots_fast_break', 'n_shots_penalty',
        'n_shots_set_piece', 'n_shots_head',
        'n_shots_on_target', 'n_shots_blocked',
        # Lineups
        'sum_def_value_norm', 'sum_pass_value_norm', 'sum_dribble_value_norm',
        'sum_keypass', 'sum_goals_assist',
        'accurate_pass_pct', 'sum_progressive_carries', 'n_starters',
    ]

    # Baseline: RMSE de xg_v3 solo
    valid = [e for e in eventos if e['xg_v3'] is not None]
    base_rmse = math.sqrt(np.mean([(e['xg_v3'] - e['goles']) ** 2 for e in valid]))
    base_corr = np.corrcoef(
        [e['xg_v3'] for e in valid], [e['goles'] for e in valid]
    )[0, 1]
    print(f'\nBASELINE V_v3: RMSE={base_rmse:.4f}, corr={base_corr:+.4f}, N={len(valid)}')

    print('\n=== Análisis univariado: cada feature como augment a V_v3 ===')
    print(f'{"feature":<26s} {"N":>5s} {"corr_g":>8s} {"alpha*":>9s} {"RMSE_aug":>9s} {"D vs V3":>8s}')

    results = []
    for feat in candidate_features:
        valid_f = [e for e in eventos if e['xg_v3'] is not None and e.get(feat) is not None]
        n_valid = len(valid_f)
        if n_valid < 100:
            continue

        feat_vals = np.array([e[feat] for e in valid_f], dtype=float)
        goles = np.array([e['goles'] for e in valid_f], dtype=float)
        xg_v3 = np.array([e['xg_v3'] for e in valid_f], dtype=float)

        # Correlación
        corr = np.corrcoef(feat_vals, goles)[0, 1]

        # Residuo: y - xg_v3 = alpha * feat + epsilon
        residuo = goles - xg_v3
        var_feat = (feat_vals * feat_vals).sum()
        if var_feat < 1e-9:
            continue
        alpha_opt = (residuo * feat_vals).sum() / var_feat

        # Pred augmented
        pred_aug = xg_v3 + alpha_opt * feat_vals
        rmse_aug = math.sqrt(np.mean((pred_aug - goles) ** 2))
        rmse_base_f = math.sqrt(np.mean((xg_v3 - goles) ** 2))
        delta = rmse_aug - rmse_base_f

        results.append({
            'feature': feat, 'n': n_valid, 'corr_g': float(corr),
            'alpha_opt': float(alpha_opt), 'rmse_aug': float(rmse_aug),
            'delta': float(delta),
        })

    # Ordenar por delta más negativo (más mejora)
    results.sort(key=lambda x: x['delta'])
    for r in results:
        flag = ' WIN' if r['delta'] < -0.005 else ('     ' if r['delta'] < 0 else ' LOSS')
        print(f'{r["feature"]:<26s} {r["n"]:>5d} {r["corr_g"]:>+8.4f} {r["alpha_opt"]:>+9.5f} {r["rmse_aug"]:>9.4f} {r["delta"]:>+8.4f}{flag}')

    # ============ Top 5 multivariado: V_v3 + top-5 features lineales ============
    print('\n=== Multivariado: V_v3 + top-5 features (NNLS) ===')
    from scipy.optimize import nnls
    top5 = [r['feature'] for r in results[:5] if r['delta'] < -0.001]
    print(f'Top-5 features (con mejora individual): {top5}')

    if len(top5) >= 2:
        valid_multi = [e for e in eventos if e['xg_v3'] is not None
                        and all(e.get(f) is not None for f in top5)]
        if len(valid_multi) >= 100:
            X = np.array([[e['xg_v3']] + [e[f] for f in top5] for e in valid_multi])
            y = np.array([e['goles'] for e in valid_multi])
            sol, _ = nnls(X, y)
            pred = X.dot(sol)
            rmse_multi = math.sqrt(np.mean((pred - y) ** 2))
            print(f'  N={len(valid_multi)} | RMSE_multi={rmse_multi:.4f} (vs V_v3={base_rmse:.4f}) | Δ={rmse_multi-base_rmse:+.4f}')
            print('  Coefs:')
            print(f'    xg_v3 coef = {sol[0]:.4f}')
            for i, f in enumerate(top5):
                print(f'    {f:<26s} coef = {sol[i+1]:+.5f}')

    # Save
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'baseline_v3_rmse': base_rmse,
            'baseline_v3_corr': base_corr,
            'n_eventos': len(eventos),
            'features_evaluated': len(results),
            'results': results,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')

    con.close()


if __name__ == '__main__':
    main()

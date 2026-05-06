"""
Backfill SHADOW logging — para todos los partidos SOFA, computar V0 + V2 y persistir.

Usa data ya en DB (NO consume API SOFA):
  - V2 = sofascore_match_features.xg_shotmap_l/v (ya calculado por motor_xg_v2_14)
  - V0 = calcular_xg_hibrido sobre stats_partido_espn (cuando matched)
  - Persiste delta_v2_v0 para análisis

Idempotente: si ya está logged el evento → skip.
"""
import sqlite3
import sys
import json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, '.')
from analisis.aliases_sofa_espn import norm_team_name, buscar_match_robusto

DB = 'fondo_quant.db'
THETA_HIBRIDO = 0.70
ALPHA_DEFAULT = 0.30


def cargar_alphas():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    alphas = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alpha_xg_v2_hibrido_sofa'"):
        alphas[r[0]] = float(r[1])
    con.close()
    return alphas


def cargar_params_v0():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    beta_sot = {'global': 0.352}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None:
            coef_corner[r[0]] = float(r[1])
    con.close()
    return beta_sot, coef_corner


def main():
    print('=== BACKFILL SHADOW LOG xG v2 ===\n')
    alphas = cargar_alphas()
    beta_sot, coef_corner = cargar_params_v0()

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Index ESPN
    espn_all = cur.execute('SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac FROM stats_partido_espn WHERE hg IS NOT NULL').fetchall()
    espn_idx = {}
    espn_by_liga_fecha = defaultdict(list)
    for r in espn_all:
        liga, fecha, ht, at = r[0], r[1], r[2], r[3]
        key = (liga, fecha, norm_team_name(ht, liga), norm_team_name(at, liga))
        espn_idx[key] = r
        espn_by_liga_fecha[(liga, fecha)].append(r)
    print(f'ESPN events indexed: {len(espn_idx)}')

    # Sofa partidos
    sofa = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               xg_shotmap_l, xg_shotmap_v, n_shots_shotmap
        FROM sofascore_match_features
        WHERE error IS NULL AND xg_shotmap_l IS NOT NULL
    ''').fetchall()
    print(f'SOFA partidos con xG: {len(sofa)}')

    # Idempotencia: skip si ya logueado
    existing = set()
    for r in cur.execute('SELECT liga, fecha, ht, at, equipo, es_local FROM picks_shadow_xg_v2'):
        existing.add((r[0], r[1], r[2], r[3], r[4], r[5]))
    print(f'Ya logueados previos: {len(existing)}')

    n_inserted = 0
    n_skip = 0
    n_no_v0 = 0  # SOFA sin match ESPN (V0=NULL)
    by_liga_stats = defaultdict(lambda: {'n':0, 'sofa_only':0, 'matched':0})

    for s in sofa:
        sofa_id, liga, fecha, ht, at, hg, ag, xg_l, xg_v, n_shots = s
        if hg is None or ag is None:
            continue

        # Match con ESPN (para V0)
        espn_match = buscar_match_robusto(liga, fecha, ht, at, espn_idx, espn_by_liga_fecha,
                                          tol_dias=2, fuzzy_thr=0.70)

        # alphas per liga
        alpha = alphas.get(liga, alphas.get('global', ALPHA_DEFAULT))

        # 2 eventos por partido (local + visita)
        for es_local, equipo, goles, xg_sofa in [(1, ht, hg, xg_l), (0, at, ag, xg_v)]:
            key = (liga, fecha, ht, at, equipo, es_local)
            if key in existing:
                n_skip += 1
                continue

            # V0
            v0_xg = None
            sofa_disp = 1
            if espn_match:
                _, _, _, _, e_hg, e_ag, hst, ast, hs, asv, hc, ac = espn_match
                # SOT/shots según es_local
                sot = hst if es_local else ast
                shots = hs if es_local else asv
                corners = hc if es_local else ac
                shots_off = max(0, (shots or 0) - (sot or 0))
                beta = beta_sot.get(liga, beta_sot['global'])
                coef_c = coef_corner.get(liga, 0.03)
                xg_calc_v0 = beta * (sot or 0) + 0.010 * shots_off + coef_c * (corners or 0)
                v0_xg = THETA_HIBRIDO * xg_calc_v0 + (1.0 - THETA_HIBRIDO) * goles
                by_liga_stats[liga]['matched'] += 1
            else:
                n_no_v0 += 1
                by_liga_stats[liga]['sofa_only'] += 1

            # V2 = α * sofa_final + (1-α) * V0
            sofa_final = THETA_HIBRIDO * xg_sofa + (1.0 - THETA_HIBRIDO) * goles
            if v0_xg is not None:
                v2_xg = alpha * sofa_final + (1.0 - alpha) * v0_xg
                delta = v2_xg - v0_xg
            else:
                # No V0 disponible (gap ESPN). V2 = sofa puro
                v2_xg = sofa_final
                delta = None

            cur.execute('''
                INSERT INTO picks_shadow_xg_v2
                (ts_log, liga, fecha, ht, at, equipo, es_local, goles_real,
                 xg_v0, xg_v2, xg_shotmap_sofa, alpha_aplicado, sofa_disponible, delta_v2_v0,
                 bead_proposal, manifesto_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'adepor-atn', 'MANIFESTO-CHANGE-APPROVED:adepor-atn')
            ''', (datetime.now().isoformat(), liga, fecha, ht, at, equipo, es_local, goles,
                  round(v0_xg, 3) if v0_xg else None, round(v2_xg, 3),
                  round(xg_sofa, 3), alpha, sofa_disp, round(delta, 3) if delta else None))
            n_inserted += 1
            by_liga_stats[liga]['n'] += 1

    con.commit()

    print(f'\n=== RESULTADOS ===')
    print(f'Insertados: {n_inserted}')
    print(f'Skipped (idempotente): {n_skip}')
    print(f'SOFA sin V0 (gap ESPN): {n_no_v0}')
    print(f'\nPor liga:')
    print(f'{"liga":<14s} {"total":>6s} {"matched":>8s} {"sofa_only":>10s}')
    for liga in sorted(by_liga_stats.keys()):
        s = by_liga_stats[liga]
        print(f'{liga:<14s} {s["n"]:>6d} {s["matched"]:>8d} {s["sofa_only"]:>10d}')

    # Resumen estadístico
    print(f'\n=== RESUMEN STATS ===')
    rows = cur.execute('''
        SELECT liga, COUNT(*), AVG(xg_v0), AVG(xg_v2), AVG(goles_real), AVG(delta_v2_v0),
               SUM(CASE WHEN xg_v0 IS NULL THEN 1 ELSE 0 END)
        FROM picks_shadow_xg_v2 GROUP BY liga ORDER BY liga
    ''').fetchall()
    print(f'{"liga":<14s} {"N":>5s} {"avg_v0":>7s} {"avg_v2":>7s} {"avg_g":>6s} {"avg_delta":>10s} {"sin_v0":>7s}')
    for r in rows:
        liga, n, av0, av2, ag, ad, no_v0 = r
        av0_s = f'{av0:.3f}' if av0 else 'NULL'
        ad_s = f'{ad:+.3f}' if ad else 'N/A'
        print(f'{liga:<14s} {n:>5d} {av0_s:>7s} {av2 or 0:>7.3f} {ag or 0:>6.3f} {ad_s:>10s} {no_v0:>7d}')

    con.close()


if __name__ == '__main__':
    main()

"""
Ablation con features SofaScore: ¿bajan el RMSE forward-EMA del Bayesian?

Pipeline:
  1. JOIN sofascore_match_features con stats_partido_espn por (liga, fecha, ht_norm, at_norm).
  2. Para cada match exitoso, extraer features pre-match (NO post-match leakage):
     - big_chances_l/v (post-game, OK como descriptor del partido)
     - shots_inside_box_l/v (post-game)
     - touches_penalty_area_l/v (post-game)
     - avg_rating_l/v (post-game pero refleja calidad histórica)
     - xg_shotmap_l/v (calculado por motor_xg_v2_14)
     - formation_l/v (pre-match REAL — debe poblarse pre-match SLA)
     - manager_l/v (pre-match)
  3. Re-entrenar Bayesian hierarchical agregando features incrementales.
  4. Reportar RMSE forward-EMA con/sin cada feature group.

Notar: post-game stats (big chances, shots inside box, etc.) son EQUIVALENTES a SOT
en el sentido de que son parte del mismo partido. Su uso en xg_calc forward-EMA es
legítimo (mismo paradigma que motor V0 actual con SOT). NO hay leakage.
"""

import json
import sqlite3
import sys
from collections import defaultdict
from math import sqrt
from pathlib import Path
import numpy as np
from scipy.optimize import nnls

sys.path.insert(0, '.')
from src.comun.gestor_nombres import obtener_nombre_estandar, son_equivalentes, cargar_diccionario

DICC_GLOBAL = cargar_diccionario()

DB = 'fondo_quant.db'
WARMUP = 5
ALFA = 0.10
THETA = 0.20
OUT_JSON = 'analisis/motor_xg_v2_15_ablation_sofa.json'


import unicodedata, re

# Aliases SOFA -> ESPN (extended via diagnostic motor_xg_v2_16)
ALIASES_SOFA_TO_ESPN = {
    'Argentina': {
        'gimnasia y esgrima': 'gimnasia la plata',
        'gimnasia y esgrima mendoza': 'gimnasia mendoza',
        'union de santa fe': 'union',
        'union santa fe': 'union',
        'central cordoba': 'central cordoba santiago del estero',
        'instituto de cordoba': 'instituto',
        'instituto cordoba': 'instituto',
    },
    'Brasil': {
        'athletico': 'athletico paranaense',
    },
    'Inglaterra': {
        'liverpool fc': 'liverpool',
        'wolverhampton': 'wolverhampton wanderers',
        'bournemouth': 'afc bournemouth',
    },
    'Bolivia': {
        'cdt real oruro': 'real oruro',
        'universitario': 'universitario de vinto',
        'fc universitario': 'universitario de vinto',
        'club fc universitario': 'universitario de vinto',
        'san antonio': 'san antonio bulo bulo',
        'cd san antonio': 'san antonio bulo bulo',
        'club independiente': 'independiente petrolero',
        'independiente': 'independiente petrolero',
    },
    'Uruguay': {
        'liverpool uy': 'liverpool',
        'racing de montevideo': 'racing',
        'racing montevideo': 'racing',
        'juventud de las piedras': 'juventud',
        'central espanol': 'central espanol futbol club',
    },
    'Peru': {
        'universitario de deportes': 'universitario',
        'adc juan pablo ii': 'juan pablo ii',
        'ad juan pablo ii': 'juan pablo ii',
        'cd moquegua': 'deportivo moquegua',
        'asociacion deportiva tarma': 'adt',
        'alianza atletico de sullana': 'alianza atletico',
        'los chankas cyc': 'los chankas',
        'cienciano': 'cienciano del cusco',
        'club atletico grau': 'atletico grau',
        'club sporting cristal': 'sporting cristal',
    },
    'Ecuador': {
        'universidad catolica del ecuador': 'universidad catolica',
        'liga deportiva universitaria de quito': 'liga de quito',
        'ldu': 'liga de quito',
        'leones del norte': 'leones',
        'mushuc runa sc': 'mushuc runa',
        'orense sc': 'orense',
        'manta fc': 'manta',
        'guayaquil city': 'guayaquil city fc',
        'guayaquil city fc': 'guayaquil city',
        'barcelona sc guayaquil': 'barcelona sc',
    },
    'Venezuela': {
        'caracas f.c.': 'caracas fc',
        'caracas fc': 'caracas',
        'trujillanos fc': 'trujillanos',
        'monagas': 'monagas sc',
        'monagas sc': 'monagas',
        'metropolitanos': 'metropolitanos fc',
        'metropolitanos fc': 'metropolitanos',
        'anzoategui fc': 'academia anzoategui',
        'academia anzoategui': 'anzoategui',
        'carabobo': 'carabobo fc',
        'carabobo fc': 'carabobo',
    },
}


def normalizar(s, liga=None):
    """Normalización agresiva para fuzzy match cross-source."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', errors='ignore').decode()
    s = s.lower().strip()
    # Quitar prefijos
    for prefix in ('club atletico ', 'ca ', 'cd ', 'club ', 'fc ', 'sc ', 'atletico ', 'atl ', 'atl. '):
        if s.startswith(prefix):
            s = s[len(prefix):]
    # Quitar paréntesis y contenido
    s = re.sub(r'\([^)]*\)', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    # Apply aliases manuales
    if liga and liga in ALIASES_SOFA_TO_ESPN:
        return ALIASES_SOFA_TO_ESPN[liga].get(s, s)
    return s


def matchear_sofa_espn():
    """JOIN sofascore_match_features ↔ stats_partido_espn por (liga, fecha, ht_norm, at_norm).
    Devuelve list[dict] con campos combinados y conteo de matches.
    """
    con = sqlite3.connect(DB)
    cur = con.cursor()

    sofa = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               big_chances_l, big_chances_v,
               shots_inside_box_l, shots_inside_box_v,
               shots_outside_box_l, shots_outside_box_v,
               touches_penalty_area_l, touches_penalty_area_v,
               errors_lead_to_shot_l, errors_lead_to_shot_v,
               recoveries_l, recoveries_v,
               formation_l, formation_v,
               manager_l, manager_v,
               avg_rating_l, avg_rating_v,
               max_rating_l, max_rating_v,
               xg_shotmap_l, xg_shotmap_v,
               referee_name, referee_yellows, referee_reds, referee_games,
               keeper_save_value_l, keeper_save_value_v
        FROM sofascore_match_features
        WHERE error IS NULL
    ''').fetchall()

    espn = cur.execute('''
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
    ''').fetchall()
    con.close()

    # Index ESPN por (liga, fecha, ht_norm, at_norm)
    espn_idx = {}
    for r in espn:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac = r
        ht_n = normalizar(ht, liga)
        at_n = normalizar(at, liga)
        espn_idx[(liga, fecha, ht_n, at_n)] = r

    matched = []
    unmatched = []
    for s in sofa:
        liga, fecha, sht, sat = s[1], s[2], s[3], s[4]
        sht_n = normalizar(sht, liga)
        sat_n = normalizar(sat, liga)
        key = (liga, fecha, sht_n, sat_n)
        if key in espn_idx:
            matched.append({'sofa': s, 'espn': espn_idx[key], 'liga': liga, 'fecha': fecha})
            continue
        # Fallback fecha +/- 1 día (zona horaria entre fuentes)
        from datetime import datetime, timedelta
        try:
            d0 = datetime.fromisoformat(fecha).date()
            for delta in (-1, 1):
                fecha_alt = (d0 + timedelta(days=delta)).isoformat()
                key_alt = (liga, fecha_alt, sht_n, sat_n)
                if key_alt in espn_idx:
                    matched.append({'sofa': s, 'espn': espn_idx[key_alt], 'liga': liga, 'fecha': fecha})
                    break
            else:
                # Try fuzzy ulterior
                candidates = [r for r in espn if r[0] == liga and abs((datetime.fromisoformat(r[1]).date() - d0).days) <= 1]
                for c in candidates:
                    if son_equivalentes(sht, c[2], DICC_GLOBAL, liga) and son_equivalentes(sat, c[3], DICC_GLOBAL, liga):
                        matched.append({'sofa': s, 'espn': c, 'liga': liga, 'fecha': fecha})
                        break
                else:
                    unmatched.append({'sofa': s, 'liga': liga, 'fecha': fecha, 'ht': sht, 'at': sat})
        except (ValueError, TypeError):
            unmatched.append({'sofa': s, 'liga': liga, 'fecha': fecha, 'ht': sht, 'at': sat})

    print(f'JOIN sofa-espn: matched={len(matched)} unmatched={len(unmatched)} | tasa={100*len(matched)/(len(matched)+len(unmatched)):.1f}%')
    return matched, unmatched


def construir_eventos_sofa(matched):
    """A cada match exitoso, generar 2 eventos (local + visita) con features SOFA + ESPN."""
    eventos = []
    for m in matched:
        s = m['sofa']
        e = m['espn']
        liga = m['liga']
        fecha = m['fecha']
        # ESPN features
        hst, ast, hs, asv, hc, ac = e[6], e[7], e[8], e[9], e[10], e[11]
        # SOFA features (indices según SELECT)
        bc_l, bc_v = s[7], s[8]
        sib_l, sib_v = s[9], s[10]
        sob_l, sob_v = s[11], s[12]
        tpa_l, tpa_v = s[13], s[14]
        elts_l, elts_v = s[15], s[16]
        rec_l, rec_v = s[17], s[18]
        form_l, form_v = s[19], s[20]
        mgr_l, mgr_v = s[21], s[22]
        ar_l, ar_v = s[23], s[24]
        mr_l, mr_v = s[25], s[26]
        xg_l, xg_v = s[27], s[28]
        ref_name, ref_y, ref_r, ref_g = s[29], s[30], s[31], s[32]
        ksv_l, ksv_v = s[33], s[34]
        ref_cards_per_game = ((ref_y or 0) + (ref_r or 0)) / max(ref_g or 1, 1) if ref_g else None
        ref_red_per_game = (ref_r or 0) / max(ref_g or 1, 1) if ref_g else None
        hg, ag = e[4], e[5]

        # Local
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': e[2], 'rival': e[3],
            'sot': hst or 0,
            'shots_off': max(0, (hs or 0) - (hst or 0)),
            'corners': hc or 0,
            'big_chances': bc_l, 'shots_inside_box': sib_l, 'shots_outside_box': sob_l,
            'touches_penalty_area': tpa_l, 'errors_lead_to_shot': elts_l, 'recoveries': rec_l,
            'avg_rating': ar_l, 'max_rating': mr_l,
            'xg_shotmap': xg_l,
            'formation': form_l, 'manager': mgr_l,
            'ref_cards_per_game': ref_cards_per_game,
            'ref_red_per_game': ref_red_per_game,
            'keeper_save_value_rival': ksv_v,  # rival keeper xG faced = our xG offensive
            'goles': hg, 'es_local': 1.0,
        })
        # Visita
        eventos.append({
            'fecha': fecha, 'liga': liga, 'equipo': e[3], 'rival': e[2],
            'sot': ast or 0,
            'shots_off': max(0, (asv or 0) - (ast or 0)),
            'corners': ac or 0,
            'big_chances': bc_v, 'shots_inside_box': sib_v, 'shots_outside_box': sob_v,
            'touches_penalty_area': tpa_v, 'errors_lead_to_shot': elts_v, 'recoveries': rec_v,
            'avg_rating': ar_v, 'max_rating': mr_v,
            'xg_shotmap': xg_v,
            'formation': form_v, 'manager': mgr_v,
            'ref_cards_per_game': ref_cards_per_game,
            'ref_red_per_game': ref_red_per_game,
            'keeper_save_value_rival': ksv_l,
            'goles': ag, 'es_local': 0.0,
        })
    return eventos


def fit_nnls(eventos_train, fnames):
    X, y = [], []
    for ev in eventos_train:
        row = [1.0]
        skip = False
        for f in fnames:
            v = ev.get(f)
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


def aplicar_y_eval(eventos, fnames, coefs, theta=THETA, alfa=ALFA):
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    errs = []
    eventos_sorted = sorted(eventos, key=lambda e: e['fecha'])
    for ev in eventos_sorted:
        xg_calc = coefs[0]
        skip = False
        for i, f in enumerate(fnames):
            v = ev.get(f)
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
            errs.append(s['ema'] - ev['goles'])
        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = alfa * xg_final + (1.0 - alfa) * s['ema']
        s['n'] += 1
    rmse = sqrt(sum(e * e for e in errs) / len(errs)) if errs else None
    return rmse, len(errs)


def main():
    matched, unmatched = matchear_sofa_espn()
    if not matched:
        print('Sin matches, abortando ablation')
        return

    eventos = construir_eventos_sofa(matched)
    print(f'Eventos para ablation: {len(eventos)}')
    eventos_train = [e for e in eventos if e['fecha'][:4] < '2026']
    print(f'Eventos train (<2026): {len(eventos_train)}')
    if len(eventos_train) < 200:
        print('N train muy pequeño. Solo evaluación in-sample esta corrida.')

    suite = {
        'BASELINE_sot': ['sot'],
        'sot+big_chances': ['sot', 'big_chances'],
        'sot+shots_inside_box': ['sot', 'shots_inside_box'],
        'sot+touches_penalty': ['sot', 'touches_penalty_area'],
        'sot+xg_shotmap': ['sot', 'xg_shotmap'],
        'sot+keeper_save_rival': ['sot', 'keeper_save_value_rival'],   # NUEVO
        'sot+avg_rating': ['sot', 'avg_rating'],
        'sot+max_rating': ['sot', 'max_rating'],
        'sot+ref_cards_per_game': ['sot', 'ref_cards_per_game'],
        'sot+ref_red_per_game': ['sot', 'ref_red_per_game'],
        'PURE_xg_shotmap': ['xg_shotmap'],
        'PURE_keeper_save_rival': ['keeper_save_value_rival'],
        'PURE_big_chances': ['big_chances'],
        'PURE_avg_rating': ['avg_rating'],
        'sot+all_shots': ['sot', 'big_chances', 'shots_inside_box', 'shots_outside_box', 'touches_penalty_area'],
        'sot+ratings+xg': ['sot', 'avg_rating', 'max_rating', 'xg_shotmap'],
        'sot+xg+keeper': ['sot', 'xg_shotmap', 'keeper_save_value_rival'],
        'sot+all_xg_proxies': ['sot', 'xg_shotmap', 'keeper_save_value_rival', 'big_chances', 'shots_inside_box'],
        'KITCHEN_SINK': ['sot', 'big_chances', 'shots_inside_box', 'touches_penalty_area',
                          'avg_rating', 'max_rating', 'xg_shotmap', 'keeper_save_value_rival',
                          'recoveries', 'errors_lead_to_shot', 'ref_red_per_game'],
    }

    # Train con todo (in-sample acá porque N pequeño season 2026)
    train_set = eventos  # in-sample (POC)

    print(f'\n{"Modelo":<32s} | {"OOS_RMSE":>10s} | {"N":>6s} | {"d_BASE":>8s} | coefs')
    rmse_base = None
    results = {}
    for tag, fnames in suite.items():
        sol, ntr = fit_nnls(train_set, fnames)
        if sol is None:
            print(f'  {tag:<32s} | sin datos')
            continue
        rmse, n_err = aplicar_y_eval(eventos, fnames, sol)
        if tag == 'BASELINE_sot':
            rmse_base = rmse
        delta = (rmse - rmse_base) if (rmse is not None and rmse_base is not None) else 0
        flag = '*' if (delta and delta < -0.005) else ' '
        coefs_str = ' '.join(f'{c:+.3f}' for c in sol[:8])
        rmse_str = f'{rmse:.4f}' if rmse is not None else '   N/A'
        print(f'[{flag}] {tag:<32s} | {rmse_str:>10s} | {n_err:>6d} | {delta:>+8.4f} | [{coefs_str}]')
        results[tag] = {'features': fnames, 'coefs': sol.tolist(), 'rmse': rmse, 'n_err': n_err, 'delta': delta}

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'matched': len(matched),
            'unmatched': len(unmatched),
            'eventos_total': len(eventos),
            'eventos_train': len(eventos_train),
            'results': results,
            'baseline_rmse': rmse_base,
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

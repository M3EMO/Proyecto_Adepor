"""
Ablation v2 — corrección estadística honesta.

Problema v1: WARMUP=5 deja N=1-2 errores válidos sobre subset matched (artefacto).

Solución v2: usar EMA del universo COMPLETO stats_partido_espn (13,430 partidos)
para warmup robusto, y solo COMPARAR errores en partidos donde existen features SOFA.

Pipeline:
  1. Construir EMA forward por equipo SOBRE UNIVERSO FULL stats_partido_espn:
     - state_full[equipo] = ema_xg_calc forward usando todos los partidos del equipo
  2. Para cada evento (equipo, partido_t) donde existe sofa_features:
     a. Pred_baseline = state_full[equipo].ema en t (con WARMUP=5 sobre universo full)
     b. Pred_sofa = pred_baseline modificado por features sofa (delta sobre baseline)
  3. RMSE comparativo solo sobre eventos sofa-matched

NO mide RMSE de un modelo nuevo. Mide DELTA RMSE incremental por agregar features sofa.
"""

import sqlite3, sys, unicodedata, re, json
from collections import defaultdict
from math import sqrt
from datetime import datetime, timedelta
import numpy as np
from scipy.optimize import nnls

DB = 'fondo_quant.db'
WARMUP = 5
ALFA = 0.10
THETA = 0.20

# Aliases (extended)
ALIASES_SOFA_TO_ESPN = {
    'Argentina': {'gimnasia y esgrima':'gimnasia la plata','gimnasia y esgrima mendoza':'gimnasia mendoza','union de santa fe':'union','union santa fe':'union','central cordoba':'central cordoba santiago del estero','instituto de cordoba':'instituto','instituto cordoba':'instituto'},
    'Brasil': {'athletico':'athletico paranaense'},
    'Inglaterra': {'liverpool fc':'liverpool','wolverhampton':'wolverhampton wanderers','bournemouth':'afc bournemouth'},
    'Bolivia': {'cdt real oruro':'real oruro','universitario':'universitario de vinto','fc universitario':'universitario de vinto','club fc universitario':'universitario de vinto','san antonio':'san antonio bulo bulo','cd san antonio':'san antonio bulo bulo','club independiente':'independiente petrolero','independiente':'independiente petrolero'},
    'Uruguay': {'liverpool uy':'liverpool','racing de montevideo':'racing','racing montevideo':'racing','juventud de las piedras':'juventud','central espanol':'central espanol futbol club'},
    'Peru': {'universitario de deportes':'universitario','adc juan pablo ii':'juan pablo ii','ad juan pablo ii':'juan pablo ii','cd moquegua':'deportivo moquegua','asociacion deportiva tarma':'adt','alianza atletico de sullana':'alianza atletico','los chankas cyc':'los chankas','cienciano':'cienciano del cusco','club atletico grau':'atletico grau','club sporting cristal':'sporting cristal'},
    'Ecuador': {'universidad catolica del ecuador':'universidad catolica','liga deportiva universitaria de quito':'liga de quito','ldu':'liga de quito','leones del norte':'leones','mushuc runa sc':'mushuc runa','orense sc':'orense','manta fc':'manta','guayaquil city':'guayaquil city fc','barcelona sc guayaquil':'barcelona sc'},
    'Venezuela': {'caracas f.c.':'caracas fc','caracas fc':'caracas','trujillanos fc':'trujillanos','monagas':'monagas sc','metropolitanos':'metropolitanos fc','anzoategui fc':'academia anzoategui','carabobo':'carabobo fc'},
}


def norm(s, liga=None):
    if not s: return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', errors='ignore').decode().lower().strip()
    for prefix in ('club atletico ', 'ca ', 'cd ', 'club ', 'fc ', 'sc ', 'atletico ', 'atl ', 'atl. '):
        if s.startswith(prefix): s = s[len(prefix):]
    s = re.sub(r'\([^)]*\)', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    if liga and liga in ALIASES_SOFA_TO_ESPN:
        return ALIASES_SOFA_TO_ESPN[liga].get(s, s)
    return s


def cargar_params():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    beta_sot = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    DEFAULT_BETA = beta_sot.pop('global', 0.352)
    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None: coef_corner[r[0]] = float(r[1])
    con.close()
    return beta_sot, coef_corner, DEFAULT_BETA


def construir_universo_completo():
    """Devuelve eventos universo full ESPN ordenados por fecha."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL AND hst IS NOT NULL AND ast IS NOT NULL
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()
    eventos = []
    for r in rows:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac = r
        eventos.append({'fecha':fecha,'liga':liga,'equipo':ht,'rival':at,
                        'sot':hst or 0,'shots_off':max(0,(hs or 0)-(hst or 0)),
                        'corners':hc or 0,'goles':hg,'es_local':1.0,
                        'norm_equipo':norm(ht, liga)})
        eventos.append({'fecha':fecha,'liga':liga,'equipo':at,'rival':ht,
                        'sot':ast or 0,'shots_off':max(0,(asv or 0)-(ast or 0)),
                        'corners':ac or 0,'goles':ag,'es_local':0.0,
                        'norm_equipo':norm(at, liga)})
    return eventos


def cargar_sofa_matched():
    """Devuelve dict (liga, fecha, ht_norm, at_norm) -> dict sofa features."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag,
               big_chances_l, big_chances_v,
               shots_inside_box_l, shots_inside_box_v,
               touches_penalty_area_l, touches_penalty_area_v,
               errors_lead_to_shot_l, errors_lead_to_shot_v,
               recoveries_l, recoveries_v,
               formation_l, formation_v,
               avg_rating_l, avg_rating_v,
               max_rating_l, max_rating_v,
               xg_shotmap_l, xg_shotmap_v,
               referee_yellows, referee_reds, referee_games,
               keeper_save_value_l, keeper_save_value_v
        FROM sofascore_match_features WHERE error IS NULL
    """).fetchall()
    con.close()
    out = {}
    for r in rows:
        liga, fecha, sht, sat = r[0], r[1], r[2], r[3]
        sht_n = norm(sht, liga)
        sat_n = norm(sat, liga)
        # Try fechas ±1 también
        for delta in (0, -1, 1):
            try:
                d = (datetime.fromisoformat(fecha) + timedelta(days=delta)).date().isoformat()
                key = (liga, d, sht_n, sat_n)
                if key not in out:  # mantener strict si existe
                    out[key] = {
                        'big_chances_l':r[6],'big_chances_v':r[7],
                        'shots_inside_box_l':r[8],'shots_inside_box_v':r[9],
                        'touches_penalty_area_l':r[10],'touches_penalty_area_v':r[11],
                        'errors_lead_to_shot_l':r[12],'errors_lead_to_shot_v':r[13],
                        'recoveries_l':r[14],'recoveries_v':r[15],
                        'avg_rating_l':r[18],'avg_rating_v':r[19],
                        'max_rating_l':r[20],'max_rating_v':r[21],
                        'xg_shotmap_l':r[22],'xg_shotmap_v':r[23],
                        'ref_cards_per_game': ((r[24] or 0)+(r[25] or 0))/r[26] if r[26] else None,
                        'ref_red_per_game': (r[25] or 0)/r[26] if r[26] else None,
                        'keeper_save_value_rival_l': r[28],  # rival keeper xS for local
                        'keeper_save_value_rival_v': r[27],
                    }
            except (ValueError, TypeError):
                pass
    return out


def computar_baseline_emas(eventos_full):
    """Para cada evento, captura EMA forward-strict (universo full).
    Returns dict {(liga, fecha, equipo_norm): ema_pre_evento}."""
    beta_sot, coef_corner, DEFAULT_BETA = cargar_params()
    state = defaultdict(lambda: {'ema': None, 'n': 0})
    eventos_sorted = sorted(eventos_full, key=lambda e: e['fecha'])
    pre_event_emas = {}

    for ev in eventos_sorted:
        liga = ev['liga']
        beta = beta_sot.get(liga, DEFAULT_BETA)
        coef_c = coef_corner.get(liga, 0.03)
        sot = ev['sot']
        shots_off = ev['shots_off']
        corners = ev['corners']
        goles = ev['goles']
        xg_calc = beta * sot + 0.010 * shots_off + coef_c * corners
        xg_final = THETA * xg_calc + (1.0 - THETA) * goles

        equipo_n = ev['norm_equipo']
        s = state[equipo_n]
        # Capturar pre-update si tiene WARMUP
        key = (liga, ev['fecha'], equipo_n)
        if s['ema'] is not None and s['n'] >= WARMUP:
            pre_event_emas[key] = s['ema']

        if s['ema'] is None:
            s['ema'] = xg_final
        else:
            s['ema'] = ALFA * xg_final + (1.0 - ALFA) * s['ema']
        s['n'] += 1
    return pre_event_emas


def main():
    print('=== ABLATION v2 — RMSE forward-EMA con baseline universo FULL ===\n')

    print('1. Cargando eventos universo full...')
    eventos_full = construir_universo_completo()
    print(f'   Eventos: {len(eventos_full)}')

    print('2. Computing EMA baseline forward-strict (V0 motor productivo)...')
    pre_event_emas = computar_baseline_emas(eventos_full)
    print(f'   Eventos con EMA válida (post-WARMUP): {len(pre_event_emas)}')

    print('3. Cargando features SOFA...')
    sofa_idx = cargar_sofa_matched()
    print(f'   Sofa features matchados: {len(sofa_idx)}')

    # Construir eventos para evaluación: aquellos donde tenemos EMA + SOFA features
    print('\n4. Identificando eventos eval (EMA disponible + SOFA features)...')
    eval_eventos = []
    for ev in eventos_full:
        liga = ev['liga']
        fecha = ev['fecha']
        equipo_n = ev['norm_equipo']
        rival_n = norm(ev['rival'], liga)
        # ht-at depende es_local
        if ev['es_local'] == 1.0:
            sofa_key = (liga, fecha, equipo_n, rival_n)
            sofa_keys_alt = [(liga, fecha, equipo_n, rival_n)]
        else:
            sofa_key = (liga, fecha, rival_n, equipo_n)
            sofa_keys_alt = [(liga, fecha, rival_n, equipo_n)]
        # Try alternative dates
        for delta in (-1, 1):
            try:
                d = (datetime.fromisoformat(fecha) + timedelta(days=delta)).date().isoformat()
                if ev['es_local'] == 1.0:
                    sofa_keys_alt.append((liga, d, equipo_n, rival_n))
                else:
                    sofa_keys_alt.append((liga, d, rival_n, equipo_n))
            except (ValueError, TypeError):
                pass
        sofa_data = None
        for k in sofa_keys_alt:
            if k in sofa_idx:
                sofa_data = sofa_idx[k]
                break
        if sofa_data is None:
            continue
        # EMA?
        ema_key = (liga, fecha, equipo_n)
        if ema_key not in pre_event_emas:
            continue
        ema_pre = pre_event_emas[ema_key]

        # Anotar features sofa (local o visita según ev)
        suf = '_l' if ev['es_local'] == 1.0 else '_v'
        suf_rival = '_v' if ev['es_local'] == 1.0 else '_l'
        eval_eventos.append({
            'liga': liga, 'fecha': fecha, 'equipo_n': equipo_n,
            'goles': ev['goles'],
            'baseline_pred': ema_pre,
            'sot': ev['sot'],
            'big_chances': sofa_data.get(f'big_chances{suf}'),
            'shots_inside_box': sofa_data.get(f'shots_inside_box{suf}'),
            'touches_penalty_area': sofa_data.get(f'touches_penalty_area{suf}'),
            'avg_rating': sofa_data.get(f'avg_rating{suf}'),
            'max_rating': sofa_data.get(f'max_rating{suf}'),
            'xg_shotmap': sofa_data.get(f'xg_shotmap{suf}'),
            'keeper_save_rival': sofa_data.get(f'keeper_save_value_rival{suf}'),
            'ref_cards_per_game': sofa_data.get('ref_cards_per_game'),
            'ref_red_per_game': sofa_data.get('ref_red_per_game'),
            'es_local': ev['es_local'],
        })

    print(f'   Eventos eval (EMA + SOFA): {len(eval_eventos)}')
    if len(eval_eventos) < 50:
        print('   N insuficiente para ablation. Abortar.')
        return

    # ===== Baseline RMSE =====
    print('\n5. RMSE BASELINE (V0 motor productivo, EMA forward-strict universo FULL):')
    base_errs = [e['baseline_pred'] - e['goles'] for e in eval_eventos]
    rmse_base = sqrt(sum(x*x for x in base_errs) / len(base_errs))
    print(f'   N = {len(base_errs)} eventos | RMSE_baseline = {rmse_base:.4f}')

    # ===== Aug. linear: pred = baseline + alpha * feature =====
    # Para cada feature, fit OLS sin intercept: residuo = goles - baseline = alpha * feature
    # Si alpha mejora RMSE OOS, feature aporta
    print('\n6. ABLATION: alpha óptimo per feature (universo eval N={})'.format(len(eval_eventos)))
    print(f'   {"Feature":<28s} {"alpha_opt":>10s} {"corr_resid":>11s} {"RMSE_aug":>9s} {"Delta":>9s} {"N_valid":>8s}')

    results = {}
    for feat in ['big_chances','shots_inside_box','touches_penalty_area','avg_rating','max_rating','xg_shotmap','keeper_save_rival','ref_cards_per_game','ref_red_per_game']:
        # Filter events with feature non-null
        valid = [e for e in eval_eventos if e.get(feat) is not None]
        if len(valid) < 30:
            print(f'   {feat:<28s} {"N<30":>10s}')
            continue
        feat_vals = np.array([e[feat] for e in valid], dtype=float)
        residuos = np.array([e['goles'] - e['baseline_pred'] for e in valid], dtype=float)
        # Fit alpha simple: minimize ||residuos - alpha*feat_vals||²
        # alpha = sum(r*f) / sum(f*f)
        denom = (feat_vals**2).sum()
        if denom < 1e-9:
            continue
        alpha = (residuos * feat_vals).sum() / denom
        # Pred aug: pred + alpha * feat
        pred_aug = np.array([e['baseline_pred'] for e in valid]) + alpha * feat_vals
        errs_aug = pred_aug - np.array([e['goles'] for e in valid])
        rmse_aug = sqrt((errs_aug**2).mean())
        # Baseline RMSE on this filtered subset
        rmse_base_f = sqrt(((np.array([e['baseline_pred'] for e in valid]) - np.array([e['goles'] for e in valid]))**2).mean())
        delta = rmse_aug - rmse_base_f
        corr = np.corrcoef(feat_vals, residuos)[0,1]
        flag = '*' if delta < -0.005 else ' '
        print(f'   [{flag}] {feat:<26s} {alpha:>+10.4f} {corr:>+11.4f} {rmse_aug:>9.4f} {delta:>+9.4f} {len(valid):>8d}')
        results[feat] = {'alpha':alpha, 'corr':corr, 'rmse_aug':rmse_aug, 'rmse_base':rmse_base_f, 'delta':delta, 'n_valid':len(valid)}

    # ===== Per liga analysis (BOL/PER/VEN/ECU vs ARG/BRA/ENG/ESP) =====
    print('\n7. Análisis por liga: RMSE baseline + features SOFA (best feature)')
    by_liga = defaultdict(list)
    for e in eval_eventos:
        by_liga[e['liga']].append(e)
    print(f'   {"liga":<12s} {"N":>4s} {"RMSE_base":>10s} {"RMSE_xgshot":>12s} {"D":>8s}')
    by_liga_analysis = {}
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        evs = by_liga[liga]
        if len(evs) < 20: continue
        base_errs = [e['baseline_pred'] - e['goles'] for e in evs]
        rmse_b = sqrt(sum(x*x for x in base_errs) / len(base_errs))
        # xg_shotmap
        valid = [e for e in evs if e.get('xg_shotmap') is not None]
        if len(valid) < 10:
            print(f'   {liga:<12s} {len(evs):>4d} {rmse_b:>10.4f} {"N<10":>12s}')
            continue
        feat_vals = np.array([e['xg_shotmap'] for e in valid], dtype=float)
        resid = np.array([e['goles'] - e['baseline_pred'] for e in valid], dtype=float)
        if (feat_vals**2).sum() < 1e-9: continue
        alpha = (resid * feat_vals).sum() / (feat_vals**2).sum()
        pred_aug = np.array([e['baseline_pred'] for e in valid]) + alpha * feat_vals
        errs = pred_aug - np.array([e['goles'] for e in valid])
        rmse_a = sqrt((errs**2).mean())
        rmse_b_f = sqrt(((np.array([e['baseline_pred'] for e in valid]) - np.array([e['goles'] for e in valid]))**2).mean())
        d = rmse_a - rmse_b_f
        print(f'   {liga:<12s} {len(evs):>4d} {rmse_b_f:>10.4f} {rmse_a:>12.4f} {d:>+8.4f}')
        by_liga_analysis[liga] = {'n':len(evs),'rmse_base':rmse_b_f,'rmse_aug_xg':rmse_a,'delta':d}

    out = {
        'rmse_baseline_global': rmse_base,
        'n_eval': len(eval_eventos),
        'features': results,
        'by_liga': by_liga_analysis,
    }
    with open('analisis/motor_xg_v2_18_ablation_v2.json', 'w') as f:
        json.dump(out, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print('\nSaved analisis/motor_xg_v2_18_ablation_v2.json')


if __name__ == '__main__':
    main()

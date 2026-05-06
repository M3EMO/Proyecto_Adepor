"""Hook post-liquidacion SOFA: scrape SofaScore para partidos recien liquidados.

Trigger: tras motor_data + scrape_post_liquidacion (FASE 3).
Identifica partidos en stats_partido_espn que NO esten en sofascore_match_features
y los scrapea con safeguards anti-bot.

Idempotente: skip si ya esta en DB.

Estrategia matching SOFA:
  Para cada partido pendiente: scoreboard SOFA (liga + fecha) -> filtrar por
  nombres de equipos -> obtener event_id -> 4 endpoints SOFA + populate xG.

Uso:
  py scripts/scrape_sofa_post_liquidacion.py                # auto: ultimos 7 dias
  py scripts/scrape_sofa_post_liquidacion.py --dias 14
  py scripts/scrape_sofa_post_liquidacion.py --max 50       # cap diario seguro
  py scripts/scrape_sofa_post_liquidacion.py --liga Argentina
  py scripts/scrape_sofa_post_liquidacion.py --dry-run

Integracion en ejecutar_proyecto.py (sugerido):
  Despues de scrape_post_liquidacion.py agregar:
    py scripts/scrape_sofa_post_liquidacion.py --max 30

CAP DIARIO: 30 partidos por defecto. ~120 calls SOFA / dia. Bajo riesgo bot detection.
"""
import argparse
import json
import random
import sqlite3
import sys
import time
import unicodedata
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as creq
from analisis.aliases_sofa_espn import norm_team_name

DB = ROOT / "fondo_quant.db"

SOFASCORE_LIGA_IDS = {
    'Argentina': 155, 'Brasil': 325, 'Bolivia': 16736, 'Peru': 406,
    'Ecuador': 240, 'Venezuela': 231, 'Uruguay': 278, 'Inglaterra': 17,
    'Espana': 8, 'Italia': 23, 'Alemania': 35, 'Francia': 34,
    'Turquia': 52, 'Noruega': 20, 'Chile': 11653, 'Colombia': 152,
}

# Safeguards
SLEEP_MIN = 1.5
SLEEP_MAX = 3.5
PAUSE_EVERY_N = 50
PAUSE_DURATION = 60
CAP_TOTAL = 200  # cap diario hook (~50 partidos × 4 endpoints)

UA_ROTATION = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
]

session = creq.Session()
_calls = 0
_aborted = False


def smart_sleep():
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def get(url):
    global _calls, _aborted
    if _aborted:
        return {'_error': 'aborted'}
    if _calls >= CAP_TOTAL:
        print(f'\n!!! CAP {CAP_TOTAL} alcanzado. Aborto preventivo.')
        _aborted = True
        return {'_error': 'cap'}
    if _calls > 0 and _calls % PAUSE_EVERY_N == 0:
        print(f'\n[PAUSA {PAUSE_DURATION}s tras {_calls} calls]')
        time.sleep(PAUSE_DURATION)
    _calls += 1
    headers = {
        'User-Agent': random.choice(UA_ROTATION),
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.sofascore.com/',
        'Origin': 'https://www.sofascore.com',
    }
    try:
        r = session.get(url, impersonate='chrome', headers=headers, timeout=25)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 403:
            print(f'\n!!! 403 BLOCKED en call #{_calls}. Aborto.')
            _aborted = True
            return {'_error': '403'}
        if r.status_code == 429:
            time.sleep(30)
            return {'_error': '429'}
        return {'_error': f'status_{r.status_code}'}
    except Exception as e:
        return {'_error': str(e)}


def cargar_pendientes(conn, dias=7, liga=None, max_n=None):
    """Partidos en stats_partido_espn liquidados en últimos N días, NO en SOFA aún."""
    cur = conn.cursor()
    cutoff = (datetime.now().date() - timedelta(days=dias)).isoformat()
    where = ['s.fecha >= ?', 's.hg IS NOT NULL', 's.ag IS NOT NULL']
    params = [cutoff]
    if liga:
        where.append('s.liga = ?')
        params.append(liga)

    sql = f'''
        SELECT s.evt_id, s.liga, s.fecha, s.ht, s.at, s.hg, s.ag
        FROM stats_partido_espn s
        WHERE {' AND '.join(where)}
          AND NOT EXISTS (
              SELECT 1 FROM sofascore_match_features sf
              WHERE sf.liga = s.liga AND sf.fecha = s.fecha
                AND LOWER(sf.ht) LIKE '%' || LOWER(SUBSTR(s.ht, 1, 6)) || '%'
          )
        ORDER BY s.fecha DESC
    '''
    if max_n:
        sql += f' LIMIT {max_n}'
    return cur.execute(sql, params).fetchall()


def buscar_event_id_sofa(liga_id, fecha, ht, at, liga):
    """Busca event_id en SOFA scoreboard para liga+fecha+equipos."""
    # SofaScore scheduled-events endpoint
    url = f'https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha}'
    d = get(url)
    if not d or '_error' in d:
        return None
    ht_n = norm_team_name(ht, liga)
    at_n = norm_team_name(at, liga)
    for ev in d.get('events', []):
        # Filtrar por tournament_id
        ut = ev.get('tournament', {}).get('uniqueTournament', {})
        if ut.get('id') != liga_id:
            continue
        sofa_ht = ev.get('homeTeam', {}).get('name', '')
        sofa_at = ev.get('awayTeam', {}).get('name', '')
        if (norm_team_name(sofa_ht, liga) == ht_n and
            norm_team_name(sofa_at, liga) == at_n):
            return ev.get('id')
    return None


def fetch_4_endpoints(event_id):
    out = {}
    out['statistics'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics')
    smart_sleep()
    out['shotmap'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/shotmap')
    smart_sleep()
    out['lineups'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/lineups')
    smart_sleep()
    out['event_main'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}')
    return out


# Reusar parsing de motor_xg_v2_13
STAT_MAP = {
    'Ball possession': 'ball_possession', 'Big chances': 'big_chances',
    'Big chances missed': 'big_chances_missed', 'Total shots': 'shots_total',
    'Shots on target': 'shots_on_target', 'Shots off target': 'shots_off_target',
    'Shots inside box': 'shots_inside_box', 'Shots outside box': 'shots_outside_box',
    'Blocked shots': 'blocked_shots', 'Hit woodwork': 'hit_woodwork',
    'Touches in penalty area': 'touches_penalty_area', 'Corner kicks': 'corners',
    'Offsides': 'offsides', 'Fouls': 'fouls', 'Goalkeeper saves': 'saves',
    'Total saves': 'saves', 'High claims': 'high_claims',
    'Tackles won': 'tackles_won_pct', 'Duels': 'duels_pct',
    'Interceptions': 'interceptions', 'Recoveries': 'recoveries',
    'Errors lead to a shot': 'errors_lead_to_shot',
}


def parse_stat(val):
    if val is None: return None
    s = str(val).strip()
    if s.endswith('%'):
        try: return float(s[:-1])
        except ValueError: return None
    if '/' in s: s = s.split('/')[0].strip()
    try:
        return float(s) if '.' in s else int(s)
    except ValueError:
        return None


def extract_all(data):
    out = {'error': None}
    # Stats period ALL
    sd = data.get('statistics', {})
    if sd and '_error' not in sd:
        for period in sd.get('statistics', []):
            if period.get('period') != 'ALL':
                continue
            for grp in period.get('groups', []):
                for item in grp.get('statisticsItems', []):
                    col = STAT_MAP.get(item.get('name'))
                    if col:
                        out[f'{col}_l'] = parse_stat(item.get('home'))
                        out[f'{col}_v'] = parse_stat(item.get('away'))
    # Lineups
    ld = data.get('lineups', {})
    if ld and '_error' not in ld:
        for side, suf in [('home', '_l'), ('away', '_v')]:
            team = ld.get(side, {})
            out[f'formation{suf}'] = team.get('formation')
            ratings, ksv = [], 0
            for p in team.get('players', []):
                stats = p.get('statistics') or {}
                r = stats.get('rating')
                if r:
                    try: ratings.append(float(r))
                    except: pass
                k = stats.get('keeperSaveValue')
                if k:
                    try: ksv += float(k)
                    except: pass
            if ratings:
                out[f'avg_rating{suf}'] = sum(ratings)/len(ratings)
                out[f'max_rating{suf}'] = max(ratings)
                out[f'n_players{suf}'] = len(ratings)
            out[f'keeper_save_value{suf}'] = ksv or None
    # Event main + referee
    ed = data.get('event_main', {})
    if ed and '_error' not in ed:
        ev = ed.get('event', {})
        ref = ev.get('referee') or {}
        if isinstance(ref, dict):
            out['referee_name'] = ref.get('name')
            out['referee_id'] = ref.get('id')
            out['referee_yellows'] = ref.get('yellowCards')
            out['referee_reds'] = ref.get('redCards')
            out['referee_games'] = ref.get('games')
    # Shotmap count
    sm = data.get('shotmap', {})
    if sm and '_error' not in sm:
        out['n_shots_shotmap'] = len(sm.get('shotmap', []))
    return out


def insertar(conn, evt_sofa, ev_data, parsed, raw):
    cur = conn.cursor()
    base = {
        'sofa_event_id': evt_sofa,
        'liga': ev_data['liga'],
        'temp': int(ev_data['fecha'][:4]),
        'fecha': ev_data['fecha'],
        'ht': ev_data['ht'],
        'at': ev_data['at'],
        'hg': ev_data['hg'],
        'ag': ev_data['ag'],
        'ingest_ts': datetime.now().isoformat(),
        'error': parsed.get('error'),
    }
    base.update({k: v for k, v in parsed.items() if k != 'error'})
    base['statistics_json'] = json.dumps(raw.get('statistics')) if raw.get('statistics') else None
    base['shotmap_json'] = json.dumps(raw.get('shotmap')) if raw.get('shotmap') else None
    base['lineups_json'] = json.dumps(raw.get('lineups')) if raw.get('lineups') else None

    cols = list(base.keys())
    placeholders = ','.join(['?']*len(cols))
    cur.execute(f"INSERT OR REPLACE INTO sofascore_match_features ({','.join(cols)}) VALUES ({placeholders})",
                [base[c] for c in cols])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dias', type=int, default=7)
    parser.add_argument('--max', type=int, default=30)
    parser.add_argument('--liga', type=str, default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB))
    pendientes = cargar_pendientes(conn, args.dias, args.liga, args.max)
    print(f'Pendientes (últimos {args.dias} días): {len(pendientes)}')

    if not pendientes:
        print('Nada que scrapear.')
        return

    n_ok = 0
    n_no_event = 0
    n_err = 0

    for evt_id, liga, fecha, ht, at, hg, ag in pendientes:
        if _aborted:
            print(f'\n[ABORTED] Restantes: {len(pendientes) - (n_ok + n_no_event + n_err)}')
            break

        liga_id = SOFASCORE_LIGA_IDS.get(liga)
        if not liga_id:
            n_no_event += 1
            continue

        # 1. Buscar event_id SOFA
        sofa_eid = buscar_event_id_sofa(liga_id, fecha, ht, at, liga)
        if not sofa_eid:
            n_no_event += 1
            print(f'  NO EVENT_ID: {liga} {fecha} {ht} vs {at}')
            smart_sleep()
            continue

        # 2. Fetch 4 endpoints
        raw = fetch_4_endpoints(sofa_eid)
        parsed = extract_all(raw)

        # 3. xG_shotmap (computado por motor_xg_v2_14 después)
        ev_data = {'liga': liga, 'fecha': fecha, 'ht': ht, 'at': at, 'hg': hg, 'ag': ag}

        if not args.dry_run:
            insertar(conn, sofa_eid, ev_data, parsed, raw)
            conn.commit()
        n_ok += 1
        print(f'  OK: {liga} {fecha} {ht[:18]:<18s} vs {at[:18]:<18s} sofa_eid={sofa_eid} | shots={parsed.get("n_shots_shotmap", 0)}')
        smart_sleep()

    conn.close()
    print(f'\n=== HOOK SOFA POST-LIQUIDACION ===')
    print(f'OK insertados: {n_ok}')
    print(f'Sin event_id SOFA: {n_no_event}')
    print(f'Errores: {n_err}')
    print(f'Calls totales: {_calls}/{CAP_TOTAL}')

    if n_ok > 0 and not args.dry_run:
        print(f'\nProximo paso recomendado: re-correr xG model + EMA rebuild para {n_ok} partidos nuevos')
        print(f'  py analisis/motor_xg_v2_14_xg_from_shotmap.py')


if __name__ == '__main__':
    main()

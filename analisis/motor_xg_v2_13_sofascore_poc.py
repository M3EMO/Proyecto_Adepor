"""
POC SOFASCORE - backfill season 2026 con safeguards ANTI-BOT agresivos.

Lecciones del bloqueo anterior (Cloudflare 403 challenge tras ~1000 calls):
  1. SofaScore detecta patron de calls rapidas + sin sleep variable
  2. Cuando bloquea, bloquea IP completa (curl_cffi y SeleniumBase tambien afectados)
  3. Recovery requiere cambio de IP o esperar 24h+

Safeguards implementadas:
  - Sleep aleatorizado 1.5-3.5s entre calls (no fixed)
  - Pausa larga 60s cada 50 calls
  - Pausa muy larga 5 min cada 200 calls
  - Cap total: 1500 calls maximo por sesion (de 480 partidos x 4 endpoints + paginacion)
  - Detecto 403 -> ABORT INMEDIATO (no insistir)
  - Logging detallado de cada call con response code
  - User-Agent rotacion entre 5 variantes Chrome reales
  - Cache local incremental (idempotente, resume desde donde quedo)

Modo:
  --schema-only    crear/migrar tabla
  --liga X         restringir liga
  --max N          max partidos por liga
  --pre-check      hacer 1 call test antes de iniciar (verificar que IP no esta bloqueada)
  --dry-run        no inserta
"""

import argparse
import json
import random
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from curl_cffi import requests as creq

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'

SOFASCORE_LIGA_IDS = {
    'Argentina': 155, 'Brasil': 325, 'Bolivia': 16736, 'Peru': 406,
    'Ecuador': 240, 'Venezuela': 231, 'Uruguay': 278, 'Inglaterra': 17,
    'Espana': 8, 'Italia': 23, 'Alemania': 35, 'Francia': 34,
    'Turquia': 52, 'Noruega': 20, 'Chile': 11653, 'Colombia': 152,
}

# === SAFEGUARDS ANTI-BOT ===
SLEEP_MIN = 1.5         # min sleep entre calls
SLEEP_MAX = 3.5         # max sleep
PAUSE_EVERY_N = 50      # pausa larga cada N calls
PAUSE_DURATION = 60     # segundos
LONG_PAUSE_EVERY = 200  # pausa muy larga
LONG_PAUSE_DURATION = 300  # 5 min
CAP_TOTAL = 2000        # cap absoluto sesion (subido de 1500 por user)
ABORT_ON_403 = True     # 403 = abort inmediato

UA_ROTATION = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
]

session = creq.Session()
_call_counter = 0
_session_aborted = False


def smart_sleep():
    """Sleep aleatorizado para parecer humano."""
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def get(url, max_retries=1):
    """GET con safeguards. Retorna dict (con _error si falla) o aborta sesion en 403."""
    global _call_counter, _session_aborted
    if _session_aborted:
        return {'_error': 'session_aborted'}
    if _call_counter >= CAP_TOTAL:
        print(f'\n!!! CAP TOTAL ALCANZADO ({CAP_TOTAL} calls). Abortando sesion preventivamente.')
        _session_aborted = True
        return {'_error': 'cap_reached'}

    # Pausas estrategicas
    if _call_counter > 0 and _call_counter % LONG_PAUSE_EVERY == 0:
        print(f'\n[PAUSA LARGA] {LONG_PAUSE_DURATION}s tras {_call_counter} calls (anti-rate-limit)...')
        time.sleep(LONG_PAUSE_DURATION)
    elif _call_counter > 0 and _call_counter % PAUSE_EVERY_N == 0:
        print(f'\n[PAUSA] {PAUSE_DURATION}s tras {_call_counter} calls...')
        time.sleep(PAUSE_DURATION)

    _call_counter += 1
    headers = {
        'User-Agent': random.choice(UA_ROTATION),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.sofascore.com/',
        'Origin': 'https://www.sofascore.com',
    }
    for attempt in range(max_retries + 1):
        try:
            r = session.get(url, impersonate='chrome', headers=headers, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 403:
                print(f'\n!!! 403 BLOCKED en call #{_call_counter}: {url[:80]}')
                print(f'    Response: {r.text[:200]}')
                if ABORT_ON_403:
                    _session_aborted = True
                return {'_error': f'403_blocked'}
            if r.status_code == 429:
                wait = 30 + attempt * 30
                print(f'\n  429 rate limit, sleeping {wait}s...')
                time.sleep(wait)
                continue
            return {'_error': f'status_{r.status_code}'}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(5)
                continue
            return {'_error': str(e)}
    return {'_error': 'max_retries'}


def pre_check():
    """Test rapido si la IP funciona ANTES de comenzar backfill."""
    print('=== PRE-CHECK ===')
    # Test 1: tournament basico
    d = get('https://api.sofascore.com/api/v1/unique-tournament/155')
    if '_error' in d:
        print(f'FAIL pre-check: {d["_error"]}')
        return False
    print(f'OK tournament endpoint funciona: {d.get("uniqueTournament", {}).get("name")}')
    smart_sleep()
    # Test 2: event endpoint
    d = get('https://api.sofascore.com/api/v1/event/15269961')
    if '_error' in d:
        print(f'FAIL event endpoint: {d["_error"]}')
        return False
    print(f'OK event endpoint funciona: {d.get("event", {}).get("homeTeam", {}).get("name")}')
    smart_sleep()
    print('Pre-check PASS. IP funciona.\n')
    return True


def crear_schema(con):
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sofascore_match_features (
            sofa_event_id INTEGER PRIMARY KEY,
            liga TEXT NOT NULL,
            temp INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            ts_start INTEGER,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            ht_id INTEGER,
            at_id INTEGER,
            hg INTEGER,
            ag INTEGER,
            ball_possession_l REAL, ball_possession_v REAL,
            big_chances_l INTEGER, big_chances_v INTEGER,
            big_chances_missed_l INTEGER, big_chances_missed_v INTEGER,
            shots_total_l INTEGER, shots_total_v INTEGER,
            shots_on_target_l INTEGER, shots_on_target_v INTEGER,
            shots_off_target_l INTEGER, shots_off_target_v INTEGER,
            shots_inside_box_l INTEGER, shots_inside_box_v INTEGER,
            shots_outside_box_l INTEGER, shots_outside_box_v INTEGER,
            blocked_shots_l INTEGER, blocked_shots_v INTEGER,
            hit_woodwork_l INTEGER, hit_woodwork_v INTEGER,
            touches_penalty_area_l INTEGER, touches_penalty_area_v INTEGER,
            corners_l INTEGER, corners_v INTEGER,
            offsides_l INTEGER, offsides_v INTEGER,
            fouls_l INTEGER, fouls_v INTEGER,
            saves_l INTEGER, saves_v INTEGER,
            high_claims_l INTEGER, high_claims_v INTEGER,
            tackles_won_pct_l REAL, tackles_won_pct_v REAL,
            duels_pct_l REAL, duels_pct_v REAL,
            interceptions_l INTEGER, interceptions_v INTEGER,
            recoveries_l INTEGER, recoveries_v INTEGER,
            errors_lead_to_shot_l INTEGER, errors_lead_to_shot_v INTEGER,
            formation_l TEXT, formation_v TEXT,
            manager_l TEXT, manager_v TEXT,
            avg_rating_l REAL, avg_rating_v REAL,
            max_rating_l REAL, max_rating_v REAL,
            n_players_l INTEGER, n_players_v INTEGER,
            xg_shotmap_l REAL, xg_shotmap_v REAL,
            n_shots_shotmap INTEGER,
            referee_name TEXT, referee_id INTEGER,
            referee_yellows INTEGER, referee_reds INTEGER, referee_games INTEGER,
            keeper_save_value_l REAL, keeper_save_value_v REAL,
            statistics_json TEXT,
            shotmap_json TEXT,
            lineups_json TEXT,
            ingest_ts TEXT NOT NULL,
            error TEXT
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sof_liga_temp ON sofascore_match_features(liga, temp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sof_fecha ON sofascore_match_features(fecha)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sof_teams ON sofascore_match_features(ht, at, fecha)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sof_referee ON sofascore_match_features(referee_id)')
    con.commit()


def get_season_id(unique_tournament_id):
    d = get(f'https://api.sofascore.com/api/v1/unique-tournament/{unique_tournament_id}/seasons')
    if not d or '_error' in d:
        return None, None
    seasons = d.get('seasons', [])
    s = seasons[0] if seasons else None
    return (s.get('id'), s.get('name')) if s else (None, None)


def get_eventos_terminados(unique_tournament_id, season_id, max_pages=2, fecha_min=None):
    eventos = []
    for page in range(0, max_pages):
        d = get(f'https://api.sofascore.com/api/v1/unique-tournament/{unique_tournament_id}/season/{season_id}/events/last/{page}')
        if not d or '_error' in d:
            break
        chunk = d.get('events', [])
        if not chunk:
            break
        eventos.extend(chunk)
        smart_sleep()
    out = [e for e in eventos if e.get('status', {}).get('description') == 'Ended']
    if fecha_min:
        cutoff = datetime.fromisoformat(fecha_min).timestamp()
        out = [e for e in out if (e.get('startTimestamp') or 0) >= cutoff]
    return out


def fetch_4_endpoints(event_id):
    out = {}
    out['statistics'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics')
    if _session_aborted:
        return out
    smart_sleep()
    out['shotmap'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/shotmap')
    if _session_aborted:
        return out
    smart_sleep()
    out['lineups'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/lineups')
    if _session_aborted:
        return out
    smart_sleep()
    out['event_main'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}')
    return out


STAT_MAP_RAW = {
    'Ball possession': 'ball_possession',
    'Big chances': 'big_chances',
    'Big chances missed': 'big_chances_missed',
    'Total shots': 'shots_total',
    'Shots on target': 'shots_on_target',
    'Shots off target': 'shots_off_target',
    'Shots inside box': 'shots_inside_box',
    'Shots outside box': 'shots_outside_box',
    'Blocked shots': 'blocked_shots',
    'Hit woodwork': 'hit_woodwork',
    'Touches in penalty area': 'touches_penalty_area',
    'Corner kicks': 'corners',
    'Offsides': 'offsides',
    'Fouls': 'fouls',
    'Goalkeeper saves': 'saves',
    'Total saves': 'saves',
    'High claims': 'high_claims',
    'Tackles won': 'tackles_won_pct',
    'Duels': 'duels_pct',
    'Interceptions': 'interceptions',
    'Recoveries': 'recoveries',
    'Errors lead to a shot': 'errors_lead_to_shot',
}


def parse_stat_value(val):
    if val is None:
        return None
    s = str(val).strip()
    if s.endswith('%'):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    if '/' in s:
        s = s.split('/')[0].strip()
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except ValueError:
        return None


def extract_stats(stats_data):
    out = {}
    if not stats_data or '_error' in stats_data:
        return out
    for period_obj in stats_data.get('statistics', []):
        if period_obj.get('period') != 'ALL':
            continue
        for grp in period_obj.get('groups', []):
            for item in grp.get('statisticsItems', []):
                col = STAT_MAP_RAW.get(item.get('name'))
                if not col:
                    continue
                out[f'{col}_l'] = parse_stat_value(item.get('home'))
                out[f'{col}_v'] = parse_stat_value(item.get('away'))
    return out


def extract_lineups(lineups_data):
    out = {}
    if not lineups_data or '_error' in lineups_data:
        return out
    for side, suf in [('home', '_l'), ('away', '_v')]:
        team = lineups_data.get(side, {})
        out[f'formation{suf}'] = team.get('formation')
        players = team.get('players', [])
        ratings = []
        keeper_save_value = 0
        for p in players:
            stats = (p.get('statistics') or {})
            r = stats.get('rating')
            if r is not None:
                try:
                    ratings.append(float(r))
                except (TypeError, ValueError):
                    pass
            ksv = stats.get('keeperSaveValue')
            if ksv:
                try:
                    keeper_save_value += float(ksv)
                except (TypeError, ValueError):
                    pass
        if ratings:
            out[f'avg_rating{suf}'] = sum(ratings) / len(ratings)
            out[f'max_rating{suf}'] = max(ratings)
            out[f'n_players{suf}'] = len(ratings)
        else:
            out[f'avg_rating{suf}'] = None
            out[f'max_rating{suf}'] = None
            out[f'n_players{suf}'] = 0
        out[f'keeper_save_value{suf}'] = keeper_save_value or None
    return out


def extract_event_main(event_data):
    out = {}
    if not event_data or '_error' in event_data:
        return out
    ev = event_data.get('event', {})
    ref = ev.get('referee') or {}
    if isinstance(ref, dict):
        out['referee_name'] = ref.get('name')
        out['referee_id'] = ref.get('id')
        out['referee_yellows'] = ref.get('yellowCards')
        out['referee_reds'] = ref.get('redCards')
        out['referee_games'] = ref.get('games')
    return out


def extract_shotmap_basic(shotmap_data):
    if not shotmap_data or '_error' in shotmap_data:
        return None, None, 0
    shots = shotmap_data.get('shotmap', [])
    return None, None, len(shots)  # xG calculado luego


def insertar_evento(con, ev, all_data, payload):
    cur = con.cursor()
    base = {
        'sofa_event_id': ev['id'],
        'liga': ev.get('_liga'),
        'temp': ev.get('_temp'),
        'fecha': ev.get('_fecha'),
        'ts_start': ev.get('startTimestamp'),
        'ht': (ev.get('homeTeam') or {}).get('name'),
        'at': (ev.get('awayTeam') or {}).get('name'),
        'ht_id': (ev.get('homeTeam') or {}).get('id'),
        'at_id': (ev.get('awayTeam') or {}).get('id'),
        'hg': (ev.get('homeScore') or {}).get('current'),
        'ag': (ev.get('awayScore') or {}).get('current'),
        'ingest_ts': datetime.now().isoformat(),
        'error': payload.get('_error'),
    }
    base.update(payload.get('stats', {}))
    base.update(payload.get('lineup', {}))
    base.update(payload.get('referee', {}))
    _, _, ns = payload.get('xg_shotmap', (None, None, 0))
    base['xg_shotmap_l'] = None
    base['xg_shotmap_v'] = None
    base['n_shots_shotmap'] = ns
    base['statistics_json'] = json.dumps(all_data.get('statistics')) if all_data.get('statistics') else None
    base['shotmap_json'] = json.dumps(all_data.get('shotmap')) if all_data.get('shotmap') else None
    base['lineups_json'] = json.dumps(all_data.get('lineups')) if all_data.get('lineups') else None

    cols = list(base.keys())
    placeholders = ','.join(['?'] * len(cols))
    sql = f"INSERT OR REPLACE INTO sofascore_match_features ({','.join(cols)}) VALUES ({placeholders})"
    cur.execute(sql, [base[c] for c in cols])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--schema-only', action='store_true')
    parser.add_argument('--liga', type=str, default=None)
    parser.add_argument('--max', type=int, default=None)
    parser.add_argument('--pre-check', action='store_true', help='Test 1 call before starting')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--fecha-min', type=str, default='2026-03-01')
    args = parser.parse_args()

    con = sqlite3.connect(str(DB))
    crear_schema(con)
    if args.schema_only:
        print('Schema OK')
        con.close()
        return

    if args.pre_check:
        if not pre_check():
            print('IP bloqueada. NO continuar.')
            con.close()
            sys.exit(1)

    target_ligas = [args.liga] if args.liga else list(SOFASCORE_LIGA_IDS.keys())
    print(f'Backfilling SofaScore POC season 2026 - {len(target_ligas)} ligas')
    print(f'Safeguards: sleep {SLEEP_MIN}-{SLEEP_MAX}s, pausa {PAUSE_DURATION}s/{PAUSE_EVERY_N} calls, cap {CAP_TOTAL}\n')

    total_ok = 0
    total_err = 0
    t0 = time.time()

    for liga in target_ligas:
        if _session_aborted:
            print(f'[{liga}] SESSION ABORTED, skipping')
            continue
        utid = SOFASCORE_LIGA_IDS[liga]
        sid, sname = get_season_id(utid)
        if not sid:
            print(f'[{liga}] sin season id (likely 403)')
            continue
        print(f'[{liga}] season "{sname}" id={sid}')
        eventos = get_eventos_terminados(utid, sid, max_pages=2, fecha_min=args.fecha_min)
        if args.max:
            eventos = eventos[:args.max]
        print(f'  {len(eventos)} eventos terminados (post {args.fecha_min})')

        cur = con.cursor()
        existentes = set(r[0] for r in cur.execute('SELECT sofa_event_id FROM sofascore_match_features').fetchall())
        pendientes = [e for e in eventos if e['id'] not in existentes]
        print(f'  {len(pendientes)} pendientes (no en DB)')

        for i, ev in enumerate(pendientes, 1):
            if _session_aborted:
                print(f'  [{liga}] ABORTED en {i-1}/{len(pendientes)}')
                break
            ev['_liga'] = liga
            ev['_temp'] = 2026
            ts = ev.get('startTimestamp')
            if ts:
                ev['_fecha'] = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            else:
                ev['_fecha'] = None

            data = fetch_4_endpoints(ev['id'])
            err = None
            errores = [v.get('_error') for v in data.values() if isinstance(v, dict) and '_error' in v]
            if errores and all('403' in str(e) for e in errores):
                err = '403_blocked'

            stats = extract_stats(data['statistics'])
            xg = extract_shotmap_basic(data['shotmap'])
            lineup = extract_lineups(data['lineups'])
            referee = extract_event_main(data['event_main'])

            payload = {
                'stats': stats, 'lineup': lineup, 'referee': referee,
                'xg_shotmap': xg, '_error': err,
            }

            if not args.dry_run:
                insertar_evento(con, ev, data, payload)
                if i % 10 == 0:
                    con.commit()
            if err:
                total_err += 1
            else:
                total_ok += 1

            if i % 10 == 0 or i == len(pendientes):
                elapsed = time.time() - t0
                rate = _call_counter / elapsed if elapsed > 0 else 0
                print(f'  [{i}/{len(pendientes)}] OK={total_ok} err={total_err} | calls={_call_counter} rate={rate:.2f}/s elapsed={elapsed:.0f}s')

            smart_sleep()

        if not args.dry_run:
            con.commit()

    con.close()
    elapsed = time.time() - t0
    print(f'\n=== POC FINAL ===')
    print(f'Total OK: {total_ok}')
    print(f'Total error: {total_err}')
    print(f'Total calls realizadas: {_call_counter}')
    print(f'Aborted: {_session_aborted}')
    print(f'Elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)')


if __name__ == '__main__':
    main()

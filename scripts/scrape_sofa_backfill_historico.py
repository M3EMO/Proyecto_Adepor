"""Backfill SOFA histórico 2022-2025 — sesiones acotadas con cap 1500.

Diseñado para ejecutarse periódicamente (cron / Task Scheduler) cada ~32H.
Cada ejecución:
  1. Identifica partidos pendientes (en partidos_backtest o
     partidos_historico_externo, fecha 2022-2025, sin entry en
     sofascore_match_features).
  2. Itera hasta CAP_TOTAL=1500 calls SOFA (~370 partidos x 4 endpoints).
  3. Persiste cada partido completado individualmente (idempotente).
  4. Aborta limpio en 403/429/CAP. Próxima ejecución continúa donde quedó.

Anti-bot:
  - Sleep 1.5-3.5s entre calls.
  - Pausa 60s cada 50 calls.
  - User-Agent rotation.
  - 403 → abort total + log aborted_reason='403_blocked'.

Uso (manual):
  py scripts/scrape_sofa_backfill_historico.py
  py scripts/scrape_sofa_backfill_historico.py --cap 500          # cap más bajo
  py scripts/scrape_sofa_backfill_historico.py --liga Argentina    # solo una liga
  py scripts/scrape_sofa_backfill_historico.py --dry-run           # contar pendientes

Uso (scheduled):
  schtasks /create /tn "Adepor_SOFA_Backfill" /tr "py C:\\...\\scrape_sofa_backfill_historico.py" /sc daily /ri 1920 /du 9999:00
  (donde 1920 min = 32 horas)
"""
import argparse
import json
import random
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as creq
from analisis.aliases_sofa_espn import norm_team_name

DB = ROOT / 'fondo_quant.db'

SOFASCORE_LIGA_IDS = {
    # Ligas domésticas (verificadas pre-2026-05-07)
    'Argentina': 155, 'Brasil': 325, 'Bolivia': 16736, 'Peru': 406,
    'Ecuador': 240, 'Venezuela': 231, 'Uruguay': 278, 'Inglaterra': 17,
    'Espana': 8, 'Italia': 23, 'Alemania': 35, 'Francia': 34,
    'Turquia': 52, 'Noruega': 20, 'Chile': 11653, 'Colombia': 152,
    # EU expansion (probe 2026-05-07)
    'Holanda': 37, 'Portugal': 238, 'Escocia': 36,
    'Dinamarca': 39, 'Belgica': 38, 'Grecia': 185, 'Suecia': 40,
    # Copas internacionales (probe 2026-05-08, todas xgot completo verificado en SOFA)
    'Champions League': 7,
    'Europa League': 679,
    'Conference League': 17015,
    'Libertadores': 384,
    'Sudamericana': 480,
    'Recopa Sudamericana': 490,
    # Copas domésticas (probe 2026-05-08)
    'FA Cup': 19,
    'EFL Cup': 21,
    'Copa del Rey': 329,
    'Coppa Italia': 328,
    'Coupe de France': 335,
    'DFB Pokal': 217,
    'Copa Argentina': 1024,
    'Copa do Brasil': 373,
}

CAP_TOTAL_DEFAULT = 1500     # Por sesión (cron 32H)
SLEEP_MIN = 1.5
SLEEP_MAX = 3.5
PAUSE_EVERY_N = 50
PAUSE_DURATION = 60

UA_ROTATION = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
]

session = creq.Session()


class State:
    def __init__(self, cap):
        self.calls = 0
        self.cap = cap
        self.aborted = False
        self.abort_reason = None


def smart_sleep():
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def get(url, st):
    if st.aborted:
        return {'_error': 'aborted'}
    if st.calls >= st.cap:
        st.aborted = True
        st.abort_reason = 'cap_alcanzado'
        return {'_error': 'cap'}
    if st.calls > 0 and st.calls % PAUSE_EVERY_N == 0:
        print(f'  [pausa {PAUSE_DURATION}s tras {st.calls} calls]', flush=True)
        time.sleep(PAUSE_DURATION)
    st.calls += 1
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
            print(f'\n!!! 403 BLOCKED en call #{st.calls}. Abort total.', flush=True)
            st.aborted = True
            st.abort_reason = '403_blocked'
            return {'_error': '403'}
        if r.status_code == 429:
            time.sleep(30)
            return {'_error': '429'}
        return {'_error': f'status_{r.status_code}'}
    except Exception as e:
        return {'_error': str(e)}


def cargar_pendientes(conn, liga=None, fecha_min='2022-01-01', fecha_max='2026-12-31', max_n=None):
    """Partidos pendientes (con goles) en rango fecha, de ligas SOFA-cubiertas,
    sin entry en sofascore_match_features.

    Driver universe UNION:
      - partidos_historico_externo: 2021-2025 (~14k stats crudas)
      - partidos_backtest:          2026 picks históricos motor
    Filter: liga ∈ SOFASCORE_LIGA_IDS keys.

    Dedup robusta (2026-05-07 fix): en lugar de NOT EXISTS LOWER simple
    (que falla en 'AFC Bournemouth' vs 'Bournemouth', 'Bodø' vs 'Bodo', etc),
    se hace pre-filter en Python con norm_team_name + dedup cross-tabla
    (mismo partido en historico_externo Y backtest no se duplica).
    """
    cur = conn.cursor()
    # Pre-load índice SOFA por (liga, fecha, norm_ht, norm_at)
    sofa_idx = set()
    for s_liga, s_fecha, s_ht, s_at in cur.execute(
        'SELECT liga, fecha, ht, at FROM sofascore_match_features'
    ).fetchall():
        sofa_idx.add((s_liga, s_fecha, norm_team_name(s_ht, s_liga), norm_team_name(s_at, s_liga)))

    # Build queries (sin NOT EXISTS, dedup en Python)
    if liga:
        liga_filter_he = 'AND p.liga=?'
        liga_filter_pb = 'AND p.pais=?'
        liga_params_he = [liga]
        liga_params_pb = [liga]
    else:
        ligas_sofa = list(SOFASCORE_LIGA_IDS.keys())
        ph = ', '.join(['?'] * len(ligas_sofa))
        liga_filter_he = f'AND p.liga IN ({ph})'
        liga_filter_pb = f'AND p.pais IN ({ph})'
        liga_params_he = ligas_sofa
        liga_params_pb = ligas_sofa

    rows = []
    # Source 1: partidos_historico_externo (ligas 2021-2025)
    rows.extend(cur.execute(f'''
        SELECT 'he_' || p.id, p.liga, SUBSTR(p.fecha,1,10), p.ht, p.at
        FROM partidos_historico_externo p
        WHERE SUBSTR(p.fecha,1,10) >= ? AND SUBSTR(p.fecha,1,10) <= ?
          AND p.hg IS NOT NULL
          {liga_filter_he}
    ''', [fecha_min, fecha_max] + liga_params_he).fetchall())
    # Source 2: partidos_backtest (2026 driver)
    rows.extend(cur.execute(f'''
        SELECT 'pb_' || p.id_partido, p.pais, SUBSTR(p.fecha,1,10), p.local, p.visita
        FROM partidos_backtest p
        WHERE SUBSTR(p.fecha,1,10) >= ? AND SUBSTR(p.fecha,1,10) <= ?
          AND p.goles_l IS NOT NULL
          {liga_filter_pb}
    ''', [fecha_min, fecha_max] + liga_params_pb).fetchall())
    # Source 3: partidos_no_liga (copas internacionales + nacionales 2022-2026)
    if liga:
        liga_filter_nl = 'AND p.competicion=?'
        liga_params_nl = [liga]
    else:
        liga_params_nl = list(SOFASCORE_LIGA_IDS.keys())
        ph = ', '.join(['?'] * len(liga_params_nl))
        liga_filter_nl = f'AND p.competicion IN ({ph})'
    rows.extend(cur.execute(f'''
        SELECT 'nl_' || p.id, p.competicion, SUBSTR(p.fecha,1,10), p.equipo_local, p.equipo_visita
        FROM partidos_no_liga p
        WHERE SUBSTR(p.fecha,1,10) >= ? AND SUBSTR(p.fecha,1,10) <= ?
          AND p.goles_l IS NOT NULL
          {liga_filter_nl}
    ''', [fecha_min, fecha_max] + liga_params_nl).fetchall())

    # Filter en Python: skip si ya en SOFA via norm; dedup cross-tabla
    seen = set()
    pendientes = []
    for uid, p_liga, p_fecha, p_ht, p_at in rows:
        key = (p_liga, p_fecha, norm_team_name(p_ht, p_liga), norm_team_name(p_at, p_liga))
        if key in sofa_idx:
            continue  # ya scrapeado
        if key in seen:
            continue  # duplicado entre historico_externo y backtest
        seen.add(key)
        pendientes.append((uid, p_liga, p_fecha, p_ht, p_at))

    # Sort por fecha DESC
    pendientes.sort(key=lambda x: x[2], reverse=True)
    if max_n:
        pendientes = pendientes[:max_n]
    return pendientes


def eid_ya_existe(conn, sofa_eid):
    """Check if sofa_event_id ya está en sofascore_match_features (con error IS NULL)."""
    r = conn.execute('SELECT 1 FROM sofascore_match_features WHERE sofa_event_id=? AND error IS NULL',
                     (sofa_eid,)).fetchone()
    return r is not None


def buscar_event_id_sofa(liga_id, fecha, ht, at, liga, st):
    url = f'https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha}'
    d = get(url, st)
    if not d or '_error' in d:
        return None
    ht_n = norm_team_name(ht, liga)
    at_n = norm_team_name(at, liga)
    for ev in d.get('events', []):
        ut = ev.get('tournament', {}).get('uniqueTournament', {})
        if ut.get('id') != liga_id:
            continue
        sofa_ht = ev.get('homeTeam', {}).get('name', '')
        sofa_at = ev.get('awayTeam', {}).get('name', '')
        if (norm_team_name(sofa_ht, liga) == ht_n and
            norm_team_name(sofa_at, liga) == at_n):
            return ev.get('id')
    return None


def fetch_4_endpoints(event_id, st):
    out = {}
    out['statistics'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics', st)
    smart_sleep()
    out['shotmap'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/shotmap', st)
    smart_sleep()
    out['lineups'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}/lineups', st)
    smart_sleep()
    out['event_main'] = get(f'https://api.sofascore.com/api/v1/event/{event_id}', st)
    return out


def parse_value(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s.endswith('%'):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    try:
        return float(s.split(' ')[0])
    except (ValueError, IndexError):
        return None


def parse_to_row(raw):
    """Extrae cols principales del raw → dict compatible con sofascore_match_features."""
    out = {
        'shots_total_l': None, 'shots_total_v': None,
        'shots_on_target_l': None, 'shots_on_target_v': None,
        'shots_off_target_l': None, 'shots_off_target_v': None,
        'shots_inside_box_l': None, 'shots_inside_box_v': None,
        'shots_outside_box_l': None, 'shots_outside_box_v': None,
        'blocked_shots_l': None, 'blocked_shots_v': None,
        'corners_l': None, 'corners_v': None,
        'errors_lead_to_shot_l': None, 'errors_lead_to_shot_v': None,
        'formation_l': None, 'formation_v': None,
        'avg_rating_l': None, 'avg_rating_v': None,
        'max_rating_l': None, 'max_rating_v': None,
        'xg_shotmap_l': None, 'xg_shotmap_v': None,
        'xg_v3_l': None, 'xg_v3_v': None,
        'n_shots_shotmap': None,
    }
    stats = raw.get('statistics', {})
    if isinstance(stats, dict) and 'statistics' in stats:
        for periodo in stats.get('statistics', []):
            if periodo.get('period') != 'ALL':
                continue
            for grp in periodo.get('groups', []):
                for it in grp.get('statisticsItems', []):
                    name = it.get('name', '')
                    h = parse_value(it.get('homeValue'))
                    a = parse_value(it.get('awayValue'))
                    if name == 'Total shots':
                        out['shots_total_l'], out['shots_total_v'] = h, a
                    elif name == 'Shots on target':
                        out['shots_on_target_l'], out['shots_on_target_v'] = h, a
                    elif name == 'Shots off target':
                        out['shots_off_target_l'], out['shots_off_target_v'] = h, a
                    elif name == 'Shots inside box':
                        out['shots_inside_box_l'], out['shots_inside_box_v'] = h, a
                    elif name == 'Shots outside box':
                        out['shots_outside_box_l'], out['shots_outside_box_v'] = h, a
                    elif name == 'Blocked shots':
                        out['blocked_shots_l'], out['blocked_shots_v'] = h, a
                    elif name == 'Corner kicks':
                        out['corners_l'], out['corners_v'] = h, a
                    elif name == 'Errors lead to shot':
                        out['errors_lead_to_shot_l'], out['errors_lead_to_shot_v'] = h, a
    shotmap = raw.get('shotmap', {})
    if isinstance(shotmap, dict) and 'shotmap' in shotmap:
        shots = shotmap.get('shotmap', [])
        out['n_shots_shotmap'] = len(shots)
        sum_xg_l = sum(s.get('xg', 0) for s in shots if s.get('isHome') and s.get('xg') is not None)
        sum_xg_v = sum(s.get('xg', 0) for s in shots if not s.get('isHome') and s.get('xg') is not None)
        out['xg_shotmap_l'] = sum_xg_l
        out['xg_shotmap_v'] = sum_xg_v
        # xg_v3 = xgot directo si existe + custom fallback
        sum_xgot_l = sum((s.get('xgot') if s.get('xgot') is not None else s.get('xg', 0))
                        for s in shots if s.get('isHome'))
        sum_xgot_v = sum((s.get('xgot') if s.get('xgot') is not None else s.get('xg', 0))
                        for s in shots if not s.get('isHome'))
        out['xg_v3_l'] = sum_xgot_l
        out['xg_v3_v'] = sum_xgot_v
    lineups = raw.get('lineups', {})
    if isinstance(lineups, dict):
        out['formation_l'] = lineups.get('home', {}).get('formation')
        out['formation_v'] = lineups.get('away', {}).get('formation')
        for lado, key in [('l', 'home'), ('v', 'away')]:
            players = lineups.get(key, {}).get('players', [])
            ratings = [p.get('statistics', {}).get('rating') for p in players]
            ratings = [r for r in ratings if r is not None]
            if ratings:
                out[f'avg_rating_{lado}'] = sum(ratings) / len(ratings)
                out[f'max_rating_{lado}'] = max(ratings)
    return out


def insertar(conn, sofa_eid, liga, fecha, ht, at, parsed, raw):
    cur = conn.cursor()
    cols = list(parsed.keys())
    # base cols requeridos: sofa_event_id, liga, temp, fecha, ht, at,
    # statistics_json, shotmap_json, error, ingest_ts (10)
    placeholders = ', '.join(['?'] * (len(cols) + 10))
    cols_sql = ', '.join(cols)
    temp = int(fecha[:4])
    ingest_ts = datetime.now().isoformat()
    cur.execute(f'''
        INSERT OR REPLACE INTO sofascore_match_features (
            sofa_event_id, liga, temp, fecha, ht, at,
            {cols_sql},
            statistics_json, shotmap_json, error, ingest_ts
        ) VALUES ({placeholders})
    ''', (
        sofa_eid, liga, temp, fecha, ht, at,
        *[parsed[c] for c in cols],
        json.dumps(raw.get('statistics', {})),
        json.dumps(raw.get('shotmap', {})),
        None,
        ingest_ts,
    ))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cap', type=int, default=CAP_TOTAL_DEFAULT)
    ap.add_argument('--liga', type=str, default=None)
    ap.add_argument('--fecha-min', default='2022-01-01')
    ap.add_argument('--fecha-max', default='2026-12-31')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    pendientes = cargar_pendientes(conn, liga=args.liga,
                                   fecha_min=args.fecha_min,
                                   fecha_max=args.fecha_max)
    print(f'[INFO] Pendientes: {len(pendientes)} partidos')
    if args.dry_run:
        from collections import Counter
        per_liga = Counter(r[1] for r in pendientes)
        for liga, n in per_liga.most_common():
            print(f'  {liga:<15s} {n}')
        return

    st = State(args.cap)
    print(f'[INFO] Cap: {st.cap} calls. Procesando...')
    n_ok = 0
    n_skip = 0
    n_err = 0
    inicio = time.time()
    for id_p, liga, fecha, ht, at in pendientes:
        if st.aborted:
            break
        liga_id = SOFASCORE_LIGA_IDS.get(liga)
        if liga_id is None:
            n_skip += 1
            continue
        eid = buscar_event_id_sofa(liga_id, fecha, ht, at, liga, st)
        if eid is None:
            n_skip += 1
            continue
        if st.aborted:
            break
        # Guard: si eid ya en DB (otro partido_backtest/historico apuntó al mismo evento),
        # skip 4-endpoints fetch para no desperdiciar 4 calls del cap.
        if eid_ya_existe(conn, eid):
            n_skip += 1
            continue
        raw = fetch_4_endpoints(eid, st)
        if st.aborted and raw.get('statistics', {}).get('_error'):
            break
        parsed = parse_to_row(raw)
        try:
            insertar(conn, eid, liga, fecha, ht, at, parsed, raw)
            n_ok += 1
            if n_ok % 25 == 0:
                elapsed = time.time() - inicio
                print(f'  {n_ok} OK | {st.calls}/{st.cap} calls | {elapsed:.0f}s', flush=True)
        except Exception as e:
            n_err += 1
            print(f'  ERR insert {liga} {fecha} {ht}: {e}', flush=True)

    elapsed = time.time() - inicio
    print(f'\n[FIN] OK={n_ok} skip={n_skip} err={n_err} calls={st.calls}/{st.cap}')
    print(f'[FIN] Tiempo total: {elapsed:.0f}s ({elapsed/60:.1f} min)')
    if st.aborted:
        print(f'[FIN] Aborted: {st.abort_reason}')
    print(f'[FIN] Próxima ejecución continuará desde donde quedó (idempotente).')
    conn.close()


if __name__ == '__main__':
    main()

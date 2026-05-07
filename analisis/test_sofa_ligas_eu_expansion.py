"""Test: ¿SofaScore expone statistics + shotmap para ligas EU NO integradas?

Probamos NED, POR, SCO, SWE, DEN sobre eventos liquidados recientes.
Si SOFA tiene stats pero ESPN no, la liga ES viable via SOFA-only path.
"""
import sys
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as creq

# uniqueTournament.id en SofaScore (verificados en sofascore.com)
LIGAS_TEST = {
    'Escocia Premiership': 36,
    'Suecia Allsvenskan': 40,
}

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
HDR = {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.sofascore.com/',
    'Origin': 'https://www.sofascore.com',
}

session = creq.Session()


def get(url):
    try:
        r = session.get(url, impersonate='chrome', headers=HDR, timeout=20)
        if r.status_code == 200:
            return r.json()
        return {'_error': f'status_{r.status_code}'}
    except Exception as e:
        return {'_error': str(e)}


def probar_liga(nombre, tid):
    print(f'\n=== {nombre} (tid={tid}) ===')
    # Step 1: ultima season
    d = get(f'https://api.sofascore.com/api/v1/unique-tournament/{tid}/seasons')
    if '_error' in d:
        print(f'  FAIL seasons: {d}')
        return
    seasons = d.get('seasons', [])
    if not seasons:
        print('  FAIL: 0 seasons')
        return
    s_recent = seasons[0]
    sid = s_recent['id']
    sname = s_recent.get('year', s_recent.get('name', '?'))
    print(f'  season_recent={sname} sid={sid}')
    time.sleep(random.uniform(1.0, 2.0))

    # Step 2: eventos recientes (last)
    d2 = get(f'https://api.sofascore.com/api/v1/unique-tournament/{tid}/season/{sid}/events/last/0')
    if '_error' in d2:
        print(f'  FAIL events: {d2}')
        return
    eventos = d2.get('events', [])
    if not eventos:
        print('  FAIL: 0 eventos last/0')
        return
    print(f'  N eventos last page: {len(eventos)}')
    # Tomar primer evento finished con score
    ev = None
    for e in eventos:
        if e.get('status', {}).get('type') == 'finished':
            ev = e
            break
    if not ev:
        print('  FAIL: 0 finished')
        return
    eid = ev['id']
    ht = ev.get('homeTeam', {}).get('name', '?')
    at = ev.get('awayTeam', {}).get('name', '?')
    fecha = time.strftime('%Y-%m-%d', time.localtime(ev.get('startTimestamp', 0)))
    print(f'  event_test eid={eid} {fecha} {ht} vs {at}')
    time.sleep(random.uniform(1.0, 2.0))

    # Step 3: probar 3 endpoints clave
    for ep in ['statistics', 'shotmap', 'lineups']:
        d3 = get(f'https://api.sofascore.com/api/v1/event/{eid}/{ep}')
        if '_error' in d3:
            print(f'    {ep:<12s} FAIL {d3}')
        else:
            n = 0
            if ep == 'statistics':
                stats = d3.get('statistics', [])
                groups = sum(len(p.get('groups', [])) for p in stats)
                items = sum(len(g.get('statisticsItems', [])) for p in stats for g in p.get('groups', []))
                n = items
                print(f'    {ep:<12s} OK (periodos={len(stats)} groups={groups} items={items})')
            elif ep == 'shotmap':
                n = len(d3.get('shotmap', []))
                xgot_count = sum(1 for s in d3.get('shotmap', []) if s.get('xgot') is not None)
                xg_count = sum(1 for s in d3.get('shotmap', []) if s.get('xg') is not None)
                print(f'    {ep:<12s} OK (n_shots={n} xg_present={xg_count} xgot_present={xgot_count})')
            elif ep == 'lineups':
                home = d3.get('home', {})
                away = d3.get('away', {})
                fmt_h = home.get('formation', '?')
                fmt_a = away.get('formation', '?')
                print(f'    {ep:<12s} OK (formation_h={fmt_h} formation_a={fmt_a})')
        time.sleep(random.uniform(1.0, 2.0))


if __name__ == '__main__':
    for nombre, tid in LIGAS_TEST.items():
        probar_liga(nombre, tid)
        time.sleep(random.uniform(2.0, 4.0))
    print('\n=== Test completo ===')

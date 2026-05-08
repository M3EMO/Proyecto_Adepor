"""Search SofaScore para encontrar uniqueTournament IDs de copas."""
import sys
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as creq

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


queries = [
    'UEFA Champions League',
    'UEFA Europa League',
    'UEFA Conference League',
    'Copa Libertadores',
    'Copa Sudamericana',
    'Recopa Sudamericana',
    'FA Cup',
    'EFL Cup',
    'Carabao Cup',
    'Copa del Rey',
    'Coppa Italia',
    'Coupe de France',
    'DFB Pokal',
    'Copa Argentina',
    'Copa do Brasil',
]

for q in queries:
    print(f'\n=== search: {q} ===')
    d = get(f'https://api.sofascore.com/api/v1/search/all?q={q.replace(" ", "%20")}&page=0')
    if '_error' in d:
        print(f'  FAIL {d}')
        continue
    results = d.get('results', [])
    for r in results[:5]:
        if r.get('type') != 'uniqueTournament':
            continue
        e = r.get('entity', {})
        tname = e.get('name', '')
        country = e.get('category', {}).get('country', {}).get('name', '')
        sport = e.get('category', {}).get('sport', {}).get('name', '')
        cid = e.get('id')
        if sport == 'Football':
            print(f'  id={cid:<8} country={country:<25s} name={tname}')
    time.sleep(random.uniform(1.0, 2.0))

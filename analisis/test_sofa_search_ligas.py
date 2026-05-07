"""Search SofaScore para encontrar uniqueTournament IDs reales de ligas."""
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


queries = ['Allsvenskan', 'Scottish Premiership', 'Eliteserien', 'Superettan']
for q in queries:
    print(f'\n=== search: {q} ===')
    d = get(f'https://api.sofascore.com/api/v1/search/all?q={q}&page=0')
    if '_error' in d:
        print(f'  FAIL {d}')
        continue
    results = d.get('results', [])
    for r in results[:8]:
        e = r.get('entity', {})
        tname = e.get('name', '')
        country = e.get('category', {}).get('country', {}).get('name', '')
        cid = e.get('id')
        ut = e.get('uniqueTournament', {})
        ut_id = e.get('id') if r.get('type') == 'uniqueTournament' else ut.get('id')
        sport = e.get('category', {}).get('sport', {}).get('name', '')
        print(f'  {r.get("type", "?"):<20s} id={cid:<8} sport={sport:<12s} country={country:<20s} name={tname}')
    time.sleep(random.uniform(1.0, 2.0))

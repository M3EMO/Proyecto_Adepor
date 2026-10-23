"""
Pedidos online a FotMob, un archivo JSON crudo por partido. Sin token ni proxy.

Guarda data/fotmob/raw/<id>.json (matchDetails completo: stats, shotmap con xG por tiro,
lineup, playerStats, eventos). La cobertura xG depende de la liga: Liga Profesional (112) si,
Copa Sudamericana (299) no.

Uso:
  python -I scripts/research/fotmob_pedir.py partido <match_id>
  python -I scripts/research/fotmob_pedir.py liga <league_id> <temporada> [--max N] [--solo-xg]
  python -I scripts/research/fotmob_pedir.py dia <YYYYMMDD> [--liga ID] [--solo-xg]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from curl_cffi import requests

sys.path.insert(0, str(Path(__file__).parent))  # -I quita el directorio del script del path
from fotmob_explorar import fila  # noqa: E402

API = 'https://www.fotmob.com/api/data/'
RAW = Path(__file__).resolve().parents[2] / 'data' / 'fotmob' / 'raw'
PAUSA = 1.0  # segundos entre pedidos


def pedir(ruta):
    r = requests.get(API + ruta, headers={'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'},
                     impersonate='chrome', timeout=20)
    r.raise_for_status()
    return r.json()


def bajar_partido(mid, forzar=False, solo_xg=False):
    """Descarga matchDetails si falta y devuelve el dict. Valida que el id devuelto coincida.
    Con solo_xg no guarda los partidos sin cobertura xG y devuelve None."""
    ruta = RAW / f'{mid}.json'
    if ruta.exists() and not forzar:
        return json.loads(ruta.read_text(encoding='utf-8'))
    det = pedir(f'matchDetails?matchId={mid}')
    if str(det.get('general', {}).get('matchId')) != str(mid):
        raise ValueError(f'matchDetails devolvio otro partido para {mid}')
    if solo_xg and det.get('general', {}).get('coverageLevel') != 'xG':
        time.sleep(PAUSA)
        return None
    RAW.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(det, ensure_ascii=False), encoding='utf-8')
    time.sleep(PAUSA)
    return det


def mostrar(det):
    if det is None:
        return
    f = fila(det)
    cob = det.get('general', {}).get('coverageLevel')
    print(json.dumps({**(f or {}), 'cobertura': cob}, ensure_ascii=False))


def bajar_lote(ids, solo_xg):
    for mid in ids:
        try:
            mostrar(bajar_partido(mid, solo_xg=solo_xg))
        except Exception as e:  # un partido malo no frena el lote
            print(f'{mid} ERROR {e!r}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='modo', required=True)
    sub.add_parser('partido').add_argument('match_id')
    p = sub.add_parser('liga')
    p.add_argument('league_id', type=int)
    p.add_argument('temporada')
    p.add_argument('--max', type=int)
    p.add_argument('--solo-xg', action='store_true', help='omite partidos sin cobertura xG')
    p = sub.add_parser('dia')
    p.add_argument('fecha')
    p.add_argument('--liga', type=int)
    p.add_argument('--solo-xg', action='store_true', help='omite partidos sin cobertura xG')
    a = ap.parse_args()
    if a.modo == 'partido':
        mostrar(bajar_partido(a.match_id, forzar=True))
    elif a.modo == 'liga':
        fx = pedir(f'fixtures?id={a.league_id}&season={a.temporada}')
        ids = [x['id'] for x in fx if x['status'].get('finished')]
        bajar_lote(ids[-a.max:] if a.max else ids, a.solo_xg)
    else:
        cal = pedir(f'matches?date={a.fecha}&timezone=America/Argentina/Buenos_Aires&ccode3=ARG')
        bajar_lote([m['id'] for lg in cal['leagues'] for m in lg['matches']
                    if m['status'].get('finished') and a.liga in (None, lg.get('primaryId'))], a.solo_xg)


if __name__ == '__main__':
    main()

"""
Explorador offline de la API de FotMob. No hace pedidos de red.

Lee respuestas JSON que el usuario guarda a mano desde su navegador:
  1. Abrir fotmob.com, F12 -> pestana Network, filtro "api/data".
  2. Abrir un dia o un partido; click derecho en el pedido -> Save response / Copy response.
  3. Guardar como .json y pasarlo a este script.

Pedidos que interesan:
  /api/data/matches?date=YYYYMMDD     calendario del dia (ids de partido)
  /api/data/matchDetails?matchId=ID   detalle de un partido (stats, xG, shotmap)

Uso:
  python -I scripts/research/fotmob_explorar.py arbol   <archivo.json> [--prof 3]
  python -I scripts/research/fotmob_explorar.py stats   <matchDetails.json>
  python -I scripts/research/fotmob_explorar.py fila    <matchDetails.json>
  python -I scripts/research/fotmob_explorar.py partidos <matches.json>
"""
import argparse
import json


def arbol(nodo, prof, nivel=0, clave='$'):
    """Lineas con la forma del JSON: clave, tipo y tamano, hasta `prof` niveles."""
    pad = '  ' * nivel
    if isinstance(nodo, dict):
        lineas = [f'{pad}{clave}: dict[{len(nodo)}]']
        if nivel < prof:
            for k, v in nodo.items():
                lineas += arbol(v, prof, nivel + 1, k)
        return lineas
    if isinstance(nodo, list):
        lineas = [f'{pad}{clave}: list[{len(nodo)}]']
        if nodo and nivel < prof:
            lineas += arbol(nodo[0], prof, nivel + 1, '[0]')  # el primer elemento muestra la forma
        return lineas
    return [f'{pad}{clave}: {type(nodo).__name__} = {str(nodo)[:40]!r}']


def grupos_stats(det):
    return det.get('content', {}).get('stats', {}).get('Periods', {}).get('All', {}).get('stats', [])


def stats(det):
    """(grupo, key, titulo, [local, visita]) de cada stat del partido completo."""
    return [(g.get('key'), s.get('key'), s.get('title'), s.get('stats'))
            for g in grupos_stats(det) for s in g.get('stats', [])
            if isinstance(s.get('stats'), list) and len(s['stats']) == 2]


def _stat(det, key):
    for _, k, _, v in stats(det):
        if k == key:
            return v
    return None


def _num(x, tipo):
    try:
        return tipo(x)
    except (TypeError, ValueError):
        return None


def fila(det):
    """Fila candidata para la futura tabla FotMob. Local = header.teams[0]."""
    teams = det.get('header', {}).get('teams', [])
    if len(teams) != 2:
        return None
    general = det.get('general', {})
    ids = [t.get('id') for t in teams]
    xg_tiros = [0.0, 0.0]
    for tiro in det.get('content', {}).get('shotmap', {}).get('shots', []):
        if tiro.get('teamId') in ids and tiro.get('expectedGoals') is not None:
            xg_tiros[ids.index(tiro['teamId'])] += float(tiro['expectedGoals'])
    out = {
        'fotmob_match_id': general.get('matchId'),
        'liga': general.get('leagueName'),
        'league_id': general.get('leagueId'),
        'fecha_utc': general.get('matchTimeUTCDate'),
        'terminado': general.get('finished'),
        'ht': teams[0].get('name'), 'at': teams[1].get('name'),
        'hg': teams[0].get('score'), 'ag': teams[1].get('score'),
        'xg_shotmap_l': round(xg_tiros[0], 4), 'xg_shotmap_v': round(xg_tiros[1], 4),
    }
    for col, key, tipo in (('xg', 'expected_goals', float), ('shots_on_target', 'ShotsOnTarget', int),
                           ('shots_total', 'total_shots', int), ('corners', 'corners', int)):
        v = _stat(det, key) or [None, None]
        out[f'{col}_l'], out[f'{col}_v'] = _num(v[0], tipo), _num(v[1], tipo)
    return out


def partidos(cal):
    """(match_id, liga, local, visita, terminado) de cada partido del calendario."""
    return [(m.get('id'), lg.get('name'), m.get('home', {}).get('name'), m.get('away', {}).get('name'),
             m.get('status', {}).get('finished'))
            for lg in cal.get('leagues', []) for m in lg.get('matches', [])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modo', choices=['arbol', 'stats', 'fila', 'partidos'])
    ap.add_argument('archivo')
    ap.add_argument('--prof', type=int, default=3)
    a = ap.parse_args()
    with open(a.archivo, encoding='utf-8') as f:
        datos = json.load(f)
    if a.modo == 'arbol':
        print('\n'.join(arbol(datos, a.prof)))
    elif a.modo == 'stats':
        for g, k, t, v in stats(datos):
            print(f'{g:<18} {k:<28} {str(t):<32} {v}')
    elif a.modo == 'fila':
        print(json.dumps(fila(datos), indent=2, ensure_ascii=False))
    else:
        for p in partidos(datos):
            print(*p, sep=' | ')


if __name__ == '__main__':
    main()

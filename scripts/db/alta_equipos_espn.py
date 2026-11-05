"""
Alta de los equipos de una liga nueva en diccionario_equipos.json, con los nombres de ESPN.

Uso:  python -I scripts/db/alta_equipos_espn.py <slug_espn>     (ej.: eng.2)
La liga interna sale de LIGAS_ESPN, asi que el slug debe estar ahi.
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # -I quita el directorio del script del path
from src.comun import gestor_nombres  # noqa: E402
from src.comun.config_sistema import LIGAS_ESPN  # noqa: E402


def equipos_espn(slug):
    r = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams', timeout=30)
    r.raise_for_status()
    ligas = (r.json().get('sports') or [{}])[0].get('leagues') or [{}]
    return [t['team']['displayName'] for t in ligas[0].get('teams', [])]


def main():
    slug = sys.argv[1]
    if slug not in LIGAS_ESPN:
        raise SystemExit(f'{slug} no esta en LIGAS_ESPN')
    nombres = equipos_espn(slug)
    if not nombres:
        raise SystemExit(f'ESPN no devuelve equipos para {slug}')
    nuevos = gestor_nombres.registrar_equipos(LIGAS_ESPN[slug], nombres)
    print(f'{LIGAS_ESPN[slug]}: {len(nombres)} equipos en ESPN, {nuevos} nuevos en el diccionario')


if __name__ == '__main__':
    main()

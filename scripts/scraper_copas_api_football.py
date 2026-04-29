"""[adepor-5y0] Scraper de fixtures de copas (nacionales + internacionales) via API-Football.

Endpoint: GET /fixtures?league=<id>&season=<year>
Inserta en partidos_no_liga con UNIQUE(fecha, equipo_local, equipo_visita, competicion)
para idempotencia (re-run no duplica).

USO:
    py scripts/scraper_copas_api_football.py --copas Copa_Argentina --temps 2024
    py scripts/scraper_copas_api_football.py --copas all_int --temps 2024
    py scripts/scraper_copas_api_football.py --copas all --temps 2022,2023,2024,2026
    py scripts/scraper_copas_api_football.py --dry-run --copas FA_Cup --temps 2024

Rate limit Free tier: 10 req/min, 100 req/dia. Multi-key rotation desde config.json.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.comun.config_sistema import API_KEYS_FOOTBALL

DB = ROOT / 'fondo_quant.db'
BASE_URL = 'https://v3.football.api-sports.io'
SLEEP_SEC = 7  # entre requests para respetar 10 req/min

# Keys activas — rotacion automatica
_KEYS = list(API_KEYS_FOOTBALL)
_KEY_IDX = 0


def _hdr():
    return {'x-apisports-key': _KEYS[_KEY_IDX]} if _KEYS else {}


def _rotar(motivo=''):
    global _KEY_IDX
    if _KEY_IDX + 1 >= len(_KEYS):
        return False
    _KEY_IDX += 1
    print(f'  [ROTACION] Key cambio ({motivo}). Ahora key {_KEY_IDX + 1}/{len(_KEYS)}.')
    return True


def status_quota():
    r = requests.get(f'{BASE_URL}/status', headers=_hdr(), timeout=15)
    if r.status_code != 200:
        return None
    d = r.json()
    if d.get('errors'):
        return {'suspended': True, 'errors': d['errors']}
    resp = d.get('response', {})
    if isinstance(resp, dict):
        req = resp.get('requests', {})
        return {'used': req.get('current', 0), 'limit': req.get('limit_day', 100), 'suspended': False}
    return None


# =============================================================================
# MAPA copas (verificado 2026-04-28 via API-Football leagues endpoint)
# =============================================================================
MAPA_COPAS_API_FOOTBALL = {
    # --- Copas internacionales UEFA ---
    'Champions_League':       {'id': 2,   'tipo': 'copa_internacional', 'pais_origen': 'Internacional', 'nombre_canon': 'Champions League'},
    'Europa_League':          {'id': 3,   'tipo': 'copa_internacional', 'pais_origen': 'Internacional', 'nombre_canon': 'Europa League'},
    'Conference_League':      {'id': 848, 'tipo': 'copa_internacional', 'pais_origen': 'Internacional', 'nombre_canon': 'Conference League'},

    # --- Copas internacionales CONMEBOL ---
    'Libertadores':           {'id': 13,  'tipo': 'copa_internacional', 'pais_origen': 'Internacional', 'nombre_canon': 'Libertadores'},
    'Sudamericana':           {'id': 11,  'tipo': 'copa_internacional', 'pais_origen': 'Internacional', 'nombre_canon': 'Sudamericana'},

    # --- Copas nacionales ---
    'Copa_Argentina':         {'id': 130, 'tipo': 'copa_nacional', 'pais_origen': 'Argentina',   'nombre_canon': 'Copa Argentina'},
    'Copa_do_Brasil':         {'id': 73,  'tipo': 'copa_nacional', 'pais_origen': 'Brasil',      'nombre_canon': 'Copa do Brasil'},
    'Copa_del_Rey':           {'id': 143, 'tipo': 'copa_nacional', 'pais_origen': 'Espana',      'nombre_canon': 'Copa del Rey'},
    'Coppa_Italia':           {'id': 137, 'tipo': 'copa_nacional', 'pais_origen': 'Italia',      'nombre_canon': 'Coppa Italia'},
    'FA_Cup':                 {'id': 45,  'tipo': 'copa_nacional', 'pais_origen': 'Inglaterra',  'nombre_canon': 'FA Cup'},
    'EFL_Cup':                {'id': 48,  'tipo': 'copa_nacional', 'pais_origen': 'Inglaterra',  'nombre_canon': 'EFL Cup'},
    'DFB_Pokal':              {'id': 81,  'tipo': 'copa_nacional', 'pais_origen': 'Alemania',    'nombre_canon': 'DFB Pokal'},
    'Coupe_de_France':        {'id': 66,  'tipo': 'copa_nacional', 'pais_origen': 'Francia',     'nombre_canon': 'Coupe de France'},
    'Turkiye_Kupasi':         {'id': 206, 'tipo': 'copa_nacional', 'pais_origen': 'Turquia',     'nombre_canon': 'Türkiye Kupası'},
}

GROUPS = {
    'all_int':  ['Champions_League', 'Europa_League', 'Conference_League', 'Libertadores', 'Sudamericana'],
    'all_nat':  ['Copa_Argentina', 'Copa_do_Brasil', 'Copa_del_Rey', 'Coppa_Italia', 'FA_Cup', 'EFL_Cup',
                 'DFB_Pokal', 'Coupe_de_France', 'Turkiye_Kupasi'],
    'all':      None,  # rellenado abajo
    '2026_arg': ['Copa_Argentina', 'Libertadores', 'Sudamericana'],
    '2026_ing': ['FA_Cup', 'EFL_Cup', 'Champions_League', 'Europa_League', 'Conference_League'],
}
GROUPS['all'] = GROUPS['all_int'] + GROUPS['all_nat']


def fetch_fixtures(copa_id, season, dry_run=False):
    """Devuelve lista de fixtures (paginado). Costo: 1-3 reqs segun volumen."""
    if dry_run:
        print(f'    [DRY-RUN] GET /fixtures?league={copa_id}&season={season}')
        return []
    fixtures = []
    page = 1
    max_pages = 10
    while page <= max_pages:
        params = {'league': copa_id, 'season': season}
        if page > 1:
            params['page'] = page
        try:
            r = requests.get(f'{BASE_URL}/fixtures', headers=_hdr(), params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f'    [ERR] HTTP fail: {e}')
            return fixtures

        if r.status_code == 429:
            if _rotar('429 rate limit'):
                continue
            print(f'    [STOP] 429 sin keys. Esperando 60s...')
            time.sleep(60)
            continue

        if r.status_code != 200:
            print(f'    [ERR] HTTP {r.status_code}: {r.text[:200]}')
            return fixtures

        d = r.json()
        if d.get('errors'):
            errs = d['errors']
            if isinstance(errs, dict) and 'access' in errs:
                if _rotar('account suspended'):
                    continue
                print(f'    [STOP] Todas las keys suspendidas: {errs}')
                return fixtures
            elif isinstance(errs, dict) and 'plan' in errs:
                print(f'    [STOP] Plan limit: {errs}')
                return fixtures
            elif isinstance(errs, list) and not errs:
                pass
            else:
                print(f'    [WARN] errors: {errs}')

        resp = d.get('response', [])
        if isinstance(resp, list):
            fixtures.extend(resp)
        paging = d.get('paging', {})
        cur = paging.get('current', 1); tot = paging.get('total', 1)
        if cur >= tot:
            break
        page += 1
        time.sleep(SLEEP_SEC)
    return fixtures


def parse_fixture(fix, copa_meta):
    """De fixture dict de API a row dict para partidos_no_liga."""
    f = fix.get('fixture', {}); l = fix.get('league', {})
    teams = fix.get('teams', {}); goals = fix.get('goals', {})
    fecha = (f.get('date') or '')[:10]
    if not fecha:
        return None
    home = teams.get('home', {}).get('name')
    away = teams.get('away', {}).get('name')
    if not home or not away:
        return None
    fase = l.get('round', '') or None
    return {
        'fecha': fecha,
        'competicion': copa_meta['nombre_canon'],
        'competicion_tipo': copa_meta['tipo'],
        'pais_origen': copa_meta['pais_origen'],
        'fase': fase,
        'equipo_local': home,
        'equipo_visita': away,
        'goles_l': goals.get('home'),
        'goles_v': goals.get('away'),
        'fuente': 'api-football',
    }


def insertar(con, rows):
    """[adepor-qqb fix 2026-04-28] Canonicaliza nombres + popula _norm. La copa
    se pasa como contexto a gestor_nombres (que sabe via _meta.ligas_por_copa
    cuales sub-ligas participan, ej Libertadores -> [Argentina,Brasil,...])."""
    from src.comun.gestor_nombres import obtener_nombre_estandar, limpiar_texto

    cur = con.cursor()
    n_ins = 0; n_dup = 0
    for r in rows:
        # Canonicalizar via gestor_nombres con scope de competicion (ej 'Libertadores')
        equipo_local_oficial = obtener_nombre_estandar(
            r['equipo_local'], liga=r['competicion'], modo_interactivo=False)
        equipo_visita_oficial = obtener_nombre_estandar(
            r['equipo_visita'], liga=r['competicion'], modo_interactivo=False)
        equipo_local_norm = limpiar_texto(equipo_local_oficial)
        equipo_visita_norm = limpiar_texto(equipo_visita_oficial)
        try:
            cur.execute("""INSERT INTO partidos_no_liga
                (fecha, competicion, competicion_tipo, pais_origen, fase,
                 equipo_local, equipo_visita,
                 equipo_local_norm, equipo_visita_norm,
                 goles_l, goles_v, fuente)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r['fecha'], r['competicion'], r['competicion_tipo'], r['pais_origen'],
                 r['fase'], equipo_local_oficial, equipo_visita_oficial,
                 equipo_local_norm, equipo_visita_norm,
                 r['goles_l'], r['goles_v'], r['fuente']))
            n_ins += 1
        except sqlite3.IntegrityError:
            n_dup += 1
    con.commit()
    return n_ins, n_dup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--copas', required=True,
                    help=f'Lista de copas (coma-separadas) o uno de: {list(GROUPS.keys())}')
    ap.add_argument('--temps', required=True, help='Lista de temps (coma-separadas), ej: 2022,2023,2024,2026')
    ap.add_argument('--dry-run', action='store_true', help='No hace requests ni inserts, solo print plan')
    args = ap.parse_args()

    if args.copas in GROUPS:
        copas_list = GROUPS[args.copas]
    else:
        copas_list = [c.strip() for c in args.copas.split(',')]
    invalid = [c for c in copas_list if c not in MAPA_COPAS_API_FOOTBALL]
    if invalid:
        print(f'ERROR copas no validas: {invalid}')
        print(f'Validas: {sorted(MAPA_COPAS_API_FOOTBALL.keys())}')
        sys.exit(1)
    temps = [int(t.strip()) for t in args.temps.split(',')]

    print(f'Plan: {len(copas_list)} copas × {len(temps)} temps = {len(copas_list)*len(temps)} requests minimas (paginacion puede sumar)')
    print(f'Copas: {copas_list}')
    print(f'Temps: {temps}')
    if not args.dry_run:
        st = status_quota()
        if st and not st.get('suspended'):
            print(f'Quota actual key {_KEY_IDX+1}: {st["used"]}/{st["limit"]} usado')

    if not DB.exists():
        print(f'ERROR DB no existe: {DB}')
        sys.exit(1)
    con = sqlite3.connect(DB) if not args.dry_run else None

    total_rows = 0; total_ins = 0; total_dup = 0; total_reqs = 0

    for copa_key in copas_list:
        meta = MAPA_COPAS_API_FOOTBALL[copa_key]
        for temp in temps:
            print(f'\n--- {copa_key} (id={meta["id"]}) season={temp} ---')
            fixs = fetch_fixtures(meta['id'], temp, dry_run=args.dry_run)
            total_reqs += 1  # min, paginacion suma mas
            print(f'  Fixtures recibidos: {len(fixs)}')
            if not fixs:
                continue
            rows = [parse_fixture(f, meta) for f in fixs]
            rows = [r for r in rows if r]
            total_rows += len(rows)
            if not args.dry_run and con:
                n_ins, n_dup = insertar(con, rows)
                print(f'  Insertados: {n_ins}, duplicados (skip): {n_dup}')
                total_ins += n_ins; total_dup += n_dup
            time.sleep(SLEEP_SEC)

    print(f'\n========== RESUMEN ==========')
    print(f'Requests min: {total_reqs}')
    print(f'Filas parseadas: {total_rows}')
    if not args.dry_run:
        print(f'Filas insertadas: {total_ins}')
        print(f'Duplicados (skip): {total_dup}')
        st = status_quota()
        if st and not st.get('suspended'):
            print(f'Quota final key {_KEY_IDX+1}: {st["used"]}/{st["limit"]}')
    if con: con.close()


if __name__ == '__main__':
    main()

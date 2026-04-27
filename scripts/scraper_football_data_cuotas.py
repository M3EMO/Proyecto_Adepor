"""
scraper_football_data_cuotas.py — Fase 1 plan_ampliacion_cuotas.md

Descarga CSVs de football-data.co.uk y persiste en `cuotas_externas_historico`.

Soporta 2 formatos:
- mmz4281 (per-temporada): E0, D1, I1, SP1, F1, T1 — opening + closing odds + 8 bookies
- new (multi-temporada): NOR.csv (Noruega) — closing only

Modo de uso:
    py scripts/scraper_football_data_cuotas.py --temporadas 2021,2022,2023,2024 \
        --ligas E0,D1,I1,SP1,F1,T1
    py scripts/scraper_football_data_cuotas.py --extra NOR --temporadas 2021,2022,2023,2024
    py scripts/scraper_football_data_cuotas.py --dry-run --ligas E0 --temporadas 2024

Bug `adepor-a0i`: N1 NO es Noruega (es Eredivisie). Para Noruega usar --extra NOR.
"""

import argparse
import csv
import io
import os
import sqlite3
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# UTF-8 stdout (Windows compat)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# Config
# ============================================================
DB_PATH = Path(__file__).resolve().parent.parent / 'fondo_quant.db'
TIMEOUT_HTTP = 30
MAX_REINTENTOS = 3
USER_AGENT = 'Mozilla/5.0 (Adepor-cuotas-scraper)'

# Mapping codigo CSV -> liga interna Adepor (alineada con partidos_historico_externo)
COD_LIGA_MMZ = {
    'E0':  'Inglaterra',
    'D1':  'Alemania',
    'I1':  'Italia',
    'SP1': 'Espana',
    'F1':  'Francia',
    'T1':  'Turquia',
}

COD_LIGA_NEW = {
    'NOR': 'Noruega',
    'ARG': 'Argentina',
    'BRA': 'Brasil',
    # Otros disponibles si se quieren agregar: SWE, POL, FIN, IRL, AUT, DEN, SWZ, MEX, JPN, USA, CHN, ROU, RUS
}

# Mapping de nombres CSV -> nombres alineados con partidos_historico_externo (ESPN).
# Necesario para LATAM porque football-data abrevia ('Argentinos Jrs') vs ESPN
# usa nombre completo ('Argentinos Juniors'). Sin esto, JOIN match cae a ~66%.
# Se aplica ANTES del INSERT en cuotas_externas_historico.
ALIASES_NEW_FORMAT = {
    'Argentina': {
        'Argentinos Jrs':       'Argentinos Juniors',
        'Atl. Tucuman':         'Atlético Tucumán',
        'Belgrano':             'Belgrano (Córdoba)',
        'Central Cordoba':      'Central Córdoba (Santiago del Estero)',
        'Dep. Riestra':         'Deportivo Riestra',
        'Estudiantes L.P.':     'Estudiantes de La Plata',
        'Gimnasia L.P.':        'Gimnasia La Plata',
        'Godoy Cruz':           'Godoy Cruz Antonio Tomba',
        'Ind. Rivadavia':       'Independiente Rivadavia',
        'Instituto':            'Instituto (Córdoba)',
        'Union de Santa Fe':    'Unión (Santa Fe)',
        # Acentos / apostrofes (ESPN los usa, football-data NO):
        'Huracan':              'Huracán',
        'Lanus':                'Lanús',
        'Newells Old Boys':     "Newell's Old Boys",
        'Sarmiento Junin':      'Sarmiento (Junín)',
        'Talleres Cordoba':     'Talleres (Córdoba)',
        'Velez Sarsfield':      'Vélez Sarsfield',
    },
    'Brasil': {
        'America MG':       'América Mineiro',
        'Athletico-PR':     'Athletico Paranaense',
        'Atletico GO':      'Atlético Goianiense',
        'Botafogo RJ':      'Botafogo',
        'Bragantino':       'Red Bull Bragantino',
        'Flamengo RJ':      'Flamengo',
        'Vasco':            'Vasco da Gama',
        # Acentos:
        'Atletico-MG':      'Atlético-MG',
        'Criciuma':         'Criciúma',
        'Cuiaba':           'Cuiabá',
        'Gremio':           'Grêmio',
        'Sao Paulo':        'São Paulo',
        'Vitoria':          'Vitória',
        # 'Chapecoense-SC' y 'Sport Recife' no estan en PHE 2022-2024 (descendidos).
        # No se mapean -> no matchearan en JOIN, OK.
    },
}


# ============================================================
# Utilidades
# ============================================================
def temp_to_mmz_path(temp):
    """Convierte temp 2024 -> '2425' (formato URL mmz4281)."""
    yy1 = temp % 100
    yy2 = (temp + 1) % 100
    return f'{yy1:02d}{yy2:02d}'


def fecha_csv_a_iso(s):
    """Convierte 'DD/MM/YYYY' o 'DD/MM/YY' a 'YYYY-MM-DD'. Devuelve None si no parsea."""
    if not s:
        return None
    s = s.strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def to_float(s):
    if s is None or s == '':
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def to_int(s):
    if s is None or s == '':
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def descargar_csv(url):
    """Descarga URL con reintentos. Retorna texto decodificado o None."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    last_err = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT_HTTP) as r:
                if r.status != 200:
                    last_err = f'HTTP {r.status}'
                    continue
                return r.read().decode('utf-8-sig', errors='replace')
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** intento)
    print(f'  FAIL {url} -> {last_err}')
    return None


# ============================================================
# Parsers por formato
# ============================================================
def parse_mmz4281(csv_text, liga, temp, url):
    """Parsea CSV mmz4281 -> lista de dicts listos para INSERT."""
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for r in reader:
        # Filtrar filas vacias o sin fecha/equipos
        fecha_iso = fecha_csv_a_iso(r.get('Date', ''))
        ht = (r.get('HomeTeam') or '').strip()
        at = (r.get('AwayTeam') or '').strip()
        if not (fecha_iso and ht and at):
            continue
        rows.append({
            'liga': liga,
            'temp': temp,
            'fecha': fecha_iso,
            'ht': ht,
            'at': at,
            'formato_csv': 'mmz4281',
            'hg': to_int(r.get('FTHG')),
            'ag': to_int(r.get('FTAG')),
            'res': (r.get('FTR') or '').strip() or None,
            # Opening
            'b365h': to_float(r.get('B365H')), 'b365d': to_float(r.get('B365D')), 'b365a': to_float(r.get('B365A')),
            'psh':   to_float(r.get('PSH')),   'psd':   to_float(r.get('PSD')),   'psa':   to_float(r.get('PSA')),
            'bwh':   to_float(r.get('BWH')),   'bwd':   to_float(r.get('BWD')),   'bwa':   to_float(r.get('BWA')),
            'whh':   to_float(r.get('WHH')),   'whd':   to_float(r.get('WHD')),   'wha':   to_float(r.get('WHA')),
            # Closing
            'b365ch': to_float(r.get('B365CH')), 'b365cd': to_float(r.get('B365CD')), 'b365ca': to_float(r.get('B365CA')),
            'psch':   to_float(r.get('PSCH')),   'pscd':   to_float(r.get('PSCD')),   'psca':   to_float(r.get('PSCA')),
            # Max / Avg opening
            'maxh': to_float(r.get('MaxH')), 'maxd': to_float(r.get('MaxD')), 'maxa': to_float(r.get('MaxA')),
            'avgh': to_float(r.get('AvgH')), 'avgd': to_float(r.get('AvgD')), 'avga': to_float(r.get('AvgA')),
            # Max / Avg closing
            'maxch': to_float(r.get('MaxCH')), 'maxcd': to_float(r.get('MaxCD')), 'maxca': to_float(r.get('MaxCA')),
            'avgch': to_float(r.get('AvgCH')), 'avgcd': to_float(r.get('AvgCD')), 'avgca': to_float(r.get('AvgCA')),
            # O/U 2.5
            'b365_25o': to_float(r.get('B365>2.5')), 'b365_25u': to_float(r.get('B365<2.5')),
            'p_25o':    to_float(r.get('P>2.5')),    'p_25u':    to_float(r.get('P<2.5')),
            'fuente_url': url,
        })
    return rows


def parse_new_format(csv_text, liga_target, temps_filter, url):
    """Parsea /new/<COD>.csv (multi-temp). Filtra por seasons en temps_filter (set).

    Aplica mapping ALIASES_NEW_FORMAT[liga_target] al nombre de equipo antes de
    persistir, para que el JOIN con partidos_historico_externo (ESPN) sea limpio.
    """
    aliases = ALIASES_NEW_FORMAT.get(liga_target, {})
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for r in reader:
        season_str = (r.get('Season') or '').strip()
        try:
            season = int(season_str)
        except ValueError:
            continue
        if season not in temps_filter:
            continue
        fecha_iso = fecha_csv_a_iso(r.get('Date', ''))
        ht = (r.get('Home') or '').strip()
        at = (r.get('Away') or '').strip()
        if not (fecha_iso and ht and at):
            continue
        # Aplicar alias ANTES de persistir (clave para JOIN limpio)
        ht = aliases.get(ht, ht)
        at = aliases.get(at, at)
        rows.append({
            'liga': liga_target,
            'temp': season,
            'fecha': fecha_iso,
            'ht': ht,
            'at': at,
            'formato_csv': 'new',
            'hg': to_int(r.get('HG')),
            'ag': to_int(r.get('AG')),
            'res': (r.get('Res') or '').strip() or None,
            # No hay opening en formato new — queda NULL
            'b365h': None, 'b365d': None, 'b365a': None,
            'psh': None, 'psd': None, 'psa': None,
            'bwh': None, 'bwd': None, 'bwa': None,
            'whh': None, 'whd': None, 'wha': None,
            # Closing
            'b365ch': to_float(r.get('B365CH')), 'b365cd': to_float(r.get('B365CD')), 'b365ca': to_float(r.get('B365CA')),
            'psch':   to_float(r.get('PSCH')),   'pscd':   to_float(r.get('PSCD')),   'psca':   to_float(r.get('PSCA')),
            'maxh': None, 'maxd': None, 'maxa': None,
            'avgh': None, 'avgd': None, 'avga': None,
            'maxch': to_float(r.get('MaxCH')), 'maxcd': to_float(r.get('MaxCD')), 'maxca': to_float(r.get('MaxCA')),
            'avgch': to_float(r.get('AvgCH')), 'avgcd': to_float(r.get('AvgCD')), 'avgca': to_float(r.get('AvgCA')),
            'b365_25o': None, 'b365_25u': None,
            'p_25o': None, 'p_25u': None,
            'fuente_url': url,
        })
    return rows


# ============================================================
# Persistencia
# ============================================================
COLS_INSERT = [
    'liga', 'temp', 'fecha', 'ht', 'at', 'formato_csv',
    'hg', 'ag', 'res',
    'b365h', 'b365d', 'b365a', 'psh', 'psd', 'psa',
    'bwh', 'bwd', 'bwa', 'whh', 'whd', 'wha',
    'b365ch', 'b365cd', 'b365ca', 'psch', 'pscd', 'psca',
    'maxh', 'maxd', 'maxa', 'avgh', 'avgd', 'avga',
    'maxch', 'maxcd', 'maxca', 'avgch', 'avgcd', 'avgca',
    'b365_25o', 'b365_25u', 'p_25o', 'p_25u',
    'fuente_url',
]

SQL_INSERT = (
    f'INSERT OR REPLACE INTO cuotas_externas_historico ({", ".join(COLS_INSERT)}) '
    f'VALUES ({", ".join(["?"] * len(COLS_INSERT))})'
)


def insertar_rows(con, rows):
    if not rows:
        return 0
    cur = con.cursor()
    payload = [tuple(r[c] for c in COLS_INSERT) for r in rows]
    cur.executemany(SQL_INSERT, payload)
    con.commit()
    return len(payload)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Scraper football-data.co.uk -> cuotas_externas_historico')
    parser.add_argument('--temporadas', type=str, default='2021,2022,2023,2024',
                        help='CSV: 2021,2022,2023,2024')
    parser.add_argument('--ligas', type=str, default='',
                        help=f'CSV codigos mmz4281. Disponibles: {",".join(COD_LIGA_MMZ.keys())}')
    parser.add_argument('--extra', type=str, default='',
                        help=f'CSV codigos formato /new/. Disponibles: {",".join(COD_LIGA_NEW.keys())}')
    parser.add_argument('--dry-run', action='store_true', help='No INSERT, solo preview de filas')
    args = parser.parse_args()

    temps = sorted({int(t) for t in args.temporadas.split(',') if t.strip()})
    cods_mmz = [c.strip() for c in args.ligas.split(',') if c.strip()]
    cods_new = [c.strip() for c in args.extra.split(',') if c.strip()]

    # Validacion
    for c in cods_mmz:
        if c not in COD_LIGA_MMZ:
            print(f'ERROR: codigo mmz4281 desconocido: {c}. Disponibles: {list(COD_LIGA_MMZ.keys())}')
            sys.exit(2)
    for c in cods_new:
        if c not in COD_LIGA_NEW:
            print(f'ERROR: codigo extra desconocido: {c}. Disponibles: {list(COD_LIGA_NEW.keys())}')
            sys.exit(2)
    if not cods_mmz and not cods_new:
        print('ERROR: tenes que pasar al menos --ligas o --extra')
        sys.exit(2)

    print(f'temporadas: {temps}')
    print(f'mmz4281: {cods_mmz}')
    print(f'new: {cods_new}')
    print(f'dry-run: {args.dry_run}')
    print(f'db: {DB_PATH}')
    print()

    con = None if args.dry_run else sqlite3.connect(str(DB_PATH))
    total_rows = 0
    total_insert = 0
    errors = []

    # === mmz4281 ===
    for cod in cods_mmz:
        liga = COD_LIGA_MMZ[cod]
        for temp in temps:
            mmz_path = temp_to_mmz_path(temp)
            url = f'https://www.football-data.co.uk/mmz4281/{mmz_path}/{cod}.csv'
            print(f'[mmz4281] {cod}={liga} temp={temp} -> {url}')
            csv_text = descargar_csv(url)
            if not csv_text:
                errors.append((cod, temp, 'download_failed'))
                continue
            rows = parse_mmz4281(csv_text, liga, temp, url)
            total_rows += len(rows)
            print(f'  rows parseadas: {len(rows)}')
            if not args.dry_run and rows:
                ins = insertar_rows(con, rows)
                total_insert += ins
                print(f'  INSERT OR REPLACE: {ins}')
            elif args.dry_run and rows:
                print(f'  [DRY-RUN] sample: {rows[0]["fecha"]} {rows[0]["ht"]} vs {rows[0]["at"]} '
                      f'B365H={rows[0]["b365h"]} PSCH={rows[0]["psch"]}')

    # === new ===
    for cod in cods_new:
        liga = COD_LIGA_NEW[cod]
        url = f'https://www.football-data.co.uk/new/{cod}.csv'
        print(f'[new] {cod}={liga} temps={temps} -> {url}')
        csv_text = descargar_csv(url)
        if not csv_text:
            errors.append((cod, None, 'download_failed'))
            continue
        rows = parse_new_format(csv_text, liga, set(temps), url)
        total_rows += len(rows)
        print(f'  rows parseadas (post-filtro temps): {len(rows)}')
        if not args.dry_run and rows:
            ins = insertar_rows(con, rows)
            total_insert += ins
            print(f'  INSERT OR REPLACE: {ins}')
        elif args.dry_run and rows:
            print(f'  [DRY-RUN] sample: {rows[0]["fecha"]} {rows[0]["ht"]} vs {rows[0]["at"]} '
                  f'PSCH={rows[0]["psch"]}')

    if con:
        con.close()

    print()
    print('=' * 60)
    print(f'TOTAL rows parseadas: {total_rows}')
    if not args.dry_run:
        print(f'TOTAL inserts (con REPLACE): {total_insert}')
    if errors:
        print(f'ERRORES: {len(errors)}')
        for e in errors:
            print(f'  {e}')
    else:
        print('errores: 0')


if __name__ == '__main__':
    main()

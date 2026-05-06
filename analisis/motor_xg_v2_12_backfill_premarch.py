"""
PLAN A.4-A.5 - Backfill referee + formation desde ESPN summary.

NO modifica scraper productivo. Crea tabla nueva fixture_premarch_features.
Idempotente: skip evt_id ya backfilleados.

Modo:
  --schema-only    : solo crea/migra tabla, no scrapea
  --sample N       : backfill solo N partidos (POC, default 50)
  --liga X         : restringe a liga
  --temp Y         : restringe a temporada
  --full           : backfill completo (~13,430 partidos, ~2-4 horas)
  --dry-run        : NO inserta, solo print

Uso:
  py analisis/motor_xg_v2_12_backfill_premarch.py --schema-only
  py analisis/motor_xg_v2_12_backfill_premarch.py --sample 50
  py analisis/motor_xg_v2_12_backfill_premarch.py --full

Uso en POC:
  --temp 2024 --sample 100   (POC 100 partidos 2024 distintos liga)
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'

LIGAS_ESPN_CODE = {
    'Inglaterra': 'eng.1', 'Espana': 'esp.1', 'Italia': 'ita.1', 'Francia': 'fra.1',
    'Alemania': 'ger.1', 'Turquia': 'tur.1', 'Argentina': 'arg.1', 'Brasil': 'bra.1',
    'Noruega': 'nor.1', 'Bolivia': 'bol.1', 'Peru': 'per.1', 'Venezuela': 'ven.1',
    'Ecuador': 'ecu.1', 'Uruguay': 'uru.1', 'Chile': 'chi.1', 'Colombia': 'col.1',
}

USER_AGENT = 'Mozilla/5.0 (Adepor-premarch-research)'
SLEEP = 0.4  # ~2.5 req/seg


def crear_schema(con):
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fixture_premarch_features (
            evt_id TEXT PRIMARY KEY,
            liga TEXT NOT NULL,
            temp INTEGER,
            fecha TEXT NOT NULL,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            referee_name TEXT,
            referee_role TEXT,
            referee_count INTEGER,
            formation_local TEXT,
            formation_visita TEXT,
            n_titulares_local INTEGER,
            n_titulares_visita INTEGER,
            lineup_local_json TEXT,
            lineup_visita_json TEXT,
            attendance INTEGER,
            venue_name TEXT,
            fuente TEXT DEFAULT 'ESPN',
            ingest_ts TEXT NOT NULL,
            error TEXT,
            FOREIGN KEY (evt_id) REFERENCES stats_partido_espn (evt_id)
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_fpf_liga_temp ON fixture_premarch_features(liga, temp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_fpf_referee ON fixture_premarch_features(referee_name)')
    con.commit()


def fetch_summary(liga_code, evt_id):
    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/{liga_code}/summary?event={evt_id}'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'_error': f'{type(e).__name__}: {e}'}


def parse_premarch(data):
    """Devuelve dict con campos pre-match. None si no hay data util."""
    if not data or '_error' in data:
        return {'error': data.get('_error') if data else 'no_data'}

    out = {'error': None}

    # Officials
    officials = data.get('gameInfo', {}).get('officials', []) or []
    if officials:
        # primer official suele ser referee principal
        out['referee_name'] = officials[0].get('fullName')
        out['referee_role'] = officials[0].get('position', {}).get('displayName') if officials[0].get('position') else None
        out['referee_count'] = len(officials)
    else:
        out['referee_name'] = None
        out['referee_role'] = None
        out['referee_count'] = 0

    # Rosters - formationPlace + starter info
    rosters = data.get('rosters', []) or []
    out['formation_local'] = None
    out['formation_visita'] = None
    out['n_titulares_local'] = 0
    out['n_titulares_visita'] = 0
    lineup_l, lineup_v = [], []

    for idx, team_roster in enumerate(rosters[:2]):
        roster = team_roster.get('roster', []) or []
        # formation directa? a veces ESPN lo expone en team_roster.formation
        formation = team_roster.get('formation', {})
        formation_str = None
        if isinstance(formation, dict):
            formation_str = formation.get('name') or formation.get('displayName')
        elif isinstance(formation, str):
            formation_str = formation

        starters = []
        for p in roster:
            if p.get('starter'):
                starters.append({
                    'fp': p.get('formationPlace'),
                    'pos': (p.get('position') or {}).get('abbreviation'),
                    'pid': p.get('playerId') or (p.get('athlete') or {}).get('id'),
                })

        if idx == 0:
            out['formation_local'] = formation_str
            out['n_titulares_local'] = len(starters)
            lineup_l = starters
        else:
            out['formation_visita'] = formation_str
            out['n_titulares_visita'] = len(starters)
            lineup_v = starters

    out['lineup_local_json'] = json.dumps(lineup_l) if lineup_l else None
    out['lineup_visita_json'] = json.dumps(lineup_v) if lineup_v else None

    # Venue + attendance
    venue = data.get('gameInfo', {}).get('venue', {}) or {}
    out['venue_name'] = venue.get('fullName')
    attendance = data.get('gameInfo', {}).get('attendance')
    out['attendance'] = int(attendance) if attendance else None

    return out


def cargar_pendientes(con, liga=None, temp=None, sample=None):
    cur = con.cursor()
    where = ['s.evt_id IS NOT NULL']
    params = []
    if liga:
        where.append('s.liga = ?')
        params.append(liga)
    if temp:
        where.append('s.temp = ?')
        params.append(temp)
    where.append('NOT EXISTS (SELECT 1 FROM fixture_premarch_features f WHERE f.evt_id = s.evt_id)')
    sql = f'''SELECT s.evt_id, s.liga, s.temp, s.fecha, s.ht, s.at
              FROM stats_partido_espn s
              WHERE {' AND '.join(where)}
              ORDER BY s.fecha DESC'''
    if sample:
        # Distribute across years 2022-2026 to avoid recency bias
        # Take ALL rows then random.sample to spread temporally
        import random
        random.seed(42)
        all_rows = cur.execute(sql, params).fetchall()
        if len(all_rows) > sample:
            # Stratified by year
            by_year = {}
            for r in all_rows:
                y = r[3][:4]
                by_year.setdefault(y, []).append(r)
            per_year = max(1, sample // max(len(by_year), 1))
            picked = []
            for y, rows in by_year.items():
                picked.extend(random.sample(rows, min(per_year, len(rows))))
            return picked[:sample]
        return all_rows
    return cur.execute(sql, params).fetchall()


def insert_row(con, row, parsed):
    cur = con.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO fixture_premarch_features
        (evt_id, liga, temp, fecha, ht, at,
         referee_name, referee_role, referee_count,
         formation_local, formation_visita,
         n_titulares_local, n_titulares_visita,
         lineup_local_json, lineup_visita_json,
         attendance, venue_name, fuente, ingest_ts, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ESPN', ?, ?)
    ''', (
        row[0], row[1], row[2], row[3], row[4], row[5],
        parsed.get('referee_name'), parsed.get('referee_role'), parsed.get('referee_count'),
        parsed.get('formation_local'), parsed.get('formation_visita'),
        parsed.get('n_titulares_local'), parsed.get('n_titulares_visita'),
        parsed.get('lineup_local_json'), parsed.get('lineup_visita_json'),
        parsed.get('attendance'), parsed.get('venue_name'),
        datetime.now().isoformat(), parsed.get('error'),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--schema-only', action='store_true')
    parser.add_argument('--sample', type=int, default=None)
    parser.add_argument('--liga', type=str, default=None)
    parser.add_argument('--temp', type=int, default=None)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    con = sqlite3.connect(str(DB))
    crear_schema(con)
    print('Schema fixture_premarch_features OK')
    if args.schema_only:
        con.close()
        return

    sample = None if args.full else (args.sample or 50)
    rows = cargar_pendientes(con, args.liga, args.temp, sample)
    print(f'Pendientes: {len(rows)}')
    if not rows:
        print('Nada que backfillear')
        con.close()
        return

    n_ok = 0
    n_ref = 0
    n_form = 0
    n_err = 0
    n_no_liga = 0
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        evt_id, liga, temp, fecha, ht, at = row
        liga_code = LIGAS_ESPN_CODE.get(liga)
        if not liga_code:
            n_no_liga += 1
            continue

        data = fetch_summary(liga_code, evt_id)
        parsed = parse_premarch(data)
        if parsed.get('error'):
            n_err += 1
        else:
            n_ok += 1
            if parsed.get('referee_name'):
                n_ref += 1
            if parsed.get('formation_local') or parsed.get('n_titulares_local', 0) > 0:
                n_form += 1

        if not args.dry_run:
            insert_row(con, row, parsed)
            if i % 25 == 0:
                con.commit()

        if i % 25 == 0 or i == len(rows):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f'  [{i}/{len(rows)}] OK={n_ok} ref={n_ref} form={n_form} err={n_err} | rate={rate:.1f} req/s elapsed={elapsed:.0f}s')

        time.sleep(SLEEP)

    if not args.dry_run:
        con.commit()
    con.close()
    print(f'\nFINAL: OK={n_ok} | referee_pop={n_ref} ({100*n_ref/max(n_ok,1):.1f}%) | formation_pop={n_form} ({100*n_form/max(n_ok,1):.1f}%) | error={n_err} | no_liga={n_no_liga}')


if __name__ == '__main__':
    main()

"""
[adepor-d5u] Scraper football-data.co.uk para cuotas históricas + stats individuales
de las TOP-5 EU + Argentina + Brasil.

URL patterns:
- EU top: https://www.football-data.co.uk/mmz4281/{TTTT+1}/{LEAGUE_CODE}.csv
  ej: 2122/E0.csv = Premier 2021-22
- ARG/BRA: https://www.football-data.co.uk/new/ARG.csv (todos los años en 1 CSV)

Cuotas preferidas: Pinnacle (PSH/PSD/PSA o PSCH/PSCD/PSCA closing) — bookie más eficiente
del mercado. Fallback: Bet365 (B365H/D/A) o Avg (AvgH/D/A).

Stats individuales (solo EU):
- HS/AS = shots, HST/AST = sot, HF/AF = fouls, HC/AC = corners, HY/AY = yellow, HR/AR = red

ARG/BRA solo tiene cuotas (no stats).

Persiste en tabla `cuotas_historicas_fdco`. Idempotente (PK fecha+local+visita).
"""
from __future__ import annotations
import argparse
import csv
import io
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

USER_AGENT = "Adepor-Research/1.0 (research; not commercial)"
TIMEOUT = 30

# Mapeo league code FD → liga Adepor
LEAGUE_MAP_EU = {
    "E0": "Inglaterra",     # Premier League
    "I1": "Italia",         # Serie A
    "D1": "Alemania",       # Bundesliga
    "SP1": "Espana",        # La Liga
    "F1": "Francia",        # Ligue 1
    "T1": "Turquia",        # Süper Lig
    "N1": "Holanda",        # Eredivisie (no en Adepor productivo, útil para validación)
}

# Temporadas a backfill: TTTT+1 format
SEASONS_EU = ["2122", "2223", "2324", "2425", "2526"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cuotas_historicas_fdco (
    liga TEXT NOT NULL,
    temp INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    equipo_local TEXT NOT NULL,
    equipo_visita TEXT NOT NULL,
    equipo_local_norm TEXT,
    equipo_visita_norm TEXT,
    goles_l INTEGER,
    goles_v INTEGER,
    cuota_1 REAL,
    cuota_x REAL,
    cuota_2 REAL,
    cuota_o25 REAL,
    cuota_u25 REAL,
    bookie_1x2 TEXT,
    bookie_ou TEXT,
    -- Stats EU only
    shots_l INTEGER,
    shots_v INTEGER,
    sot_l INTEGER,
    sot_v INTEGER,
    corners_l INTEGER,
    corners_v INTEGER,
    fouls_l INTEGER,
    fouls_v INTEGER,
    yellow_l INTEGER,
    yellow_v INTEGER,
    red_l INTEGER,
    red_v INTEGER,
    source TEXT NOT NULL DEFAULT 'football-data.co.uk',
    fecha_scraped TEXT NOT NULL,
    PRIMARY KEY (liga, fecha, equipo_local, equipo_visita)
);
CREATE INDEX IF NOT EXISTS idx_fdco_liga_temp ON cuotas_historicas_fdco(liga, temp);
CREATE INDEX IF NOT EXISTS idx_fdco_fecha ON cuotas_historicas_fdco(fecha);
CREATE INDEX IF NOT EXISTS idx_fdco_norms ON cuotas_historicas_fdco(equipo_local_norm, equipo_visita_norm);
"""


def normalize_team(name):
    if not name: return ""
    import unicodedata
    nf = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nf if not unicodedata.combining(c)).lower().replace(" ", "").strip()


def parse_date_dmy(s):
    """football-data fecha format: dd/mm/yyyy o dd/mm/yy."""
    if not s: return None
    try:
        if len(s.split("/")[2]) == 2:
            return datetime.strptime(s.strip(), "%d/%m/%y").strftime("%Y-%m-%d")
        return datetime.strptime(s.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return None


def temp_from_season_eu(season_code, fecha):
    """De season '2526' devuelve temp=2026 (Adepor: temp = año del fin de temporada)."""
    yy_end = int(season_code[2:4]) + 2000
    return yy_end


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read().decode("utf-8", errors="replace")
    return body


def f(v):
    """Float seguro (vacío, None, 'N/A' → None)."""
    if v is None or v == "" or v == "N/A": return None
    try: return float(v)
    except (ValueError, TypeError): return None


def i(v):
    if v is None or v == "" or v == "N/A": return None
    try: return int(float(v))
    except (ValueError, TypeError): return None


def parse_eu_csv(body, league_code, season_code):
    """Parsea CSV EU (E0, I1, etc.) — temp por season_code."""
    liga = LEAGUE_MAP_EU[league_code]
    temp = temp_from_season_eu(season_code, None)
    reader = csv.DictReader(io.StringIO(body))
    out = []
    for row in reader:
        date = row.get("Date") or row.get("﻿Date")
        fecha = parse_date_dmy(date)
        if not fecha: continue
        ht = (row.get("HomeTeam") or "").strip()
        at = (row.get("AwayTeam") or "").strip()
        if not ht or not at: continue
        # Cuotas 1X2: Pinnacle prefer, fallback B365, fallback Avg
        c1, cx, c2, bookie = None, None, None, None
        for prefix, name in [("PS", "Pinnacle"), ("B365", "Bet365"), ("Avg", "Avg")]:
            ph = f(row.get(f"{prefix}H")); pd = f(row.get(f"{prefix}D")); pa = f(row.get(f"{prefix}A"))
            if ph and pd and pa:
                c1, cx, c2, bookie = ph, pd, pa, name
                break
        # Cuotas O/U 2.5
        o25, u25, bookie_ou = None, None, None
        for prefix, name in [("P", "Pinnacle"), ("B365", "Bet365"), ("Avg", "Avg")]:
            po = f(row.get(f"{prefix}>2.5")); pu = f(row.get(f"{prefix}<2.5"))
            if po and pu:
                o25, u25, bookie_ou = po, pu, name
                break
        out.append({
            "liga": liga, "temp": temp, "fecha": fecha,
            "equipo_local": ht, "equipo_visita": at,
            "equipo_local_norm": normalize_team(ht),
            "equipo_visita_norm": normalize_team(at),
            "goles_l": i(row.get("FTHG")), "goles_v": i(row.get("FTAG")),
            "cuota_1": c1, "cuota_x": cx, "cuota_2": c2,
            "cuota_o25": o25, "cuota_u25": u25,
            "bookie_1x2": bookie, "bookie_ou": bookie_ou,
            "shots_l": i(row.get("HS")), "shots_v": i(row.get("AS")),
            "sot_l": i(row.get("HST")), "sot_v": i(row.get("AST")),
            "corners_l": i(row.get("HC")), "corners_v": i(row.get("AC")),
            "fouls_l": i(row.get("HF")), "fouls_v": i(row.get("AF")),
            "yellow_l": i(row.get("HY")), "yellow_v": i(row.get("AY")),
            "red_l": i(row.get("HR")), "red_v": i(row.get("AR")),
        })
    return out


def parse_argbra_csv(body, country):
    """Parsea CSV ARG/BRA — formato distinto, todos los años en 1 CSV.
    Solo cuotas, no stats individuales."""
    liga = "Argentina" if country == "ARG" else "Brasil"
    reader = csv.DictReader(io.StringIO(body))
    out = []
    for row in reader:
        season = (row.get("Season") or "").strip()
        # Argentina: '2012/2013' o '2024'; Brasil: '2024'
        if "/" in season:
            temp = int(season.split("/")[1])
        elif season.isdigit():
            temp = int(season)
        else:
            continue
        fecha = parse_date_dmy(row.get("Date") or "")
        if not fecha: continue
        ht = (row.get("Home") or "").strip()
        at = (row.get("Away") or "").strip()
        if not ht or not at: continue
        # Cuotas: PSCH/PSCD/PSCA = Pinnacle Closing; AvgCH/D/A = Avg Closing
        c1, cx, c2, bookie = None, None, None, None
        for prefix, name in [("PSC", "Pinnacle Close"), ("AvgC", "Avg Close"), ("B365C", "Bet365 Close")]:
            ph = f(row.get(f"{prefix}H")); pd = f(row.get(f"{prefix}D")); pa = f(row.get(f"{prefix}A"))
            if ph and pd and pa:
                c1, cx, c2, bookie = ph, pd, pa, name
                break
        out.append({
            "liga": liga, "temp": temp, "fecha": fecha,
            "equipo_local": ht, "equipo_visita": at,
            "equipo_local_norm": normalize_team(ht),
            "equipo_visita_norm": normalize_team(at),
            "goles_l": i(row.get("HG")), "goles_v": i(row.get("AG")),
            "cuota_1": c1, "cuota_x": cx, "cuota_2": c2,
            "cuota_o25": None, "cuota_u25": None,
            "bookie_1x2": bookie, "bookie_ou": None,
            "shots_l": None, "shots_v": None, "sot_l": None, "sot_v": None,
            "corners_l": None, "corners_v": None,
            "fouls_l": None, "fouls_v": None,
            "yellow_l": None, "yellow_v": None, "red_l": None, "red_v": None,
        })
    return out


def persistir(conn, rows, dry_run=False):
    if not rows: return 0
    if dry_run:
        return len(rows)
    ts = datetime.now().isoformat(timespec="seconds")
    cur = conn.cursor()
    inserts = []
    for r in rows:
        inserts.append((
            r["liga"], r["temp"], r["fecha"], r["equipo_local"], r["equipo_visita"],
            r["equipo_local_norm"], r["equipo_visita_norm"],
            r["goles_l"], r["goles_v"],
            r["cuota_1"], r["cuota_x"], r["cuota_2"],
            r["cuota_o25"], r["cuota_u25"],
            r["bookie_1x2"], r["bookie_ou"],
            r["shots_l"], r["shots_v"], r["sot_l"], r["sot_v"],
            r["corners_l"], r["corners_v"],
            r["fouls_l"], r["fouls_v"],
            r["yellow_l"], r["yellow_v"], r["red_l"], r["red_v"],
            "football-data.co.uk", ts,
        ))
    cur.executemany("""
        INSERT OR REPLACE INTO cuotas_historicas_fdco (
            liga, temp, fecha, equipo_local, equipo_visita,
            equipo_local_norm, equipo_visita_norm,
            goles_l, goles_v,
            cuota_1, cuota_x, cuota_2,
            cuota_o25, cuota_u25,
            bookie_1x2, bookie_ou,
            shots_l, shots_v, sot_l, sot_v,
            corners_l, corners_v,
            fouls_l, fouls_v,
            yellow_l, yellow_v, red_l, red_v,
            source, fecha_scraped
        ) VALUES (?,?,?,?,?, ?,?, ?,?, ?,?,?, ?,?, ?,?, ?,?,?,?, ?,?, ?,?, ?,?,?,?, ?,?)
    """, inserts)
    conn.commit()
    return len(inserts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", type=str, default=None,
                    help="Filtro 'EU' (top-5+TR) o 'ARG' o 'BRA' o liga code (E0,I1,D1,SP1,F1,T1,N1)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB); conn.text_factory = str
    conn.executescript(SCHEMA_SQL)

    print(f"=== Scraper football-data.co.uk ({'DRY-RUN' if args.dry_run else 'APPLY'}) ===")
    total_rows = 0

    # EU top
    only = args.only.upper() if args.only else None
    eu_codes = list(LEAGUE_MAP_EU.keys())
    if only and only != "EU" and only != "ARG" and only != "BRA":
        if only in eu_codes:
            eu_codes = [only]
        else:
            eu_codes = []

    if not only or only == "EU" or only in eu_codes:
        for code in eu_codes:
            for season in SEASONS_EU:
                url = f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
                try:
                    body = fetch_csv(url)
                    rows = parse_eu_csv(body, code, season)
                    n = persistir(conn, rows, dry_run=args.dry_run)
                    print(f"  {LEAGUE_MAP_EU[code]:<12s} {season:>4s} -> {n:>4d} filas")
                    total_rows += n
                    time.sleep(0.5)
                except urllib.error.HTTPError as e:
                    print(f"  {LEAGUE_MAP_EU[code]:<12s} {season:>4s} -> HTTP {e.code} (skip)")
                except Exception as e:
                    print(f"  {LEAGUE_MAP_EU[code]:<12s} {season:>4s} -> ERR: {e}")

    # ARG/BRA
    for country in ["ARG", "BRA"]:
        if only and only != country and only != "EU": continue
        if only == "EU": continue
        url = f"https://www.football-data.co.uk/new/{country}.csv"
        try:
            body = fetch_csv(url)
            rows = parse_argbra_csv(body, country)
            n = persistir(conn, rows, dry_run=args.dry_run)
            print(f"  {country:<12s} ALL  -> {n:>4d} filas")
            total_rows += n
        except Exception as e:
            print(f"  {country:<12s} ERR: {e}")

    print(f"\nTotal filas: {total_rows} ({'NO persistido' if args.dry_run else 'persistido'})")

    if not args.dry_run:
        cur = conn.cursor()
        # Stats persistencia
        n_total = cur.execute("SELECT COUNT(*) FROM cuotas_historicas_fdco").fetchone()[0]
        print(f"\n=== Tabla cuotas_historicas_fdco resumen ===")
        print(f"Total filas: {n_total}")
        print("\nPor liga × temp:")
        for r in cur.execute("""
            SELECT liga, temp, COUNT(*) as n,
                   SUM(CASE WHEN cuota_1 IS NOT NULL THEN 1 ELSE 0 END) as con_1x2,
                   SUM(CASE WHEN cuota_o25 IS NOT NULL THEN 1 ELSE 0 END) as con_ou
            FROM cuotas_historicas_fdco
            GROUP BY liga, temp
            ORDER BY liga, temp
        """):
            print(f"  {r[0]:<12s} {r[1]:>4d}  N={r[2]:>5d}  1X2={r[3]:>5d}  O/U={r[4]:>5d}")

    conn.close()


if __name__ == "__main__":
    main()

"""
[adepor xG copa LATAM] Scraper ESPN summary endpoint para extraer stats
detalladas (possession, pass%, crosses, long balls, etc.) de partidos copa
internacional LATAM (Libertadores, Sudamericana, Recopa, CWC) y nacionales.

ESPN endpoint: site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={id}
Devuelve 27 stats/equipo: Fouls, YC, RC, Offsides, Corners, Saves, Possession,
Shots, On Goal, Pass%, Crosses, Long Balls, Blocked Shots, Tackles, Interceptions,
Clearances.

Permite analizar 'generación de juego' por equipo en copa int → ajustar motor xG
para copa específicamente.

Tabla: stats_partidos_no_liga (PK fecha + eq_local + eq_visita + competicion).
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# Slugs ESPN para copas internacionales LATAM y EU + nacionales con N>=20 IS 2026
SLUGS_TO_SCRAPE = {
    "conmebol.libertadores": "Libertadores",
    "conmebol.sudamericana": "Sudamericana",
    "conmebol.recopa": "Recopa Sudamericana",
    "fifa.cwc": "FIFA Club World Cup",
    "uefa.champions": "Champions League",
    "uefa.europa": "Europa League",
    "uefa.europa.conf": "Conference League",
    "eng.fa": "FA Cup",
    "eng.league_cup": "EFL Cup",
    "esp.copa_del_rey": "Copa del Rey",
    "ita.coppa_italia": "Coppa Italia",
    "fra.coupe_de_france": "Coupe de France",
    "ger.dfb_pokal": "DFB Pokal",
    "arg.copa": "Copa Argentina",
    "bra.copa_do_brazil": "Copa do Brasil",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stats_partidos_no_liga (
    fecha TEXT NOT NULL,
    competicion TEXT NOT NULL,
    competicion_tipo TEXT,
    equipo_local TEXT NOT NULL,
    equipo_visita TEXT NOT NULL,
    equipo_local_norm TEXT,
    equipo_visita_norm TEXT,
    espn_event_id TEXT,
    -- Goals
    goles_l INTEGER,
    goles_v INTEGER,
    -- Disparo
    shots_l INTEGER, shots_v INTEGER,
    sot_l INTEGER, sot_v INTEGER,
    blocked_l INTEGER, blocked_v INTEGER,
    -- Generación juego
    possession_l REAL, possession_v REAL,
    accurate_passes_l INTEGER, accurate_passes_v INTEGER,
    total_passes_l INTEGER, total_passes_v INTEGER,
    pass_pct_l REAL, pass_pct_v REAL,
    accurate_crosses_l INTEGER, accurate_crosses_v INTEGER,
    total_crosses_l INTEGER, total_crosses_v INTEGER,
    long_balls_l INTEGER, long_balls_v INTEGER,
    accurate_long_balls_l INTEGER, accurate_long_balls_v INTEGER,
    -- Defensa
    tackles_l INTEGER, tackles_v INTEGER,
    interceptions_l INTEGER, interceptions_v INTEGER,
    clearances_l INTEGER, clearances_v INTEGER,
    saves_l INTEGER, saves_v INTEGER,
    -- Disciplina
    fouls_l INTEGER, fouls_v INTEGER,
    yellow_l INTEGER, yellow_v INTEGER,
    red_l INTEGER, red_v INTEGER,
    offsides_l INTEGER, offsides_v INTEGER,
    corners_l INTEGER, corners_v INTEGER,
    -- Metadata
    espn_slug TEXT,
    fecha_scraped TEXT NOT NULL,
    PRIMARY KEY (fecha, competicion, equipo_local_norm, equipo_visita_norm)
);
CREATE INDEX IF NOT EXISTS idx_spnl_fecha ON stats_partidos_no_liga(fecha);
CREATE INDEX IF NOT EXISTS idx_spnl_comp ON stats_partidos_no_liga(competicion);
CREATE INDEX IF NOT EXISTS idx_spnl_local ON stats_partidos_no_liga(equipo_local_norm);
CREATE INDEX IF NOT EXISTS idx_spnl_visita ON stats_partidos_no_liga(equipo_visita_norm);
"""


def normalize(s):
    if not s: return ""
    import unicodedata
    nf = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nf if not unicodedata.combining(c)).lower().replace(" ", "").strip()


def to_int(v):
    if v is None or v == "" or v == "-": return None
    try: return int(float(str(v).rstrip('%')))
    except (ValueError, TypeError): return None


def to_float(v):
    if v is None or v == "" or v == "-": return None
    try: return float(str(v).rstrip('%'))
    except (ValueError, TypeError): return None


def parse_team_stats(stats_list):
    """Mapa label→value desde lista de stats ESPN."""
    out = {}
    for s in stats_list or []:
        label = (s.get("label") or s.get("name") or "").strip().lower()
        val = s.get("displayValue")
        out[label] = val
    return out


def fetch_summary(slug, event_id, retries=2):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            if attempt < retries:
                time.sleep(1)
    return None


def fetch_scoreboard(slug, fecha):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={fecha}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("events", [])
    except Exception:
        pass
    return []


def extract_stats_row(slug, comp, comp_tipo, evt, summary):
    """Extrae fila stats desde summary ESPN."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    if len(teams) < 2: return None

    # Identificar local vs visita por homeAway
    home_idx = next((i for i, t in enumerate(teams)
                     if t.get("team", {}).get("homeAway") == "home"
                     or t.get("homeAway") == "home"), None)
    if home_idx is None:
        # fallback: primer equipo es home en ESPN convención
        home_idx = 0
    away_idx = 1 - home_idx if home_idx in (0, 1) else 1

    t_l = teams[home_idx]; t_v = teams[away_idx]
    name_l = t_l.get("team", {}).get("displayName") or t_l.get("displayName")
    name_v = t_v.get("team", {}).get("displayName") or t_v.get("displayName")
    if not name_l or not name_v: return None

    sl = parse_team_stats(t_l.get("statistics", []))
    sv = parse_team_stats(t_v.get("statistics", []))

    # Goals desde header
    header = summary.get("header", {})
    competitions = header.get("competitions", [])
    gl = gv = None
    if competitions:
        comp_data = competitions[0].get("competitors", [])
        if len(comp_data) >= 2:
            for cd in comp_data:
                if cd.get("homeAway") == "home":
                    gl = to_int(cd.get("score"))
                else:
                    gv = to_int(cd.get("score"))

    fecha = (header.get("competitions", [{}])[0].get("date") or "")[:10]
    if not fecha: return None

    return {
        "fecha": fecha, "competicion": comp, "competicion_tipo": comp_tipo,
        "equipo_local": name_l, "equipo_visita": name_v,
        "equipo_local_norm": normalize(name_l), "equipo_visita_norm": normalize(name_v),
        "espn_event_id": evt.get("id"),
        "goles_l": gl, "goles_v": gv,
        "shots_l": to_int(sl.get("shots")), "shots_v": to_int(sv.get("shots")),
        "sot_l": to_int(sl.get("on goal")), "sot_v": to_int(sv.get("on goal")),
        "blocked_l": to_int(sl.get("blocked shots")), "blocked_v": to_int(sv.get("blocked shots")),
        "possession_l": to_float(sl.get("possession")), "possession_v": to_float(sv.get("possession")),
        "accurate_passes_l": to_int(sl.get("accurate passes")), "accurate_passes_v": to_int(sv.get("accurate passes")),
        "total_passes_l": to_int(sl.get("passes")), "total_passes_v": to_int(sv.get("passes")),
        "pass_pct_l": to_float(sl.get("pass completion %")) or to_float(sl.get("pass completion")),
        "pass_pct_v": to_float(sv.get("pass completion %")) or to_float(sv.get("pass completion")),
        "accurate_crosses_l": to_int(sl.get("accurate crosses")),
        "accurate_crosses_v": to_int(sv.get("accurate crosses")),
        "total_crosses_l": to_int(sl.get("crosses")),
        "total_crosses_v": to_int(sv.get("crosses")),
        "long_balls_l": to_int(sl.get("long balls")), "long_balls_v": to_int(sv.get("long balls")),
        "accurate_long_balls_l": to_int(sl.get("accurate long balls")),
        "accurate_long_balls_v": to_int(sv.get("accurate long balls")),
        "tackles_l": to_int(sl.get("tackles")), "tackles_v": to_int(sv.get("tackles")),
        "interceptions_l": to_int(sl.get("interceptions")), "interceptions_v": to_int(sv.get("interceptions")),
        "clearances_l": to_int(sl.get("clearances")), "clearances_v": to_int(sv.get("clearances")),
        "saves_l": to_int(sl.get("saves")), "saves_v": to_int(sv.get("saves")),
        "fouls_l": to_int(sl.get("fouls")), "fouls_v": to_int(sv.get("fouls")),
        "yellow_l": to_int(sl.get("yellow cards")), "yellow_v": to_int(sv.get("yellow cards")),
        "red_l": to_int(sl.get("red cards")), "red_v": to_int(sv.get("red cards")),
        "offsides_l": to_int(sl.get("offsides")), "offsides_v": to_int(sv.get("offsides")),
        "corners_l": to_int(sl.get("corner kicks")), "corners_v": to_int(sv.get("corner kicks")),
        "espn_slug": slug,
    }


def persistir(conn, rows, dry_run=False):
    if not rows or dry_run:
        return len(rows)
    ts = datetime.now().isoformat(timespec="seconds")
    cur = conn.cursor()
    inserts = []
    for r in rows:
        inserts.append((
            r["fecha"], r["competicion"], r["competicion_tipo"],
            r["equipo_local"], r["equipo_visita"],
            r["equipo_local_norm"], r["equipo_visita_norm"],
            r["espn_event_id"],
            r["goles_l"], r["goles_v"],
            r["shots_l"], r["shots_v"], r["sot_l"], r["sot_v"],
            r["blocked_l"], r["blocked_v"],
            r["possession_l"], r["possession_v"],
            r["accurate_passes_l"], r["accurate_passes_v"],
            r["total_passes_l"], r["total_passes_v"],
            r["pass_pct_l"], r["pass_pct_v"],
            r["accurate_crosses_l"], r["accurate_crosses_v"],
            r["total_crosses_l"], r["total_crosses_v"],
            r["long_balls_l"], r["long_balls_v"],
            r["accurate_long_balls_l"], r["accurate_long_balls_v"],
            r["tackles_l"], r["tackles_v"],
            r["interceptions_l"], r["interceptions_v"],
            r["clearances_l"], r["clearances_v"],
            r["saves_l"], r["saves_v"],
            r["fouls_l"], r["fouls_v"],
            r["yellow_l"], r["yellow_v"],
            r["red_l"], r["red_v"],
            r["offsides_l"], r["offsides_v"],
            r["corners_l"], r["corners_v"],
            r["espn_slug"], ts,
        ))
    cur.executemany("""
        INSERT OR REPLACE INTO stats_partidos_no_liga (
            fecha, competicion, competicion_tipo, equipo_local, equipo_visita,
            equipo_local_norm, equipo_visita_norm, espn_event_id,
            goles_l, goles_v,
            shots_l, shots_v, sot_l, sot_v, blocked_l, blocked_v,
            possession_l, possession_v,
            accurate_passes_l, accurate_passes_v, total_passes_l, total_passes_v,
            pass_pct_l, pass_pct_v,
            accurate_crosses_l, accurate_crosses_v, total_crosses_l, total_crosses_v,
            long_balls_l, long_balls_v, accurate_long_balls_l, accurate_long_balls_v,
            tackles_l, tackles_v, interceptions_l, interceptions_v,
            clearances_l, clearances_v, saves_l, saves_v,
            fouls_l, fouls_v, yellow_l, yellow_v, red_l, red_v,
            offsides_l, offsides_v, corners_l, corners_v,
            espn_slug, fecha_scraped
        ) VALUES (?,?,?,?,?,?,?,?, ?,?, ?,?,?,?,?,?, ?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?)
    """, inserts)
    conn.commit()
    return len(inserts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default=None,
                    help="Filtro slug (e.g. conmebol.libertadores)")
    ap.add_argument("--from-date", default="2022-01-01")
    ap.add_argument("--to-date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3, help="Sleep entre requests")
    args = ap.parse_args()

    if args.to_date is None:
        args.to_date = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB); conn.text_factory = str
    conn.executescript(SCHEMA_SQL)

    slugs = {args.only: SLUGS_TO_SCRAPE[args.only]} if args.only else SLUGS_TO_SCRAPE

    print(f"=== Scraper ESPN summary ({'DRY-RUN' if args.dry_run else 'APPLY'}) ===")
    print(f"Rango: {args.from_date} a {args.to_date}")
    print(f"Slugs: {len(slugs)}")
    print()

    # Determinar tipo (intl vs nacional)
    INTL = {"conmebol.libertadores","conmebol.sudamericana","conmebol.recopa","fifa.cwc",
            "uefa.champions","uefa.europa","uefa.europa.conf"}

    total_persistido = 0
    fecha_dt = datetime.strptime(args.from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(args.to_date, "%Y-%m-%d")

    while fecha_dt <= to_dt:
        fecha_str = fecha_dt.strftime("%Y%m%d")
        for slug, comp_name in slugs.items():
            comp_tipo = "copa_internacional" if slug in INTL else "copa_nacional"
            events = fetch_scoreboard(slug, fecha_str)
            for evt in events:
                state = evt.get("status", {}).get("type", {}).get("state")
                if state != "post":  # Solo partidos finalizados
                    continue
                eid = evt.get("id")
                if not eid: continue
                summary = fetch_summary(slug, eid)
                if not summary: continue
                row = extract_stats_row(slug, comp_name, comp_tipo, evt, summary)
                if not row: continue
                # Verificar tiene stats útiles
                if row["shots_l"] is None and row["sot_l"] is None: continue
                n = persistir(conn, [row], dry_run=args.dry_run)
                total_persistido += n
                time.sleep(args.sleep)
        fecha_dt += timedelta(days=1)
        if fecha_dt.day == 1:
            print(f"  Procesando {fecha_dt.strftime('%Y-%m')} ... total persistido hasta ahora: {total_persistido}")

    print()
    print(f"Total persistidos: {total_persistido}")

    if not args.dry_run:
        cur = conn.cursor()
        print()
        print("=== stats_partidos_no_liga resumen ===")
        for r in cur.execute("""
            SELECT competicion, COUNT(*) as n
            FROM stats_partidos_no_liga
            GROUP BY competicion ORDER BY n DESC
        """):
            print(f"  {r[0]:<25s} N={r[1]}")
    conn.close()


if __name__ == "__main__":
    main()

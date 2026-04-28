"""Fase 3 (adepor-6kw): scrape posesion ESPN para LATAM (enriqueciendo cache existente)
y para EUR (scrape from scratch). Persiste a cache_espn/{liga}_{temp}.json y a tabla DB.

Estrategia:
  - LATAM (9 ligas × 3 temps): cache_espn ya existe con stats basicos. Iteramos por
    cada partido en cache, hacemos summary call SOLO si no tiene 'h_pos' (idempotente),
    actualizamos cache.
  - EUR (Inglaterra/Espana/Italia/Alemania/Francia/Turquia/Noruega × 3 temps):
    cache no existe. Llamamos al scraper completo (con stats + posesion) via
    scraper_espn_historico.scrape_liga_temp.

Uso:
  py analisis/fase3_scraper_posesion.py --enriquecer-latam
  py analisis/fase3_scraper_posesion.py --scrape-eur
  py analisis/fase3_scraper_posesion.py --persistir-db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "analisis" / "cache_espn"
DB = ROOT / "fondo_quant.db"

LIGAS_LATAM = ["Argentina", "Brasil", "Bolivia", "Chile", "Colombia", "Ecuador",
                "Peru", "Uruguay", "Venezuela"]
LIGAS_EUR = ["Inglaterra", "Espana", "Italia", "Alemania", "Francia", "Turquia", "Noruega"]
TEMPS = [2022, 2023, 2024]

LIGAS_ESPN_CODE = {
    "Argentina": "arg.1", "Brasil": "bra.1", "Bolivia": "bol.1",
    "Chile": "chi.1", "Colombia": "col.1", "Ecuador": "ecu.1",
    "Peru": "per.1", "Uruguay": "uru.1", "Venezuela": "ven.1",
    "Inglaterra": "eng.1", "Espana": "esp.1", "Italia": "ita.1",
    "Alemania": "ger.1", "Francia": "fra.1", "Turquia": "tur.1",
    "Noruega": "nor.1",
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _fetch(url, retries=3, sleep_429=10):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = sleep_429 * (i + 1)
                print(f"      [429] sleep {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None
            time.sleep(2)
        except Exception as e:
            time.sleep(2)
    return None


def get_stat(box, name):
    if not box:
        return 0
    for s in box.get("statistics", []):
        if s.get("name") == name:
            v = s.get("displayValue")
            try:
                return int(v) if v else 0
            except (ValueError, TypeError):
                return 0
    return 0


def get_stat_float(box, name):
    if not box:
        return None
    for s in box.get("statistics", []):
        if s.get("name") == name:
            v = s.get("displayValue")
            try:
                return float(v) if v is not None and v != "" else None
            except (ValueError, TypeError):
                return None
    return None


# Lista completa de stats ESPN (28 nombres). Mapping name -> (h_key, a_key, type)
# type: "int" o "float" (para displayValue parsing)
ESPN_STAT_FIELDS = [
    ("foulsCommitted", "h_fouls", "a_fouls", "int"),
    ("yellowCards", "h_yellow", "a_yellow", "int"),
    ("redCards", "h_red", "a_red", "int"),
    ("offsides", "h_offsides", "a_offsides", "int"),
    ("wonCorners", "hc", "ac", "int"),
    ("saves", "h_saves", "a_saves", "int"),
    ("possessionPct", "h_pos", "a_pos", "float"),
    ("totalShots", "hs", "as_v", "int"),
    ("shotsOnTarget", "hst", "ast", "int"),
    ("shotPct", "h_shot_pct", "a_shot_pct", "float"),
    ("penaltyKickGoals", "h_pk_goals", "a_pk_goals", "int"),
    ("penaltyKickShots", "h_pk_shots", "a_pk_shots", "int"),
    ("accuratePasses", "h_passes_acc", "a_passes_acc", "int"),
    ("totalPasses", "h_passes", "a_passes", "int"),
    ("passPct", "h_pass_pct", "a_pass_pct", "float"),
    ("accurateCrosses", "h_crosses_acc", "a_crosses_acc", "int"),
    ("totalCrosses", "h_crosses", "a_crosses", "int"),
    ("crossPct", "h_cross_pct", "a_cross_pct", "float"),
    ("totalLongBalls", "h_longballs", "a_longballs", "int"),
    ("accurateLongBalls", "h_longballs_acc", "a_longballs_acc", "int"),
    ("longballPct", "h_longball_pct", "a_longball_pct", "float"),
    ("blockedShots", "h_blocks", "a_blocks", "int"),
    ("effectiveTackles", "h_tackles_eff", "a_tackles_eff", "int"),
    ("totalTackles", "h_tackles", "a_tackles", "int"),
    ("tacklePct", "h_tackle_pct", "a_tackle_pct", "float"),
    ("interceptions", "h_interceptions", "a_interceptions", "int"),
    ("effectiveClearance", "h_clearance_eff", "a_clearance_eff", "int"),
    ("totalClearance", "h_clearance", "a_clearance", "int"),
]


def extract_all_stats(home_box, away_box):
    """Extrae las 28 stats ESPN. Devuelve dict con h_*, a_* keys."""
    out = {}
    for espn_name, h_key, a_key, dtype in ESPN_STAT_FIELDS:
        if dtype == "int":
            out[h_key] = get_stat(home_box, espn_name)
            out[a_key] = get_stat(away_box, espn_name)
        else:
            out[h_key] = get_stat_float(home_box, espn_name)
            out[a_key] = get_stat_float(away_box, espn_name)
    return out


def fetch_summary_stats(liga_code, evt_id):
    """Devuelve dict con TODAS las stats ESPN o None si falla."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga_code}/summary?event={evt_id}"
    data = _fetch(url)
    if not data:
        return None
    boxscore = data.get("boxscore", {})
    teams_box = boxscore.get("teams", [])
    if len(teams_box) < 2:
        return None
    home_box = teams_box[0]
    away_box = teams_box[1]
    return extract_all_stats(home_box, away_box)


def enriquecer_cache_latam(sleep_per_event=0.4):
    """Itera cache_espn/{liga}_{temp}.json para LATAM. Si partido no tiene h_pos,
    hace summary call y agrega. Persiste de vuelta."""
    # Idempotencia: si tiene h_blocks (key nueva v2) entonces ya esta completo.
    # Si solo tiene h_pos (v1 enriquecido viejo) sin h_blocks, re-scrapea todo.
    total_enriched = 0
    total_already = 0
    total_failed = 0
    for liga in LIGAS_LATAM:
        liga_code = LIGAS_ESPN_CODE[liga]
        for temp in TEMPS:
            cache_path = CACHE_DIR / f"{liga}_{temp}.json"
            if not cache_path.exists():
                print(f"[SKIP] {liga} {temp}: cache no existe")
                continue
            partidos = json.loads(cache_path.read_text(encoding="utf-8"))
            n_already = sum(1 for p in partidos if p.get("h_blocks") is not None)
            n_pendientes = len(partidos) - n_already
            print(f"[{liga} {temp}] {len(partidos)} partidos, {n_already} con stats v2, {n_pendientes} pendientes")
            if n_pendientes == 0:
                total_already += n_already
                continue
            for i, p in enumerate(partidos):
                if p.get("h_blocks") is not None:
                    continue
                evt = p.get("evt_id")
                if not evt:
                    total_failed += 1
                    continue
                stats = fetch_summary_stats(liga_code, evt)
                if not stats:
                    total_failed += 1
                    continue
                p.update(stats)
                total_enriched += 1
                if (i + 1) % 50 == 0:
                    print(f"  ... {i+1}/{len(partidos)} (enriched={total_enriched})", flush=True)
                time.sleep(sleep_per_event)
            cache_path.write_text(json.dumps(partidos, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  [SAVED] {cache_path}", flush=True)
            total_already += n_already
    print(f"\n=== LATAM enriquecimiento: enriched={total_enriched} already={total_already} failed={total_failed} ===")


def listar_event_ids(liga_code, season):
    """Lista ALL event IDs via paginated core API."""
    base = f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/{liga_code}/seasons/{season}/types/1/events"
    ids = []
    page = 1
    while True:
        url = f"{base}?limit=300&page={page}"
        data = _fetch(url)
        if not data:
            break
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            ref = item.get("$ref", "")
            # Extraer ID del $ref
            if "/events/" in ref:
                eid = ref.split("/events/")[-1].split("?")[0]
                ids.append(eid)
        if page >= data.get("pageCount", 1):
            break
        page += 1
        time.sleep(0.3)
    return ids


def scrape_eur(sleep_per_event=0.4):
    """Para cada (liga EUR, temp), si cache no existe, scrape from scratch."""
    for liga in LIGAS_EUR:
        liga_code = LIGAS_ESPN_CODE[liga]
        for temp in TEMPS:
            cache_path = CACHE_DIR / f"{liga}_{temp}.json"
            if cache_path.exists():
                partidos = json.loads(cache_path.read_text(encoding="utf-8"))
                n_v2 = sum(1 for p in partidos if p.get("h_blocks") is not None)
                if n_v2 == len(partidos):
                    print(f"[SKIP] {liga} {temp}: cache completa v2 ({len(partidos)} partidos)")
                    continue
                print(f"[ENRIQUECER] {liga} {temp}: cache parcial v2, completar...")
            else:
                print(f"[SCRAPE] {liga} {temp} from scratch...")
                partidos = []
                ids = listar_event_ids(liga_code, temp)
                print(f"  {len(ids)} event IDs")
                for i, eid in enumerate(ids):
                    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga_code}/summary?event={eid}"
                    data = _fetch(url)
                    if not data:
                        continue
                    # Parsear basico
                    header = data.get("header", {}) or data.get("gamepackageJSON", {}).get("header", {})
                    competitions = header.get("competitions", [])
                    if not competitions:
                        continue
                    comp = competitions[0]
                    comps = comp.get("competitors", [])
                    if len(comps) < 2:
                        continue
                    home = next((c for c in comps if c.get("homeAway") == "home"), None)
                    away = next((c for c in comps if c.get("homeAway") == "away"), None)
                    if not home or not away:
                        continue
                    fecha = comp.get("date") or comp.get("status", {}).get("clock")
                    ht = home.get("team", {}).get("displayName", "")
                    at = away.get("team", {}).get("displayName", "")
                    try:
                        hg = int(home.get("score", 0))
                        ag = int(away.get("score", 0))
                    except (ValueError, TypeError):
                        continue
                    boxscore = data.get("boxscore", {})
                    teams_box = boxscore.get("teams", [])
                    if len(teams_box) < 2:
                        continue
                    home_box = next((t for t in teams_box if t.get("team", {}).get("id") == home.get("id")), teams_box[0])
                    away_box = next((t for t in teams_box if t.get("team", {}).get("id") == away.get("id")), teams_box[1])
                    # Las 28 stats ESPN
                    stats_dict = extract_all_stats(home_box, away_box)
                    # 'as' es palabra reservada, queda como key 'as' del extract
                    # hst/ast/hs/as/hc/ac estan dentro del dict tambien
                    p = {
                        "fecha": fecha, "ht": ht, "at": at, "hg": hg, "ag": ag,
                        **stats_dict,
                        "evt_id": eid, "temp": temp,
                    }
                    partidos.append(p)
                    if (i + 1) % 50 == 0:
                        print(f"  ... {i+1}/{len(ids)}")
                    time.sleep(sleep_per_event)
                cache_path.write_text(json.dumps(partidos, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  [SAVED] {cache_path}: {len(partidos)} partidos")
                continue
            # Enriquecer caso parcial
            for i, p in enumerate(partidos):
                if p.get("h_blocks") is not None:
                    continue
                evt = p.get("evt_id")
                if not evt:
                    continue
                stats = fetch_summary_stats(liga_code, evt)
                if stats:
                    p.update(stats)
                if (i + 1) % 50 == 0:
                    print(f"  ... {i+1}/{len(partidos)}", flush=True)
                time.sleep(sleep_per_event)
            cache_path.write_text(json.dumps(partidos, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  [SAVED] {cache_path}")


def persistir_db():
    """Crea/poble tabla stats_partido_espn desde cache_espn enriquecida.
    Schema completo con las 28 stats ESPN (h_*, a_*)."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # Schema completo con todas las stats
    cols_extra = []
    for espn_name, h_key, a_key, dtype in ESPN_STAT_FIELDS:
        sql_type = "INTEGER" if dtype == "int" else "REAL"
        # hst/ast/hs/as/hc/ac ya estan en otros nombres pero el extract los pone como h_/a_
        # asi que sus keys son ya hst, ast, hs, as_ (con underscore), hc, ac
        # pero la table los necesita coherentes. Uso nombre del extract.
        if h_key == "as":
            h_key = "as_"  # SQL reserved
        cols_extra.append(f"{h_key} {sql_type}")
        cols_extra.append(f"{a_key} {sql_type}")
    schema = """
        CREATE TABLE IF NOT EXISTS stats_partido_espn (
            liga TEXT NOT NULL,
            temp INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            ht TEXT NOT NULL,
            at TEXT NOT NULL,
            evt_id TEXT,
            hg INTEGER, ag INTEGER,
            """ + ",\n            ".join(cols_extra) + """,
            PRIMARY KEY (liga, temp, fecha, ht, at)
        )
    """
    cur.execute("DROP TABLE IF EXISTS stats_partido_espn")
    cur.execute(schema)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_espn_liga_temp ON stats_partido_espn(liga, temp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_espn_match ON stats_partido_espn(liga, fecha, ht, at)")

    # Construir INSERT con todas las cols
    base_cols = ["liga", "temp", "fecha", "ht", "at", "evt_id", "hg", "ag"]
    for espn_name, h_key, a_key, dtype in ESPN_STAT_FIELDS:
        h_col = h_key if h_key != "as" else "as_"
        base_cols.append(h_col)
        base_cols.append(a_key)
    placeholders = ",".join(["?"] * len(base_cols))
    insert_sql = f"INSERT OR REPLACE INTO stats_partido_espn ({','.join(base_cols)}) VALUES ({placeholders})"

    n = 0
    n_pos = 0
    for cache_path in sorted(CACHE_DIR.glob("*.json")):
        # Skip archivos _idx.json (solo mapping evt_id, no partidos completos)
        if cache_path.stem.endswith("_idx"):
            continue
        liga, temp_str = cache_path.stem.rsplit("_", 1)
        try:
            temp = int(temp_str)
        except ValueError:
            continue
        partidos = json.loads(cache_path.read_text(encoding="utf-8"))
        for p in partidos:
            fecha = (p.get("fecha") or "")[:10]
            if not fecha or not p.get("ht") or not p.get("at"):
                continue
            row = [liga, temp, fecha, p["ht"], p["at"], p.get("evt_id"), p.get("hg"), p.get("ag")]
            for espn_name, h_key, a_key, dtype in ESPN_STAT_FIELDS:
                row.append(p.get(h_key))
                # Compat: cache viejo guarda "as" (totalShots visita)
                if a_key == "as_v" and p.get(a_key) is None:
                    row.append(p.get("as"))
                else:
                    row.append(p.get(a_key))
            cur.execute(insert_sql, row)
            n += 1
            if p.get("h_pos") is not None:
                n_pos += 1
    con.commit()
    con.close()
    print(f"stats_partido_espn: {n} filas insertadas, {n_pos} con posesion ({n_pos*100/max(n,1):.1f}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enriquecer-latam", action="store_true")
    ap.add_argument("--scrape-eur", action="store_true")
    ap.add_argument("--persistir-db", action="store_true")
    ap.add_argument("--all", action="store_true", help="Ejecuta todo")
    args = ap.parse_args()

    if args.all:
        args.enriquecer_latam = True
        args.scrape_eur = True
        args.persistir_db = True

    if not (args.enriquecer_latam or args.scrape_eur or args.persistir_db):
        ap.print_help()
        return

    if args.enriquecer_latam:
        enriquecer_cache_latam()
    if args.scrape_eur:
        scrape_eur()
    if args.persistir_db:
        persistir_db()


if __name__ == "__main__":
    main()

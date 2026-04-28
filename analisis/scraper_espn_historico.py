"""Scraper ESPN core+summary para datos LATAM historicos (adepor-bgt iter3).

Estrategia:
  1. Listar event IDs via core API: /v2/sports/soccer/leagues/{liga}/seasons/{year}/types/1/events
     -> paginado, ~300 events/page max.
  2. Para cada event, llamar summary endpoint (1 call = goles + stats SoT/shots/corners).
  3. Cachear por liga-temp en disco (JSON) para idempotencia.

Output: analisis/cache_espn/{liga}_{temp}.json con lista de partidos full-stats.

Uso:
  py analisis/scraper_espn_historico.py --liga Argentina --temp 2024
  py analisis/scraper_espn_historico.py --liga Argentina --temps 2022,2023,2024
  py analisis/scraper_espn_historico.py --all-latam --temps 2022,2023,2024
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "analisis" / "cache_espn"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

LIGAS_ESPN_CODE = {
    "Argentina": "arg.1",
    "Brasil": "bra.1",
    "Bolivia": "bol.1",
    "Chile": "chi.1",
    "Colombia": "col.1",
    "Ecuador": "ecu.1",
    "Peru": "per.1",
    "Uruguay": "uru.1",
    "Venezuela": "ven.1",
    "Inglaterra": "eng.1",
    "Espana": "esp.1",
    "Italia": "ita.1",
    "Alemania": "ger.1",
    "Francia": "fra.1",
    "Turquia": "tur.1",
    "Noruega": "nor.1",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _fetch(url, retries=3, sleep_429=10):
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = sleep_429 * (i + 1)
                print(f"      [429] sleep {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None
            time.sleep(2)
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise last_err


def listar_event_ids(liga_code, season):
    """Lista ALL event IDs de una temporada via paginated core API."""
    base = f"http://sports.core.api.espn.com/v2/sports/soccer/leagues/{liga_code}/seasons/{season}/types/1/events"
    page = 1
    ids = []
    while True:
        url = f"{base}?lang=en&limit=500&page={page}"
        data = _fetch(url)
        if not data:
            break
        items = data.get("items", [])
        for item in items:
            ref = item.get("$ref", "")
            # /events/694171?lang=en  -> 694171
            evt_id = ref.split("/events/")[-1].split("?")[0]
            if evt_id.isdigit():
                ids.append(evt_id)
        page_count = data.get("pageCount", 1)
        if page >= page_count:
            break
        page += 1
        time.sleep(0.3)
    return ids


def fetch_summary(liga_code, evt_id):
    """1 call que devuelve goles + stats SoT/shots/corners."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga_code}/summary?event={evt_id}"
    return _fetch(url)


def parse_summary(data):
    """Extrae partido en formato uniforme."""
    if not data:
        return None
    hdr = data.get("header", {})
    comps_hdr = hdr.get("competitions", [])
    if not comps_hdr:
        return None
    comp = comps_hdr[0]
    fecha = comp.get("date")
    status = comp.get("status", {}).get("type", {})
    if not status.get("completed", False):
        return None

    # competitors -> score, homeAway, team
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    hg = home.get("score")
    ag = away.get("score")
    try:
        hg = int(hg)
        ag = int(ag)
    except (ValueError, TypeError):
        return None

    ht_name = home.get("team", {}).get("displayName", "")
    at_name = away.get("team", {}).get("displayName", "")

    # Stats from boxscore
    boxscore = data.get("boxscore", {})
    teams_box = boxscore.get("teams", [])
    home_box = next((t for t in teams_box if t.get("team", {}).get("id") == home.get("id")), None)
    away_box = next((t for t in teams_box if t.get("team", {}).get("id") == away.get("id")), None)

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

    return {
        "fecha": fecha,
        "ht": ht_name, "at": at_name,
        "hg": hg, "ag": ag,
        "hst": get_stat(home_box, "shotsOnTarget"),
        "ast": get_stat(away_box, "shotsOnTarget"),
        "hs": get_stat(home_box, "totalShots"),
        "as": get_stat(away_box, "totalShots"),
        "hc": get_stat(home_box, "wonCorners"),
        "ac": get_stat(away_box, "wonCorners"),
        # Fase 3: posesion + stats avanzadas
        "h_pos": get_stat_float(home_box, "possessionPct"),
        "a_pos": get_stat_float(away_box, "possessionPct"),
        "h_passes": get_stat(home_box, "totalPasses"),
        "a_passes": get_stat(away_box, "totalPasses"),
        "h_pass_pct": get_stat_float(home_box, "passPct"),
        "a_pass_pct": get_stat_float(away_box, "passPct"),
        "h_fouls": get_stat(home_box, "foulsCommitted"),
        "a_fouls": get_stat(away_box, "foulsCommitted"),
        "h_yellow": get_stat(home_box, "yellowCards"),
        "a_yellow": get_stat(away_box, "yellowCards"),
        "h_red": get_stat(home_box, "redCards"),
        "a_red": get_stat(away_box, "redCards"),
        "h_offsides": get_stat(home_box, "offsides"),
        "a_offsides": get_stat(away_box, "offsides"),
    }


def scrape_liga_temp(liga, season, sleep_per_event=0.4):
    cache_path = CACHE_DIR / f"{liga}_{season}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  [CACHE] {liga} {season}: {len(cached)} partidos")
        return cached

    liga_code = LIGAS_ESPN_CODE.get(liga)
    if not liga_code:
        print(f"  [SKIP] {liga}: codigo desconocido")
        return []

    print(f"  [SCRAPE] {liga} {season} (code={liga_code})...", flush=True)
    ids = listar_event_ids(liga_code, season)
    print(f"     {len(ids)} event IDs encontrados", flush=True)

    partidos = []
    for i, eid in enumerate(ids):
        try:
            data = fetch_summary(liga_code, eid)
        except Exception as e:
            print(f"     [WARN] event {eid}: {e}", file=sys.stderr)
            continue
        p = parse_summary(data)
        if p:
            p["evt_id"] = eid
            p["temp"] = season
            partidos.append(p)
        if (i + 1) % 50 == 0:
            print(f"     {i+1}/{len(ids)} procesados ({len(partidos)} validos)", flush=True)
        time.sleep(sleep_per_event)

    print(f"  [DONE] {liga} {season}: {len(partidos)} partidos validos / {len(ids)} totales", flush=True)
    cache_path.write_text(json.dumps(partidos, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return partidos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", default=None)
    ap.add_argument("--all-latam", action="store_true")
    ap.add_argument("--all-eur", action="store_true")
    ap.add_argument("--temps", default="2022,2023,2024")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    LATAM = ["Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
             "Ecuador", "Peru", "Uruguay", "Venezuela"]
    EUR = ["Inglaterra", "Espana", "Italia", "Alemania", "Francia", "Turquia", "Noruega"]

    if args.all_latam:
        ligas = LATAM
    elif args.all_eur:
        ligas = EUR
    elif args.liga:
        ligas = [args.liga]
    else:
        print("ERROR: --liga, --all-latam o --all-eur requerido", file=sys.stderr)
        sys.exit(1)

    temps = [int(t.strip()) for t in args.temps.split(",")]

    print(f"=== ESPN scrape ligas={ligas} temps={temps} sleep_per_event={args.sleep}s ===")
    for liga in ligas:
        for temp in temps:
            scrape_liga_temp(liga, temp, sleep_per_event=args.sleep)


if __name__ == "__main__":
    main()

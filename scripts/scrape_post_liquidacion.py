"""Hook post-liquidacion: scrape ESPN summary stats para partidos recien liquidados.

Trigger: cada vez que motor_data liquida partidos nuevos en partidos_backtest,
ejecutar este script para enriquecer stats_partido_espn con stats avanzadas
(28 stats por equipo: posesion, pases, crosses, blocks, tackles, etc).

Idempotente: solo procesa partidos liquidados que NO esten ya en stats_partido_espn.

Estrategia mapping liga -> ESPN code:
  Usa LIGAS_ESPN_CODE de fase3_scraper_posesion.

Mapping fecha + nombres equipo -> evt_id:
  Buscar en cache_espn/{liga}_{temp}.json el partido por (fecha, ht, at).
  Si no existe (temp 2026 nueva, no scrapeada), buscar via ESPN core API.

Uso:
  py scripts/scrape_post_liquidacion.py             # solo procesa pendientes
  py scripts/scrape_post_liquidacion.py --liga Argentina --temp 2026
  py scripts/scrape_post_liquidacion.py --dry-run

Integracion sugerida en ejecutar_proyecto.py:
  Despues de motor_data (FASE 3) agregar:
    py scripts/scrape_post_liquidacion.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analisis.aliases_espn import match_partido, names_match

DB = ROOT / "fondo_quant.db"
CACHE_DIR = ROOT / "analisis" / "cache_espn"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LIGAS_ESPN_CODE = {
    "Argentina": "arg.1", "Brasil": "bra.1", "Bolivia": "bol.1",
    "Chile": "chi.1", "Colombia": "col.1", "Ecuador": "ecu.1",
    "Peru": "per.1", "Uruguay": "uru.1", "Venezuela": "ven.1",
    "Inglaterra": "eng.1", "Espana": "esp.1", "Italia": "ita.1",
    "Alemania": "ger.1", "Francia": "fra.1", "Turquia": "tur.1",
    "Noruega": "nor.1",
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

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


def _fetch(url, retries=3, sleep_429=10):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(sleep_429 * (i + 1))
                continue
            if e.code == 404:
                return None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


def _stat(box, name, dtype):
    if not box:
        return None if dtype == "float" else 0
    for s in box.get("statistics", []):
        if s.get("name") == name:
            v = s.get("displayValue")
            try:
                return float(v) if dtype == "float" else int(v)
            except (ValueError, TypeError):
                return None if dtype == "float" else 0
    return None if dtype == "float" else 0


def derivar_temp(fecha_str, liga):
    y = int(fecha_str[:4])
    m = int(fecha_str[5:7])
    eur = {"Alemania", "Espana", "Francia", "Inglaterra", "Italia", "Turquia"}
    return y if (liga not in eur or m >= 7) else y - 1


def buscar_evt_id_en_cache(liga, fecha, ht, at):
    """Busca en cache_espn/{liga}_{temp}.json el evt_id por (fecha, ht, at).
    Usa matching flexible (normalizacion + wildcards + aliases)."""
    temp = derivar_temp(fecha, liga)
    cache_path = CACHE_DIR / f"{liga}_{temp}.json"
    if not cache_path.exists():
        return None, temp
    partidos = json.loads(cache_path.read_text(encoding="utf-8"))
    matched = match_partido(liga, fecha, ht, at, partidos)
    if matched:
        return matched.get("evt_id"), temp
    return None, temp


# Pre-fetch event listings por (liga, season) — cache en memoria.
_PREFETCH_CACHE = {}


def prefetch_temp_events(liga_code, season):
    """Lista events ESPN de una temp + summary basico (fecha, ht, at, evt_id).
    Cachea en _PREFETCH_CACHE y persiste a cache_espn/{liga}_{season}_idx.json."""
    key = (liga_code, season)
    if key in _PREFETCH_CACHE:
        return _PREFETCH_CACHE[key]
    # liga code -> liga nombre
    liga_inv = {v: k for k, v in {
        "Argentina": "arg.1", "Brasil": "bra.1", "Bolivia": "bol.1",
        "Chile": "chi.1", "Colombia": "col.1", "Ecuador": "ecu.1",
        "Peru": "per.1", "Uruguay": "uru.1", "Venezuela": "ven.1",
        "Inglaterra": "eng.1", "Espana": "esp.1", "Italia": "ita.1",
        "Alemania": "ger.1", "Francia": "fra.1", "Turquia": "tur.1",
        "Noruega": "nor.1",
    }.items()}
    liga_nom = liga_inv.get(liga_code, liga_code)
    cache_path = CACHE_DIR / f"{liga_nom}_{season}_idx.json"
    if cache_path.exists():
        partidos = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  [CACHE-IDX] {liga_nom} {season}: {len(partidos)} events from disk", flush=True)
        _PREFETCH_CACHE[key] = partidos
        return partidos
    print(f"  [PREFETCH] {liga_code} {season}...", flush=True)
    base = (f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/"
            f"{liga_code}/seasons/{season}/types/1/events")
    eids = []
    page = 1
    while page <= 20:
        url = f"{base}?limit=300&page={page}"
        data = _fetch(url)
        if not data:
            break
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            ref = item.get("$ref", "")
            if "/events/" in ref:
                eid = ref.split("/events/")[-1].split("?")[0]
                eids.append(eid)
        if page >= data.get("pageCount", 1):
            break
        page += 1
        time.sleep(0.3)
    print(f"     {len(eids)} event IDs encontrados, fetching summaries...", flush=True)
    partidos = []
    for i, eid in enumerate(eids):
        sum_url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
                    f"{liga_code}/summary?event={eid}")
        sd = _fetch(sum_url)
        if not sd:
            continue
        comp = sd.get("header", {}).get("competitions", [{}])[0]
        comps = comp.get("competitors", [])
        if len(comps) < 2:
            continue
        home = next((c for c in comps if c.get("homeAway") == "home"), None)
        away = next((c for c in comps if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        partidos.append({
            "fecha": (comp.get("date") or "")[:10],
            "ht": home.get("team", {}).get("displayName", ""),
            "at": away.get("team", {}).get("displayName", ""),
            "evt_id": eid,
        })
        if (i + 1) % 50 == 0:
            print(f"     ... {i+1}/{len(eids)}", flush=True)
        time.sleep(0.3)
    _PREFETCH_CACHE[key] = partidos
    # Persistir a disco
    cache_path.write_text(json.dumps(partidos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [SAVED-IDX] {cache_path}", flush=True)
    return partidos


def buscar_evt_id_via_prefetch(liga, liga_code, fecha, ht, at, season):
    """Usa prefetch + match_partido (flexible)."""
    candidatos = prefetch_temp_events(liga_code, season)
    matched = match_partido(liga, fecha, ht, at, candidatos)
    if matched:
        return matched.get("evt_id")
    return None


def fetch_stats_summary(liga_code, evt_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga_code}/summary?event={evt_id}"
    data = _fetch(url)
    if not data:
        return None
    boxscore = data.get("boxscore", {})
    teams_box = boxscore.get("teams", [])
    if len(teams_box) < 2:
        return None
    h, a = teams_box[0], teams_box[1]
    out = {}
    for espn_name, hk, ak, dtype in ESPN_STAT_FIELDS:
        out[hk] = _stat(h, espn_name, dtype)
        out[ak] = _stat(a, espn_name, dtype)
    return out


def insertar_stats_db(con, liga, temp, fecha, ht, at, evt_id, hg, ag, stats):
    cur = con.cursor()
    base_cols = ["liga", "temp", "fecha", "ht", "at", "evt_id", "hg", "ag"]
    for _, hk, ak, _ in ESPN_STAT_FIELDS:
        h_col = hk if hk != "as" else "as_"
        base_cols.append(h_col)
        base_cols.append(ak)
    placeholders = ",".join(["?"] * len(base_cols))
    sql = f"INSERT OR REPLACE INTO stats_partido_espn ({','.join(base_cols)}) VALUES ({placeholders})"
    row = [liga, temp, fecha, ht, at, evt_id, hg, ag]
    for _, hk, ak, _ in ESPN_STAT_FIELDS:
        row.append(stats.get(hk))
        row.append(stats.get(ak))
    cur.execute(sql, row)
    con.commit()


def cargar_partidos_pendientes(con, liga_filter=None, temp_filter=None):
    """Devuelve liquidados en partidos_backtest sin entry en stats_partido_espn."""
    cur = con.cursor()
    where = ["b.estado='Liquidado'", "b.goles_l IS NOT NULL", "b.goles_v IS NOT NULL"]
    params = []
    if liga_filter:
        where.append("b.pais = ?")
        params.append(liga_filter)
    if temp_filter:
        # Temp = año derivado, filtrar por substring de fecha
        where.append(f"substr(b.fecha,1,4) = ?")
        params.append(str(temp_filter))
    where_clause = " AND ".join(where)
    rows = cur.execute(f"""
        SELECT b.pais, substr(b.fecha,1,10), b.local, b.visita, b.goles_l, b.goles_v, b.id_partido
        FROM partidos_backtest b
        LEFT JOIN stats_partido_espn s
          ON b.pais = s.liga
         AND substr(b.fecha,1,10) = s.fecha
         AND b.local = s.ht
         AND b.visita = s.at
        WHERE {where_clause}
          AND s.fecha IS NULL
        ORDER BY b.fecha
    """, params).fetchall()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", help="Filtrar por liga")
    ap.add_argument("--temp", type=int, help="Filtrar por temp (año)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=500, help="Tope de partidos por corrida")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    con = sqlite3.connect(DB)

    # Verificar tabla existe
    n = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='stats_partido_espn'").fetchone()[0]
    if n == 0:
        print("[FATAL] tabla stats_partido_espn no existe. Ejecutar primero:")
        print("  py analisis/fase3_scraper_posesion.py --persistir-db")
        return

    pendientes = cargar_partidos_pendientes(con, args.liga, args.temp)
    print(f"=== Hook post-liquidacion ===")
    print(f"Partidos liquidados sin stats ESPN: {len(pendientes)}")
    if not pendientes:
        print("Nada que hacer. Todo al dia.")
        return

    if args.dry_run:
        print(f"[DRY RUN] Primeros 10 partidos pendientes:")
        for r in pendientes[:10]:
            print(f"  {r[0]} {r[1]} {r[2]} vs {r[3]} ({r[4]}-{r[5]})")
        return

    n_ok = 0
    n_fail = 0
    n_liga_no_espn = 0
    procesados = 0
    for r in pendientes[:args.max]:
        liga, fecha, ht, at, hg, ag, _ = r
        liga_code = LIGAS_ESPN_CODE.get(liga)
        if not liga_code:
            n_liga_no_espn += 1
            continue
        # Buscar evt_id en cache
        evt_id, temp = buscar_evt_id_en_cache(liga, fecha, ht, at)
        if not evt_id:
            # Cache no tiene; usar prefetch (paginated, una vez por (liga, temp))
            evt_id = buscar_evt_id_via_prefetch(liga, liga_code, fecha, ht, at, temp)
        if not evt_id:
            n_fail += 1
            print(f"  [MISS] {liga} {fecha} {ht} vs {at} (sin evt_id)")
            continue
        # Fetch stats
        stats = fetch_stats_summary(liga_code, evt_id)
        if not stats:
            n_fail += 1
            print(f"  [FAIL] {liga} {fecha} {ht} vs {at} evt={evt_id} (sin stats)")
            time.sleep(args.sleep)
            continue
        insertar_stats_db(con, liga, temp, fecha, ht, at, evt_id, hg, ag, stats)
        n_ok += 1
        procesados += 1
        if procesados % 20 == 0:
            print(f"  ... {procesados}/{min(len(pendientes), args.max)} (ok={n_ok} fail={n_fail})", flush=True)
        time.sleep(args.sleep)

    con.close()
    print(f"\n=== RESUMEN ===")
    print(f"  ok          : {n_ok}")
    print(f"  fail        : {n_fail}")
    print(f"  liga sin ESPN: {n_liga_no_espn}")


if __name__ == "__main__":
    main()

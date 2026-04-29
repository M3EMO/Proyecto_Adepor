"""
[F2 sub-15] Scraping copas via ESPN API — completa knockouts UEFA + LATAM 2025-26.

Cobertura validada (probe ESPN core leagues 2026-04-28):
- uefa.champions, uefa.europa, uefa.europa.conf
- conmebol.libertadores, conmebol.sudamericana
- ger.dfb_pokal, esp.copa_del_rey, fra.coupe_de_france
- eng.fa, eng.league_cup, ita.coppa_italia
- arg.copa, bra.copa_do_brazil
- conmebol.recopa, concacaf.champions_cup, fifa.cwc

ESPN endpoint: site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates=YYYYMMDD

Itera por dias en rango. Para cada event con status FINAL extrae goles. Para
events futuros persiste con goles NULL (útil para fixture upcoming Layer 3).

[REF: docs/papers/copa_modelado.md Q2/Q3 — copa internacional captura mejor por
jerarquía clara; F2 schema enriquecido + F3 Elo cross-competition].

USO:
    py scripts/scraper_copas_espn.py
    py scripts/scraper_copas_espn.py --desde 2025-07-01 --hasta 2026-12-31
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import obtener_nombre_estandar, limpiar_texto  # noqa

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={fecha}"
UA = "Mozilla/5.0 (Adepor-Research)"

# Copas a scrapear con metadata de mapeo a partidos_no_liga
COPAS = [
    # UEFA Champions/Europa/Conference League — copa internacional
    {"slug": "uefa.champions", "competicion": "Champions League", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    {"slug": "uefa.europa", "competicion": "Europa League", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    {"slug": "uefa.europa.conf", "competicion": "Conference League", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    # Conmebol — copa internacional
    {"slug": "conmebol.libertadores", "competicion": "Libertadores", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    {"slug": "conmebol.sudamericana", "competicion": "Sudamericana", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    {"slug": "conmebol.recopa", "competicion": "Recopa Sudamericana", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    # Concacaf
    {"slug": "concacaf.champions_cup", "competicion": "Concacaf Champions Cup", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    # FIFA CWC
    {"slug": "fifa.cwc", "competicion": "FIFA Club World Cup", "competicion_tipo": "copa_internacional", "pais_origen": "Internacional"},
    # Copas nacionales EUR + LATAM
    {"slug": "eng.fa", "competicion": "FA Cup", "competicion_tipo": "copa_nacional", "pais_origen": "Inglaterra"},
    {"slug": "eng.league_cup", "competicion": "EFL Cup", "competicion_tipo": "copa_nacional", "pais_origen": "Inglaterra"},
    {"slug": "ger.dfb_pokal", "competicion": "DFB Pokal", "competicion_tipo": "copa_nacional", "pais_origen": "Alemania"},
    {"slug": "esp.copa_del_rey", "competicion": "Copa del Rey", "competicion_tipo": "copa_nacional", "pais_origen": "Espana"},
    {"slug": "fra.coupe_de_france", "competicion": "Coupe de France", "competicion_tipo": "copa_nacional", "pais_origen": "Francia"},
    {"slug": "ita.coppa_italia", "competicion": "Coppa Italia", "competicion_tipo": "copa_nacional", "pais_origen": "Italia"},
    {"slug": "arg.copa", "competicion": "Copa Argentina", "competicion_tipo": "copa_nacional", "pais_origen": "Argentina"},
    {"slug": "bra.copa_do_brazil", "competicion": "Copa do Brasil", "competicion_tipo": "copa_nacional", "pais_origen": "Brasil"},
]


def determinar_formato(competicion, fase_str):
    """Single-leg vs two-leg knockout segun copa + fase. [REF docs/papers/copa_modelado.md Q2]"""
    # Copas nacionales EUR/LATAM = single-leg knockout
    if competicion in {"FA Cup", "EFL Cup", "DFB Pokal", "Copa del Rey",
                        "Coupe de France", "Coppa Italia",
                        "Copa Argentina", "Copa do Brasil",
                        "FIFA Club World Cup", "Recopa Sudamericana"}:
        return "copa_knockout_single"
    # UCL/UEL/UECL: fase liga, knockout single (final), two_leg para octavos+
    if competicion in {"Champions League", "Europa League", "Conference League"}:
        if fase_str and "liga" in fase_str.lower():
            return "copa_grupo"
        if fase_str and "final" in fase_str.lower() and "semi" not in fase_str.lower():
            return "copa_knockout_single"
        return "copa_knockout_two_leg"
    # Libertadores/Sudamericana: grupos -> two_leg para eliminatorias -> single final
    if competicion in {"Libertadores", "Sudamericana"}:
        if fase_str and ("grupo" in fase_str.lower() or "group" in fase_str.lower()):
            return "copa_grupo"
        if fase_str and "final" in fase_str.lower() and "semi" not in fase_str.lower():
            return "copa_knockout_single"
        return "copa_knockout_two_leg"
    return "copa_otro"


def fetch_dia(slug, fecha_yyyymmdd):
    url = ESPN_BASE.format(liga=slug, fecha=fecha_yyyymmdd)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return None  # liga no existe ese dia
        raise


def parse_event(ev, copa_meta):
    """Convierte event ESPN a row dict."""
    comp = ev.get("competitions", [{}])[0]
    fecha_iso = ev.get("date", "")[:10]
    if not fecha_iso:
        return None
    cs = comp.get("competitors", [])
    if len(cs) != 2:
        return None
    home = next((c for c in cs if c.get("homeAway") == "home"), None)
    away = next((c for c in cs if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    home_name = home.get("team", {}).get("displayName")
    away_name = away.get("team", {}).get("displayName")
    if not home_name or not away_name:
        return None
    # Fase: del nombre de la season + "round"
    fase = (ev.get("season", {}).get("slug") or "").replace("-", " ") or None
    notes = comp.get("notes", [])
    if notes:
        fase = notes[0].get("headline") or fase
    # Status ESPN: state='post' o completed=True indica jugado.
    # Names observados: STATUS_FULL_TIME, STATUS_FINAL, STATUS_FINAL_PEN.
    status_type = comp.get("status", {}).get("type", {})
    is_completed = status_type.get("state") == "post" or status_type.get("completed") is True
    if is_completed:
        gh = home.get("score")
        ga = away.get("score")
        try:
            gh_int = int(gh) if gh is not None else None
            ga_int = int(ga) if ga is not None else None
        except (TypeError, ValueError):
            gh_int = ga_int = None
    else:
        gh_int = ga_int = None
    return {
        "fecha": fecha_iso,
        "local": home_name,
        "visita": away_name,
        "goles_l": gh_int,
        "goles_v": ga_int,
        "fase": fase,
    }


def insertar(con, copa_meta, row):
    cur = con.cursor()
    eq_l_oficial = obtener_nombre_estandar(row["local"], liga=copa_meta["competicion"], modo_interactivo=False)
    eq_v_oficial = obtener_nombre_estandar(row["visita"], liga=copa_meta["competicion"], modo_interactivo=False)
    eq_l_norm = limpiar_texto(eq_l_oficial)
    eq_v_norm = limpiar_texto(eq_v_oficial)
    formato = determinar_formato(copa_meta["competicion"], row["fase"])
    try:
        cur.execute("""
            INSERT INTO partidos_no_liga
            (fecha, competicion, competicion_tipo, pais_origen, fase,
             equipo_local, equipo_visita,
             equipo_local_norm, equipo_visita_norm,
             goles_l, goles_v, fuente, competicion_formato)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            row["fecha"], copa_meta["competicion"], copa_meta["competicion_tipo"],
            copa_meta["pais_origen"], row["fase"],
            eq_l_oficial, eq_v_oficial, eq_l_norm, eq_v_norm,
            row["goles_l"], row["goles_v"],
            "espn-2026-batch", formato,
        ))
        return "ins"
    except sqlite3.IntegrityError:
        # UPDATE goles si nueva info (ej partido jugado, antes era NULL)
        if row["goles_l"] is not None:
            cur.execute("""
                UPDATE partidos_no_liga
                SET goles_l = ?, goles_v = ?
                WHERE fecha = ? AND equipo_local = ? AND equipo_visita = ? AND competicion = ?
                  AND (goles_l IS NULL OR goles_v IS NULL)
            """, (row["goles_l"], row["goles_v"], row["fecha"],
                  eq_l_oficial, eq_v_oficial, copa_meta["competicion"]))
            if cur.rowcount > 0:
                return "upd"
        return "dup"


def daterange(d1, d2):
    cur = d1
    while cur <= d2:
        yield cur
        cur += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2025-07-01")
    ap.add_argument("--hasta", default=date.today().isoformat())
    args = ap.parse_args()
    d1 = datetime.strptime(args.desde, "%Y-%m-%d").date()
    d2 = datetime.strptime(args.hasta, "%Y-%m-%d").date()
    print(f"Scraping ESPN copas: {d1} a {d2}")
    con = sqlite3.connect(DB); con.text_factory = str

    totales = {"ins": 0, "upd": 0, "dup": 0, "skip": 0}
    for copa in COPAS:
        slug = copa["slug"]
        c_ins = c_upd = c_dup = c_dias_ok = 0
        for d in daterange(d1, d2):
            fecha_str = d.strftime("%Y%m%d")
            try:
                data = fetch_dia(slug, fecha_str)
            except Exception as e:
                print(f"  [ERROR] {slug} {fecha_str}: {e}")
                continue
            if not data:
                continue
            events = data.get("events", [])
            if not events:
                continue
            c_dias_ok += 1
            for ev in events:
                row = parse_event(ev, copa)
                if not row:
                    continue
                res = insertar(con, copa, row)
                if res == "ins": c_ins += 1
                elif res == "upd": c_upd += 1
                else: c_dup += 1
            time.sleep(0.05)  # politeness
        con.commit()
        print(f"  {slug:<28s} dias_con_events={c_dias_ok:>3d}  ins={c_ins:>4d}  upd={c_upd:>3d}  dup={c_dup:>4d}")
        totales["ins"] += c_ins; totales["upd"] += c_upd; totales["dup"] += c_dup

    con.close()
    print(f"\nTOTALES: ins={totales['ins']}, upd={totales['upd']}, dup={totales['dup']}")


if __name__ == "__main__":
    main()

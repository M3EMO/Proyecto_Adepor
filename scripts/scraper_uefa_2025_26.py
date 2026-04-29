"""
[F2 sub] Scraping copas UEFA 2025-26 (UCL/UEL/UECL) desde Wikipedia ES.

Fundamentación: docs/papers/copa_modelado.md Q2/Q3 — copa internacional es la
categoría con mejor predicción Elo (53%). Backtest 2026 actualmente solo tiene
48 partidos LATAM (Libertadores+Sudamericana parciales). Champions/Europa/
Conference 2025-26 tiene 144+288+288 partidos disponibles → critico para validar
motor copa V14 en in-sample 2026.

Estructura Wikipedia ES: cada partido es <table class="vevent"> con cells
estructurados (local, score, visita, fecha en metadata).

URLs:
- Fase liga UCL: Anexo:Fase_de_liga_de_la_Liga_de_Campeones_de_la_UEFA_2025-26
- Fase liga UEL: Anexo:Fase_de_liga_de_la_Liga_Europa_de_la_UEFA_2025-26
- Fase liga UECL: Anexo:Fase_de_liga_de_la_Liga_Conferencia_de_la_UEFA_2025-26

Inserta en partidos_no_liga con _norm + liga_local/visita + competicion_formato.
Idempotente via UNIQUE(fecha, equipo_local, equipo_visita, competicion).
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import obtener_nombre_estandar, limpiar_texto  # noqa

UA = "Mozilla/5.0 (Adepor-Research)"

COPAS = [
    {
        "url": "https://es.wikipedia.org/wiki/Anexo:Fase_de_liga_de_la_Liga_de_Campeones_de_la_UEFA_2025-26",
        "competicion": "Champions League",
        "competicion_tipo": "copa_internacional",
        "competicion_formato": "copa_grupo",  # fase liga es formato Suizo (similar grupos)
        "fase": "Fase de liga 2025-26",
    },
    {
        "url": "https://es.wikipedia.org/wiki/Anexo:Fase_de_liga_de_la_Liga_Europa_de_la_UEFA_2025-26",
        "competicion": "Europa League",
        "competicion_tipo": "copa_internacional",
        "competicion_formato": "copa_grupo",
        "fase": "Fase de liga 2025-26",
    },
    {
        "url": "https://es.wikipedia.org/wiki/Anexo:Fase_de_liga_de_la_Liga_Conferencia_de_la_UEFA_2025-26",
        "competicion": "Conference League",
        "competicion_tipo": "copa_internacional",
        "competicion_formato": "copa_grupo",
        "fase": "Fase de liga 2025-26",
    },
]

MES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12, "setiembre": 9,
}


def parse_fecha_es_full(texto):
    """Parsea '16 de septiembre de 2025' -> '2025-09-16'."""
    if not texto:
        return None
    t = texto.lower().strip()
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", t)
    if not m:
        return None
    dia, mes_n, anio = m.group(1), m.group(2), m.group(3)
    mes = MES_ES.get(mes_n)
    if not mes:
        return None
    return f"{int(anio):04d}-{mes:02d}-{int(dia):02d}"


def parse_resultado(texto):
    """'1:3', '0–5', '1-2' -> (1, 3)."""
    if not texto:
        return None, None
    m = re.match(r"\s*(\d+)\s*[-:–]\s*(\d+)", texto.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def normalize_team(name):
    """Limpia nombre del wiki (quita superíndices [n], paréntesis con país, etc)."""
    if not name:
        return ""
    name = re.sub(r"\[[^\]]+\]", "", name)  # [n], [a]
    name = re.sub(r"\(\w{2,3}\)", "", name)  # (esp), (ALE)
    return name.strip()


def parse_partidos(html, copa_meta):
    """Extrae partidos del HTML.

    Estructura UEFA Wikipedia ES 2025-26:
    <table class="vevent">
      <tbody><tr>
        <td>16 de septiembre de 2025</td>      <- fecha
        <td>PSV Eindhoven</td>                 <- local
        <td><b>1:3</b> (0:2)</td>              <- score (en <b>)
        <td>Union Saint-Gilloise</td>          <- visita
        <td>Philips Stadion, Eindhoven</td>    <- estadio
      </tr></tbody>
    </table>

    Hay 5 celdas en primera fila. Detectar la celda con fecha + tomar +1, +2, +3.
    """
    soup = BeautifulSoup(html, "html.parser")
    partidos = []
    vevents = soup.select("table.vevent")
    print(f"    vevents detectados: {len(vevents)}")

    n_skip_fecha = n_skip_score = n_ok = 0
    for ve in vevents:
        primera = ve.find("tr")
        if not primera:
            continue
        cells = primera.find_all(["th", "td"], recursive=False)
        if len(cells) < 4:
            continue

        # Detectar índice de la celda con fecha
        fecha = None
        idx_fecha = -1
        for i, c in enumerate(cells):
            txt = c.get_text(" ", strip=True)
            f = parse_fecha_es_full(txt)
            if f:
                fecha = f
                idx_fecha = i
                break
        if not fecha or idx_fecha + 3 >= len(cells):
            n_skip_fecha += 1
            continue

        local = cells[idx_fecha + 1].get_text(" ", strip=True)
        score_cell = cells[idx_fecha + 2]
        b_el = score_cell.find("b")
        score = b_el.get_text(" ", strip=True) if b_el else score_cell.get_text(" ", strip=True)
        visita = cells[idx_fecha + 3].get_text(" ", strip=True)

        local = normalize_team(local)
        visita = normalize_team(visita)
        gl, gv = parse_resultado(score)

        if not (local and visita):
            n_skip_score += 1
            continue
        n_ok += 1
        partidos.append({
            "fecha": fecha,
            "local": local,
            "visita": visita,
            "goles_l": gl,
            "goles_v": gv,
            "fase": copa_meta["fase"],
        })
    print(f"    parseados: {n_ok} (skip_fecha={n_skip_fecha}, skip_score={n_skip_score})")
    return partidos


def insertar(con, copa_meta, partidos):
    cur = con.cursor()
    n_ins = n_dup = 0
    for p in partidos:
        eq_l_oficial = obtener_nombre_estandar(p["local"], liga=copa_meta["competicion"], modo_interactivo=False)
        eq_v_oficial = obtener_nombre_estandar(p["visita"], liga=copa_meta["competicion"], modo_interactivo=False)
        eq_l_norm = limpiar_texto(eq_l_oficial)
        eq_v_norm = limpiar_texto(eq_v_oficial)
        try:
            cur.execute("""
                INSERT INTO partidos_no_liga
                (fecha, competicion, competicion_tipo, pais_origen, fase,
                 equipo_local, equipo_visita,
                 equipo_local_norm, equipo_visita_norm,
                 goles_l, goles_v, fuente,
                 competicion_formato)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["fecha"], copa_meta["competicion"], copa_meta["competicion_tipo"],
                "Internacional", p["fase"],
                eq_l_oficial, eq_v_oficial, eq_l_norm, eq_v_norm,
                p["goles_l"], p["goles_v"], "wikipedia-uefa-2025-26",
                copa_meta["competicion_formato"],
            ))
            n_ins += 1
        except sqlite3.IntegrityError:
            n_dup += 1
    con.commit()
    return n_ins, n_dup


def main():
    if not DB.exists():
        print(f"DB no existe: {DB}"); sys.exit(1)
    con = sqlite3.connect(DB); con.text_factory = str
    total_ins = total_dup = 0
    total_partidos = 0
    for copa in COPAS:
        print(f"\n=== {copa['competicion']} 2025-26 ===")
        print(f"  URL: {copa['url']}")
        try:
            r = requests.get(copa["url"], headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  [ERROR fetch] {e}")
            continue
        partidos = parse_partidos(r.text, copa)
        # Filtrar partidos sin resultado (futuros) — los persistimos igual con goles NULL
        n_jugados = sum(1 for p in partidos if p["goles_l"] is not None)
        print(f"  Partidos detectados: {len(partidos)} ({n_jugados} jugados)")
        ins, dup = insertar(con, copa, partidos)
        print(f"  insertados: {ins}, duplicados: {dup}")
        total_ins += ins; total_dup += dup; total_partidos += len(partidos)
        time.sleep(2)  # politeness
    con.close()
    print(f"\nTOTAL: detectados={total_partidos}, insertados={total_ins}, duplicados={total_dup}")


if __name__ == "__main__":
    main()

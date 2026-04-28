"""[adepor-5y0 sub-2] Wikipedia scraper para copas 2026 (API-Football Free no soporta).

Pages target:
  - es.wikipedia.org/wiki/Copa_Libertadores_2026
  - es.wikipedia.org/wiki/Copa_Sudamericana_2026
  - es.wikipedia.org/wiki/Copa_Argentina_2026
  - es.wikipedia.org/wiki/Copa_de_Brasil_2026  (portuguese fallback)

Estructura comun de las tablas con partidos (fase grupos):
  | Fecha | Lugar | Local | Resultado | Visitante |
  Ej: "8 de abril" "Medellin" "Independiente Medellin" "1:1" "Estudiantes (LP)"

Inserta en partidos_no_liga con fuente='wikipedia-2026' y resultados conocidos.
Idempotente: UNIQUE constraint sobre (fecha, equipo_local, equipo_visita, competicion).
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = 'Mozilla/5.0 (Adepor-research)'

# Mes Spanish -> num
MES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    # variantes
    'setiembre': 9,
}


def parse_fecha_es(texto, year):
    """Convierte '8 de abril' o '14 de abril de 2026' a YYYY-MM-DD."""
    if not texto: return None
    texto = texto.strip().lower()
    # Patrones: "DD de MES" o "DD de MES de YYYY"
    m = re.match(r'(\d+)\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?', texto)
    if not m: return None
    dia = int(m.group(1)); mes_nombre = m.group(2); year_match = m.group(3)
    mes = MES_ES.get(mes_nombre)
    if not mes: return None
    y = int(year_match) if year_match else year
    return f'{y:04d}-{mes:02d}-{dia:02d}'


def parse_resultado(texto):
    """'1:1' -> (1, 1); '-' -> (None, None)."""
    if not texto: return None, None
    texto = texto.strip()
    m = re.match(r'(\d+)\s*[-:]\s*(\d+)', texto)
    if m: return int(m.group(1)), int(m.group(2))
    return None, None


COPAS_2026 = [
    {
        'url': 'https://es.wikipedia.org/wiki/Copa_Libertadores_2026',
        'competicion': 'Libertadores',
        'tipo': 'copa_internacional',
        'pais_origen': 'Internacional',
        'year_default': 2026,
    },
    {
        'url': 'https://es.wikipedia.org/wiki/Copa_Sudamericana_2026',
        'competicion': 'Sudamericana',
        'tipo': 'copa_internacional',
        'pais_origen': 'Internacional',
        'year_default': 2026,
    },
    {
        'url': 'https://es.wikipedia.org/wiki/Copa_Argentina_2026',
        'competicion': 'Copa Argentina',
        'tipo': 'copa_nacional',
        'pais_origen': 'Argentina',
        'year_default': 2026,
    },
    {
        'url': 'https://es.wikipedia.org/wiki/Copa_de_Brasil_2026',
        'competicion': 'Copa do Brasil',
        'tipo': 'copa_nacional',
        'pais_origen': 'Brasil',
        'year_default': 2026,
    },
]


def fetch_html(url):
    r = requests.get(url, headers={'User-Agent': UA}, timeout=20)
    if r.status_code == 200:
        return r.text
    print(f'  HTTP {r.status_code} para {url}')
    return None


def extraer_partidos(html, year_default):
    """Extrae list of (fecha, local, visita, gl, gv, fase) de un page Wikipedia.

    Strategy: busca todas las wikitable, identifica filas con 5 cells matching
    [Fecha|Lugar|Local|Resultado|Visitante]. Salta header y rows malformadas.
    """
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', class_='wikitable')
    out = []
    fase_actual = None

    # Tambien buscar h3/h4 cercanos para fase
    body = soup.find('div', class_='mw-parser-output') or soup
    elements = body.find_all(['h2', 'h3', 'h4', 'table'])

    for el in elements:
        if el.name in ('h2', 'h3', 'h4'):
            txt = el.get_text(' ', strip=True)
            txt = re.sub(r'\[editar\]', '', txt).strip()
            fase_actual = txt[:60] if txt else None
        elif el.name == 'table' and 'wikitable' in (el.get('class') or []):
            rows = el.find_all('tr')
            for row in rows:
                cells = row.find_all(['th', 'td'])
                if len(cells) != 5:
                    continue
                txt = [c.get_text(' ', strip=True) for c in cells]
                # skip header
                if txt[0].lower() in ('fecha', '') or 'fecha' in txt[0].lower()[:6]:
                    continue
                # validate first col looks like date
                fecha = parse_fecha_es(txt[0], year_default)
                if not fecha:
                    continue
                lugar = txt[1]
                local = txt[2]
                resultado = txt[3]
                visita = txt[4]
                if not local or not visita:
                    continue
                gl, gv = parse_resultado(resultado)
                out.append({
                    'fecha': fecha,
                    'local': local,
                    'visita': visita,
                    'goles_l': gl,
                    'goles_v': gv,
                    'fase': fase_actual,
                })
    return out


def insertar_partidos(con, copa_meta, partidos):
    cur = con.cursor()
    n_ins = 0; n_dup = 0
    for p in partidos:
        try:
            cur.execute("""INSERT INTO partidos_no_liga
                (fecha, competicion, competicion_tipo, pais_origen, fase,
                 equipo_local, equipo_visita, goles_l, goles_v, fuente)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p['fecha'], copa_meta['competicion'], copa_meta['tipo'],
                 copa_meta['pais_origen'], p.get('fase'),
                 p['local'], p['visita'], p.get('goles_l'), p.get('goles_v'),
                 'wikipedia-2026'))
            n_ins += 1
        except sqlite3.IntegrityError:
            n_dup += 1
    con.commit()
    return n_ins, n_dup


def main():
    if not DB.exists():
        print(f'DB no existe: {DB}'); sys.exit(1)
    con = sqlite3.connect(DB)
    total_ins = 0; total_dup = 0
    for copa in COPAS_2026:
        print(f'\n=== {copa["competicion"]} 2026 ===')
        print(f'  URL: {copa["url"]}')
        html = fetch_html(copa['url'])
        if not html:
            print('  Skip (no HTML).')
            continue
        partidos = extraer_partidos(html, copa['year_default'])
        print(f'  Partidos parseados: {len(partidos)}')
        if partidos:
            n_ins, n_dup = insertar_partidos(con, copa, partidos)
            total_ins += n_ins; total_dup += n_dup
            print(f'  Insertados: {n_ins}, duplicados: {n_dup}')
            # Sample
            print(f'  Primeros 3:')
            for p in partidos[:3]:
                gl, gv = p['goles_l'], p['goles_v']
                res = f'{gl}-{gv}' if gl is not None else 'pend'
                print(f'    {p["fecha"]}  {p["local"]} {res} {p["visita"]} | fase={p["fase"]}')
        time.sleep(2)

    print(f'\n========== RESUMEN ==========')
    print(f'Total insertados: {total_ins}')
    print(f'Duplicados (skip): {total_dup}')
    con.close()


if __name__ == '__main__':
    main()

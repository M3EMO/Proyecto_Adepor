"""
Migra diccionario_equipos.json plano (364 entradas) a estructura anidada por liga.

Genera:
- Sub-dict por liga domestica con aliases -> nombre_oficial
- _meta.equipo_a_liga_home (string o lista para equipos ambiguos)
- _meta.ligas_por_copa (placeholder con las copas planeadas)

Inferencia de liga_home: el pais donde aparece el equipo en partidos_backtest.
Equipos en diccionario_equipos pero ausentes en DB -> sub-dict '_huerfanos'
(preservados para backwards-compat, deprecable en iteracion posterior).

Salida: diccionario_equipos.json (reemplaza el anterior; backup .bak creado).
Reporte a stdout con conteos y lista de ambiguos para review manual.
"""
import sqlite3
import json
import shutil
import sys
import unicodedata
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DICC_FILE = ROOT / 'diccionario_equipos.json'
DB_FILE = ROOT / 'fondo_quant.db'
BACKUP = ROOT / 'diccionario_equipos.json.bak'

LIGAS_POR_COPA_PLACEHOLDER = {
    "Libertadores":  ["Argentina", "Brasil", "Uruguay", "Chile", "Ecuador", "Peru", "Bolivia", "Colombia", "Venezuela", "Paraguay"],
    "Sudamericana":  ["Argentina", "Brasil", "Uruguay", "Chile", "Ecuador", "Peru", "Bolivia", "Colombia", "Venezuela", "Paraguay"],
    "Champions":     ["Espana", "Italia", "Alemania", "Francia", "Inglaterra", "Turquia", "Noruega"],
    "EuropaLeague":  ["Espana", "Italia", "Alemania", "Francia", "Inglaterra", "Turquia", "Noruega"]
}


def limpiar_texto(texto):
    if not texto:
        return ""
    texto_norm = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto).lower().strip())
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'[^a-z0-9]', '', texto_norm)


def main():
    if not DICC_FILE.exists():
        print(f"[ERROR] {DICC_FILE} no existe.")
        sys.exit(1)
    if not DB_FILE.exists():
        print(f"[ERROR] {DB_FILE} no existe.")
        sys.exit(1)

    # Backup
    shutil.copy2(DICC_FILE, BACKUP)
    print(f"[BACKUP] {BACKUP.name} creado.")

    with open(DICC_FILE, 'r', encoding='utf-8') as f:
        dict_plano = json.load(f)
    print(f"[INPUT] dict plano: {len(dict_plano)} aliases")

    # Inferir pais por nombre oficial desde DB
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT local, pais FROM partidos_backtest WHERE local IS NOT NULL AND pais IS NOT NULL
        UNION
        SELECT DISTINCT visita, pais FROM partidos_backtest WHERE visita IS NOT NULL AND pais IS NOT NULL
    """)
    equipo_a_paises = defaultdict(set)
    for nombre, pais in cur.fetchall():
        equipo_a_paises[nombre].add(pais)
    con.close()
    print(f"[DB] {len(equipo_a_paises)} equipos canonicos inferidos desde partidos_backtest")

    # _meta.equipo_a_liga_home: str si unico, list si ambiguo
    equipo_a_liga_home = {}
    ambiguos = []
    for nombre, paises in equipo_a_paises.items():
        if len(paises) == 1:
            equipo_a_liga_home[nombre] = next(iter(paises))
        else:
            equipo_a_liga_home[nombre] = sorted(paises)
            ambiguos.append((nombre, sorted(paises)))

    # Armar dict anidado: {pais: {alias_limpio: nombre_oficial}}
    nested = defaultdict(dict)
    huerfanos = {}  # aliases cuyo nombre_oficial no aparece en DB

    for alias_limpio, nombre_oficial in dict_plano.items():
        if nombre_oficial not in equipo_a_paises:
            huerfanos[alias_limpio] = nombre_oficial
            continue
        paises = equipo_a_paises[nombre_oficial]
        # Si ambiguo, replicamos el alias en cada liga (el lookup scoped lo resuelve)
        for pais in paises:
            nested[pais][alias_limpio] = nombre_oficial

    # Tambien asegurar que el alias propio del nombre oficial limpio este en su liga
    for nombre_oficial, paises in equipo_a_paises.items():
        clean = limpiar_texto(nombre_oficial)
        for pais in paises:
            if clean and clean not in nested[pais]:
                nested[pais][clean] = nombre_oficial

    # Construir JSON final
    out = {
        "_meta": {
            "version": "5.0",
            "estructura": "scoped_por_liga",
            "equipo_a_liga_home": dict(sorted(equipo_a_liga_home.items())),
            "ligas_por_copa": LIGAS_POR_COPA_PLACEHOLDER,
            "notas": "Dict anidado por liga domestica. Equipos con mismo nombre en varias ligas se listan en todas. Copas iteran sobre ligas_por_copa[copa]."
        }
    }
    for pais in sorted(nested.keys()):
        out[pais] = dict(sorted(nested[pais].items()))
    if huerfanos:
        out["_huerfanos"] = dict(sorted(huerfanos.items()))

    with open(DICC_FILE, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # Reporte
    print()
    print("=" * 60)
    print("MIGRACION COMPLETADA")
    print("=" * 60)
    print(f"Ligas en el dict: {len(nested)}")
    for pais in sorted(nested.keys()):
        print(f"  {pais:<15s} {len(nested[pais]):>4d} aliases")
    print(f"Huerfanos (nombre_oficial no en DB): {len(huerfanos)}")
    print(f"Ambiguos (equipos en >1 pais): {len(ambiguos)}")
    for nombre, paises in ambiguos:
        print(f"  {nombre!r:40} -> {paises}")
    print()
    print(f"Output: {DICC_FILE}")
    print(f"Backup: {BACKUP}")


if __name__ == "__main__":
    main()

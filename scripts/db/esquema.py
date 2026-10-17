"""
Esquema versionado de fondo_quant.db (auditoria 2026-10).

El esquema estaba disperso en ~49 scripts con CREATE/ALTER ad-hoc: una instalacion
nueva no podia reconstruir la DB. Este script congela el esquema real en git y crea
una DB vacia a partir de el.

Uso:
  python scripts/db/esquema.py --exportar            # DB actual -> docs/db_schema.sql
  python scripts/db/esquema.py --crear <ruta.db>     # docs/db_schema.sql -> DB vacia
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.config_sistema import DB_NAME  # noqa: E402

ESQUEMA = ROOT / 'docs' / 'db_schema.sql'


def exportar(db_path, destino=ESQUEMA):
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        raise FileNotFoundError(f'DB inexistente o vacia: {db_path}')
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    # Tablas primero (las vistas e indices dependen de ellas); sqlite_* son internas.
    filas = con.execute("""
        SELECT sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'view' THEN 2 ELSE 3 END, name
    """).fetchall()
    con.close()
    Path(destino).write_text(''.join(f'{s};\n\n' for (s,) in filas), encoding='utf-8')
    return len(filas)


def crear(db_path, origen=ESQUEMA):
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        raise FileExistsError(f'No se sobrescribe una DB existente: {db_path}')
    con = sqlite3.connect(db_path)
    con.executescript(Path(origen).read_text(encoding='utf-8'))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--exportar', action='store_true')
    g.add_argument('--crear', metavar='RUTA_DB')
    args = ap.parse_args()
    if args.exportar:
        print(f'{exportar(DB_NAME)} objetos exportados a {ESQUEMA}')
    else:
        crear(args.crear)
        print(f'DB vacia creada en {args.crear}')


if __name__ == '__main__':
    main()

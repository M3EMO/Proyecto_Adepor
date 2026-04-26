"""
migrate_clv_pct.py — Schema migration: 2 columnas CLV separadas (1X2 y O/U).

Bead: adepor-dl6 — Sub-tarea 3b.

Decision Lead 2026-04-25:
  - Opcion β: ALTER TABLE ADD COLUMN (preserva clv_registrado TEXT legacy con 20 'SI').
  - 2 columnas separadas (clv_pct_1x2, clv_pct_ou) en lugar de promedio ponderado.
    Razon: 1X2 y O/U son mercados independientes con dinamica distinta. Granularidad
    por mercado facilita analisis "donde tengo CLV+ sostenido".

Idempotente: si las columnas ya existen, no falla (verifica via PRAGMA table_info).
"""
import sqlite3
import sys

DB_NAME = 'fondo_quant.db'

COLUMNAS_NUEVAS = [
    ('clv_pct_1x2', 'REAL'),
    ('clv_pct_ou',  'REAL'),
]


def main():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(partidos_backtest)")
    cols_actuales = {row[1] for row in cursor.fetchall()}

    for col, tipo in COLUMNAS_NUEVAS:
        if col in cols_actuales:
            print(f"[SKIP] Columna {col} ya existe.")
            continue
        print(f"[ALTER] ADD COLUMN {col} {tipo}")
        cursor.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col} {tipo}")

    conn.commit()

    cursor.execute("PRAGMA table_info(partidos_backtest)")
    cols_post = {row[1] for row in cursor.fetchall()}
    for col, _ in COLUMNAS_NUEVAS:
        assert col in cols_post, f"Migracion fallida: {col} no esta en schema"

    conn.close()
    print("[OK] Migracion completada. Schema verificado.")


if __name__ == "__main__":
    main()

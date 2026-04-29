"""
[adepor-qqb] Backfill idempotente de columnas equipo_norm en tablas afectadas.

Llamado al inicio del pipeline (antes de Layer 3 evaluar) como defensa contra
INSERTs legacy que no popularan _norm correctamente. Idempotente: solo escribe
filas con _norm IS NULL o desactualizado vs limpiar_texto(equipo).

Tablas:
- posiciones_tabla_snapshot.equipo_norm
- partidos_historico_externo.ht_norm, at_norm
- partidos_no_liga.equipo_local_norm, equipo_visita_norm

Uso:
    py scripts/backfill_norm_columns.py            # apply
    py scripts/backfill_norm_columns.py --dry-run  # preview
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
DRY = "--dry-run" in sys.argv

sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import limpiar_texto  # noqa: E402


def backfill_tabla(conn, tabla, col_equipo, col_norm):
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT rowid, {col_equipo}, {col_norm} FROM {tabla} "
        f"WHERE {col_equipo} IS NOT NULL"
    ).fetchall()
    n_to_update = 0
    n_skip = 0
    for rid, eq, current_norm in rows:
        expected = limpiar_texto(eq)
        if current_norm == expected:
            n_skip += 1
            continue
        if not DRY:
            cur.execute(
                f"UPDATE {tabla} SET {col_norm}=? WHERE rowid=?",
                (expected, rid),
            )
        n_to_update += 1
    return n_to_update, n_skip


def main():
    if not DB.exists():
        print(f"DB no existe: {DB}")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    conn.text_factory = str
    print(f"{'DRY-RUN' if DRY else 'APPLY'} backfill _norm columns\n")

    config = [
        ("posiciones_tabla_snapshot", "equipo", "equipo_norm"),
        ("partidos_historico_externo", "ht", "ht_norm"),
        ("partidos_historico_externo", "at", "at_norm"),
        ("partidos_no_liga", "equipo_local", "equipo_local_norm"),
        ("partidos_no_liga", "equipo_visita", "equipo_visita_norm"),
    ]

    total_updated = 0
    for tabla, col_eq, col_norm in config:
        n_upd, n_skip = backfill_tabla(conn, tabla, col_eq, col_norm)
        print(f"  {tabla}.{col_norm}: updated={n_upd} skipped={n_skip}")
        total_updated += n_upd

    if not DRY:
        conn.commit()
    conn.close()
    print(f"\nTotal updates: {total_updated}")
    return total_updated


if __name__ == "__main__":
    main()

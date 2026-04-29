"""
[adepor-04p] Ingesta ClubElo CSV para cross-validation Elo Adepor.

ClubElo API (clubelo.com):
- /<CLUBNAME> -> CSV histórico ratings de un club (1939-presente)
- /<YYYY-MM-DD> -> snapshot de TODOS los clubes en esa fecha

Schema CSV: Rank, Club, Country, Level, Elo, From, To

Estrategia:
1. Snapshot 2024-12-31 (cierre OOS) para todos clubes top.
2. Persistir en tabla clubelo_ratings.
3. Cross-correlation con equipo_nivel_elo Adepor.

[REF: docs/papers/elo_calibracion.md Q3 — ClubElo como puente cross-liga]
"""
from __future__ import annotations
import sqlite3
import sys
import urllib.request
import urllib.parse
import csv
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
UA = "Adepor-Research/1.0"


def crear_tabla(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clubelo_ratings (
            club TEXT NOT NULL,
            country TEXT,
            level INTEGER,
            elo_clubelo REAL,
            fecha_from TEXT NOT NULL,
            fecha_to TEXT NOT NULL,
            rank_at INTEGER,
            timestamp_insertado TEXT,
            PRIMARY KEY (club, fecha_from)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_clubelo_country
        ON clubelo_ratings(country, fecha_from)
    """)
    conn.commit()


def fetch_snapshot(fecha):
    """Snapshot todos los clubes en fecha YYYY-MM-DD."""
    url = f"http://api.clubelo.com/{fecha}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", errors="ignore")
    reader = csv.DictReader(StringIO(body))
    return list(reader)


def insertar_snapshot(conn, rows, fecha_label):
    cur = conn.cursor()
    n_ins = 0
    import time
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        try:
            rank = int(r["Rank"]) if r.get("Rank") and r["Rank"] != "None" else None
            elo = float(r["Elo"]) if r.get("Elo") else None
            level = int(r["Level"]) if r.get("Level") else None
            cur.execute("""
                INSERT OR REPLACE INTO clubelo_ratings
                (club, country, level, elo_clubelo, fecha_from, fecha_to,
                 rank_at, timestamp_insertado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["Club"], r.get("Country"), level, elo,
                r.get("From"), r.get("To"), rank, ts
            ))
            n_ins += 1
        except (ValueError, KeyError) as e:
            continue
    conn.commit()
    return n_ins


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    crear_tabla(conn)

    # Snapshots clave: 2024-12-31 (cierre OOS) + 2025-12-31 + hoy
    snapshots = ["2024-12-31", "2025-12-31", "2026-04-28"]
    for fecha in snapshots:
        print(f"\nFetching ClubElo snapshot {fecha}...")
        try:
            rows = fetch_snapshot(fecha)
            print(f"  N clubes: {len(rows)}")
            n_ins = insertar_snapshot(conn, rows, fecha)
            print(f"  Insertados/replaced: {n_ins}")
        except Exception as e:
            print(f"  ERROR: {e}")

    # Verificación
    print("\n=== Verificacion ===")
    n_total = conn.execute("SELECT COUNT(*) FROM clubelo_ratings").fetchone()[0]
    print(f"  Total filas clubelo_ratings: {n_total}")
    print("  Top 10 por Elo (mas reciente):")
    for r in conn.execute("""
        SELECT club, country, elo_clubelo, fecha_from
        FROM clubelo_ratings
        WHERE fecha_from >= '2026-04-01'
        ORDER BY elo_clubelo DESC LIMIT 10
    """).fetchall():
        print(f"    {r[0]:<25s} ({r[1]:<3s}) elo={r[2]:.1f}  fecha={r[3]}")

    conn.close()


if __name__ == "__main__":
    main()

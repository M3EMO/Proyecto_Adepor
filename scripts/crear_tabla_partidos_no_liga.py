"""[adepor-5y0.1] Crea tabla partidos_no_liga + view v_partidos_unificado.

partidos_no_liga registra partidos de copas nacionales (FA Cup, Copa Argentina,
Copa del Rey, Coppa Italia, etc.) y copas internacionales (Champions, Europa,
Conference, Libertadores, Sudamericana, Recopa) para que el motor pueda calcular
gap_dias_desde_ultimo_partido por (equipo, fecha).

Apoya:
  - adepor-5y0 EPIC calendario completo equipos
  - adepor-tyb [PROPOSAL] Layer 3 H4 X-rescue per-liga (refinement con cansancio mid-week)
  - adepor-p4e (Q3 ARG 2023 copas internacionales)

Idempotente: si la tabla/view ya existe, no toca nada.
Tests al final: helper gap_dias(equipo, fecha) usando la view.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'


def crear_tabla_y_view(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS partidos_no_liga (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            competicion TEXT NOT NULL,
            competicion_tipo TEXT NOT NULL CHECK(competicion_tipo IN ('copa_nacional','copa_internacional')),
            pais_origen TEXT NOT NULL,
            fase TEXT,
            equipo_local TEXT NOT NULL,
            equipo_visita TEXT NOT NULL,
            goles_l INTEGER,
            goles_v INTEGER,
            fuente TEXT NOT NULL,
            timestamp_inserted TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fecha, equipo_local, equipo_visita, competicion)
        )
    """)
    print("[OK] Tabla partidos_no_liga creada (o ya existia).")

    cur.execute("""CREATE INDEX IF NOT EXISTS idx_pnl_local_fecha
                   ON partidos_no_liga(equipo_local, fecha)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_pnl_visita_fecha
                   ON partidos_no_liga(equipo_visita, fecha)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_pnl_fecha
                   ON partidos_no_liga(fecha)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_pnl_competicion
                   ON partidos_no_liga(competicion)""")
    print("[OK] Indices creados.")

    cur.execute("DROP VIEW IF EXISTS v_partidos_unificado")
    cur.execute("""
        CREATE VIEW v_partidos_unificado AS
        SELECT
            substr(fecha,1,10)        AS fecha,
            ht                         AS equipo_local,
            at                         AS equipo_visita,
            liga                       AS pais_origen,
            'Liga ' || liga            AS competicion,
            'liga'                     AS competicion_tipo,
            NULL                       AS fase,
            hg                         AS goles_l,
            ag                         AS goles_v,
            'partidos_historico_externo' AS origen
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 OR hg IS NOT NULL

        UNION ALL

        SELECT
            fecha, equipo_local, equipo_visita, pais_origen,
            competicion, competicion_tipo, fase,
            goles_l, goles_v,
            'partidos_no_liga'         AS origen
        FROM partidos_no_liga
    """)
    print("[OK] View v_partidos_unificado creada.")

    conn.commit()


def test_helper_gap(conn):
    """Test rapido: para algunos equipos conocidos, calcular gap entre 2 partidos."""
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM v_partidos_unificado
    """)
    n_total = cur.fetchone()[0]
    print(f"\n[TEST] v_partidos_unificado N total = {n_total:,}")

    cur.execute("""
        SELECT competicion_tipo, COUNT(*) FROM v_partidos_unificado GROUP BY competicion_tipo
    """)
    for tipo, n in cur.fetchall():
        print(f"  {tipo}: {n:,}")

    print("\n[TEST] Gap entre dos liga-matches consecutivos River Plate 2023:")
    cur.execute("""
        SELECT fecha, equipo_local, equipo_visita, competicion
        FROM v_partidos_unificado
        WHERE (equipo_local='River Plate' OR equipo_visita='River Plate')
          AND pais_origen='Argentina'
          AND fecha LIKE '2023%'
        ORDER BY fecha ASC LIMIT 5
    """)
    for r in cur.fetchall():
        print(f"  {r[0]} | {r[1]:<28} vs {r[2]:<28} | {r[3]}")

    print("\n[TEST] Helper Python gap_dias(equipo, fecha):")
    def gap_dias(equipo, fecha):
        r = cur.execute("""
            SELECT fecha FROM v_partidos_unificado
            WHERE (equipo_local=? OR equipo_visita=?) AND fecha < ?
            ORDER BY fecha DESC LIMIT 1
        """, (equipo, equipo, fecha)).fetchone()
        if not r: return None
        from datetime import datetime
        d1 = datetime.strptime(r[0], '%Y-%m-%d')
        d2 = datetime.strptime(fecha[:10], '%Y-%m-%d')
        return (d2 - d1).days

    casos = [
        ('River Plate', '2023-08-15'),
        ('Man City', '2024-03-15'),
        ('Boca Juniors', '2023-05-01'),
    ]
    for eq, fc in casos:
        g = gap_dias(eq, fc)
        print(f"  gap_dias({eq!r}, {fc!r}) = {g} dias")


def main():
    if not DB.exists():
        print(f"[ERROR] {DB} no existe.")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    crear_tabla_y_view(conn)
    test_helper_gap(conn)
    conn.close()
    print("\n[OK] Migracion completa.")


if __name__ == "__main__":
    main()

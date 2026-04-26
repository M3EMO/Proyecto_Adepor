"""Investiga cuales equipos faltantes en equipos_altitud son andinos (>1500m).

Read-only diagnostico para guiar el INSERT de adepor-om4.
"""
import sqlite3

DB_PATH = "fondo_quant.db"


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1. Equipos faltantes (LOCAL en partidos_backtest, no en equipos_altitud)
    cur.execute("""
        SELECT pb.pais, pb.local AS equipo, COUNT(*) AS partidos,
               SUM(CASE WHEN pb.estado='Liquidado' THEN 1 ELSE 0 END) AS liquidados
        FROM partidos_backtest pb
        LEFT JOIN equipos_altitud ea ON ea.equipo_real = pb.local
        WHERE pb.pais IN ('Bolivia','Peru','Ecuador','Colombia')
          AND ea.equipo_real IS NULL
        GROUP BY pb.pais, pb.local
        ORDER BY pb.pais, partidos DESC
    """)
    rows = cur.fetchall()
    print(f"=== {len(rows)} equipos LOCAL faltantes ===")

    # 2. Por cada uno, mostrar fechas/visita para context (ej. detectar copas internacionales)
    for r in rows:
        pais, equipo, npart, nliq = r
        cur.execute("""
            SELECT fecha, local, visita
            FROM partidos_backtest
            WHERE local = ? OR visita = ?
            ORDER BY fecha
            LIMIT 3
        """, (equipo, equipo))
        ej = cur.fetchall()
        print(f"\n[{pais}] {equipo:<35} ({nliq}L/{npart}T)")
        for e in ej:
            print(f"   {e[0]} {e[1]} vs {e[2]}")

    con.close()


if __name__ == "__main__":
    main()

"""
[adepor adepor-9uq] Tabla shadow para M.2 (n_acum_l filter) logging IS 2026.

Loggea TODOS los picks que el motor calculó (incluyendo los que M.2 bloqueó),
con n_acum_l calculado on-the-fly + outcome real. Permite verificar trigger
N>=200 picks >=60 in-sample 2026 para PROPOSAL M.2 condicional.
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks_shadow_m2_log (
    id_partido TEXT NOT NULL,
    fecha TEXT NOT NULL,
    pais TEXT NOT NULL,
    local TEXT NOT NULL,
    visita TEXT NOT NULL,
    n_acum_l INTEGER,
    n_acum_v INTEGER,
    apuesta_1x2 TEXT,
    cuota_pick REAL,
    goles_l INTEGER,
    goles_v INTEGER,
    outcome_real TEXT,
    hit INTEGER,
    pasaria_m2 INTEGER,  -- 1 si n_acum_l < 60 (pasa filtro), 0 si n_acum_l >= 60 (bloqueado)
    fecha_log TEXT NOT NULL,
    PRIMARY KEY (id_partido)
);
CREATE INDEX IF NOT EXISTS idx_psm2_n_acum ON picks_shadow_m2_log(n_acum_l);
CREATE INDEX IF NOT EXISTS idx_psm2_pais_fecha ON picks_shadow_m2_log(pais, fecha);
"""


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    print("=== Backfill picks_shadow_m2_log para IS 2026 TOP-5 ===")
    ligas_m1 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]
    ph = ",".join("?" for _ in ligas_m1)

    # Picks reales IS 2026
    rows = cur.execute(f"""
        SELECT id_partido, fecha, pais, local, visita,
               apuesta_1x2, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE fecha >= '2026-01-01' AND pais IN ({ph})
          AND apuesta_1x2 LIKE '%LOCAL%' OR apuesta_1x2 LIKE '%VISITA%' OR apuesta_1x2 LIKE '%EMPATE%'
    """, ligas_m1).fetchall()

    inserts = []
    import datetime as dt
    log_ts = dt.datetime.now().isoformat(timespec="seconds")

    for r in rows:
        id_p, fecha, pais, local, visita, apuesta, c1, cx, c2, gl, gv = r

        # n_acum_l: contar partidos del equipo local antes
        n_phe = cur.execute("""SELECT COUNT(*) FROM partidos_historico_externo
                                WHERE liga=? AND (ht=? OR at=?) AND fecha < ?""",
                            (pais, local, local, fecha)).fetchone()[0]
        n_pb = cur.execute("""SELECT COUNT(*) FROM partidos_backtest
                                WHERE pais=? AND (local=? OR visita=?) AND fecha < ?""",
                            (pais, local, local, fecha)).fetchone()[0]
        n_acum_l = n_phe + n_pb

        n_phe_v = cur.execute("""SELECT COUNT(*) FROM partidos_historico_externo
                                  WHERE liga=? AND (ht=? OR at=?) AND fecha < ?""",
                              (pais, visita, visita, fecha)).fetchone()[0]
        n_pb_v = cur.execute("""SELECT COUNT(*) FROM partidos_backtest
                                  WHERE pais=? AND (local=? OR visita=?) AND fecha < ?""",
                            (pais, visita, visita, fecha)).fetchone()[0]
        n_acum_v = n_phe_v + n_pb_v

        # outcome
        outcome = None; hit = None
        if gl is not None and gv is not None:
            outcome = "1" if gl > gv else ("X" if gl == gv else "2")
            # parsea apuesta texto
            am = None
            if "LOCAL" in (apuesta or ""): am = "1"
            elif "VISITA" in (apuesta or ""): am = "2"
            elif "EMPATE" in (apuesta or ""): am = "X"
            if am:
                hit = int(am == outcome)

        cuota_pick = None
        if "LOCAL" in (apuesta or ""): cuota_pick = c1
        elif "VISITA" in (apuesta or ""): cuota_pick = c2
        elif "EMPATE" in (apuesta or ""): cuota_pick = cx

        pasaria = 1 if n_acum_l < 60 else 0

        inserts.append((
            id_p, fecha, pais, local, visita,
            n_acum_l, n_acum_v, apuesta, cuota_pick,
            gl, gv, outcome, hit, pasaria, log_ts,
        ))

    cur.executemany("""
        INSERT OR REPLACE INTO picks_shadow_m2_log
        (id_partido, fecha, pais, local, visita,
         n_acum_l, n_acum_v, apuesta_1x2, cuota_pick,
         goles_l, goles_v, outcome_real, hit, pasaria_m2, fecha_log)
        VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?,?,?)
    """, inserts)
    conn.commit()
    print(f"Persistido: {len(inserts)} filas en picks_shadow_m2_log")

    # Reporte trigger 9uq
    print()
    print("=== Trigger adepor-9uq: picks IS 2026 con n_acum_l >= 60 ===")
    r = cur.execute("""SELECT COUNT(*),
                              SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END),
                              AVG(cuota_pick)
                       FROM picks_shadow_m2_log
                       WHERE n_acum_l >= 60 AND outcome_real IS NOT NULL""").fetchone()
    n, h, c_avg = r[0], r[1] or 0, r[2] or 0
    print(f"  N picks IS 2026 con n_acum_l>=60 (BLOQUEADOS por M.2): {n}")
    if n > 0:
        hit_pct = 100*h/n
        print(f"  Hit rate: {h}/{n} = {hit_pct:.1f}%")
        print(f"  Cuota promedio: {c_avg:.3f}")
        if c_avg > 1.01:
            yld_simple = hit_pct/100 * c_avg - 1
            print(f"  Yield simple aprox: {100*yld_simple:+.2f}%")
    print()
    if n >= 200:
        print(f"  ★ TRIGGER 9uq MET: N>=200 → análisis bucket >=60 disponible")
    else:
        print(f"  Trigger pending: faltan {200-n} picks bucket >=60 para N=200")

    # Distribución per liga
    print()
    print("Por liga (subset n_acum_l>=60):")
    for r in cur.execute("""SELECT pais, COUNT(*),
                                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                            FROM picks_shadow_m2_log
                            WHERE n_acum_l >= 60 AND outcome_real IS NOT NULL
                            GROUP BY pais ORDER BY 2 DESC"""):
        if r[1] > 0:
            print(f"  {r[0]:<13s} N={r[1]:>4d} hit={100*(r[2] or 0)/r[1]:.1f}%")
    conn.close()


if __name__ == "__main__":
    main()

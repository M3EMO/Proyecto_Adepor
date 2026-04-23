"""
Schema migration: PK compuesta (equipo_norm, liga) en historial_equipos y
UNIQUE (nombre, liga) en equipos_stats.

Motivo: permite que un equipo con mismo nombre canonico coexista en ligas
distintas (Everton Chile + Everton Inglaterra, Liverpool Inglaterra + Liverpool
Uruguay, etc.) con su propia EMA/stats sin pisarse.

SQLite no soporta ALTER PRIMARY KEY directamente. Patron estandar:
  1. CREATE TABLE _new con nuevo schema
  2. INSERT INTO _new SELECT * FROM old
  3. DROP TABLE old
  4. ALTER TABLE _new RENAME TO old

Ejecucion en una sola transaccion. Rollback si cualquier paso falla.

Idempotente: si la tabla ya tiene PK/UNIQUE compuesto, no hace nada.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'


def _get_ddl(cur, tabla):
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,))
    r = cur.fetchone()
    return r[0] if r else None


def _tiene_pk_compuesta_historial(cur):
    ddl = _get_ddl(cur, 'historial_equipos') or ""
    # Heuristica: la PK nueva tiene "PRIMARY KEY (equipo_norm, liga)" explicito
    return 'PRIMARY KEY (equipo_norm, liga)' in ddl.replace('\n', ' ').replace('  ', ' ')


def _tiene_unique_compuesto_equipos(cur):
    ddl = _get_ddl(cur, 'equipos_stats') or ""
    return 'UNIQUE(nombre, liga)' in ddl.replace(' ', '') or 'UNIQUE (nombre, liga)' in ddl


def migrar_historial_equipos(cur):
    if _tiene_pk_compuesta_historial(cur):
        print("  historial_equipos: ya tiene PK compuesta, skip.")
        return 0
    print("  historial_equipos: migrando a PK (equipo_norm, liga)...")
    cur.execute("""
        CREATE TABLE historial_equipos_new (
            equipo_norm TEXT NOT NULL,
            equipo_real TEXT,
            liga TEXT NOT NULL,
            ema_xg_favor REAL,
            ema_xg_contra REAL,
            partidos_analizados INTEGER,
            ultima_actualizacion TEXT,
            ema_xg_favor_home REAL DEFAULT 1.4,
            ema_xg_contra_home REAL DEFAULT 1.4,
            partidos_home INTEGER DEFAULT 0,
            ema_xg_favor_away REAL DEFAULT 1.4,
            ema_xg_contra_away REAL DEFAULT 1.4,
            partidos_away INTEGER DEFAULT 0,
            ultimo_partido_procesado TEXT,
            ema_var_favor_home REAL DEFAULT 0.1,
            ema_var_contra_home REAL DEFAULT 0.1,
            ema_var_favor_away REAL DEFAULT 0.1,
            ema_var_contra_away REAL DEFAULT 0.1,
            PRIMARY KEY (equipo_norm, liga)
        )
    """)
    cur.execute("""
        INSERT INTO historial_equipos_new (
            equipo_norm, equipo_real, liga, ema_xg_favor, ema_xg_contra,
            partidos_analizados, ultima_actualizacion,
            ema_xg_favor_home, ema_xg_contra_home, partidos_home,
            ema_xg_favor_away, ema_xg_contra_away, partidos_away,
            ultimo_partido_procesado,
            ema_var_favor_home, ema_var_contra_home,
            ema_var_favor_away, ema_var_contra_away
        )
        SELECT
            equipo_norm, equipo_real, COALESCE(liga, 'DESCONOCIDA'), ema_xg_favor, ema_xg_contra,
            partidos_analizados, ultima_actualizacion,
            ema_xg_favor_home, ema_xg_contra_home, partidos_home,
            ema_xg_favor_away, ema_xg_contra_away, partidos_away,
            ultimo_partido_procesado,
            ema_var_favor_home, ema_var_contra_home,
            ema_var_favor_away, ema_var_contra_away
        FROM historial_equipos
    """)
    migradas = cur.rowcount
    cur.execute("DROP TABLE historial_equipos")
    cur.execute("ALTER TABLE historial_equipos_new RENAME TO historial_equipos")
    print(f"  historial_equipos: {migradas} filas migradas.")
    return migradas


def migrar_equipos_stats(cur):
    if _tiene_unique_compuesto_equipos(cur):
        print("  equipos_stats: ya tiene UNIQUE compuesto, skip.")
        return 0
    print("  equipos_stats: migrando UNIQUE nombre -> UNIQUE (nombre, liga)...")
    cur.execute("""
        CREATE TABLE equipos_stats_new (
            id_equipo INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            liga TEXT NOT NULL,
            xg_local REAL DEFAULT 1.35,
            xga_local REAL DEFAULT 1.15,
            xg_visita REAL DEFAULT 1.15,
            xga_visita REAL DEFAULT 1.35,
            partidos_dt INTEGER DEFAULT 10,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dt_nombre TEXT DEFAULT 'Desconocido',
            UNIQUE(nombre, liga)
        )
    """)
    cur.execute("""
        INSERT INTO equipos_stats_new (
            id_equipo, nombre, liga, xg_local, xga_local, xg_visita, xga_visita,
            partidos_dt, fecha_actualizacion, dt_nombre
        )
        SELECT id_equipo, nombre, liga, xg_local, xga_local, xg_visita, xga_visita,
               partidos_dt, fecha_actualizacion, dt_nombre
        FROM equipos_stats
    """)
    migradas = cur.rowcount
    cur.execute("DROP TABLE equipos_stats")
    cur.execute("ALTER TABLE equipos_stats_new RENAME TO equipos_stats")
    print(f"  equipos_stats: {migradas} filas migradas.")
    return migradas


def main():
    if not DB.exists():
        print(f"[ERROR] {DB} no existe.")
        sys.exit(1)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        print("[MIGRATION] Schema migration: PK/UNIQUE compuesto por (nombre, liga)")
        n_hist = migrar_historial_equipos(cur)
        n_stats = migrar_equipos_stats(cur)
        conn.commit()
        print(f"[OK] Migracion exitosa: {n_hist} filas historial + {n_stats} filas equipos_stats")
    except Exception as e:
        conn.rollback()
        print(f"[ROLLBACK] Error durante migracion: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
Crea una fondo_quant.db nueva y operable (auditoria 2026-10: la DB de produccion se perdio).

- Crea config_motor_valores (indice + trigger de bloqueo) y siembra los parametros del v2.
- Crea las tablas base que los motores leen antes de crearlas ellos mismos.

Uso:  python scripts/db/inicializar_db.py [ruta.db]   (default: DB_NAME / ADEPOR_DB)
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.ingesta.motor_oddspapi import SQL_CUOTAS_FORWARD  # noqa: E402

CONFIG_MOTOR = """
CREATE TABLE IF NOT EXISTS config_motor_valores (
    clave               TEXT NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'global',
    valor_real          REAL,
    valor_texto         TEXT,
    tipo                TEXT NOT NULL,
    fuente              TEXT,
    bloqueado           INTEGER NOT NULL DEFAULT 0,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (clave, scope)
);
CREATE INDEX IF NOT EXISTS idx_config_clave ON config_motor_valores(clave);
CREATE TRIGGER IF NOT EXISTS trg_config_bloqueado_no_update
BEFORE UPDATE ON config_motor_valores
FOR EACH ROW WHEN OLD.bloqueado = 1
BEGIN
    SELECT RAISE(ABORT, 'config_motor_valores: fila bloqueada, modificar bloqueado=0 primero');
END;
"""

# Mismos valores que los defaults de src/nucleo/valor_v2.py. bloqueado=0: D-020 los deja
# provisorios hasta recalibrar el frente de Pareto con >=50 picks liquidados.
# (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
SEMILLAS = [
    ('umbral_ev_v2', 'global', 0.02, None, 'float', 'valor_v2.py (D-019)', 0),
    ('fraccion_kelly_v2', 'global', 0.25, None, 'float', 'valor_v2.py (D-020)', 0),
    ('tope_stake_v2', 'global', 0.005, None, 'float', 'valor_v2.py (D-020)', 0),
]

# Esquema completo: antes las columnas se agregaban con ALTER dispersos en varios motores
# y una DB nueva fallaba en el primer motor que leia una columna aun no creada.
TABLAS_BASE = """
CREATE TABLE IF NOT EXISTS partidos_backtest (
    id_partido TEXT PRIMARY KEY, fecha TEXT, pais TEXT, local TEXT, visita TEXT,
    cuota_1 REAL DEFAULT 0, cuota_x REAL DEFAULT 0, cuota_2 REAL DEFAULT 0,
    cuota_o25 REAL DEFAULT 0, cuota_u25 REAL DEFAULT 0,
    apuesta_1x2 TEXT DEFAULT 'pendiente', apuesta_ou TEXT DEFAULT 'pendiente',
    stake_1x2 REAL DEFAULT 0, stake_ou REAL DEFAULT 0,
    goles_l INTEGER, goles_v INTEGER, estado TEXT DEFAULT 'Pendiente',
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    cuota_cierre_1x2 REAL, cuota_cierre_ou REAL,
    clv_pct_1x2 REAL, clv_pct_ou REAL,
    pin_1 REAL DEFAULT 0, pin_x REAL DEFAULT 0, pin_2 REAL DEFAULT 0,
    pin_o25 REAL DEFAULT 0, pin_u25 REAL DEFAULT 0,
    pin_cierre_1 REAL, pin_cierre_x REAL, pin_cierre_2 REAL,
    pin_cierre_o25 REAL, pin_cierre_u25 REAL);
CREATE INDEX IF NOT EXISTS idx_pb_estado_fecha ON partidos_backtest(estado, fecha);
CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS apuestas_confirmadas (
    id_partido TEXT NOT NULL, mercado TEXT NOT NULL, pick TEXT NOT NULL,
    cuota_tomada REAL NOT NULL, stake REAL NOT NULL, ts TEXT DEFAULT CURRENT_TIMESTAMP,
    casa TEXT,
    PRIMARY KEY (id_partido, mercado));
""" + SQL_CUOTAS_FORWARD


def inicializar(db_path):
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        raise FileExistsError(f'La DB ya existe, no se toca: {db_path}')
    con = sqlite3.connect(db_path)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript(CONFIG_MOTOR)
        con.executemany("""INSERT OR IGNORE INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", SEMILLAS)
        con.executescript(TABLAS_BASE)
        con.commit()
    finally:
        con.close()


if __name__ == '__main__':
    destino = sys.argv[1] if len(sys.argv) > 1 else DB_NAME
    inicializar(destino)
    print(f'DB nueva lista en {destino}')

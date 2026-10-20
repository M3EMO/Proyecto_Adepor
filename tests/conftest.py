"""Fixtures compartidas. La DB de tests vive en un tmp aislado: ADEPOR_DB se fija
ANTES de importar src.*, porque config_sistema resuelve DB_NAME al importarse."""
import os
import sqlite3
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="adepor_test_")
os.environ["ADEPOR_DB"] = os.path.join(_TMP, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

SCHEMA = """
CREATE TABLE partidos_backtest (
    id_partido TEXT PRIMARY KEY, fecha TEXT, pais TEXT, local TEXT, visita TEXT,
    cuota_1 REAL DEFAULT 0, cuota_x REAL DEFAULT 0, cuota_2 REAL DEFAULT 0,
    cuota_o25 REAL DEFAULT 0, cuota_u25 REAL DEFAULT 0,
    apuesta_1x2 TEXT DEFAULT 'pendiente', apuesta_ou TEXT DEFAULT 'pendiente',
    stake_1x2 REAL DEFAULT 0, stake_ou REAL DEFAULT 0,
    goles_l INTEGER, goles_v INTEGER, estado TEXT DEFAULT 'Pendiente',
    cuota_cierre_1x2 REAL, cuota_cierre_ou REAL, clv_pct_1x2 REAL, clv_pct_ou REAL
);
CREATE TABLE config_motor_valores (
    clave TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global', valor_real REAL,
    valor_texto TEXT, tipo TEXT NOT NULL, fuente TEXT, bloqueado INTEGER NOT NULL DEFAULT 0,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (clave, scope)
);
CREATE TABLE configuracion (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE log_alertas (id_alerta TEXT PRIMARY KEY, partido TEXT NOT NULL,
    mercado TEXT NOT NULL, pick TEXT NOT NULL, stake_enviado REAL, timestamp TEXT);
"""


@pytest.fixture
def db():
    """DB vacia con el esquema minimo del pipeline. Devuelve una conexion abierta."""
    path = os.environ["ADEPOR_DB"]
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    yield conn
    conn.close()


# Algunos modulos leen config_motor_valores al importarse:
# la DB debe tener el esquema antes de la coleccion de tests.
_c = sqlite3.connect(os.environ["ADEPOR_DB"])
_c.executescript(SCHEMA)
_c.close()

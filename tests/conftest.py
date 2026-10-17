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
    prob_1 REAL DEFAULT 0, prob_x REAL DEFAULT 0, prob_2 REAL DEFAULT 0,
    prob_o25 REAL DEFAULT 0, prob_u25 REAL DEFAULT 0,
    apuesta_1x2 TEXT DEFAULT 'pendiente', apuesta_ou TEXT DEFAULT 'pendiente',
    stake_1x2 REAL DEFAULT 0, stake_ou REAL DEFAULT 0,
    goles_l INTEGER, goles_v INTEGER, estado TEXT DEFAULT 'Pendiente',
    cuota_cierre_1x2 REAL, cuota_cierre_ou REAL, clv_pct_1x2 REAL, clv_pct_ou REAL,
    incertidumbre REAL, shadow_xg_local REAL, shadow_xg_visita REAL,
    apuesta_shadow_1x2 TEXT, stake_shadow_1x2 REAL, xg_local REAL, xg_visita REAL,
    xg_local_corto REAL, xg_visita_corto REAL
);
CREATE TABLE config_motor_valores (
    clave TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global', valor_real REAL,
    valor_texto TEXT, tipo TEXT NOT NULL, fuente TEXT, bloqueado INTEGER NOT NULL DEFAULT 0,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (clave, scope)
);
CREATE TABLE configuracion (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE log_alertas (id_alerta TEXT PRIMARY KEY, partido TEXT NOT NULL,
    mercado TEXT NOT NULL, pick TEXT NOT NULL, stake_enviado REAL, timestamp TEXT);
CREATE TABLE historial_equipos (
    equipo_norm TEXT, equipo_real TEXT, liga TEXT,
    ema_xg_favor_home REAL DEFAULT 1.4, ema_xg_contra_home REAL DEFAULT 1.4,
    ema_xg_favor_away REAL DEFAULT 1.4, ema_xg_contra_away REAL DEFAULT 1.4,
    ema_var_favor_home REAL DEFAULT 0.1, ema_var_contra_home REAL DEFAULT 0.1,
    ema_var_favor_away REAL DEFAULT 0.1, ema_var_contra_away REAL DEFAULT 0.1,
    ema_corto_favor_home REAL, ema_corto_contra_home REAL,
    ema_corto_favor_away REAL, ema_corto_contra_away REAL,
    partidos_home INTEGER DEFAULT 0, partidos_away INTEGER DEFAULT 0, ultima_actualizacion TEXT,
    PRIMARY KEY (equipo_norm, liga)
);
CREATE TABLE historial_equipos_stats (liga TEXT, equipo TEXT, fecha TEXT, n_acum INTEGER,
    PRIMARY KEY (liga, equipo, fecha));
CREATE TABLE ligas_stats (liga TEXT PRIMARY KEY, rho_calculado REAL DEFAULT -0.04);
CREATE TABLE equipos_altitud (equipo_norm TEXT PRIMARY KEY, equipo_real TEXT, altitud INTEGER);
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


# Algunos modulos (motor_calculadora) leen config_motor_valores al importarse:
# la DB debe tener el esquema antes de la coleccion de tests.
_c = sqlite3.connect(os.environ["ADEPOR_DB"])
_c.executescript(SCHEMA)
_c.close()

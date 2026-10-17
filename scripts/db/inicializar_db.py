"""
Crea una fondo_quant.db nueva y operable (auditoria 2026-10: la DB de produccion se perdio).

- Siembra config_motor_valores con los valores del manifiesto (scripts/db/crear_config_motor.py).
- Arranca con ema_prior_por_equipo=TRUE: las EMAs nacen en escala de goles por equipo, asi que
  factor_corr_xg_ou y gamma_1x2 parten en 1.0 (los 0.52-0.65 del seed compensaban el prior viejo).
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
from scripts.db import crear_config_motor as ccm  # noqa: E402

# Escala nueva: sin compensaciones del prior por partido.
_OVERRIDES = {'factor_corr_xg_ou': 1.0, 'gamma_1x2': 1.0}

# Esquema completo: antes las columnas se agregaban con ALTER dispersos en 5 scripts
# (motor_fixture, motor_data, motor_calculadora, motor_tactico, migrate_clv_pct) y una
# DB nueva fallaba en el primer motor que leia una columna aun no creada.
TABLAS_BASE = """
CREATE TABLE IF NOT EXISTS partidos_backtest (
    id_partido TEXT PRIMARY KEY, fecha TEXT, pais TEXT, local TEXT, visita TEXT,
    cuota_1 REAL DEFAULT 0, cuota_x REAL DEFAULT 0, cuota_2 REAL DEFAULT 0,
    cuota_o25 REAL DEFAULT 0, cuota_u25 REAL DEFAULT 0,
    prob_1 REAL DEFAULT 0, prob_x REAL DEFAULT 0, prob_2 REAL DEFAULT 0,
    prob_o25 REAL DEFAULT 0, prob_u25 REAL DEFAULT 0,
    apuesta_1x2 TEXT DEFAULT 'pendiente', apuesta_ou TEXT DEFAULT 'pendiente',
    stake_1x2 REAL DEFAULT 0, stake_ou REAL DEFAULT 0,
    goles_l INTEGER, goles_v INTEGER, estado TEXT DEFAULT 'Pendiente',
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    arbitro TEXT DEFAULT 'NO', id_arbitro TEXT DEFAULT 'NO', auditoria TEXT DEFAULT 'NO',
    formacion_l TEXT DEFAULT '', formacion_v TEXT DEFAULT '',
    clv_registrado TEXT, cuota_cierre_1x2 REAL, cuota_cierre_ou REAL,
    clv_pct_1x2 REAL, clv_pct_ou REAL,
    incertidumbre REAL, shadow_xg_local REAL, shadow_xg_visita REAL,
    apuesta_shadow_1x2 TEXT, stake_shadow_1x2 REAL,
    xg_local REAL, xg_visita REAL, xg_local_corto REAL, xg_visita_corto REAL,
    sot_l INTEGER, shots_l INTEGER, corners_l INTEGER,
    sot_v INTEGER, shots_v INTEGER, corners_v INTEGER,
    pin_1 REAL DEFAULT 0, pin_x REAL DEFAULT 0, pin_2 REAL DEFAULT 0,
    pin_o25 REAL DEFAULT 0, pin_u25 REAL DEFAULT 0,
    pin_cierre_1 REAL, pin_cierre_x REAL, pin_cierre_2 REAL,
    pin_cierre_o25 REAL, pin_cierre_u25 REAL);
CREATE INDEX IF NOT EXISTS idx_pb_estado_fecha ON partidos_backtest(estado, fecha);
CREATE TABLE IF NOT EXISTS historial_equipos (
    equipo_norm TEXT NOT NULL, equipo_real TEXT, liga TEXT NOT NULL, ultima_actualizacion TEXT,
    ema_xg_favor_home REAL DEFAULT 1.4, ema_xg_contra_home REAL DEFAULT 1.4,
    ema_xg_favor_away REAL DEFAULT 1.4, ema_xg_contra_away REAL DEFAULT 1.4,
    partidos_home INTEGER DEFAULT 0, partidos_away INTEGER DEFAULT 0,
    ema_var_favor_home REAL DEFAULT 0.1, ema_var_contra_home REAL DEFAULT 0.1,
    ema_var_favor_away REAL DEFAULT 0.1, ema_var_contra_away REAL DEFAULT 0.1,
    ema_corto_favor_home REAL DEFAULT 1.4, ema_corto_contra_home REAL DEFAULT 1.4,
    ema_corto_favor_away REAL DEFAULT 1.4, ema_corto_contra_away REAL DEFAULT 1.4,
    partidos_corto_home INTEGER DEFAULT 0, partidos_corto_away INTEGER DEFAULT 0,
    PRIMARY KEY (equipo_norm, liga));
CREATE TABLE IF NOT EXISTS ema_procesados (id_partido TEXT PRIMARY KEY);
-- Historia externa (2022-2024 en la DB perdida). Vacia en una DB nueva: posiciones y H2H
-- la leen en UNION con partidos_backtest y deben poder correr sin ella.
CREATE TABLE IF NOT EXISTS partidos_historico_externo (
    id TEXT PRIMARY KEY, liga TEXT, temp INTEGER, fecha TEXT, ht TEXT, at TEXT,
    hg INTEGER, ag INTEGER, has_full_stats INTEGER DEFAULT 0, ht_norm TEXT, at_norm TEXT);
CREATE TABLE IF NOT EXISTS arbitros_stats (
    id_arbitro TEXT PRIMARY KEY, nombre TEXT, partidos INTEGER DEFAULT 0,
    ema_faltas REAL DEFAULT 0, ema_amarillas REAL DEFAULT 0,
    ema_rojas REAL DEFAULT 0, ema_penales REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS ligas_stats (
    liga TEXT PRIMARY KEY, total_partidos INTEGER DEFAULT 0, empates INTEGER DEFAULT 0,
    rho_calculado REAL DEFAULT -0.09, total_goles INTEGER DEFAULT 0,
    total_corners INTEGER DEFAULT 0, coef_corner_calculado REAL DEFAULT 0.02);
CREATE TABLE IF NOT EXISTS equipos_altitud (equipo_norm TEXT PRIMARY KEY, equipo_real TEXT, altitud INTEGER);
CREATE TABLE IF NOT EXISTS apuestas_confirmadas (
    id_partido TEXT NOT NULL, mercado TEXT NOT NULL, pick TEXT NOT NULL,
    cuota_tomada REAL NOT NULL, stake REAL NOT NULL, ts TEXT DEFAULT CURRENT_TIMESTAMP,
    casa TEXT,
    PRIMARY KEY (id_partido, mercado));
"""


def filas_seed():
    filas = []
    for clave, scope, vr, vt, tipo, fuente, bloq in ccm.seed_rows():
        if clave in _OVERRIDES:
            vr, fuente = _OVERRIDES[clave], 'inicializar_db 2026-10 (prior por equipo)'
        filas.append((clave, scope, vr, vt, tipo, fuente, bloq))
    filas.append(('gamma_1x2', 'global', 1.0, None, 'float', 'inicializar_db 2026-10', 1))
    # Sin historial no hay evidencia: O/U arranca en pretest (stake 0) como el 1X2.
    filas = [f for f in filas if f[0] != 'apuesta_ou_live']
    filas.append(('apuesta_ou_live', 'global', None, 'FALSE', 'bool', 'inicializar_db 2026-10', 0))
    filas.append(('ema_prior_por_equipo', 'global', None, 'TRUE', 'bool', 'inicializar_db 2026-10', 1))
    return filas


def inicializar(db_path):
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        raise FileExistsError(f'La DB ya existe, no se toca: {db_path}')
    con = sqlite3.connect(db_path)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute(ccm.SQL_CREATE_TABLE)
        con.execute(ccm.SQL_CREATE_INDEX)
        con.execute(ccm.SQL_CREATE_TRIGGER)
        con.executemany("""INSERT OR IGNORE INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", filas_seed())
        con.executescript(TABLAS_BASE)
        con.commit()
    finally:
        con.close()


if __name__ == '__main__':
    destino = sys.argv[1] if len(sys.argv) > 1 else DB_NAME
    inicializar(destino)
    print(f'DB nueva lista en {destino}')

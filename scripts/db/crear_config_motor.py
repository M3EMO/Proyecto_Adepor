"""
crear_config_motor.py - STEP 1 fase3 adepor (flujo-datos)

Crea la tabla config_motor_valores + indice + trigger de bloqueo, y siembra
los valores vigentes del manifiesto Reglas_IA.txt / motores de produccion.

Idempotente: re-ejecutable sin romper estado (INSERT OR IGNORE + CREATE IF NOT EXISTS).

Uso:
    py scripts/db/crear_config_motor.py

Snapshot previo obligatorio:
    py adepor_guard.py snapshot

Referencias de los valores seed:
    - src/ingesta/motor_data.py:16-36,274-276 (ALFA_EMA, N0_ANCLA, PROFUNDIDAD_*)
    - src/nucleo/motor_calculadora.py (FLOOR_PROB_MIN, KELLY, RHO, DIVERGENCIA, etc.)
    - src/nucleo/calibrar_rho.py:31-33 (RHO_FALLBACK, RHO_FLOOR)
    - Reglas_IA.txt II.B, II.E, IV.A, IV.D, IV.E, IV.G, IV.H, IV.J
"""
import os
import sys
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from src.comun.config_sistema import DB_NAME

DB_PATH = os.path.join(PROJECT_ROOT, DB_NAME)


SQL_CREATE_TABLE = """
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
"""

SQL_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_config_clave ON config_motor_valores(clave);
"""

SQL_CREATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_config_bloqueado_no_update
BEFORE UPDATE ON config_motor_valores
FOR EACH ROW WHEN OLD.bloqueado = 1
BEGIN
    SELECT RAISE(ABORT, 'config_motor_valores: fila bloqueada, modificar bloqueado=0 primero');
END;
"""


def _f(clave, scope, valor, fuente, bloqueado=1):
    return (clave, scope, float(valor), None, 'float', fuente, bloqueado)


def _i(clave, scope, valor, fuente, bloqueado=1):
    return (clave, scope, float(valor), None, 'int', fuente, bloqueado)


def _b(clave, scope, valor_bool, fuente, bloqueado=1):
    vt = 'TRUE' if valor_bool else 'FALSE'
    return (clave, scope, None, vt, 'bool', fuente, bloqueado)


def seed_rows():
    """Devuelve lista de 7-tuplas (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)."""
    rows = []

    # ------------------------------------------------------------------
    # (a) GLOBALES float / int - valores vigentes del manifiesto
    # ------------------------------------------------------------------
    # Filtros globales (Reglas_IA IV.A, motor_calculadora.py)
    rows.append(_f('floor_prob_min',              'global', 0.33,  'manifiesto_IV.A'))
    rows.append(_f('floor_prob_min_camino3',      'global', 0.33,  'manifiesto_IV.C'))
    rows.append(_f('margen_predictivo_1x2',       'global', 0.03,  'manifiesto_IV.A'))
    rows.append(_f('margen_predictivo_ou',        'global', 0.05,  'manifiesto_IV.D2'))

    # Kelly / gestion de riesgo (Reglas_IA IV.E)
    rows.append(_f('fraccion_kelly',              'global', 0.50,  'manifiesto_IV.E'))
    rows.append(_f('max_kelly_pct_normal',        'global', 0.025, 'manifiesto_IV.E'))
    rows.append(_f('max_kelly_pct_drawdown',      'global', 0.010, 'manifiesto_IV.E'))
    rows.append(_i('drawdown_threshold',          'global', 5,     'manifiesto_IV.E'))

    # Techos de cuota (Reglas_IA IV.C, IV.D2)
    rows.append(_f('techo_cuota_1x2',             'global', 5.0,   'manifiesto_IV.C'))
    rows.append(_f('techo_cuota_ou',              'global', 6.0,   'manifiesto_IV.D2'))
    rows.append(_f('techo_cuota_alta_conv',       'global', 8.0,   'manifiesto_IV.C'))

    # Divergencias
    rows.append(_f('divergencia_desacuerdo_max',  'global', 0.30,  'manifiesto_IV.C'))
    # (divergencia_max_ou fue eliminada V4.9, no se siembra)

    # O/U Fix B (Reglas_IA IV.D2)
    rows.append(_f('margen_xg_ou_over',           'global', 0.30,  'manifiesto_IV.D2'))
    rows.append(_f('margen_xg_ou_under',          'global', 0.25,  'manifiesto_IV.D2'))

    # Rho Dixon-Coles (Reglas_IA II.C, calibrar_rho.py)
    rows.append(_f('rho_fallback',                'global', -0.09, 'manifiesto_II.C'))
    rows.append(_f('rho_floor',                   'global', -0.03, 'manifiesto_II.C'))

    # Hallazgo G (Reglas_IA IV.H)
    rows.append(_i('n_min_hallazgo_g',            'global', 50,    'manifiesto_IV.H'))
    rows.append(_f('boost_g_fraccion',            'global', 0.50,  'manifiesto_IV.H'))

    # Fix #5 calibracion (Reglas_IA II.C, motor_calculadora.py CALIBRACION_CORRECCION)
    rows.append(_f('calibracion_delta',           'global', 0.042, 'manifiesto_II.C'))

    # Hallazgo C delta-stake (Reglas_IA IV.G)
    rows.append(_f('delta_stake_mult_alto',       'global', 1.30,  'manifiesto_IV.G'))
    rows.append(_f('delta_stake_mult_med',        'global', 1.15,  'manifiesto_IV.G'))

    # Ancla bayesiana (Reglas_IA II.B)
    rows.append(_i('n0_ancla',                    'global', 5,     'manifiesto_II.B'))

    # Camino 3 EV minimo (motor_calculadora.py CONVICCION_EV_MIN)
    rows.append(_f('conviccion_ev_min',           'global', 1.0,   'manifiesto_IV.C'))

    # Profundidades de scrape (Reglas_IA IV.J, motor_data.py:274-276)
    # NOTA: codigo vigente usa 365 como valor inicial (no 210 como indica el manifiesto IV.J).
    # Seed bit-a-bit del .py vigente. PLAN.md §4 D4 autoriza override por liga (0-365).
    rows.append(_i('profundidad_inicial',         'global', 365,   'motor_data.py:274'))
    rows.append(_i('profundidad_profunda',        'global', 140,   'motor_data.py:275'))
    rows.append(_i('profundidad_mantenimiento',   'global', 7,     'motor_data.py:276'))

    # ALFA EMA fallback global (Reglas_IA II.B, motor_data.py:16)
    rows.append(_f('alfa_ema',                    'global', 0.15,  'manifiesto_II.B'))

    # ------------------------------------------------------------------
    # (a') GLOBALES bool
    # ------------------------------------------------------------------
    rows.append(_b('calibracion_activa',          'global', True,  'manifiesto_II.C'))
    rows.append(_b('hallazgo_g_activo',           'global', True,  'manifiesto_IV.H'))
    rows.append(_b('delta_stake_activo',          'global', True,  'manifiesto_IV.G'))
    rows.append(_b('corr_visita_activa',          'global', False, 'manifiesto_II.C'))  # Fix A revertido
    rows.append(_b('apuesta_empate_permitida',    'global', False, 'manifiesto_IV.A'))
    rows.append(_b('apuesta_ou_live',             'global', True,  'manifiesto_IV.D2'))  # STEP4/F3C -> FALSE

    # ------------------------------------------------------------------
    # (b) POR LIGA - bloqueados=1
    # ------------------------------------------------------------------
    # ALFA EMA por liga (Reglas_IA II.B, motor_data.py:29-36)
    rows.append(_f('alfa_ema', 'Brasil',     0.20, 'manifiesto_II.B'))
    rows.append(_f('alfa_ema', 'Turquia',    0.20, 'manifiesto_II.B'))
    rows.append(_f('alfa_ema', 'Noruega',    0.18, 'manifiesto_II.B'))
    rows.append(_f('alfa_ema', 'Argentina',  0.15, 'manifiesto_II.B'))
    rows.append(_f('alfa_ema', 'Inglaterra', 0.12, 'manifiesto_II.B'))

    # DIVERGENCIA_MAX_1X2 por liga (Reglas_IA IV.D, motor_calculadora.py DIVERGENCIA_MAX_POR_LIGA)
    rows.append(_f('divergencia_max_1x2', 'Inglaterra', 0.10, 'manifiesto_IV.D'))
    rows.append(_f('divergencia_max_1x2', 'Argentina',  0.15, 'manifiesto_IV.D'))
    rows.append(_f('divergencia_max_1x2', 'Brasil',     0.18, 'manifiesto_IV.D'))
    rows.append(_f('divergencia_max_1x2', 'Noruega',    0.20, 'manifiesto_IV.D'))
    rows.append(_f('divergencia_max_1x2', 'Turquia',    0.20, 'manifiesto_IV.D'))
    # divergencia_max_1x2 global fallback
    rows.append(_f('divergencia_max_1x2', 'global',     0.15, 'manifiesto_IV.D'))

    # FACTOR_CORR_XG_OU por liga (Reglas_IA II.E, motor_calculadora.py)
    # Senior pidio seed solo las 4 con valor distinto del fallback global.
    # Inglaterra / sudamericanas caen al fallback 0.627 via scope='global'.
    rows.append(_f('factor_corr_xg_ou', 'Noruega',   0.524, 'manifiesto_II.E'))
    rows.append(_f('factor_corr_xg_ou', 'Brasil',    0.603, 'manifiesto_II.E'))
    rows.append(_f('factor_corr_xg_ou', 'Argentina', 0.642, 'manifiesto_II.E'))
    rows.append(_f('factor_corr_xg_ou', 'Turquia',   0.648, 'manifiesto_II.E'))
    rows.append(_f('factor_corr_xg_ou', 'global',    0.627, 'manifiesto_II.E'))

    # PROFUNDIDAD_INICIAL por liga (PLAN.md §4 D4 "0-365 por liga")
    # Las 12 ligas de LIGAS_ESPN, default=365 (vigente motor_data.py), Noruega override 365 (igual).
    ligas_12 = ['Argentina', 'Inglaterra', 'Brasil', 'Noruega', 'Turquia',
                'Bolivia', 'Chile', 'Uruguay', 'Peru', 'Ecuador', 'Colombia', 'Venezuela']
    for liga in ligas_12:
        rows.append(_i('profundidad_inicial', liga, 365, 'motor_data.py:274+PLAN.md_D4'))

    return rows


def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB no existe: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(SQL_CREATE_TABLE)
        cur.execute(SQL_CREATE_INDEX)
        cur.execute(SQL_CREATE_TRIGGER)

        rows = seed_rows()
        cur.executemany("""
            INSERT OR IGNORE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        insertadas = cur.rowcount
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM config_motor_valores")
        total = cur.fetchone()[0]

        print(f"[OK] config_motor_valores creada / actualizada.")
        print(f"     Seed intentado   : {len(rows)} filas")
        print(f"     Insertadas nuevas: {insertadas}")
        print(f"     Total en tabla   : {total}")

        print("\nSample (5 claves criticas):")
        for clave, scope in [('floor_prob_min', 'global'),
                             ('alfa_ema', 'Brasil'),
                             ('factor_corr_xg_ou', 'Argentina'),
                             ('hallazgo_g_activo', 'global'),
                             ('profundidad_inicial', 'Noruega')]:
            cur.execute("""
                SELECT valor_real, valor_texto, tipo, fuente, bloqueado
                  FROM config_motor_valores WHERE clave=? AND scope=?
            """, (clave, scope))
            r = cur.fetchone()
            print(f"  {clave:35s} scope={scope:12s} -> {r}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()

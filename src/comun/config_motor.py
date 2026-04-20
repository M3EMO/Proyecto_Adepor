"""
config_motor - lector de la tabla config_motor_valores.

STEP 1 fase3 adepor (flujo-datos). Sin matematica, sin efectos. Un unico entry
point para leer parametros del manifiesto persistidos en SQLite.

Uso:
    from src.comun.config_motor import get_param
    floor = get_param('floor_prob_min')                    # 0.33
    alfa  = get_param('alfa_ema', scope='Brasil')          # 0.20
    alfa  = get_param('alfa_ema', scope='Bolivia')         # 0.15 (fallback global)
    flag  = get_param('hallazgo_g_activo')                 # True  (bool)
    fcorr = get_param('factor_corr_xg_ou', 'Inglaterra')   # 0.627 (fallback global)
"""
import os
import sqlite3

from .config_sistema import DB_NAME

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_PATH = os.path.join(_PROJECT_ROOT, DB_NAME)


def _coerce(valor_real, valor_texto, tipo):
    if tipo == 'bool':
        return valor_texto == 'TRUE'
    if tipo == 'text':
        return valor_texto
    if tipo == 'int':
        return int(valor_real)
    return valor_real


def get_param(clave, scope='global', default=None):
    """
    Devuelve el valor de `clave` en `scope` desde config_motor_valores.

    Orden de resolucion:
        1. (clave, scope) exacto.
        2. Si scope != 'global' y (1) no encontro: (clave, 'global').
        3. default.

    El tipo del valor retornado sigue la columna `tipo` de la tabla:
        'float' -> float, 'int' -> int, 'bool' -> bool, 'text' -> str.
    """
    conn = sqlite3.connect(_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT valor_real, valor_texto, tipo
              FROM config_motor_valores
             WHERE clave = ? AND scope = ?
        """, (clave, scope))
        row = cur.fetchone()
        if row is None and scope != 'global':
            cur.execute("""
                SELECT valor_real, valor_texto, tipo
                  FROM config_motor_valores
                 WHERE clave = ? AND scope = 'global'
            """, (clave,))
            row = cur.fetchone()
        if row is None:
            return default
        return _coerce(*row)
    finally:
        conn.close()

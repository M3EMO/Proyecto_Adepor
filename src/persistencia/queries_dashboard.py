"""Queries de lectura para el dashboard operativo Adepor.

Refactor 2026-04-17 — solo lectura. Para escritura usar adepor_guard.py.
"""
from src.comun import config_sistema
import sqlite3

def get_partidos_proximos(limit: int = 50):
    """Devuelve filas de Partidos con estado != 'Liquidado'."""
    con = sqlite3.connect(config_sistema.DB_NAME)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM Partidos WHERE estado != 'Liquidado' ORDER BY fecha_evento ASC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
    finally:
        con.close()

def get_liquidados_recientes(n_dias: int = 30):
    """Devuelve filas Liquidadas dentro de los últimos n_dias."""
    con = sqlite3.connect(config_sistema.DB_NAME)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM Partidos WHERE estado = 'Liquidado' "
            "AND fecha_evento >= date('now', ?) ORDER BY fecha_evento DESC",
            (f"-{int(n_dias)} days",),
        )
        return cur.fetchall()
    finally:
        con.close()

# === STUBS ===
def get_xg_desglose(*args, **kwargs):
    """STUB — implementación futura. Ver MIGRACION_SCHEMA_PENDIENTE.md."""
    raise NotImplementedError("get_xg_desglose pendiente — fase futura")

def get_kelly_breakdown(*args, **kwargs):
    """STUB — implementación futura."""
    raise NotImplementedError("get_kelly_breakdown pendiente")

def get_clv_por_partido(*args, **kwargs):
    """STUB — implementación futura."""
    raise NotImplementedError("get_clv_por_partido pendiente")

def get_drawdown_actual(*args, **kwargs):
    """STUB — implementación futura."""
    raise NotImplementedError("get_drawdown_actual pendiente")

def get_friccion_arbitral(*args, **kwargs):
    """STUB — implementación futura."""
    raise NotImplementedError("get_friccion_arbitral pendiente")

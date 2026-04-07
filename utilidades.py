# ==========================================
# UTILIDADES — Funciones compartidas del sistema (V1.0)
# Reune helpers que estaban copiados en 5+ archivos.
# Importar desde aqui en lugar de redefinir localmente.
# ==========================================

import sqlite3
import unicodedata
import re
from contextlib import contextmanager
from datetime import datetime


# ==========================================================================
# CONVERSIONES SEGURAS
# ==========================================================================

def safe_float(val, default=0.0):
    """
    Conversion segura a float con fallback.
    Reemplaza las copias en motor_data, motor_calculadora, analisis_filtros, etc.
    """
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """
    Conversion segura a int con fallback.
    Reemplaza las copias en motor_data y motor_backtest.
    """
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ==========================================================================
# NORMALIZACION DE TEXTO
# ==========================================================================

def normalizar_texto(texto):
    """
    Normaliza texto para comparaciones: minusculas, sin tildes, solo alfanumerico.
    Identica a gestor_nombres.limpiar_texto() y motor_calculadora.normalizar_extremo().
    Version centralizada — usar esta en lugar de redefinir localmente.

    Ejemplo:
        normalizar_texto("Atlético-MG") -> "atleticomg"
        normalizar_texto("Vélez Sársfield") -> "velezsarsfield"
    """
    if not texto:
        return ""
    sin_tildes = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto).lower().strip())
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'[^a-z0-9]', '', sin_tildes)


# ==========================================================================
# CONEXION A BASE DE DATOS
# ==========================================================================

@contextmanager
def conectar_db(db_path=None):
    """
    Context manager para conexiones SQLite.
    Garantiza cierre de la conexion incluso si ocurre una excepcion.

    Uso correcto:
        with conectar_db() as conn:
            cursor = conn.cursor()
            cursor.execute(...)
            conn.commit()
        # conn.close() se llama automaticamente al salir del bloque

    El patron conn = sqlite3.connect() + conn.close() sin try/finally
    deja conexiones abiertas si hay una excepcion entre medias.
    """
    from config_sistema import DB_NAME as _DB
    conn = sqlite3.connect(db_path or _DB)
    try:
        yield conn
    finally:
        conn.close()


# ==========================================================================
# PARSEO DE FECHAS
# ==========================================================================

def fecha_desde_str(fecha_str):
    """
    Parsea una fecha desde cualquier formato usado en el sistema.
    Prueba en orden: ISO con hora, ISO sin hora, DD/MM con hora, DD/MM sin hora.
    Devuelve datetime o None si no puede parsear.

    Centraliza la logica de parseo repetida en motor_sincronizador y motor_fixture.
    """
    if not fecha_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(fecha_str).strip(), fmt)
        except ValueError:
            continue
    return None


# ==========================================================================
# RESULTADO DE APUESTAS
# ==========================================================================

def determinar_resultado_apuesta(apuesta, gl, gv):
    """
    Determina si una apuesta fue GANADA, PERDIDA o INDETERMINADA.
    Centraliza la logica duplicada en motor_calculadora y motor_liquidador.

    Args:
        apuesta: string del tipo "[APOSTAR] LOCAL" o "[APOSTAR] OVER 2.5"
        gl: goles del local (int)
        gv: goles del visitante (int)
    """
    if gl is None or gv is None:
        return "INDETERMINADO"
    if not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"
    if "LOCAL"     in apuesta: return "GANADA" if gl > gv        else "PERDIDA"
    if "EMPATE"    in apuesta: return "GANADA" if gl == gv        else "PERDIDA"
    if "VISITA"    in apuesta: return "GANADA" if gl < gv         else "PERDIDA"
    if "OVER 2.5"  in apuesta: return "GANADA" if (gl+gv) > 2.5  else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl+gv) < 2.5  else "PERDIDA"
    return "INDETERMINADO"

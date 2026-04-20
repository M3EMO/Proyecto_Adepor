"""
Helpers de conversión de fechas al formato ESPN.

Unifica los `.strftime('%Y%m%d')` dispersos en motor_data, motor_fixture
y motor_arbitro. No cambia los loops multi-formato de parseo defensivo
(motor_fixture usa su propio try/except con formatos de odds-api).
"""

from datetime import datetime


def fecha_a_espn(dt):
    """Serializa un datetime al formato ESPN scoreboard 'YYYYMMDD'."""
    return dt.strftime('%Y%m%d')


def parse_fecha_espn(raw):
    """Parsea un string 'YYYYMMDD' ESPN a datetime."""
    return datetime.strptime(raw, '%Y%m%d')


def ddmmyyyy_a_espn(raw):
    """Convierte 'DD/MM/YYYY' (fecha corta de DB) a 'YYYYMMDD' ESPN."""
    return datetime.strptime(raw, '%d/%m/%Y').strftime('%Y%m%d')

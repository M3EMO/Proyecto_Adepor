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


def fecha_db_a_espn(raw):
    """Convierte fecha corta de DB ('YYYY-MM-DD' o 'DD/MM/YYYY') a 'YYYYMMDD' ESPN."""
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y%m%d')
        except ValueError:
            continue
    raise ValueError(f"Fecha no reconocida: {raw}")


def ahora_art():
    """Hora actual en UTC-3, naive: la misma escala que partidos_backtest.fecha.

    motor_fixture guarda kickoff = UTC - 3h. Comparar contra datetime.now() solo era
    correcto si la maquina corria en UTC-3.
    """
    from datetime import timezone, timedelta
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)

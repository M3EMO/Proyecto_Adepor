"""
Helpers de casteo tolerantes a valores inválidos.

Origen: deduplicados de motor_data, motor_backtest y motor_calculadora.
Comportamiento preservado bit-a-bit con la versión mayoritaria (motor_data):
cualquier excepción de casteo devuelve 0 / 0.0.
"""


def safe_int(val):
    try: return int(val)
    except: return 0


def safe_float(val):
    try: return float(val)
    except: return 0.0

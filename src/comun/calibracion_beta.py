"""
CALIBRACION BETA — aplica mapeo lineal p' = a*p + b a probs 1X2.

Los coeficientes se calibran mensualmente via scripts/calibrar_beta.py y se
guardan en config_motor_valores (scope='global'). Esta funcion SOLO se usa
en display/auditoria del Excel (BS calibrado, columnas cal). El motor de
picks sigue usando probs crudas — el yield no se ve afectado.

Fundamento empirico: probs crudas tienden a comprimir el empate y estirar
favorito/underdog. Los coefs tipicos son a1 > 1, a2 > 1, ax < 1.
"""
from src.comun.config_motor import get_param


def _get_float(clave, default):
    v = get_param(clave, scope='global', default=None)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def obtener_coefs_beta():
    """Devuelve (a1, b1, ax, bx, a2, b2) desde config_motor_valores.
    Si no existen, devuelve identidad (1,0,1,0,1,0) -> sin efecto."""
    return (
        _get_float('beta_scale_a_p1', 1.0),
        _get_float('beta_scale_b_p1', 0.0),
        _get_float('beta_scale_a_px', 1.0),
        _get_float('beta_scale_b_px', 0.0),
        _get_float('beta_scale_a_p2', 1.0),
        _get_float('beta_scale_b_p2', 0.0),
    )


def calibrar_probs(p1, px, p2, coefs=None):
    """Aplica p' = a*p + b por salida, clampea a [0,1] y renormaliza a suma 1.
    Si coefs=None, los lee de config cada llamada (para scripts one-shot).
    Para performance en loops, pasar coefs explicito."""
    if coefs is None:
        coefs = obtener_coefs_beta()
    a1, b1, ax, bx, a2, b2 = coefs

    q1 = max(0.0, min(1.0, a1 * p1 + b1))
    qx = max(0.0, min(1.0, ax * px + bx))
    q2 = max(0.0, min(1.0, a2 * p2 + b2))
    s = q1 + qx + q2
    if s > 0:
        return q1 / s, qx / s, q2 / s
    return p1, px, p2  # fallback si todo clampeo a 0

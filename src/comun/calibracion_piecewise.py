"""
CALIBRACION PIECEWISE — aplica mapeo por buckets 5pp de probs 1X2.

Los mapas se calibran via scripts/calibrar_piecewise.py y se guardan como
JSON en config_motor_valores.clave='piecewise_calibration_map', scope='global'.

Esta funcion SOLO se usa en display/auditoria del Excel — el motor de picks
sigue usando probs crudas.

Fallback: si un bucket no tiene mapeo (N<5 samples), se aplica beta-scaling;
si tampoco hay beta, se devuelve la prob cruda.
"""
import json

from src.comun.config_motor import get_param
from src.comun.calibracion_beta import calibrar_probs as _cal_beta, obtener_coefs_beta


def obtener_mapas_piecewise():
    """Devuelve dict con p1/px/p2 maps o None si no hay mapas en DB."""
    raw = get_param('piecewise_calibration_map', scope='global', default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _apply_bucket(p, bucket_map):
    """Busca el bucket que contiene p y devuelve la freq empirica.
    Si no hay bucket matching, devuelve None."""
    for k, v in bucket_map.items():
        lo_s, hi_s = k.split('-')
        if float(lo_s) <= p < float(hi_s):
            return v
    return None


def calibrar_probs_pw(p1, px, p2, mapas=None, coefs_beta=None):
    """Aplica piecewise calibration, fallback beta-scaling, fallback crudo.

    Args:
        p1, px, p2: probs crudas del modelo
        mapas: dict con 'p1','px','p2' bucket maps. Si None, los lee de DB.
        coefs_beta: 6-tuple (a1,b1,ax,bx,a2,b2) para fallback. Si None, los lee.

    Returns:
        (p1_cal, px_cal, p2_cal) renormalizadas a suma 1.
    """
    if mapas is None:
        mapas = obtener_mapas_piecewise()

    # Sin mapas piecewise -> usar beta directo
    if not mapas:
        return _cal_beta(p1, px, p2, coefs=coefs_beta)

    if coefs_beta is None:
        coefs_beta = obtener_coefs_beta()
    a1, b1, ax, bx, a2, b2 = coefs_beta

    def _cal_una(p, bucket_map, a, b):
        v = _apply_bucket(p, bucket_map) if bucket_map else None
        if v is not None:
            return v
        # Fallback beta por esa salida
        return max(0.0, min(1.0, a * p + b))

    q1 = _cal_una(p1, mapas.get('p1', {}), a1, b1)
    qx = _cal_una(px, mapas.get('px', {}), ax, bx)
    q2 = _cal_una(p2, mapas.get('p2', {}), a2, b2)

    s = q1 + qx + q2
    if s > 0:
        return q1 / s, qx / s, q2 / s
    return p1, px, p2

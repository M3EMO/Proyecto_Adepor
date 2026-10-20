"""Metricas de dinero real: P/L, yield, acierto y t-test sobre apuestas liquidadas con stake > 0."""
import math

from src.comun.picks import cuota_para_pick
from src.comun.resolucion import determinar_resultado_entero


def _beta_incompleta(a, b, x):
    """Beta incompleta regularizada I_x(a, b) por fraccion continua (Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):  # convergencia: usar la simetria
        return 1.0 - _beta_incompleta(b, a, 1.0 - x)
    ln_pre = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
              + a * math.log(x) + b * math.log(1 - x))
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    f = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + num / c
            c = c if abs(c) > tiny else tiny
            f *= c * d
        if abs(c * d - 1.0) < 1e-12:
            break
    return math.exp(ln_pre) * f / a


def p_valor_t(t, df):
    """p-valor bilateral de un estadistico t con df grados de libertad."""
    if df <= 0:
        return 1.0
    return _beta_incompleta(df / 2.0, 0.5, df / (df + t * t))

def _pl_apuesta(res, stk, cuota):
    """P/L de una apuesta liquidada. None si gana sin cuota valida (no se puede valorar)."""
    if res == 1:
        return stk * (cuota - 1) if cuota > 0 else None
    return -stk


def _grupo(bets):
    """Agrega una lista de apuestas en KPIs (n, pl, vol, yield, hit, t, p)."""
    n = len(bets)
    if n == 0:
        return {'n': 0, 'pl': 0.0, 'vol': 0.0, 'yield': 0.0,
                'acierto_bets': 0.0, 't': 0.0, 'p': 1.0}
    pl = sum(b['pl'] for b in bets)
    vol = sum(b['stk'] for b in bets)
    ganadas = sum(1 for b in bets if b['res'] == 1)
    yld = pl / vol if vol > 0 else 0.0
    acierto_bets = ganadas / n
    if n >= 2:
        ys = [b['pl'] / b['stk'] for b in bets]
        mean_y = sum(ys) / n
        var = sum((y - mean_y) ** 2 for y in ys) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        t = (mean_y / (std / math.sqrt(n))) if std > 0 else 0.0
        p_v = p_valor_t(t, n - 1)  # Student-t: la normal subestimaba p con N chico
    else:
        t, p_v = 0.0, 1.0
    return {
        'n': n, 'pl': pl, 'vol': vol, 'yield': yld,
        'acierto_bets': acierto_bets,
        't': round(t, 4), 'p': round(p_v, 4),
    }


def metricas_dinero(datos):
    """KPIs total / 1x2 / ou de las apuestas liquidadas con stake > 0.

    datos: filas con el orden de dashboard.cargar_partidos (indices 5-16).
    Una apuesta ganada sin cuota valida no se puede valorar: queda fuera de P/L y volumen.
    """
    bets = {'1x2': [], 'ou': []}
    for r in datos:
        estado, gl, gv = r[14], r[15], r[16]
        if estado != 'Liquidado' or gl is None or gv is None:
            continue
        for mercado, ap, stk in (('1x2', r[5], r[7]), ('ou', r[6], r[8])):
            if not ap or not stk or stk <= 0:
                continue
            res = determinar_resultado_entero(ap, gl, gv)
            if res == 0:
                continue
            pl = _pl_apuesta(res, stk, cuota_para_pick(ap, *r[9:14]))
            if pl is not None:
                bets[mercado].append({'res': res, 'stk': stk, 'pl': pl})
    return {'total': _grupo(bets['1x2'] + bets['ou']), '1x2': _grupo(bets['1x2']), 'ou': _grupo(bets['ou'])}

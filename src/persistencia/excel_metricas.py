"""
Calculo de metricas para el Dashboard (Python, no formulas Excel).

- calcular_metricas_dashboard: agrega los 223+ partidos y devuelve un dict
  con P/L, yield, hit, Brier, T-score, p-value por grupo (total/1x2/OU).
- semaforo: dado un valor, devuelve el fill (verde/amarillo/rojo/neutro)
  segun umbrales.

Extraido del motor_sincronizador.py monolitico (V9.2) en fase 4 (2026-04-21).
"""
import math

from src.comun.resolucion import determinar_resultado_entero
from src.comun.calibracion_beta import obtener_coefs_beta
from src.comun.calibracion_piecewise import obtener_mapas_piecewise, calibrar_probs_pw
from src.persistencia.excel_estilos import (
    FILL_VERDE, FILL_AMARILLO, FILL_ROJO, FILL_NEUTRO,
)
from src.persistencia.excel_formulas import cuota_1x2, cuota_ou



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


def calcular_metricas_dashboard(datos, fraccion_kelly):
    """
    Recorre los rows del SELECT de partidos_backtest y devuelve un dict con:
      - total / 1x2 / ou: _grupo() de cada scope
      - acierto_partidos, pred_aciertos, pred_total: precision del modelo
        sobre la columna Acierto (margen >5pp, filtrando PASAR).
      - bs_sis, bs_casa, bs_glob: Brier medio sistema, casa y su diferencia.
      - fraccion_kelly: echo del parametro.
    """
    bets_1x2, bets_ou = [], []
    bs_sis_list, bs_casa_list, bs_cal_list = [], [], []
    dif_glob, dif_glob_cal = [], []  # sistema - casa, PAREADO sobre partidos con cuotas
    pred_aciertos = 0
    pred_fallos = 0

    # Calibradores display-only (piecewise + fallback beta)
    _coefs_beta = obtener_coefs_beta()
    _mapas_pw = obtener_mapas_piecewise()
    # por_liga: stats de picks liquidados (incluyendo pretest con stake=0).
    # n/g/p se cuentan desde el texto [GANADA]/[PERDIDA] del pick 1X2.
    # vol/pl solo incluyen apuestas con stake>0 (dinero real movido).
    por_liga = {}
    # Ganadas sin cuota: excluidas de P/L y volumen (no se valoran).
    ganadas_sin_cuota = 0

    for row in datos:
        (id_p, fecha, local, visita, pais,
         p1, px, p2, po, pu,
         ap1x2, apou, stk1x2, stkou,
         c1, cx, c2, co, cu,
         estado, gl, gv, incert, auditoria,
         _ap_shadow, _stk_shadow, *_extra) = row

        if gl is None or gv is None:
            continue

        # --- % Acierto P: replica logica de f_acierto ---
        if p1 and px and p2:
            mx = max(p1, px, p2)
            md = sorted([p1, px, p2])[1]
            if (mx - md) > 0.05:
                if p1 == mx:   pred = 'LOCAL'
                elif px == mx: pred = 'EMPATE'
                else:          pred = 'VISITA'
                real = 'LOCAL' if gl > gv else ('EMPATE' if gl == gv else 'VISITA')
                if pred == real:
                    pred_aciertos += 1
                else:
                    pred_fallos += 1

        # --- por_liga: TODAS las apuestas [GANADA]/[PERDIDA] (pretest + live), 1X2 y O/U ---
        # (antes solo 1X2: una liga con O/U live y 1X2 en pretest mostraba n=0 y yield 0)
        for ap, stk, cuota in ((ap1x2, stk1x2, cuota_1x2(ap1x2, c1, cx, c2) if ap1x2 else 0),
                               (apou, stkou, cuota_ou(apou, co, cu) if apou else 0)):
            if not (pais and ap and ('[GANADA]' in ap or '[PERDIDA]' in ap)):
                continue
            s_l = por_liga.setdefault(pais, {'n': 0, 'g': 0, 'p': 0, 'vol': 0.0, 'pl': 0.0})
            s_l['n'] += 1
            s_l['g' if '[GANADA]' in ap else 'p'] += 1
            # vol/pl solo si hubo dinero real liquidado
            if stk and stk > 0 and estado == 'Liquidado':
                res = determinar_resultado_entero(ap, gl, gv)
                if res != 0:
                    pl_r = _pl_apuesta(res, stk, cuota or 0)
                    if pl_r is None:
                        ganadas_sin_cuota += 1
                    else:
                        s_l['vol'] += stk
                        s_l['pl'] += pl_r

        # --- Apuestas liquidadas con stake real (para metricas financieras total/1x2/ou) ---
        if stk1x2 and stk1x2 > 0 and ap1x2 and estado == 'Liquidado':
            res = determinar_resultado_entero(ap1x2, gl, gv)
            if res != 0:
                pl_r = _pl_apuesta(res, stk1x2, cuota_1x2(ap1x2, c1, cx, c2) or 0)
                if pl_r is None:
                    ganadas_sin_cuota += 1
                else:
                    bets_1x2.append({'res': res, 'stk': stk1x2, 'pl': pl_r})

        if stkou and stkou > 0 and apou and estado == 'Liquidado':
            res = determinar_resultado_entero(apou, gl, gv)
            if res != 0:
                pl_r = _pl_apuesta(res, stkou, cuota_ou(apou, co, cu) or 0)
                if pl_r is None:
                    ganadas_sin_cuota += 1
                else:
                    bets_ou.append({'res': res, 'stk': stkou, 'pl': pl_r})

        # --- Brier Score por partido ---
        if p1 and px and p2:
            o1 = 1 if gl > gv else 0
            ox = 1 if gl == gv else 0
            o2 = 1 if gl < gv else 0
            bs_sis_list.append((p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2)
            # Brier calibrado (piecewise + fallback beta, display-only)
            q1, qx, q2 = calibrar_probs_pw(p1, px, p2, mapas=_mapas_pw, coefs_beta=_coefs_beta)
            bs_cal_list.append((q1 - o1) ** 2 + (qx - ox) ** 2 + (q2 - o2) ** 2)
            if c1 and c1 > 0 and cx and cx > 0 and c2 and c2 > 0:
                r1, rx, r2 = 1 / c1, 1 / cx, 1 / c2
                tot = r1 + rx + r2
                p1m, pxm, p2m = r1 / tot, rx / tot, r2 / tot
                bs_casa_list.append((p1m - o1) ** 2 + (pxm - ox) ** 2 + (p2m - o2) ** 2)
                dif_glob.append(bs_sis_list[-1] - bs_casa_list[-1])
                dif_glob_cal.append(bs_cal_list[-1] - bs_casa_list[-1])

    if ganadas_sin_cuota:
        print(f"[WARN] {ganadas_sin_cuota} apuestas ganadas sin cuota: excluidas de P/L y volumen.")

    pred_total = pred_aciertos + pred_fallos
    acierto_partidos = pred_aciertos / pred_total if pred_total > 0 else 0.0

    bs_sis = sum(bs_sis_list) / len(bs_sis_list) if bs_sis_list else 0.0
    bs_casa = sum(bs_casa_list) / len(bs_casa_list) if bs_casa_list else 0.0
    bs_cal = sum(bs_cal_list) / len(bs_cal_list) if bs_cal_list else 0.0

    return {
        'total': _grupo(bets_1x2 + bets_ou),
        '1x2':   _grupo(bets_1x2),
        'ou':    _grupo(bets_ou),
        'acierto_partidos': acierto_partidos,
        'pred_aciertos':    pred_aciertos,
        'pred_total':       pred_total,
        'bs_sis':  bs_sis,
        'bs_cal':  bs_cal,
        'bs_casa': bs_casa,
        # Pareado: antes restaba medias sobre conjuntos distintos de partidos.
        'bs_glob':     sum(dif_glob) / len(dif_glob) if dif_glob else 0.0,
        'bs_glob_cal': sum(dif_glob_cal) / len(dif_glob_cal) if dif_glob_cal else 0.0,
        'fraccion_kelly': fraccion_kelly,
        'por_liga': por_liga,
    }


def semaforo(valor, bueno, malo, mayor_es_mejor=True):
    """Devuelve fill verde/amarillo/rojo/neutro segun umbrales."""
    if valor is None or valor == '—':
        return FILL_NEUTRO
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return FILL_NEUTRO
    if mayor_es_mejor:
        if v >= bueno: return FILL_VERDE
        if v >= malo:  return FILL_AMARILLO
        return FILL_ROJO
    else:
        if v <= bueno: return FILL_VERDE
        if v <= malo:  return FILL_AMARILLO
        return FILL_ROJO

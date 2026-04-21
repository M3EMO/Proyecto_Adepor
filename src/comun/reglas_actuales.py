"""
Reglas actuales del motor (Fase 3.3.5) como funcion reutilizable.

Extraido de scripts/resimular_liquidadas.py para que tanto el script como la
pestana 'Si Hubiera' del Excel compartan la misma logica de decision.

Camino 1  : favorito de prob con EV escalado
Camino 2  : max-EV si no hubo C1
Camino 2B : desacuerdo prob vs mercado (favorito distinto)
Camino 3  : convergencia absoluta (EV >= 1.0)
Camino 4  : consenso prob_min=0.36, cuota 1.12-2.00, favorito coincide con mercado
"""
from src.comun.config_motor import get_param

LIGAS_SESGO = ('Brasil', 'Inglaterra', 'Noruega', 'Turquia')


def min_ev_escalado(p, umbral=0.03):
    """Umbral de EV escalado por prob: cuanto mas alta la prob, mas laxo."""
    if p >= 0.50: return umbral
    if p >= 0.40: return umbral * 2.67
    if p >= 0.33: return umbral * 4.0
    return 999


def evaluar_actual(p1, px, p2, c1, cx, c2, liga):
    """Aplica los 5 caminos de motor_calculadora (Fase 3.3.5) y devuelve
    (pick, cuota, camino) donde pick in {LOCAL, EMPATE, VISITA} o None si pasa.

    Args:
        p1, px, p2: probabilidades Dixon-Coles
        c1, cx, c2: cuotas de mercado
        liga: pais/liga (afecta umbrales por scope y F2b)

    Returns:
        (pick, cuota, camino) o (None, None, razon_de_pasar)
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None, None, None
    floor = 0.40
    margen = get_param('margen_predictivo_1x2', scope=liga, default=0.03)
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15)
    techo, techo_alta = 5.0, 8.0
    c4_prob = 0.36
    c4_cmin = 1.12
    c4_cmax = 2.00

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None, None, 'margen'
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = p_f * c_f - 1
    umb_f = 0.03 * (0.5 / p_f) if p_f > 0 else 999
    div_f = p_f - 1 / c_f

    # C1
    if p_f >= floor and c_f <= techo and ev_f >= umb_f and div_f <= div_max:
        return fav, c_f, 'C1'
    # C2B
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
            and ev_f >= min_ev_escalado(p_f) and c_f <= techo_alta):
        return fav, c_f, 'C2B'
    # C3
    if p_f >= floor and ev_f >= 1.0 and c_f <= techo_alta:
        return fav, c_f, 'C3'
    # C4 Consenso con Mercado
    if fav == fav_mkt and p_f >= c4_prob and c4_cmin <= c_f <= c4_cmax and div_f <= div_max:
        return fav, c_f, 'C4'
    # C2 (max-EV)
    evs = {k: probs[k] * cuotas[k] - 1 for k in probs}
    ev_k = max(evs, key=evs.get)
    p_e, c_e, m_e = probs[ev_k], cuotas[ev_k], evs[ev_k]
    umb_e = 0.03 * (0.5 / p_e) if p_e > 0 else 999
    div_e = p_e - 1 / c_e
    if ev_k == 'VISITA' and 0.33 <= p_e < 0.40 and liga in LIGAS_SESGO:
        return None, None, 'F2b'
    if c_e <= techo and m_e >= umb_e and div_e <= div_max:
        return ev_k, c_e, 'C2'
    return None, None, 'PASAR'

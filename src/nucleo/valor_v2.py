"""
Modelo v2 (D-019): Pinnacle como verdad.

La probabilidad justa sale de las cuotas de Pinnacle sin margen. El usuario compara la
cuota minima con la de su casa (BetWarrior, Bet365, casas locales) y confirma solo si su
casa paga mas. El edge se mide con el CLV de lo confirmado contra el cierre de Pinnacle.

Sin margen = normalizacion proporcional de 1/cuota.
shortcut: la normalizacion proporcional sobreestima levemente a los underdogs (sesgo
favorito-underdog); cambiar a metodo de Shin o potencia si el CLV de underdogs sale peor.
"""
from src.comun.config_motor import get_param

UMBRAL_EV_V2 = get_param('umbral_ev_v2', default=0.02)          # EV minimo sobre la prob justa
FRACCION_KELLY_V2 = get_param('fraccion_kelly_v2', default=0.25)  # D-020: sale del frente de Pareto
TOPE_STAKE_V2 = get_param('tope_stake_v2', default=0.005)         # D-020: con Max DD p95 15% el frente da ~0.5%


def prob_justa(cuotas):
    """Probabilidades sin margen a partir de las cuotas de un mercado. None si falta alguna."""
    if not cuotas or any(not c or c <= 1 for c in cuotas):
        return None
    inv = [1 / c for c in cuotas]
    total = sum(inv)
    return [x / total for x in inv]


def cuota_minima(p, umbral=UMBRAL_EV_V2):
    """Cuota a partir de la cual la apuesta tiene EV >= umbral sobre la prob justa."""
    return (1 + umbral) / p


def stake_v2(p, cuota, bankroll, fraccion=FRACCION_KELLY_V2, tope=TOPE_STAKE_V2):
    """Kelly fraccional con tope, sobre la prob justa. 0 si no hay valor."""
    kelly = (p * cuota - 1) / (cuota - 1) if cuota > 1 else 0.0
    if kelly <= 0:
        return 0.0
    return round(bankroll * min(fraccion * kelly, tope), 2)


def tabla_valor(fila):
    """Para un partido, lista de (mercado, pick, prob_justa, cuota_minima) desde cuotas Pinnacle.

    fila: dict con pin_1, pin_x, pin_2, pin_o25, pin_u25.
    """
    out = []
    for mercado, picks, claves in (('1X2', ('LOCAL', 'EMPATE', 'VISITA'), ('pin_1', 'pin_x', 'pin_2')),
                                   ('OU', ('OVER 2.5', 'UNDER 2.5'), ('pin_o25', 'pin_u25'))):
        probs = prob_justa([fila.get(k) for k in claves])
        if probs:
            out.extend((mercado, pick, p, cuota_minima(p)) for pick, p in zip(picks, probs))
    return out


def clv_v2(cuota_tomada, cierres, idx):
    """EV de la cuota tomada contra el cierre de Pinnacle sin margen (positivo = edge).

    cierres: cuotas de cierre Pinnacle del mercado; idx: posicion del pick en ese mercado.
    """
    probs = prob_justa(cierres)
    return None if probs is None or not cuota_tomada else cuota_tomada * probs[idx] - 1

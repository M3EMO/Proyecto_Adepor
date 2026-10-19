"""
Yield potencial: cada pick liquidado a 1 unidad, tenga o no stake.

NO es dinero real. El pretest tiene stake 0 y aqui cuenta igual.
El dinero real vive en metricas.metricas_dinero.
"""
import random

from src.comun.picks import cuota_para_pick

MERCADOS = {'1X2': 'apuesta_1x2', 'OU': 'apuesta_ou'}
_RESAMPLES = 2000
_SEED = 42


def apuestas_potenciales(filas):
    """Lista de apuestas liquidadas a 1 unidad. Omite picks sin cuota valida (> 1)."""
    out = []
    for f in filas:
        for mercado, col in MERCADOS.items():
            ap = str(f.get(col) or '')
            ganada = ap.startswith('[GANADA]')
            if not (ganada or ap.startswith('[PERDIDA]')):
                continue
            cuota = cuota_para_pick(ap, f['cuota_1'], f['cuota_x'], f['cuota_2'],
                                    f['cuota_o25'], f['cuota_u25'])
            if cuota <= 1:
                continue
            out.append({'pais': f['pais'], 'fecha': f['fecha'], 'mercado': mercado,
                        'cuota': cuota, 'ganada': ganada,
                        'pl': cuota - 1 if ganada else -1.0})
    return out


def _bootstrap_ci(pls):
    """IC 95% del yield (media de P/L por apuesta) por bootstrap. Semilla fija."""
    rng = random.Random(_SEED)
    n = len(pls)
    medias = sorted(sum(rng.choices(pls, k=n)) / n for _ in range(_RESAMPLES))
    return medias[int(0.025 * (_RESAMPLES - 1))], medias[int(0.975 * (_RESAMPLES - 1))]


def _resumen(apuestas):
    n = len(apuestas)
    if n == 0:
        return {'n': 0, 'ganadas': 0, 'hit': None, 'profit': 0.0, 'yield': None,
                'break_even': None, 'ci_low': None, 'ci_high': None}
    pls = [a['pl'] for a in apuestas]
    ci_low, ci_high = _bootstrap_ci(pls)
    ganadas = sum(1 for a in apuestas if a['ganada'])
    return {
        'n': n,
        'ganadas': ganadas,
        'hit': ganadas / n,
        'profit': sum(pls),
        'yield': sum(pls) / n,
        # Hit rate minimo para yield 0: media de probabilidades implicitas.
        'break_even': sum(1 / a['cuota'] for a in apuestas) / n,
        'ci_low': ci_low,
        'ci_high': ci_high,
    }


def yield_potencial(filas):
    """Devuelve global, por_liga y por_mercado. Cada grupo trae n, hit, yield, IC 95%."""
    apuestas = apuestas_potenciales(filas)
    por_liga = {}
    for a in apuestas:
        por_liga.setdefault(a['pais'], []).append(a)
    return {
        'global': _resumen(apuestas),
        'por_liga': {p: _resumen(v) for p, v in sorted(por_liga.items())},
        'por_mercado': {m: _resumen([a for a in apuestas if a['mercado'] == m])
                        for m in MERCADOS},
    }

"""
Simulacion de apuestas con EV positivo contra Pinnacle. Protocolo: docs/specs/12-producto-deploy.md.

Uso: python -I analisis/simular_apuestas_ev.py [top5|todas]
Salida: analisis/simular_apuestas_ev.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analisis'))
from src.nucleo.valor_v2 import UMBRAL_EV_V2, stake_v2  # noqa: E402
from value_pinnacle_bet365 import apuestas  # noqa: E402

DIVS = ('E0', 'SP1', 'D1', 'I1', 'F1')
CARPETAS = ('3', '4')  # temporadas 2023/24 y 2024/25
GRILLA_N = (50, 100, 250, 500)
N_SIM, BANKROLL, DD_MAX = 5000, 100_000.0, 0.15


def piscina(variante='top5'):
    """Apuestas 1X2 con EV previo > umbral: (cuota, prob previa, prob de cierre) y partidos totales."""
    out = []
    for c in CARPETAS:
        for d in (DIVS if variante == 'top5' else [p.stem for p in sorted((ROOT / f'data/football_data/eu/{c}').glob('*.csv'))]):
            out += apuestas(ROOT / f'data/football_data/eu/{c}', f'{d}.csv')
    sel = [a for a in out if a['ev'] > UMBRAL_EV_V2]
    return [(a['cuota'], (a['ev'] + 1) / a['cuota'], (a['ev_cierre'] + 1) / a['cuota']) for a in sel], len(out) // 3


def simular(pool, n, p_real, rng, bankroll=BANKROLL):
    """Un camino de n apuestas. Devuelve (yield, drawdown maximo, CLV de cada apuesta)."""
    idx = rng.integers(0, len(pool), n)
    gana = rng.random(n)
    banca, pico, dd, pl, vol, clv = bankroll, bankroll, 0.0, 0.0, 0.0, []
    for k, i in enumerate(idx):
        cuota, q_pre, q_cierre = pool[i]
        stake = stake_v2(q_pre, cuota, banca)
        res = stake * (cuota - 1) if gana[k] < p_real(q_pre, q_cierre) else -stake
        banca += res
        pl, vol = pl + res, vol + stake
        pico = max(pico, banca)
        dd = max(dd, 1 - banca / pico)
        clv.append(cuota * q_cierre - 1)
    return (pl / vol if vol else 0.0), dd, clv


ESCENARIOS = {'A_cierre_es_verdad': lambda q_pre, q_cierre: q_cierre,
              'B_previo_es_verdad': lambda q_pre, q_cierre: q_pre}


def celda(pool, n, p_real, semilla):
    rng = np.random.default_rng(semilla)
    ys, dds, promo = [], [], 0
    for _ in range(N_SIM):
        y, dd, clv = simular(pool, n, p_real, rng)
        ys.append(y)
        dds.append(dd)
        clv = np.array(clv)
        excluye_cero = clv.mean() - 1.96 * clv.std(ddof=1) / np.sqrt(n) > 0
        promo += bool(excluye_cero and y >= 0)
    ys = np.array(ys)
    return {'n_apuestas': n, 'p_yield_positivo': float((ys > 0).mean()),
            'yield_p5_p50_p95': [float(np.percentile(ys, q)) for q in (5, 50, 95)],
            'p_drawdown_mayor_15': float((np.array(dds) > DD_MAX).mean()), 'p_promocion': promo / N_SIM}


def main():
    variante = sys.argv[1] if len(sys.argv) > 1 else 'top5'
    pool, n_partidos = piscina(variante)
    sem = 20261023
    r = {'variante': variante, 'piscina': len(pool), 'partidos_en_piscina': n_partidos,
         'apuestas_por_partido': len(pool) / n_partidos,
         'ev_previo_medio': float(np.mean([c * q - 1 for c, q, _ in pool])),
         'ev_cierre_medio': float(np.mean([c * qc - 1 for c, _, qc in pool])),
         'escenarios': {nom: [celda(pool, n, f, sem) for n in GRILLA_N] for nom, f in ESCENARIOS.items()}}
    texto = json.dumps(r, indent=2)
    (ROOT / ('analisis/simular_apuestas_ev.json' if variante == 'top5' else f'analisis/simular_apuestas_ev_{variante}.json')).write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

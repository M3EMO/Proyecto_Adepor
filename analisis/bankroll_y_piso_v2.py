"""
Dos preguntas del usuario sobre el v2 (2026-10-23), con datos de football-data (Europa top 6):

1. Evolucion del bankroll: por partido, el v2 elige el resultado de mayor EV de Bet365 previo sobre
   la prob justa de Pinnacle previo, si ese EV es >= 2 %, y apuesta stake_v2 (Kelly 0.25, tope 0.5 %).
   Bankroll inicial 100.000, con interes compuesto por fecha. Exploratorio: no decide nada.
2. Piso de probabilidad: protocolo pre-registrado en el bead adepor-aua (eleccion 2019-2022,
   prueba 2023-2025).

Uso:  python -I analisis/bankroll_y_piso_v2.py [salida.json]
"""
import csv
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analisis'))  # -I quita el directorio del script del path
from margen_y_tiros_pinnacle import DIVS, RES, TEMP_MIN, _f, _fecha, proporcional  # noqa: E402
from src.nucleo.valor_v2 import UMBRAL_EV_V2, stake_v2  # noqa: E402

BANKROLL = 100_000.0
PISOS = (0.0, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
N_MIN_ELECCION, N_BOOT, SEMILLA = 200, 2000, 42
TEMPS_ELECCION, TEMPS_PRUEBA = ('2019', '2020', '2021', '2022'), ('2023', '2024', '2025')


def picks(dir_csvs='data/football_data/eu'):
    """Un pick por partido: el resultado de mayor EV de Bet365 previo sobre Pinnacle previo, si EV >= 2 %."""
    out = []
    for path in glob.glob(f'{dir_csvs}/**/*.csv', recursive=True):
        for r in csv.DictReader(open(path, encoding='latin-1')):
            r = {(k or '').lstrip('﻿ï»¿'): v for k, v in r.items()}  # BOM leido como latin-1
            fecha, res = _fecha(r.get('Date')), RES.get(r.get('FTR'))
            if r.get('Div') not in DIVS or fecha is None or res is None:
                continue
            temp = str(fecha.year if fecha.month >= 7 else fecha.year - 1)
            pre = [_f(r.get(c)) for c in ('PSH', 'PSD', 'PSA')]
            b365 = [_f(r.get(c)) for c in ('B365H', 'B365D', 'B365A')]
            cierre = [_f(r.get(c)) for c in ('PSCH', 'PSCD', 'PSCA')]
            if temp < TEMP_MIN or not (all(pre) and all(b365) and all(cierre)):
                continue
            p = proporcional(pre)
            evs = [c * q - 1 for c, q in zip(b365, p)]
            i = int(np.argmax(evs))
            if evs[i] >= UMBRAL_EV_V2:
                out.append({'fecha': fecha, 'temp': temp, 'p': float(p[i]), 'cuota': b365[i], 'ev': evs[i],
                            'gana': res == i, 'clv': b365[i] * float(proporcional(cierre)[i]) - 1})
    return sorted(out, key=lambda x: x['fecha'])


def evolucion(ps, bankroll=BANKROLL):
    """Bankroll con stake_v2 e interes compuesto: los picks de un mismo dia usan el bankroll del inicio del dia."""
    por_dia = defaultdict(list)
    for x in ps:
        por_dia[x['fecha']].append(x)
    banca, pico, dd_max, vol, curva = bankroll, bankroll, 0.0, 0.0, []
    por_temp = defaultdict(lambda: {'n': 0, 'pl': 0.0, 'vol': 0.0})
    for dia in sorted(por_dia):
        inicio = banca
        for x in por_dia[dia]:
            stake = stake_v2(x['p'], x['cuota'], inicio)
            pl = stake * (x['cuota'] - 1) if x['gana'] else -stake
            banca += pl
            vol += stake
            t = por_temp[x['temp']]
            t['n'] += 1
            t['pl'] += pl
            t['vol'] += stake
        pico = max(pico, banca)
        dd_max = max(dd_max, 1 - banca / pico)
        curva.append((dia.strftime('%Y-%m-%d'), round(banca, 2)))
    return {'n': len(ps), 'bankroll_final': round(banca, 2), 'pl': round(banca - bankroll, 2),
            'yield': (banca - bankroll) / vol if vol else None, 'drawdown_max': dd_max,
            'clv_medio': float(np.mean([x['clv'] for x in ps])) if ps else None,
            'acierto': float(np.mean([x['gana'] for x in ps])) if ps else None,
            'por_temporada': {k: {**v, 'yield': v['pl'] / v['vol'] if v['vol'] else None} for k, v in sorted(por_temp.items())},
            'curva': curva}


def _ic95(d):
    d = np.asarray(d, float)
    m = d[np.random.default_rng(SEMILLA).integers(0, len(d), (N_BOOT, len(d)))].mean(axis=1)
    return {'n': len(d), 'media': float(d.mean()), 'ic95': [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]}


def piso(ps):
    """Protocolo adepor-aua: elige el piso con 2019-2022 y lo prueba una vez con 2023-2025."""
    elec = [x for x in ps if x['temp'] in TEMPS_ELECCION]
    grilla = {}
    for piso_p in PISOS:
        sel = [x['clv'] for x in elec if x['p'] >= piso_p]
        grilla[piso_p] = {'n': len(sel), 'clv_medio': float(np.mean(sel)) if sel else None}
    validos = [k for k, v in grilla.items() if v['n'] >= N_MIN_ELECCION]
    elegido = max(validos, key=lambda k: grilla[k]['clv_medio'])
    prueba = [x for x in ps if x['temp'] in TEMPS_PRUEBA]
    con_piso = _ic95([x['clv'] for x in prueba if x['p'] >= elegido])
    sin_piso = _ic95([x['clv'] for x in prueba])
    pasa = con_piso['ic95'][0] > 0 and con_piso['media'] > sin_piso['media']
    return {'grilla_eleccion': grilla, 'piso_elegido': elegido, 'prueba_con_piso': con_piso,
            'prueba_sin_piso': sin_piso, 'pasa_regla': pasa}


def _autochequeo():
    x = {'fecha': _fecha('01/01/2024'), 'temp': '2023', 'p': 0.5, 'cuota': 2.2, 'gana': True, 'clv': 0.05}
    r = evolucion([x], 100_000.0)
    assert r['n'] == 1 and r['pl'] == stake_v2(0.5, 2.2, 100_000.0) * 1.2


def main():
    _autochequeo()
    salida = sys.argv[1] if len(sys.argv) > 1 else 'analisis/bankroll_y_piso_v2.json'
    ps = picks()
    out = {'beads': ['adepor-aua'], 'n_picks': len(ps), 'evolucion': evolucion(ps),
           'evolucion_p_min_035': evolucion([x for x in ps if x['p'] >= 0.35]), 'piso': piso(ps)}
    Path(salida).write_text(json.dumps(out, indent=2, default=str))
    print(f'{len(ps)} picks -> {salida}')


if __name__ == '__main__':
    main()

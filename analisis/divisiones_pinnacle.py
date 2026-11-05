"""
Experimento adepor-4c8 (protocolo pre-registrado el 2026-10-23, ver el bead).

A) Calibracion del cierre de Pinnacle por nivel de division.
B) CLV de los picks del v2 (mayor EV de Bet365 previo sobre Pinnacle previo, EV >= 2 %) por nivel,
   por temporada y por tramo de probabilidad.

Uso:  python -I analisis/divisiones_pinnacle.py [salida.json]
"""
import csv
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))  # -I quita el directorio del script del path
from margen_y_tiros_pinnacle import RES, TEMP_MIN, _f, _fecha, proporcional  # noqa: E402

NIVELES = {'N1': ('E0', 'SP1', 'I1', 'D1', 'F1', 'SC0'), 'N2': ('E1', 'SP2', 'I2', 'D2', 'F2', 'SC1'),
           'N3': ('E2', 'SC2'), 'N4': ('E3', 'EC', 'SC3')}
DIV_NIVEL = {d: n for n, ds in NIVELES.items() for d in ds}
TEMPS_VIGENTE = ('2023', '2024', '2025')
UMBRAL_EV, N_BOOT, SEMILLA, NIVEL_IC = 0.02, 2000, 42, 98.75
TRAMOS = ((0, 0.20), (0.20, 0.35), (0.35, 0.50), (0.50, 1.01))


def cargar(dir_csvs='data/football_data/eu'):
    out = []
    for path in glob.glob(f'{dir_csvs}/**/*.csv', recursive=True):
        for r in csv.DictReader(open(path, encoding='latin-1')):
            r = {(k or '').lstrip('﻿ï»¿'): v for k, v in r.items()}  # BOM leido como latin-1
            fecha, res = _fecha(r.get('Date')), RES.get(r.get('FTR'))
            if r.get('Div') not in DIV_NIVEL or fecha is None or res is None:
                continue
            temp = str(fecha.year if fecha.month >= 7 else fecha.year - 1)
            cierre = [_f(r.get(c)) for c in ('PSCH', 'PSCD', 'PSCA')]
            if temp < TEMP_MIN or not all(cierre):
                continue
            out.append({'nivel': DIV_NIVEL[r['Div']], 'temp': temp, 'res': res, 'cierre': cierre,
                        'pre': [_f(r.get(c)) for c in ('PSH', 'PSD', 'PSA')],
                        'b365': [_f(r.get(c)) for c in ('B365H', 'B365D', 'B365A')]})
    return out


def calibracion(filas):
    """Pendiente e intercepto de la regresion logistica de y sobre logit(p), resultados apilados."""
    p = np.array([q for f in filas for q in proporcional(f['cierre'])]).clip(1e-6, 1 - 1e-6)
    y = np.array([float(i == f['res']) for f in filas for i in range(3)])
    x = np.log(p / (1 - p))

    def nll(th):
        z = th[0] + th[1] * x
        return np.mean(np.logaddexp(0, z) - y * z)
    a, b = minimize(nll, [0.0, 1.0]).x
    margen = np.mean([sum(1 / c for c in f['cierre']) - 1 for f in filas])
    brier = np.mean([sum((q - (i == f['res'])) ** 2 for i, q in enumerate(proporcional(f['cierre']))) for f in filas])
    return {'n_partidos': len(filas), 'intercepto': float(a), 'pendiente': float(b),
            'margen_medio': float(margen), 'brier': float(brier)}


def picks(filas):
    out = []
    for f in filas:
        if not (all(f['pre']) and all(f['b365'])):
            continue
        p = proporcional(f['pre'])
        evs = [c * q - 1 for c, q in zip(f['b365'], p)]
        i = int(np.argmax(evs))
        if evs[i] >= UMBRAL_EV:
            c = f['b365'][i]
            out.append({'nivel': f['nivel'], 'temp': f['temp'], 'p': float(p[i]),
                        'clv': c * float(proporcional(f['cierre'])[i]) - 1,
                        'pl': c - 1 if f['res'] == i else -1.0})
    return out


def ic(d, nivel=95):
    d = np.asarray(d, float)
    if not len(d):
        return {'n': 0}
    m = d[np.random.default_rng(SEMILLA).integers(0, len(d), (N_BOOT, len(d)))].mean(axis=1)
    cola = (100 - nivel) / 2
    return {'n': len(d), 'media': float(d.mean()),
            f'ic{nivel}': [float(np.percentile(m, cola)), float(np.percentile(m, 100 - cola))]}


def main():
    salida = sys.argv[1] if len(sys.argv) > 1 else 'analisis/divisiones_pinnacle.json'
    filas = cargar()
    ps = picks(filas)
    out = {'bead': 'adepor-4c8', 'calibracion': {}, 'edge_vigente': {}, 'por_temporada': {}, 'por_tramo': {}}
    for n in NIVELES:
        fn, pn = [f for f in filas if f['nivel'] == n], [x for x in ps if x['nivel'] == n]
        out['calibracion'][n] = calibracion(fn)
        vig = [x['clv'] for x in pn if x['temp'] in TEMPS_VIGENTE]
        r = ic(vig, NIVEL_IC)
        out['edge_vigente'][n] = {**r, 'yield': float(np.mean([x['pl'] for x in pn if x['temp'] in TEMPS_VIGENTE])) if vig else None,
                                  'pasa': bool(vig) and r[f'ic{NIVEL_IC}'][0] > 0}
        por_t = defaultdict(list)
        for x in pn:
            por_t[x['temp']].append(x)
        out['por_temporada'][n] = {t: {'n': len(v), 'clv': float(np.mean([x['clv'] for x in v])),
                                       'yield': float(np.mean([x['pl'] for x in v]))} for t, v in sorted(por_t.items())}
    for lo, hi in TRAMOS:
        clave = f'{lo:.2f}-{min(hi, 1):.2f}'
        sel = [x for x in ps if lo <= x['p'] < hi]
        out['por_tramo'][clave] = {t: {'n': len(v), 'clv': float(np.mean([x['clv'] for x in v]))}
                                   for t in sorted({x['temp'] for x in sel})
                                   for v in [[x for x in sel if x['temp'] == t]]}
    Path(salida).write_text(json.dumps(out, indent=2))
    print(f'{len(filas)} partidos, {len(ps)} picks -> {salida}')


if __name__ == '__main__':
    main()

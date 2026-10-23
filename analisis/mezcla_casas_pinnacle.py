"""
Experimento adepor-u3x (protocolo pre-registrado el 2026-10-22, ver el bead).

Mezcla el cierre de Pinnacle con otra fuente de cierre (promedio de mercado, Bet365 o Betfair
Exchange) con un pool log-lineal p ~ p_pin^w * p_x^(1-w), y mide si baja la log-loss contra
Pinnacle solo. w se ajusta walk-forward: temporadas anteriores, prueba en la siguiente.

Uso:  python -I analisis/mezcla_casas_pinnacle.py [salida.json]
Lee data/football_data/eu (Europa top 6) y data/football_data/new (ARG, BRA, NOR).
"""
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

sys.path.insert(0, str(Path(__file__).parent))  # -I quita el directorio del script del path
from margen_y_tiros_pinnacle import (DIVS, PAISES_NEW, RES, TEMP_MIN, _f, _fecha,  # noqa: E402
                                     proporcional)

N_BOOT, SEMILLA = 2000, 42
FUENTES = {'promedio': ('AvgCH', 'AvgCD', 'AvgCA'), 'bet365': ('B365CH', 'B365CD', 'B365CA'),
           'betfair_ex': ('BFECH', 'BFECD', 'BFECA')}
ESTRATOS = {'europa': ('data/football_data/eu', ('promedio', 'bet365')),
            'arg_bra_nor': ('data/football_data/new', ('promedio', 'bet365', 'betfair_ex'))}


def cargar(dir_csvs, fuente):
    cols = FUENTES[fuente]
    out = []
    for path in sorted(glob.glob(f'{dir_csvs}/**/*.csv', recursive=True)):
        for r in csv.DictReader(open(path, encoding='latin-1')):
            r = {(k or '').lstrip('﻿ï»¿'): v for k, v in r.items()}  # BOM leido como latin-1
            if r.get('Div') not in DIVS and r.get('Country') not in PAISES_NEW:
                continue
            fecha, res = _fecha(r.get('Date')), RES.get(r.get('FTR') or r.get('Res'))
            if fecha is None or res is None:
                continue
            temp = str(r.get('Season') or (fecha.year if fecha.month >= 7 else fecha.year - 1)).split('/')[0]
            pin = [_f(r.get(c)) for c in ('PSCH', 'PSCD', 'PSCA')]
            otra = [_f(r.get(c)) for c in cols]
            if temp >= TEMP_MIN and all(pin) and all(otra):
                out.append((temp, np.log(proporcional(pin)), np.log(proporcional(otra)), res))
    return out


def logloss(w, lp, lx, y):
    z = w * lp + (1 - w) * lx
    z = z - z.max(axis=1, keepdims=True)
    lz = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
    return -lz[np.arange(len(y)), y]


def bootstrap(d, nivel):
    d = np.asarray(d)
    rng = np.random.default_rng(SEMILLA)
    medias = d[rng.integers(0, len(d), (N_BOOT, len(d)))].mean(axis=1)
    cola = (100 - nivel) / 2
    return {'n': len(d), 'media': float(d.mean()), f'ic{nivel}': [float(np.percentile(medias, cola)),
                                                               float(np.percentile(medias, 100 - cola))]}


def prueba(filas):
    temps = sorted({f[0] for f in filas})
    diffs, acierto_pin, acierto_mix, por_temp = [], [], [], {}
    arr = lambda fs: (np.array([f[1] for f in fs]), np.array([f[2] for f in fs]), np.array([f[3] for f in fs]))
    for t in temps[1:]:
        lp_tr, lx_tr, y_tr = arr([f for f in filas if f[0] < t])
        te = [f for f in filas if f[0] == t]
        if not te:
            continue
        w = minimize_scalar(lambda w: logloss(w, lp_tr, lx_tr, y_tr).mean(), bounds=(-1, 2), method='bounded').x
        lp, lx, y = arr(te)
        mix, sola = logloss(w, lp, lx, y), -lp[np.arange(len(y)), y]
        diffs += list(mix - sola)
        p_mix = w * lp + (1 - w) * lx
        acierto_pin += list(lp.argmax(axis=1) == y)
        acierto_mix += list(p_mix.argmax(axis=1) == y)
        por_temp[t] = {'n': len(te), 'w': float(w), 'logloss_pinnacle': float(sola.mean()),
                       'logloss_mezcla': float(mix.mean())}
    return {'por_temporada': por_temp, 'diff_mezcla_vs_pinnacle': {**bootstrap(diffs, 95), **bootstrap(diffs, 99)},
            'acierto_favorito': {'pinnacle': float(np.mean(acierto_pin)), 'mezcla': float(np.mean(acierto_mix))}}


def _autochequeo():
    lp = np.log([[0.5, 0.3, 0.2]])
    lx = np.log([[0.4, 0.3, 0.3]])
    assert abs(logloss(1.0, lp, lx, np.array([0]))[0] + np.log(0.5)) < 1e-12  # w=1 es Pinnacle solo
    assert abs(logloss(0.0, lp, lx, np.array([0]))[0] + np.log(0.4)) < 1e-12  # w=0 es la otra casa


def main():
    _autochequeo()
    salida = sys.argv[1] if len(sys.argv) > 1 else 'analisis/mezcla_casas_pinnacle.json'
    out = {'bead': 'adepor-u3x'}
    for estrato, (dir_csvs, fuentes) in ESTRATOS.items():
        for fuente in fuentes:
            filas = cargar(dir_csvs, fuente)
            out[f'{estrato}_{fuente}'] = {'n': len(filas), **prueba(filas)}
    with open(salida, 'w') as fh:
        json.dump(out, fh, indent=2)
    print(f'-> {salida}')


if __name__ == '__main__':
    main()

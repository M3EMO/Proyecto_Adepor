"""
Cruce entre Pinnacle, Bet365 y el promedio del mercado. Protocolo: docs/specs/13-estudios-forward.md (E4).

Uso: python -I analisis/cruce_casas_pinnacle.py
Salida: analisis/cruce_casas_pinnacle.json
"""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
UMBRAL, N_BOOT, N_MIN = 0.02, 10000, 80
RES = {'H': 0, 'D': 1, 'A': 2}


def sin_margen(o):
    inv = 1 / np.array(o)
    return inv / inv.sum()


def apuestas(carpeta):
    """Una fila por resultado: cuota B365, EV vs Pinnacle de B365 y de Avg, CLV, movimiento de Pinnacle."""
    out = []
    for f in sorted((ROOT / f'data/football_data/eu/{carpeta}').glob('*.csv')):
        for r in csv.DictReader(open(f, encoding='latin-1')):
            try:
                g = lambda pre, suf: [float(r[f'{pre}{k}']) for k in suf]
                pin, b365, avg, pinc = g('PS', 'HDA'), g('B365', 'HDA'), g('Avg', 'HDA'), g('PSC', 'HDA')
            except (KeyError, ValueError):
                continue
            qp, qc = sin_margen(pin), sin_margen(pinc)
            for i in range(3):
                out.append({'ev_b': b365[i] * qp[i] - 1, 'ev_avg': avg[i] * qp[i] - 1,
                            'clv': b365[i] * qc[i] - 1, 'mov': qc[i] - qp[i]})
    return out


def resumen(x, rng):
    if not x:
        return {'n': 0}
    x = np.array(x)
    m = x[rng.integers(0, len(x), (N_BOOT, len(x)))].mean(axis=1)
    return {'n': len(x), 'media': float(x.mean()), 'ic95': [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]}


def senales(filas):
    s1 = [a for a in filas if a['ev_b'] > UMBRAL]
    return {'S1_base': s1, 'S2_cruce': [a for a in s1 if a['ev_avg'] > UMBRAL],
            'S3_solo_b365': [a for a in s1 if a['ev_avg'] <= 0]}


def main():
    rng = np.random.default_rng(20261023)
    r = {}
    for nombre, carpeta in (('exploracion_2023_24', '3'), ('validacion_2024_25', '4')):
        r[nombre] = {k: {'clv': resumen([a['clv'] for a in v], rng), 'mov_pinnacle': resumen([a['mov'] for a in v], rng)}
                     for k, v in senales(apuestas(carpeta)).items()}
    s2 = r['validacion_2024_25']['S2_cruce']['clv']
    r['exito'] = bool(s2['n'] >= N_MIN and s2['ic95'][0] > 0)
    texto = json.dumps(r, indent=2)
    (ROOT / 'analisis/cruce_casas_pinnacle.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

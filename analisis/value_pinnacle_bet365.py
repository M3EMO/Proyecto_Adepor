"""
Backtest "Pinnacle como verdad": apostar en Bet365 cuando paga mas que la probabilidad de
Pinnacle sin margen, ambas tomadas al mismo momento (columnas PS* y B365* de football-data).

Liquida con el resultado real y mide el EV esperado contra el cierre de Pinnacle sin margen.
Citado en docs/specs/10-modelo-v2.md.

Uso:  python analisis/value_pinnacle_bet365.py <dir_csvs> [salida.json]
"""
import csv
import glob
import json
import random
import sys
from pathlib import Path


def apuestas(dir_csvs, patron='*.csv'):
    out = []
    for f in sorted(glob.glob(f'{dir_csvs}/{patron}')):
        for r in csv.DictReader(open(f, encoding='latin-1')):
            try:
                ps = [float(r[k]) for k in ('PSH', 'PSD', 'PSA')]
                pc = [float(r[k]) for k in ('PSCH', 'PSCD', 'PSCA')]
                b = [float(r[k]) for k in ('B365H', 'B365D', 'B365A')]
                gh, ga = int(r['FTHG']), int(r['FTAG'])
            except (KeyError, ValueError):
                continue
            q = [1 / x for x in ps]
            q = [x / sum(q) for x in q]
            qc = [1 / x for x in pc]
            qc = [x / sum(qc) for x in qc]
            res = (gh > ga, gh == ga, gh < ga).index(True)
            for i in range(3):
                out.append({'ev': b[i] * q[i] - 1, 'ev_cierre': b[i] * qc[i] - 1,
                            'cuota': b[i], 'gano': i == res})
    return out


def resumen(todas, umbral, semilla=1):
    sel = [a for a in todas if a['ev'] > umbral]
    n = len(sel)
    if not n:
        return {'umbral': umbral, 'n': 0}
    pl = [(a['cuota'] - 1) if a['gano'] else -1.0 for a in sel]
    rng = random.Random(semilla)
    bs = sorted(sum(rng.choice(pl) for _ in pl) / n for _ in range(2000))
    return {'umbral': umbral, 'n': n, 'roi': sum(pl) / n, 'ic95': (bs[50], bs[1949]),
            'ev_esperado_vs_cierre': sum(a['ev_cierre'] for a in sel) / n,
            'cuota_mediana': sorted(a['cuota'] for a in sel)[n // 2]}


def main():
    todas = apuestas(sys.argv[1])
    out = {'resultados_posibles': len(todas),
           'por_umbral': [resumen(todas, u) for u in (0.0, 0.02, 0.04, 0.06)]}
    texto = json.dumps(out, indent=2, ensure_ascii=False)
    print(texto)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(texto, encoding='utf-8')


if __name__ == '__main__':
    main()

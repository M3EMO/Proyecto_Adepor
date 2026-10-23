"""
Seleccion de divisiones por EV contra el cierre de Pinnacle. Protocolo: docs/specs/12-producto-deploy.md.
Selecciona con 2023/24 (carpeta eu/3) y valida con 2024/25 (carpeta eu/4).

Uso: python -I analisis/seleccion_divisiones_ev.py
Salida: analisis/seleccion_divisiones_ev.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'analisis'))
from src.nucleo.valor_v2 import UMBRAL_EV_V2  # noqa: E402
from value_pinnacle_bet365 import apuestas  # noqa: E402

MIN_APUESTAS, N_BOOT = 30, 10000


def por_division(carpeta):
    out = {}
    for f in sorted((ROOT / f'data/football_data/eu/{carpeta}').glob('*.csv')):
        sel = [a['ev_cierre'] for a in apuestas(f.parent, f.name) if a['ev'] > UMBRAL_EV_V2]
        if sel:
            out[f.stem] = sel
    return out


def ic95(x, rng):
    x = np.asarray(x, float)
    m = x[rng.integers(0, len(x), (N_BOOT, len(x)))].mean(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def resumen(x, rng):
    return {'n': len(x), 'ev_cierre_medio': float(np.mean(x)), 'ic95': ic95(x, rng)} if x else {'n': 0}


def main():
    rng = np.random.default_rng(20261023)
    sel_data, val_data = por_division('3'), por_division('4')
    elegidas = sorted(d for d, x in sel_data.items() if len(x) >= MIN_APUESTAS and np.mean(x) > 0)
    grupo = [v for d in elegidas for v in val_data.get(d, [])]
    resto = [v for d, x in val_data.items() if d not in elegidas for v in x]
    r = {'elegidas': elegidas, 'n_divisiones_con_apuestas': len(sel_data),
         'seleccion': {d: {'n': len(x), 'ev_cierre_medio': float(np.mean(x))} for d, x in sorted(sel_data.items())},
         'validacion_elegidas': resumen(grupo, rng), 'validacion_resto': resumen(resto, rng)}
    r['exito'] = bool(grupo) and r['validacion_elegidas']['ic95'][0] > 0
    texto = json.dumps(r, indent=2)
    (ROOT / 'analisis/seleccion_divisiones_ev.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

"""
TEST CORRECCION BIAS POR LIGA - walk-forward.

Hipotesis: el bias por liga es mas persistente que el bias por equipo.
Si entrenamos correccion = mean(residuo_liga) sobre 2022-2025 y aplicamos a 2026,
deberia bajar RMSE 2026.

Validacion adicional: walk-forward por anio para descartar overfit cross-temporal.
"""

import sqlite3
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path
import numpy as np

import sys
sys.path.insert(0, '.')
from analisis.motor_xg_v2_08_audit_bias import (
    cargar_partidos, construir_eventos, computar_residuos
)

OUT_JSON = 'analisis/motor_xg_v2_09_correccion_bias_liga.json'


def test_correccion_bias_liga(residuos):
    """Walk-forward: train correcciones < year_test, eval == year_test."""
    print('\n=== TEST WALK-FORWARD: bias por liga ===\n')

    out = {}
    for year_test in ('2023', '2024', '2025', '2026'):
        train = [r for r in residuos if r['anio'] < year_test]
        test = [r for r in residuos if r['anio'] == year_test]

        # Calcular bias por liga sobre train
        by_liga = defaultdict(list)
        for r in train:
            by_liga[r['liga']].append(r['residuo'])
        bias_liga = {liga: float(np.mean(vals)) for liga, vals in by_liga.items() if len(vals) >= 50}

        # Eval
        errs_orig = np.array([r['residuo'] for r in test])
        errs_corr = []
        for r in test:
            c = bias_liga.get(r['liga'], 0)
            errs_corr.append(r['residuo'] - c)
        errs_corr = np.array(errs_corr)

        rmse_o = sqrt((errs_orig**2).mean()) if len(errs_orig) else None
        rmse_c = sqrt((errs_corr**2).mean()) if len(errs_corr) else None

        delta = rmse_c - rmse_o if (rmse_o and rmse_c) else 0
        flag = 'MEJORA' if delta < -0.001 else ('PEOR' if delta > 0.001 else 'NEUTRO')
        print(f'  Train < {year_test} ({len(train)} eventos), Test {year_test} (N={len(test)})')
        print(f'    RMSE original: {rmse_o:.4f}')
        print(f'    RMSE corregido: {rmse_c:.4f}')
        print(f'    Delta: {delta:+.4f} ({flag})')
        print(f'    Bias_liga mas grande: {sorted(bias_liga.items(), key=lambda x: -abs(x[1]))[:5]}')
        print()
        out[year_test] = {
            'n_train': len(train), 'n_test': len(test),
            'rmse_orig': rmse_o, 'rmse_corr': rmse_c, 'delta': delta,
            'flag': flag, 'bias_liga': bias_liga,
        }

    return out


def main():
    print('=== CORRECCION BIAS POR LIGA - walk-forward ===')
    partidos = cargar_partidos()
    eventos = construir_eventos(partidos)
    residuos = computar_residuos(eventos, theta=0.20, modelo='V5_NNLS')
    print(f'Eventos post-warmup: {len(residuos)}')

    out = test_correccion_bias_liga(residuos)

    # Resumen
    print('=== RESUMEN ===')
    print(f'{"year_test":<10} {"N":>6} {"RMSE_orig":>10} {"RMSE_corr":>10} {"delta":>8} {"flag":<10}')
    for y, d in out.items():
        print(f'{y:<10} {d["n_test"]:>6} {d["rmse_orig"]:>10.4f} {d["rmse_corr"]:>10.4f} {d["delta"]:>+8.4f} {d["flag"]:<10}')

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print(f'\nGuardado {OUT_JSON}')


if __name__ == '__main__':
    main()

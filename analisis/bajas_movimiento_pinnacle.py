"""
E15: las bajas del once predicen el movimiento de Pinnacle entre la linea previa y el cierre.
Protocolo: bead adepor-bgr y docs/specs/13-estudios-forward.md, seccion E15.

Uso: python -I analisis/bajas_movimiento_pinnacle.py
Salida: analisis/bajas_movimiento_pinnacle.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))
import fotmob_xg_vs_pinnacle as ev  # noqa: E402
import jugadores_vs_pinnacle as jv  # noqa: E402

TEMPORADAS = {'2024/25': '4', '2025/26': '5'}  # carpetas data/football_data/eu/<n>
N_BOOT, SEMILLA = 2000, 42
LOCAL, VISITA = 0, 2


def filas(fm, periodo):
    """Por partido cruzado con d y cuotas Pinnacle previa y cierre: (d, previa, cierre, b365 o None)."""
    pares, sin = ev.cruzar(fm, ev.cargar_fd('eu', periodo))
    out = [(p[8][0] - p[8][1], q[8], q[6], q[9]) for p, q in pares if q[8]]
    return out, {'cruzados': len(pares), 'sin_cruce': sin, 'con_previa': len(out)}


def pendiente(x, y):
    """Pendiente OLS de y sobre x con intercepto."""
    x = x - x.mean()
    return float((x * (y - y.mean())).sum() / (x * x).sum())


def pick(d, p10, p90):
    """d bajo (local mas debilitado) da visita; d alto da local; si no, sin pick."""
    return VISITA if d <= p10 else LOCAL if d >= p90 else None


def clv(cuota_previa, cierre, k):
    return cuota_previa[k] * jv.sin_margen(cierre)[k] - 1


def boot_media(v):
    rng = np.random.default_rng(SEMILLA)
    m = v[rng.integers(0, len(v), (N_BOOT, len(v)))].mean(axis=1)
    return {'n': len(v), 'media': float(v.mean()), 'ic95': [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]}


def boot_pendiente(x, y):
    rng = np.random.default_rng(SEMILLA)
    b = [pendiente(x[i], y[i]) for i in rng.integers(0, len(x), (N_BOOT, len(x)))]
    return {'n': len(x), 'pendiente': pendiente(x, y), 'ic95': [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]}


def _autochequeo():
    x = np.array([0.0, 1, 2, 3])
    assert abs(pendiente(x, 2 * x + 1) - 2) < 1e-12
    assert pick(-0.5, -0.2, 0.2) == VISITA and pick(0.5, -0.2, 0.2) == LOCAL and pick(0.0, -0.2, 0.2) is None
    assert pick(-0.2, -0.2, 0.2) == VISITA and pick(0.2, -0.2, 0.2) == LOCAL  # umbrales inclusivos
    # Cierre sin margen 0.5/0.25/0.25 y cuota previa 2.2 al local: CLV = 2.2 * 0.5 - 1 = 0.1.
    assert abs(clv([2.2, 4, 4], [1.9, 3.8, 3.8], LOCAL) - 0.1) < 1e-12
    r = boot_media(np.ones(10))
    assert r['media'] == 1 and r['ic95'] == [1.0, 1.0]


def main():
    _autochequeo()
    fm = [p for p in jv.con_variables(jv.cargar()) if p[8]]
    datos, res = {}, {'bead': 'adepor-bgr', 'n_fotmob_con_d': len(fm)}
    for t, periodo in TEMPORADAS.items():
        datos[t], res[t] = filas(fm, periodo)

    # Parte A: cambio de p local (previa -> cierre) sobre d, dos temporadas juntas.
    todas = datos['2024/25'] + datos['2025/26']
    d = np.array([f[0] for f in todas])
    dp = np.array([jv.sin_margen(f[2])[LOCAL] - jv.sin_margen(f[1])[LOCAL] for f in todas])
    res['A_pendiente_dp_local_sobre_d'] = boot_pendiente(d, dp)

    # Parte B: umbrales en 2024/25, picks en 2025/26.
    p10, p90 = (float(v) for v in np.percentile([f[0] for f in datos['2024/25']], [10, 90]))
    picks = [(k, f) for f in datos['2025/26'] if (k := pick(f[0], p10, p90)) is not None]
    prim = boot_media(np.array([clv(f[1], f[2], k) for k, f in picks]))
    res['B'] = {'p10': p10, 'p90': p90,
                'picks_local': sum(k == LOCAL for k, _ in picks), 'picks_visita': sum(k == VISITA for k, _ in picks),
                'clv_pinnacle_previa': prim,
                'clv_bet365_previa': boot_media(np.array([clv(f[3], f[2], k) for k, f in picks if f[3]])),
                'edge': prim['ic95'][0] > 0,
                # Post hoc, fuera del protocolo: separa el movimiento del margen de la linea previa.
                'post_hoc_margen_previa_medio': float(np.mean([sum(1 / np.array(f[1])) - 1 for _, f in picks])),
                'post_hoc_clv_previa_sin_margen': float(np.mean([jv.sin_margen(f[2])[k] / jv.sin_margen(f[1])[k] - 1
                                                                 for k, f in picks]))}
    texto = json.dumps(res, indent=2)
    (ROOT / 'analisis/bajas_movimiento_pinnacle.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

"""Pruebas de aceptacion X1-X4 de docs/specs/11-evaluacion-xg.md. Datos sinteticos, sin red."""
import datetime as dt

import numpy as np

from analisis import fotmob_xg_vs_pinnacle as ev


def partido(i, ht, at, hg, ag, xl, xv, dia):
    fecha = dt.date(2025, 8, 1) + dt.timedelta(days=dia)
    p = (47, fecha, hg, ag, ht, at, xl, xv)
    q = (47, fecha, hg, ag, ht, at, [2.0, 3.5, 4.0], 'H')
    return p, q


def serie(ultimo_xg):
    return [partido(i, 'A', 'B', 1, 0, 1.0, 0.5, i * 7) for i in range(7)] + \
           [partido(7, 'A', 'B', 1, 0, ultimo_xg, 0.5, 49)]


def test_x1_cruce_rechaza_nombres_distintos_y_cuenta_sin_pareja():
    fm = [(47, dt.date(2025, 8, 1), 1, 0, 'Arsenal', 'Chelsea', 1.0, 0.5)]
    fd = [(47, dt.date(2025, 8, 1), 1, 0, 'Arsenal', 'Chelsea', [2, 3, 4], 'H'),
          (47, dt.date(2025, 8, 1), 1, 0, 'Zzzzzz', 'Qqqqqq', [2, 3, 4], 'H'),
          (47, dt.date(2025, 8, 9), 1, 0, 'Arsenal', 'Chelsea', [2, 3, 4], 'H')]
    pares, sin = ev.cruzar(fm, fd)
    assert len(pares) == 1 and sin == 2


def test_x2_ema_no_usa_el_partido_actual():
    X1, _, _ = ev.features(serie(1.0))
    X2, _, _ = ev.features(serie(9.0))  # solo cambia el xG del ultimo partido
    assert len(X1) == 8 - ev.MIN_PREV
    assert np.allclose(X1[-1], X2[-1])  # la fila del ultimo partido no ve su propio xG


def datos_sinteticos(n, filtra):
    rng = np.random.default_rng(1)
    base = rng.dirichlet([4, 3, 3], n)
    y = np.array([rng.choice(3, p=p) for p in base])
    ruido = rng.normal(size=n)
    dxg = (y == 0) * 1.0 - (y == 2) * 1.0 + 0.5 * ruido if filtra else ruido
    X = np.column_stack([np.log(base[:, 0] / base[:, 1]), np.log(base[:, 2] / base[:, 1]), dxg, dxg])
    return X, y, base


def delta(filtra):
    Xtr, ytr, _ = datos_sinteticos(3000, filtra)
    Xte, yte, Pb = datos_sinteticos(3000, filtra)
    P = ev.ajustar(Xtr, ytr, Xte, [0, 1, 2])
    return ev.boot(ev.ll(P, yte) - ev.ll(Pb, yte), np.random.default_rng(0))


def test_x3_control_negativo_no_mejora():
    _, _, hi = delta(filtra=False)
    assert hi >= 0  # sin informacion, el IC no queda por debajo de 0


def test_x4_control_positivo_mejora():
    m, _, hi = delta(filtra=True)
    assert hi < 0 and m < 0

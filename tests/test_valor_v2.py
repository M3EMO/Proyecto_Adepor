from src.nucleo import valor_v2 as v


def test_prob_justa_quita_margen():
    p = v.prob_justa([2.0, 3.5, 4.0])
    assert abs(sum(p) - 1) < 1e-12 and p[0] > p[1] > p[2]
    assert v.prob_justa([2.0, 0, 4.0]) is None


def test_cuota_minima_y_stake():
    assert abs(v.cuota_minima(0.5, umbral=0.02) - 2.04) < 1e-12
    assert v.stake_v2(0.5, 1.9, 10000) == 0.0                     # sin valor: no apuesta
    # p=0.5, cuota 2.2 -> kelly 1/12; 0.25 * 1/12 = 2.08% < tope 2.5%
    assert v.stake_v2(0.5, 2.2, 10000, fraccion=0.25, tope=0.025) == round(10000 * 0.25 / 12, 2)
    assert v.stake_v2(0.5, 4.0, 10000, fraccion=1.0, tope=0.025) == 250.0   # tope activo


def test_clv_v2_contra_cierre_sin_margen():
    # cierre 1.90 / 1.90 -> 0.5 justa; tomada 2.10 -> EV +5%
    assert abs(v.clv_v2(2.10, [1.90, 1.90], 0) - 0.05) < 1e-12


def test_tabla_valor():
    filas = v.tabla_valor({'pin_1': 2.0, 'pin_x': 3.5, 'pin_2': 4.0, 'pin_o25': None, 'pin_u25': 1.9})
    assert [f[:2] for f in filas] == [('1X2', 'LOCAL'), ('1X2', 'EMPATE'), ('1X2', 'VISITA')]

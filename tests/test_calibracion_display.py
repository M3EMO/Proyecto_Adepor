from src.comun.calibracion_beta import calibrar_probs
from src.comun.calibracion_piecewise import calibrar_probs_pw


def test_fallback_beta_suma_uno():
    q = calibrar_probs(0.1, 0.2, 0.3, coefs=(1, -0.9, 1, -0.9, 1, -0.9))
    assert abs(sum(q) - 1) < 1e-12


def test_fallback_piecewise_suma_uno():
    q = calibrar_probs_pw(0.1, 0.2, 0.3, mapas={}, coefs_beta=(1, -0.9, 1, -0.9, 1, -0.9))
    assert abs(sum(q) - 1) < 1e-12

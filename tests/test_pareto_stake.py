import random

from analisis.pareto_stake import frente_pareto, simular


def test_simular_cuentas_a_mano():
    # Kelly con p=0.6, cuota 2.0 -> 0.2; fraccion 0.5 -> 0.1; gana y pierde: 1.1 * 0.9 = 0.99
    lg, dd = simular([(0.6, 2.0, True), (0.6, 2.0, False)], 0.5, 1.0)
    assert abs(lg - __import__('math').log(0.99)) < 1e-12 and abs(dd - 0.1) < 1e-12


def test_sin_edge_no_apuesta():
    lg, dd = simular([(0.4, 2.0, True), (0.4, 2.0, False)], 1.0, 1.0)
    assert lg == 0.0 and dd == 0.0


def test_frente_con_edge_real_es_monotono_y_respeta_tope_de_dd():
    rng = random.Random(3)
    apuestas = []
    for _ in range(400):                       # edge real: p verdadera 0.55 a cuota 2.0
        apuestas.append((0.55, 2.0, rng.random() < 0.55))
    eficientes, elegida = frente_pareto(apuestas, n_boot=200, dd_max=0.30)
    dds = [f['max_dd_p95'] for f in eficientes]
    crec = [f['crecimiento_mediano'] for f in eficientes]
    assert dds == sorted(dds) and crec == sorted(crec)   # mas riesgo, mas crecimiento
    assert elegida in eficientes and elegida['max_dd_p95'] <= 0.30
    assert all(f['crecimiento_mediano'] <= elegida['crecimiento_mediano']
               for f in eficientes if f['max_dd_p95'] <= 0.30)

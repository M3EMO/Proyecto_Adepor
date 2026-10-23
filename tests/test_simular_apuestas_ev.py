"""Prueba de la simulacion de apuestas (docs/specs/12-producto-deploy.md)."""

from analisis import simular_apuestas_ev as sim

def celda(pool, f):
    sim.N_SIM = 300
    return sim.celda(pool, 100, f, semilla=1)

def test_ev_real_positivo_gana_mas_de_la_mitad():
    pool = [(2.5, 0.45, 0.45)]  # cuota 2.5 con prob real 0.45: EV +12.5%
    assert celda(pool, sim.ESCENARIOS['B_previo_es_verdad'])['p_yield_positivo'] > 0.5

def test_ev_real_negativo_gana_menos_de_la_mitad():
    pool = [(2.5, 0.45, 0.35)]  # previo dice +12.5%, el cierre dice -12.5%
    assert celda(pool, sim.ESCENARIOS['A_cierre_es_verdad'])['p_yield_positivo'] < 0.5

def test_clv_positivo_constante_se_promueve():
    sim.N_SIM = 100
    pool = [(2.5, 0.45, 0.45), (3.0, 0.38, 0.37)]  # CLV positivo en ambas
    r = sim.celda(pool, 250, sim.ESCENARIOS['B_previo_es_verdad'], semilla=2)
    assert r['p_promocion'] > 0.5

import sqlite3

import pytest

from src.ingesta.betano_ar import canonico, cargar_diccionario, guardar_cuota, mismo_partido
from src.ingesta.motor_oddspapi import SQL_CUOTAS_FORWARD

D = cargar_diccionario()


def test_nombres_de_betano_resuelven_al_canonico():
    assert canonico('Defensa y Justicia', 'Argentina', D) == 'Defensa y Justicia'
    assert canonico('CA Platense', 'Argentina', D) == 'Platense'
    assert canonico('CA Independiente', 'Argentina', D) == 'Independiente'  # via prefijo "CA"
    assert canonico('Central Cordoba', 'Argentina', D) == 'Central Córdoba (santiago del Estero)'
    assert canonico('Club Inexistente', 'Argentina', D) is None


def test_mismo_partido_exige_orientacion():
    assert mismo_partido('CA Platense', 'Central Cordoba', 'Platense',
                         'Central Córdoba (santiago del Estero)', 'Argentina', D)
    assert not mismo_partido('Central Cordoba', 'CA Platense', 'Platense',
                             'Central Córdoba (santiago del Estero)', 'Argentina', D)


def test_guardar_cuota_valida_y_es_idempotente():
    conn = sqlite3.connect(':memory:')
    conn.executescript(SQL_CUOTAS_FORWARD)
    guardar_cuota(conn, '2026-11-02T22:00', '90509193', '2026-11-02T21:00', 1.65, 3.5, 5.5)
    guardar_cuota(conn, '2026-11-02T22:00', '90509193', '2026-11-02T21:00', 1.65, 3.5, 5.5)
    assert conn.execute("SELECT casa, fixture_id, COUNT(*) FROM cuotas_forward").fetchone() == (
        'betano_ar', 'bt:90509193', 1)
    with pytest.raises(ValueError):
        guardar_cuota(conn, 't', '1', 'i', 1.0, 3.5, 5.5)


from src.ingesta.betano_ar import capturar, elegir, eventos_1x2
from src.nucleo.valor_v2 import cuota_minima


def _resp(vivo=False, cuota1=2.2):
    sel = lambda i, p: {'id': f's{i}', 'price': p}
    return {'data': {'events': [
        {'id': '1', 'name': 'CA Platense - Central Cordoba', 'liveNow': vivo, 'startTime': 1794168000000,
         'markets': [{'type': 'MRES', 'suspended': False,
                      'selections': [sel(1, cuota1), sel(2, 3.2), sel(3, 4.0)]}]},
        {'id': '2', 'name': 'Sin mercado', 'startTime': 1794168000000, 'markets': []}]}}


PICK = {'partido': 'Platense vs Central Córdoba (santiago del Estero)', 'liga': 'Argentina',
        'inicio': '2026-11-08T20:00', 'resultado': 0, 'p_pin': 0.5}


def test_eventos_omite_lo_incompleto_y_elegir_valida_cuota_minima():
    ev = eventos_1x2(_resp())
    assert [e['id'] for e in ev] == ['1']
    sel, motivo = elegir(PICK, ev, D)
    assert sel == {'evento_id': '1', 'seleccion_id': 's1', 'cuota': 2.2} and motivo == 'ok'
    sel, motivo = elegir(PICK, eventos_1x2(_resp(cuota1=1.5)), D)
    assert sel is None and 'minima' in motivo and cuota_minima(0.5) > 1.5


def test_elegir_descarta_en_vivo_y_capturar_solo_guarda_no_empezados():
    assert elegir(PICK, eventos_1x2(_resp(vivo=True)), D) == (None, 'en vivo o suspendido')
    conn = sqlite3.connect(':memory:')
    conn.executescript(SQL_CUOTAS_FORWARD)
    assert capturar(conn, 't', eventos_1x2(_resp(vivo=True))) == 0
    assert capturar(conn, 't', eventos_1x2(_resp())) == 1

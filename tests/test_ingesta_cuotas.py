"""Tests de motor_cuotas: gate de actualizacion, extraccion 1X2 y request a The Odds API."""
import sqlite3
from datetime import datetime

import requests

from src.ingesta import motor_cuotas as mc


def test_puede_actualizar_cuotas_reglas():
    ahora = datetime(2026, 10, 12, 18, 0)
    assert mc._puede_actualizar_cuotas('2026-10-12 20:00', False, ahora) is True
    assert mc._puede_actualizar_cuotas('2026-10-12 17:59', False, ahora) is False  # en juego
    assert mc._puede_actualizar_cuotas('2026-10-12 18:00', False, ahora) is False  # kickoff == now
    assert mc._puede_actualizar_cuotas('2026-10-12 20:00', True, ahora) is False  # ya alertado
    assert mc._puede_actualizar_cuotas('', False, ahora) is False
    assert mc._puede_actualizar_cuotas('12/10/2026 20:00', False, ahora) is False


def test_tiene_alerta_con_y_sin_tabla(db):
    cur = db.cursor()
    assert mc._tiene_alerta(cur, 'P1') is False
    cur.execute("INSERT INTO log_alertas (id_alerta, partido, mercado, pick) "
                "VALUES ('P1_OU', 'x', 'O/U', 'Over')")
    assert mc._tiene_alerta(cur, 'P1') is True
    assert mc._tiene_alerta(cur, 'P2') is False
    sin_tabla = sqlite3.connect(':memory:')
    assert mc._tiene_alerta(sin_tabla.cursor(), 'P1') is False
    sin_tabla.close()


def _libro(key, home, draw, away):
    return {'key': key, 'markets': [{'key': 'h2h', 'outcomes': [
        {'name': 'Local', 'price': home}, {'name': 'Draw', 'price': draw}, {'name': 'Visita', 'price': away}]}]}


def test_extraer_1x2_prefiere_pinnacle_aunque_bet365_vaya_primero():
    books = [_libro('bet365', 2.0, 3.0, 4.0), _libro('pinnacle', 1.9, 3.4, 4.2)]
    assert mc.extraer_cuotas_sharp(books, 'Local', 'Visita') == (1.9, 3.4, 4.2, 0.0, 0.0)


def test_extraer_1x2_no_mezcla_libros_si_pinnacle_no_tiene_empate():
    pinnacle_sin_empate = {'key': 'pinnacle', 'markets': [{'key': 'h2h', 'outcomes': [
        {'name': 'Local', 'price': 1.9}, {'name': 'Visita', 'price': 4.2}]}]}
    books = [_libro('bet365', 2.0, 3.0, 4.0), pinnacle_sin_empate]
    assert mc.extraer_cuotas_sharp(books, 'Local', 'Visita') == (2.0, 3.0, 4.0, 0.0, 0.0)


def test_obtener_datos_api_key_fuera_de_url(monkeypatch):
    capturado = {}

    class Resp:
        status_code = 200

        def json(self):
            return []

    def fake_get(url, params=None, timeout=None):
        capturado['url'] = url
        capturado['params'] = params
        return Resp()

    monkeypatch.setattr(mc, 'API_KEYS', ['KEY123'])
    monkeypatch.setattr(mc.requests, 'get', fake_get)
    datos, idx = mc.obtener_datos_api('soccer_x')
    assert datos == [] and idx == 0
    assert 'KEY123' not in capturado['url']
    assert capturado['params']['apiKey'] == 'KEY123'
    assert capturado['params']['commenceTimeFrom'].endswith('Z')


def test_obtener_datos_api_error_red_imprime_solo_tipo(monkeypatch, capsys):
    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError(f"fallo en {url}?apiKey=KEY123")

    monkeypatch.setattr(mc, 'API_KEYS', ['KEY123'])
    monkeypatch.setattr(mc.requests, 'get', fake_get)
    datos, idx = mc.obtener_datos_api('soccer_x')
    salida = capsys.readouterr().out
    assert datos is None and idx == 0
    assert 'KEY123' not in salida
    assert 'ConnectionError' in salida


def test_main_sin_keys_falla(monkeypatch):
    import pytest
    import src.ingesta.motor_cuotas as mcu
    monkeypatch.setattr(mcu, 'API_KEYS', [])
    with pytest.raises(SystemExit) as e:
        mcu.main()
    assert e.value.code == 1


def test_obtener_datos_api_rota_dentro_del_rango_pedido(monkeypatch):
    usadas = []

    class Resp:
        def __init__(self, k):
            self.status_code = 429 if k == 'C1' else 200

        def json(self):
            return []

    def get(url, params, timeout):
        usadas.append(params['apiKey'])
        return Resp(params['apiKey'])
    monkeypatch.setattr(mc.requests, 'get', get)
    monkeypatch.setattr(mc, 'API_KEYS', ['P1', 'P2'])
    datos, idx = mc.obtener_datos_api('soccer_epl', 0, ['C1', 'C2'])
    assert usadas == ['C1', 'C2'] and idx == 1  # nunca toca las claves del pipeline

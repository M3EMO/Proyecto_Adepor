"""Tests de motor_cuotas_apifootball: los 3 precios 1X2 deben venir del mismo bookie."""
from src.ingesta import motor_cuotas_apifootball as af


def test_odds_fixture_no_mezcla_bookies(monkeypatch):
    # Pinnacle (id 4, primero en jerarquia) sin empate; Bet365 (id 8) completo
    respuesta = {'response': [{'bookmakers': [
        {'id': 4, 'bets': [{'id': 1, 'values': [
            {'value': 'Home', 'odd': '1.9'}, {'value': 'Away', 'odd': '4.2'}]}]},
        {'id': 8, 'bets': [{'id': 1, 'values': [
            {'value': 'Home', 'odd': '2.0'}, {'value': 'Draw', 'odd': '3.0'}, {'value': 'Away', 'odd': '4.0'}]}]},
    ]}]}
    monkeypatch.setattr(af, '_get', lambda url, max_retries=2: respuesta)
    c1, cx, c2, co, cu = af._obtener_odds_fixture(1)
    assert (c1, cx, c2) == (2.0, 3.0, 4.0)

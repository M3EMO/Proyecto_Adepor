import os
import sqlite3

import src.ingesta.motor_oddspapi as mo

AHORA = '2026-10-23T12:00:00'


def _fixture(fid, inicio, casas):
    def mercado(precios, activo=True):
        return {'101': {'outcomes': {o: {'players': {'0': {'price': p, 'active': activo}}}
                                     for o, p in zip(('101', '102', '103'), precios)}}}
    return {'fixtureId': fid, 'tournamentId': 155, 'startTime': inicio, 'participant1Id': 1, 'participant2Id': 2,
            'bookmakerOdds': {c: {'markets': mercado(*args)} for c, args in casas.items()}}


def test_filas_1x2_solo_futuros_con_tres_cuotas_activas():
    fixtures = [
        _fixture('f1', '2026-10-24T20:00:00.000Z', {'pinnacle': ([2.0, 3.4, 4.0],), 'bet365.bet.ar': ([2.1, 3.2, 3.8],)}),
        _fixture('f2', '2026-10-23T11:00:00.000Z', {'pinnacle': ([2.0, 3.4, 4.0],)}),        # ya empezo
        _fixture('f3', '2026-10-25T20:00:00.000Z', {'betano': ([2.0, 3.4, 4.0], False)}),    # suspendido
    ]
    filas = mo.filas_1x2(fixtures, 'TS', AHORA)
    assert [(f[1], f[6], f[7:]) for f in filas] == [('f1', 'pinnacle', (2.0, 3.4, 4.0)),
                                                   ('f1', 'bet365.bet.ar', (2.1, 3.2, 3.8))]


def test_main_pide_una_casa_y_cinco_torneos_y_captura_una_vez_por_dia(monkeypatch, tmp_path):
    db = str(tmp_path / 'f.db')
    pedidos = []

    class Resp:
        def __init__(self, casas):
            self.casas = casas

        def raise_for_status(self):
            pass

        def json(self):
            return [_fixture('f1', '2099-01-01T20:00:00.000Z',
                             {c: ([2.0, 3.4, 4.0],) for c in self.casas.split(',')})]

    def get(url, params, timeout):
        pedidos.append((params['bookmaker'], params['tournamentIds']))
        return Resp(params['bookmaker'])

    monkeypatch.setattr(mo, 'API_KEY_ODDSPAPI', 'K')
    monkeypatch.setattr(mo, 'DB_NAME', db)
    monkeypatch.setattr(mo, 'PAUSA', 0)
    monkeypatch.setattr(mo.requests, 'get', get)
    mo.main()
    assert len(pedidos) == 8 and all(len(t.split(',')) <= 5 for _, t in pedidos)  # 2 casas x 4 lotes
    for casa in mo.CASAS:
        assert sorted(int(t) for c, ts in pedidos if c == casa for t in ts.split(',')) == sorted(mo.TORNEOS)
    casas = {r[0] for r in sqlite3.connect(db).execute('SELECT casa FROM cuotas_forward')}
    assert casas == set(mo.CASAS)

    mo.main()  # segunda corrida del dia: no pide nada
    assert len(pedidos) == 8
    assert os.path.exists(db)


MARKETS = [
    {'marketId': 1010, 'marketType': 'totals', 'period': 'fulltime', 'playerProp': False, 'handicap': 2.5,
     'outcomes': [{'outcomeId': 1011, 'outcomeName': 'Under'}, {'outcomeId': 1010, 'outcomeName': 'Over'}]},
    {'marketId': 10781, 'marketType': 'totals-corners', 'period': 'fulltime', 'playerProp': False, 'handicap': 9.5,
     'outcomes': [{'outcomeId': 10781, 'outcomeName': 'Over'}, {'outcomeId': 10782, 'outcomeName': 'Under'}]},
    {'marketId': 2010, 'marketType': 'totals', 'period': 'firsthalf', 'playerProp': False, 'handicap': 0.5,
     'outcomes': [{'outcomeId': 2010, 'outcomeName': 'Over'}, {'outcomeId': 2011, 'outcomeName': 'Under'}]},
    {'marketId': 101, 'marketType': '1x2', 'period': 'fulltime', 'playerProp': False, 'handicap': 0.0, 'outcomes': []},
]


def test_mapa_totales_solo_partido_completo():
    assert mo.mapa_totales(MARKETS) == {'1010': ('goles', 2.5, '1010', '1011'),
                                       '10781': ('corners', 9.5, '10781', '10782')}


def test_filas_totales_una_fila_por_linea_con_over_y_under_activos():
    def mercado(o_over, o_under, precios, activo=True):
        return {'outcomes': {o: {'players': {'0': {'price': p, 'active': activo}}}
                             for o, p in zip((o_over, o_under), precios)}}
    fx = [{'fixtureId': 'f1', 'startTime': '2026-10-24T20:00:00.000Z',
           'bookmakerOdds': {'pinnacle': {'markets': {'1010': mercado('1010', '1011', (2.27, 1.684)),
                                                      '10781': mercado('10781', '10782', (1.9, 1.9), False),
                                                      '2010': mercado('2010', '2011', (1.5, 2.5))}}}},
          {'fixtureId': 'f2', 'startTime': '2026-10-23T11:00:00.000Z',  # ya empezo
           'bookmakerOdds': {'pinnacle': {'markets': {'1010': mercado('1010', '1011', (2.0, 1.8))}}}}]
    assert mo.filas_totales(fx, 'TS', AHORA, mo.mapa_totales(MARKETS)) == [
        ('TS', 'f1', 'pinnacle', 'goles', 2.5, 2.27, 1.684)]

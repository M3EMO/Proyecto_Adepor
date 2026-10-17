import pytest

from src.persistencia.yield_potencial import apuestas_potenciales, yield_potencial


def _fila(pais='Argentina', fecha='2026-01-01 15:00', ap1='', apou='',
          c1=2.0, cx=3.0, c2=3.5, co=1.8, cu=2.0):
    return {'pais': pais, 'fecha': fecha, 'apuesta_1x2': ap1, 'apuesta_ou': apou,
            'cuota_1': c1, 'cuota_x': cx, 'cuota_2': c2, 'cuota_o25': co, 'cuota_u25': cu}


def test_dos_ganadas_y_dos_perdidas_a_cuota_2_dan_yield_cero():
    filas = [_fila(ap1='[GANADA] LOCAL'), _fila(ap1='[GANADA] LOCAL'),
             _fila(ap1='[PERDIDA] LOCAL'), _fila(ap1='[PERDIDA] LOCAL')]
    g = yield_potencial(filas)['global']
    assert (g['n'], g['ganadas'], g['hit']) == (4, 2, 0.5)
    assert g['profit'] == pytest.approx(0.0)
    assert g['yield'] == pytest.approx(0.0)
    assert g['break_even'] == pytest.approx(0.5)


def test_break_even_es_media_de_inversas_y_yield_sale_de_cuotas():
    # Ganada a 4.0 (+3) y perdida a 2.0 (-1): profit 2, yield 1.0, break-even (0.25+0.5)/2
    filas = [_fila(ap1='[GANADA] LOCAL', c1=4.0), _fila(ap1='[PERDIDA] LOCAL', c1=2.0)]
    g = yield_potencial(filas)['global']
    assert g['profit'] == pytest.approx(2.0)
    assert g['yield'] == pytest.approx(1.0)
    assert g['break_even'] == pytest.approx(0.375)


def test_pick_sin_cuota_valida_o_no_liquidado_se_omite():
    filas = [
        _fila(ap1='[GANADA] LOCAL', c1=0.0),      # sin cuota
        _fila(ap1='[PERDIDA] VISITA', c2=1.0),    # cuota no > 1
        _fila(ap1='[APOSTAR] LOCAL', c1=2.0),     # no liquidado
        _fila(ap1='pendiente'),                   # sin prefijo
    ]
    assert yield_potencial(filas)['global']['n'] == 0
    assert apuestas_potenciales(filas) == []
    # Una valida al lado de las omitidas: solo ella cuenta.
    filas.append(_fila(ap1='[PERDIDA] EMPATE', cx=3.0))
    g = yield_potencial(filas)['global']
    assert (g['n'], g['profit']) == (1, -1.0)


def test_ambos_mercados_y_por_mercado_separados():
    filas = [_fila(ap1='[GANADA] EMPATE', cx=3.0),
             _fila(apou='[GANADA] OVER 2.5', co=1.8),
             _fila(apou='[PERDIDA] UNDER 2.5', cu=2.2)]
    r = yield_potencial(filas)
    assert r['por_mercado']['1X2']['n'] == 1
    ou = r['por_mercado']['OU']
    assert (ou['n'], ou['ganadas']) == (2, 1)
    assert ou['profit'] == pytest.approx(0.8 - 1.0)
    assert ou['yield'] == pytest.approx(-0.1)


def test_por_liga_agrupa_por_pais():
    filas = [_fila(pais='Argentina', ap1='[GANADA] LOCAL'),
             _fila(pais='Italia', ap1='[PERDIDA] LOCAL'),
             _fila(pais='Italia', apou='[GANADA] UNDER 2.5', cu=2.0)]
    por = yield_potencial(filas)['por_liga']
    assert set(por) == {'Argentina', 'Italia'}
    assert por['Argentina']['n'] == 1
    assert por['Italia']['n'] == 2
    assert por['Italia']['profit'] == pytest.approx(0.0)


def test_ic95_contiene_al_yield_y_es_determinista():
    # 10 ganadas a 2.0 y 6 perdidas: yield (10-6)/16 = 0.25
    filas = [_fila(ap1='[GANADA] LOCAL') for _ in range(10)] + \
            [_fila(ap1='[PERDIDA] LOCAL') for _ in range(6)]
    g1 = yield_potencial(filas)['global']
    g2 = yield_potencial(filas)['global']
    assert g1['yield'] == pytest.approx(0.25)
    assert g1['ci_low'] < g1['ci_high']
    assert g1['ci_low'] <= 0.25 <= g1['ci_high']
    assert (g1['ci_low'], g1['ci_high']) == (g2['ci_low'], g2['ci_high'])


def test_ic95_degenerado_cuando_todas_las_apuestas_son_iguales():
    filas = [_fila(ap1='[GANADA] LOCAL', c1=2.0) for _ in range(3)]
    g = yield_potencial(filas)['global']
    assert (g['ci_low'], g['ci_high']) == (pytest.approx(1.0), pytest.approx(1.0))


def test_sin_filas_devuelve_grupos_vacios():
    r = yield_potencial([])
    assert r['global']['n'] == 0
    assert r['global']['yield'] is None
    assert r['por_liga'] == {}

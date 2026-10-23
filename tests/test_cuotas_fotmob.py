"""Pruebas W1-W4 de docs/specs/13-estudios-forward.md (E1). Sin red."""
import sqlite3

import pytest

import src.ingesta.motor_cuotas_fotmob as mf
from src.ingesta.motor_oddspapi import SQL_CUOTAS_FORWARD

TS = '2026-10-23T12:00:00Z'


def odds(clave, precios):
    sel = [{'name': n, 'oddsDecimal': str(p)} for n, p in zip('1x2', precios)]
    return {'persistentKey': clave, 'odds': {'matchfactMarkets': [{'headerTranslationKey': 'who_will_win',
                                                                   'selections': sel}]}}


def test_w1_orientacion_invertida_no_empareja():
    partidos = [('p1', 'Augsburg', 'Union Berlin')]
    assert mf.emparejar(partidos, [(10, 'Augsburg', 'Union Berlin')]) == [('p1', 10)]
    assert mf.emparejar(partidos, [(11, 'Union Berlin', 'Augsburg')]) == []


def test_w1_nombres_distintos_no_empareja():
    assert mf.emparejar([('p1', 'Arsenal', 'Everton')], [(10, 'Zzzzzz', 'Qqqqqq')]) == []


def test_fila_1x2_lee_casa_y_precios():
    assert mf.fila_1x2(odds('1xBet_Argentina', [2.0, 3.4, 4.0])) == ('1xbet_argentina_fm', 2.0, 3.4, 4.0)


def test_w2_respuesta_nula_o_incompleta_no_da_fila():
    assert mf.fila_1x2(None) is None
    assert mf.fila_1x2(odds('X', [2.0, 0, 4.0])) is None
    assert mf.fila_1x2({'persistentKey': 'X', 'odds': {'matchfactMarkets': []}}) is None


@pytest.fixture
def db(tmp_path):
    c = sqlite3.connect(tmp_path / 'f.db')
    c.executescript(SQL_CUOTAS_FORWARD)
    return c


def pedir_falso(ruta):
    if 'ccode3=ARG' in ruta:
        return odds('1xBet_Argentina', [2.5, 3.4, 3.0])
    return None  # GBR sin cuotas


def test_w2_w3_captura_guarda_y_es_idempotente(db):
    partidos = [('p1', 'Augsburg', 'Union Berlin', 2.0, 3.5, 4.0)]
    cal = [(10, 'Augsburg', 'Union Berlin', '2026-10-24T14:30:00Z', 54)]
    n1 = mf.capturar(db, TS, partidos, cal, pedir_falso, pausa=0)
    n2 = mf.capturar(db, TS, partidos, cal, pedir_falso, pausa=0)
    filas = db.execute('SELECT fixture_id, casa FROM cuotas_forward ORDER BY casa').fetchall()
    assert (n1, n2) == (2, 2)  # una fila de la casa y una de Pinnacle; la repeticion no duplica
    assert filas == [('fm:10:p1', '1xbet_argentina_fm'), ('fm:10:p1', 'pinnacle_pb')]


def fila(db, ts, casa, c):
    db.execute('INSERT INTO cuotas_forward VALUES (?,?,?,?,?,?,?,?,?,?)', (ts, 'fm:10:p1', 54, 'x', 1, 2, casa, *c))


def test_w4_clv_usa_la_cuota_guardada_en_la_primera_captura_con_valor(db):
    # captura 1: Pinnacle 2.0/3.5/4.0 y la casa paga 2.5 al local (EV alto). Captura 2: la casa baja a 1.9.
    fila(db, 'T1', 'pinnacle_pb', (2.0, 3.5, 4.0))
    fila(db, 'T1', 'casa_fm', (2.5, 3.0, 3.0))
    fila(db, 'T2', 'pinnacle_pb', (2.0, 3.5, 4.0))
    fila(db, 'T2', 'casa_fm', (1.9, 3.0, 3.0))
    cierres = {'p1': (1.8, 3.8, 4.8)}
    r = mf.clv_apuestas(db, cierres, umbral=0.02)
    assert len(r) == 1 and r[0][0] == 'casa_fm'
    inv = [1 / x for x in (1.8, 3.8, 4.8)]
    p_cierre_local = inv[0] / sum(inv)
    assert r[0][1] == pytest.approx(2.5 * p_cierre_local - 1)

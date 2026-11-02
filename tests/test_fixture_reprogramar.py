import sqlite3
from datetime import datetime

from src.ingesta.motor_fixture import reprogramar


def _cursor(filas):
    c = sqlite3.connect(':memory:').cursor()
    c.execute('CREATE TABLE partidos_backtest (id_partido TEXT, fecha TEXT, local TEXT, visita TEXT, estado TEXT)')
    c.executemany('INSERT INTO partidos_backtest VALUES (?,?,?,?,?)', filas)
    return c


def test_postergado_actualiza_la_fecha_y_no_duplica():
    c = _cursor([('2026-10-28ab', '2026-10-28 15:00', 'A', 'B', 'Pendiente')])
    assert reprogramar(c, 'A', 'B', datetime(2026, 10, 30, 17, 0))
    assert c.execute('SELECT fecha FROM partidos_backtest').fetchall() == [('2026-10-30 17:00',)]


def test_liquidado_no_cambia_y_lejano_es_partido_nuevo():
    c = _cursor([('2026-10-28ab', '2026-10-28 15:00', 'A', 'B', 'Liquidado')])
    assert reprogramar(c, 'A', 'B', datetime(2026, 10, 29, 15, 0))
    assert c.execute('SELECT fecha FROM partidos_backtest').fetchone() == ('2026-10-28 15:00',)
    assert not reprogramar(c, 'A', 'B', datetime(2026, 11, 5, 15, 0))  # mas de 3 dias: se inserta aparte

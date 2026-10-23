"""Pruebas del informe de medicion (docs/specs/12-producto-deploy.md)."""
import sqlite3

import numpy as np

from scripts.ops import informe_medicion as im


def crear(db, filas):
    c = sqlite3.connect(db)
    c.execute("""create table partidos_backtest(estado text, goles_l int, goles_v int,
        apuesta_1x2 text, apuesta_ou text, stake_1x2 real, stake_ou real,
        cuota_1 real, cuota_x real, cuota_2 real, cuota_o25 real, cuota_u25 real,
        clv_pct_1x2 real, clv_pct_ou real, pin_1 real, pin_x real, pin_2 real)""")
    c.executemany("insert into partidos_backtest values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    c.commit()


def test_solo_cuenta_liquidadas_con_stake(tmp_path):
    db = tmp_path / 'a.db'
    crear(db, [
        ('Liquidado', 2, 0, '[GANADA] LOCAL', '', 100, 0, 2.5, 3, 3, 0, 0, 4.0, None, 2.4, 3.2, 3.5),
        ('Liquidado', 0, 1, '[PERDIDA] LOCAL', '', 100, 0, 2.0, 3, 3, 0, 0, -2.0, None, 2.0, 3.3, 4.0),
        ('Pendiente', None, None, '[APOSTAR] LOCAL', '', 100, 0, 2.0, 3, 3, 0, 0, None, None, 2.0, 3.3, 4.0),
        ('Liquidado', 1, 1, '', '', 0, 0, 2.0, 3, 3, 0, 0, None, None, 2.0, 3.3, 4.0),
    ])
    r = im.informe(db, n_boot=200)
    assert r['n'] == 2
    assert abs(r['yield'] - (150 - 100) / 200) < 1e-9  # +150 y -100 sobre 200 apostados
    assert abs(r['clv_medio'] - 1.0) < 1e-9
    assert r['concluyente'] is False  # N menor que 50


def test_calibracion_usa_todos_los_liquidados_con_pinnacle(tmp_path):
    db = tmp_path / 'a.db'
    crear(db, [('Liquidado', 1, 0, '', '', 0, 0, 0, 0, 0, 0, 0, None, None, 2.0, 3.5, 4.0),
               ('Liquidado', 0, 0, '', '', 0, 0, 0, 0, 0, 0, 0, None, None, 2.0, 3.5, 4.0)])
    r = im.informe(db, n_boot=50)
    assert r['n_calibracion'] == 2
    inv = 1 / np.array([2.0, 3.5, 4.0]); p = inv / inv.sum()
    assert abs(r['logloss_pinnacle'] - (-(np.log(p[0]) + np.log(p[1])) / 2)) < 1e-9


def test_sin_apuestas_no_falla(tmp_path):
    db = tmp_path / 'a.db'
    crear(db, [])
    r = im.informe(db, n_boot=50)
    assert r['n'] == 0 and r['yield'] is None and r['clv_medio'] is None

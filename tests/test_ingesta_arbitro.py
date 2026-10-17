"""Tests de motor_arbitro: conversion de fecha a ESPN y skip sin boxscore."""
import os

import pytest

from datetime import timedelta

from src.comun.tiempo import ahora_art, fecha_db_a_espn
from src.ingesta import motor_arbitro as ma


def test_fecha_db_a_espn_acepta_iso_y_ddmmyyyy():
    assert fecha_db_a_espn('2026-03-15') == '20260315'
    assert fecha_db_a_espn('15/03/2026') == '20260315'
    with pytest.raises(ValueError):
        fecha_db_a_espn('15-03-26')


FECHA = (ahora_art() - timedelta(days=2)).strftime('%Y-%m-%d')


def test_auditar_usa_fecha_iso_y_no_marca_si_sin_boxscore(db, monkeypatch):
    pais = next(iter(ma.MAPA_LIGAS_ESPN))
    db.execute("ALTER TABLE partidos_backtest ADD COLUMN arbitro TEXT")
    db.execute("ALTER TABLE partidos_backtest ADD COLUMN id_arbitro TEXT")
    db.execute("ALTER TABLE partidos_backtest ADD COLUMN auditoria TEXT")
    db.execute("CREATE TABLE arbitros_stats (id_arbitro TEXT PRIMARY KEY, nombre TEXT, partidos INTEGER, "
               "ema_faltas REAL, ema_amarillas REAL, ema_rojas REAL, ema_penales REAL)")
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado) "
               "VALUES ('P1', ?, ?, 'Equipo A', 'Equipo B', 'Liquidado')", (FECHA + ' 20:00', pais))
    db.commit()

    urls = []

    class Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, timeout=None):
        urls.append(url)
        if 'scoreboard' in url:
            return Resp({'events': [{'id': '99', 'competitions': [{'competitors': [
                {'team': {'displayName': 'Equipo A'}}, {'team': {'displayName': 'Equipo B'}}]}]}]})
        return Resp({'header': {'competitions': [{'officials': [{'fullName': 'Juan Perez'}]}]},
                     'boxscore': {'teams': []}})

    monkeypatch.setattr(ma.requests, 'get', fake_get)
    monkeypatch.setattr(ma, 'DB_NAME', os.environ['ADEPOR_DB'])
    ma.auditar_partidos()

    assert any(f"dates={FECHA.replace('-', '')}" in u for u in urls)
    assert db.execute("SELECT auditoria FROM partidos_backtest WHERE id_partido='P1'").fetchone()[0] is None
    assert db.execute("SELECT COUNT(*) FROM arbitros_stats").fetchone()[0] == 0


def test_no_reintenta_partidos_fuera_de_ventana(db, monkeypatch):
    db.execute("ALTER TABLE partidos_backtest ADD COLUMN auditoria TEXT")
    viejo = (ahora_art() - timedelta(days=ma.VENTANA_DIAS + 5)).strftime('%Y-%m-%d 20:00')
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado) "
               "VALUES ('V', ?, ?, 'A', 'B', 'Liquidado')", (viejo, next(iter(ma.MAPA_LIGAS_ESPN))))
    db.commit()
    urls = []
    monkeypatch.setattr(ma.requests, 'get', lambda url, timeout=None: urls.append(url))
    monkeypatch.setattr(ma, 'DB_NAME', os.environ['ADEPOR_DB'])
    ma.auditar_partidos()
    assert urls == []

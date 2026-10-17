"""motor_adaptativo: idempotencia por id_partido, commit por partido, NULL guard y dry run
del CLI de online_sgd_v12."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import motor_adaptativo as ma
from scripts import online_sgd_v12 as sgd
from src.comun.config_sistema import DB_NAME

ROOT = Path(__file__).resolve().parent.parent
EPOCH = "1970-01-01 00:00:00"


def _setup(db):
    """Columnas stats, pesos V12 (liga y global) y N_acum por encima del warmup."""
    for col in ("sot_l", "shots_l", "corners_l", "sot_v", "shots_v", "corners_v"):
        db.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col} REAL")
    payload = json.dumps({'W': [[0.0] * 13] * 3, 'mean': [0.0] * 13, 'std': [1.0] * 13})
    for scope in ('Argentina', 'global'):
        db.execute("""INSERT INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('lr_v12_weights', ?, NULL, ?, 'json', 'test', 0)""", (scope, payload))
        db.execute("""INSERT INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('online_sgd_n_partidos', ?, ?, NULL, 'real', 'test', 0)""",
                   (scope, sgd.WARMUP_N))
    db.commit()


def _partido(db, id_, fecha, estado='Liquidado'):
    db.execute("""INSERT INTO partidos_backtest
        (id_partido, fecha, pais, local, visita, goles_l, goles_v, estado,
         sot_l, shots_l, corners_l, sot_v, shots_v, corners_v)
        VALUES (?, ?, 'Argentina', 'Boca', 'River', 2, 1, ?, 4, 10, 5, 3, 8, 4)""",
               (id_, fecha, estado))
    db.commit()


def _procesados(db):
    return {r[0] for r in db.execute("SELECT id_partido FROM motor_adaptativo_procesados")}


@pytest.fixture
def feats(monkeypatch):
    """Features fijas: evita tablas EMA. El test cubre el watermark, no las features."""
    monkeypatch.setattr(ma, 'features_v12_para_partido', lambda *a, **k: [1.0] * 13)


def test_no_reaplica_y_procesa_tardios(db, feats):
    _setup(db)
    _partido(db, 'A', '2026-03-01 15:00')
    _partido(db, 'B', '2026-03-01 15:00')   # mismo minuto de kickoff
    _partido(db, 'C', '2026-03-02 18:00')
    conn = sqlite3.connect(DB_NAME)
    try:
        ma.init_procesados(conn, EPOCH)
        n_sgd, _, _, _ = ma.procesar_partidos_nuevos(conn, EPOCH)
        assert n_sgd == 3
        assert _procesados(db) == {'A', 'B', 'C'}

        # Segunda corrida: nada que hacer
        n_sgd, _, _, _ = ma.procesar_partidos_nuevos(conn, EPOCH)
        assert n_sgd == 0

        # Dato tardio con fecha anterior al watermark: se procesa igual
        _partido(db, 'D', '2026-02-01 10:00')
        n_sgd, _, _, _ = ma.procesar_partidos_nuevos(conn, EPOCH)
        assert n_sgd == 1
        assert _procesados(db) == {'A', 'B', 'C', 'D'}
    finally:
        conn.close()


def test_crash_no_reaplica_pasos_commiteados(db, feats, monkeypatch):
    _setup(db)
    for id_, fecha in (('A', '2026-03-01 15:00'), ('B', '2026-03-02 15:00'),
                       ('C', '2026-03-03 15:00')):
        _partido(db, id_, fecha)

    real_step = ma.sgd_step_partido
    llamadas = []

    def falla_en_quinta(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 5:   # A (liga+global) y B commiteados; C a medias
            raise RuntimeError("crash simulado")
        return real_step(*a, **k)

    conn = sqlite3.connect(DB_NAME)
    try:
        ma.init_procesados(conn, EPOCH)
        monkeypatch.setattr(ma, 'sgd_step_partido', falla_en_quinta)
        with pytest.raises(RuntimeError):
            ma.procesar_partidos_nuevos(conn, EPOCH)
        assert _procesados(db) == {'A', 'B'}

        # Reintento sin falla: solo C, con sus dos pasos SGD
        monkeypatch.setattr(ma, 'sgd_step_partido', real_step)
        n_sgd, _, _, _ = ma.procesar_partidos_nuevos(conn, EPOCH)
        assert n_sgd == 1
        assert _procesados(db) == {'A', 'B', 'C'}
    finally:
        conn.close()


def test_migracion_marca_partidos_previos_al_watermark(db, feats):
    _setup(db)
    _partido(db, 'VIEJO', '2026-02-15 15:00')
    _partido(db, 'NUEVO', '2026-03-05 15:00')
    ma.set_last_run(db, '2026-03-01 15:00')
    db.commit()
    conn = sqlite3.connect(DB_NAME)
    try:
        ma.init_procesados(conn, '2026-03-01 15:00')
        assert _procesados(db) == {'VIEJO'}
        n_sgd, _, _, _ = ma.procesar_partidos_nuevos(conn, '2026-03-01 15:00')
        assert n_sgd == 1
        assert _procesados(db) == {'VIEJO', 'NUEVO'}
    finally:
        conn.close()


def test_migracion_interrumpida_siembra_igual(db, feats):
    """Tabla creada pero vacia (crash entre CREATE y siembra): la siembra se repite."""
    _setup(db)
    _partido(db, 'VIEJO', '2026-02-15 15:00')
    db.execute("CREATE TABLE motor_adaptativo_procesados (id_partido TEXT PRIMARY KEY, ts TEXT)")
    db.commit()
    conn = sqlite3.connect(DB_NAME)
    try:
        ma.init_procesados(conn, '2026-03-01 15:00')
        assert _procesados(db) == {'VIEJO'}
    finally:
        conn.close()


@pytest.mark.parametrize("ht_row, at_row", [
    ((1.0, None, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0)),   # NULL en el local
    ((1.0, 1.0, 1.0, 1.0), (1.0, 1.0, 1.0, None)),   # NULL en el visitante
])
def test_features_con_null_devuelven_none(db, ht_row, at_row):
    db.execute("""CREATE TABLE historial_equipos_v6_shadow (equipo_norm TEXT PRIMARY KEY,
        ema_xg_v6_favor_home REAL, ema_xg_v6_contra_home REAL,
        ema_xg_v6_favor_away REAL, ema_xg_v6_contra_away REAL)""")
    db.execute("INSERT INTO historial_equipos_v6_shadow VALUES ('boca', ?, ?, ?, ?)", ht_row)
    db.execute("INSERT INTO historial_equipos_v6_shadow VALUES ('river', ?, ?, ?, ?)", at_row)
    db.commit()
    assert ma.features_v12_para_partido(db, 'Argentina', 'boca', 'river', '2026-03-01') is None


def test_cli_sgd_dry_run_no_escribe(db):
    _setup(db)
    consulta = ("SELECT clave, scope, valor_real, valor_texto FROM config_motor_valores "
                "ORDER BY clave, scope")
    antes = db.execute(consulta).fetchall()

    res = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'online_sgd_v12.py'),
         '--liga', 'Argentina', '--partidos', '20'],
        capture_output=True, text=True, timeout=120, env=os.environ.copy(),
    )

    assert res.returncode == 0, res.stderr
    assert 'DRY RUN' in res.stdout
    assert db.execute(consulta).fetchall() == antes
    tablas = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'online_sgd_log' not in tablas

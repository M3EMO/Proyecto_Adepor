"""Pruebas del chequeo de salud (docs/specs/12-producto-deploy.md)."""
import os
import sqlite3
import time

from scripts.ops import salud

AHORA = 1_800_000_000.0


def tocar(path, edad_s):
    path.write_text('x')
    os.utime(path, (AHORA - edad_s, AHORA - edad_s))


def test_log_reciente_ok_y_viejo(tmp_path):
    tocar(tmp_path / 'pipeline_20261022.log', 3600)
    assert salud.log_reciente(tmp_path, 'pipeline_*.log', 26 * 3600, AHORA)[0]
    tocar(tmp_path / 'pipeline_20261022.log', 27 * 3600)
    assert not salud.log_reciente(tmp_path, 'pipeline_*.log', 26 * 3600, AHORA)[0]


def test_log_reciente_sin_archivos_falla(tmp_path):
    assert not salud.log_reciente(tmp_path, 'pipeline_*.log', 3600, AHORA)[0]


def test_snapshot_viejo_falla(tmp_path):
    tocar(tmp_path / 'fondo_quant_1.db', 8 * 86400)
    assert not salud.log_reciente(tmp_path, 'fondo_quant_*.db', 7 * 86400, AHORA)[0]


def test_integridad_ok(tmp_path):
    db = tmp_path / 'a.db'
    sqlite3.connect(db).execute('create table t(x)').connection.commit()
    assert salud.integridad(db)[0]


def test_integridad_archivo_corrupto_falla(tmp_path):
    db = tmp_path / 'a.db'
    db.write_bytes(b'esto no es sqlite' * 100)
    assert not salud.integridad(db)[0]


def crear_partidos(db, filas):
    c = sqlite3.connect(db)
    c.execute("create table partidos_backtest(estado text, fecha text, pin_1 real, cuota_1 real, pais text)")
    c.executemany("insert into partidos_backtest values (?, ?, ?, 2.0, ?)", filas)
    c.commit()


def en_horas(h):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + h * 3600))


def test_cuotas_pinnacle_faltantes(tmp_path):
    ok = [('Pendiente', en_horas(5), 2.0, 'X')] * 8 + [('Pendiente', en_horas(5), None, 'X')] * 2  # 20% exacto: pasa
    crear_partidos(tmp_path / 'a.db', ok)
    assert salud.cuotas_pinnacle(tmp_path / 'a.db', 0.2)[0]
    crear_partidos(tmp_path / 'b.db', ok + [('Pendiente', en_horas(5), None, 'X')])  # 3 de 11 = 27%
    assert not salud.cuotas_pinnacle(tmp_path / 'b.db', 0.2)[0]


def test_cuotas_ignora_partidos_lejanos_y_liquidados(tmp_path):
    crear_partidos(tmp_path / 'a.db', [('Pendiente', en_horas(200), None, 'X'), ('Liquidado', en_horas(-5), None, 'X')])
    assert salud.cuotas_pinnacle(tmp_path / 'a.db', 0.2)[0]


def test_ligas_sin_cuotas_es_informativo(tmp_path):
    db = tmp_path / 'a.db'
    crear_partidos(db, [('Pendiente', en_horas(5), 2.0, 'Con')])
    sqlite3.connect(db).execute("insert into partidos_backtest values ('Pendiente', ?, NULL, 0, 'Sin')",
                                (en_horas(5),)).connection.commit()
    ok, msg = salud.ligas_sin_cuotas(db)
    assert ok and 'Sin' in msg and 'Con' not in msg


def test_main_codigo_de_salida(tmp_path, monkeypatch):
    monkeypatch.setattr(salud, 'chequeos', lambda: [(True, 'a'), (False, 'b')])
    assert salud.main() == 1
    monkeypatch.setattr(salud, 'chequeos', lambda: [(True, 'a')])
    assert salud.main() == 0


def test_main_escribe_estado_y_leer_estado_lo_devuelve(tmp_path, monkeypatch):
    estado = tmp_path / 'salud_estado.json'
    monkeypatch.setattr(salud, 'ESTADO', estado)
    monkeypatch.setattr(salud, 'chequeos', lambda: [(True, 'a'), (False, 'b falla')])
    salud.main()
    ok, fallas = salud.leer_estado(estado, time.time())
    assert not ok and fallas == ['b falla']


def test_leer_estado_ausente_o_viejo_es_none(tmp_path):
    assert salud.leer_estado(tmp_path / 'no.json', AHORA) is None
    estado = tmp_path / 'e.json'
    tocar(estado, 4 * 3600)
    estado.write_text('{"ok": false, "fallas": ["x"]}')
    os.utime(estado, (AHORA - 4 * 3600, AHORA - 4 * 3600))
    assert salud.leer_estado(estado, AHORA) is None  # el cron de salud no corre hace 4 h: no es confiable


def test_leer_estado_corrupto_es_none(tmp_path):
    estado = tmp_path / 'e.json'
    estado.write_text('no es json')
    assert salud.leer_estado(estado, time.time()) is None

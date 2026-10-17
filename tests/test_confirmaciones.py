from datetime import timedelta

from src.comun.tiempo import ahora_art

import pytest

import src.nucleo.motor_calculadora as mc
from src.persistencia.confirmaciones import confirmar_apuesta, ids_confirmados


def _pick(db, id_p, ap='[APOSTAR] LOCAL'):
    fecha = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, cuota_1, "
               "cuota_x, cuota_2, apuesta_1x2, estado) VALUES (?, ?, 'Argentina', 'River Plate', "
               "'Boca Juniors', 2.0, 3.4, 3.8, ?, 'Calculado')", (id_p, fecha, ap))
    db.commit()


def test_confirmar_guarda_cuota_y_stake_reales(db):
    _pick(db, 'm1')
    assert confirmar_apuesta(db, 'm1', '1X2', 2.15, 300.0) == 'LOCAL'
    assert db.execute("SELECT cuota_1, stake_1x2 FROM partidos_backtest").fetchone() == (2.15, 300.0)
    assert ids_confirmados(db.cursor()) == {'m1'}


def test_no_confirma_pick_inexistente_ni_valores_invalidos(db):
    _pick(db, 'm1', ap='[PASAR] Sin Valor')
    with pytest.raises(ValueError):
        confirmar_apuesta(db, 'm1', '1X2', 2.0, 100.0)
    _pick(db, 'm2')
    with pytest.raises(ValueError):
        confirmar_apuesta(db, 'm2', '1X2', 1.0, 100.0)


def test_partido_confirmado_queda_congelado(db):
    _pick(db, 'm1')
    confirmar_apuesta(db, 'm1', '1X2', 2.15, 300.0)
    mc.main()
    assert db.execute("SELECT apuesta_1x2, stake_1x2, cuota_1 FROM partidos_backtest").fetchone() \
        == ('[APOSTAR] LOCAL', 300.0, 2.15)


def test_no_confirma_partido_empezado(db):
    pasado = (ahora_art() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, cuota_1, "
               "apuesta_1x2, estado) VALUES ('ya', ?, 'Argentina', 'A', 'B', 2.0, "
               "'[APOSTAR] LOCAL', 'Calculado')", (pasado,))
    db.commit()
    with pytest.raises(ValueError, match='empezo'):
        confirmar_apuesta(db, 'ya', '1X2', 2.0, 100.0)


def test_picks_vivos_incluye_pretest_y_excluye_empezados():
    import dashboard
    fut = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    pas = (ahora_art() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')

    def fila(id_p, fecha, stake):
        return [id_p, fecha, 'A', 'B', 'Argentina', 0.55, 0.25, 0.20, 0.5, 0.5,
                '[APOSTAR] LOCAL', '', stake, 0.0, 2.0, 3.4, 4.0, 1.9, 1.9,
                'Calculado', None, None, 0.1, 'NO', '', 0.0]
    vivos = dashboard.picks_vivos([fila('pre', fut, 0.0), fila('emp', pas, 50.0)])
    assert [p['id'] for p in vivos] == ['pre'] and vivos[0]['stake'] == 0.0

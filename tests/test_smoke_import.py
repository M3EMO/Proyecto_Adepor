def test_motor_calculadora_importa_con_db_vacia():
    import src.nucleo.motor_calculadora as m
    assert m.FLOOR_PROB_MIN == 0.33


def test_get_param_no_crea_db_inexistente(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    import src.comun.config_motor as cm
    falta = tmp_path / 'no_existe.db'
    monkeypatch.setattr(cm, '_DB_PATH', str(falta))
    with pytest.raises(sqlite3.OperationalError):
        cm.get_param('x', default=1)
    assert not falta.exists()

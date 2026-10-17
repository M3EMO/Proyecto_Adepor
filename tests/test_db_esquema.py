import os
import sqlite3

import pytest

from scripts.db import esquema


def test_exportar_y_crear_reproducen_el_esquema(db, tmp_path):
    db.execute("CREATE VIEW v_liq AS SELECT * FROM partidos_backtest WHERE estado='Liquidado'")
    db.execute("CREATE INDEX idx_pb_fecha ON partidos_backtest(fecha)")
    db.commit()
    sql = tmp_path / 'schema.sql'
    assert esquema.exportar(os.environ['ADEPOR_DB'], sql) > 0

    nueva = tmp_path / 'nueva.db'
    esquema.crear(str(nueva), sql)
    objetos = lambda c: sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    assert objetos(sqlite3.connect(nueva)) == objetos(db)

    with pytest.raises(FileExistsError):
        esquema.crear(str(nueva), sql)

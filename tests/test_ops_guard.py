"""adepor_guard: el snapshot debe incluir commits que aun estan en el -wal (modo WAL)."""
import json
import os
import sqlite3

import adepor_guard as ag


def test_snapshot_incluye_commits_en_wal(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # snapshots/ se crea en el tmp, no en el repo
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado)
                  VALUES ('WAL1', '2026-01-01', 'Argentina', 'A', 'B', 'Liquidado')""")
    db.commit()
    # Precondicion: el commit vive en el -wal y no se checkpointeo a la DB principal
    wal = os.environ["ADEPOR_DB"] + "-wal"
    assert os.path.exists(wal) and os.path.getsize(wal) > 0

    json_path = ag.cmd_snapshot()

    with open(json_path, encoding="utf-8") as f:
        backup = json.load(f)["_meta"]["db_backup"]
    con = sqlite3.connect(backup)
    try:
        n = con.execute("SELECT COUNT(*) FROM partidos_backtest WHERE id_partido='WAL1'").fetchone()[0]
    finally:
        con.close()
    assert n == 1

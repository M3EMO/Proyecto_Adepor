"""El hook SOFA toma pendientes de lo que el pipeline liquida (no de un backfill manual)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import scrape_sofa_post_liquidacion as hook  # noqa: E402


def test_pendientes_salen_de_partidos_backtest(db):
    hook.crear_schema(db)
    hoy = date.today().isoformat()
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, goles_l, "
               "goles_v, estado) VALUES ('m1', ?, 'Argentina', 'River Plate', 'Boca Juniors', 2, 1, "
               "'Liquidado')", (hoy + ' 21:00',))
    db.commit()
    assert [r[0] for r in hook.cargar_pendientes(db, dias=7)] == ['m1']

    db.execute("INSERT INTO sofascore_match_features (sofa_event_id, liga, temp, fecha, ht, at, "
               "ingest_ts) VALUES (1, 'Argentina', 2026, ?, 'River Plate', 'Boca Juniors', 'x')", (hoy,))
    db.commit()
    assert hook.cargar_pendientes(db, dias=7) == []

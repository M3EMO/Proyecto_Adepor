"""calibrar_rho: un fallback (descarga caida, liga sin datos) no debe pisar el rho
MLE ya guardado en ligas_stats."""
import random
import sqlite3

import pytest

import src.nucleo.calibrar_rho as cr


def _partidos_sinteticos(n, seed=7):
    rnd = random.Random(seed)
    equipos = [f"E{i}" for i in range(10)]
    out = []
    for _ in range(n):
        ht, at = rnd.sample(equipos, 2)
        out.append((ht, at, rnd.randint(0, 3), rnd.randint(0, 3)))
    return out


def _rho_db(liga):
    con = sqlite3.connect(cr.DB_NAME)
    try:
        row = con.execute("SELECT rho_calculado FROM ligas_stats WHERE liga=?", (liga,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


@pytest.mark.parametrize("liga, partidos", [
    ("Inglaterra", []),                              # descarga caida: sin partidos
    ("Argentina", _partidos_sinteticos(100)),        # LATAM exige N>=150: fallback
])
def test_fallback_no_pisa_rho_calibrado(db, liga, partidos):
    db.execute("INSERT INTO ligas_stats (liga, rho_calculado) VALUES (?, -0.05)", (liga,))
    db.commit()

    resultados, fallbacks = {}, {}
    cr._procesar_liga(liga, partidos, resultados, fallbacks)

    assert resultados == {}
    assert fallbacks == {liga: cr.RHO_FALLBACK}
    cr.actualizar_rho_en_db(resultados)
    assert _rho_db(liga) == -0.05


def test_fit_mle_si_se_escribe(db):
    db.execute("INSERT INTO ligas_stats (liga, rho_calculado) VALUES ('Inglaterra', -0.05)")
    db.commit()

    resultados, fallbacks = {}, {}
    cr._procesar_liga("Inglaterra", _partidos_sinteticos(200), resultados, fallbacks)

    assert "Inglaterra" in resultados
    assert fallbacks == {}
    cr.actualizar_rho_en_db(resultados)
    assert _rho_db("Inglaterra") == resultados["Inglaterra"]

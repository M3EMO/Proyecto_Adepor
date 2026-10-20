from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard

RAIZ = Path(__file__).resolve().parent.parent


def _sembrar(db):
    """Tres partidos: m1 liquidado con stake, m2 liquidado pretest (stake 0), m3 vivo."""
    cols = ("id_partido, fecha, pais, local, visita, cuota_1, cuota_x, cuota_2, cuota_o25, "
            "cuota_u25, apuesta_1x2, apuesta_ou, stake_1x2, stake_ou, goles_l, goles_v, estado")
    marcas = ", ".join("?" * 17)
    db.executemany(f"INSERT INTO partidos_backtest ({cols}) VALUES ({marcas})", [
        ("m1", "2026-03-01 15:00", "Argentina", "River", "Boca",
         2.0, 3.4, 3.8, 1.8, 1.9,
         "[GANADA] LOCAL", "[PERDIDA] UNDER 2.5", 100, 50, 2, 1, "Liquidado"),
        ("m2", "2026-03-05 15:00", "Italia", "Juve", "Roma",
         2.5, 3.2, 2.9, 2.0, 1.8,
         "[PERDIDA] VISITA", "[PERDIDA] OVER 2.5", 0, 0, 1, 1, "Liquidado"),
        ("m3", "2099-01-01 15:00", "Italia", "Lazio", "Milan",
         2.2, 3.2, 3.4, 2.0, 1.9,
         "[APOSTAR] EMPATE", "[APOSTAR] OVER 2.5", 80, 40, None, None, "Calculado"),
    ])
    db.execute("INSERT INTO configuracion (clave, valor) VALUES ('bankroll', '100000')")
    db.commit()


def test_cargar_todo_con_filas_de_prueba(db):
    _sembrar(db)
    b = dashboard.cargar_todo(db)

    # Dinero real: solo m1 (1X2 +100, O/U -50). m2 es pretest con stake 0.
    t = b["metricas"]["total"]
    assert (t["n"], t["pl"]) == (2, 50.0)
    assert b["equity"]["equity"].iloc[-1] == pytest.approx(100050.0)
    assert sum(a["pl"] for a in dashboard.apuestas_reales(_datos(db))) == pytest.approx(50.0)

    # Yield potencial: incluye pretest. Cuatro apuestas: +1, -1, -1, -1.
    g = b["yield"]["global"]
    assert (g["n"], g["ganadas"], g["profit"]) == (4, 1, -2.0)
    assert g["yield"] == pytest.approx(-0.5)
    assert set(b["yield"]["por_liga"]) == {"Argentina", "Italia"}

    # Historial: P/L neto de m1 = 100 - 50.
    hist = b["historial"].set_index("Partido")
    assert hist.loc["River vs Boca", "P/L neto"] == pytest.approx(50.0)


def _datos(db):
    return dashboard.cargar_partidos(db.cursor())


def test_app_renderiza_las_cuatro_pestanas(db):
    _sembrar(db)
    st.cache_data.clear()  # la app cachea 60 s: evitar datos de otra prueba
    at = AppTest.from_file(str(RAIZ / "dashboard.py"), default_timeout=120).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == dashboard.TABS


def test_app_sin_liquidados_no_falla(db):
    """Base recien creada: tablas vacias no deben romper ninguna pestana."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("../dashboard.py", default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]

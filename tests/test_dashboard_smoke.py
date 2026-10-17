from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard
from src.persistencia.confirmaciones import confirmar_apuesta

RAIZ = Path(__file__).resolve().parent.parent


def _sembrar(db):
    """Tres partidos: m1 liquidado con stake, m2 liquidado pretest (stake 0), m3 vivo."""
    db.execute("ALTER TABLE partidos_backtest ADD COLUMN auditoria TEXT")
    cols = ("id_partido, fecha, pais, local, visita, cuota_1, cuota_x, cuota_2, cuota_o25, "
            "cuota_u25, prob_1, prob_x, prob_2, prob_o25, prob_u25, apuesta_1x2, apuesta_ou, "
            "stake_1x2, stake_ou, goles_l, goles_v, estado, apuesta_shadow_1x2, "
            "stake_shadow_1x2, incertidumbre")
    marcas = ", ".join("?" * 25)
    db.executemany(f"INSERT INTO partidos_backtest ({cols}) VALUES ({marcas})", [
        ("m1", "2026-03-01 15:00", "Argentina", "River", "Boca",
         2.0, 3.4, 3.8, 1.8, 1.9, 0.55, 0.25, 0.20, 0.52, 0.48,
         "[GANADA] LOCAL", "[PERDIDA] UNDER 2.5", 100, 50, 2, 1, "Liquidado",
         "[PERDIDA] VISITA", 30, 1.1),
        ("m2", "2026-03-05 15:00", "Italia", "Juve", "Roma",
         2.5, 3.2, 2.9, 2.0, 1.8, 0.40, 0.30, 0.30, 0.55, 0.45,
         "[PERDIDA] VISITA", "[PERDIDA] OVER 2.5", 0, 0, 1, 1, "Liquidado", None, None, 1.0),
        ("m3", "2099-01-01 15:00", "Italia", "Lazio", "Milan",
         2.2, 3.2, 3.4, 2.0, 1.9, 0.40, 0.33, 0.27, 0.55, 0.45,
         "[APOSTAR] EMPATE", "[APOSTAR] OVER 2.5", 80, 40, None, None, "Calculado",
         "[APOSTAR] LOCAL", 30, 1.2),
    ])
    db.execute("INSERT INTO configuracion (clave, valor) VALUES ('bankroll', '100000')")
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) "
               "VALUES ('apuestas_live', 'Argentina', 'TRUE', 'bool')")
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

    # Picks vivos: 1X2 y O/U de m3, ambos sin confirmar.
    assert [(p["id"], p["mercado"], p["confirmada"]) for p in b["picks"]] == \
        [("m3", "1X2", False), ("m3", "OU", False)]

    # Historial: P/L neto de m1 = 100 - 50.
    hist = b["historial"].set_index("Partido")
    assert hist.loc["River vs Boca", "P/L neto"] == pytest.approx(50.0)

    # Sombra: Op1 +100 vs Op4 -30 en m1.
    assert (b["sombra"]["op1"]["pl"], b["sombra"]["op4"]["pl"]) == (100.0, -30.0)

    # Resumen por liga: Argentina con 2 apuestas reales, Italia sin apuestas reales.
    res = b["resumen"].set_index("Liga")
    assert (res.loc["Argentina", "Apuestas"], res.loc["Argentina", "Estado"]) == (2, "LIVE")
    assert res.loc["Italia", "Apuestas"] == 0

    # Si hubiera: conteo real in-sample, 4 picks reales y 1 ganada.
    assert b["si_resumen"]["kpi"]["n_real"] == 4
    assert b["si_resumen"]["kpi"]["g_real"] == 1


def _datos(db):
    from src.persistencia.motor_sincronizador import _cargar_partidos
    return _cargar_partidos(db.cursor())


def test_confirmar_marca_solo_el_mercado_confirmado(db):
    _sembrar(db)
    confirmar_apuesta(db, "m3", "1X2", 3.3, 80.0)
    picks = dashboard.cargar_todo(db)["picks"]
    estado = {(p["id"], p["mercado"]): p for p in picks}
    assert estado[("m3", "1X2")]["confirmada"] is True
    assert estado[("m3", "1X2")]["cuota"] == pytest.approx(3.3)
    assert estado[("m3", "OU")]["confirmada"] is False


def test_app_renderiza_las_siete_pestanas(db):
    _sembrar(db)
    st.cache_data.clear()  # la app cachea 60 s: evitar datos de otra prueba
    at = AppTest.from_file(str(RAIZ / "dashboard.py"), default_timeout=120).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == dashboard.TABS


def test_formulario_confirma_desde_la_app(db):
    _sembrar(db)
    st.cache_data.clear()
    at = AppTest.from_file(str(RAIZ / "dashboard.py"), default_timeout=120).run()
    at.number_input[0].set_value(3.3)   # cuota tomada 1X2 de m3
    at.number_input[1].set_value(80.0)  # stake
    at.button[0].click().run()
    assert not at.exception
    assert "Confirmada" in at.success[0].value
    assert db.execute("SELECT cuota_x, stake_1x2 FROM partidos_backtest "
                      "WHERE id_partido = 'm3'").fetchone() == (3.3, 80.0)


def test_app_sin_liquidados_no_falla(db):
    """Base recien creada: tablas vacias no deben romper ninguna pestana."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("../dashboard.py", default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]

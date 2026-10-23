from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard
from src.persistencia.confirmaciones import confirmar_apuesta

RAIZ = Path(__file__).resolve().parent.parent
PIN_PRE = ("pin_1", "pin_x", "pin_2", "pin_o25", "pin_u25")
PIN_CIERRE = ("pin_cierre_1", "pin_cierre_x", "pin_cierre_2", "pin_cierre_o25", "pin_cierre_u25")
PRE = (2.2, 3.4, 3.6, 1.8, 2.0)
CIERRE = (2.0, 3.5, 4.0, 1.9, 1.9)


def _sembrar(db, con_pin=True):
    """f1 futuro con Pinnacle, f2 futuro sin Pinnacle, f3 pasado y f4 liquidado (ambos con Pinnacle)."""
    db.executemany("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado, "
                   "goles_l, goles_v) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("f1", "2099-01-01 15:00", "Argentina", "River", "Boca", "Pendiente", None, None),
        ("f2", "2099-01-02 15:00", "Italia", "Juve", "Roma", "Pendiente", None, None),
        ("f3", "2020-01-01 15:00", "Italia", "Lazio", "Milan", "Pendiente", None, None),
        ("f4", "2099-01-03 15:00", "Italia", "Inter", "Napoli", "Liquidado", 2, 1),
    ])
    if con_pin:
        for c in PIN_PRE + PIN_CIERRE:
            db.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {c} REAL")
        db.executemany("UPDATE partidos_backtest SET pin_1=?, pin_x=?, pin_2=?, pin_o25=?, pin_u25=?, "
                       "pin_cierre_1=?, pin_cierre_x=?, pin_cierre_2=?, pin_cierre_o25=?, "
                       "pin_cierre_u25=? WHERE id_partido=?",
                       [(*PRE, *CIERRE, i) for i in ("f1", "f3", "f4")])
    db.commit()


def test_valor_v2_vivos_solo_futuros_con_pinnacle(db):
    _sembrar(db)
    filas = dashboard.valor_v2_vivos(db)
    assert {(r["id"], r["mercado"], r["pick"]) for r in filas} == {
        ("f1", "1X2", "LOCAL"), ("f1", "1X2", "EMPATE"), ("f1", "1X2", "VISITA"),
        ("f1", "OU", "OVER 2.5"), ("f1", "OU", "UNDER 2.5")}

    local = next(r for r in filas if r["pick"] == "LOCAL")
    p = (1 / 2.2) / (1 / 2.2 + 1 / 3.4 + 1 / 3.6)
    assert local["prob_justa"] == pytest.approx(p)
    assert local["cuota_minima"] == pytest.approx(1.02 / p)
    assert local["partido"] == "River vs Boca"
    assert local["confirmada"] is False
    suma_1x2 = sum(r["prob_justa"] for r in filas if r["mercado"] == "1X2")
    assert suma_1x2 == pytest.approx(1.0)

    # Sin confirmaciones: la tabla aun no existe y el CLV queda vacio.
    assert dashboard.clv_v2_confirmadas(db)["n"] == 0


def test_valor_v2_vivos_marca_confirmada(db):
    _sembrar(db)
    confirmar_apuesta(db, "f1", "1X2", 2.5, 10.0, pick="LOCAL", casa="Bet365")
    estado = {(r["mercado"], r["pick"]): r["confirmada"] for r in dashboard.valor_v2_vivos(db)}
    assert estado == {("1X2", "LOCAL"): True, ("1X2", "EMPATE"): True, ("1X2", "VISITA"): True,
                      ("OU", "OVER 2.5"): False, ("OU", "UNDER 2.5"): False}


def test_clv_v2_confirmadas_desde_cierre_pinnacle(db):
    _sembrar(db)
    confirmar_apuesta(db, "f1", "1X2", 2.5, 10.0, pick="LOCAL", casa="Bet365")
    confirmar_apuesta(db, "f1", "OU", 2.2, 5.0, pick="OVER 2.5", casa="BetWarrior")
    confirmar_apuesta(db, "f2", "1X2", 3.0, 10.0, pick="VISITA", casa="Casa local")  # sin Pinnacle

    res = dashboard.clv_v2_confirmadas(db)
    por_mercado = {(f["id"], f["mercado"]): f for f in res["filas"]}
    p_cierre = (1 / 2.0) / (1 / 2.0 + 1 / 3.5 + 1 / 4.0)
    clv_1x2 = 2.5 * p_cierre - 1
    assert por_mercado[("f1", "1X2")]["clv"] == pytest.approx(clv_1x2)
    assert por_mercado[("f1", "OU")]["clv"] == pytest.approx(0.1)  # 2.2 * 0.5 - 1
    assert por_mercado[("f2", "1X2")]["clv"] is None
    assert por_mercado[("f1", "1X2")]["casa"] == "Bet365"
    assert por_mercado[("f1", "1X2")]["estado"] == "Pendiente"

    assert (res["n"], res["n_clv"]) == (3, 2)
    assert res["clv_medio"] == pytest.approx((clv_1x2 + 0.1) / 2)
    assert res["clv_por_casa"]["Bet365"] == pytest.approx(clv_1x2)
    assert res["clv_por_casa"]["Casa local"] is None


def test_app_sin_pin_columns_no_falla(db):
    _sembrar(db, con_pin=False)
    st.cache_data.clear()
    at = AppTest.from_file(str(RAIZ / "dashboard.py"), default_timeout=120).run()
    assert not at.exception
    assert at.tabs[0].label == "Valor v2"
    assert len(at.button) == 0  # sin cuotas Pinnacle no hay formularios


def test_app_con_pin_columns_confirma_desde_valor_v2(db):
    _sembrar(db)
    st.cache_data.clear()
    at = AppTest.from_file(str(RAIZ / "dashboard.py"), default_timeout=120).run()
    assert not at.exception
    assert len(at.button) == 0  # sin cuota de la casa cargada no hay formularios

    at.session_state["cuotas_casa"] = {("f1", "LOCAL"): 2.0}  # minima LOCAL ~2.30: sin valor
    at.run()
    assert len(at.button) == 0

    at.session_state["cuotas_casa"] = {("f1", "LOCAL"): 2.6}
    at.run()
    assert len(at.button) == 1
    at.selectbox[0].set_value("Bet365").run()
    at.button[0].click().run()
    assert not at.exception
    assert "Confirmada" in at.success[0].value
    assert db.execute("SELECT casa, cuota_tomada FROM apuestas_confirmadas "
                      "WHERE id_partido = 'f1' AND mercado = '1X2'").fetchone() == ("Bet365", 2.6)


def test_tabla_ev_ordena_y_recomienda(db):
    _sembrar(db)
    filas = dashboard.valor_v2_vivos(db)
    ev = dashboard.tabla_ev(filas, {("f1", "LOCAL"): 2.6, ("f1", "EMPATE"): 3.0, ("otro", "LOCAL"): 9.0})
    assert [f["pick"] for f in ev] == ["LOCAL", "EMPATE"]  # mayor EV primero; ids ajenos se ignoran
    local, empate = ev
    assert local["ev"] == pytest.approx(2.6 * local["prob_justa"] - 1)
    assert local["apostar"] and not empate["apostar"]  # 3.0 < minima EMPATE (~3.6)


def test_resultados_pinnacle_usa_cierre_y_calcula_brier(db):
    _sembrar(db)
    r = dashboard.resultados_pinnacle(db)
    assert r["n"] == 1 and r["n_cierre"] == 1  # f4 jugado 2-1; f3 paso pero no tiene goles
    f = r["filas"][0]
    p = [(1 / c) / (1 / 2.0 + 1 / 3.5 + 1 / 4.0) for c in (2.0, 3.5, 4.0)]
    assert (f["Favorito"], f["Acerto"], f["Fuente"]) == ("LOCAL", True, "cierre")
    assert f["Brier"] == pytest.approx((p[0] - 1) ** 2 + p[1] ** 2 + p[2] ** 2)
    assert r["brier"] == pytest.approx(f["Brier"])

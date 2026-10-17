import pytest

from src.persistencia.excel_metricas import calcular_metricas_dashboard


def _fila(id_p, ap1x2, apou, stk1x2, stkou, estado, gl, gv, c1=2.0, cx=3.0, co=1.8):
    # Orden de columnas: ver _cargar_partidos en motor_sincronizador.py.
    # Probs en 0: no entra al bloque de accuracy ni Brier.
    return (id_p, '2026-03-10 20:00', 'A', 'B', 'Argentina',
            0.0, 0.0, 0.0, 0.0, 0.0,
            ap1x2, apou, stk1x2, stkou,
            c1, cx, 4.0, co, 2.0,
            estado, gl, gv, None, None, None, None)


def test_metricas_financieras_solo_liquidadas():
    datos = [
        _fila("a", "[GANADA] LOCAL", "pendiente", 10, 0, "Liquidado", 2, 1),       # +10
        _fila("b", "[PERDIDA] VISITA", "pendiente", 10, 0, "Liquidado", 2, 1),     # -10
        _fila("c", "[APOSTAR] LOCAL", "pendiente", 100, 0, "Calculado", 3, 0),     # excluida: no liquidada
        _fila("d", "[GANADA] LOCAL", "pendiente", 5, 0, "Liquidado", 2, 1, c1=0),  # ganada sin cuota: excluida
        _fila("e", "[PERDIDA] EMPATE", "pendiente", 5, 0, "Liquidado", 2, 1, cx=0),  # perdida: -5 sin cuota
        _fila("f", "pendiente", "[GANADA] OVER 2.5", 0, 4, "Liquidado", 2, 1),     # ou: +3.2
    ]
    m = calcular_metricas_dashboard(datos, 0.25)

    assert m['1x2']['n'] == 3
    assert m['1x2']['pl'] == pytest.approx(-5.0)
    assert m['1x2']['vol'] == pytest.approx(25.0)
    assert m['ou']['n'] == 1
    assert m['ou']['pl'] == pytest.approx(3.2)
    assert m['ou']['vol'] == pytest.approx(4.0)
    assert m['total']['pl'] == pytest.approx(-1.8)
    assert m['total']['vol'] == pytest.approx(29.0)

    liga = m['por_liga']['Argentina']
    assert liga['n'] == 5 and liga['g'] == 3 and liga['p'] == 2  # incluye O/U (fila f)
    assert liga['vol'] == pytest.approx(29.0)
    assert liga['pl'] == pytest.approx(-1.8)


def test_p_valor_t_student_coincide_con_tabla():
    from src.persistencia.excel_metricas import p_valor_t
    # Valores de referencia (scipy.stats.t): la normal daba 0.046 en ambos casos.
    assert abs(p_valor_t(2.0, 9) - 0.076553) < 1e-6
    assert abs(p_valor_t(2.0, 23) - 0.057445) < 1e-6
    assert p_valor_t(0.0, 5) == 1.0

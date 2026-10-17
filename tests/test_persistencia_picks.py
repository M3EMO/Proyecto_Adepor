import pytest

from src.comun.picks import cuota_para_pick, es_pick_valido

C = dict(c1=2.1, cx=3.3, c2=3.9, co=1.8, cu=2.0)


@pytest.mark.parametrize("token,esperado", [
    # Tokens reales de la DB, pendientes y liquidados
    ("[APOSTAR] LOCAL", 2.1), ("[APOSTAR] EMPATE", 3.3), ("[APOSTAR] VISITA", 3.9),
    ("[APOSTAR] OVER 2.5", 1.8), ("[APOSTAR] UNDER 2.5", 2.0),
    ("[GANADA] LOCAL", 2.1), ("[PERDIDA] EMPATE", 3.3), ("[GANADA] VISITA", 3.9),
    ("[GANADA] OVER 2.5", 1.8), ("[PERDIDA] UNDER 2.5", 2.0),
    # Tokens legacy
    ("[APOSTAR] 1", 2.1), ("[APOSTAR] X", 3.3), ("[APOSTAR] 2", 3.9),
    ("[APOSTAR] OVER", 1.8), ("[APOSTAR] UNDER", 2.0),
])
def test_cuota_por_token(token, esperado):
    assert cuota_para_pick(token, **C) == esperado


@pytest.mark.parametrize("token", [
    "[APOSTAR] HANDICAP", "LOCAL", "", None, "[APOSTAR]",
])
def test_token_no_reconocido_retorna_cero(token):
    assert cuota_para_pick(token, **C) == 0.0


def test_cuota_faltante_retorna_cero():
    assert cuota_para_pick("[APOSTAR] LOCAL", None, 3.0, 4.0, 2.0, 2.0) == 0.0


@pytest.mark.parametrize("token,esperado", [
    ("[APOSTAR] LOCAL", True), ("[GANADA] OVER 2.5", True), ("[APOSTAR] 2", True),
    ("[APOSTAR] HANDICAP", False), ("LOCAL", False), (None, False),
])
def test_es_pick_valido(token, esperado):
    assert es_pick_valido(token) is esperado

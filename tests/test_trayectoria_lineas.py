"""Pruebas del estudio E5 (docs/specs/13-estudios-forward.md). Datos sinteticos, sin red."""
import json

import pytest

from analisis import trayectoria_lineas as tl

INICIO = 10_000_000.0
H = 3600


def serie(*puntos):
    return [[INICIO - h * H, p] for h, p in puntos]


def tray(pin, casa):
    """pin y casa: tres series (local, empate, visita)."""
    return {'inicio': INICIO, 'casas': {'pinnacle': dict(zip(tl.OUTCOMES, pin)), 'betano': dict(zip(tl.OUTCOMES, casa))}}


def planas(p1, px, p2):
    return [serie((48, p1)), serie((48, px)), serie((48, p2))]


def test_lineas_quietas_el_clv_iguala_al_ev_inicial():
    t = tray(planas(2.0, 3.5, 4.0), planas(2.4, 3.2, 3.5))  # la casa paga 20% mas al local
    ops = [o for o in tl.oportunidades(t) if o[2] == 0]
    assert ops and all(o[4] > 0.1 for o in ops)
    assert ops[0][0] == pytest.approx(48, abs=0.6)  # primera oportunidad: unas 48 h antes


def test_pinnacle_se_mueve_hacia_la_casa_el_clv_cae():
    pin = [serie((48, 2.0), (6, 2.4)), serie((48, 3.5)), serie((48, 4.0), (6, 3.4))]  # el local sube a 2.4 al cierre
    t = tray(pin, planas(2.4, 3.2, 3.5))
    ops = [o for o in tl.oportunidades(t) if o[2] == 0]
    assert ops and all(o[4] < 0.05 for o in ops)  # el EV previo de +17% se evapora hacia el cierre


def test_sin_tres_precios_de_la_casa_no_hay_oportunidades():
    t = tray(planas(2.0, 3.5, 4.0), [serie((48, 2.4)), [], []])
    assert tl.oportunidades(t) == []


def test_medir_marca_insuficiente_y_calcula_con_pocos(tmp_path):
    for i in range(3):
        (tmp_path / f'f{i}.json').write_text(json.dumps(tray(planas(2.0, 3.5, 4.0), planas(2.4, 3.2, 3.5))))
    r = tl.medir(tmp_path)
    assert r['n_partidos_bajados'] == 3 and not r['suficiente']
    c = r['por_casa']['betano']
    assert c['todas']['n_partidos'] == 3 and c['todas']['clv_medio'] > 0.1
    assert c['todas']['exito'] is False  # menos de 40 partidos: no cuenta como exito


def test_reducir_ordena_y_descarta_precios_vacios():
    resp = {'bookmakers': {'pinnacle': {'markets': {'101': {'outcomes': {
        '101': {'players': {'0': [{'createdAt': '2026-10-23T12:00:00Z', 'price': 2.0},
                                   {'createdAt': '2026-10-23T10:00:00Z', 'price': 1.9},
                                   {'createdAt': '2026-10-23T11:00:00Z', 'price': None}]}}}}}}}}
    r = tl.reducir(resp, '2026-10-23T18:00:00Z')
    assert [p for _, p in r['casas']['pinnacle']['101']] == [1.9, 2.0]

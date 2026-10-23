import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'analisis'))
import clv_bet365ar as c  # noqa: E402


def test_ev_picks_umbral_y_filtro_de_calidad():
    pin = [2.0, 3.4, 4.0]
    assert c.ev_picks(pin, [2.25, 3.3, 3.6]) == [0]           # solo el local supera 2 %
    assert c.ev_picks(pin, [1.9, 3.3, 3.8]) == []
    assert c.ev_picks([1.5, 4.2, 6.5], [6.5, 4.2, 1.5]) == []  # local y visita invertidos: se descarta
    assert c.ev_picks([1.28, 5.9, 10.3], [11.5, 4.9, 1.22]) == []  # caso real Betano 2026-10-22


def test_cruzar_por_kickoff_y_nombre(monkeypatch):
    monkeypatch.setattr(c.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    candidatos = [{'fecha': '2026-10-24 17:00', 'local': 'River Plate', 'visita': 'Boca Juniors'},
                  {'fecha': '2026-11-07 17:00', 'local': 'River Plate', 'visita': 'Boca Juniors'}]
    p = {'pais': 'Argentina', 'inicio_utc': '2026-10-24T20:00:00.000Z', 'local': 'River Plate', 'visita': 'Boca Juniors'}
    assert c.cruzar(p, candidatos) is candidatos[0]
    lejos = {**p, 'inicio_utc': '2026-10-30T20:00:00.000Z'}
    assert c.cruzar(lejos, candidatos) is None
    largo = {'pais': 'Italia', 'inicio_utc': '2026-10-25T11:30:00.000Z', 'local': 'Inter Milano', 'visita': 'ACF Fiorentina'}
    serie_a = [{'fecha': '2026-10-25 08:30', 'local': 'Inter', 'visita': 'Fiorentina'},
               {'fecha': '2026-10-25 08:30', 'local': 'Napoli', 'visita': 'Torino'}]
    assert c.cruzar(largo, serie_a) is serie_a[0]  # nombres largos de OddsPapi


def test_resumen_calcula_clv_y_yield():
    r = c.resumen([{'clv': 0.05, 'pl': 1.2}, {'clv': -0.01, 'pl': -1.0}, {'clv': None, 'pl': None}])
    assert (r['n_picks'], r['n_con_cierre'], r['n_jugados']) == (3, 2, 2)
    assert abs(r['clv_medio'] - 0.02) < 1e-12 and abs(r['yield_plano'] - 0.1) < 1e-12


def test_aprender_guarda_alias_claro_y_deja_dudoso_para_revisar(monkeypatch):
    monkeypatch.setattr(c.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    guardados = []
    monkeypatch.setattr(c.gestor_nombres, 'aprender_alias', lambda crudo, oficial, liga: guardados.append((crudo, oficial)) or liga)
    revisar = []
    partido = {'pais': 'Espana', 'local': 'Malaga CF', 'visita': 'Athletic Bilbao'}
    c.aprender(partido, {'local': 'Málaga', 'visita': 'Athletic Club'}, revisar)
    assert guardados == [('Malaga CF', 'Málaga')]  # 'malaga' esta contenido en 'malagacf'
    assert revisar == [{'pais': 'Espana', 'oddspapi': 'Athletic Bilbao', 'base': 'Athletic Club'}]


def test_cusum_alarma_solo_cuando_el_clv_cae():
    assert not c.cusum([0.02] * 300)['alarma']           # edge de 2 %: S queda en 0
    r = c.cusum([-0.05] * 40)                            # sin edge: S sube 0.06 por pick
    assert r['alarma'] and abs(r['s'] - 40 * 0.06) < 1e-9


def test_cierre_aproximado_usa_la_ultima_captura_entre_pick_e_inicio():
    snaps = [('2026-10-20T12:00:00Z', [2.0, 3.4, 4.0]), ('2026-10-21T12:00:00Z', [1.9, 3.5, 4.2]),
             ('2026-10-22T12:00:00Z', [1.8, 3.6, 4.5]), ('2026-10-23T12:00:00Z', [1.7, 3.7, 4.9])]
    assert c.cierre_aproximado(snaps, '2026-10-20T12:00:00Z', '2026-10-22T20:00:00.000Z') == [1.8, 3.6, 4.5]
    assert c.cierre_aproximado(snaps[:1], '2026-10-20T12:00:00Z', '2026-10-22T20:00:00.000Z') is None


def test_simulacion_mueve_el_bankroll_solo_con_picks_jugados():
    base = {'resultado': 0, 'p_pin': 0.5, 'cuota': 2.2, 'clv': 0.05, 'liga': 'Argentina', 'partido': 'A vs B'}
    picks = [{**base, 'inicio': '2026-10-24T20:00', 'pl': 1.2}, {**base, 'inicio': '2026-10-25T20:00', 'pl': None}]
    r = c.simulacion(picks, 100_000.0)
    stake = c.stake_v2(0.5, 2.2, 100_000.0)
    assert r['bankroll_final'] == round(100_000.0 + stake * 1.2, 2) and r['n_jugados'] == 1
    assert [f['estado'] for f in r['picks']] == ['ganada', 'pendiente'] and r['picks'][1]['stake'] is None

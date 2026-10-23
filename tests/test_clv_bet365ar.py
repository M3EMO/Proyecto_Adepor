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

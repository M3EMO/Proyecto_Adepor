"""Pruebas de aceptacion F1-F4 de docs/specs/07-fotmob.md. Ninguna toca la red."""
import copy
import json

import pytest

from scripts.research import fotmob_pedir as fp
from tests.test_fotmob_explorar import DET

MID = 1


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, 'RAW', tmp_path)
    monkeypatch.setattr(fp, 'PAUSA', 0)
    return tmp_path


def con_cobertura(nivel, match_id=MID):
    det = copy.deepcopy(DET)
    det['general'].update(matchId=match_id, coverageLevel=nivel)
    return det


def test_f1_xg_de_tiros_coincide_con_stats():
    det = copy.deepcopy(DET)
    for st in det['content']['stats']['Periods']['All']['stats'][0]['stats']:
        if st['key'] == 'expected_goals':
            st['stats'] = ['0.30', '0.77']  # suma de los tiros: 0.30 y 0.75
    f = fp.fila(det)
    assert (f['xg_shotmap_l'], f['xg_shotmap_v']) == (0.3, 0.75)
    assert abs(f['xg_shotmap_l'] - f['xg_l']) <= 0.05
    assert abs(f['xg_shotmap_v'] - f['xg_v']) <= 0.05


def test_f2_id_distinto_lanza_y_no_guarda(raw, monkeypatch):
    monkeypatch.setattr(fp, 'pedir', lambda ruta: con_cobertura('xG', match_id=999))
    with pytest.raises(ValueError):
        fp.bajar_partido(MID)
    assert not list(raw.iterdir())


def test_f3_solo_xg_descarta_ratings(raw, monkeypatch):
    monkeypatch.setattr(fp, 'pedir', lambda ruta: con_cobertura('ratings'))
    assert fp.bajar_partido(MID, solo_xg=True) is None
    assert not list(raw.iterdir())


def test_f3_solo_xg_guarda_xg(raw, monkeypatch):
    monkeypatch.setattr(fp, 'pedir', lambda ruta: con_cobertura('xG'))
    assert fp.bajar_partido(MID, solo_xg=True) is not None
    assert (raw / f'{MID}.json').exists()


def test_f4_archivo_existente_no_pide_red(raw, monkeypatch):
    (raw / f'{MID}.json').write_text(json.dumps(con_cobertura('xG')))
    def sin_red(ruta):
        raise AssertionError('no debe pedir')
    monkeypatch.setattr(fp, 'pedir', sin_red)
    assert fp.bajar_partido(MID)['general']['matchId'] == MID

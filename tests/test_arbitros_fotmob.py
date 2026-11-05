"""Captura previa del arbitro en FotMob (E14). Sin red."""
import src.ingesta.motor_arbitros_fotmob as ma

TS = '2026-10-26T12:00:00Z'


def partido(mid, **status):
    return {'id': mid, 'home': {'name': 'A'}, 'away': {'name': 'B'}, 'status': {'utcTime': '2026-10-27T22:00:00.000Z', **status}}


def detalle(mid, arbitro=None):
    ib = {'Referee': {'text': arbitro, 'id': 7}} if arbitro else {}
    return {'general': {'matchId': mid}, 'content': {'matchFacts': {'infoBox': ib}}}


def fake(respuestas):
    def pedir(ruta):
        r = respuestas[ruta]
        if isinstance(r, Exception):
            raise r
        return r
    return pedir


def test_captura_arbitro_publicado_y_pendiente():
    resp = {'matches?date=20261027&timezone=America/Argentina/Buenos_Aires&ccode3=ARG': {'leagues': [
                {'primaryId': 112, 'matches': [partido(1), partido(2), partido(3, started=True)]},
                {'primaryId': 47, 'matches': [partido(4)]}]},
            'matchDetails?matchId=1': detalle(1, 'Darío Herrera'),
            'matchDetails?matchId=2': detalle(2)}
    filas = ma.capturar(TS, ['20261027'], fake(resp), pausa=0)
    assert [(f['match_id'], f['arbitro'], f['arbitro_id']) for f in filas] == [(1, 'Darío Herrera', 7), (2, None, None)]
    assert filas[0]['ts_captura'] == TS and filas[0]['inicio_utc'] == '2026-10-27T22:00:00.000Z'


def test_pedido_caido_u_otro_partido_no_frena_el_lote():
    resp = {'matches?date=20261027&timezone=America/Argentina/Buenos_Aires&ccode3=ARG': {'leagues': [
                {'primaryId': 112, 'matches': [partido(1), partido(2), partido(3)]}]},
            'matchDetails?matchId=1': RuntimeError('503'),
            'matchDetails?matchId=2': detalle(99, 'Otro'),
            'matchDetails?matchId=3': detalle(3, 'Yael Falcón Pérez'),
            'matches?date=20261028&timezone=America/Argentina/Buenos_Aires&ccode3=ARG': RuntimeError('503')}
    filas = ma.capturar(TS, ['20261027', '20261028'], fake(resp), pausa=0)
    assert [f['match_id'] for f in filas] == [3]


def test_baja_solo_terminados_que_faltan(tmp_path):
    (tmp_path / '1.json').write_text('{}')
    resp = {'fixtures?id=112': [{'id': '1', 'status': {'finished': True}}, {'id': '2', 'status': {'finished': True}},
                                {'id': '3', 'status': {'finished': False}}, {'id': '4', 'status': {'finished': True}},
                                {'id': '5', 'status': {'finished': True}}, {'id': '6', 'status': {'finished': True}}],
            'matchDetails?matchId=2': {'general': {'matchId': 2, 'finished': True}},
            'matchDetails?matchId=4': {'general': {'matchId': 4, 'finished': False}},
            'matchDetails?matchId=5': RuntimeError('503'),
            'matchDetails?matchId=6': {'general': {'matchId': 99, 'finished': True}}}
    assert ma.bajar_terminados(tmp_path, fake(resp), pausa=0) == ['2']
    assert sorted(f.name for f in tmp_path.iterdir()) == ['1.json', '2.json']
    assert (tmp_path / '1.json').read_text() == '{}'  # un archivo existente no se pisa


def test_fixtures_caido_no_rompe():
    assert ma.bajar_terminados(pedir_fn=fake({'fixtures?id=112': RuntimeError('503')}), pausa=0) == []

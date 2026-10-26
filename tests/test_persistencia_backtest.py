from src.persistencia.motor_backtest import _coincide_partido, _score_entero

PENDIENTE = ("p1", "River Plate", "Boca Juniors", "2026-03-10 20:00", "Argentina")


def test_coincide_misma_fecha_liga_y_equipos():
    assert _coincide_partido(PENDIENTE, "Argentina", "20260310", "River Plate", "Boca Juniors")


def test_no_coincide_otra_fecha():
    assert not _coincide_partido(PENDIENTE, "Argentina", "20260313", "River Plate", "Boca Juniors")


def test_no_coincide_otra_liga():
    assert not _coincide_partido(PENDIENTE, "Inglaterra", "20260310", "River Plate", "Boca Juniors")


def test_tolera_un_dia_de_diferencia():
    assert _coincide_partido(PENDIENTE, "Argentina", "20260309", "River Plate", "Boca Juniors")
    assert _coincide_partido(PENDIENTE, "Argentina", "20260311", "River Plate", "Boca Juniors")


def test_no_coincide_dos_dias_de_diferencia():
    assert not _coincide_partido(PENDIENTE, "Argentina", "20260312", "River Plate", "Boca Juniors")


def test_no_coincide_equipos_distintos():
    assert not _coincide_partido(PENDIENTE, "Argentina", "20260310", "River Plate", "Newell's")


def test_score_entero():
    assert _score_entero("2") == 2
    assert _score_entero("0") == 0
    assert _score_entero(None) is None
    assert _score_entero("") is None
    assert _score_entero("x") is None


def test_backtest_incluye_pendientes_pasados(db, monkeypatch):
    """Si el pipeline aborto antes de calcular, el partido igual debe liquidarse."""
    import src.persistencia.motor_backtest as mb

    class _Resp:
        status_code = 200

        def json(self):
            return {'events': [{'status': {'type': {'completed': True, 'name': 'STATUS_FULL_TIME'}},
                                'competitions': [{'competitors': [
                                    {'homeAway': 'home', 'score': '2', 'team': {'displayName': 'Torino'}},
                                    {'homeAway': 'away', 'score': '1', 'team': {'displayName': 'Udinese'}}]}]}]}
    monkeypatch.setattr(mb.requests, 'get', lambda *a, **k: _Resp())
    monkeypatch.setattr(mb.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    monkeypatch.setattr(mb, 'MAPA_LIGAS_ESPN', {'Italia': 'ita.1'})
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado) "
               "VALUES ('p', '2026-10-12 15:45', 'Italia', 'Torino', 'Udinese', 'Pendiente')")
    db.commit()
    mb.main()
    assert db.execute("SELECT estado, goles_l, goles_v FROM partidos_backtest").fetchone() == ('Finalizado', 2, 1)


def test_backtest_liquida_partido_postergado_un_dia(db, monkeypatch):
    """PSG vs Lyon 2026-10: la DB guarda el 25/10 y ESPN lo lista el 26/10."""
    import src.persistencia.motor_backtest as mb
    pedidas = []

    class _Resp:
        status_code = 200

        def __init__(self, fecha):
            self.fecha = fecha

        def json(self):
            if self.fecha != '20261026':
                return {'events': []}
            return {'events': [{'status': {'type': {'completed': True, 'name': 'STATUS_FULL_TIME'}},
                                'competitions': [{'competitors': [
                                    {'homeAway': 'home', 'score': '3', 'team': {'displayName': 'Paris Saint-Germain'}},
                                    {'homeAway': 'away', 'score': '0', 'team': {'displayName': 'Lyon'}}]}]}]}

    def get(url, timeout):
        fecha = url.rsplit('=', 1)[1]
        pedidas.append(fecha)
        return _Resp(fecha)
    monkeypatch.setattr(mb.requests, 'get', get)
    monkeypatch.setattr(mb.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    monkeypatch.setattr(mb, 'MAPA_LIGAS_ESPN', {'Francia': 'fra.1'})
    monkeypatch.setattr(mb, 'ahora_art', lambda: __import__('datetime').datetime(2026, 10, 27, 9, 0))
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, estado) "
               "VALUES ('p', '2026-10-25 16:45', 'Francia', 'Paris Saint-Germain', 'Lyon', 'Pendiente')")
    db.commit()
    mb.main()
    assert db.execute("SELECT estado, goles_l, goles_v FROM partidos_backtest").fetchone() == ('Finalizado', 3, 0)

"""Tests de Pinnacle crudo (modelo v2): helper cuotas_pinnacle y escritura pin_* en main()."""
import os
from datetime import datetime

import pytest

from src.ingesta import motor_cuotas as mc

AHORA = datetime(2026, 10, 12, 18, 0)


def _libro(key, home, draw, away):
    return {'key': key, 'markets': [{'key': 'h2h', 'outcomes': [
        {'name': 'Local', 'price': home}, {'name': 'Draw', 'price': draw}, {'name': 'Visita', 'price': away}]}]}


def _totales(key, outcomes):
    """outcomes: lista de (nombre, punto, precio)."""
    return {'key': key, 'markets': [{'key': 'totals', 'outcomes': [
        {'name': n, 'point': p, 'price': q} for n, p, q in outcomes]}]}


def test_cuotas_pinnacle_ignora_bet365_y_toma_1x2_completo():
    books = [_libro('bet365', 2.0, 3.0, 4.0), _libro('pinnacle', 1.9, 3.4, 4.2)]
    assert mc.cuotas_pinnacle(books, 'Local', 'Visita') == (1.9, 3.4, 4.2, 0.0, 0.0)


def test_cuotas_pinnacle_sin_empate_da_1x2_en_cero():
    pinnacle_sin_empate = {'key': 'pinnacle', 'markets': [{'key': 'h2h', 'outcomes': [
        {'name': 'Local', 'price': 1.9}, {'name': 'Visita', 'price': 4.2}]}]}
    books = [_libro('bet365', 2.0, 3.0, 4.0), pinnacle_sin_empate]
    assert mc.cuotas_pinnacle(books, 'Local', 'Visita') == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_cuotas_pinnacle_totals_solo_linea_2_5_y_solo_pinnacle():
    books = [
        _totales('bet365', [('Over', 2.5, 2.0), ('Under', 2.5, 1.8)]),
        {'key': 'pinnacle', 'markets': [{'key': 'totals', 'outcomes': [
            {'name': 'Over', 'point': 2.0, 'price': 1.3}, {'name': 'Under', 'point': 2.0, 'price': 3.5},
            {'name': 'Over', 'point': 2.5, 'price': 1.95}, {'name': 'Under', 'point': 2.5, 'price': 1.92},
            {'name': 'Over', 'point': 3.0, 'price': 2.6}, {'name': 'Under', 'point': 3.0, 'price': 1.5}]}]},
    ]
    assert mc.cuotas_pinnacle(books, 'Local', 'Visita') == (0.0, 0.0, 0.0, 1.95, 1.92)


def test_cuotas_pinnacle_o_u_necesita_los_dos_lados():
    solo_over = _totales('pinnacle', [('Over', 2.5, 1.95)])
    assert mc.cuotas_pinnacle([solo_over], 'Local', 'Visita') == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_main_escribe_pin_respetando_freeze_y_ventana(db, monkeypatch):
    # Esquema viejo: sin pin_* ni apuestas_confirmadas. main() debe migrar las columnas.
    db.execute("CREATE TABLE apuestas_confirmadas (id_partido TEXT NOT NULL, mercado TEXT NOT NULL, "
               "pick TEXT NOT NULL, cuota_tomada REAL NOT NULL, stake REAL NOT NULL, "
               "ts TEXT DEFAULT CURRENT_TIMESTAMP, casa TEXT, PRIMARY KEY (id_partido, mercado))")
    db.execute("INSERT INTO apuestas_confirmadas (id_partido, mercado, pick, cuota_tomada, stake) "
               "VALUES ('LEJOS', '1X2', 'LOCAL', 1.5, 10)")
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, cuota_1) "
               "VALUES ('LEJOS', '2026-10-12 21:00', 'Inglaterra', 'Arsenal', 'Chelsea', 1.5)")  # +3h: fuera de ventana
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita) "
               "VALUES ('CERCA', '2026-10-12 18:30', 'Inglaterra', 'Liverpool', 'Everton')")  # +30min: en ventana, sin stake
    db.commit()

    def evento(local, visita, kickoff_utc):
        return {'home_team': local, 'away_team': visita, 'commence_time': kickoff_utc, 'bookmakers': [{'key': 'pinnacle', 'markets': [
            {'key': 'h2h', 'outcomes': [{'name': local, 'price': 1.9}, {'name': 'Draw', 'price': 3.4},
                                        {'name': visita, 'price': 4.2}]},
            {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.95},
                                           {'name': 'Under', 'point': 2.5, 'price': 1.9}]}]}]}

    class Resp:
        status_code = 200

        def json(self):
            return [evento('Arsenal', 'Chelsea', '2026-10-13T00:00:00Z'),
                    evento('Liverpool', 'Everton', '2026-10-12T21:30:00Z')]

    monkeypatch.setattr(mc, 'API_KEYS', ['K'])
    monkeypatch.setattr(mc.requests, 'get', lambda *a, **k: Resp())
    monkeypatch.setattr(mc, 'ahora_art', lambda: AHORA)
    monkeypatch.setattr(mc, 'DB_NAME', os.environ['ADEPOR_DB'])
    monkeypatch.setattr(mc.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)

    mc.main()

    cols = [r[1] for r in db.execute("PRAGMA table_info(partidos_backtest)")]
    assert {'pin_1', 'pin_u25', 'pin_cierre_1', 'pin_cierre_u25'} <= set(cols)

    lejos = db.execute("SELECT cuota_1, pin_1, pin_u25, pin_cierre_1 FROM partidos_backtest "
                       "WHERE id_partido='LEJOS'").fetchone()
    assert lejos == (1.5, 1.9, 1.9, None)  # pin cambia con apuesta confirmada; cuota del pick no

    cerca = db.execute("SELECT pin_1, pin_x, pin_cierre_1, pin_cierre_x, pin_cierre_o25 "
                       "FROM partidos_backtest WHERE id_partido='CERCA'").fetchone()
    assert cerca == (1.9, 3.4, 1.9, 3.4, 1.95)  # cierre en ventana aun sin stake


def test_misma_fecha_rechaza_eventos_de_otro_partido():
    # Casos reales 2026-10-20 (adepor-bh4): el partido de la base ya se habia jugado y el
    # fuzzy lo emparejo con un evento futuro de otro rival.
    assert mc._misma_fecha('2026-10-19T23:00:00Z', '2026-10-19 20:00')       # mismo kickoff
    assert mc._misma_fecha('2026-10-20T08:00:00Z', '2026-10-19 20:00')       # 12 h: limite
    assert not mc._misma_fecha('2026-10-25T21:30:00Z', '2026-10-19 20:00')   # Corinthians -> Coritiba
    assert not mc._misma_fecha(None, '2026-10-19 20:00')                     # sin fecha: no se empareja
    assert not mc._misma_fecha('2026-10-19T23:00:00Z', '19/10/2026 20:00')


def test_solo_cierre_consulta_solo_ligas_con_kickoff_inminente(db, monkeypatch):
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, cuota_1) "
               "VALUES ('YA', '2026-10-12 18:15', 'Inglaterra', 'Local', 'Visita', 1.5)")  # +15 min: limite
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita) "
               "VALUES ('LUEGO', '2026-10-12 19:00', 'Espana', 'Betis', 'Sevilla')")  # +1 h: otra liga, no se consulta
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita) "
               "VALUES ('SIN_CLAVE', '2026-10-12 18:10', 'Bolivia', 'Bolivar', 'Always Ready')")  # sin clave Odds API
    db.commit()

    pedidos = []

    class Resp:
        status_code = 200

        def json(self):
            return [{'home_team': 'Local', 'away_team': 'Visita', 'commence_time': '2026-10-12T21:15:00Z',
                     'bookmakers': [_libro('pinnacle', 2.1, 3.3, 3.6)]}]

    monkeypatch.setattr(mc, 'API_KEYS', ['K'])
    monkeypatch.setattr(mc.requests, 'get', lambda url, **k: pedidos.append(url) or Resp())
    monkeypatch.setattr(mc, 'ahora_art', lambda: AHORA)
    monkeypatch.setattr(mc, 'DB_NAME', os.environ['ADEPOR_DB'])
    monkeypatch.setattr(mc.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)

    mc.main(solo_cierre=True)

    assert pedidos == ['https://api.the-odds-api.com/v4/sports/soccer_epl/odds/']  # un pedido = 2 creditos
    ya = db.execute("SELECT cuota_1, pin_1, pin_cierre_1, pin_cierre_x, pin_cierre_2 FROM partidos_backtest "
                    "WHERE id_partido='YA'").fetchone()
    assert ya == (1.5, 0, 2.1, 3.3, 3.6)  # solo cierre: pin_* y cuota_* intactos

"""Integracion de punta a punta del camino del dinero v2, sobre una DB creada por inicializar_db:
Pinnacle -> confirmacion (cuota tomada + stake) -> cierre -> resultado ESPN -> liquidacion -> CLV -> bankroll."""
import os
import sqlite3
from datetime import timedelta

import src.persistencia.motor_backtest as mb
import src.persistencia.motor_liquidador as ml
from scripts.db.inicializar_db import inicializar
from src.comun.tiempo import ahora_art
from src.persistencia.bankroll import obtener_bankroll_operativo
from src.persistencia.confirmaciones import confirmar_apuesta

ID = 'flujo-riverboca'


def _db_nueva():
    path = os.environ['ADEPOR_DB']
    for sufijo in ('', '-wal', '-shm'):
        if os.path.exists(path + sufijo):
            os.remove(path + sufijo)
    inicializar(path)
    return sqlite3.connect(path)


def test_flujo_v2_pinnacle_como_verdad(monkeypatch):
    import dashboard
    from src.nucleo.valor_v2 import tabla_valor
    conn = _db_nueva()
    futuro = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    conn.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, pin_1, pin_x, pin_2) "
                 "VALUES (?, ?, 'Argentina', 'River Plate', 'Boca Juniors', 2.00, 3.40, 4.20)", (ID, futuro))
    conn.executemany("INSERT INTO configuracion VALUES (?, ?)", [
        ('bankroll', '100000'), ('bankroll_modo', 'dinamico'), ('bankroll_piso', '1000'),
        ('bankroll_techo', '1000000'), ('bankroll_fecha_corte', '2000-01-01')])
    conn.commit()

    # 1. Prob justa y cuota minima desde Pinnacle; el usuario ve 2.20 en BetWarrior.
    local = next(t for t in tabla_valor({'pin_1': 2.0, 'pin_x': 3.4, 'pin_2': 4.2}) if t[1] == 'LOCAL')
    assert 2.20 > local[3]
    confirmar_apuesta(conn, ID, '1X2', 2.20, 100.0, pick='LOCAL', casa='BetWarrior')

    # 2. Cierre de Pinnacle (el mercado se movio a favor del pick) y resultado 1-0.
    pasado = (ahora_art() - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M')
    conn.execute("UPDATE partidos_backtest SET fecha=?, pin_cierre_1=1.90, pin_cierre_x=3.50, "
                 "pin_cierre_2=4.50, cuota_cierre_1x2=1.90", (pasado,))
    conn.commit()

    class _Espn:
        status_code = 200

        def json(self):
            return {'events': [{'status': {'type': {'completed': True, 'name': 'STATUS_FULL_TIME'}},
                                'competitions': [{'competitors': [
                                    {'homeAway': 'home', 'score': '1', 'team': {'displayName': 'River Plate'}},
                                    {'homeAway': 'away', 'score': '0', 'team': {'displayName': 'Boca Juniors'}}]}]}]}
    monkeypatch.setattr(mb.requests, 'get', lambda *a, **k: _Espn())
    monkeypatch.setattr(mb.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    monkeypatch.setattr(mb, 'MAPA_LIGAS_ESPN', {'Argentina': 'arg.1'})
    mb.main()
    ml.main()

    # 3. Liquidada a la cuota de BetWarrior, con CLV v2 positivo contra el cierre sin margen.
    assert conn.execute("SELECT estado, apuesta_1x2 FROM partidos_backtest").fetchone() == ('Liquidado', '[GANADA] LOCAL')
    clv = dashboard.clv_v2_confirmadas(conn)
    assert clv['n'] == 1 and clv['clv_medio'] > 0
    assert 'BetWarrior' in clv['clv_por_casa']
    assert obtener_bankroll_operativo(conn.cursor()) == 100000 + 100 * 1.20
    conn.close()

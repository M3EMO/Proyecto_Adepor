"""Integracion de punta a punta del camino del dinero, sobre una DB creada por inicializar_db:
pick -> confirmacion (cuota tomada + stake) -> cierre -> resultado ESPN -> liquidacion -> CLV -> bankroll."""
import os
import sqlite3
from datetime import timedelta

import src.nucleo.motor_calculadora as mc
import src.persistencia.motor_backtest as mb
import src.persistencia.motor_liquidador as ml
from scripts.db.inicializar_db import inicializar
from src.comun.tiempo import ahora_art
from src.persistencia.confirmaciones import confirmar_apuesta

ID = 'flujo-riverboca'


def _db_nueva():
    path = os.environ['ADEPOR_DB']
    for sufijo in ('', '-wal', '-shm'):
        if os.path.exists(path + sufijo):
            os.remove(path + sufijo)
    inicializar(path)
    return sqlite3.connect(path)


def test_flujo_completo_de_una_apuesta_real(monkeypatch):
    conn = _db_nueva()
    futuro = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    conn.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, cuota_1, cuota_x, "
                 "cuota_2) VALUES (?, ?, 'Argentina', 'River Plate', 'Boca Juniors', 1.90, 3.50, 4.50)",
                 (ID, futuro))
    # River fuerte de local, Boca flojo de visita, ambos con historia suficiente (>= 5 PJ).
    for eq, fh, ch, fa, ca in (('riverplate', 2.0, 0.8, 1.5, 1.2), ('bocajuniors', 1.3, 1.1, 0.9, 1.8)):
        conn.execute("INSERT INTO historial_equipos (equipo_norm, liga, ema_xg_favor_home, ema_xg_contra_home, "
                     "ema_xg_favor_away, ema_xg_contra_away, partidos_home, partidos_away) "
                     "VALUES (?, 'Argentina', ?, ?, ?, ?, 10, 10)", (eq, fh, ch, fa, ca))
    conn.executemany("INSERT INTO configuracion VALUES (?, ?)", [
        ('bankroll', '100000'), ('bankroll_modo', 'dinamico'), ('bankroll_piso', '1000'),
        ('bankroll_techo', '1000000'), ('bankroll_fecha_corte', '2000-01-01')])
    conn.commit()

    # 1. Pick en pretest: se genera con stake 0.
    mc.main()
    ap, stk = conn.execute("SELECT apuesta_1x2, stake_1x2 FROM partidos_backtest").fetchone()
    assert ap == '[APOSTAR] LOCAL' and stk == 0

    # 2. El usuario apuesta: cuota tomada 1.95, stake 1000. El pick queda congelado.
    confirmar_apuesta(conn, ID, '1X2', 1.95, 1000.0)
    mc.main()
    assert conn.execute("SELECT apuesta_1x2, stake_1x2, cuota_1 FROM partidos_backtest").fetchone() \
        == ('[APOSTAR] LOCAL', 1000.0, 1.95)

    # 3. Cierre capturado por motor_cuotas (ventana pre-kickoff) y el partido se juega.
    pasado = (ahora_art() - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M')
    conn.execute("UPDATE partidos_backtest SET cuota_cierre_1x2 = 1.80, fecha = ?", (pasado,))
    conn.commit()

    class _Espn:
        status_code = 200

        def json(self):
            return {'events': [{'status': {'type': {'completed': True, 'name': 'STATUS_FULL_TIME'}},
                                'competitions': [{'competitors': [
                                    {'homeAway': 'home', 'score': '2', 'team': {'displayName': 'River Plate'}},
                                    {'homeAway': 'away', 'score': '0', 'team': {'displayName': 'Boca Juniors'}}]}]}]}
    monkeypatch.setattr(mb.requests, 'get', lambda *a, **k: _Espn())
    monkeypatch.setattr(mb.gestor_nombres, 'obtener_nombre_estandar', lambda n, **k: n)
    monkeypatch.setattr(mb, 'MAPA_LIGAS_ESPN', {'Argentina': 'arg.1'})
    mb.main()
    ml.main()

    # 4. Liquidacion, CLV y bankroll con el precio realmente tomado.
    fila = conn.execute("SELECT estado, apuesta_1x2, clv_pct_1x2 FROM partidos_backtest").fetchone()
    assert fila[0] == 'Liquidado' and fila[1] == '[GANADA] LOCAL'
    assert abs(fila[2] - (1.95 / 1.80 - 1) * 100) < 1e-9          # +8.33%
    assert mc.obtener_bankroll_operativo(conn.cursor()) == 100000 + 1000 * 0.95
    conn.close()

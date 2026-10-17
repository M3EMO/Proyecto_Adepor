"""Regresiones de motor_calculadora (auditoria 2026-10)."""
from datetime import timedelta

from src.comun.tiempo import ahora_art

import pytest

import src.nucleo.motor_calculadora as mc


def _fila(db, id_p, fecha, ap1x2='', st1x2=0.0, apou='', stou=0.0, estado='Liquidado',
          gl=None, gv=None, c=(2.0, 3.4, 3.8, 1.9, 1.9), pais='Argentina'):
    db.execute("""INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita,
                  cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
                  apuesta_1x2, stake_1x2, apuesta_ou, stake_ou, estado, goles_l, goles_v)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (id_p, fecha, pais, 'River Plate', 'Boca Juniors', *c,
                ap1x2, st1x2, apou, stou, estado, gl, gv))
    db.commit()


def test_drawdown_detecta_racha_de_perdidas_liquidadas(db):
    for i in range(5):
        _fila(db, f'p{i}', f'2026-05-0{i + 1} 20:00', '[PERDIDA] LOCAL', 100.0)
    assert mc.detectar_drawdown(db.cursor(), umbral=5) is True


def test_drawdown_corta_con_ganada_reciente(db):
    for i in range(5):
        _fila(db, f'p{i}', f'2026-05-0{i + 1} 20:00', '[PERDIDA] LOCAL', 100.0)
    _fila(db, 'p9', '2026-05-09 20:00', '[GANADA] VISITA', 100.0)
    assert mc.detectar_drawdown(db.cursor(), umbral=5) is False


def test_drawdown_cuenta_mercado_ou_e_ignora_stake_cero(db):
    for i in range(3):
        _fila(db, f'a{i}', f'2026-05-0{i + 1} 20:00', '', 0.0, '[PERDIDA] OVER 2.5', 50.0)
    _fila(db, 'b', '2026-05-08 20:00', '[GANADA] LOCAL', 0.0)  # pretest: stake 0 no cuenta
    assert mc.detectar_drawdown(db.cursor(), umbral=3) is True


def test_n_acum_resuelve_display_name_espn(db):
    db.executemany("INSERT INTO historial_equipos_stats VALUES (?,?,?,?)", [
        ('Argentina', 'River Plate', '2026-03-01', 40),
        ('Argentina', 'River Plate', '2026-04-01', 41),
        ('Argentina', 'River Plate', '2026-05-01', 42),
    ])
    db.commit()
    mc._N_ACUM_NOMBRES.clear()
    assert mc._get_n_acum_pre_partido('Argentina', 'riverplate', '2026-04-15 20:00', db) == 41
    assert mc._get_n_acum_pre_partido('Argentina', 'equipoinexistente', '2026-04-15', db) is None


def test_m2_no_bloquea_sin_opt_in(monkeypatch):
    monkeypatch.setattr(mc, '_FILTRO_PICKS_V51',
                        {'ligas': {'Argentina'}, 'n_acum_max': 60, 'excluir_q4': False,
                         'm2_activo': False})
    pick, _, _ = mc.evaluar_mercado_1x2(0.60, 0.22, 0.18, 2.0, 3.6, 4.5,
                                        liga='Argentina', n_acum_l=200)
    assert 'EMA Madura' not in pick


def test_m2_bloquea_con_opt_in(monkeypatch):
    monkeypatch.setattr(mc, '_FILTRO_PICKS_V51',
                        {'ligas': {'Argentina'}, 'n_acum_max': 60, 'excluir_q4': False,
                         'm2_activo': True})
    pick, _, _ = mc.evaluar_mercado_1x2(0.60, 0.22, 0.18, 2.0, 3.6, 4.5,
                                        liga='Argentina', n_acum_l=200)
    assert 'EMA Madura' in pick


def test_hallazgo_g_infla_locales_no_favoritos():
    """Documenta por que HG salio del camino de decision: p1=0.25 -> 0.36."""
    p1, _, _ = mc.aplicar_hallazgo_g(0.25, 0.25, 0.50, 'Brasil',
                                     {'Brasil': {'n': 80, 'freq_local': 0.47}})
    assert p1 > 0.35


def test_main_solo_calcula_futuros_sin_alerta(db):
    futuro = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    pasado = (ahora_art() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    _fila(db, 'futuro', futuro, 'pendiente', estado='Pendiente')
    _fila(db, 'en_juego', pasado, 'pendiente', estado='Calculado')
    _fila(db, 'jugado', futuro, 'pendiente', estado='Calculado', gl=2, gv=0)
    _fila(db, 'alertado', futuro, '[APOSTAR] LOCAL', 500.0, estado='Calculado')
    db.execute("INSERT INTO log_alertas VALUES ('alertado_1X2','x','1X2','[APOSTAR] LOCAL',500,'t')")
    db.commit()

    mc.main()

    filas = dict(db.execute("SELECT id_partido, estado || '|' || apuesta_1x2 || '|' || stake_1x2 "
                            "FROM partidos_backtest").fetchall())
    assert filas['futuro'].startswith('Calculado|') and 'pendiente' not in filas['futuro']
    assert filas['en_juego'] == 'Calculado|pendiente|0.0'
    assert filas['jugado'] == 'Calculado|pendiente|0.0'
    assert filas['alertado'] == 'Calculado|[APOSTAR] LOCAL|500.0'


@pytest.mark.parametrize('lam,mu', [(1.3, 1.1), (2.0, 0.6), (0.4, 0.4)])
def test_poisson_dc_suma_uno(lam, mu):
    p = mc._calcular_probs_poisson_dc(lam, mu, -0.09)
    assert abs(sum(p) - 1) < 1e-9 and all(0 < x < 1 for x in p)


def test_kelly_medio_y_cap():
    # p=0.55, cuota 2.0 -> kelly full 0.10 -> medio 0.05 -> cap 0.025
    ev = 0.55 * 2.0 - 1
    assert mc.calcular_stake_independiente('[APOSTAR] LOCAL', ev, 2.0, 100000, 0.025) == 2500.0
    assert mc.calcular_stake_independiente('[PASAR] x', ev, 2.0, 100000, 0.025) == 0.0


def _probs_tras_main(db, flag):
    futuro = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    db.execute("DELETE FROM partidos_backtest")
    db.execute("DELETE FROM config_motor_valores")
    _fila(db, 'm', futuro, 'pendiente', estado='Pendiente')
    for eq in ('riverplate', 'bocajuniors'):
        db.execute("INSERT OR REPLACE INTO historial_equipos (equipo_norm, liga, ema_xg_favor_home, "
                   "ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away) "
                   "VALUES (?, 'Argentina', 2.4, 2.0, 2.1, 2.3)", (eq,))
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_real, tipo) "
               "VALUES ('factor_corr_xg_ou', 'global', 0.6, 'float')")
    if flag:
        db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) "
                   "VALUES ('escalar_lambda_1x2', 'global', 'TRUE', 'bool')")
    db.commit()
    mc.main()
    return db.execute("SELECT prob_x, prob_o25 FROM partidos_backtest WHERE id_partido='m'").fetchone()


def test_flag_escalar_lambda_1x2_no_doble_escala_ou(db):
    px_off, po_off = _probs_tras_main(db, False)
    px_on, po_on = _probs_tras_main(db, True)
    assert px_on > px_off                      # lambdas en escala de goles -> mas empates
    assert po_on == pytest.approx(po_off)      # O/U ya estaba escalado: no cambia


def test_cuotas_invertidas_no_generan_pick():
    # Modelo: local 0.45. Cuotas tipo Palmeiras-Gremio invertidas: local 6.03, visita 1.54.
    pick, ev, _ = mc.evaluar_mercado_1x2(0.45, 0.19, 0.36, 6.03, 4.24, 1.54, liga=None)
    assert pick.startswith('[PASAR] Cuotas Incoherentes') and ev > 1.0


def test_cuotas_coherentes_siguen_evaluandose():
    pick, _, _ = mc.evaluar_mercado_1x2(0.55, 0.25, 0.20, 2.00, 3.50, 4.20, liga=None)
    assert 'Incoherentes' not in pick


def test_drawdown_cuenta_un_resultado_por_partido(db):
    for i in range(2):
        _fila(db, f'd{i}', f'2026-05-0{i + 1} 20:00', '[PERDIDA] LOCAL', 100.0,
              '[PERDIDA] OVER 2.5', 50.0)
    assert mc.detectar_drawdown(db.cursor(), umbral=3) is False  # 2 partidos, 4 apuestas


def test_main_no_aplica_hallazgo_g_ni_fix5(db, monkeypatch):
    monkeypatch.setattr(mc, 'HALLAZGO_G_ACTIVO', True)
    p_sin, _ = _probs_tras_main(db, False)
    p1_sin = db.execute("SELECT prob_1 FROM partidos_backtest WHERE id_partido='m'").fetchone()[0]
    # 60 liquidados con 100% local: Hallazgo G empujaria p1 hacia arriba si siguiera activo.
    for i in range(60):
        _fila(db, f'h{i}', f'2026-01-01 {i % 24:02d}:00', '', 0.0, gl=2, gv=0)
    futuro = (ahora_art() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
    db.execute("UPDATE partidos_backtest SET estado='Pendiente', fecha=? WHERE id_partido='m'", (futuro,))
    db.commit()
    mc.main()
    p1_con = db.execute("SELECT prob_1 FROM partidos_backtest WHERE id_partido='m'").fetchone()[0]
    assert p1_con == pytest.approx(p1_sin)


def test_bankroll_bajo_piso_usa_capital_real(db):
    db.executemany("INSERT INTO configuracion VALUES (?, ?)", [
        ('bankroll', '100000'), ('bankroll_modo', 'dinamico'),
        ('bankroll_piso', '100000'), ('bankroll_techo', '1000000'),
        ('bankroll_fecha_corte', '2026-01-01')])
    _fila(db, 'p1', '2026-05-01 20:00', '[PERDIDA] LOCAL', 20000.0)
    assert mc.obtener_bankroll_operativo(db.cursor()) == 80000.0


def test_filtro_v51_sin_clave_ligas_no_bloquea(monkeypatch):
    monkeypatch.setattr(mc, '_FILTRO_PICKS_V51',
                        {'ligas': None, 'n_acum_max': 60, 'excluir_q4': False, 'm2_activo': False})
    pick, _, _ = mc.evaluar_mercado_1x2(0.60, 0.22, 0.18, 2.0, 3.6, 4.5, liga='Argentina')
    assert 'Liga No Apostable' not in pick


def test_ou_por_omision_es_pretest():
    assert mc.APUESTA_OU_ACTIVA is False


def test_layer2_sin_pesos_v12_mantiene_v0(db):
    futuro = (ahora_art() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
    _fila(db, 'v12', futuro, 'pendiente', estado='Pendiente')
    db.execute("CREATE TABLE historial_equipos_v6_shadow (equipo_norm TEXT, ema_xg_v6_favor_home REAL, "
               "ema_xg_v6_contra_home REAL, ema_xg_v6_favor_away REAL, ema_xg_v6_contra_away REAL)")
    db.executemany("INSERT INTO historial_equipos_v6_shadow VALUES (?, 1.5, 1.1, 1.2, 1.4)",
                   [('riverplate',), ('bocajuniors',)])
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) VALUES "
               "('arch_decision_per_liga', 'global', '{\"Argentina\": \"V12\"}', 'json')")
    db.commit()
    mc.main()
    p1, px, p2 = db.execute("SELECT prob_1, prob_x, prob_2 FROM partidos_backtest").fetchone()
    assert abs(p1 - 1 / 3) > 1e-6 and abs(p1 + px + p2 - 1) < 1e-6

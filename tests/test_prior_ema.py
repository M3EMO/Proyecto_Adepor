"""El prior por equipo deja las lambdas en escala de goles; el legacy las infla."""
import random

import pytest

import src.ingesta.motor_data as md
from scripts import evaluar_prior_ema as ev


@pytest.fixture
def liga_sintetica(db, monkeypatch):
    # xG proxy perfecto: el xG de cada equipo es su gol real.
    monkeypatch.setattr(md, 'calcular_xg_v2_hibrido_sofa', lambda st, goles, **kw: float(goles))
    monkeypatch.setattr(md, 'calcular_xg_hibrido', lambda st, goles, *a, **kw: float(goles))
    rng = random.Random(7)

    def poi(lam):
        k, p, u = 0, 2.718281828 ** -lam, rng.random()
        acc = p
        while u > acc:
            k += 1
            p *= lam / k
            acc += p
        return k

    equipos = [f'Equipo {i}' for i in range(12)]
    n = 0
    for temporada in range(3):
        for i, a in enumerate(equipos):
            for b in equipos[i + 1:]:
                for loc, vis in ((a, b), (b, a)):
                    n += 1
                    db.execute("""INSERT INTO partidos_backtest
                        (id_partido, fecha, pais, local, visita, goles_l, goles_v, estado)
                        VALUES (?, ?, 'Sintetica', ?, ?, ?, ?, 'Liquidado')""",
                               (f'm{n}', f'202{temporada}-01-01 {n % 24:02d}:{n % 60:02d}',
                                loc, vis, poi(1.5), poi(1.15)))
    for col in ('sot_l', 'shots_l', 'corners_l', 'sot_v', 'shots_v', 'corners_v'):
        db.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col} INTEGER DEFAULT 0")
    db.execute("UPDATE partidos_backtest SET sot_l=0, sot_v=0")
    db.execute("ALTER TABLE ligas_stats ADD COLUMN coef_corner_calculado REAL")
    db.commit()
    return db


def _k(conn, prior):
    partidos = ev.cargar_partidos(conn.cursor())
    _, filas = ev.replay_con_pronosticos(conn, partidos, prior)
    return ev.metricas(filas, {}, {}, None)['Sintetica']


def test_prior_por_equipo_escala_correcta(liga_sintetica):
    nuevo = _k(liga_sintetica, True)
    viejo = _k(liga_sintetica, False)
    assert 0.92 < nuevo['k'] < 1.08, nuevo['k']
    assert viejo['k'] < 0.85, viejo['k']
    # Lambdas infladas subestiman el empate.
    assert viejo['px_pred'] < nuevo['px_pred']


def test_prior_liga_por_equipo_respeta_flag(db):
    assert md.prior_liga_por_equipo(260, 100) == pytest.approx(2.6)
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) "
               "VALUES ('ema_prior_por_equipo', 'global', 'TRUE', 'bool')")
    db.commit()
    assert md.prior_liga_por_equipo(260, 100) == pytest.approx(1.3)
    assert md.prior_liga_por_equipo(0, 0) == 1.4


def test_aplicar_migra_escala_flag_y_factores(liga_sintetica):
    db = liga_sintetica
    partidos = ev.cargar_partidos(db.cursor())
    viejo, _ = ev.reconstruir(db, partidos, prior_por_equipo=False)
    for (eq, liga), s in viejo.items():
        db.execute("INSERT INTO historial_equipos (equipo_norm, liga, ema_xg_favor_home, "
                   "ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away) VALUES (?,?,?,?,?,?)",
                   (eq, liga, s['fav_h'], s['con_h'], s['fav_a'], s['con_a']))
    db.execute("INSERT INTO historial_equipos (equipo_norm, liga, ema_xg_favor_home, "
               "ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away) "
               "VALUES ('sinstats', 'Sintetica', 2.0, 2.0, 2.0, 2.0)")
    db.commit()
    _, filas = ev.replay_con_pronosticos(db, partidos, True)
    ev.aplicar(db, partidos, ev.metricas(filas, {}, {}, None))

    cfg = dict(((c, s), v or t) for c, s, v, t in db.execute(
        "SELECT clave, scope, valor_real, valor_texto FROM config_motor_valores"))
    assert cfg[('ema_prior_por_equipo', 'global')] == 'TRUE'
    assert 0.9 < cfg[('factor_corr_xg_ou', 'Sintetica')] < 1.1
    media = db.execute("SELECT AVG(ema_xg_favor_home) FROM historial_equipos "
                       "WHERE equipo_norm != 'sinstats'").fetchone()[0]
    assert 1.2 < media < 1.6                      # escala de goles por equipo
    sin = db.execute("SELECT ema_xg_favor_home FROM historial_equipos "
                     "WHERE equipo_norm='sinstats'").fetchone()[0]
    assert sin < 1.8                              # reescalado, no quedo en 2.0


def test_rebuild_no_pisa_emas_sin_sofa_activo(db, monkeypatch):
    import sys
    from scripts import rebuild_ema_v2 as rb
    db.execute("INSERT INTO historial_equipos (equipo_norm, liga, ema_xg_favor_home) "
               "VALUES ('riverplate', 'Argentina', 1.77)")
    db.commit()
    monkeypatch.setattr(sys, 'argv', ['rebuild_ema_v2.py'])
    rb.main()
    assert db.execute("SELECT ema_xg_favor_home FROM historial_equipos").fetchone()[0] == 1.77

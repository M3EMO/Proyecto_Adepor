import random

import numpy as np

from src.nucleo.xg_pesos_dinamicos import kalman_update, replay_liga


def _poisson(rng, lam):
    k, p, u = 0, np.exp(-lam), rng.random()
    acc = p
    while u > acc:
        k += 1
        p *= lam / k
        acc += p
    return k


def _liga(rng, thetas):
    """Observaciones sinteticas: cada tramo usa su theta real."""
    obs = []
    for theta, n in thetas:
        for _ in range(n):
            x = np.array([rng.randint(0, 9), rng.randint(0, 12), rng.randint(0, 10)], float)
            obs.append((x, _poisson(rng, max(0.05, x @ np.array(theta)))))
    return obs


def test_dinamico_supera_al_estatico_cuando_los_pesos_reales_difieren_y_cambian():
    rng = random.Random(11)
    prior = (0.352, 0.010, 0.02)
    obs = _liga(rng, [((0.25, 0.03, 0.0), 600), ((0.40, 0.0, 0.03), 600)])
    r = replay_liga(obs, prior)
    assert r['ll_dinamico'] > r['ll_estatico']
    assert abs(r['theta'][0] - 0.40) < 0.06     # sigue al regimen final


def test_sin_senal_se_queda_cerca_del_prior():
    rng = random.Random(5)
    prior = (0.352, 0.010, 0.02)
    obs = _liga(rng, [(prior, 300)])
    r = replay_liga(obs, prior)
    assert np.allclose(r['theta'], prior, atol=0.05)


def test_kalman_update_no_muta_argumentos():
    theta, P = np.zeros(3), np.eye(3)
    kalman_update(theta, P, np.ones(3), 2.0)
    assert not theta.any() and np.array_equal(P, np.eye(3))


def test_script_shadow_registra_por_liga(db, monkeypatch):
    from scripts import xg_pesos_dinamicos_shadow as sh
    for col in ('sot_l', 'shots_l', 'corners_l', 'sot_v', 'shots_v', 'corners_v'):
        db.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col} INTEGER")
    db.execute("ALTER TABLE ligas_stats ADD COLUMN coef_corner_calculado REAL")
    for i in range(20):
        db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, goles_l, goles_v, estado, "
                   "sot_l, shots_l, corners_l, sot_v, shots_v, corners_v) VALUES "
                   "(?, ?, 'Argentina', 2, 1, 'Liquidado', 5, 12, 6, 3, 9, 4)",
                   (f'm{i}', f'2026-09-{i + 1:02d} 20:00'))
    db.commit()
    monkeypatch.setattr('sys.argv', ['xg_pesos_dinamicos_shadow.py'])
    sh.main()
    fila = db.execute("SELECT liga, n_obs, aplicado_produccion FROM xg_pesos_dinamicos_shadow").fetchone()
    assert fila == ('Argentina', 40, 0)

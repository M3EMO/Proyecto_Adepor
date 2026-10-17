"""
Pesos dinamicos del xG proxy por liga (SHADOW, bead adepor-thv.21, aprobado 2026-10-13).

Modelo por equipo y partido:  goles ~ Poisson(lambda),  lambda = x . theta
    x = (tiros al arco, tiros afuera/bloqueados, corners)
    theta = (b_sot, b_off, b_corner)

Filtro de Kalman por liga con olvido exponencial:
    prior theta_0 = coeficientes estaticos vigentes (pooling hacia lo global)
    P_pred = P / lam                     (lam=0.995 -> memoria efectiva ~200 observaciones)
    K = P_pred x / (x' P_pred x + r)
    theta += K (goles - x' theta)
    P = P_pred - K x' P_pred
Cada observacion se pronostica ANTES de actualizar: el log-lik es walk-forward.
"""
import math

import numpy as np

LAMBDA_OLVIDO = 0.995
R_OBS = 1.3            # varianza de goles condicional (~media Poisson por equipo)
SD_PRIOR = (0.10, 0.05, 0.05)
LAMBDA_MIN = 0.05


def _loglik_poisson(goles, lam):
    lam = max(LAMBDA_MIN, lam)
    return goles * math.log(lam) - lam - math.lgamma(goles + 1)


def kalman_update(theta, P, x, y, lam=LAMBDA_OLVIDO, r=R_OBS):
    """Un paso del filtro. Devuelve (theta, P) nuevos; no muta los argumentos."""
    P_pred = P / lam
    Px = P_pred @ x
    K = Px / (x @ Px + r)
    theta = theta + K * (y - x @ theta)
    P = P_pred - np.outer(K, Px)
    return theta, P


def replay_liga(observaciones, theta0, lam=LAMBDA_OLVIDO, r=R_OBS):
    """observaciones: lista cronologica de (x, goles). Devuelve metricas walk-forward.

    ll_estatico usa theta0 fijo; ll_dinamico usa el theta vigente antes de cada observacion.
    """
    theta0 = np.asarray(theta0, dtype=float)
    theta, P = theta0.copy(), np.diag(np.square(SD_PRIOR))
    ll_est = ll_din = 0.0
    for x, y in observaciones:
        x = np.asarray(x, dtype=float)
        ll_est += _loglik_poisson(y, float(x @ theta0))
        ll_din += _loglik_poisson(y, float(x @ theta))
        theta, P = kalman_update(theta, P, x, y, lam, r)
    n = len(observaciones)
    return {
        'n': n, 'theta': tuple(float(t) for t in theta),
        'll_estatico': ll_est / n if n else None,
        'll_dinamico': ll_din / n if n else None,
    }

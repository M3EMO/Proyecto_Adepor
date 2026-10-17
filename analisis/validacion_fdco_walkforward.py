"""
Validacion walk-forward del motor (auditoria 2026-10) contra cuotas reales de Pinnacle.

Datos: CSVs de football-data.co.uk (HS/HST/HC, goles, PSH/PSD/PSA y cierre PSCH/PSCD/PSCA).
Temporada 1 = calentamiento de EMAs; temporada 2 = evaluacion. Cada partido se pronostica
con el estado AS-OF (antes de absorber su resultado). Sin parametros ajustados a estos datos:
se usan los defaults del manifiesto.

Motores comparados (funciones reales de src/nucleo/motor_calculadora):
  viejo: prior EMA por partido + Hallazgo G + Fix #5, sin guarda de coherencia ni min PJ
  nuevo: prior EMA por equipo + probs puras + guarda de coherencia + min 5 PJ
  nuevo_dinamico: nuevo + pesos xG por liga via Kalman (SHADOW adepor-thv.21)

Uso:  python analisis/validacion_fdco_walkforward.py <dir_csvs> [salida.json]
"""
import csv
import json
import math
import os
import random
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('ADEPOR_DB', os.path.join(tempfile.mkdtemp(), 'vacia.db'))

import sqlite3  # noqa: E402
_c = sqlite3.connect(os.environ['ADEPOR_DB'])
_c.execute("CREATE TABLE IF NOT EXISTS config_motor_valores (clave TEXT, scope TEXT, valor_real REAL, "
           "valor_texto TEXT, tipo TEXT, fuente TEXT, bloqueado INTEGER, fecha_actualizacion TEXT)")
_c.close()

import numpy as np  # noqa: E402

import src.nucleo.motor_calculadora as mc  # noqa: E402
from src.nucleo import xg_pesos_dinamicos as xd  # noqa: E402

LIGAS = {'E0': 'Inglaterra', 'SP1': 'Espana', 'I1': 'Italia', 'D1': 'Alemania'}
ALFA = {'Inglaterra': 0.12}            # motor_data ALFA_EMA_POR_LIGA; resto 0.15
N0 = 5
BETA_SOT, BETA_OFF, COEF_CORNER = 0.352, 0.010, 0.02
FACTOR_OU_VIEJO = 0.627


def xg_proxy(goles, sot, shots, corners, theta=None):
    b_sot, b_off, b_corner = theta if theta is not None else (BETA_SOT, BETA_OFF, COEF_CORNER)
    xg = sot * b_sot + max(0, shots - sot) * b_off + corners * b_corner
    if xg == 0 and goles > 0:
        return float(goles)
    return 0.7 * xg + 0.3 * goles


def efecto_marcador(xg, propio, rival):
    return xg * 0.95 if propio > rival else (xg * 1.05 if propio < rival else xg)


def leer(path):
    out = []
    for r in csv.DictReader(open(path, encoding='latin-1')):
        try:
            fecha = datetime.strptime(r['Date'], '%d/%m/%Y' if len(r['Date']) == 10 else '%d/%m/%y')
            fila = {k: float(r[k]) for k in ('FTHG', 'FTAG', 'HS', 'AS', 'HST', 'AST', 'HC', 'AC')}
            odds = {k: float(r[k]) for k in ('PSH', 'PSD', 'PSA', 'PSCH', 'PSCD', 'PSCA')
                    if r.get(k) not in (None, '')}
            ou = {k: float(r[k]) for k in ('P>2.5', 'P<2.5', 'PC>2.5', 'PC<2.5') if r.get(k) not in (None, '')}
        except (KeyError, ValueError):
            continue
        out.append({'fecha': fecha, 'h': r['HomeTeam'], 'a': r['AwayTeam'], **fila, 'odds': odds, 'ou': ou})
    return sorted(out, key=lambda p: p['fecha'])


class Ema:
    """Estado EMA por equipo, igual que motor_data.actualizar_estado (largo, sin corto)."""

    def __init__(self, por_equipo, alfa, dinamico=False):
        self.por_equipo, self.alfa = por_equipo, alfa
        # Pesos xG por liga via Kalman (src/nucleo/xg_pesos_dinamicos), as-of cada partido.
        self.kalman = ((np.array((BETA_SOT, BETA_OFF, COEF_CORNER)), np.diag(np.square(xd.SD_PRIOR)))
                       if dinamico else None)
        self.eq = defaultdict(lambda: {'fh': 1.4, 'ch': 1.4, 'nh': 0, 'fa': 1.4, 'ca': 1.4, 'na': 0})
        self.goles = self.n = 0

    def prior(self):
        if self.n == 0:
            return 1.4
        return self.goles / self.n / (2.0 if self.por_equipo else 1.0)

    def lambdas(self, h, a):
        L, V = self.eq[h], self.eq[a]
        return (L['fh'] + V['ca']) / 2, (V['fa'] + L['ch']) / 2, L['nh'], V['na']

    def actualizar(self, p):
        prior, a = self.prior(), self.alfa
        th = self.kalman[0] if self.kalman else None
        xl = efecto_marcador(xg_proxy(p['FTHG'], p['HST'], p['HS'], p['HC'], th), p['FTHG'], p['FTAG'])
        xv = efecto_marcador(xg_proxy(p['FTAG'], p['AST'], p['AS'], p['AC'], th), p['FTAG'], p['FTHG'])
        if self.kalman:
            t, P = self.kalman
            for sot, shots, corners, g in ((p['HST'], p['HS'], p['HC'], p['FTHG']),
                                           (p['AST'], p['AS'], p['AC'], p['FTAG'])):
                t, P = xd.kalman_update(t, P, np.array((sot, max(0, shots - sot), corners)), g)
            self.kalman = (t, P)
        for eq, f, c, kf, kc, kn in ((p['h'], xl, xv, 'fh', 'ch', 'nh'), (p['a'], xv, xl, 'fa', 'ca', 'na')):
            s = self.eq[eq]
            w = N0 / (N0 + s[kn])
            s[kf] = round((1 - w) * (f * a + s[kf] * (1 - a)) + w * prior, 3)
            s[kc] = round((1 - w) * (c * a + s[kc] * (1 - a)) + w * prior, 3)
            s[kn] += 1
        self.goles += p['FTHG'] + p['FTAG']
        self.n += 1


def probs(lam, mu, factor_ou):
    p1, px, p2 = mc._calcular_probs_poisson_dc(lam, mu, mc.RHO_FALLBACK)
    a, b = lam * factor_ou, mu * factor_ou
    po = sum(mc.poisson(i, a) * mc.poisson(j, b) * mc.tau(i, j, a, b, mc.RHO_FALLBACK)
             for i in range(10) for j in range(10) if i + j > 2)
    tot = sum(mc.poisson(i, a) * mc.poisson(j, b) * mc.tau(i, j, a, b, mc.RHO_FALLBACK)
              for i in range(10) for j in range(10))
    return p1, px, p2, po / tot


def decidir(motor, p1, px, p2, odds, liga, n_min_ok):
    """Pick 1X2 con la capa de decision real. Devuelve (pick, cuota) o None."""
    c1, cx, c2 = odds['PSH'], odds['PSD'], odds['PSA']
    viejo = motor == 'viejo'
    mc.RATIO_MIN_IMPLICITA = 0.0 if viejo else 0.5
    pick, ev, cuota = mc.evaluar_mercado_1x2(p1, px, p2, c1, cx, c2, liga=liga)
    if '[APOSTAR]' not in pick:
        return None
    prob = {'LOCAL': p1, 'EMPATE': px, 'VISITA': p2}[pick.split()[-1]]
    if prob < mc.FLOOR_PROB_MIN or ev < mc.min_ev_escalado(prob):
        return None
    if not viejo and not n_min_ok:
        return None
    return pick.split()[-1], cuota


def correr(partidos_por_liga):
    res = {m: {'picks': [], 'brier': [], 'll': [], 'brier_mkt': [], 'll_mkt': [], 'px': [], 'k': [0.0, 0.0]}
           for m in ('viejo', 'nuevo', 'nuevo_dinamico')}
    for liga, (warm, evalua) in partidos_por_liga.items():
        emas = {m: Ema(m != 'viejo', ALFA.get(liga, 0.15), dinamico=(m == 'nuevo_dinamico')) for m in res}
        hg = {'n': 0, 'loc': 0}
        for fase, partidos in (('warm', warm), ('eval', evalua)):
            for p in partidos:
                o = (p['FTHG'] > p['FTAG'], p['FTHG'] == p['FTAG'], p['FTHG'] < p['FTAG'])
                tiene_odds = all(k in p['odds'] for k in ('PSH', 'PSD', 'PSA', 'PSCH', 'PSCD', 'PSCA'))
                for m, ema in emas.items():
                    lam, mu, nh, na = ema.lambdas(p['h'], p['a'])
                    if fase == 'eval' and tiene_odds:
                        p1, px, p2, _ = probs(lam, mu, 1.0)
                        if m == 'viejo':
                            hg_data = ({liga: {'n': hg['n'], 'freq_local': hg['loc'] / hg['n']}}
                                       if hg['n'] >= mc.N_MIN_HALLAZGO_G else {})
                            p1, px, p2 = mc.corregir_calibracion(*mc.aplicar_hallazgo_g(p1, px, p2, liga, hg_data))
                        r = res[m]
                        r['brier'].append(sum((a - b) ** 2 for a, b in zip((p1, px, p2), o)))
                        r['ll'].append(-math.log(max(1e-12, (p1, px, p2)[o.index(True)])))
                        r['px'].append(px)
                        r['k'][0] += p['FTHG'] + p['FTAG']
                        r['k'][1] += lam + mu
                        q = [1 / p['odds'][k] for k in ('PSCH', 'PSCD', 'PSCA')]
                        q = [x / sum(q) for x in q]
                        r['brier_mkt'].append(sum((a - b) ** 2 for a, b in zip(q, o)))
                        r['ll_mkt'].append(-math.log(q[o.index(True)]))
                        d = decidir(m, p1, px, p2, p['odds'], liga, min(nh, na) >= 5)
                        if d:
                            pick, cuota = d
                            idx = ('LOCAL', 'EMPATE', 'VISITA').index(pick)
                            cierre = p['odds'][('PSCH', 'PSCD', 'PSCA')[idx]]
                            r['picks'].append({'liga': liga, 'gano': o[idx], 'cuota': cuota,
                                               'clv': cuota / cierre - 1})
                    ema.actualizar(p)
                hg['n'] += 1
                hg['loc'] += o[0]
    return res


def resumir(r, semilla=7):
    picks = r['picks']
    n = len(picks)
    pl = [(x['cuota'] - 1) if x['gano'] else -1.0 for x in picks]
    rng = random.Random(semilla)
    boots = sorted(sum(rng.choice(pl) for _ in pl) / n for _ in range(2000)) if n else []
    media = lambda v: sum(v) / len(v) if v else None  # noqa: E731
    return {
        'n_partidos': len(r['brier']), 'k_goles_sobre_lambda': r['k'][0] / r['k'][1] if r['k'][1] else None,
        'p_empate_medio': media(r['px']),
        'brier_modelo': media(r['brier']), 'brier_mercado_cierre': media(r['brier_mkt']),
        'logloss_modelo': media(r['ll']), 'logloss_mercado_cierre': media(r['ll_mkt']),
        'n_picks': n, 'hit': media([x['gano'] for x in picks]),
        'yield_plano': media(pl), 'yield_ic95': (boots[50], boots[1949]) if n else None,
        'clv_medio': media([x['clv'] for x in picks]),
        'por_liga': {lg: {'n': len(v), 'yield': media([(x['cuota'] - 1) if x['gano'] else -1 for x in v])}
                     for lg in LIGAS.values()
                     for v in [[x for x in picks if x['liga'] == lg]] if v},
    }


def mezcla_con_pinnacle(partidos_por_liga):
    """Peso optimo w de p = q_apertura^(1-w) * p_modelo^w (motor nuevo), elegido en la 1ra mitad
    de la temporada de evaluacion y medido en la 2da. w=0: el modelo no agrega informacion."""
    filas = []
    for liga, (warm, evalua) in partidos_por_liga.items():
        ema = Ema(True, ALFA.get(liga, 0.15))
        for fase, partidos in (('warm', warm), ('eval', evalua)):
            for p in partidos:
                lam, mu, nh, na = ema.lambdas(p['h'], p['a'])
                if fase == 'eval' and all(k in p['odds'] for k in ('PSH', 'PSD', 'PSA')) and min(nh, na) >= 5:
                    q = [1 / p['odds'][k] for k in ('PSH', 'PSD', 'PSA')]
                    o = (p['FTHG'] > p['FTAG'], p['FTHG'] == p['FTAG'], p['FTHG'] < p['FTAG']).index(True)
                    filas.append((p['fecha'], probs(lam, mu, 1.0)[:3], [x / sum(q) for x in q], o))
                ema.actualizar(p)
    filas.sort(key=lambda f: f[0])
    mitad = len(filas) // 2

    def ll(fs, w):
        tot = 0.0
        for _, pm, q, o in fs:
            z = [(qi ** (1 - w)) * (pi ** w) for qi, pi in zip(q, pm)]
            tot -= math.log(z[o] / sum(z))
        return tot / len(fs)
    grilla = [i / 20 for i in range(11)]
    w = min(grilla, key=lambda x: ll(filas[:mitad], x))
    return {'n': len(filas), 'w_optimo_1ra_mitad': w,
            'logloss_2da_mercado': ll(filas[mitad:], 0.0), 'logloss_2da_mezcla': ll(filas[mitad:], w),
            'logloss_2da_modelo': ll(filas[mitad:], 1.0)}


def main():
    d = Path(sys.argv[1])
    datos = {}
    for cod, liga in LIGAS.items():
        datos[liga] = (leer(d / f'{cod}_2324.csv'), leer(d / f'{cod}_2425.csv'))
    out = {m: resumir(r) for m, r in correr(datos).items()}
    out['mezcla_modelo_pinnacle'] = mezcla_con_pinnacle(datos)
    texto = json.dumps(out, indent=2, ensure_ascii=False, default=float)
    print(texto)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(texto, encoding='utf-8')


if __name__ == '__main__':
    main()

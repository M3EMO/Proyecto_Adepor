"""
E13 (bead adepor-9q0, protocolo pre-registrado el 2026-10-26): las tarjetas de los jugadores del once
y del arbitro, agregan informacion sobre el total de tarjetas del partido por encima del equipo?

M0 equipo, M1 = M0 + arbitro, M2 = M1 + jugadores. Binomial negativa (enlace log) ajustada en una
temporada y evaluada en la siguiente. Metrica: diferencia de NLL media por partido en prueba.

Uso:  python -I analisis/tarjetas_jugadores.py [salida.json]
"""
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import nbinom

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))  # -I quita el directorio del script del path
from divisiones_pinnacle import ic  # noqa: E402  (bootstrap 2000, semilla 42)

ESTRATOS = {'eu': {'ligas': (47, 87, 54, 55, 53), 'train': '2024', 'test': '2025'},
            'arg': {'ligas': (112,), 'train': '2024', 'test': '2025'}}
MIN_PREVIOS, V_EQUIPO, K_ARB, PRIOR_MIN, NIVEL_IC, MIN_LIGA = 3, 10, 10, 900, 98.75, 10
MODELOS = {'M0': [0, 1, 2], 'M1': [0, 1, 2, 3], 'M2': [0, 1, 2, 3, 4, 5]}
LINEAS = (3.5, 4.5, 5.5)


def temporada(lid, fecha):
    return fecha[:4] if lid == 112 else str(int(fecha[:4]) - (int(fecha[5:7]) < 7))


def minutos(lineup_equipo, rojas):
    """{id jugador: minutos} desde la alineacion; la roja corta los minutos. shortcut: partido de 90'."""
    out = {}
    for k in ('starters', 'subs'):
        for p in lineup_equipo.get(k, []):
            sub = {s['type']: s['time'] for s in (p.get('performance') or {}).get('substitutionEvents', [])}
            ini = 0 if k == 'starters' else sub.get('subIn')
            if ini is None:
                continue
            fin = min(sub.get('subOut', 90), rojas.get(p['id'], 90), 90)
            out[p['id']] = max(fin - ini, 0)
    return out


def cargar(ligas):
    """Partidos de liga terminados con eventos de tarjeta, en orden cronologico."""
    out = []
    for fl in glob.glob(str(ROOT / 'data/fotmob/raw/*.json')):
        d = json.load(open(fl, encoding='utf-8'))
        g, c = d['general'], d['content'] or {}
        lid = next((x for x in (g.get('leagueId'), g.get('parentLeagueId')) if x in ligas), None)
        mf, lu = c.get('matchFacts') or {}, c.get('lineup') or {}
        evs = ((mf.get('events') or {}).get('events')) or []
        if lid is None or not g.get('finished') or not lu.get('homeTeam') or not any(e['type'] == 'Card' for e in evs):
            continue
        cartas = [e for e in evs if e['type'] == 'Card']
        rojas = {e['player']['id']: e['time'] for e in cartas if e.get('card') in ('Red', 'YellowRed')}
        por_jug = defaultdict(int)
        for e in cartas:
            por_jug[e['player']['id']] += 1
        lus = (lu['homeTeam'], lu['awayTeam'])
        out.append({'lid': lid, 'fecha': g['matchTimeUTCDate'], 'temp': temporada(lid, g['matchTimeUTCDate']),
                    'equipos': [t['id'] for t in d['header']['teams']],
                    'arbitro': ((mf.get('infoBox') or {}).get('Referee') or {}).get('text'),
                    'tarj': [sum(e['isHome'] for e in cartas), sum(not e['isHome'] for e in cartas)],
                    'titulares': [[p['id'] for p in x.get('starters', [])] for x in lus],
                    'minutos': [minutos(x, rojas) for x in lus], 'por_jug': por_jug})
    return sorted(out, key=lambda m: m['fecha'])


def tasa_encogida(n, media, n_prior, m_prior):
    return (n * media + n_prior * m_prior) / (n + n_prior)


def con_variables(partidos):
    """Agrega 'x' (seis variables en log, o None) a cada partido usando solo partidos previos."""
    hist_eq = defaultdict(list)            # (liga, equipo) -> tarjetas recibidas por partido
    ult_once = {}                          # (liga, equipo) -> titulares del partido anterior
    arb = defaultdict(lambda: [0, 0])      # arbitro -> [partidos, tarjetas]
    jug = defaultdict(lambda: [0, 0.0])    # jugador -> [tarjetas, minutos]
    liga = defaultdict(lambda: [0, 0, 0, 0.0])  # (liga, temp) o (liga, '*') -> [partidos, tarjetas, tarj. jugadores, minutos]
    for m in partidos:
        claves = [(m['lid'], e) for e in m['equipos']]
        ls = liga[(m['lid'], m['temp'])]
        ls = ls if ls[0] >= MIN_LIGA else liga[(m['lid'], '*')]  # inicio de temporada: toda la historia previa de la liga
        m['x'] = None
        if ls[0] and ls[3] and all(len(hist_eq[k]) >= MIN_PREVIOS and k in ult_once for k in claves):
            m_liga, m_jug90 = ls[1] / ls[0], ls[2] / ls[3] * 90
            na, ta = arb[m['arbitro']] if m['arbitro'] else (0, 0)
            r_arb = tasa_encogida(na, ta / na if na else 0, K_ARB, m_liga)
            once = [sum(tasa_encogida(jug[p][1] / 90, jug[p][0] / jug[p][1] * 90 if jug[p][1] else 0, PRIOR_MIN / 90, m_jug90)
                        for p in ult_once[k]) for k in claves]
            eq = [np.mean(hist_eq[k][-V_EQUIPO:]) for k in claves]
            # shortcut: piso 0.1 para el log de un equipo sin tarjetas en su ventana; revisar si aparecen muchos
            m['x'] = list(np.log(np.maximum([eq[0], eq[1], m_liga, r_arb, once[0], once[1]], 0.1)))
        total = sum(m['tarj'])
        for lado, k in enumerate(claves):
            hist_eq[k].append(m['tarj'][lado])
            ult_once[k] = m['titulares'][lado]
        if m['arbitro']:
            arb[m['arbitro']][0] += 1
            arb[m['arbitro']][1] += total
        tj, mn = 0, 0.0
        for lado in (0, 1):
            for p, mins in m['minutos'][lado].items():
                c = m['por_jug'].get(p, 0)
                jug[p][0] += c
                jug[p][1] += mins
                tj, mn = tj + c, mn + mins
        for key in ((m['lid'], m['temp']), (m['lid'], '*')):
            v = liga[key]
            v[0], v[1], v[2], v[3] = v[0] + 1, v[1] + total, v[2] + tj, v[3] + mn
    return partidos


def nll_nb(y, mu, log_alpha):
    """NLL por partido de la binomial negativa NB2 (var = mu + alpha mu^2)."""
    r = np.exp(-log_alpha)
    return -(gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu)))


def ajustar(X, y):
    """Devuelve (beta con intercepto primero, log_alpha) por maxima verosimilitud."""
    Z = np.column_stack([np.ones(len(X)), X])

    def f(th):
        return nll_nb(y, np.exp(Z @ th[:-1]), th[-1]).mean()
    th0 = np.r_[np.log(y.mean()), np.zeros(X.shape[1]), np.log(0.1)]
    # piso en log_alpha: las tarjetas pueden venir casi Poisson y alpha -> 0
    bounds = [(None, None)] * (X.shape[1] + 1) + [(-12, 3)]
    res = minimize(f, th0, method='L-BFGS-B', bounds=bounds)
    assert res.success, res.message
    return res.x[:-1], res.x[-1]


def predecir(beta, X):
    return np.exp(np.column_stack([np.ones(len(X)), X]) @ beta)


def calibracion(y, mu, log_alpha):
    r = np.exp(-log_alpha)
    out = {}
    for linea in LINEAS:
        p = nbinom.sf(int(linea), r, r / (r + mu))
        obs = (y > linea).astype(float)
        cortes = np.quantile(p, [0.2, 0.4, 0.6, 0.8])
        q = np.searchsorted(cortes, p, side='right')
        out[f'over_{linea}'] = {'p_media': float(p.mean()), 'frecuencia': float(obs.mean()),
                                'brier': float(np.mean((p - obs) ** 2)),
                                'quintiles': [{'n': int((q == i).sum()), 'p_media': float(p[q == i].mean()),
                                               'frecuencia': float(obs[q == i].mean())} for i in range(5)]}
    return out


def estudiar(nombre, cfg):
    ps = con_variables(cargar(cfg['ligas']))
    data = {}
    for parte in ('train', 'test'):
        sel = [m for m in ps if m['temp'] == cfg[parte] and m['x'] is not None]
        data[parte] = (np.array([m['x'] for m in sel]), np.array([sum(m['tarj']) for m in sel], float))
    (Xtr, ytr), (Xte, yte) = data['train'], data['test']
    res = {'n_partidos': len(ps), 'n_train': len(ytr), 'n_test': len(yte),
           'temporadas': {'train': cfg['train'], 'test': cfg['test']},
           'sin_arbitro_test': sum(1 for m in ps if m['temp'] == cfg['test'] and m['x'] is not None and not m['arbitro']),
           'tarjetas_media_test': float(yte.mean()), 'varianza_test': float(yte.var()), 'modelos': {}}
    nll, fits = {}, {}
    for mod, cols in MODELOS.items():
        beta, la = ajustar(Xtr[:, cols], ytr)
        mu = predecir(beta, Xte[:, cols])
        nll[mod], fits[mod] = nll_nb(yte, mu, la), (mu, la)
        res['modelos'][mod] = {'beta': [float(b) for b in beta], 'alpha': float(np.exp(la)),
                               'nll_test': float(nll[mod].mean())}
    for a, b in (('M1', 'M0'), ('M2', 'M1')):
        r = ic(nll[a] - nll[b], NIVEL_IC)
        res[f'{a}-{b}'] = {**r, 'pasa': r[f'ic{NIVEL_IC}'][1] < 0}
    mejor = min(nll, key=lambda k: nll[k].mean())
    res['calibracion'] = {'modelo': mejor, **calibracion(yte, *fits[mejor])}
    return res


def _autochequeo():
    y, mu, la = np.array([0., 3., 7.]), np.array([2.5, 4.0, 5.0]), np.log(0.2)
    r = np.exp(-la)
    assert np.allclose(nll_nb(y, mu, la), -nbinom.logpmf(y, r, r / (r + mu)))
    rng = np.random.default_rng(42)
    X = rng.normal(size=(4000, 1))
    mu = np.exp(1.5 + 0.4 * X[:, 0])
    ys = rng.negative_binomial(1 / 0.15, (1 / 0.15) / (1 / 0.15 + mu)).astype(float)
    beta, la = ajustar(X, ys)
    assert abs(beta[0] - 1.5) < 0.05 and abs(beta[1] - 0.4) < 0.05 and abs(np.exp(la) - 0.15) < 0.05
    assert tasa_encogida(0, 0, 10, 4.5) == 4.5 and tasa_encogida(10, 6.0, 10, 4.0) == 5.0
    lu = {'starters': [{'id': 1, 'performance': {'substitutionEvents': [{'type': 'subOut', 'time': 60}]}},
                       {'id': 2}, {'id': 3}],
          'subs': [{'id': 4, 'performance': {'substitutionEvents': [{'type': 'subIn', 'time': 60}]}}, {'id': 5}]}
    assert minutos(lu, {3: 30}) == {1: 60, 2: 90, 3: 30, 4: 30}
    assert temporada(47, '2025-01-10') == '2024' and temporada(47, '2025-08-10') == '2025'
    assert temporada(112, '2025-01-10') == '2025'


def main():
    _autochequeo()
    salida = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'analisis/tarjetas_jugadores.json')
    out = {'bead': 'adepor-9q0', 'nivel_ic': NIVEL_IC, 'regla': 'un paso pasa si el limite superior de su IC < 0',
           'estratos': {n: estudiar(n, c) for n, c in ESTRATOS.items()}}
    Path(salida).write_text(json.dumps(out, indent=2))
    for n, r in out['estratos'].items():
        print(n, r['n_train'], r['n_test'], {k: r[k] for k in ('M1-M0', 'M2-M1')})


if __name__ == '__main__':
    main()

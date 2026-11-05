"""
E14 (bead adepor-jjx, protocolo fijado el 2026-10-26 con cuotas_forward_totales vacia): el M1 de tarjetas
de E13 (equipo + arbitro), con el nivel recalibrado, le gana a las lineas de tarjetas de bet365 AR?

Paso 1 (historico): M1 de Argentina ajustado en 2024+2025. Antes de cada partido se reestima solo el
intercepto, para que la media de mu de los ultimos 100 partidos terminados iguale su media observada.
Prueba en 2026. Pasa si (a) su NLL media no supera la de M1 sin recalibrar y (b) |P media - frecuencia|
<= 0.03 en over 3.5, 4.5 y 5.5.
Paso 2 (forward): log-loss del modelo contra el cierre sin margen de bet365 AR en la linea de referencia.
Se abre solo si pasa el paso 1. Cruza cuotas_forward_totales con la captura previa del arbitro
(src/ingesta/motor_arbitros_fotmob.py) y con el partido terminado de data/fotmob/raw. Lee la base en modo ro.

Uso:  python -I analisis/tarjetas_forward.py [salida.json]
"""
import json
import sqlite3
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.stats import nbinom

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))  # -I quita el directorio del script del path
from divisiones_pinnacle import ic  # noqa: E402  (bootstrap 2000, semilla 42)
from tarjetas_jugadores import LINEAS, MODELOS, ajustar, calibracion, cargar, con_variables, nll_nb, predecir  # noqa: E402
from clv_bet365ar import PARTICIPANTES, cruzar  # noqa: E402  (criterio de cruce de E8, banco de nombres)
from src.comun.config_sistema import DB_NAME  # noqa: E402  (clv_bet365ar agrega la raiz al path)

TRAIN, TEST, VENTANA, TOL_CALIB = ('2024', '2025'), '2026', 100, 0.03
CASA, UMBRAL_EV, N_PARADA, FECHA_PARADA = 'bet365.bet.ar', 0.05, 300, '2027-06-30'
# El paso 1 se decidio el 2026-10-26 con los partidos bajados ese dia; el ultimo es del 2026-10-20.
# Los partidos que baja despues motor_arbitros_fotmob no entran a la prueba del paso 1.
CORTE_PASO1 = '2026-10-21'
TORNEO = 155  # Liga Profesional en OddsPapi
ARBITROS = ROOT / 'data' / 'fotmob' / 'prepartido' / 'arbitros.jsonl'
RAW = ROOT / 'data' / 'fotmob' / 'raw'


def recalibrar(mu0, y, fechas, ventana=VENTANA):
    """mu con el intercepto reestimado antes de cada partido: mu0 * suma(y) / suma(mu0) de los ultimos
    `ventana` partidos con kickoff estrictamente anterior. NaN si todavia no hay `ventana` previos."""
    out = np.full(len(mu0), np.nan)
    for i, f in enumerate(fechas):
        j = bisect_left(fechas, f)
        if j >= ventana:
            out[i] = mu0[i] * y[j - ventana:j].sum() / mu0[j - ventana:j].sum()
    return out


def clave(m):
    return m['fecha'], tuple(m['equipos'])


def modelo(arbitro_previo):
    """M1 de Argentina ajustado en TRAIN y mu (sin recalibrar y recalibrado) de cada partido con variables.
    arbitro_previo: {clave: arbitro designado antes del partido}; reemplaza al arbitro real en el forward."""
    ps = cargar((112,))
    for m in ps:
        m['arbitro'] = arbitro_previo.get(clave(m), m['arbitro'])
    ps = [m for m in con_variables(ps) if m['x'] is not None]
    X = np.array([m['x'] for m in ps])[:, MODELOS['M1']]
    y = np.array([sum(m['tarj']) for m in ps], float)
    tr = np.isin([m['temp'] for m in ps], TRAIN)
    beta, la = ajustar(X[tr], y[tr])
    mu0 = predecir(beta, X)
    return {'ps': ps, 'y': y, 'tr': tr, 'beta': beta, 'la': la, 'mu0': mu0,
            'mu_r': recalibrar(mu0, y, [m['fecha'] for m in ps])}


def paso1(mod):
    ps, y, tr, beta, la, mu0, mu_r = (mod[k] for k in ('ps', 'y', 'tr', 'beta', 'la', 'mu0', 'mu_r'))
    te = np.array([m['temp'] == TEST and m['fecha'] < CORTE_PASO1 for m in ps])
    assert not np.isnan(mu_r[te]).any()
    nll0, nll_r = nll_nb(y[te], mu0[te], la), nll_nb(y[te], mu_r[te], la)
    cal0, cal_r = calibracion(y[te], mu0[te], la), calibracion(y[te], mu_r[te], la)
    a = bool(nll_r.mean() <= nll0.mean())
    desvio = {k: v['p_media'] - v['frecuencia'] for k, v in cal_r.items()}
    b = all(abs(d) <= TOL_CALIB for d in desvio.values())
    return {'n_train': int(tr.sum()), 'n_test': int(te.sum()), 'temporadas': {'train': TRAIN, 'test': TEST},
            'ventana': VENTANA, 'beta_M1': [float(x) for x in beta], 'alpha': float(np.exp(la)),
            'tarjetas_media_train': float(y[tr].mean()), 'tarjetas_media_test': float(y[te].mean()),
            'mu_media_test': {'sin_recalibrar': float(mu0[te].mean()), 'recalibrado': float(mu_r[te].mean())},
            'desplazamiento_intercepto_test': [float(np.log(mu_r[te] / mu0[te]).min()),
                                               float(np.log(mu_r[te] / mu0[te]).max())],
            'nll_test': {'sin_recalibrar': float(nll0.mean()), 'recalibrado': float(nll_r.mean())},
            'recal-sin': ic(nll_r - nll0, 95),  # descriptivo: la regla (a) compara medias
            'calibracion': {'sin_recalibrar': cal0, 'recalibrado': cal_r},
            'regla': {'a_nll': a, 'b_calibracion': b, 'desvio_p_menos_frecuencia': desvio, 'pasa': a and b}}


# ---- Paso 2: cruce y evaluacion forward (sin cuotas de tarjetas al 2026-10-26) ----

def leer_arbitros(lineas):
    """{match_id FotMob: {inicio_utc, local, visita, ts_arbitro, arbitro}} desde arbitros.jsonl. ts_arbitro es
    la primera captura con arbitro publicado. shortcut: usa ese primer arbitro aunque despues cambie."""
    out = {}
    for x in sorted(map(json.loads, lineas), key=lambda x: x['ts_captura']):
        a = out.setdefault(x['match_id'], {'ts_arbitro': None, 'arbitro': None})
        a.update(inicio_utc=x['inicio_utc'], local=x['local'], visita=x['visita'])
        if x['arbitro'] and a['ts_arbitro'] is None:
            a['ts_arbitro'], a['arbitro'] = x['ts_captura'], x['arbitro']
    return out


def cruzar_fixtures(fixtures, arbitros):
    """{fixture_id OddsPapi: match_id FotMob}. fixtures: {fixture_id: {inicio_utc, local, visita}} con nombres
    de OddsPapi. cruzar (E8) pide kickoff a 3 h o menos y nombres parecidos tras el banco de nombres."""
    # cruzar compara contra la hora de Argentina (UTC-3), como en partidos_backtest
    cands = [{'id': mid, 'local': a['local'], 'visita': a['visita'],
              'fecha': (datetime.strptime(a['inicio_utc'][:16], '%Y-%m-%dT%H:%M') - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M')}
             for mid, a in arbitros.items()]
    out = {}
    for fid, f in fixtures.items():
        c = cruzar({**f, 'pais': 'Argentina'}, cands)
        if c:
            out[fid] = c['id']
    return out


def datos_forward(conn):
    """(fixtures, capturas) de bet365 AR en la Liga Profesional. fixtures sale de la ultima captura 1X2 de
    cuotas_forward; capturas = {fixture_id: [(ts, linea, over, under)]} de tarjetas."""
    nombres = json.loads(PARTICIPANTES.read_text(encoding='utf-8'))
    fx = {}
    for fid, ini, loc, vis in conn.execute('SELECT fixture_id, inicio_utc, local_id, visita_id FROM cuotas_forward '
                                           'WHERE torneo_id = ? AND casa = ? ORDER BY ts_captura', (TORNEO, CASA)):
        fx[fid] = {'inicio_utc': ini, 'local': nombres.get(str(loc), ''), 'visita': nombres.get(str(vis), '')}
    caps = defaultdict(list)
    for ts, fid, *c in conn.execute('SELECT ts_captura, fixture_id, linea, cuota_over, cuota_under FROM cuotas_forward_totales '
                                    "WHERE tipo = 'tarjetas' AND casa = ?", (CASA,)):
        if fid in fx:
            caps[fid].append((ts, *c))
    return fx, dict(caps)


def cruce_forward(fx, caps, arbitros):
    """(arbitro_previo, base, conteos). base = {clave del partido FotMob: datos de evaluar_partido sin mu ni y}.
    Entra un partido cruzado, con arbitro publicado y con el partido terminado en data/fotmob/raw."""
    cruce = cruzar_fixtures({f: fx[f] for f in caps}, arbitros)
    previo, base = {}, {}
    for fid, mid in cruce.items():
        raw = RAW / f'{mid}.json'
        if arbitros[mid]['ts_arbitro'] is None or not raw.exists():
            continue
        d = json.loads(raw.read_text(encoding='utf-8'))
        if not d['general'].get('finished'):
            continue
        k = (d['general']['matchTimeUTCDate'], tuple(t['id'] for t in d['header']['teams']))
        previo[k] = arbitros[mid]['arbitro']
        base[k] = {'inicio': fx[fid]['inicio_utc'], 'ts_arbitro': arbitros[mid]['ts_arbitro'], 'capturas': caps[fid]}
    return previo, base, {'n_fixtures_con_tarjetas': len(caps), 'n_cruzados': len(cruce), 'n_con_resultado': len(base)}


def paso2(mod, base, conteos):
    # shortcut: cargar (E13) omite partidos sin tarjetas (~1 % con mu 5); revisar si el forward los necesita
    partidos = [{**base[clave(m)], 'mu': mu, 'log_alpha': mod['la'], 'y': y}
                for m, mu, y in zip(mod['ps'], mod['mu_r'], mod['y']) if clave(m) in base]
    return {**conteos, 'n_con_mu': len(partidos), **evaluar_forward(partidos)}


def p_over(mu, log_alpha, linea):
    r = np.exp(-log_alpha)
    return float(nbinom.sf(int(linea), r, r / (r + mu)))


def sin_margen(over, under):
    """P(over) justa, metodo proporcional de dos resultados."""
    return (1 / over) / (1 / over + 1 / under)


def evaluar_partido(p):
    """p: {'mu', 'log_alpha', 'y', 'inicio', 'ts_arbitro', 'capturas': [(ts, linea, over, under)]} de bet365 AR.
    Devuelve None si el partido se descarta; si no, la diferencia de log-loss y el pick descriptivo."""
    if p.get('ts_arbitro') is None:
        return None
    # Enmienda del usuario (2026-10-26, sin datos forward vistos): la referencia es la primera captura
    # posterior a la publicacion del arbitro. FotMob lo publica 1-2 dias antes; bet365 abre hasta 10.
    # shortcut: solo lineas .5; una linea entera tiene push y el proporcional de dos resultados no aplica
    # [:19]: ts_captura termina en 'Z' e inicio_utc en '.000Z'
    caps = sorted(c for c in p['capturas']
                  if p['ts_arbitro'][:19] <= c[0][:19] < p['inicio'][:19] and c[1] % 1 == 0.5)
    if not caps:
        return None
    ts0 = caps[0][0]
    primera = [c for c in caps if c[0] == ts0]
    ref = min(primera, key=lambda c: (abs(sin_margen(c[2], c[3]) - 0.5), c[1]))

    def cierre(linea):
        # posterior a la primera captura (como en E12): si no, el cierre seria la apertura
        post = [c for c in caps if c[1] == linea and c[0] > ts0]
        return post[-1] if post else None

    out = {'inicio': p['inicio'], 'linea_ref': ref[1], 'd_logloss': None, 'pick': None}
    c_ref = cierre(ref[1])
    if c_ref is not None:
        o = p['y'] > ref[1]
        pm, pc = p_over(p['mu'], p['log_alpha'], ref[1]), sin_margen(c_ref[2], c_ref[3])
        out['d_logloss'] = float(-np.log(pm if o else 1 - pm) + np.log(pc if o else 1 - pc))
    evs = []
    for _, linea, over, under in primera:
        pm = p_over(p['mu'], p['log_alpha'], linea)
        evs += [(over * pm - 1, linea, 'over', over), (under * (1 - pm) - 1, linea, 'under', under)]
    ev, linea, lado, cuota = max(evs)
    if ev >= UMBRAL_EV:
        gana = (p['y'] > linea) == (lado == 'over')
        c = cierre(linea)
        pc = None if c is None else sin_margen(c[2], c[3])
        out['pick'] = {'linea': linea, 'lado': lado, 'cuota': cuota, 'ev': float(ev), 'pl': cuota - 1 if gana else -1.0,
                       'clv': None if pc is None else cuota * (pc if lado == 'over' else 1 - pc) - 1}
    return out


def evaluar_forward(partidos):
    ev = [e for e in map(evaluar_partido, partidos) if e is not None]
    d = [e['d_logloss'] for e in ev if e['d_logloss'] is not None]
    picks = [e['pick'] for e in ev if e['pick']]
    clv = [x['clv'] for x in picks if x['clv'] is not None]
    r = ic(d, 95)
    return {'n_partidos': len(partidos), 'n_evaluables': len(ev), 'n_con_cierre': len(d), 'logloss_modelo-cierre': r,
            'gana_a_bet365': bool(d) and r['ic95'][1] < 0,
            'decision_lista': len(d) >= N_PARADA or max((e['inicio'] for e in ev), default='') >= FECHA_PARADA,
            'picks': {'n': len(picks), 'clv': ic(clv, 95), 'yield_plano': float(np.mean([x['pl'] for x in picks])) if picks else None}}


def _autochequeo_cruce():
    lineas = [json.dumps({'ts_captura': ts, 'match_id': 1, 'inicio_utc': '2026-11-01T18:00:00.000Z', 'local': 'Boca Juniors',
                          'visita': 'River Plate', 'arbitro': a}) for ts, a in
              (('2026-10-31T12:00:00Z', 'Yael Falcón Pérez'), ('2026-10-30T12:00:00Z', None), ('2026-10-31T00:00:00Z', 'Darío Herrera'))]
    a = leer_arbitros(lineas)[1]
    assert (a['ts_arbitro'], a['arbitro']) == ('2026-10-31T00:00:00Z', 'Darío Herrera')  # orden por ts, no de archivo
    assert leer_arbitros(lineas[1:2])[1]['ts_arbitro'] is None
    arbitros = {1: a, 2: {**a, 'local': 'River Plate', 'visita': 'Boca Juniors'}}
    fx = {'ok': {'inicio_utc': '2026-11-01T18:00:00.000Z', 'local': 'Boca Juniors', 'visita': 'CA River Plate (ARG)'},
          'tarde': {'inicio_utc': '2026-11-01T22:00:00.000Z', 'local': 'Boca Juniors', 'visita': 'CA River Plate (ARG)'},
          'otro': {'inicio_utc': '2026-11-01T18:00:00.000Z', 'local': 'CA Lanus', 'visita': 'CA Tigre'}}
    assert cruzar_fixtures(fx, arbitros) == {'ok': 1}  # el 2 tiene local y visita invertidos


def _autochequeo():
    _autochequeo_cruce()
    assert abs(sin_margen(1.9, 1.9) - 0.5) < 1e-12 and abs(sin_margen(1.5, 2.5) - 0.625) < 1e-12
    mu0, y = np.array([1.0, 2.0, 2.0, 4.0]), np.array([2.0, 4.0, 1.0, 9.0])
    f = ['2026-01-01', '2026-01-02', '2026-01-02', '2026-01-03']
    r = recalibrar(mu0, y, f, ventana=1)
    assert np.isnan(r[0]) and r[1] == r[2] == 4.0 and r[3] == 4.0 * 1.0 / 2.0  # empate de kickoff no entra
    la = np.log(0.1)
    base = {'mu': 5.0, 'log_alpha': la, 'y': 6, 'inicio': '2026-11-01T20:00:00', 'ts_arbitro': '2026-10-30T00:00:00',
            'capturas': [('2026-10-31T10:00:00Z', 4.5, 1.40, 2.80), ('2026-10-31T10:00:00Z', 5.5, 1.85, 1.95),
                         ('2026-10-31T10:00:00Z', 5.0, 1.60, 2.20), ('2026-11-01T10:00:00Z', 5.5, 1.70, 2.10),
                         ('2026-11-01T21:00:00Z', 5.5, 1.10, 6.00)]}  # la ultima es posterior al inicio
    e = evaluar_partido(base)
    pm, pc = p_over(5.0, la, 5.5), sin_margen(1.70, 2.10)
    assert e['linea_ref'] == 5.5 and abs(e['d_logloss'] - (-np.log(pm) + np.log(pc))) < 1e-12
    evs = {(ln, s): c * (q if s == 'over' else 1 - q) - 1 for ln, o, u in ((4.5, 1.40, 2.80), (5.5, 1.85, 1.95))
           for q in [p_over(5.0, la, ln)] for s, c in (('over', o), ('under', u))}
    (ln, s), ev = max(evs.items(), key=lambda kv: kv[1])
    assert ev >= UMBRAL_EV and (e['pick']['linea'], e['pick']['lado']) == (ln, s) == (4.5, 'under')
    assert e['pick']['pl'] == -1.0 and e['pick']['clv'] is None  # y = 6 pierde el under; 4.5 no tiene cierre
    tarde = evaluar_partido({**base, 'ts_arbitro': '2026-10-31T12:00:00Z'})  # la referencia pasa al 11-01
    assert tarde['linea_ref'] == 5.5 and tarde['d_logloss'] is None  # una sola captura posterior: sin cierre
    assert evaluar_partido({**base, 'ts_arbitro': '2026-11-01T12:00:00Z'}) is None
    assert evaluar_partido({**base, 'ts_arbitro': None}) is None
    sin_cierre = evaluar_partido({**base, 'capturas': base['capturas'][:3]})
    assert sin_cierre['d_logloss'] is None
    # un modelo con la verdad le gana a un mercado sesgado; uno sesgado no le gana a un mercado justo
    rng = np.random.default_rng(42)
    mus = rng.uniform(3.5, 7.0, 600)
    ys = rng.negative_binomial(10, 10 / (10 + mus))
    q = np.array([p_over(m, la, 5.5) for m in mus])

    def partidos(mu_mod, p_mkt):
        return [{**base, 'mu': mm, 'y': int(yy), 'capturas': [(base['capturas'][0][0], 5.5, 1.95 / pp, 1.95 / (1 - pp)),
                                                             (base['capturas'][3][0], 5.5, 1.95 / pp, 1.95 / (1 - pp))]}
                for mm, yy, pp in zip(mu_mod, ys, p_mkt)]
    bueno = evaluar_forward(partidos(mus, np.clip(q + 0.12, 0.05, 0.95)))
    assert bueno['gana_a_bet365'] and bueno['n_con_cierre'] == 600 and bueno['decision_lista']
    malo = evaluar_forward(partidos(mus * 1.4, q))
    assert not malo['gana_a_bet365']


def main():
    _autochequeo()
    salida = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'analisis/tarjetas_forward.json')
    arbitros = leer_arbitros(ARBITROS.read_text(encoding='utf-8').splitlines()) if ARBITROS.exists() else {}
    conn = sqlite3.connect(f'file:{DB_NAME}?mode=ro', uri=True)
    try:
        previo, base, conteos = cruce_forward(*datos_forward(conn), arbitros)
    finally:
        conn.close()
    mod = modelo(previo)
    r = paso1(mod)
    out = {'bead': 'adepor-jjx', 'lineas': LINEAS, 'tolerancia_calibracion': TOL_CALIB, 'paso1': r,
           'paso2': paso2(mod, base, conteos) if r['regla']['pasa'] else 'cerrado: el paso 1 no pasa'}
    Path(salida).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: r[k] for k in ('n_train', 'n_test', 'nll_test', 'mu_media_test', 'tarjetas_media_test', 'regla')}, indent=1))
    print(json.dumps(out['paso2'], indent=1))


if __name__ == '__main__':
    main()

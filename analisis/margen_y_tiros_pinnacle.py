"""
Experimento adepor-4kg (protocolo pre-registrado el 2026-10-22, ver el bead).

A) Metodo de margen: proporcional vs Shin vs potencia sobre el cierre de Pinnacle.
B) Tiros al arco como correccion del cierre de Pinnacle, walk-forward por temporada.

Uso:  python -I analisis/margen_y_tiros_pinnacle.py <dir_csvs> [salida.json]
Los CSV son los de football-data.co.uk: formato por temporada (Div, HomeTeam, FTR, HST...)
o multi-temporada de /new/ (Country, Home, Res, Season...).
"""
import csv
import glob
import json
import math
import sys
from collections import defaultdict, deque
from datetime import datetime

import numpy as np
from scipy.optimize import brentq, minimize

RES = {'H': 0, 'D': 1, 'A': 2}
# Ligas del protocolo pre-registrado; los zips por temporada traen mas, y se ignoran.
DIVS = {'E0', 'SP1', 'I1', 'D1', 'F1', 'T1'}
PAISES_NEW = {'Argentina', 'Brazil', 'Norway'}
TEMP_MIN = '2019'  # protocolo: temporadas 2019-20 en adelante
N_BOOT, SEMILLA, VENTANA, MIN_PREVIOS = 2000, 42, 5, 3


# ---------------------------------------------------------------- metodos de margen
def proporcional(cuotas):
    q = 1 / np.asarray(cuotas, float)
    return q / q.sum()


def shin(cuotas):
    """Shin (1993): el margen protege contra apostadores informados; carga mas a los underdogs."""
    q = 1 / np.asarray(cuotas, float)
    s = q.sum()

    def probs(z):
        return (np.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))
    if s <= 1:
        return q / s
    z = brentq(lambda z: probs(z).sum() - 1, 0.0, 0.4)
    return probs(z)


def potencia(cuotas):
    """p_i = q_i^k con k tal que la suma da 1."""
    q = 1 / np.asarray(cuotas, float)
    if q.sum() <= 1:
        return q / q.sum()
    k = brentq(lambda k: (q ** k).sum() - 1, 1.0, 5.0)
    return q ** k


METODOS = {'proporcional': proporcional, 'shin': shin, 'potencia': potencia}


# ---------------------------------------------------------------- carga
def _f(v):
    try:
        x = float(v)
        return x if x > 1 else None
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _fecha(s):
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def cargar(dir_csvs):
    filas = []
    for path in sorted(glob.glob(f'{dir_csvs}/**/*.csv', recursive=True)):
        for r in csv.DictReader(open(path, encoding='latin-1')):
            r = {(k or '').lstrip('\ufeffï»¿'): v for k, v in r.items()}  # BOM leido como latin-1
            if r.get('Div') not in DIVS and r.get('Country') not in PAISES_NEW:
                continue
            fecha = _fecha(r.get('Date'))
            res = RES.get(r.get('FTR') or r.get('Res'))
            if fecha is None or res is None:
                continue
            liga = r.get('Div') or f"{r.get('Country')}-{r.get('League')}"
            # Temporada europea agosto-mayo; las de /new/ traen su propia columna Season.
            temp = r.get('Season') or str(fecha.year if fecha.month >= 7 else fecha.year - 1)
            gl, gv = _i(r.get('FTHG') or r.get('HG')), _i(r.get('FTAG') or r.get('AG'))
            if str(temp).split('/')[0] < TEMP_MIN:
                continue
            filas.append({
                'liga': liga, 'temp': str(temp).split('/')[0], 'fecha': fecha,
                'local': r.get('HomeTeam') or r.get('Home'), 'visita': r.get('AwayTeam') or r.get('Away'),
                'res': res, 'goles': None if gl is None or gv is None else gl + gv,
                'cierre': [_f(r.get(c)) for c in ('PSCH', 'PSCD', 'PSCA')],
                'precierre': [_f(r.get(c)) for c in ('PSH', 'PSD', 'PSA')],
                'ou_cierre': [_f(r.get('PC>2.5')), _f(r.get('PC<2.5'))],
                'sot': (_i(r.get('HST')), _i(r.get('AST'))),
            })
    filas.sort(key=lambda f: f['fecha'])
    return filas


# ---------------------------------------------------------------- metricas
def bootstrap_diff(d):
    """Media de d e IC95 bootstrap (remuestreo de partidos)."""
    d = np.asarray(d, float)
    rng = np.random.default_rng(SEMILLA)
    medias = d[rng.integers(0, len(d), (N_BOOT, len(d)))].mean(axis=1)
    return {'n': len(d), 'media': float(d.mean()),
            'ic95': [float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))]}


def calibracion(p, y):
    """Prob media predicha vs frecuencia observada, por decil de prob predicha."""
    p, y = np.asarray(p), np.asarray(y)
    bordes = np.quantile(p, np.linspace(0, 1, 11))
    out = []
    for lo, hi in zip(bordes[:-1], bordes[1:]):
        m = (p >= lo) & (p <= hi)
        if m.any():
            out.append({'p_media': float(p[m].mean()), 'frec': float(y[m].mean()), 'n': int(m.sum())})
    return out


def experimento_a(filas):
    out = {}
    mercados = (('1X2', 'cierre', lambda f: f['res']),
                ('OU25', 'ou_cierre', lambda f: None if f['goles'] is None else int(f['goles'] < 2.5)))
    for mercado, col, y_de in mercados:
        validas = [f for f in filas if all(f[col]) and y_de(f) is not None]
        if not validas:
            out[mercado] = {'n': 0}  # los CSV de /new/ no traen O/U
            continue
        ll = {m: [] for m in METODOS}
        pares = defaultdict(list)  # prob de cada resultado posible, para calibracion
        for f in validas:
            y = y_de(f)
            for m, fn in METODOS.items():
                p = fn(f[col])
                ll[m].append(-math.log(p[y]))
                pares[m] += [(float(pi), int(i == y)) for i, pi in enumerate(p)]
        out[mercado] = {
            'n': len(validas),
            'logloss': {m: float(np.mean(v)) for m, v in ll.items()},
            'diff_vs_proporcional': {m: bootstrap_diff(np.subtract(ll[m], ll['proporcional']))
                                     for m in METODOS if m != 'proporcional'},
            'calibracion': {m: calibracion(*zip(*pares[m])) for m in METODOS},
        }
    return out


def features_tiros(filas):
    """x = media de (SOT a favor - en contra) en los ultimos 5 del local menos la del visitante.
    Solo usa partidos anteriores de la misma liga y temporada: walk-forward por construccion."""
    hist = defaultdict(lambda: deque(maxlen=VENTANA))
    for f in filas:
        hl, hv = hist[(f['liga'], f['temp'], f['local'])], hist[(f['liga'], f['temp'], f['visita'])]
        f['x'] = (np.mean(hl) - np.mean(hv)) if len(hl) >= MIN_PREVIOS and len(hv) >= MIN_PREVIOS else None
        sl, sv = f['sot']
        if sl is not None and sv is not None:
            hl.append(sl - sv)
            hv.append(sv - sl)


def _logloss_modelo(theta, logp, x, y):
    a_h, b_h, a_a, b_a = theta
    z = logp + np.column_stack([a_h + b_h * x, np.zeros_like(x), a_a + b_a * x])
    z -= z.max(axis=1, keepdims=True)
    lp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
    return -lp[np.arange(len(y)), y]


def experimento_b(filas, base):
    validas = [f for f in filas if f.get('x') is not None and all(f[base])]
    temps = sorted({f['temp'] for f in validas})
    diffs, por_temp = [], {}
    for t in temps[1:]:
        tr = [f for f in validas if f['temp'] < t]
        te = [f for f in validas if f['temp'] == t]
        if not tr or not te:
            continue
        arr = lambda fs: (np.log([proporcional(f[base]) for f in fs]),
                          np.array([f['x'] for f in fs]), np.array([f['res'] for f in fs]))
        lp_tr, x_tr, y_tr = arr(tr)
        theta = minimize(lambda th: _logloss_modelo(th, lp_tr, x_tr, y_tr).mean(), np.zeros(4)).x
        lp_te, x_te, y_te = arr(te)
        modelo = _logloss_modelo(theta, lp_te, x_te, y_te)
        sola = -lp_te[np.arange(len(y_te)), y_te]
        diffs += list(modelo - sola)
        por_temp[t] = {'n': len(te), 'logloss_pinnacle': float(sola.mean()),
                       'logloss_modelo': float(modelo.mean()), 'theta': [float(v) for v in theta]}
    return {'base': base, 'por_temporada': por_temp,
            'diff_modelo_vs_pinnacle': bootstrap_diff(diffs) if diffs else None}


def _autochequeo():
    c = [1.9, 3.6, 4.2]
    for fn in METODOS.values():
        assert abs(fn(c).sum() - 1) < 1e-9
    assert np.allclose(shin([2.0, 2.0]), [0.5, 0.5])
    # Con margen, Shin y potencia le dan menos al underdog que la proporcional.
    assert shin(c)[2] < proporcional(c)[2] and potencia(c)[2] < proporcional(c)[2]
    th = np.zeros(4)
    lp = np.log([[0.5, 0.3, 0.2]])
    assert abs(_logloss_modelo(th, lp, np.array([1.0]), np.array([0]))[0] + math.log(0.5)) < 1e-12


def main():
    _autochequeo()
    dir_csvs = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else 'analisis/margen_y_tiros_pinnacle.json'
    filas = cargar(dir_csvs)
    features_tiros(filas)
    out = {'bead': 'adepor-4kg', 'n_partidos': len(filas),
           'ligas': sorted({f['liga'] for f in filas}), 'temporadas': sorted({f['temp'] for f in filas}),
           'A_margen': experimento_a(filas),
           'B_tiros_vs_cierre': experimento_b(filas, 'cierre'),
           'B_tiros_vs_precierre': experimento_b(filas, 'precierre')}
    with open(salida, 'w') as fh:
        json.dump(out, fh, indent=2)
    print(f'{len(filas)} partidos -> {salida}')


if __name__ == '__main__':
    main()

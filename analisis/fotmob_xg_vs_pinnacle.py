"""
xG de FotMob contra el cierre de Pinnacle (1X2). Protocolo: fotmob_xg_vs_pinnacle_prereg.md.

Entrada: data/fotmob/raw/*.json (matchDetails) y data/football_data/ (eu/{4,5}/*.csv o new/ARG.csv).
Salida: analisis/fotmob_xg_vs_pinnacle_<estrato>.json
Uso: python -I analisis/fotmob_xg_vs_pinnacle.py [eu|arg]
"""
import csv
import difflib
import glob
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
ESTRATOS = {
    'eu': {'ligas': {47: 'E0', 87: 'SP1', 54: 'D1', 55: 'I1', 53: 'F1'},  # id FotMob -> Div football-data
           'train': '4', 'test': '5'},  # carpetas data/football_data/eu/<n>
    'arg': {'ligas': {112: 'ARG'}, 'train': '2024', 'test': '2025'},  # temporada en new/ARG.csv
}
LIGAS = ESTRATOS['eu']['ligas']  # se reasigna en main() segun el estrato
ALPHA, MIN_PREV, C, N_BOOT = 0.1, 5, 1.0, 10000


def cargar_fotmob():
    """Partidos terminados con xG por tiro: (liga, fecha, hg, ag, ht, at, xg_l, xg_v)."""
    out = []
    for f in glob.glob(str(ROOT / 'data/fotmob/raw/*.json')):
        d = json.load(open(f, encoding='utf-8'))
        g = d['general']
        # La Liga Profesional usa ids de subtorneo en 2024-25: la liga vive en parentLeagueId.
        lid = next((x for x in (g.get('leagueId'), g.get('parentLeagueId')) if x in LIGAS), None)
        if lid is None or not g.get('finished') or g.get('coverageLevel') != 'xG':
            continue
        t = d['header']['teams']
        ids = [x['id'] for x in t]
        xg = [0.0, 0.0]
        for s in d['content'].get('shotmap', {}).get('shots', []):
            if s['teamId'] in ids and s.get('expectedGoals') is not None:
                xg[ids.index(s['teamId'])] += s['expectedGoals']
        fecha = datetime.strptime(g['matchTimeUTCDate'][:10], '%Y-%m-%d').date()
        out.append((lid, fecha, t[0]['score'], t[1]['score'], t[0]['name'], t[1]['name'], xg[0], xg[1]))
    return out


def cargar_fd(estrato, periodo):
    """Filas de football-data con cuotas de cierre: (liga, fecha, hg, ag, local, visita, cuotas, resultado)."""
    filas = []
    for lid, div in LIGAS.items():
        if estrato == 'eu':
            ruta, cols = ROOT / f'data/football_data/eu/{periodo}/{div}.csv', ('FTHG', 'FTAG', 'HomeTeam', 'AwayTeam', 'FTR')
        else:
            ruta, cols = ROOT / 'data/football_data/new/ARG.csv', ('HG', 'AG', 'Home', 'Away', 'Res')
        for r in csv.DictReader(open(ruta, encoding='utf-8-sig')):
            if estrato == 'arg' and r['Season'] != periodo:
                continue
            try:
                cuotas = [float(r[k]) for k in ('PSCH', 'PSCD', 'PSCA')]
                fecha = datetime.strptime(r['Date'], '%d/%m/%Y').date()
                filas.append((lid, fecha, int(r[cols[0]]), int(r[cols[1]]), r[cols[2]], r[cols[3]], cuotas, r[cols[4]]))
            except (ValueError, KeyError):
                continue  # sin cuotas de cierre o sin resultado
    return filas


def sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def cruzar(fm, fd):
    """Une por liga, fecha (+-1 dia) y marcador; desempata por parecido de nombres."""
    idx = {}
    for p in fm:
        idx.setdefault((p[0], p[2], p[3]), []).append(p)
    pares, sin = [], 0
    for q in fd:
        cand = [p for p in idx.get((q[0], q[2], q[3]), []) if abs((p[1] - q[1]).days) <= 1]
        if not cand:
            sin += 1
            continue
        p = max(cand, key=lambda p: sim(p[4], q[4]) + sim(p[5], q[5]))
        if sim(p[4], q[4]) + sim(p[5], q[5]) < 0.8:  # nombres demasiado distintos: no es el mismo partido
            sin += 1
            continue
        pares.append((p, q))
    return pares, sin


def features(pares):
    """Por partido: logits de Pinnacle sin margen, dxg, dg y resultado. EMA solo con partidos previos."""
    pares = sorted(pares, key=lambda x: x[1][1])
    ema, n, X, y, base = {}, {}, [], [], []
    for p, q in pares:
        lid, h, a = q[0], p[4], p[5]
        xl, xv, gl, gv = p[6], p[7], p[2], p[3]
        kh, ka = (lid, h), (lid, a)
        if n.get(kh, 0) >= MIN_PREV and n.get(ka, 0) >= MIN_PREV:
            inv = 1 / np.array(q[6])
            pr = inv / inv.sum()
            f = lambda k: (ema[k]['xf'] - ema[k]['xc'], ema[k]['gf'] - ema[k]['gc'])
            dxg = f(kh)[0] - f(ka)[0]
            dg = f(kh)[1] - f(ka)[1]
            X.append([np.log(pr[0] / pr[1]), np.log(pr[2] / pr[1]), dxg, dg])
            y.append('HDA'.index(q[7]))
            base.append(pr)
        for k, xf, xc, gf, gc in ((kh, xl, xv, gl, gv), (ka, xv, xl, gv, gl)):
            e = ema.setdefault(k, {'xf': xf, 'xc': xc, 'gf': gf, 'gc': gc})
            if n.get(k, 0):
                for kk, v in (('xf', xf), ('xc', xc), ('gf', gf), ('gc', gc)):
                    e[kk] = ALPHA * v + (1 - ALPHA) * e[kk]
            n[k] = n.get(k, 0) + 1
    return np.array(X), np.array(y), np.array(base)


def ll(P, y):
    return -np.log(np.clip(P[np.arange(len(y)), y], 1e-12, None))


def ajustar(Xtr, ytr, Xte, cols):
    m = LogisticRegression(C=C, max_iter=1000).fit(Xtr[:, cols], ytr)
    return m.predict_proba(Xte[:, cols])


def boot(d, rng):
    idx = rng.integers(0, len(d), (N_BOOT, len(d)))
    m = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    global LIGAS
    estrato = sys.argv[1] if len(sys.argv) > 1 else 'eu'
    LIGAS = ESTRATOS[estrato]['ligas']
    fm = cargar_fotmob()
    res, data = {'estrato': estrato, 'n_fotmob': len(fm)}, {}
    for nombre in ('train', 'test'):
        fd = cargar_fd(estrato, ESTRATOS[estrato][nombre])
        pares, sin = cruzar(fm, fd)
        # solo partidos de la temporada correspondiente (el csv ya la fija)
        data[nombre] = features(pares)
        res[nombre] = {'n_fd': len(fd), 'sin_cruce': sin, 'n_modelo': len(data[nombre][1])}
    Xtr, ytr, _ = data['train']
    Xte, yte, Pb = data['test']
    rng = np.random.default_rng(0)
    base = ll(Pb, yte)
    res['logloss_base'] = float(base.mean())
    for nom, cols in (('candidato_xg', [0, 1, 2]), ('control_goles', [0, 1, 3]), ('recalibrada_sin_xg', [0, 1])):
        P = ajustar(Xtr, ytr, Xte, cols)
        d = ll(P, yte) - base
        m, lo, hi = boot(d, rng)
        res[nom] = {'logloss': float(ll(P, yte).mean()), 'delta': m, 'ic95': [lo, hi], 'exito': hi < 0}
    Path(ROOT / f'analisis/fotmob_xg_vs_pinnacle_{estrato}.json').write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == '__main__':
    main()

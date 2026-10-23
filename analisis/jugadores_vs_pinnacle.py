"""
E7: ausencias, disciplina y descanso contra el cierre de Pinnacle. Protocolo: docs/specs/13-estudios-forward.md.

Uso: python -I analisis/jugadores_vs_pinnacle.py [eu|arg]
Salida: analisis/jugadores_vs_pinnacle_<estrato>.json
"""
import glob
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))
import fotmob_xg_vs_pinnacle as ev  # noqa: E402

MIN_PREVIOS, V_AUS, V_DISC, TOPE_DESC = 3, 5, 10, 10


def tarjetas(det, lado):
    n = 0.0
    for grp in det['content'].get('stats', {}).get('Periods', {}).get('All', {}).get('stats', []):
        for s in grp.get('stats', []):
            if s.get('key') in ('yellow_cards', 'red_cards') and isinstance(s.get('stats'), list) and len(s['stats']) == 2:
                try:
                    n += float(s['stats'][lado]) * (2 if s['key'] == 'red_cards' else 1)
                except (TypeError, ValueError):
                    pass
    return n


def cargar():
    """Partidos de liga terminados con valor del once, tarjetas y fecha, en orden cronologico."""
    out = []
    for fl in glob.glob(str(ROOT / 'data/fotmob/raw/*.json')):
        d = json.load(open(fl, encoding='utf-8'))
        g = d['general']
        lid = next((x for x in (g.get('leagueId'), g.get('parentLeagueId')) if x in ev.LIGAS), None)
        lu = (d['content'] or {}).get('lineup') or {}
        if lid is None or not g.get('finished') or not lu.get('homeTeam'):
            continue
        t = d['header']['teams']
        vals = [lu['homeTeam'].get('totalStarterMarketValue'), lu['awayTeam'].get('totalStarterMarketValue')]
        out.append({'lid': lid, 'fecha': datetime.strptime(g['matchTimeUTCDate'][:10], '%Y-%m-%d'),
                    'equipos': [t[0]['name'], t[1]['name']], 'goles': [t[0]['score'], t[1]['score']],
                    'valor': vals, 'tarj': [tarjetas(d, 0), tarjetas(d, 1)]})
    return sorted(out, key=lambda m: m['fecha'])


def con_variables(partidos):
    """Tuplas estilo ev.cargar_fotmob con las seis variables (o None) en el indice 8. Solo pasado."""
    hist = defaultdict(list)  # (liga, equipo) -> [(fecha, valor, tarjetas)]
    out = []
    for m in partidos:
        feats = []
        for lado in (0, 1):
            h = hist[(m['lid'], m['equipos'][lado])]
            if len(h) >= MIN_PREVIOS and m['valor'][lado] and all(x[1] for x in h[-V_AUS:]):
                aus = np.log(m['valor'][lado]) - np.log(np.mean([x[1] for x in h[-V_AUS:]]))
                disc = float(np.mean([x[2] for x in h[-V_DISC:]]))
                desc = min((m['fecha'] - h[-1][0]).days, TOPE_DESC)
                feats.append([aus, disc, desc])
            else:
                feats.append(None)
        out.append((m['lid'], m['fecha'].date(), m['goles'][0], m['goles'][1], m['equipos'][0], m['equipos'][1], 0.0, 0.0,
                    None if None in feats else [feats[0][0], feats[1][0], feats[0][1], feats[1][1], feats[0][2], feats[1][2]]))
        for lado in (0, 1):
            hist[(m['lid'], m['equipos'][lado])].append((m['fecha'], m['valor'][lado], m['tarj'][lado]))
    return out


def sin_margen(o):
    inv = 1 / np.array(o)
    return inv / inv.sum()


def main():
    estrato = sys.argv[1] if len(sys.argv) > 1 else 'eu'
    ev.LIGAS = ev.ESTRATOS[estrato]['ligas']
    fm = con_variables(cargar())
    data, res = {}, {'estrato': estrato, 'n_fotmob': len(fm), 'con_variables': sum(1 for p in fm if p[8])}
    for nombre in ('train', 'test'):
        pares, sin = ev.cruzar([p for p in fm if p[8]], ev.cargar_fd(estrato, ev.ESTRATOS[estrato][nombre]))
        X, y, base = [], [], []
        for p, q in pares:
            pr = sin_margen(q[6])
            X.append([np.log(pr[0] / pr[1]), np.log(pr[2] / pr[1]), *p[8]])
            y.append('HDA'.index(q[7]))
            base.append(pr)
        data[nombre] = (np.array(X), np.array(y), np.array(base))
        res[nombre] = {'n': len(X), 'sin_cruce': sin}
    (Xtr, ytr, _), (Xte, yte, Pb) = data['train'], data['test']
    rng = np.random.default_rng(20261023)
    base = ev.ll(Pb, yte)
    res['logloss_base'] = float(base.mean())
    for nom, cols in (('candidato_jugadores', list(range(8))), ('solo_ausencias', [0, 1, 2, 3]), ('recalibrada', [0, 1])):
        P = ev.ajustar(Xtr, ytr, Xte, cols)
        m, lo, hi = ev.boot(ev.ll(P, yte) - base, rng)
        res[nom] = {'delta': m, 'ic95': [lo, hi], 'exito': hi < 0}
    texto = json.dumps(res, indent=2)
    (ROOT / f'analisis/jugadores_vs_pinnacle_{estrato}.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

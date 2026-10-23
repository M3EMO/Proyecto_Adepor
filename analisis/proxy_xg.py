"""
E3: proxy de xG de equipo desde estadisticas agregadas. Protocolo: docs/specs/13-estudios-forward.md.

Uso: python -I analisis/proxy_xg.py
Salida: analisis/proxy_xg.json
"""
import glob
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLAVES = ('total_shots', 'ShotsOnTarget', 'shots_inside_box', 'big_chance', 'touches_opp_box', 'corners')
CONJUNTOS = {'solo_tiros_totales': (0,), 'tiros_y_al_arco': (0, 1), 'conjunto_completo': tuple(range(6))}


def num(x):
    try:
        return float(str(x).split(' ')[0])
    except ValueError:
        return None


def filas():
    """Una fila por equipo y partido con xG en el shotmap: (fecha, [stats], xG)."""
    out = []
    for f in glob.glob(str(ROOT / 'data/fotmob/raw/*.json')):
        d = json.load(open(f, encoding='utf-8'))
        g = d['general']
        if not g.get('finished') or g.get('coverageLevel') != 'xG':
            continue
        ids = [t['id'] for t in d['header']['teams']]
        xg = [0.0, 0.0]
        for s in d['content'].get('shotmap', {}).get('shots', []):
            if s['teamId'] in ids and s.get('expectedGoals') is not None:
                xg[ids.index(s['teamId'])] += s['expectedGoals']
        stats = {s['key']: s['stats'] for grp in d['content'].get('stats', {}).get('Periods', {}).get('All', {}).get('stats', [])
                 for s in grp.get('stats', []) if isinstance(s.get('stats'), list) and len(s['stats']) == 2}
        for lado in (0, 1):
            v = [num(stats.get(k, [None, None])[lado]) for k in CLAVES]
            if None not in v and sum(xg) > 0:
                out.append((g['matchTimeUTCDate'], v, xg[lado]))
    return sorted(out)


def r2(y, p):
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def main():
    f = filas()
    X, y = np.array([x[1] for x in f]), np.array([x[2] for x in f])
    corte = int(len(f) * 0.8)
    res = {'n': len(f), 'n_train': corte, 'n_test': len(f) - corte, 'fecha_corte': f[corte][0][:10], 'modelos': {}}
    for nom, cols in CONJUNTOS.items():
        A = np.column_stack([np.ones(len(X)), X[:, cols]])
        beta = np.linalg.lstsq(A[:corte], y[:corte], rcond=None)[0]
        p = A[corte:] @ beta
        res['modelos'][nom] = {'r2_test': r2(y[corte:], p), 'rmse_test': float(np.sqrt(((y[corte:] - p) ** 2).mean())),
                               'coeficientes': dict(zip(('const', *[CLAVES[c] for c in cols]), map(float, beta)))}
    comp, base = res['modelos']['conjunto_completo']['r2_test'], res['modelos']['solo_tiros_totales']['r2_test']
    res['exito'] = bool(comp >= 0.6 and comp - base >= 0.05)
    texto = json.dumps(res, indent=2)
    (ROOT / 'analisis/proxy_xg.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

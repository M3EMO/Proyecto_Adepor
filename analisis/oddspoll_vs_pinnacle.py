"""
Variables del oddspoll de FotMob contra el cierre de Pinnacle (E2). Protocolo: docs/specs/13-estudios-forward.md.

Uso: python -I analisis/oddspoll_vs_pinnacle.py [eu|arg]
Salida: analisis/oddspoll_vs_pinnacle_<estrato>.json
"""
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))
import fotmob_xg_vs_pinnacle as ev  # noqa: E402


def variables(facts):
    """[f_forma, f_h2h_gana, f_h2h_invicto, f_goles] desde las plantillas del oddspoll. 0 si falta."""
    f = [0.0, 0.0, 0.0, 0.0]
    for x in facts or []:
        t, v = x.get('TextTemplateId'), x.get('StatValues') or []
        try:
            if t == 'team_form_both' and len(v) == 8:
                f[0] = ((int(v[1]) - int(v[3])) - (int(v[5]) - int(v[7]))) / 5
            elif t == 'h2h_winstreak' and len(v) == 3:
                f[1] = int(v[2]) * (1 if v[0] == 'home_team' else -1)
            elif t == 'h2h_undefeated' and len(v) == 5:
                f[2] = int(v[2]) * (1 if v[0] == 'home_team' else -1)
            elif t == 'goals_total_last_3_both' and len(v) == 5:
                f[3] = float(v[3]) - float(v[4])
        except ValueError:
            continue
    return f


def cargar_fotmob():
    """Como ev.cargar_fotmob, con las variables del oddspoll en el indice 8."""
    out = []
    for fl in glob.glob(str(ROOT / 'data/fotmob/raw/*.json')):
        d = json.load(open(fl, encoding='utf-8'))
        g = d['general']
        lid = next((x for x in (g.get('leagueId'), g.get('parentLeagueId')) if x in ev.LIGAS), None)
        if lid is None or not g.get('finished'):
            continue
        t = d['header']['teams']
        facts = ((d['content'].get('matchFacts') or {}).get('poll') or {}).get('oddspoll', {}).get('Facts')
        fecha = datetime.strptime(g['matchTimeUTCDate'][:10], '%Y-%m-%d').date()
        out.append((lid, fecha, t[0]['score'], t[1]['score'], t[0]['name'], t[1]['name'], 0.0, 0.0, variables(facts)))
    return out


def matriz(pares):
    X, y, base = [], [], []
    for p, q in pares:
        inv = 1 / np.array(q[6])
        pr = inv / inv.sum()
        X.append([np.log(pr[0] / pr[1]), np.log(pr[2] / pr[1]), *p[8]])
        y.append('HDA'.index(q[7]))
        base.append(pr)
    return np.array(X), np.array(y), np.array(base)


def main():
    estrato = sys.argv[1] if len(sys.argv) > 1 else 'eu'
    ev.LIGAS = ev.ESTRATOS[estrato]['ligas']
    fm = cargar_fotmob()
    data, res = {}, {'estrato': estrato, 'n_fotmob': len(fm)}
    for nombre in ('train', 'test'):
        pares, sin = ev.cruzar(fm, ev.cargar_fd(estrato, ev.ESTRATOS[estrato][nombre]))
        data[nombre] = matriz(pares)
        X = data[nombre][0]
        res[nombre] = {'n': len(X), 'sin_cruce': sin, 'con_alguna_variable': int((np.abs(X[:, 2:]).sum(axis=1) > 0).sum())}
    (Xtr, ytr, _), (Xte, yte, Pb) = data['train'], data['test']
    rng = np.random.default_rng(20261023)
    base = ev.ll(Pb, yte)
    res['logloss_base'] = float(base.mean())
    for nom, cols in (('candidato_oddspoll', [0, 1, 2, 3, 4, 5]), ('recalibrada_sin_oddspoll', [0, 1])):
        P = ev.ajustar(Xtr, ytr, Xte, cols)
        m, lo, hi = ev.boot(ev.ll(P, yte) - base, rng)
        res[nom] = {'delta': m, 'ic95': [lo, hi], 'exito': hi < 0}
    texto = json.dumps(res, indent=2)
    (ROOT / f'analisis/oddspoll_vs_pinnacle_{estrato}.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

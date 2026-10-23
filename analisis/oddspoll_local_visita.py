"""
E2b: variables del oddspoll de FotMob separadas por local y visitante. Protocolo: docs/specs/13-estudios-forward.md.

Uso: python -I analisis/oddspoll_local_visita.py [eu|arg]
Salida: analisis/oddspoll_local_visita_<estrato>.json
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))
import fotmob_xg_vs_pinnacle as ev  # noqa: E402
import oddspoll_vs_pinnacle as op  # noqa: E402


def variables8(facts):
    """[forma_l, forma_v, h2h_gana_l, h2h_gana_v, h2h_invicto_l, h2h_invicto_v, goles_l, goles_v]."""
    _, gana, invicto, _ = op.variables(facts)  # h2h con signo: positivo local, negativo visitante
    f = [0.0, 0.0, max(gana, 0.0), max(-gana, 0.0), max(invicto, 0.0), max(-invicto, 0.0), 0.0, 0.0]
    for x in facts or []:
        t, v = x.get('TextTemplateId'), x.get('StatValues') or []
        try:
            if t == 'team_form_both' and len(v) == 8:
                f[0], f[1] = (int(v[1]) - int(v[3])) / 5, (int(v[5]) - int(v[7])) / 5
            elif t == 'goals_total_last_3_both' and len(v) == 5:
                f[6], f[7] = float(v[3]), float(v[4])
        except ValueError:
            continue
    return f


def sin_margen(cuotas):
    inv = 1 / np.array(cuotas)
    return inv / inv.sum()


def diagnostico(pares):
    """Rachas h2h de 4 o mas victorias, por lado: % real de victorias contra la prob media de Pinnacle."""
    out = {}
    for lado, idx, res in (('local', 2, 'H'), ('visita', 3, 'A')):
        filas = [(q[7] == res, sin_margen(q[6])[0 if lado == 'local' else 2])
                 for p, q in pares if variables8(p[8])[idx] >= 4]
        out[lado] = ({'n': len(filas), 'gana_real': float(np.mean([g for g, _ in filas])),
                      'prob_pinnacle': float(np.mean([pr for _, pr in filas]))} if filas else {'n': 0})
    return out


def main():
    estrato = sys.argv[1] if len(sys.argv) > 1 else 'eu'
    ev.LIGAS = ev.ESTRATOS[estrato]['ligas']
    fm = op.cargar_fotmob(crudo=True)
    data, res, pares_test = {}, {'estrato': estrato}, []
    for nombre in ('train', 'test'):
        pares, sin = ev.cruzar(fm, ev.cargar_fd(estrato, ev.ESTRATOS[estrato][nombre]))
        X, y, base = [], [], []
        for p, q in pares:
            pr = sin_margen(q[6])
            X.append([np.log(pr[0] / pr[1]), np.log(pr[2] / pr[1]), *variables8(p[8])])
            y.append('HDA'.index(q[7]))
            base.append(pr)
        data[nombre] = (np.array(X), np.array(y), np.array(base))
        res[nombre] = {'n': len(X), 'sin_cruce': sin}
        if nombre == 'test':
            pares_test = pares
    (Xtr, ytr, _), (Xte, yte, Pb) = data['train'], data['test']
    res['diagnostico_rachas_h2h_4mas_en_prueba'] = diagnostico(pares_test)
    rng = np.random.default_rng(20261023)
    base = ev.ll(Pb, yte)
    res['logloss_base'] = float(base.mean())
    for nom, cols in (('candidato_local_visita', list(range(10))), ('recalibrada_sin_oddspoll', [0, 1])):
        P = ev.ajustar(Xtr, ytr, Xte, cols)
        m, lo, hi = ev.boot(ev.ll(P, yte) - base, rng)
        res[nom] = {'delta': m, 'ic95': [lo, hi], 'exito': hi < 0}
    texto = json.dumps(res, indent=2)
    (ROOT / f'analisis/oddspoll_local_visita_{estrato}.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

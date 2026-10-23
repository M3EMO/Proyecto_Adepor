"""
E6 y E6b: porcentaje de victorias local/visitante y rachas h2h contra el cierre de Pinnacle.
Protocolo: docs/specs/13-estudios-forward.md.

Uso: python -I analisis/winrate_local_visita.py
Salida: analisis/winrate_local_visita.json
"""
import csv
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'analisis'))
import fotmob_xg_vs_pinnacle as ev  # noqa: E402

TOP5 = {'E0', 'SP1', 'D1', 'I1', 'F1'}
ORDEN = ('0', '1', '2', '6', '3', '4', '5')  # temporadas 2019/20 a 2025/26 en orden cronologico
INDEPENDIENTE = {'0', '1', '2', '6', '3'}
VENTANA, MIN_PREVIOS, MIN_RACHA, N_BOOT = 10, 5, 4, 10000


def fecha(s):
    for f in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError(s)


def cargar():
    """Partidos con resultado, ordenados por fecha: dict con div, carpeta, local, visita, goles, cuotas de cierre."""
    out = []
    for c in ORDEN:
        for f in sorted((ROOT / f'data/football_data/eu/{c}').glob('*.csv')):
            for r in csv.DictReader(open(f, encoding='latin-1')):
                try:
                    m = {'div': f.stem, 'carpeta': c, 'fecha': fecha(r['Date']), 'l': r['HomeTeam'], 'v': r['AwayTeam'],
                         'res': r['FTR'], 'cierre': None}
                    if m['res'] not in ('H', 'D', 'A'):
                        continue
                except (KeyError, ValueError):
                    continue
                try:
                    m['cierre'] = [float(r[k]) for k in ('PSCH', 'PSCD', 'PSCA')]
                except (KeyError, ValueError):
                    pass
                out.append(m)
    return sorted(out, key=lambda m: m['fecha'])


def sin_margen(o):
    inv = 1 / np.array(o)
    return inv / inv.sum()


def winrate(partidos):
    """E6: filas (carpeta, X, y, cuotas) con wl y wv de partidos previos, solo ligas grandes."""
    local, visita = defaultdict(lambda: deque(maxlen=VENTANA)), defaultdict(lambda: deque(maxlen=VENTANA))
    filas = []
    for m in partidos:
        if m['div'] not in TOP5:
            continue
        kl, kv = (m['div'], m['l']), (m['div'], m['v'])
        if m['cierre'] and len(local[kl]) >= MIN_PREVIOS and len(visita[kv]) >= MIN_PREVIOS:
            pr = sin_margen(m['cierre'])
            wl, wv = np.mean(local[kl]), np.mean(visita[kv])
            filas.append((m['carpeta'], [np.log(pr[0] / pr[1]), np.log(pr[2] / pr[1]), wl, wv], 'HDA'.index(m['res']), pr, m['cierre']))
        local[kl].append(m['res'] == 'H')
        visita[kv].append(m['res'] == 'A')
    return filas


def rachas(partidos):
    """E6b: filas (carpeta, lado, gano, prob_pinnacle, cuota) del equipo con racha h2h >= MIN_RACHA."""
    hist = defaultdict(list)  # (div, equipo A, equipo B ordenados) -> ganadores previos
    filas = []
    for m in partidos:
        clave = (m['div'], *sorted((m['l'], m['v'])))
        prev = hist[clave]
        if m['cierre'] and prev and prev[-1]:
            x, n = prev[-1], 0
            for g in reversed(prev):
                if g != x:
                    break
                n += 1
            if n >= MIN_RACHA and x in (m['l'], m['v']):
                lado = 'local' if x == m['l'] else 'visita'
                i = 0 if lado == 'local' else 2
                filas.append((m['carpeta'], lado, m['res'] == 'HDA'[i], sin_margen(m['cierre'])[i], m['cierre'][i]))
        prev.append(m['l'] if m['res'] == 'H' else m['v'] if m['res'] == 'A' else None)
    return filas


def rachas_localia(partidos):
    """E6c: filas (carpeta, div, tipo, umbral, resultado_del_equipo_senalado, prob_pinnacle, cuota) por racha en su cancha.
    Se emite una fila por umbral cumplido (3, 4 y 5)."""
    casa, fuera = defaultdict(list), defaultdict(list)  # (div, equipo) -> resultados de local / de visitante
    filas = []

    def racha(lista, cond):
        n = 0
        for r in reversed(lista):
            if not cond(r):
                break
            n += 1
        return n

    for m in partidos:
        kl, kv = (m['div'], m['l']), (m['div'], m['v'])
        if m['cierre']:
            pr, c = sin_margen(m['cierre']), m['cierre']
            senales = (('L_gana_en_casa', racha(casa[kl], lambda r: r == 'H'), 'H', 0),
                       ('V_gana_fuera', racha(fuera[kv], lambda r: r == 'A'), 'A', 2),
                       ('V_sin_ganar_fuera', racha(fuera[kv], lambda r: r != 'A'), 'no_A', 2))
            for tipo, n, gana, i in senales:
                for u in (3, 4, 5):
                    if n >= u:
                        # V_sin_ganar_fuera: el evento es "el visitante no gana": prob = 1 - P(visitante), sin cuota simple
                        if gana == 'no_A':
                            filas.append((m['carpeta'], m['div'], tipo, u, m['res'] != 'A', 1 - pr[2], None))
                        else:
                            filas.append((m['carpeta'], m['div'], tipo, u, m['res'] == gana, pr[i], c[i]))
        casa[kl].append(m['res'])
        fuera[kv].append(m['res'])
    return filas


def z_y_yield(filas, rng):
    if not filas:
        return {'n': 0}
    g = np.array([f[2] for f in filas], float)
    pr = np.array([f[3] for f in filas])
    ret = np.array([(f[4] - 1) if f[2] else -1.0 for f in filas])
    m = ret[rng.integers(0, len(ret), (N_BOOT, len(ret)))].mean(axis=1)
    return {'n': len(filas), 'gana_real': float(g.mean()), 'prob_pinnacle': float(pr.mean()),
            'z': float((g.mean() - pr.mean()) / (np.sqrt((pr * (1 - pr)).sum()) / len(filas))),
            'yield_medio': float(ret.mean()), 'yield_ic95': [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]}


def main():
    rng = np.random.default_rng(20261023)
    partidos = cargar()
    r = {'partidos': len(partidos)}
    # E6
    f = winrate(partidos)
    tr = [x for x in f if x[0] in ORDEN[:5]]
    te = [x for x in f if x[0] == '4']
    Xtr, ytr = np.array([x[1] for x in tr]), np.array([x[2] for x in tr])
    Xte, yte, Pb = np.array([x[1] for x in te]), np.array([x[2] for x in te]), np.array([x[3] for x in te])
    P = ev.ajustar(Xtr, ytr, Xte, [0, 1, 2, 3])
    m, lo, hi = ev.boot(ev.ll(P, yte) - ev.ll(Pb, yte), rng)
    ing = []
    for x in te:
        wl, wv = x[1][2], x[1][3]
        if wl != wv:
            i = 0 if wl > wv else 2
            ing.append((x[0], 'ingenua', x[2] == i, x[3][i], x[4][i]))
    r['E6'] = {'n_train': len(tr), 'n_test': len(te), 'delta_logloss': m, 'ic95': [lo, hi], 'exito': hi < 0,
               'regla_ingenua': z_y_yield(ing, rng)}
    # E6b
    rc = rachas(partidos)
    ind = [x for x in rc if x[0] in INDEPENDIENTE]
    r['E6b'] = {'independiente': {lado: z_y_yield([x for x in ind if x[1] == lado], rng) for lado in ('local', 'visita')},
                'independiente_agrupado': z_y_yield(ind, rng),
                'posterior_2024_25': z_y_yield([x for x in rc if x[0] in ('4', '5')], rng)}
    ag = r['E6b']['independiente_agrupado']
    lados = r['E6b']['independiente']
    rl = rachas_localia(partidos)
    r['E6c'] = {}
    for tipo in ('L_gana_en_casa', 'V_gana_fuera', 'V_sin_ganar_fuera'):
        r['E6c'][tipo] = {}
        for u in (3, 4, 5):
            base = [(x[0], x[2], x[4], x[5], x[6]) for x in rl if x[2] == tipo and x[3] == u]
            sel = lambda per: [(a, b, c, d, e) for a, b, c, d, e in base if (a in INDEPENDIENTE) == per]
            ind_, post_ = sel(True), sel(False)
            conv = lambda xs: [(x[0], None, x[2], x[3], x[4] if x[4] else 2.0) for x in xs]
            r['E6c'][tipo][str(u)] = {'independiente': z_y_yield(conv(ind_), rng) if ind_ else {'n': 0},
                                      'posterior': z_y_yield(conv(post_), rng) if post_ else {'n': 0}}
    cand = [r['E6c'][t]['4']['independiente'] for t in r['E6c']]
    r['E6c']['exito'] = bool(any(c.get('n', 0) >= 300 and c.get('z', 0) > 2.4 for c in cand))
    por_div = defaultdict(list)
    for x in rl:
        if x[3] == 4 and x[0] in INDEPENDIENTE:
            por_div[(x[2], x[1])].append((x[0], None, x[4], x[5], x[6] if x[6] else 2.0))
    r['E6c']['por_division_umbral4'] = {f'{k[0]}|{k[1]}': {a: round(b, 3) if isinstance(b, float) else b for a, b in z_y_yield(v, rng).items() if a in ('n', 'gana_real', 'prob_pinnacle', 'z')}
                                        for k, v in sorted(por_div.items()) if len(v) >= 100}
    r['E6b']['exito'] = bool(ag['n'] >= 300 and ag['z'] > 2 and all(lados[k]['n'] and lados[k]['gana_real'] > lados[k]['prob_pinnacle'] for k in lados))
    texto = json.dumps(r, indent=2)
    (ROOT / 'analisis/winrate_local_visita.json').write_text(texto)
    print(texto)


if __name__ == '__main__':
    main()

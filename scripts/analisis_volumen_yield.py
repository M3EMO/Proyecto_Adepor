"""
ANALISIS VOLUMEN vs YIELD
=========================
1. Train/test split cronologico 60/40 sobre apuestas liquidadas
2. Threshold test +-20% en filtros clave
3. Matriz de trade-offs volumen/yield por liga

Objetivo: encontrar configuracion que maximice volumen sin castigar yield >5pp.
"""
import sqlite3
import sys
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402

DB = 'fondo_quant.db'
LIGAS_SESGO = ('Brasil', 'Inglaterra', 'Noruega', 'Turquia')


def min_ev_escalado(p, umbral):
    if p >= 0.50: return umbral
    if p >= 0.40: return umbral * 2.67
    if p >= 0.33: return umbral * 4.0
    return 999


def evaluar(p1, px, p2, c1, cx, c2, liga, params):
    """Evalua 1X2 con params configurables. params dict: floor, margen_mul, techo,
    ev, consenso_prob_min, consenso_cuota_min, consenso_cuota_max."""
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None, None
    floor  = params['floor']
    margen = params['margen_base'] * params.get('margen_mul', 1.0)
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15) * params.get('div_mul', 1.0)
    techo = params['techo']
    techo_alta = params['techo'] * 1.6  # ratio mantenido
    umbral_ev = params['ev']
    c_prob_min = params['consenso_prob_min']
    c_cuota_min = params['consenso_cuota_min']
    c_cuota_max = params['consenso_cuota_max']

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None, None
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = p_f * c_f - 1
    umb_f = umbral_ev * (0.5 / p_f) if p_f > 0 else 999
    div_f = p_f - 1/c_f

    # C1
    if p_f >= floor and c_f <= techo and ev_f >= umb_f and div_f <= div_max:
        return fav, c_f
    # C2B
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
        and ev_f >= min_ev_escalado(p_f, umbral_ev) and c_f <= techo_alta):
        return fav, c_f
    # C3
    if p_f >= floor and ev_f >= 1.0 and c_f <= techo_alta:
        return fav, c_f
    # C4 Consenso
    if fav == fav_mkt and p_f >= c_prob_min and c_cuota_min <= c_f <= c_cuota_max and div_f <= div_max:
        return fav, c_f
    # C2
    evs = {k: probs[k]*cuotas[k]-1 for k in probs}
    ev_k = max(evs, key=evs.get)
    p_e, c_e, m_e = probs[ev_k], cuotas[ev_k], evs[ev_k]
    umb_e = umbral_ev * (0.5/p_e) if p_e > 0 else 999
    div_e = p_e - 1/c_e
    if ev_k == 'VISITA' and 0.33 <= p_e < 0.40 and liga in LIGAS_SESGO:
        return None, None
    if c_e <= techo and m_e >= umb_e and div_e <= div_max:
        return ev_k, c_e
    return None, None


def simular(rows, params):
    n = g = 0
    ret = 0.0
    por_liga = {}
    for pa, p1, px, p2, c1, cx, c2, gl, gv in rows:
        pick, cuota = evaluar(p1, px, p2, c1, cx, c2, pa, params)
        if pick is None: continue
        n += 1
        gana = (pick=='LOCAL' and gl>gv) or (pick=='EMPATE' and gl==gv) or (pick=='VISITA' and gl<gv)
        if gana: g += 1; ret += cuota - 1
        else: ret -= 1
        por_liga.setdefault(pa, [0, 0, 0.0])
        por_liga[pa][0] += 1
        if gana: por_liga[pa][1] += 1; por_liga[pa][2] += cuota - 1
        else: por_liga[pa][2] -= 1
    hit = 100*g/n if n else 0
    y = 100*ret/n if n else 0
    return n, g, hit, y, por_liga


PARAMS_BASE = {
    'floor': 0.40,
    'margen_base': 0.03,
    'margen_mul': 1.0,
    'div_mul': 1.0,
    'techo': 5.0,
    'ev': 0.03,
    'consenso_prob_min': 0.45,
    'consenso_cuota_min': 1.40,
    'consenso_cuota_max': 2.00,
}


def cargar(con):
    return con.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2, goles_l, goles_v, fecha
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1>0 AND prob_x>0 AND prob_2>0
          AND cuota_1>0 AND cuota_x>0 AND cuota_2>0
        ORDER BY fecha ASC
    """).fetchall()


def main():
    con = sqlite3.connect(DB)
    rows = cargar(con)
    print(f'Total partidos liquidados con datos validos: {len(rows)}')

    # === 1. TRAIN/TEST SPLIT 60/40 CRONOLOGICO ===
    cut = int(len(rows) * 0.6)
    train = [r[:-1] for r in rows[:cut]]   # drop fecha
    test  = [r[:-1] for r in rows[cut:]]
    print(f'Train: {len(train)} (hasta {rows[cut-1][-1][:10]})')
    print(f'Test:  {len(test)} (desde {rows[cut][-1][:10]})')
    print()

    print('=== BASELINE (params actuales en produccion) ===')
    for label, data in [('TRAIN', train), ('TEST', test), ('ALL', train+test)]:
        n, g, hit, y, _ = simular(data, PARAMS_BASE)
        print(f'  {label:<6s} N={n:>3d} hit={hit:>5.1f}% yield={y:>+6.1f}%')
    print()

    # === 2. THRESHOLD TEST +-20% PARAMETRO POR PARAMETRO ===
    print('=== THRESHOLD TEST (+-20% por filtro, sobre TEST set) ===')
    print(f'{"Variacion":<35s} {"N":>4s} {"Hit%":>6s} {"Yield%":>7s} {"dN":>4s} {"dYield":>7s}')
    print('-'*72)
    n0, g0, hit0, y0, _ = simular(test, PARAMS_BASE)
    print(f'{"BASELINE":<35s} {n0:>4d} {hit0:>5.1f}% {y0:>+6.1f}%')
    print('-'*72)

    ajustes = [
        ('FLOOR 0.40 -> 0.32 (-20%)',      {'floor': 0.32}),
        ('FLOOR 0.40 -> 0.48 (+20%)',      {'floor': 0.48}),
        ('MARGEN 0.03 -> 0.024 (-20%)',    {'margen_mul': 0.80}),
        ('MARGEN 0.03 -> 0.036 (+20%)',    {'margen_mul': 1.20}),
        ('DIV max -20% (mas permisivo)',   {'div_mul': 0.80}),
        ('DIV max +20% (mas estricto)',    {'div_mul': 1.20}),
        ('TECHO 5.0 -> 4.0 (-20%)',        {'techo': 4.0}),
        ('TECHO 5.0 -> 6.0 (+20%)',        {'techo': 6.0}),
        ('EV 0.03 -> 0.024 (-20%)',        {'ev': 0.024}),
        ('EV 0.03 -> 0.036 (+20%)',        {'ev': 0.036}),
        ('C4 prob 0.45 -> 0.36 (-20%)',    {'consenso_prob_min': 0.36}),
        ('C4 prob 0.45 -> 0.54 (+20%)',    {'consenso_prob_min': 0.54}),
        ('C4 cuota min 1.40 -> 1.12 (-20%)', {'consenso_cuota_min': 1.12}),
        ('C4 cuota min 1.40 -> 1.68 (+20%)', {'consenso_cuota_min': 1.68}),
        ('C4 cuota max 2.00 -> 1.60 (-20%)', {'consenso_cuota_max': 1.60}),
        ('C4 cuota max 2.00 -> 2.40 (+20%)', {'consenso_cuota_max': 2.40}),
    ]
    resultados = []
    for label, overrides in ajustes:
        p = dict(PARAMS_BASE, **overrides)
        n, g, hit, y, _ = simular(test, p)
        dn = n - n0
        dy = y - y0
        resultados.append((label, n, hit, y, dn, dy))
        print(f'{label:<35s} {n:>4d} {hit:>5.1f}% {y:>+6.1f}% {dn:>+4d} {dy:>+6.1f}pp')

    print()
    # === CANDIDATOS INTERESANTES ===
    print('=== CANDIDATOS: volumen +N sin yield <-5pp (vs TEST baseline) ===')
    candidatos = [r for r in resultados if r[4] > 0 and r[5] > -5]
    if candidatos:
        for lbl, n, hit, y, dn, dy in sorted(candidatos, key=lambda x: x[4], reverse=True):
            print(f'  +{dn:>2d} picks  {lbl:<38s} hit={hit:.1f}% yield={y:+.1f}% dY={dy:+.1f}pp')
    else:
        print('  Ninguno pasa el filtro (vol+, yield-<5pp)')

    print()
    # === 3. COMBO TOP candidatos ===
    print('=== COMBOS TOP: combinar 2 ajustes que individualmente ganaron volumen ===')
    ganadores = [(lbl, a) for (lbl, a) in ajustes if any(
        lbl == r[0] and r[4] > 0 and r[5] > -5 for r in resultados
    )]
    print(f'Candidatos individuales positivos: {len(ganadores)}')
    for i, (lbl_a, a) in enumerate(ganadores):
        for lbl_b, b in ganadores[i+1:]:
            combo = {**a, **b}
            if set(a.keys()) & set(b.keys()):
                continue  # evitar duplicar el mismo filtro
            p = dict(PARAMS_BASE, **combo)
            n, g, hit, y, _ = simular(test, p)
            if (n - n0) > 2 and (y - y0) > -3:
                print(f'  COMBO: {lbl_a.split("(")[0].strip()} + {lbl_b.split("(")[0].strip():<30s} -> N={n} hit={hit:.1f}% y={y:+.1f}% (dN={n-n0:+d} dY={y-y0:+.1f}pp)')

    con.close()


if __name__ == '__main__':
    main()

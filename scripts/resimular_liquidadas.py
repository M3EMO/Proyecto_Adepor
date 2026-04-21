"""
RESIMULACION de apuestas liquidadas con los criterios ACTUALES.

Aplica los filtros de motor_calculadora HOY (fase 3.3.5) sobre los 223 partidos
liquidados para responder:
  1. Cuantas apuestas MAS habria hoy si los criterios actuales hubieran regido
     desde el principio? (C4 prob 0.36 + cuota_min 1.12 = mas volumen)
  2. Cual seria el N y hit rate por liga para el pretest?
  3. Cual seria el p-valor binomial con ese N?

ADVERTENCIA: esto es backtesting in-sample. Los criterios fueron calibrados
con exactamente estos datos. Usar estos numeros para decidir LIVE seria un
look-ahead bias. Sirve como visibilidad/referencia, no como justificacion
operativa para flipear ligas.
"""
import sqlite3
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402

DB = 'fondo_quant.db'
LIGAS_SESGO = ('Brasil', 'Inglaterra', 'Noruega', 'Turquia')


def min_ev_escalado(p, umbral=0.03):
    if p >= 0.50: return umbral
    if p >= 0.40: return umbral * 2.67
    if p >= 0.33: return umbral * 4.0
    return 999


def p_valor(n, k, p0=0.5):
    """Binomial one-sided: P(X >= k | n, p0)."""
    if n == 0 or k == 0:
        return 1.0
    return sum(comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i)) for i in range(k, n + 1))


def evaluar_actual(p1, px, p2, c1, cx, c2, liga):
    """Replica exactamente motor_calculadora hoy: fase 3.3.5.
    C4 prob_min=0.36, cuota_min=1.12, cuota_max=2.00."""
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None, None, None
    floor = 0.40
    margen = get_param('margen_predictivo_1x2', scope=liga, default=0.03)
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15)
    techo, techo_alta = 5.0, 8.0
    c4_prob = 0.36
    c4_cmin = 1.12
    c4_cmax = 2.00

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None, None, 'margen'
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = p_f * c_f - 1
    umb_f = 0.03 * (0.5 / p_f) if p_f > 0 else 999
    div_f = p_f - 1 / c_f

    # C1
    if p_f >= floor and c_f <= techo and ev_f >= umb_f and div_f <= div_max:
        return fav, c_f, 'C1'
    # C2B
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
            and ev_f >= min_ev_escalado(p_f) and c_f <= techo_alta):
        return fav, c_f, 'C2B'
    # C3
    if p_f >= floor and ev_f >= 1.0 and c_f <= techo_alta:
        return fav, c_f, 'C3'
    # C4 Consenso con Mercado
    if fav == fav_mkt and p_f >= c4_prob and c4_cmin <= c_f <= c4_cmax and div_f <= div_max:
        return fav, c_f, 'C4'
    # C2
    evs = {k: probs[k] * cuotas[k] - 1 for k in probs}
    ev_k = max(evs, key=evs.get)
    p_e, c_e, m_e = probs[ev_k], cuotas[ev_k], evs[ev_k]
    umb_e = 0.03 * (0.5 / p_e) if p_e > 0 else 999
    div_e = p_e - 1 / c_e
    if ev_k == 'VISITA' and 0.33 <= p_e < 0.40 and liga in LIGAS_SESGO:
        return None, None, 'F2b'
    if c_e <= techo and m_e >= umb_e and div_e <= div_max:
        return ev_k, c_e, 'C2'
    return None, None, 'PASAR'


def main():
    con = sqlite3.connect(DB)
    rows = con.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v, apuesta_1x2
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1>0 AND prob_x>0 AND prob_2>0
          AND cuota_1>0 AND cuota_x>0 AND cuota_2>0
    """).fetchall()

    # REAL: picks que se hicieron con criterios viejos
    from collections import defaultdict
    real_por_liga = defaultdict(lambda: {'n': 0, 'g': 0, 'ret': 0.0})
    for pa, p1, px, p2, c1, cx, c2, gl, gv, ap in rows:
        if not ap or '[GANADA]' not in ap and '[PERDIDA]' not in ap:
            continue
        real_por_liga[pa]['n'] += 1
        if '[GANADA]' in ap:
            real_por_liga[pa]['g'] += 1

    # SIMULACION: picks que harian los criterios ACTUALES
    sim_por_liga = defaultdict(lambda: {'n': 0, 'g': 0, 'ret': 0.0, 'caminos': defaultdict(lambda: [0, 0])})
    for pa, p1, px, p2, c1, cx, c2, gl, gv, ap in rows:
        pick, cuota, camino = evaluar_actual(p1, px, p2, c1, cx, c2, pa)
        if pick is None:
            continue
        gana = (pick == 'LOCAL' and gl > gv) or (pick == 'EMPATE' and gl == gv) or (pick == 'VISITA' and gl < gv)
        sim_por_liga[pa]['n'] += 1
        if gana:
            sim_por_liga[pa]['g'] += 1
            sim_por_liga[pa]['ret'] += cuota - 1
        else:
            sim_por_liga[pa]['ret'] -= 1
        sim_por_liga[pa]['caminos'][camino][0] += 1
        if gana:
            sim_por_liga[pa]['caminos'][camino][1] += 1

    # Comparacion por liga
    print('=' * 95)
    print('RESIMULACION: criterios actuales (fase 3.3.5) vs picks que se hicieron con los criterios viejos')
    print('=' * 95)
    print()
    print(f'{"Liga":<12s} | {"REAL (historico)":>35s} | {"SIMULADO (criterios actuales)":>45s}')
    print(f'{"":<12s} | {"N":>4s} {"g":>3s} {"hit%":>6s} | {"N":>4s} {"g":>3s} {"hit%":>6s} {"pval":>6s} {"dN":>4s} {"estado pretest"}')
    print('-' * 110)

    pretest_hit = float(get_param('pretest_hit_threshold', default=0.55) or 0.55)
    pretest_n = int(get_param('pretest_n_minimo', default=15) or 15)
    pretest_p = float(get_param('pretest_p_max', default=0.30) or 0.30)

    todas_ligas = sorted(set(list(real_por_liga.keys()) + list(sim_por_liga.keys())))
    for liga in todas_ligas:
        r = real_por_liga.get(liga, {'n': 0, 'g': 0})
        s = sim_por_liga.get(liga, {'n': 0, 'g': 0})
        hit_r = 100 * r['g'] / r['n'] if r['n'] else 0
        hit_s = 100 * s['g'] / s['n'] if s['n'] else 0
        pval_s = p_valor(s['n'], s['g'], 0.5)
        dn = s['n'] - r['n']
        # Evaluar criterio pretest con simulados
        if s['n'] < pretest_n:
            estado = f'wait N (+{pretest_n - s["n"]})'
        elif hit_s < 100 * pretest_hit:
            estado = f'wait hit ({hit_s:.0f}<{100 * pretest_hit:.0f})'
        elif pval_s > pretest_p:
            estado = f'wait p ({pval_s:.2f}>{pretest_p:.2f})'
        else:
            estado = 'LIVE (si se aceptara in-sample)'
        print(f'{liga:<12s} | {r["n"]:>4d} {r["g"]:>3d} {hit_r:>5.1f}% | {s["n"]:>4d} {s["g"]:>3d} {hit_s:>5.1f}% {pval_s:>6.3f} {dn:>+4d}  {estado}')

    print()
    # Totales
    total_r = sum(v['n'] for v in real_por_liga.values())
    total_r_g = sum(v['g'] for v in real_por_liga.values())
    total_s = sum(v['n'] for v in sim_por_liga.values())
    total_s_g = sum(v['g'] for v in sim_por_liga.values())
    total_s_ret = sum(v['ret'] for v in sim_por_liga.values())
    hit_r_tot = 100 * total_r_g / total_r if total_r else 0
    hit_s_tot = 100 * total_s_g / total_s if total_s else 0
    yld_s = 100 * total_s_ret / total_s if total_s else 0
    print(f'TOTAL REAL:      N={total_r:>4d}  hit={hit_r_tot:.1f}%  (lo que hay en DB hoy)')
    print(f'TOTAL SIMULADO:  N={total_s:>4d}  hit={hit_s_tot:.1f}%  yield={yld_s:+.1f}%  (si criterios actuales hubieran regido)')
    print(f'DELTA:           {total_s - total_r:+d} picks ({100*(total_s-total_r)/total_r:+.1f}%)')

    # Desglose por camino en la simulacion
    print()
    print('=== Picks simulados por CAMINO ===')
    print(f'{"Liga":<12s} {"C1":>6s} {"C2":>6s} {"C2B":>6s} {"C3":>6s} {"C4":>6s}')
    for liga in todas_ligas:
        s = sim_por_liga.get(liga, {'caminos': {}})
        cams = s.get('caminos', {})
        c1 = cams.get('C1', [0, 0])
        c2 = cams.get('C2', [0, 0])
        c2b = cams.get('C2B', [0, 0])
        c3 = cams.get('C3', [0, 0])
        c4 = cams.get('C4', [0, 0])
        if c1[0] + c2[0] + c2b[0] + c3[0] + c4[0] == 0:
            continue
        def _fmt(x):
            return f'{x[0]}/{x[1]}' if x[0] else '-'
        print(f'{liga:<12s} {_fmt(c1):>6s} {_fmt(c2):>6s} {_fmt(c2b):>6s} {_fmt(c3):>6s} {_fmt(c4):>6s}')
    print('   (formato: N_picks/ganadas; - = sin picks por ese camino)')

    con.close()


if __name__ == '__main__':
    main()

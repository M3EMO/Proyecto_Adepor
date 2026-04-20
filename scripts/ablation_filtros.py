"""
ABLATION STUDY — hit% y yield con distintas combinaciones de filtros ON/OFF.

Filtros evaluados:
  FLOOR     : prob_pick >= 0.40 (o 0.33 si OFF)
  F2b       : Camino 2 restringido en VISITA 33-40% + ligas sesgo
  MARGEN    : prob_fav - 2a_prob >= margen_por_liga
  EV        : EV >= umbral escalado
  DIV       : divergencia prob-mercado <= div_max_por_liga
  TECHO     : cuota <= 5.0

Se reimplementa la logica Cuatro Caminos localmente para poder togglear.
"""
import sqlite3
import sys
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402

DB = 'fondo_quant.db'

# Filtros disponibles (orden importa para el display)
FILTROS = ['FLOOR', 'F2b', 'MARGEN', 'EV', 'DIV', 'TECHO']
LIGAS_SESGO_VISITA = ('Brasil', 'Inglaterra', 'Noruega', 'Turquia')


def min_ev_escalado(prob):
    if prob >= 0.50: return 0.03
    if prob >= 0.40: return 0.08
    if prob >= 0.33: return 0.12
    return 999


def evaluar_con_filtros(p1, px, p2, c1, cx, c2, liga, filtros_on):
    """Devuelve pick string ('LOCAL', 'VISITA', 'EMPATE', None si PASAR)
    aplicando solo los filtros que estan en filtros_on (set)."""
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None

    floor = 0.40 if 'FLOOR' in filtros_on else 0.33
    margen = get_param('margen_predictivo_1x2', scope=liga, default=0.03) if 'MARGEN' in filtros_on else 0.0
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15) if 'DIV' in filtros_on else 1.0
    techo = 5.0 if 'TECHO' in filtros_on else 999.0
    techo_alta = 8.0 if 'TECHO' in filtros_on else 999.0
    chk_ev = 'EV' in filtros_on

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}

    # Margen predictivo
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None

    fav_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[fav_key], cuotas[fav_key]
    ev_fav = (p_fav * c_fav) - 1
    umb_fav = 0.03 * (0.5 / p_fav) if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)

    # Camino 1
    if (p_fav >= floor and c_fav <= techo
            and (not chk_ev or ev_fav >= umb_fav)
            and div_fav <= div_max):
        return fav_key

    # Camino 2B (desacuerdo)
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav_key != fav_mkt
            and p_fav >= 0.40
            and div_max < div_fav <= 0.30
            and (not chk_ev or ev_fav >= min_ev_escalado(p_fav))
            and c_fav <= techo_alta):
        return fav_key

    # Camino 3 (alta conviccion)
    if (p_fav >= floor and ev_fav >= 1.0 and c_fav <= techo_alta):
        return fav_key

    # Camino 2 (value hunting) - UTIMO
    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    ev_key = max(evs, key=evs.get)
    p_ev, c_ev, m_ev = probs[ev_key], cuotas[ev_key], evs[ev_key]
    umb_ev = 0.03 * (0.5 / p_ev) if p_ev > 0 else 999
    div_ev = p_ev - (1 / c_ev)

    # Filtro F2b
    if 'F2b' in filtros_on:
        if ev_key == 'VISITA' and 0.33 <= p_ev < 0.40 and liga in LIGAS_SESGO_VISITA:
            return None

    if (p_ev >= floor and c_ev <= techo
            and (not chk_ev or m_ev >= umb_ev)
            and div_ev <= div_max):
        return ev_key

    return None


def simular(filtros_on):
    """Simula sobre todos los liquidados con cuotas validas.
    Retorna (N_apuestas, N_ganadas, hit%, yield%)."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1 > 0 AND prob_x > 0 AND prob_2 > 0
          AND cuota_1 > 0 AND cuota_x > 0 AND cuota_2 > 0
    """).fetchall()
    con.close()

    n_apuestas = 0
    n_ganadas = 0
    total_stake = 0.0
    total_return = 0.0
    stake = 1.0  # flat stake

    for pais, p1, px, p2, c1, cx, c2, gl, gv in rows:
        pick = evaluar_con_filtros(p1, px, p2, c1, cx, c2, pais, filtros_on)
        if pick is None:
            continue
        n_apuestas += 1
        total_stake += stake
        cuota_apuesta = c1 if pick == 'LOCAL' else (cx if pick == 'EMPATE' else c2)
        gana = (pick == 'LOCAL' and gl > gv) or \
               (pick == 'EMPATE' and gl == gv) or \
               (pick == 'VISITA' and gl < gv)
        if gana:
            n_ganadas += 1
            total_return += stake * (cuota_apuesta - 1)
        else:
            total_return -= stake

    hit = 100 * n_ganadas / n_apuestas if n_apuestas else 0
    yield_pct = 100 * total_return / total_stake if total_stake else 0
    return n_apuestas, n_ganadas, hit, yield_pct


def main():
    # 1. Baseline: todos los filtros ON
    base = set(FILTROS)
    n_b, g_b, hit_b, y_b = simular(base)

    # 2. Baseline sin filtros (ninguno)
    n_0, g_0, hit_0, y_0 = simular(set())

    # 3. Ablation: dejar todos ON excepto uno
    print('=' * 90)
    print(f'BASELINE (todos los filtros ON): N={n_b}, ganadas={g_b}, hit={hit_b:.1f}%, yield={y_b:+.1f}%')
    print(f'CERO FILTROS (todos OFF):         N={n_0}, ganadas={g_0}, hit={hit_0:.1f}%, yield={y_0:+.1f}%')
    print('=' * 90)
    print()
    print('== Ablation: un filtro OFF a la vez (todos los demas ON) ==')
    print(f'{"OFF":<10s} {"N":>4s} {"Ganadas":>8s} {"Hit%":>7s} {"Yield%":>8s} {"ΔN_vs_base":>12s} {"ΔHit":>7s}')
    print('-' * 65)
    for f in FILTROS:
        sub = base - {f}
        n, g, hit, y = simular(sub)
        print(f'{f:<10s} {n:>4d} {g:>8d} {hit:>6.1f}% {y:>+7.1f}% {n-n_b:>+11d} {hit-hit_b:>+6.1f}pp')

    # 4. Ablation: un filtro ON (solo uno activo)
    print()
    print('== Ablation inversa: solo un filtro ON (resto OFF) ==')
    print(f'{"ON":<10s} {"N":>4s} {"Ganadas":>8s} {"Hit%":>7s} {"Yield%":>8s}')
    print('-' * 50)
    for f in FILTROS:
        n, g, hit, y = simular({f})
        print(f'{f:<10s} {n:>4d} {g:>8d} {hit:>6.1f}% {y:>+7.1f}%')

    # 5. Combinaciones de 2 filtros OFF
    print()
    print('== Pares de filtros OFF (resto ON) ==')
    print(f'{"OFF":<20s} {"N":>4s} {"Hit%":>7s} {"Yield%":>8s}')
    print('-' * 50)
    for f1, f2 in combinations(FILTROS, 2):
        sub = base - {f1, f2}
        n, g, hit, y = simular(sub)
        label = f'{f1}+{f2}'
        if hit >= 55 or (hit >= 50 and n >= n_b + 10):
            marca = ' <<< CANDIDATO'
        else:
            marca = ''
        print(f'{label:<20s} {n:>4d} {hit:>6.1f}% {y:>+7.1f}%{marca}')

    print()
    print('Notas:')
    print('  - CANDIDATO = hit >= 55% y N no demasiado menor al baseline')
    print('  - FLOOR OFF = permite picks con prob < 0.40 (hasta 0.33)')
    print('  - F2b OFF = NO restringe Camino 2 (VISITA 33-40% en ligas con sesgo)')
    print('  - MARGEN OFF = no requiere gap entre favorito y segunda opcion')
    print('  - EV OFF = no requiere EV positivo ni umbral escalado')
    print('  - DIV OFF = no filtra por info oculta (divergencia prob-mercado)')
    print('  - TECHO OFF = sin limite superior de cuota (5.0/8.0)')


if __name__ == '__main__':
    main()

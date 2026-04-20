"""Ablation study POR LIGA."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa

DB = 'fondo_quant.db'
FILTROS = ['FLOOR', 'F2b', 'MARGEN', 'EV', 'DIV', 'TECHO']
LIGAS_SESGO_VISITA = ('Brasil', 'Inglaterra', 'Noruega', 'Turquia')


def min_ev_escalado(prob):
    if prob >= 0.50: return 0.03
    if prob >= 0.40: return 0.08
    if prob >= 0.33: return 0.12
    return 999


def evaluar(p1, px, p2, c1, cx, c2, liga, filtros_on):
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
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen: return None
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = (p_f * c_f) - 1
    umb_f = 0.03 * (0.5 / p_f) if p_f > 0 else 999
    div_f = p_f - (1 / c_f)
    if (p_f >= floor and c_f <= techo and (not chk_ev or ev_f >= umb_f) and div_f <= div_max):
        return fav
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
            and (not chk_ev or ev_f >= min_ev_escalado(p_f)) and c_f <= techo_alta):
        return fav
    if p_f >= floor and ev_f >= 1.0 and c_f <= techo_alta:
        return fav
    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    ev_k = max(evs, key=evs.get)
    p_e, c_e, m_e = probs[ev_k], cuotas[ev_k], evs[ev_k]
    umb_e = 0.03 * (0.5 / p_e) if p_e > 0 else 999
    div_e = p_e - (1 / c_e)
    if 'F2b' in filtros_on:
        if ev_k == 'VISITA' and 0.33 <= p_e < 0.40 and liga in LIGAS_SESGO_VISITA:
            return None
    if (p_e >= floor and c_e <= techo and (not chk_ev or m_e >= umb_e) and div_e <= div_max):
        return ev_k
    return None


def cargar_datos():
    con = sqlite3.connect(DB)
    rows = con.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1>0 AND prob_x>0 AND prob_2>0
          AND cuota_1>0 AND cuota_x>0 AND cuota_2>0
    """).fetchall()
    con.close()
    return rows


def simular_liga(rows, liga, filtros_on):
    n_ap = n_g = 0
    stake = 1.0
    ret = 0.0
    for r in rows:
        if r[0] != liga: continue
        _, p1, px, p2, c1, cx, c2, _, _ = r
        pick = evaluar(p1, px, p2, c1, cx, c2, liga, filtros_on)
        if pick is None: continue
        n_ap += 1
        _, p1, px, p2, c1, cx, c2, gl, gv = r
        c_a = c1 if pick == 'LOCAL' else (cx if pick == 'EMPATE' else c2)
        gana = (pick == 'LOCAL' and gl > gv) or (pick == 'EMPATE' and gl == gv) or (pick == 'VISITA' and gl < gv)
        if gana:
            n_g += 1
            ret += stake * (c_a - 1)
        else:
            ret -= stake
    hit = 100 * n_g / n_ap if n_ap else 0
    y = 100 * ret / n_ap if n_ap else 0
    return n_ap, n_g, hit, y


def main():
    rows = cargar_datos()
    ligas = sorted(set(r[0] for r in rows))
    base = set(FILTROS)

    print('=' * 95)
    print('BASELINE (todos los filtros ON) por liga')
    print('=' * 95)
    print(f'{"Liga":<12s} {"N":>4s} {"Ganadas":>8s} {"Hit%":>7s} {"Yield%":>8s}')
    print('-' * 50)
    baselines = {}
    for liga in ligas:
        n, g, h, y = simular_liga(rows, liga, base)
        baselines[liga] = (n, g, h, y)
        if n > 0:
            print(f'{liga:<12s} {n:>4d} {g:>8d} {h:>6.1f}% {y:>+7.1f}%')

    # Ablation por liga
    for liga in ligas:
        nb, gb, hb, yb = baselines[liga]
        if nb == 0: continue
        n0, g0, h0, y0 = simular_liga(rows, liga, set())
        print()
        print('=' * 95)
        print(f'LIGA: {liga}  — baseline N={nb} hit={hb:.1f}%  yield={yb:+.1f}%  |  sin_filtros N={n0} hit={h0:.1f}% yield={y0:+.1f}%')
        print('=' * 95)
        print(f'{"Quitar":<10s} {"N":>4s} {"Ganadas":>8s} {"Hit%":>7s} {"Yield%":>8s} {"ΔN":>4s} {"ΔHit":>7s}')
        print('-' * 60)
        for f in FILTROS:
            sub = base - {f}
            n, g, h, y = simular_liga(rows, liga, sub)
            print(f'{f:<10s} {n:>4d} {g:>8d} {h:>6.1f}% {y:>+7.1f}% {n-nb:>+4d} {h-hb:>+6.1f}pp')


if __name__ == '__main__':
    main()

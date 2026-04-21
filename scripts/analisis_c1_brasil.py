"""
ANALISIS C1 BRASIL - threshold test con 3 opciones

Problema: en Brasil el Camino 1 tiene hit 38% en 21 picks (8/21).
Objetivo: probar ajustes para mejorar hit sin castigar yield global.

Opciones:
  A. FLOOR C1 subido a 0.50 (desde 0.40)
  B. UMBRAL_EV C1 subido a 0.05 (desde 0.03)
  C. C1 restringido a cuotas [1.50, 3.00]

Se evalua cada opcion individual + 4 combinaciones (A+B, A+C, B+C, A+B+C).
Solo afecta a CAMINO 1. C4/C2/C2B/C3 se mantienen identicos.
"""
import sqlite3
import sys
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


def evaluar(p1, px, p2, c1, cx, c2, liga,
            c1_floor=0.40, c1_ev=0.03, c1_cmin=0.0, c1_cmax=999.0):
    """Evalua motor_calculadora fase 3.3.5 con params C1 configurables."""
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None, None, None
    margen = get_param('margen_predictivo_1x2', scope=liga, default=0.03)
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15)
    techo, techo_alta = 5.0, 8.0

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None, None, 'margen'
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = p_f * c_f - 1
    # UMB C1 CONFIGURABLE (solo aqui, C4 sigue usando 0.03)
    umb_f_c1 = c1_ev * (0.5 / p_f) if p_f > 0 else 999
    umb_f_default = 0.03 * (0.5 / p_f) if p_f > 0 else 999
    div_f = p_f - 1 / c_f

    # C1 con restricciones ajustables
    if (p_f >= c1_floor and c_f <= techo and ev_f >= umb_f_c1
            and div_f <= div_max
            and c1_cmin <= c_f <= c1_cmax):
        return fav, c_f, 'C1'
    # C2B (usa default)
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
            and ev_f >= min_ev_escalado(p_f) and c_f <= techo_alta):
        return fav, c_f, 'C2B'
    # C3
    if p_f >= 0.40 and ev_f >= 1.0 and c_f <= techo_alta:
        return fav, c_f, 'C3'
    # C4 (SIN cambios: fase 3.3.5 prob=0.36 cuota 1.12-2.00)
    if fav == fav_mkt and p_f >= 0.36 and 1.12 <= c_f <= 2.00 and div_f <= div_max:
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


def simular(rows, params, solo_brasil=False):
    from collections import defaultdict
    per = defaultdict(lambda: {'n': 0, 'g': 0, 'ret': 0.0, 'caminos': defaultdict(lambda: [0, 0])})
    for pa, p1, px, p2, c1, cx, c2, gl, gv in rows:
        if solo_brasil and pa != 'Brasil':
            continue
        pick, cuota, cam = evaluar(p1, px, p2, c1, cx, c2, pa, **params)
        if pick is None:
            continue
        gana = (pick == 'LOCAL' and gl > gv) or (pick == 'VISITA' and gl < gv) or (pick == 'EMPATE' and gl == gv)
        per[pa]['n'] += 1
        per[pa]['caminos'][cam][0] += 1
        if gana:
            per[pa]['g'] += 1
            per[pa]['ret'] += cuota - 1
            per[pa]['caminos'][cam][1] += 1
        else:
            per[pa]['ret'] -= 1
    return per


def reportar(nombre, per):
    total_n = sum(v['n'] for v in per.values())
    total_g = sum(v['g'] for v in per.values())
    total_ret = sum(v['ret'] for v in per.values())
    hit = 100 * total_g / total_n if total_n else 0
    yld = 100 * total_ret / total_n if total_n else 0
    # Brasil especifico
    br = per.get('Brasil', {'n': 0, 'g': 0, 'ret': 0.0, 'caminos': {}})
    br_c1 = br['caminos'].get('C1', [0, 0])
    br_hit = 100 * br['g'] / br['n'] if br['n'] else 0
    br_yld = 100 * br['ret'] / br['n'] if br['n'] else 0
    br_c1_hit = 100 * br_c1[1] / br_c1[0] if br_c1[0] else 0
    print(f'{nombre:<35s} | Global N={total_n:>3d} hit={hit:>5.1f}% y={yld:>+6.1f}% | '
          f'Brasil N={br["n"]:>3d} hit={br_hit:>5.1f}% y={br_yld:>+6.1f}% | '
          f'BR-C1 {br_c1[1]}/{br_c1[0]} ({br_c1_hit:>5.1f}%)')


def main():
    con = sqlite3.connect(DB)
    rows = con.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1>0 AND prob_x>0 AND prob_2>0 AND cuota_1>0 AND cuota_x>0 AND cuota_2>0
    """).fetchall()
    print(f'N liquidados: {len(rows)}')
    print()

    # Parametros base (fase 3.3.5 actual) — C1 sin restricciones extra
    BASE = {'c1_floor': 0.40, 'c1_ev': 0.03, 'c1_cmin': 0.0, 'c1_cmax': 999.0}
    A    = {'c1_floor': 0.50, 'c1_ev': 0.03, 'c1_cmin': 0.0, 'c1_cmax': 999.0}
    B    = {'c1_floor': 0.40, 'c1_ev': 0.05, 'c1_cmin': 0.0, 'c1_cmax': 999.0}
    C    = {'c1_floor': 0.40, 'c1_ev': 0.03, 'c1_cmin': 1.50, 'c1_cmax': 3.00}
    AB   = {'c1_floor': 0.50, 'c1_ev': 0.05, 'c1_cmin': 0.0, 'c1_cmax': 999.0}
    AC   = {'c1_floor': 0.50, 'c1_ev': 0.03, 'c1_cmin': 1.50, 'c1_cmax': 3.00}
    BC   = {'c1_floor': 0.40, 'c1_ev': 0.05, 'c1_cmin': 1.50, 'c1_cmax': 3.00}
    ABC  = {'c1_floor': 0.50, 'c1_ev': 0.05, 'c1_cmin': 1.50, 'c1_cmax': 3.00}

    configs = [
        ('BASELINE (actual)',                BASE),
        ('A: FLOOR_C1=0.50',                 A),
        ('B: EV_C1=0.05',                    B),
        ('C: CUOTA_C1 [1.50-3.00]',          C),
        ('A+B: FLOOR=0.50 + EV=0.05',        AB),
        ('A+C: FLOOR=0.50 + CUOTA [1.5-3]',  AC),
        ('B+C: EV=0.05 + CUOTA [1.5-3]',     BC),
        ('A+B+C (todo junto)',               ABC),
    ]

    print('=' * 130)
    print('COMPARATIVA (cambios SOLO para Camino 1; C4/C2/C2B/C3 intactos):')
    print('=' * 130)
    for nombre, params in configs:
        per = simular(rows, params)
        reportar(nombre, per)

    print()
    print('=' * 130)
    print('DESGLOSE POR LIGA — configuracion ganadora vs BASELINE:')
    print('=' * 130)

    # Compare BASELINE vs cada opcion: mostrar delta por liga
    per_base = simular(rows, BASE)
    base_brasil = per_base.get('Brasil', {})

    print()
    print(f'{"Config":<28s} {"Liga":<12s} {"dN":>4s} {"dHit":>6s} {"dYield":>7s}')
    print('-' * 70)
    for nombre, params in configs[1:]:
        per_new = simular(rows, params)
        for liga in sorted(set(per_base.keys()) | set(per_new.keys())):
            b = per_base.get(liga, {'n': 0, 'g': 0, 'ret': 0.0})
            n = per_new.get(liga, {'n': 0, 'g': 0, 'ret': 0.0})
            if b['n'] == 0 and n['n'] == 0:
                continue
            h_b = 100 * b['g'] / b['n'] if b['n'] else 0
            h_n = 100 * n['g'] / n['n'] if n['n'] else 0
            y_b = 100 * b['ret'] / b['n'] if b['n'] else 0
            y_n = 100 * n['ret'] / n['n'] if n['n'] else 0
            dn = n['n'] - b['n']
            dh = h_n - h_b
            dy = y_n - y_b
            if abs(dn) > 0 or abs(dh) > 1:  # filtrar ruido
                print(f'{nombre:<28s} {liga:<12s} {dn:>+4d} {dh:>+5.1f}pp {dy:>+6.1f}pp')
        print()

    con.close()


if __name__ == '__main__':
    main()

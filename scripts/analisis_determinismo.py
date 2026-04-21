"""
ANALISIS DETERMINISMO via Temperature Scaling
==============================================
Problema: 80% de partidos tienen prob_fav 40-50%, 0% llega a 60%.
Causa: Poisson natural produce distribuciones parejas con lambdas ~1.1-1.2.

Solucion propuesta: post-procesar las probs con temperature T>1:
    p_i' = p_i^T / sum(p_j^T)

T=1.0 -> probs originales (baseline)
T=1.3 -> moderadamente mas determinante
T=1.5 -> bastante mas determinante
T=2.0 -> muy determinante (riesgo overfit)

Medimos 4 cosas sobre TEST set:
1. Volumen de picks generados
2. Hit rate
3. Yield
4. Brier score (calibracion) - si sube mucho, perdimos informacion real

El ganador deberia tener: volumen+, yield+, Brier cercano al baseline.
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


def temperature(p1, px, p2, T):
    """Aplica temperature scaling a las 3 probs y renormaliza."""
    if T == 1.0:
        return p1, px, p2
    a = p1 ** T
    b = px ** T
    c = p2 ** T
    s = a + b + c
    if s == 0: return p1, px, p2
    return a/s, b/s, c/s


def evaluar(p1, px, p2, c1, cx, c2, liga):
    """Evalua con params 3.3.4 actuales."""
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None, None
    floor = 0.40
    margen = get_param('margen_predictivo_1x2', scope=liga, default=0.03)
    div_max = get_param('divergencia_max_1x2', scope=liga, default=0.15)
    techo, techo_alta = 5.0, 8.0

    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    ord_p = sorted([p1, px, p2])
    if (ord_p[2] - ord_p[1]) < margen:
        return None, None
    fav = max(probs, key=probs.get)
    p_f, c_f = probs[fav], cuotas[fav]
    ev_f = p_f * c_f - 1
    umb_f = 0.03 * (0.5/p_f) if p_f > 0 else 999
    div_f = p_f - 1/c_f

    if p_f >= floor and c_f <= techo and ev_f >= umb_f and div_f <= div_max:
        return fav, c_f
    fav_mkt = min(cuotas, key=cuotas.get)
    if (fav != fav_mkt and p_f >= 0.40 and div_max < div_f <= 0.30
        and ev_f >= min_ev_escalado(p_f) and c_f <= techo_alta):
        return fav, c_f
    if p_f >= floor and ev_f >= 1.0 and c_f <= techo_alta:
        return fav, c_f
    # C4 con prob_min 0.36 (post fase 3.3.4)
    if fav == fav_mkt and p_f >= 0.36 and 1.40 <= c_f <= 2.00 and div_f <= div_max:
        return fav, c_f
    evs = {k: probs[k]*cuotas[k]-1 for k in probs}
    ev_k = max(evs, key=evs.get)
    p_e, c_e, m_e = probs[ev_k], cuotas[ev_k], evs[ev_k]
    umb_e = 0.03 * (0.5/p_e) if p_e > 0 else 999
    div_e = p_e - 1/c_e
    if ev_k == 'VISITA' and 0.33 <= p_e < 0.40 and liga in LIGAS_SESGO:
        return None, None
    if c_e <= techo and m_e >= umb_e and div_e <= div_max:
        return ev_k, c_e
    return None, None


def simular_T(rows, T):
    """Simula con temperature T aplicada a las probs."""
    n = g = 0
    ret = 0.0
    brier_sum = 0
    brier_n = 0
    maxp_bucket = {'<40': 0, '40-50': 0, '50-60': 0, '>=60': 0}
    for pa, p1, px, p2, c1, cx, c2, gl, gv in rows:
        p1t, pxt, p2t = temperature(p1, px, p2, T)
        # Brier
        o1 = 1 if gl > gv else 0
        ox = 1 if gl == gv else 0
        o2 = 1 if gl < gv else 0
        brier_sum += (p1t-o1)**2 + (pxt-ox)**2 + (p2t-o2)**2
        brier_n += 1
        maxp = max(p1t, pxt, p2t)
        if maxp < 0.40: maxp_bucket['<40'] += 1
        elif maxp < 0.50: maxp_bucket['40-50'] += 1
        elif maxp < 0.60: maxp_bucket['50-60'] += 1
        else: maxp_bucket['>=60'] += 1
        # Evaluar picks con probs transformadas
        pick, cuota = evaluar(p1t, pxt, p2t, c1, cx, c2, pa)
        if pick is None: continue
        n += 1
        gana = (pick=='LOCAL' and gl>gv) or (pick=='EMPATE' and gl==gv) or (pick=='VISITA' and gl<gv)
        if gana: g += 1; ret += cuota-1
        else: ret -= 1
    hit = 100*g/n if n else 0
    y = 100*ret/n if n else 0
    brier = brier_sum / brier_n if brier_n else 0
    return n, g, hit, y, brier, maxp_bucket


def main():
    con = sqlite3.connect(DB)
    rows = con.execute("""
        SELECT pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND prob_1>0 AND prob_x>0 AND prob_2>0 AND cuota_1>0 AND cuota_x>0 AND cuota_2>0
        ORDER BY fecha ASC
    """).fetchall()

    cut = int(len(rows) * 0.6)
    train = rows[:cut]
    test = rows[cut:]

    print(f'Train: {len(train)}  Test: {len(test)}')
    print()
    print(f'{"T":>4s} | {"N":>4s} {"hit%":>6s} {"yield%":>7s} {"Brier":>7s} | {"<40":>4s} {"40-50":>6s} {"50-60":>6s} {">=60":>5s}')
    print('-'*80)

    for T in [1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0]:
        n, g, hit, y, brier, bucket = simular_T(test, T)
        total_maxp = sum(bucket.values())
        p40 = 100*bucket['<40']/total_maxp if total_maxp else 0
        p45 = 100*bucket['40-50']/total_maxp if total_maxp else 0
        p55 = 100*bucket['50-60']/total_maxp if total_maxp else 0
        p60 = 100*bucket['>=60']/total_maxp if total_maxp else 0
        marca = '  <-- baseline' if T == 1.0 else ''
        print(f'{T:>4.1f} | {n:>4d} {hit:>5.1f}% {y:>+6.1f}% {brier:>7.4f} | {p40:>3.0f}% {p45:>5.0f}% {p55:>5.0f}% {p60:>4.0f}%{marca}')

    print()
    print('=== Impacto combinado con MARGEN reducido (-20% = 0.024) y T scaling ===')
    # Hmm, requiere modificar evaluar() para aceptar margen override. Lo omitimos por brevedad.

    print()
    print('Leyenda:')
    print('  Brier mas bajo = mejor calibracion (baseline 0.586-0.620)')
    print('  >=60% = % de partidos donde el favorito tiene prob dominante')
    print('  Si T sube, Brier sube (perdemos calibracion) pero las probs son mas utilizables por los filtros')

    con.close()


if __name__ == '__main__':
    main()

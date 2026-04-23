"""
TEST COMPARATIVO — mide impacto real de beta-scaling + piecewise (paso 2+3)
sobre Brier con hold-out temporal. Separa calibracion de evaluacion.

Metodo:
  1. Ordena los liquidados cronologicamente.
  2. Split 50/50 por fecha: train antiguo, test reciente.
  3. Calibra piecewise + beta SOLO sobre train.
  4. Aplica a probs de test y mide BS.

Reporta:
  - BS crudo vs beta vs piecewise (sobre test)
  - Delta por liga
  - Verificacion: yield simulado con reglas_actuales NO cambia (probs crudas intactas).
"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.comun.reglas_actuales import evaluar_actual  # noqa: E402

BUCKET_SIZE = 0.05
N_MIN_BUCKET = 5


def fit_beta(rows, idx_p, fy):
    best = (1.0, 0.0, float('inf'))
    for a10 in range(50, 151):
        a = a10 / 100.0
        for b100 in range(-20, 21):
            b = b100 / 100.0
            total = sum((max(0, min(1, a * r[idx_p] + b)) - fy(r)) ** 2 for r in rows)
            if total < best[2]:
                best = (a, b, total)
    return best


def build_map(rows, idx_p, fy, bucket_size=BUCKET_SIZE, n_min=N_MIN_BUCKET):
    m = {}
    n_buckets = int(1 / bucket_size)
    for i in range(n_buckets):
        lo = round(i * bucket_size, 4)
        hi = round(lo + bucket_size, 4)
        items = [fy(r) for r in rows if lo <= r[idx_p] < hi]
        if len(items) >= n_min:
            m[(lo, hi)] = sum(items) / len(items)
    return m


def apply_bucket(p, m):
    for (lo, hi), v in m.items():
        if lo <= p < hi:
            return v
    return None


def bs(p1, px, p2, y1, yx, y2):
    return (p1 - y1) ** 2 + (px - yx) ** 2 + (p2 - y2) ** 2


def main():
    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()
    cur.execute("""
        SELECT fecha, pais, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND prob_1 > 0 AND cuota_1 > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha
    """)
    raw = cur.fetchall()
    if len(raw) < 60:
        print(f"[ERROR] N={len(raw)} insuficiente.")
        return

    # Parse fecha + tupla (p1,px,p2,gl,gv,cuota1,cx,c2,pais)
    rows = []
    for fecha, pais, p1, px, p2, c1, cx, c2, gl, gv in raw:
        try:
            d = datetime.strptime(fecha[:10], '%Y-%m-%d')
        except Exception:
            continue
        rows.append((d, pais, p1, px, p2, c1, cx, c2, gl, gv))
    rows.sort(key=lambda x: x[0])
    n = len(rows)
    mid = n // 2
    train = rows[:mid]
    test = rows[mid:]
    print(f"N total={n}  train (<= {train[-1][0].date()}): {len(train)}  test (>= {test[0][0].date()}): {len(test)}")

    # Fit calibraciones sobre TRAIN (sin pais en idxs, adaptar)
    # Tuplas para fit: (p1, px, p2, gl, gv) => idx p=0/1/2, goles=3/4
    train_calib = [(r[2], r[3], r[4], r[8], r[9]) for r in train]
    y1 = lambda r: 1.0 if r[3] > r[4] else 0.0    # noqa: E731
    yx = lambda r: 1.0 if r[3] == r[4] else 0.0   # noqa: E731
    y2 = lambda r: 1.0 if r[3] < r[4] else 0.0    # noqa: E731

    a1, b1, _ = fit_beta(train_calib, 0, y1)
    ax, bx, _ = fit_beta(train_calib, 1, yx)
    a2, b2, _ = fit_beta(train_calib, 2, y2)
    m1 = build_map(train_calib, 0, y1)
    mx = build_map(train_calib, 1, yx)
    m2 = build_map(train_calib, 2, y2)

    print(f"\nBeta fitted (train): P1 a={a1:.2f} b={b1:+.2f} | PX a={ax:.2f} b={bx:+.2f} | P2 a={a2:.2f} b={b2:+.2f}")
    print(f"Piecewise buckets fitted (train, N>={N_MIN_BUCKET}): P1={len(m1)} PX={len(mx)} P2={len(m2)}")

    # Evaluar sobre TEST
    bs_raw = bs_beta = bs_pw = 0.0
    por_liga_raw = defaultdict(list)
    por_liga_pw = defaultdict(list)
    picks_raw = picks_pw = 0
    hit_raw = hit_pw = 0
    yld_raw = yld_pw = 0.0

    for d, pais, p1, px, p2, c1, cx, c2, gl, gv in test:
        y_1, y_x, y_2 = (1 if gl > gv else 0), (1 if gl == gv else 0), (1 if gl < gv else 0)
        bs_raw += bs(p1, px, p2, y_1, y_x, y_2)
        por_liga_raw[pais].append(bs(p1, px, p2, y_1, y_x, y_2))

        # Beta-scaling
        q1b = max(0, min(1, a1 * p1 + b1))
        qxb = max(0, min(1, ax * px + bx))
        q2b = max(0, min(1, a2 * p2 + b2))
        s = q1b + qxb + q2b
        if s > 0:
            q1b, qxb, q2b = q1b / s, qxb / s, q2b / s
        bs_beta += bs(q1b, qxb, q2b, y_1, y_x, y_2)

        # Piecewise con fallback beta por salida
        q1p = apply_bucket(p1, m1)
        if q1p is None: q1p = q1b
        qxp = apply_bucket(px, mx)
        if qxp is None: qxp = qxb
        q2p = apply_bucket(p2, m2)
        if q2p is None: q2p = q2b
        s = q1p + qxp + q2p
        if s > 0:
            q1p, qxp, q2p = q1p / s, qxp / s, q2p / s
        bs_pw += bs(q1p, qxp, q2p, y_1, y_x, y_2)
        por_liga_pw[pais].append(bs(q1p, qxp, q2p, y_1, y_x, y_2))

        # Yield check: picks con reglas actuales (usa probs CRUDAS)
        pick, cuota, _ = evaluar_actual(p1, px, p2, c1, cx, c2, pais)
        if pick:
            picks_raw += 1
            gana = ((pick == 'LOCAL' and gl > gv) or (pick == 'EMPATE' and gl == gv) or (pick == 'VISITA' and gl < gv))
            if gana: hit_raw += 1; yld_raw += (cuota - 1)
            else: yld_raw += -1

    n_t = len(test)
    bs_raw /= n_t; bs_beta /= n_t; bs_pw /= n_t
    print(f"\n=== HOLD-OUT (test N={n_t}) ===")
    print(f"{'Estrategia':<22} {'BS':>8} {'delta':>10}")
    print(f"{'Crudo':<22} {bs_raw:>8.4f} {'baseline':>10}")
    print(f"{'Beta-scaling':<22} {bs_beta:>8.4f} {bs_beta-bs_raw:>+10.4f}")
    print(f"{'Piecewise (fb beta)':<22} {bs_pw:>8.4f} {bs_pw-bs_raw:>+10.4f}")
    print()

    # Por liga
    print(f"\n=== Breakdown por liga (test) ===")
    print(f"{'Liga':<12} {'N':>4} {'BS_raw':>8} {'BS_pw':>8} {'delta':>8}")
    for pais in sorted(por_liga_raw.keys()):
        br = por_liga_raw[pais]
        bp = por_liga_pw[pais]
        if len(br) < 3:
            continue
        bsr = sum(br) / len(br); bsp = sum(bp) / len(bp)
        print(f"{pais:<12} {len(br):>4} {bsr:>8.4f} {bsp:>8.4f} {bsp-bsr:>+8.4f}")

    # Yield verification
    print(f"\n=== Yield verification (picks solo con probs crudas, no cambia) ===")
    if picks_raw:
        hit_pct = 100 * hit_raw / picks_raw
        yld_pct = 100 * yld_raw / picks_raw
        print(f"Test picks N={picks_raw}  hit={hit_pct:.1f}%  yield={yld_pct:+.1f}%")
        print(f"(las probs calibradas son display-only; el motor sigue usando crudas)")

    con.close()


if __name__ == '__main__':
    main()

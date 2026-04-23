"""
CALIBRAR_PIECEWISE — calibracion por buckets 5pp de probs 1X2 (display-only).

Para cada salida (P1, PX, P2), divide el rango [0, 1] en 20 buckets de 5pp
y mapea cada bucket a la frecuencia empirica real observada en liquidados.
Buckets con N < 5 se dejan sin mapeo (se usa beta-scaling o prob cruda como
fallback).

Ventaja vs beta-scaling: captura no-linealidades (ej: subconfianza solo en
buckets centrales 40-60%). Desventaja: mas parametros -> mas riesgo overfit.
Mitigacion: umbral N>=5 por bucket + recalibracion mensual rolling.

Fundamento empirico (optimizador_modelo 2026-04-22):
  Hold-out: BS 0.6101 -> 0.5583 con piecewise (-0.0518, mejor que beta -0.0235).

Uso:
  py scripts/calibrar_piecewise.py              # reporta y guarda mapas
  py scripts/calibrar_piecewise.py --dry-run    # solo reporta
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_sistema import DB_NAME  # noqa: E402

BUCKET_SIZE = 0.05
N_MIN_BUCKET = 5  # minimo de samples por bucket para considerar el mapeo valido


def build_map(rows, idx_p, fy, bucket_size=BUCKET_SIZE, n_min=N_MIN_BUCKET):
    """Construye mapa bucket -> freq empirica sobre rows."""
    n_buckets = int(1 / bucket_size)
    m = {}
    stats = {}
    for i in range(n_buckets):
        lo = round(i * bucket_size, 4)
        hi = round(lo + bucket_size, 4)
        items = [fy(r) for r in rows if lo <= r[idx_p] < hi]
        stats[f'{lo:.2f}-{hi:.2f}'] = len(items)
        if len(items) >= n_min:
            freq = sum(items) / len(items)
            m[f'{lo:.2f}-{hi:.2f}'] = round(freq, 4)
    return m, stats


def main(dry_run=False):
    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()
    cur.execute("""
        SELECT prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND prob_1 > 0 AND prob_x > 0 AND prob_2 > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """)
    rows = cur.fetchall()
    n = len(rows)
    if n < 60:
        print(f"[ERROR] N={n} insuficiente para piecewise (minimo 60).")
        con.close()
        return 1

    y1 = lambda r: 1.0 if r[3] > r[4] else 0.0   # noqa: E731
    yx = lambda r: 1.0 if r[3] == r[4] else 0.0  # noqa: E731
    y2 = lambda r: 1.0 if r[3] < r[4] else 0.0   # noqa: E731

    m1, s1 = build_map(rows, 0, y1)
    mx, sx = build_map(rows, 1, yx)
    m2, s2 = build_map(rows, 2, y2)

    print(f"\n=== Mapas piecewise 5pp sobre N={n} liquidados ===")
    print(f"Bucket  |  P1 (freq_local)     PX (freq_empate)     P2 (freq_visita)")
    print("-" * 75)
    n_buckets = int(1 / BUCKET_SIZE)
    for i in range(n_buckets):
        lo = round(i * BUCKET_SIZE, 4)
        hi = round(lo + BUCKET_SIZE, 4)
        k = f'{lo:.2f}-{hi:.2f}'
        p1_info = f"{m1[k]:.3f} (N={s1[k]})" if k in m1 else f"-      (N={s1[k]})"
        px_info = f"{mx[k]:.3f} (N={sx[k]})" if k in mx else f"-      (N={sx[k]})"
        p2_info = f"{m2[k]:.3f} (N={s2[k]})" if k in m2 else f"-      (N={s2[k]})"
        # Filtrar filas con todos buckets vacios para reducir ruido
        if s1[k] == 0 and sx[k] == 0 and s2[k] == 0:
            continue
        print(f"{k}   {p1_info:<20}  {px_info:<20}  {p2_info}")

    # Evaluar BS crudo vs calibrado piecewise (in-sample, usando mismo N -> optimista)
    def apply_map(p, m):
        for k, v in m.items():
            lo_s, hi_s = k.split('-')
            if float(lo_s) <= p < float(hi_s):
                return v
        return p  # sin mapeo -> devuelve cruda

    bs_crudo = 0.0
    bs_cal = 0.0
    for r in rows:
        p1, px, p2, gl, gv = r
        y_1 = 1 if gl > gv else 0
        y_x = 1 if gl == gv else 0
        y_2 = 1 if gl < gv else 0
        bs_crudo += (p1 - y_1) ** 2 + (px - y_x) ** 2 + (p2 - y_2) ** 2
        q1 = apply_map(p1, m1)
        qx = apply_map(px, mx)
        q2 = apply_map(p2, m2)
        s = q1 + qx + q2
        if s > 0:
            q1, qx, q2 = q1 / s, qx / s, q2 / s
        bs_cal += (q1 - y_1) ** 2 + (qx - y_x) ** 2 + (q2 - y_2) ** 2
    bs_crudo /= n
    bs_cal /= n

    print()
    print(f"Brier 1X2 crudo          = {bs_crudo:.4f}")
    print(f"Brier 1X2 piecewise cal. = {bs_cal:.4f}")
    print(f"Delta                    = {bs_crudo - bs_cal:+.4f}  ({100*(bs_crudo-bs_cal)/bs_crudo:+.1f}%)")
    print("(in-sample; holdout real ~0.5-0.6x del delta in-sample)")
    print()

    if dry_run:
        print("[dry-run] No se guardaron mapas en DB.")
        con.close()
        return 0

    # Guardar los 3 mapas como JSON en config_motor_valores (valor_texto)
    mapas = {'p1': m1, 'px': mx, 'p2': m2, 'n_total': n, 'n_min_bucket': N_MIN_BUCKET}
    fuente = f'calibrar_piecewise_2026-04-22_N={n}'
    cur.execute("""
        INSERT INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
        VALUES ('piecewise_calibration_map', 'global', NULL, ?, 'text', ?, 0, datetime('now'))
        ON CONFLICT(clave, scope) DO UPDATE SET
            valor_texto=excluded.valor_texto,
            fuente=excluded.fuente,
            fecha_actualizacion=excluded.fecha_actualizacion
    """, (json.dumps(mapas), fuente))
    con.commit()
    con.close()
    print("Mapas piecewise guardados en config_motor_valores (scope=global).")
    return 0


if __name__ == '__main__':
    main(dry_run='--dry-run' in sys.argv)

"""
CALIBRAR_BETA — calibración Beta-scaling lineal de probs 1X2 (display-only).

Ajusta un mapeo lineal p' = a*p + b por cada salida (P1, PX, P2) sobre todos
los liquidados para minimizar el Brier individual. Los 6 coeficientes se
guardan en config_motor_valores y se aplican SOLO en display/auditoria del
Excel — el motor de picks sigue usando probs crudas (yield intacto).

Fundamento empirico (reporte optimizador_modelo 2026-04-22):
  El modelo comprime empate en exceso (ax < 1) y estira favorito/underdog
  (a1, a2 > 1). En hold-out N=163 mejora Brier de 0.6101 a 0.5867 (-0.0234).

Uso:
  py scripts/calibrar_beta.py                 # reporta y guarda coeficientes
  py scripts/calibrar_beta.py --dry-run       # solo reporta
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_sistema import DB_NAME  # noqa: E402


def bs_p(pred, y):
    """Brier component de una salida binaria."""
    return (pred - y) ** 2


def fit_beta_grid(rows, idx_p, fy):
    """Grid search a in [0.50, 1.50] step 0.01, b in [-0.20, 0.20] step 0.01
    minimizando sum((a*p + b) - y)^2 sobre los rows."""
    best = (1.0, 0.0, float('inf'))
    for a10 in range(50, 151):
        a = a10 / 100.0
        for b100 in range(-20, 21):
            b = b100 / 100.0
            total = 0.0
            for r in rows:
                p = max(0.0, min(1.0, a * r[idx_p] + b))
                y = fy(r)
                total += (p - y) ** 2
            if total / len(rows) < best[2]:
                best = (a, b, total / len(rows))
    return best


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
    if n < 30:
        print(f"[ERROR] N={n} insuficiente para calibrar beta (minimo 30).")
        con.close()
        return 1

    # y1,yx,y2 esperan tuplas (p1, px, p2, gl, gv) donde gl=idx 3, gv=idx 4
    y1 = lambda r: 1.0 if r[3] > r[4] else 0.0  # noqa: E731
    yx = lambda r: 1.0 if r[3] == r[4] else 0.0  # noqa: E731
    y2 = lambda r: 1.0 if r[3] < r[4] else 0.0  # noqa: E731

    a1, b1, bs1 = fit_beta_grid(rows, 0, y1)
    ax, bx, bsx = fit_beta_grid(rows, 1, yx)
    a2, b2, bs2 = fit_beta_grid(rows, 2, y2)

    # Brier crudo de referencia (sin calibrar)
    bs_crudo = 0.0
    for r in rows:
        p1, px, p2, gl, gv = r
        y_1, y_x, y_2 = y1(r), yx(r), y2(r)
        bs_crudo += (p1 - y_1) ** 2 + (px - y_x) ** 2 + (p2 - y_2) ** 2
    bs_crudo /= n

    # Brier calibrado (aplicando los coefs in-sample)
    bs_cal = 0.0
    for r in rows:
        p1, px, p2, gl, gv = r
        q1 = max(0.0, min(1.0, a1 * p1 + b1))
        qx = max(0.0, min(1.0, ax * px + bx))
        q2 = max(0.0, min(1.0, a2 * p2 + b2))
        s = q1 + qx + q2
        if s > 0:
            q1, qx, q2 = q1 / s, qx / s, q2 / s
        y_1, y_x, y_2 = y1(r), yx(r), y2(r)
        bs_cal += (q1 - y_1) ** 2 + (qx - y_x) ** 2 + (q2 - y_2) ** 2
    bs_cal /= n

    print(f"\n=== Calibracion Beta-scaling sobre N={n} liquidados ===")
    print(f"P1:  a={a1:.3f}  b={b1:+.3f}  (BS_p1 fit={bs1:.4f})")
    print(f"PX:  a={ax:.3f}  b={bx:+.3f}  (BS_px fit={bsx:.4f})")
    print(f"P2:  a={a2:.3f}  b={b2:+.3f}  (BS_p2 fit={bs2:.4f})")
    print()
    print(f"Brier 1X2 crudo     = {bs_crudo:.4f}")
    print(f"Brier 1X2 calibrado = {bs_cal:.4f}")
    print(f"Delta               = {bs_crudo - bs_cal:+.4f}  ({100*(bs_crudo-bs_cal)/bs_crudo:+.1f}%)")
    print()

    if dry_run:
        print("[dry-run] No se guardaron coeficientes en DB.")
        con.close()
        return 0

    # Guardar en config_motor_valores
    claves = [
        ('beta_scale_a_p1', a1), ('beta_scale_b_p1', b1),
        ('beta_scale_a_px', ax), ('beta_scale_b_px', bx),
        ('beta_scale_a_p2', a2), ('beta_scale_b_p2', b2),
    ]
    fuente = f'calibrar_beta_2026-04-22_N={n}'
    for clave, valor in claves:
        cur.execute("""
            INSERT INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
            VALUES (?, 'global', ?, NULL, 'float', ?, 0, datetime('now'))
            ON CONFLICT(clave, scope) DO UPDATE SET
                valor_real=excluded.valor_real,
                fuente=excluded.fuente,
                fecha_actualizacion=excluded.fecha_actualizacion
        """, (clave, float(valor), fuente))
    con.commit()
    con.close()
    print("Coeficientes guardados en config_motor_valores (scope=global).")
    return 0


if __name__ == '__main__':
    main(dry_run='--dry-run' in sys.argv)

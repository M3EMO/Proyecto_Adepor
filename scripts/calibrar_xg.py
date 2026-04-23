"""
CALIBRAR_XG — re-calibra coeficientes xG por liga (P4 + gamma display).

Dos calibraciones combinadas:

1. **beta_sot por liga** (entra al Poisson via calcular_xg_hibrido):
   OLS univariada sobre residuos parciales:
     residuo_i = goles_i - beta_shots_off * shots_off_i - coef_corner * corners_i
     beta_sot  = sum(residuo * SOT) / sum(SOT^2)
   Afecta DIRECTAMENTE el Brier (mejora xG -> mejora probs).

2. **gamma_1x2 display por liga** (solo cosmetico, compresion xG mostrado):
     gamma = sum(goles_reales) / sum(xg_crudo)
   NO afecta Brier (xg_*_display solo se guarda en DB para display).

Criterio minimo: liga con N >= 20 liquidados y stats SOT/Shots/Corners completos.
Ligas sin N suficiente mantienen fallback global.

Uso:
  py scripts/calibrar_xg.py              # reporta y persiste
  py scripts/calibrar_xg.py --dry-run    # solo reporta
  py scripts/calibrar_xg.py --only=Brasil,Argentina  # filtrar ligas
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.comun.config_motor import get_param  # noqa: E402

N_MIN_CALIB = 20


def calibrar_liga(rows, beta_shots_off=0.010, coef_corner=0.03):
    """rows: lista de (sot, shots_off, corners, goles, xg_crudo).
    Devuelve (beta_sot, gamma, sse_before, sse_after, n_efectivo)."""
    sum_r_sot = 0.0
    sum_sot2  = 0.0
    sum_goles = 0
    sum_xg    = 0.0
    sse_before_sum = 0.0
    n = 0

    for sot, shots_off, corners, goles, xg_crudo in rows:
        if sot is None or shots_off is None or corners is None or goles is None:
            continue
        if sot < 0 or goles < 0:
            continue
        residuo = goles - beta_shots_off * shots_off - coef_corner * corners
        sum_r_sot += residuo * sot
        sum_sot2  += sot * sot
        sum_goles += goles
        if xg_crudo and xg_crudo > 0:
            sum_xg += xg_crudo
        sse_before_sum += (goles - (0.352 * sot + beta_shots_off * shots_off + coef_corner * corners)) ** 2
        n += 1

    if n < N_MIN_CALIB or sum_sot2 == 0:
        return None

    beta_sot = sum_r_sot / sum_sot2
    # Clamp a rango razonable (literatura Opta: [0.25, 0.45])
    beta_sot = max(0.25, min(0.45, beta_sot))

    gamma = sum_goles / sum_xg if sum_xg > 0 else 0.59

    # SSE con beta_sot nuevo
    sse_after = 0.0
    for sot, shots_off, corners, goles, xg_crudo in rows:
        if sot is None or shots_off is None or corners is None or goles is None:
            continue
        pred = beta_sot * sot + beta_shots_off * shots_off + coef_corner * corners
        sse_after += (goles - pred) ** 2

    return (beta_sot, gamma, sse_before_sum, sse_after, n)


def main(dry_run=False, filtro_ligas=None):
    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()
    cur.execute("""
        SELECT pais,
               sot_l, shots_l, corners_l, goles_l, xg_local,
               sot_v, shots_v, corners_v, goles_v, xg_visita
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
          AND shots_l IS NOT NULL AND shots_v IS NOT NULL
          AND corners_l IS NOT NULL AND corners_v IS NOT NULL
    """)
    rows = cur.fetchall()

    # Agrupar por liga. Cada partido contribuye 2 obs (local + visitante).
    from collections import defaultdict
    por_liga = defaultdict(list)
    for r in rows:
        pais = r[0]
        # Local
        sot_l, shots_l, corners_l, goles_l, xg_l = r[1], r[2], r[3], r[4], r[5]
        if sot_l is not None:
            shots_off_l = max(0, (shots_l or 0) - sot_l)  # shots_off_or_blocked
            por_liga[pais].append((sot_l, shots_off_l, corners_l or 0, goles_l, xg_l))
        # Visitante
        sot_v, shots_v, corners_v, goles_v, xg_v = r[6], r[7], r[8], r[9], r[10]
        if sot_v is not None:
            shots_off_v = max(0, (shots_v or 0) - sot_v)
            por_liga[pais].append((sot_v, shots_off_v, corners_v or 0, goles_v, xg_v))

    print(f"\n=== Calibracion P4 + gamma por liga ===")
    print(f"{'Liga':<12s} {'N_obs':>6s} {'beta_sot':>10s} {'vs global':>10s} {'gamma':>8s} {'SSE_imp%':>10s}")
    print('-' * 65)

    resultados = []
    for pais in sorted(por_liga.keys()):
        if filtro_ligas and pais not in filtro_ligas:
            continue
        data = por_liga[pais]
        beta_actual = float(get_param('beta_sot', scope=pais, default=0.352) or 0.352)
        res = calibrar_liga(data)
        if res is None:
            print(f"{pais:<12s} {len(data):>6d} SKIP (N<{N_MIN_CALIB} o SOT=0)")
            continue
        beta_new, gamma, sse_b, sse_a, n = res
        delta_beta = beta_new - beta_actual
        sse_improvement = 100 * (sse_b - sse_a) / sse_b if sse_b > 0 else 0
        print(f"{pais:<12s} {n:>6d} {beta_new:>10.4f} {delta_beta:>+10.4f} {gamma:>8.3f} {sse_improvement:>9.1f}%")
        resultados.append((pais, beta_new, gamma, n))

    print()

    if dry_run:
        print("[dry-run] No se guardaron valores en DB.")
        con.close()
        return 0

    if not resultados:
        print("[WARN] Ninguna liga paso los criterios minimos.")
        con.close()
        return 0

    fuente = f'calibrar_xg_2026-04-22'
    for pais, beta_sot, gamma, n in resultados:
        for clave, valor in [('beta_sot', beta_sot), ('gamma_1x2', gamma)]:
            cur.execute("""
                INSERT INTO config_motor_valores
                    (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
                VALUES (?, ?, ?, NULL, 'float', ?, 0, datetime('now'))
                ON CONFLICT(clave, scope) DO UPDATE SET
                    valor_real=excluded.valor_real,
                    fuente=excluded.fuente,
                    fecha_actualizacion=excluded.fecha_actualizacion
            """, (clave, pais, float(valor), f'{fuente}_N={n}'))
    con.commit()
    con.close()
    print(f"Guardados beta_sot + gamma_1x2 para {len(resultados)} ligas en config_motor_valores.")
    return 0


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    filtro = None
    for arg in sys.argv:
        if arg.startswith('--only='):
            filtro = set(arg.split('=')[1].split(','))
    main(dry_run=dry, filtro_ligas=filtro)

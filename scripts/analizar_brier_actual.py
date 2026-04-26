"""Calcula Brier rolling actual del sistema sobre Liquidados.

Diferencia clave con walk-forward:
  - Walk-forward: test simulado, train 2022-23, predict 2024 sobre data externa.
  - Sistema real: probs almacenadas en partidos_backtest cuando se calculo.
                  Liquidados NO se recalculan al cambiar el filtro V4.5.

V4.5 NO afecta el Brier de Liquidados (la prob ya estaba guardada).
V4.5 SOLO afecta DECISIONES futuras (apostar/pasar).
"""
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
con = sqlite3.connect(DB)
cur = con.cursor()

print("=== BRIER 1X2 sobre Liquidados (REAL del sistema) ===\n")

# Brier por liga
sql = """
SELECT pais, COUNT(*) AS n
FROM partidos_backtest
WHERE estado = 'Liquidado' AND prob_1 IS NOT NULL
  AND goles_l IS NOT NULL AND goles_v IS NOT NULL
GROUP BY pais
ORDER BY pais
"""
print(f"{'Liga':<13} {'N':>5} {'Brier':>8} {'Brier_acertado_pred':>18}")

total_brier = 0
total_n = 0
for liga, _ in cur.execute(sql):
    rows = cur.execute(
        """
        SELECT prob_1, prob_x, prob_2, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado' AND pais = ? AND prob_1 IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        """,
        (liga,)
    ).fetchall()

    n = len(rows)
    if n == 0:
        continue

    brier_sum = 0
    brier_arg_sum = 0
    n_correct = 0
    for r in rows:
        p1, px, p2, gl, gv = r
        # Outcome real
        if gl > gv:
            outcome = 0
        elif gl == gv:
            outcome = 1
        else:
            outcome = 2
        # Brier completo (tres clases)
        b_full = ((p1 - (1 if outcome == 0 else 0))**2
                  + (px - (1 if outcome == 1 else 0))**2
                  + (p2 - (1 if outcome == 2 else 0))**2)
        brier_sum += b_full

        # Brier solo del pred top
        argmax_idx = max([(0, p1), (1, px), (2, p2)], key=lambda x: x[1])[0]
        if argmax_idx == outcome:
            n_correct += 1

    brier_mean = brier_sum / n
    hit_rate = n_correct / n
    print(f"{liga:<13} {n:>5} {brier_mean:>8.4f} {hit_rate:>18.4f}")
    total_brier += brier_sum
    total_n += n

print()
if total_n > 0:
    print(f"TOTAL pool: N={total_n}  Brier={total_brier/total_n:.4f}")

# Hit rate del sistema real (con TODOS los filtros aplicados)
print()
print("=== Hit rate sistema REAL (solo picks [APOSTAR] que se concretaron) ===")
cur.execute("""
    SELECT
      COUNT(*) AS total_picks,
      SUM(CASE WHEN apuesta_1x2 = 'GANO' THEN 1 ELSE 0 END) AS ganados,
      SUM(CASE WHEN apuesta_1x2 = 'PERDIO' THEN 1 ELSE 0 END) AS perdidos,
      SUM(CASE WHEN apuesta_1x2 = 'VOID' THEN 1 ELSE 0 END) AS voids
    FROM partidos_backtest
    WHERE estado = 'Liquidado'
      AND apuesta_1x2 LIKE '[APOSTAR]%'
      AND apuesta_1x2 IS NOT NULL
""")
r = cur.fetchone()
total = r[0] or 0
ganados = r[1] or 0
perdidos = r[2] or 0
voids = r[3] or 0
n_decididos = ganados + perdidos
print(f"  Total picks reales: {total}")
print(f"  Ganados: {ganados}, Perdidos: {perdidos}, Voids: {voids}")
if n_decididos > 0:
    print(f"  Hit rate (sin voids): {ganados / n_decididos:.4f}  ({100*ganados/n_decididos:.2f}%)")

# Hit rate ROLLING ULTIMOS 50
print()
print("=== Hit rate ULTIMOS 50 picks reales (rolling) ===")
cur.execute("""
    SELECT id_partido, fecha, apuesta_1x2, apuesta_1x2
    FROM partidos_backtest
    WHERE estado = 'Liquidado'
      AND apuesta_1x2 LIKE '[APOSTAR]%'
      AND apuesta_1x2 IN ('GANO','PERDIO')
    ORDER BY fecha DESC
    LIMIT 50
""")
rows = cur.fetchall()
n50 = len(rows)
g50 = sum(1 for r in rows if r[3] == 'GANO')
print(f"  N: {n50}  GANO: {g50}  hit_rate: {g50/n50:.4f}" if n50 > 0 else "  Sin data")

con.close()

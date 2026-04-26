"""Check estado post-pipeline tras aplicar V4.5."""
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

print("=== Estados partidos_backtest ===")
for r in cur.execute("SELECT estado, COUNT(*) FROM partidos_backtest GROUP BY estado ORDER BY 2 DESC"):
    print(f"  {r[0]:<15} {r[1]}")
print()

# Picks 1X2 actuales con filter status
print("=== Picks 1X2 actuales (Pendiente + Calculado) ===")
sql = """
SELECT pais, COUNT(*) AS total,
       SUM(CASE WHEN apuesta_1x2 LIKE '[APOSTAR]%' THEN 1 ELSE 0 END) AS apostar,
       SUM(CASE WHEN apuesta_1x2 LIKE '[PASAR] Margen%' THEN 1 ELSE 0 END) AS filtrado_margen,
       SUM(CASE WHEN apuesta_1x2 LIKE '[PASAR]%' AND apuesta_1x2 NOT LIKE '[PASAR] Margen%' THEN 1 ELSE 0 END) AS pasar_otros
FROM partidos_backtest
WHERE estado IN ('Pendiente','Calculado')
GROUP BY pais
ORDER BY pais
"""
print(f"{'Liga':<13} {'total':>6} {'APOSTAR':>8} {'MARGEN':>8} {'PASAR_otros':>12}")
for r in cur.execute(sql):
    print(f"{r[0]:<13} {r[1]:>6} {r[2]:>8} {r[3]:>8} {r[4]:>12}")
print()

# Shadow log
n_shadow = cur.execute("SELECT COUNT(*) FROM picks_shadow_margen_log").fetchone()[0]
print(f"=== Shadow log: {n_shadow} entries ===")
if n_shadow > 0:
    print(f"{'fecha_log':<20} {'liga':<13} {'margen':>7} {'thr_actual':>10} {'thr_optimo':>10} {'p_act':>5} {'p_B':>3} {'p_C':>3}")
    for r in cur.execute("""
        SELECT fecha_log, liga, margen_real, threshold_actual, threshold_optimo_b,
               pasaria_actual, pasaria_opcion_b, pasaria_opcion_c
        FROM picks_shadow_margen_log
        ORDER BY fecha_log DESC LIMIT 20
    """):
        print(f"{r[0]:<20} {r[1]:<13} {r[2]:>7.4f} {r[3]:>10.3f} {r[4]:>10.3f} {r[5]:>5} {r[6]:>3} {r[7]:>3}")

# Picks que ahora aparecen como [PASAR] Margen
print()
print("=== Sample partidos con [PASAR] Margen Predictivo (post-V4.5) ===")
for r in cur.execute("""
    SELECT pais, local, visita, apuesta_1x2, prob_1, prob_x, prob_2
    FROM partidos_backtest
    WHERE estado = 'Calculado' AND apuesta_1x2 LIKE '[PASAR] Margen%'
    ORDER BY pais
    LIMIT 15
"""):
    sorted_probs = sorted([r[4] or 0, r[5] or 0, r[6] or 0], reverse=True)
    margen = sorted_probs[0] - sorted_probs[1]
    print(f"  {r[0]:<11} {r[1][:20]:<20} vs {r[2][:20]:<20}  margen={margen:.4f}  {r[3][:50]}")

con.close()

"""Brier y yield reales del sistema sobre Liquidados."""
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

# Brier sobre Liquidados con prob
print("=== Liquidados con prob_1 NOT NULL ===")
for r in cur.execute("""
    SELECT pais, COUNT(*) FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 IS NOT NULL
    GROUP BY pais ORDER BY 2 DESC
"""):
    print(f"  {r[0]:<14} {r[1]}")
print()

# Total Liquidados (con o sin prob)
print("=== Total Liquidados (incluye sin prob) ===")
total_liq = 0
for r in cur.execute("""
    SELECT pais, COUNT(*) FROM partidos_backtest
    WHERE estado='Liquidado'
    GROUP BY pais ORDER BY 2 DESC
"""):
    print(f"  {r[0]:<14} {r[1]}")
    total_liq += r[1]
print(f"  TOTAL: {total_liq}")
print()

# Brier por liga (donde hay prob + goles)
print("=== Brier 1X2 por liga (Liquidados con prob + goles) ===")
print(f"{'Liga':<13} {'N':>4} {'Brier':>7} {'Hit':>7}")

brier_por_liga = {}
hits_por_liga = {}
for r in cur.execute("""
    SELECT pais, prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 IS NOT NULL
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
"""):
    pais, p1, px, p2, gl, gv = r
    if gl > gv:
        outcome = 0
    elif gl == gv:
        outcome = 1
    else:
        outcome = 2
    b = ((p1 - (1 if outcome == 0 else 0)) ** 2
         + (px - (1 if outcome == 1 else 0)) ** 2
         + (p2 - (1 if outcome == 2 else 0)) ** 2)
    brier_por_liga.setdefault(pais, []).append(b)
    argmax = max([(0, p1), (1, px), (2, p2)], key=lambda x: x[1])[0]
    hits_por_liga.setdefault(pais, []).append(argmax == outcome)

total_brier_sum = 0
total_hits_sum = 0
total_n_sum = 0
for pais in sorted(brier_por_liga):
    bs = brier_por_liga[pais]
    hs = hits_por_liga[pais]
    n = len(bs)
    print(f"{pais:<13} {n:>4} {sum(bs)/n:>7.4f} {sum(hs)/n:>7.4f}")
    total_brier_sum += sum(bs)
    total_hits_sum += sum(hs)
    total_n_sum += n

print()
if total_n_sum > 0:
    print(f"POOL: N={total_n_sum}  Brier={total_brier_sum/total_n_sum:.4f}  Hit_rate={total_hits_sum/total_n_sum:.4f}")

# Picks reales: GANO/PERDIO calculado on-the-fly
print()
print("=== Picks [APOSTAR] reales en Liquidados ===")
total_picks = 0
ganados = 0
for r in cur.execute("""
    SELECT apuesta_1x2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado='Liquidado'
      AND apuesta_1x2 LIKE '[APOSTAR]%'
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
"""):
    ap, gl, gv = r
    s = (ap or "").upper()
    if "[APOSTAR] 1" in s and "[APOSTAR] 1X" not in s:
        pred = 0
    elif "[APOSTAR] X" in s:
        pred = 1
    elif "[APOSTAR] 2" in s and "[APOSTAR] 2X" not in s:
        pred = 2
    else:
        continue
    if gl > gv:
        outcome = 0
    elif gl == gv:
        outcome = 1
    else:
        outcome = 2
    total_picks += 1
    if pred == outcome:
        ganados += 1

print(f"  Total picks reales [APOSTAR]: {total_picks}")
print(f"  Ganados: {ganados}")
if total_picks > 0:
    print(f"  Hit rate REAL del sistema: {ganados/total_picks:.4f}  ({100*ganados/total_picks:.1f}%)")

con.close()

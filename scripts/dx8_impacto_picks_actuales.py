"""Estima el impacto del filtro V4.5 sobre los picks actuales en DB.

Muestra:
  - picks_actuales con [APOSTAR] en estado Pendiente/Calculado
  - cuantos perderian con el filtro nuevo (margen < 0.05)
  - margen real de cada pick para ver si esta en zona de riesgo
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

# Picks actuales con margen real
print("=== Picks actuales [APOSTAR] 1X2 (Pendiente/Calculado) ===")
print(f"{'Liga':<13} {'Local':<22} {'Visita':<22} {'Apuesta':<22} {'p_top1':>7} {'p_top2':>7} {'margen':>7}")

picks = cur.execute("""
    SELECT pais, local, visita, apuesta_1x2, prob_1, prob_x, prob_2
    FROM partidos_backtest
    WHERE estado IN ('Pendiente','Calculado')
      AND apuesta_1x2 LIKE '[APOSTAR]%'
      AND prob_1 IS NOT NULL
    ORDER BY pais
""").fetchall()

n_total = len(picks)
n_filter = 0
for p in picks:
    pais, local, visita, ap, p1, px, p2 = p
    sorted_probs = sorted([p1, px, p2], reverse=True)
    margen = sorted_probs[0] - sorted_probs[1]
    flag = "<- SE FILTRA" if margen < 0.05 else ""
    if margen < 0.05:
        n_filter += 1
    print(f"{pais:<13} {local[:22]:<22} {visita[:22]:<22} {ap[:22]:<22} "
          f"{sorted_probs[0]:>7.4f} {sorted_probs[1]:>7.4f} {margen:>7.4f}  {flag}")

print()
print(f"=== RESUMEN ===")
print(f"Total picks actuales: {n_total}")
print(f"Se filtrarian con V4.5 (margen < 5%): {n_filter} ({100*n_filter/n_total:.1f}% si N>0)" if n_total else "")
print(f"Sobreviven: {n_total - n_filter}")

con.close()

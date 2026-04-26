"""Brier sobre Liquidados POR THRESHOLD de margen.

Pregunta: si V4.5 afectara Liquidados, mejoraria el Brier?

Distincion clave:
  - V4.5 NO cambia probabilidades (no recalibra)
  - V4.5 CAMBIA decisiones (apostar/pasar)
  - PERO: al filtrar por margen, seleccionamos los partidos donde el modelo
    es MAS CONFIADO. En esos partidos, el Brier deberia ser MEJOR.

Test: Brier_pool sobre subsets filtrados por margen.
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

print("=== Brier sobre Liquidados, filtrado por margen real ===\n")
print(f"{'threshold':>10} {'N_kept':>7} {'%kept':>6} {'Brier':>7} {'hit_rate':>9} {'Δ_brier_vs_base':>16}")

# Cargar todas las predicciones con prob + goles
rows = cur.execute("""
    SELECT prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado = 'Liquidado' AND prob_1 IS NOT NULL
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""").fetchall()

# Computar margen + Brier por partido
predicciones = []
for r in rows:
    p1, px, p2, gl, gv = r
    sorted_probs = sorted([p1, px, p2], reverse=True)
    margen = sorted_probs[0] - sorted_probs[1]
    if gl > gv:
        outcome = 0
    elif gl == gv:
        outcome = 1
    else:
        outcome = 2
    brier = ((p1 - (1 if outcome == 0 else 0)) ** 2
             + (px - (1 if outcome == 1 else 0)) ** 2
             + (p2 - (1 if outcome == 2 else 0)) ** 2)
    argmax = max([(0, p1), (1, px), (2, p2)], key=lambda x: x[1])[0]
    hit = 1 if argmax == outcome else 0
    predicciones.append({"margen": margen, "brier": brier, "hit": hit})

n_total = len(predicciones)
brier_base = sum(p["brier"] for p in predicciones) / n_total
hit_base = sum(p["hit"] for p in predicciones) / n_total

# Por threshold
for thr in [0.00, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]:
    kept = [p for p in predicciones if p["margen"] >= thr]
    n_kept = len(kept)
    if n_kept == 0:
        continue
    brier_kept = sum(p["brier"] for p in kept) / n_kept
    hit_kept = sum(p["hit"] for p in kept) / n_kept
    delta_brier = brier_kept - brier_base
    pct = 100 * n_kept / n_total
    print(f"{thr:>10.2f} {n_kept:>7} {pct:>5.1f}% {brier_kept:>7.4f} {hit_kept:>9.4f} {delta_brier:>+16.4f}")

print(f"\nN total Liquidados con prob: {n_total}")
print(f"Brier_base (sin filtro):     {brier_base:.4f}")
print(f"Hit_rate_base (sin filtro):  {hit_base:.4f}")

# Si aplicaramos filtro V4.5 (margen >= 0.05) sobre Liquidados retroactivamente:
n_v45 = sum(1 for p in predicciones if p["margen"] >= 0.05)
brier_v45 = sum(p["brier"] for p in predicciones if p["margen"] >= 0.05) / n_v45
hit_v45 = sum(p["hit"] for p in predicciones if p["margen"] >= 0.05) / n_v45
print(f"\n=== HIPOTETICO: si V4.5 hubiera filtrado los Liquidados ===")
print(f"  N kept (margen >=0.05): {n_v45} ({100*n_v45/n_total:.1f}%)")
print(f"  Brier sobre kept:       {brier_v45:.4f}")
print(f"  Hit rate sobre kept:    {hit_v45:.4f}")
print(f"  Δ Brier:                {brier_v45 - brier_base:+.4f}  ({'MEJOR' if brier_v45 < brier_base else 'PEOR'})")
print(f"  Δ Hit rate:             {hit_v45 - hit_base:+.4f}")

con.close()

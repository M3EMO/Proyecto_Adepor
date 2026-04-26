"""Diagnostico para beads del Sprint E (E1, E2, E3): solo lectura."""
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

# E1: Liquidados por liga
print("=" * 60)
print("E1 (adepor-334) — Liquidados por liga (trigger N>=100)")
print("=" * 60)
cur.execute("""
    SELECT pais, COUNT(*)
    FROM partidos_backtest
    WHERE estado='Liquidado'
    GROUP BY pais
    ORDER BY 2 DESC
""")
for pais, n in cur.fetchall():
    flag = "<- TRIGGER" if n >= 100 else ""
    print(f"  {pais:<12} N={n:>3}  {flag}")

# E2: Brier rolling Argentina
print()
print("=" * 60)
print("E2 (adepor-dex) — Brier rolling Argentina")
print("=" * 60)
cur.execute("""
    SELECT id_partido, fecha, prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado='Liquidado' AND pais='Argentina' AND prob_1 IS NOT NULL
    ORDER BY fecha DESC
    LIMIT 50
""")
rows = cur.fetchall()

brier_sum = 0
n = 0
for r in rows:
    p1, px, p2, gl, gv = r[2], r[3], r[4], r[5], r[6]
    if any(x is None for x in [p1, px, p2, gl, gv]):
        continue
    if gl > gv:
        o = 1
    elif gl == gv:
        o = 0
    else:
        o = 2
    b = (p1 - (1.0 if o == 1 else 0))**2 + (px - (1.0 if o == 0 else 0))**2 + (p2 - (1.0 if o == 2 else 0))**2
    brier_sum += b
    n += 1

mean_b = brier_sum / n if n > 0 else None
print(f"  Ultimas N partidos: {n}")
print(f"  Brier rolling actual: {mean_b:.4f}" if mean_b else "  no data")
print(f"  Baseline (mean alerta): 0.196")
print(f"  Threshold alerta: 0.220")
if mean_b is not None:
    if mean_b > 0.220:
        print(f"  ESTADO: ALERTA EXCEDIDA (>0.220)")
    elif mean_b > 0.205:
        print(f"  ESTADO: ELEVADO (entre 0.205 y 0.220, monitor)")
    else:
        print(f"  ESTADO: NORMAL (<0.205)")

# E3: Verificacion N>=150 LATAM (post m4g)
print()
print("=" * 60)
print("E3 (adepor-ehj) — N externo LATAM post m4g (vs threshold 150)")
print("=" * 60)
import json
JSON_M4G = Path(__file__).resolve().parent.parent / "analisis" / "mle_externo_rho_adepor-m4g.json"
JSON_1VT = Path(__file__).resolve().parent.parent / "analisis" / "mle_externo_rho_adepor-1vt.json"

if JSON_M4G.exists():
    data_m4g = json.loads(JSON_M4G.read_text(encoding="utf-8"))["resultados"]
else:
    data_m4g = {}

if JSON_1VT.exists():
    data_1vt = json.loads(JSON_1VT.read_text(encoding="utf-8"))["resultados"]
else:
    data_1vt = {}

LATAM = ["Argentina", "Bolivia", "Brasil", "Chile", "Colombia",
         "Ecuador", "Peru", "Uruguay", "Venezuela"]

for liga in LATAM:
    if liga in data_m4g:
        n = data_m4g[liga].get("n_externo", 0)
        src = "m4g"
    elif liga in data_1vt:
        n = data_1vt[liga].get("n_externo", 0)
        src = "1vt"
    else:
        n = 0
        src = "none"
    flag = "PASA threshold 150" if n >= 150 else "BAJO threshold 150"
    print(f"  {liga:<12} N_ext={n:>5}  fuente={src}  {flag}")

con.close()

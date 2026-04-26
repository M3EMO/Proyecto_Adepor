"""Verifica calidad de cache ESPN scraped."""
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CACHE = Path(__file__).resolve().parent.parent / "analisis" / "cache_espn"

for f in sorted(CACHE.glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    n = len(data)
    if n == 0:
        print(f"{f.name}: EMPTY")
        continue
    n_zero = sum(1 for p in data if p["hs"] == 0 and p["hst"] == 0 and p["hc"] == 0)
    avg_shots = sum(p["hs"] for p in data) / n
    avg_sot = sum(p["hst"] for p in data) / n
    avg_corners = sum(p["hc"] for p in data) / n
    avg_goles = sum(p["hg"] for p in data) / n
    print(f"{f.name}: N={n}  avg_goals={avg_goles:.2f}  shots={avg_shots:.2f}  SoT={avg_sot:.2f}  C={avg_corners:.2f}  zero_stats={n_zero}/{n}")

    # Sample
    print("  Sample:")
    for p in data[:2]:
        print(f"    {p['fecha'][:10]}  {p['ht']:<25} {p['hg']}-{p['ag']}  {p['at']:<25}  SoT {p['hst']}-{p['ast']}  shots {p['hs']}-{p['as']}  C {p['hc']}-{p['ac']}")

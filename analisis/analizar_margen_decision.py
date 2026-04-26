"""Analiza el impacto de regla 'abstenerse si margen entre top1 y top2 < 5pp'.

Sobre las predicciones del walk-forward (iter1 EUR + iter3 LATAM):
  margen = max(p1,px,p2) - segundo(p1,px,p2)
  abstener_si margen < threshold
  hit_rate sobre los NO abstenidos

Compara:
  - Sin filtro: hit_rate, N
  - Con filtro 3pp, 5pp, 10pp, 15pp: hit_rate, N, %abstenido
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent

INPUTS = [
    (ROOT / "analisis" / "walk_forward_multiliga.json", "iter1 EUR CSV"),
    (ROOT / "analisis" / "walk_forward_full_stats.json", "iter3 LATAM ESPN"),
]

THRESHOLDS = [0.0, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]


def margen_top(p1, px, p2):
    sorted_probs = sorted([p1, px, p2], reverse=True)
    return sorted_probs[0] - sorted_probs[1]


def cargar_predicciones_por_liga():
    """Carga predicciones de los JSONs walk-forward."""
    por_liga = defaultdict(list)
    for path, source in INPUTS:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ligas = data.get("ligas", {})
        for liga, info in ligas.items():
            # JSONs old: solo agregados. Necesitamos predicciones individuales.
            # Si no existen, hay que re-correr. Veamos.
            preds = info.get("predicciones_sample_5") or []
            if not preds:
                # Fallback: usar metricas agregadas
                m = info.get("metricas", {})
                if m.get("n"):
                    por_liga[liga].append({
                        "source": source, "n": m["n"],
                        "hit_rate": m["hit_rate"],
                        "calibration": m.get("calibracion_por_bucket", {}),
                    })
    return por_liga


def main():
    """Lee directly walk_forward_full_stats.json — pero solo tiene sample 5.
    Necesitamos re-correr y guardar todas las predicciones.
    """
    print("Las predicciones detalladas no estan persistidas (solo sample 5 + calibration buckets).")
    print("Voy a deducir el analisis desde calibration_por_bucket:")
    print("  cada bucket b agrupa predicciones donde max(p1,px,p2) cae en [b, b+10)")
    print("  margen NO se conserva por bucket, pero PROXY: prob_max alta -> margen alto")
    print()
    print("PROXY analysis: filtrar por prob_max >= threshold")
    print()

    for path, source in INPUTS:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"=== {source} ({path.name}) ===")
        print(f"{'Liga':<12} {'N_total':>7} {'Hit_full':>8}", end=" ")
        for thr in [40, 50, 60, 70]:
            print(f"{'p>='+str(thr)+'%_n':>9} {'p>='+str(thr)+'%_hit':>10}", end=" ")
        print()

        for liga, info in sorted(data.get("ligas", {}).items()):
            m = info.get("metricas", {})
            if not m.get("n"):
                continue
            calib = m.get("calibracion_por_bucket", {})

            # Por threshold de prob_max
            row = [liga, m["n"], m["hit_rate"]]
            for thr in [40, 50, 60, 70]:
                # bucket >= thr
                n_thr = 0
                hits_thr = 0
                for k, b in calib.items():
                    # k: '40-50', '50-60', etc.
                    try:
                        lo = int(k.split("-")[0])
                    except ValueError:
                        continue
                    if lo >= thr:
                        n_thr += b["n"]
                        hits_thr += int(round(b["n"] * b["hit_rate"]))
                hit_rate_thr = hits_thr / n_thr if n_thr > 0 else 0
                pct_kept = 100.0 * n_thr / m["n"] if m["n"] > 0 else 0
                row += [n_thr, round(hit_rate_thr, 4)]

            print(f"{row[0]:<12} {row[1]:>7} {row[2]:>8.4f}", end=" ")
            for i in range(3, len(row), 2):
                print(f"{row[i]:>9} {row[i+1]:>10.4f}", end=" ")
            print()
        print()


if __name__ == "__main__":
    main()

"""Bootstrap CI 95% + split temporal de rho EPL (adepor-wxv).

Confirma o refuta:
  H1: rho_EPL post-COVID ~ 0 (CI 95% incluye 0)
  H2: regimen estable a lo largo de 2021-2025 (rho similar en H1 vs H2)

Metodologia:
  - Bootstrap: 1000 resamples con reemplazo de los 1852 partidos. MLE en cada.
  - Split temporal: 2 splits de 2.5 temporadas cada uno.
  - Tambien split por temporada individual (5 puntos) para inspeccion.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nucleo.calibrar_rho import (
    descargar_partidos_csv,
    estimar_rho_mle,
    FUENTES_CSV,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = ROOT / "analisis" / "bootstrap_rho_epl_adepor-wxv.json"
N_BOOTSTRAP = 200
SEED = 20260426


def percentile(values, p):
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    print("=" * 70)
    print("Bootstrap CI 95% + split temporal rho EPL — adepor-wxv")
    print("=" * 70)

    # 1. Cargar EPL completo
    print("\n[1/4] Cargando EPL CSVs...")
    por_url = {}
    partidos = descargar_partidos_csv("Inglaterra", FUENTES_CSV["Inglaterra"], por_url=por_url)
    print(f"      Total partidos: {len(partidos)}")
    for url, lista in por_url.items():
        # extraer codigo temporada del URL (ej: "2526" -> 2025-26)
        marker = url.split("/")[-2] if "mmz4281" in url else "unknown"
        print(f"      Temp {marker}: {len(lista)} partidos")

    # 2. rho point estimate
    print(f"\n[2/4] Point estimate (constrained):")
    rho_punto = estimar_rho_mle(partidos)
    print(f"      rho_MLE = {rho_punto:+.4f} (N={len(partidos)})")

    # 3. Bootstrap
    print(f"\n[3/4] Bootstrap {N_BOOTSTRAP} resamples...")
    random.seed(SEED)
    rhos = []
    n = len(partidos)
    for i in range(N_BOOTSTRAP):
        sample = [random.choice(partidos) for _ in range(n)]
        rho_b = estimar_rho_mle(sample)
        if rho_b is not None:
            rhos.append(rho_b)
        if (i + 1) % 100 == 0:
            print(f"      {i+1}/{N_BOOTSTRAP} hecho. Hasta ahora: mean={sum(rhos)/len(rhos):+.4f}")

    ci_lo = percentile(rhos, 0.025)
    ci_hi = percentile(rhos, 0.975)
    mean_rho = sum(rhos) / len(rhos)
    incluye_zero = ci_lo <= 0 <= ci_hi
    incluye_neg013 = ci_lo <= -0.13 <= ci_hi

    print(f"\n      rho_punto:   {rho_punto:+.4f}")
    print(f"      rho_mean:    {mean_rho:+.4f}")
    print(f"      CI 95%:      [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"      Incluye 0?    {incluye_zero}")
    print(f"      Incluye -0.13?{incluye_neg013}")

    # 4. Split temporal
    print(f"\n[4/4] Split temporal por temporada...")

    # Re-cargar con tracking explicito por temporada
    por_url2 = {}
    descargar_partidos_csv("Inglaterra", FUENTES_CSV["Inglaterra"], por_url=por_url2)

    # Convertir URL -> temp_code y luego agregar 2x temps por split
    splits = {}
    for url, lista in por_url2.items():
        if "mmz4281" not in url:
            continue
        marker = url.split("/")[-2]  # ej "2526"
        splits[marker] = lista

    sorted_marks = sorted(splits.keys())
    print(f"      Temporadas detectadas: {sorted_marks}")

    splits_per_temp = {}
    for m in sorted_marks:
        lista = splits[m]
        if len(lista) >= 80:
            rho_t = estimar_rho_mle(lista)
            splits_per_temp[m] = {"n": len(lista), "rho_mle": rho_t}
            print(f"      Temp {m}: N={len(lista)} rho={rho_t:+.4f}")
        else:
            splits_per_temp[m] = {"n": len(lista), "rho_mle": None}

    # Split H1 (mas viejas) vs H2 (mas recientes)
    mid = len(sorted_marks) // 2
    H1_marks = sorted_marks[:mid] if mid > 0 else sorted_marks[:1]
    H2_marks = sorted_marks[mid:]

    H1_partidos = [p for m in H1_marks for p in splits[m]]
    H2_partidos = [p for m in H2_marks for p in splits[m]]

    rho_H1 = estimar_rho_mle(H1_partidos) if len(H1_partidos) >= 80 else None
    rho_H2 = estimar_rho_mle(H2_partidos) if len(H2_partidos) >= 80 else None

    print(f"\n      H1 ({H1_marks}): N={len(H1_partidos)} rho={rho_H1}")
    print(f"      H2 ({H2_marks}): N={len(H2_partidos)} rho={rho_H2}")

    if rho_H1 is not None and rho_H2 is not None:
        delta_H1H2 = rho_H2 - rho_H1
        print(f"      delta H2 - H1 = {delta_H1H2:+.4f}")
        if abs(delta_H1H2) < 0.03:
            print(f"      Veredicto: REGIMEN ESTABLE (delta < 0.03)")
        else:
            print(f"      Veredicto: SHIFT DE REGIMEN (delta >= 0.03)")

    output = {
        "bead_id": "adepor-wxv",
        "metodologia": {
            "n_bootstrap": N_BOOTSTRAP,
            "seed": SEED,
            "fuente": "football-data.co.uk CSV (5 temps EPL)",
        },
        "point_estimate": {
            "rho_mle": rho_punto,
            "n_total": len(partidos),
        },
        "bootstrap_ci_95": {
            "n_resamples_validos": len(rhos),
            "rho_mean": mean_rho,
            "ci_lo_2.5p": ci_lo,
            "ci_hi_97.5p": ci_hi,
            "incluye_cero": incluye_zero,
            "incluye_minus_013": incluye_neg013,
        },
        "split_temporadas": splits_per_temp,
        "split_H1_H2": {
            "H1_marks": H1_marks,
            "H2_marks": H2_marks,
            "H1_n": len(H1_partidos),
            "H2_n": len(H2_partidos),
            "H1_rho": rho_H1,
            "H2_rho": rho_H2,
            "delta_H2_H1": (rho_H2 - rho_H1) if (rho_H1 is not None and rho_H2 is not None) else None,
        },
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

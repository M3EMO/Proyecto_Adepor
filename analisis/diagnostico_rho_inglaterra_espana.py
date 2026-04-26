"""Diagnostico rho_MLE=0 para Inglaterra y Espana (adepor-0yy + extension m4g).

PIPOTESIS A TESTEAR:
H1 — Constraint estructural: el grid search en calibrar_rho.py esta acotado a
     [-0.30, 0.00]. Si el verdadero MLE optimum cae en rho >= 0, el algoritmo
     retorna 0.0 mecanicamente. Verificar extendiendo el grid a [-0.30, +0.10].

H2 — Goal inflation post-COVID: si la correlacion de bajo marcador genuinamente
     desaparecio, las frecuencias empiricas de 0-0/1-0/0-1/1-1 deberian alinearse
     con un modelo Poisson SIN tau (rho=0).

H3 — Bug en parser CSV: si rho_MLE = 0.0000 EXACTO sin convergencia decimal,
     puede ser bug. Si es =0.0010 o similar, no es bug.

OUTPUTS:
  - LL curve vs rho [-0.30, +0.10] step 0.005 -> CSV
  - rho_MLE constrained vs unconstrained vs DB
  - Empirical 0-0/1-0/0-1/1-1 vs Poisson(lambda_avg, mu_avg) con rho=0 y rho=-0.13

"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nucleo.calibrar_rho import (
    _estimar_lambdas_por_equipo,
    _log_verosimilitud_total,
    descargar_partidos_csv,
    descargar_partidos_api_football,
    FUENTES_CSV,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = ROOT / "analisis" / "diagnostico_rho_ing_esp.json"
LIGAS = ["Inglaterra", "Espana"]
TEMPORADAS_API = [2024, 2023, 2022, 2021]


def construir_partidos_lm(partidos):
    """Identico a estimar_rho_mle pero retorna lista (hg, ag, lam, mu)."""
    sh, sa, ch, ca, lav_h, lav_a = _estimar_lambdas_por_equipo(partidos)
    res = []
    for ht, at, hg, ag in partidos:
        lam = (sh.get(ht, lav_h) + ca.get(at, lav_h)) / 2
        mu = (sa.get(at, lav_a) + ch.get(ht, lav_a)) / 2
        lam = max(lam, 0.1)
        mu = max(mu, 0.1)
        res.append((hg, ag, lam, mu))
    return res, lav_h, lav_a


def grid_ll_extendido(partidos_lm, lo=-0.30, hi=0.10, paso=0.005):
    pts = []
    n = int((hi - lo) / paso) + 1
    for i in range(n):
        rho = round(lo + i * paso, 4)
        ll = _log_verosimilitud_total(partidos_lm, rho)
        pts.append((rho, ll))
    return pts


def freq_marcadores(partidos):
    """Cuenta frecuencias relativas de marcadores 0-0, 1-0, 0-1, 1-1."""
    n = len(partidos)
    counts = {"0-0": 0, "1-0": 0, "0-1": 0, "1-1": 0}
    for _, _, hg, ag in partidos:
        if hg == 0 and ag == 0:
            counts["0-0"] += 1
        elif hg == 1 and ag == 0:
            counts["1-0"] += 1
        elif hg == 0 and ag == 1:
            counts["0-1"] += 1
        elif hg == 1 and ag == 1:
            counts["1-1"] += 1
    return {k: v / n for k, v in counts.items()}


def freq_esperadas_poisson_dc(lav_h, lav_a, rho):
    """Probabilidades teoricas con tau Dixon-Coles para los 4 marcadores bajos."""

    def poisson(k, lam):
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    def tau(i, j, lam, mu, rho):
        if i == 0 and j == 0:
            return max(0.0, 1.0 - lam * mu * rho)
        if i == 0 and j == 1:
            return max(0.0, 1.0 + lam * rho)
        if i == 1 and j == 0:
            return max(0.0, 1.0 + mu * rho)
        if i == 1 and j == 1:
            return max(0.0, 1.0 - rho)
        return 1.0

    out = {}
    for i, j in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        p = poisson(i, lav_h) * poisson(j, lav_a) * tau(i, j, lav_h, lav_a, rho)
        out[f"{i}-{j}"] = p
    return out


def main():
    resultados = {}

    for liga in LIGAS:
        print(f"\n=== {liga} ===")
        # Fuente preferida: CSV; fallback API-Football
        if liga in FUENTES_CSV:
            partidos = descargar_partidos_csv(liga, FUENTES_CSV[liga])
            fuente = "CSV"
        else:
            partidos = descargar_partidos_api_football(liga, TEMPORADAS_API)
            fuente = "API-Football"

        n = len(partidos)
        print(f"  Fuente: {fuente}, N = {n}")

        if n < 80:
            print(f"  [SKIP] N insuficiente.")
            resultados[liga] = {"error": "N_INSUFICIENTE", "n": n}
            continue

        partidos_lm, lav_h, lav_a = construir_partidos_lm(partidos)

        # 1. Grid extendido
        curva = grid_ll_extendido(partidos_lm)
        rho_argmax_unconstrained = max(curva, key=lambda x: x[1])
        rho_argmax_constrained = max(
            [p for p in curva if p[0] <= 0.0], key=lambda x: x[1]
        )

        print(f"  rho_MLE constrained ([-0.30, 0]):       {rho_argmax_constrained[0]:+.4f}  (LL={rho_argmax_constrained[1]:.2f})")
        print(f"  rho_MLE unconstrained ([-0.30, +0.10]): {rho_argmax_unconstrained[0]:+.4f}  (LL={rho_argmax_unconstrained[1]:.2f})")

        # 2. Curvatura cerca del optimo
        delta_ll_at_zero = max(c[1] for c in curva if abs(c[0]) < 0.001) - rho_argmax_unconstrained[1]
        delta_ll_at_minus_013 = max(c[1] for c in curva if abs(c[0] - (-0.13)) < 0.0025) - rho_argmax_unconstrained[1]
        print(f"  LL drop vs unconstrained max:")
        print(f"     en rho=0:     {delta_ll_at_zero:+.3f}")
        print(f"     en rho=-0.13: {delta_ll_at_minus_013:+.3f}")

        # 3. Frecuencias empiricas vs teoricas con rho=0 y rho=-0.13
        emp = freq_marcadores(partidos)
        teor_0 = freq_esperadas_poisson_dc(lav_h, lav_a, 0.0)
        teor_neg = freq_esperadas_poisson_dc(lav_h, lav_a, -0.13)
        print(f"  lambda_avg = {lav_h:.3f}  mu_avg = {lav_a:.3f}")
        print(f"  Marcador  | Empirico | Teor rho=0 | Teor rho=-0.13")
        for k in ["0-0", "1-0", "0-1", "1-1"]:
            print(f"  {k:<8}  | {emp[k]:>7.4f} |  {teor_0[k]:>7.4f}  |   {teor_neg[k]:>7.4f}")

        resultados[liga] = {
            "fuente": fuente,
            "n_partidos": n,
            "lambda_avg": lav_h,
            "mu_avg": lav_a,
            "rho_constrained": rho_argmax_constrained[0],
            "ll_constrained": rho_argmax_constrained[1],
            "rho_unconstrained": rho_argmax_unconstrained[0],
            "ll_unconstrained": rho_argmax_unconstrained[1],
            "delta_ll_at_zero": delta_ll_at_zero,
            "delta_ll_at_minus_013": delta_ll_at_minus_013,
            "freq_empirica": emp,
            "freq_teorica_rho_0": teor_0,
            "freq_teorica_rho_negativa": teor_neg,
            "ll_curve": curva,
        }

    OUT.write_text(json.dumps(resultados, indent=2, ensure_ascii=False, default=lambda x: round(x, 4) if isinstance(x, float) else x), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

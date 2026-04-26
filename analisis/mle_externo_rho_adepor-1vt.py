"""
MLE externo de rho por liga (out-of-sample).

Reusa funciones de src/nucleo/calibrar_rho.py SIN escribir en fondo_quant.db.
Salida: analisis/mle_externo_rho_adepor-1vt.json (resultados crudos del MLE).

Cambios vs calibrar_rho.py vigente:
  - TEMPORADAS_API: 2024, 2023, 2022, 2021 (4 anos en lugar de 3) - mas N para LATAM.
  - MIN_PARTIDOS: 80 para Europa, 150 para LATAM (recomendacion investigador).
  - Aplica shrinkage post-MLE hacia -0.12 con peso N/(N+200), floor -0.03.
  - Outlier gate: si rho_MLE fuera de [-0.20, +0.05] -> -0.12 (con floor).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nucleo.calibrar_rho import (
    descargar_partidos_csv, descargar_partidos_api_football,
    estimar_rho_mle, FUENTES_CSV,
)
from src.comun.config_sistema import LIGAS_ESPN

JSON_OUT = ROOT / "analisis" / "mle_externo_rho_adepor-1vt.json"
BEAD_ID = "adepor-1vt"

TEMPORADAS_API_EXT = [2024, 2023, 2022, 2021]
MIN_PARTIDOS_EUROPA = 80
MIN_PARTIDOS_LATAM = 150

LATAM = {"Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
         "Ecuador", "Peru", "Uruguay", "Venezuela"}

RHO_FLOOR = -0.03
RHO_RAZONABLE_MIN = -0.20
RHO_RAZONABLE_MAX = 0.05
RHO_SHRINKAGE_TARGET = -0.12
SHRINKAGE_PSEUDO_N = 200


def aplicar_shrinkage(rho_mle, n):
    w = n / (n + SHRINKAGE_PSEUDO_N)
    return w * rho_mle + (1 - w) * RHO_SHRINKAGE_TARGET


def aplicar_floor(rho):
    return min(rho, RHO_FLOOR)


def main():
    print("=" * 70)
    print(f"MLE EXTERNO RHO - bead {BEAD_ID}")
    print("=" * 70)
    print(f"TEMPORADAS_API_EXT = {TEMPORADAS_API_EXT}")
    print(f"MIN Europa={MIN_PARTIDOS_EUROPA}, MIN LATAM={MIN_PARTIDOS_LATAM}")
    print()

    ligas_activas = sorted(set(LIGAS_ESPN.values()))
    resultados = {}

    for liga in ligas_activas:
        print(f"--- {liga} ({'LATAM' if liga in LATAM else 'EUR'}) ---")
        # Fuente preferida: CSV si esta disponible
        if liga in FUENTES_CSV:
            partidos = descargar_partidos_csv(liga, FUENTES_CSV[liga])
            fuente = "CSV"
        else:
            partidos = descargar_partidos_api_football(liga, TEMPORADAS_API_EXT)
            fuente = "API-Football"

        n = len(partidos)
        min_required = MIN_PARTIDOS_LATAM if liga in LATAM else MIN_PARTIDOS_EUROPA
        if n < min_required:
            print(f"   [SKIP] N={n} < {min_required}. No MLE.")
            resultados[liga] = {
                'fuente': fuente,
                'n_externo': n,
                'min_requerido': min_required,
                'estado': 'N_INSUFICIENTE',
                'rho_mle': None,
                'rho_post_shrinkage': None,
                'rho_propuesto_externo': None,
            }
            continue

        rho_mle = estimar_rho_mle(partidos)
        if rho_mle is None:
            # Esto solo ocurre si N < 80 (calibrar_rho.MIN_PARTIDOS), ya filtramos arriba
            resultados[liga] = {
                'fuente': fuente,
                'n_externo': n,
                'estado': 'MLE_NO_CONVERGIO',
                'rho_mle': None,
                'rho_post_shrinkage': None,
                'rho_propuesto_externo': None,
            }
            continue

        # Outlier detection
        if not (RHO_RAZONABLE_MIN <= rho_mle <= RHO_RAZONABLE_MAX):
            outlier = True
            rho_propuesto = aplicar_floor(RHO_SHRINKAGE_TARGET)
            print(f"   [OUTLIER] rho_MLE={rho_mle} fuera de [{RHO_RAZONABLE_MIN},{RHO_RAZONABLE_MAX}]. Cae a -0.12.")
        else:
            outlier = False
            rho_post_shrink = aplicar_shrinkage(rho_mle, n)
            rho_propuesto = aplicar_floor(rho_post_shrink)
            print(f"   rho_MLE={rho_mle:+.4f}  rho_post_shrink={rho_post_shrink:+.4f}  rho_final={rho_propuesto:+.4f}  (w={n/(n+200):.3f})")

        resultados[liga] = {
            'fuente': fuente,
            'n_externo': n,
            'estado': 'MLE_OK',
            'rho_mle': rho_mle,
            'rho_post_shrinkage': round(aplicar_shrinkage(rho_mle, n), 4) if not outlier else None,
            'rho_propuesto_externo': round(rho_propuesto, 4),
            'outlier': outlier,
            'shrinkage_w': round(n/(n+200), 4),
        }

    output = {
        'bead_id': BEAD_ID,
        'metodologia': {
            'temporadas_api_extended': TEMPORADAS_API_EXT,
            'min_partidos_europa': MIN_PARTIDOS_EUROPA,
            'min_partidos_latam': MIN_PARTIDOS_LATAM,
            'shrinkage_target': RHO_SHRINKAGE_TARGET,
            'shrinkage_pseudo_n': SHRINKAGE_PSEUDO_N,
            'outlier_range': [RHO_RAZONABLE_MIN, RHO_RAZONABLE_MAX],
            'floor': RHO_FLOOR,
        },
        'resultados': resultados,
    }
    JSON_OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print()
    print(f"[OK] JSON: {JSON_OUT}")


if __name__ == "__main__":
    main()

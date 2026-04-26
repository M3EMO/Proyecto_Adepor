"""MLE externo rho — retry con backoff para 9 ligas que dieron 429 en adepor-1vt.

Ligas target: Chile, Colombia, Ecuador, Espana, Francia, Italia, Peru, Uruguay, Venezuela.

Diferencias vs adepor-1vt:
  - Backoff exponencial 5/15/30/60s ante 429.
  - Sleep entre temporadas: 6s (10 req/min de margen, API-Football free tier 30 req/min).
  - Sleep entre ligas: 12s.
  - max retries por temporada: 4.
  - Respeta Retry-After header si viene.

Salida:
  - analisis/mle_externo_rho_adepor-m4g.json (resultados crudos del MLE)
  - Sin tocar DB.

Para aplicar resultados: generar SQL de UPDATE manual post-veredicto Critico (igual que adepor-1vt -> adepor-5ul).
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nucleo.calibrar_rho import (
    MAPA_LIGAS_API_FOOTBALL,
    estimar_rho_mle,
    API_KEY_FOOTBALL,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

JSON_OUT = ROOT / "analisis" / "mle_externo_rho_adepor-m4g.json"
BEAD_ID = "adepor-m4g"

LIGAS_429 = [
    "Chile", "Colombia", "Ecuador", "Espana", "Francia",
    "Italia", "Peru", "Uruguay", "Venezuela",
]
TEMPORADAS_API_EXT = [2024, 2023, 2022, 2021]
LATAM = {"Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
         "Ecuador", "Peru", "Uruguay", "Venezuela"}
MIN_PARTIDOS_EUROPA = 80
MIN_PARTIDOS_LATAM = 150

# --- Constantes de calibracion (consistentes con adepor-1vt) ---
RHO_FLOOR = -0.03
RHO_RAZONABLE_MIN = -0.20
RHO_RAZONABLE_MAX = 0.05
RHO_SHRINKAGE_TARGET = -0.12
SHRINKAGE_PSEUDO_N = 200

# --- Backoff config ---
SLEEP_ENTRE_TEMPORADAS = 6     # segundos
SLEEP_ENTRE_LIGAS = 12         # segundos
MAX_REINTENTOS = 4
BACKOFF_BASE = [5, 15, 30, 60]  # segundos por intento (1-indexed)
TIMEOUT_HTTP = 30


def aplicar_shrinkage(rho_mle, n):
    w = n / (n + SHRINKAGE_PSEUDO_N)
    return w * rho_mle + (1 - w) * RHO_SHRINKAGE_TARGET


def aplicar_floor(rho):
    return min(rho, RHO_FLOOR)


def descargar_temporada_con_backoff(liga_nombre, liga_id, temporada, key):
    """Descarga 1 temporada con retry + backoff. Devuelve lista de tuplas o []."""
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"league": liga_id, "season": temporada, "status": "FT"}
    headers = {"x-apisports-key": key}

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_HTTP)
        except requests.exceptions.RequestException as e:
            if intento < MAX_REINTENTOS:
                espera = BACKOFF_BASE[intento - 1]
                print(f"     [RETRY {intento}/{MAX_REINTENTOS}] red error: {e}. Espera {espera}s.")
                time.sleep(espera)
                continue
            print(f"     [ERROR] red {liga_nombre} {temporada}: {e}")
            return []

        if resp.status_code == 429:
            # Try Retry-After header first
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                espera = int(retry_after)
            else:
                espera = BACKOFF_BASE[intento - 1] if intento <= len(BACKOFF_BASE) else 60
            print(f"     [429] {liga_nombre} {temporada} intento {intento}/{MAX_REINTENTOS}. Retry-After={retry_after}, espera {espera}s.")
            time.sleep(espera)
            continue

        if resp.status_code != 200:
            print(f"     [SKIP] HTTP {resp.status_code} {liga_nombre} {temporada}")
            return []

        # 200 OK
        data = resp.json()
        fixtures = data.get("response", [])
        partidos = []
        for f in fixtures:
            try:
                ht = f["teams"]["home"]["name"]
                at = f["teams"]["away"]["name"]
                hg = f["goals"]["home"]
                ag = f["goals"]["away"]
                if hg is not None and ag is not None:
                    partidos.append((ht, at, int(hg), int(ag)))
            except (KeyError, TypeError):
                continue
        print(f"     [OK] {len(partidos)} partidos <- {liga_nombre} {temporada}")
        return partidos

    print(f"     [GIVEUP] {liga_nombre} {temporada} agoto {MAX_REINTENTOS} intentos por 429.")
    return []


def descargar_liga_con_backoff(liga_nombre, temporadas, key):
    liga_id = MAPA_LIGAS_API_FOOTBALL.get(liga_nombre)
    if not liga_id:
        print(f"   [SKIP] {liga_nombre}: no esta en MAPA_LIGAS_API_FOOTBALL")
        return []

    todos = []
    for i, temp in enumerate(temporadas):
        partidos = descargar_temporada_con_backoff(liga_nombre, liga_id, temp, key)
        todos.extend(partidos)
        if i < len(temporadas) - 1:
            time.sleep(SLEEP_ENTRE_TEMPORADAS)
    return todos


def main():
    if not API_KEY_FOOTBALL:
        print("ERROR: api_key_football no configurada en config.json", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print(f"MLE EXTERNO RHO — bead {BEAD_ID} (retry 9 ligas con 429)")
    print("=" * 70)
    print(f"TEMPORADAS = {TEMPORADAS_API_EXT}")
    print(f"Backoff: max {MAX_REINTENTOS} retries / temporada, sleep {SLEEP_ENTRE_LIGAS}s entre ligas")
    print()

    resultados = {}

    for i, liga in enumerate(LIGAS_429):
        print(f"--- {liga} ({'LATAM' if liga in LATAM else 'EUR'}) ---")
        partidos = descargar_liga_con_backoff(liga, TEMPORADAS_API_EXT, API_KEY_FOOTBALL)
        n = len(partidos)
        min_required = MIN_PARTIDOS_LATAM if liga in LATAM else MIN_PARTIDOS_EUROPA

        if n < min_required:
            print(f"   [SKIP] N={n} < {min_required}. No MLE.")
            resultados[liga] = {
                "n_externo": n,
                "min_requerido": min_required,
                "estado": "N_INSUFICIENTE",
                "rho_mle": None,
                "rho_propuesto_externo": None,
            }
        else:
            rho_mle = estimar_rho_mle(partidos)
            if rho_mle is None:
                resultados[liga] = {
                    "n_externo": n,
                    "estado": "MLE_NO_CONVERGIO",
                    "rho_mle": None,
                    "rho_propuesto_externo": None,
                }
            else:
                if not (RHO_RAZONABLE_MIN <= rho_mle <= RHO_RAZONABLE_MAX):
                    outlier = True
                    rho_propuesto = aplicar_floor(RHO_SHRINKAGE_TARGET)
                    print(f"   [OUTLIER] rho_MLE={rho_mle} fuera de rango. Cae a -0.12.")
                else:
                    outlier = False
                    rho_post = aplicar_shrinkage(rho_mle, n)
                    rho_propuesto = aplicar_floor(rho_post)
                    print(f"   rho_MLE={rho_mle:+.4f}  shrink={rho_post:+.4f}  final={rho_propuesto:+.4f}  (w={n/(n+200):.3f})")

                resultados[liga] = {
                    "n_externo": n,
                    "estado": "MLE_OK",
                    "rho_mle": rho_mle,
                    "rho_post_shrinkage": round(aplicar_shrinkage(rho_mle, n), 4) if not outlier else None,
                    "rho_propuesto_externo": round(rho_propuesto, 4),
                    "outlier": outlier,
                    "shrinkage_w": round(n/(n+200), 4),
                }

        if i < len(LIGAS_429) - 1:
            print(f"   [sleep {SLEEP_ENTRE_LIGAS}s antes de siguiente liga]")
            time.sleep(SLEEP_ENTRE_LIGAS)

    output = {
        "bead_id": BEAD_ID,
        "metodologia": {
            "ligas_target": LIGAS_429,
            "temporadas": TEMPORADAS_API_EXT,
            "max_retries_por_temporada": MAX_REINTENTOS,
            "backoff_base_seg": BACKOFF_BASE,
            "sleep_entre_temporadas": SLEEP_ENTRE_TEMPORADAS,
            "sleep_entre_ligas": SLEEP_ENTRE_LIGAS,
            "shrinkage_target": RHO_SHRINKAGE_TARGET,
            "shrinkage_pseudo_n": SHRINKAGE_PSEUDO_N,
            "outlier_range": [RHO_RAZONABLE_MIN, RHO_RAZONABLE_MAX],
            "floor": RHO_FLOOR,
        },
        "resultados": resultados,
    }
    JSON_OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"[OK] JSON: {JSON_OUT}")


if __name__ == "__main__":
    main()

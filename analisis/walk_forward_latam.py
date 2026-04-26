"""Walk-forward LATAM — adepor-bgt iter 2.

Extension del walk-forward EUR a 9 ligas LATAM via API-Football.

LIMITACION CRITICA: API-Football v3 free tier NO incluye SoT/shots/corners
en el endpoint /fixtures (solo goles). Para obtener stats por partido se
requiere endpoint /fixtures/statistics (1 call por partido = >10k calls).

Por lo tanto el xG proxy LATAM se simplifica a GOALS-ONLY:
  xg_proxy = goles  (sin smoothing por SoT/shots/corners)

Esto es coherente con el motor real cuando ESPN no provee stats:
  motor_data.calcular_xg_hibrido linea 153-154:
    if xg_calc == 0 and goles_reales > 0:
        return goles_reales

Por lo tanto los resultados LATAM son una APROXIMACION del walk-forward;
el motor en produccion usa stats ESPN (cuando estan disponibles) y degrada
a goals-only si no.

Setup:
  - Train: temps 2021, 2022, 2023 (warmup)
  - Predict: temp 2024 (target con metricas)
  - Backoff identico a adepor-m4g: 5/15/30/60s en 429.
"""
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nucleo.calibrar_rho import MAPA_LIGAS_API_FOOTBALL, API_KEY_FOOTBALL

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = ROOT / "analisis" / "walk_forward_latam.json"

LIGAS_LATAM = [
    "Argentina", "Brasil", "Bolivia",
    "Chile", "Colombia", "Ecuador",
    "Peru", "Uruguay", "Venezuela",
]
TEMPS_TRAIN = [2021, 2022, 2023]
TEMP_PREDICT = 2024
TEMPS_ALL = TEMPS_TRAIN + [TEMP_PREDICT]

# === Constantes idem walk-forward EUR ===
ALFA_EMA = 0.18
N0_ANCLA = 5
RANGO_POISSON = 10
EMA_INIT = 1.4
TIMEOUT_HTTP = 30

# Backoff
SLEEP_ENTRE_TEMPS = 6
SLEEP_ENTRE_LIGAS = 12
MAX_RETRIES = 4
BACKOFF_BASE = [5, 15, 30, 60]


# ============================================================
def poisson(k, lam):
    if lam <= 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


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


def calcular_probs_1x2(xg_l, xg_v, rho):
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    total = p1 + px + p2
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p1/total, px/total, p2/total


# ============================================================
# API-Football fetch con backoff (similar a adepor-m4g)
# ============================================================
def fetch_temp(liga_id, temp, key):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"league": liga_id, "season": temp, "status": "FT"}
    headers = {"x-apisports-key": key}

    for intento in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_HTTP)
        except requests.exceptions.RequestException as e:
            if intento < MAX_RETRIES:
                time.sleep(BACKOFF_BASE[intento - 1])
                continue
            return [], f"network_error: {e}"

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            espera = int(retry_after) if (retry_after and retry_after.isdigit()) else BACKOFF_BASE[intento - 1]
            print(f"     [429] {temp} intento {intento}/{MAX_RETRIES}, espera {espera}s")
            time.sleep(espera)
            continue

        if resp.status_code != 200:
            return [], f"http_{resp.status_code}"

        data = resp.json()
        fixtures = data.get("response", [])
        partidos = []
        for f in fixtures:
            try:
                ts = f["fixture"].get("timestamp", 0)
                ht = f["teams"]["home"]["name"]
                at = f["teams"]["away"]["name"]
                hg = f["goals"]["home"]
                ag = f["goals"]["away"]
                if hg is None or ag is None:
                    continue
                partidos.append({
                    "ts": ts,
                    "ht": ht, "at": at,
                    "hg": int(hg), "ag": int(ag),
                })
            except (KeyError, TypeError):
                continue
        return partidos, "ok"

    return [], "giveup_429"


def fetch_liga(liga, temps, key):
    liga_id = MAPA_LIGAS_API_FOOTBALL.get(liga)
    if not liga_id:
        return [], None
    todos = []
    estado_por_temp = {}
    for i, t in enumerate(temps):
        partidos, status = fetch_temp(liga_id, t, key)
        for p in partidos:
            p["temp"] = t
        todos.extend(partidos)
        estado_por_temp[t] = {"status": status, "n": len(partidos)}
        print(f"     temp {t}: N={len(partidos)} ({status})")
        if i < len(temps) - 1:
            time.sleep(SLEEP_ENTRE_TEMPS)
    todos.sort(key=lambda x: x["ts"])
    return todos, estado_por_temp


# ============================================================
# EMA goals-only (sin shots/corners)
# ============================================================
def init_estado():
    return {
        "fav_home": EMA_INIT, "con_home": EMA_INIT, "p_home": 0,
        "fav_away": EMA_INIT, "con_away": EMA_INIT, "p_away": 0,
    }


def actualizar_estado(estado, equipo, xg_f, xg_c, is_home, promedio_liga):
    if equipo not in estado:
        estado[equipo] = init_estado()
    e = estado[equipo]
    if is_home:
        ema_f = xg_f * ALFA_EMA + e["fav_home"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_home"] * (1 - ALFA_EMA)
        N = e["p_home"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_home"] = w_ema * ema_f + w_liga * promedio_liga
        e["con_home"] = w_ema * ema_c + w_liga * promedio_liga
        e["p_home"] += 1
    else:
        ema_f = xg_f * ALFA_EMA + e["fav_away"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_away"] * (1 - ALFA_EMA)
        N = e["p_away"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_away"] = w_ema * ema_f + w_liga * promedio_liga
        e["con_away"] = w_ema * ema_c + w_liga * promedio_liga
        e["p_away"] += 1


def prediccion_xg(estado, ht, at):
    el = estado.get(ht, init_estado())
    ev = estado.get(at, init_estado())
    xg_l = (el["fav_home"] + ev["con_away"]) / 2.0
    xg_v = (ev["fav_away"] + el["con_home"]) / 2.0
    return xg_l, xg_v


def get_rho_liga(liga):
    """rho actual ligas_stats."""
    import sqlite3
    DB = ROOT / "fondo_quant.db"
    con = sqlite3.connect(DB)
    r = con.execute("SELECT rho_calculado FROM ligas_stats WHERE liga = ?", (liga,)).fetchone()
    con.close()
    return r[0] if r else -0.09


def metricas(predicciones):
    n = len(predicciones)
    if n == 0:
        return {}
    hits = sum(1 for p in predicciones if p["hit"])
    brier = sum(p["brier"] for p in predicciones) / n
    mse_l = sum((p["xg_l_pred"] - p["g_l"])**2 for p in predicciones) / n
    mse_v = sum((p["xg_v_pred"] - p["g_v"])**2 for p in predicciones) / n
    bias_l = sum(p["xg_l_pred"] - p["g_l"] for p in predicciones) / n
    bias_v = sum(p["xg_v_pred"] - p["g_v"] for p in predicciones) / n

    cnt_1 = sum(1 for p in predicciones if p["outcome"] == "1")
    cnt_x = sum(1 for p in predicciones if p["outcome"] == "X")
    cnt_2 = sum(1 for p in predicciones if p["outcome"] == "2")

    buckets = defaultdict(lambda: {"n": 0, "hits": 0, "sum_p": 0.0})
    for p in predicciones:
        p_max = max(p["p1"], p["px"], p["p2"])
        b = int(p_max * 10) * 10
        b_label = f"{b}-{b+10}"
        buckets[b_label]["n"] += 1
        buckets[b_label]["sum_p"] += p_max
        if p["hit"]:
            buckets[b_label]["hits"] += 1

    calib = {}
    for k, d in sorted(buckets.items()):
        if d["n"] > 0:
            calib[k] = {
                "n": d["n"],
                "p_max_avg": round(d["sum_p"] / d["n"], 4),
                "hit_rate": round(d["hits"] / d["n"], 4),
                "delta": round(d["hits"] / d["n"] - d["sum_p"] / d["n"], 4),
            }

    return {
        "n": n,
        "hit_rate": round(hits / n, 4),
        "brier_mean": round(brier, 4),
        "xg_mse_local": round(mse_l, 4),
        "xg_mse_visita": round(mse_v, 4),
        "xg_bias_local": round(bias_l, 4),
        "xg_bias_visita": round(bias_v, 4),
        "outcomes_real": {"1": cnt_1, "X": cnt_x, "2": cnt_2},
        "base_rate_local": round(cnt_1 / n, 4),
        "calibracion_por_bucket": calib,
    }


# ============================================================
def main():
    if not API_KEY_FOOTBALL:
        print("ERROR: api_key_football no configurada", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("Walk-forward LATAM — adepor-bgt iter 2 (goals-only EMA)")
    print("=" * 70)
    print(f"Train: {TEMPS_TRAIN}  Predict: {TEMP_PREDICT}")
    print(f"Ligas: {LIGAS_LATAM}")
    print()

    out_per_liga = {}
    summary = []

    for i_liga, liga in enumerate(LIGAS_LATAM):
        print(f"\n{'='*70}")
        print(f"[LIGA] {liga}")
        print(f"{'='*70}")
        partidos, estado_temps = fetch_liga(liga, TEMPS_ALL, API_KEY_FOOTBALL)
        if not partidos:
            print(f"   [SKIP] sin datos: {estado_temps}")
            continue
        print(f"   N total = {len(partidos)}")

        # promedio liga
        prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
        print(f"   promedio_liga = {prom:.3f}")

        rho = get_rho_liga(liga)
        print(f"   rho = {rho:+.4f}")

        # Walk-forward
        estado = {}
        predicciones = []
        train_count = 0
        for p in partidos:
            es_target = p["temp"] == TEMP_PREDICT

            if es_target:
                xg_l_pred, xg_v_pred = prediccion_xg(estado, p["ht"], p["at"])
                p1, px, p2 = calcular_probs_1x2(xg_l_pred, xg_v_pred, rho)
                if p["hg"] > p["ag"]:
                    outcome = "1"
                elif p["hg"] == p["ag"]:
                    outcome = "X"
                else:
                    outcome = "2"
                argmax = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
                hit = argmax == outcome
                brier = (
                    (p1 - (1.0 if outcome == "1" else 0.0))**2
                    + (px - (1.0 if outcome == "X" else 0.0))**2
                    + (p2 - (1.0 if outcome == "2" else 0.0))**2
                )
                predicciones.append({
                    "ht": p["ht"], "at": p["at"],
                    "g_l": p["hg"], "g_v": p["ag"],
                    "outcome": outcome,
                    "xg_l_pred": xg_l_pred, "xg_v_pred": xg_v_pred,
                    "p1": p1, "px": px, "p2": p2,
                    "argmax": argmax, "hit": hit, "brier": brier,
                })

            # Goals-only EMA: xg_real = goles (no shots/corners)
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
            actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
            actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

            if not es_target:
                train_count += 1

        m = metricas(predicciones)
        if not m:
            print("   [SKIP] sin predicciones target")
            continue

        print(f"\n   N target = {m['n']}, train warmup = {train_count}")
        print(f"   hit_rate    = {m['hit_rate']:.4f}  (base_rate_local={m['base_rate_local']:.3f})")
        print(f"   brier_mean  = {m['brier_mean']:.4f}")
        print(f"   xg_bias L   = {m['xg_bias_local']:+.3f}")
        print(f"   xg_bias V   = {m['xg_bias_visita']:+.3f}")
        print(f"   xg_MSE L    = {m['xg_mse_local']:.4f}")

        out_per_liga[liga] = {
            "config": {
                "rho": rho,
                "promedio_liga": round(prom, 4),
                "n_total": len(partidos),
            },
            "estado_temps": estado_temps,
            "metricas": m,
        }
        summary.append((liga, m))

        if i_liga < len(LIGAS_LATAM) - 1:
            print(f"   [sleep {SLEEP_ENTRE_LIGAS}s antes de siguiente liga]")
            time.sleep(SLEEP_ENTRE_LIGAS)

    # Tabla resumen
    print(f"\n{'='*70}")
    print(f"RESUMEN MULTI-LIGA LATAM (target temp 2024)")
    print(f"{'='*70}")
    print(f"{'Liga':<11} {'N':>4} {'Hit':>6} {'Base':>6}  {'Brier':>7} {'xG_bias_L':>10} {'xG_MSE_L':>10}")
    print("-" * 70)
    for liga, m in summary:
        print(f"{liga:<11} {m['n']:>4} {m['hit_rate']:>6.3f} {m['base_rate_local']:>6.3f}  "
              f"{m['brier_mean']:>7.4f} {m['xg_bias_local']:>+10.3f} {m['xg_mse_local']:>10.4f}")

    output = {
        "bead_id": "adepor-bgt",
        "iter": 2,
        "scope": "LATAM 9 ligas (API-Football, goals-only EMA)",
        "limitacion": "API free tier no provee SoT/shots/corners; xg=goles directos.",
        "config_global": {
            "alfa_ema": ALFA_EMA,
            "n0_ancla": N0_ANCLA,
            "temps_train": TEMPS_TRAIN,
            "temp_predict": TEMP_PREDICT,
        },
        "ligas": out_per_liga,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

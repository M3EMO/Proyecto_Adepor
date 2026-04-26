"""Walk-forward backtest multi-liga — adepor-bgt extension.

Extiende el piloto EPL a 6 ligas con CSV disponible en football-data.co.uk.
Usa fuente CSV unica (no API-Football) -> rapido y reproducible.

Ligas + codigos:
  Inglaterra: E0 (Premier)
  Italia:     I1 (Serie A)
  Espana:     SP1 (La Liga)
  Francia:    F1 (Ligue 1)
  Alemania:   D1 (Bundesliga)
  Turquia:    T1 (Super Lig)

Setup por liga:
  - Train: 3 temps (2021-22, 2022-23, 2023-24)
  - Predict: 2024-25 (1 temp completa)
  - Eval: hit_rate, Brier, xG_MSE/bias, calibration

Output: walk_forward_multiliga.json + tabla resumen por liga
"""
import csv
import io
import json
import math
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "walk_forward_multiliga.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
RANGO_POISSON = 10
EMA_INIT = 1.4

LIGAS = {
    "Inglaterra": "E0",
    "Italia":     "I1",
    "Espana":     "SP1",
    "Francia":    "F1",
    "Alemania":   "D1",
    "Turquia":    "T1",
    "Noruega":    "N1",  # Eliteserien (agregado 2026-04-26 para coverage completo)
}
TEMPS_TRAIN = ["2122", "2223", "2324"]
TEMPS_PREDICT = ["2425"]
TEMPS_ALL = TEMPS_TRAIN + TEMPS_PREDICT


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


def descargar_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req).read().decode("utf-8-sig", errors="ignore")


def parsear_temp(texto, codigo):
    rows = []
    reader = csv.DictReader(io.StringIO(texto))
    for r in reader:
        try:
            fecha = r.get("Date", "")
            if not fecha:
                continue
            try:
                d = datetime.strptime(fecha, "%d/%m/%Y")
            except ValueError:
                d = datetime.strptime(fecha, "%d/%m/%y")
            ht = r.get("HomeTeam", "").strip()
            at = r.get("AwayTeam", "").strip()
            hg = r.get("FTHG", "")
            ag = r.get("FTAG", "")
            if not ht or not at or hg == "" or ag == "":
                continue
            hg = int(hg)
            ag = int(ag)
            hs = int(r.get("HS", 0) or 0)
            as_ = int(r.get("AS", 0) or 0)
            hst = int(r.get("HST", 0) or 0)
            ast = int(r.get("AST", 0) or 0)
            hc = int(r.get("HC", 0) or 0)
            ac = int(r.get("AC", 0) or 0)
            rows.append({
                "temp": codigo, "fecha": d,
                "ht": ht, "at": at, "hg": hg, "ag": ag,
                "hst": hst, "ast": ast, "hs": hs, "as": as_,
                "hc": hc, "ac": ac,
            })
        except (ValueError, TypeError):
            continue
    return rows


def cargar_liga(codigo_csv):
    """Descarga 4 temps de la liga."""
    todos = []
    for temp in TEMPS_ALL:
        url = f"https://www.football-data.co.uk/mmz4281/{temp}/{codigo_csv}.csv"
        try:
            texto = descargar_csv(url)
            partidos = parsear_temp(texto, temp)
            todos.extend(partidos)
        except Exception as e:
            print(f"   [ERROR] {url}: {e}")
    todos.sort(key=lambda x: x["fecha"])
    return todos


def xg_hibrido(sot, shots, corners, goles, beta_sot, coef_c):
    shots_off = max(0, shots - sot)
    xg_calc = (sot * beta_sot) + (shots_off * BETA_SHOTS_OFF) + (corners * coef_c)
    if xg_calc == 0 and goles > 0:
        return float(goles)
    return xg_calc * 0.70 + goles * 0.30


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
        nuevo_ema_fav = xg_f * ALFA_EMA + e["fav_home"] * (1 - ALFA_EMA)
        nuevo_ema_con = xg_c * ALFA_EMA + e["con_home"] * (1 - ALFA_EMA)
        N = e["p_home"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_home"] = w_ema * nuevo_ema_fav + w_liga * promedio_liga
        e["con_home"] = w_ema * nuevo_ema_con + w_liga * promedio_liga
        e["p_home"] += 1
    else:
        nuevo_ema_fav = xg_f * ALFA_EMA + e["fav_away"] * (1 - ALFA_EMA)
        nuevo_ema_con = xg_c * ALFA_EMA + e["con_away"] * (1 - ALFA_EMA)
        N = e["p_away"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_away"] = w_ema * nuevo_ema_fav + w_liga * promedio_liga
        e["con_away"] = w_ema * nuevo_ema_con + w_liga * promedio_liga
        e["p_away"] += 1


def prediccion_xg(estado, ht, at):
    el = estado.get(ht, init_estado())
    ev = estado.get(at, init_estado())
    xg_l = (el["fav_home"] + ev["con_away"]) / 2.0
    xg_v = (ev["fav_away"] + el["con_home"]) / 2.0
    return xg_l, xg_v


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

    # Frecuencia real outcomes (base rate)
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


def get_rho_liga(liga):
    """rho actual en DB (ligas_stats), o RHO_FALLBACK -0.09."""
    con = sqlite3.connect(DB)
    r = con.execute("SELECT rho_calculado FROM ligas_stats WHERE liga = ?", (liga,)).fetchone()
    con.close()
    return r[0] if r else -0.09


def get_coef_corner_liga(liga):
    con = sqlite3.connect(DB)
    r = con.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga = ?", (liga,)).fetchone()
    con.close()
    return r[0] if r and r[0] is not None else 0.02


def main():
    print("=" * 70)
    print("Walk-forward MULTI-LIGA — adepor-bgt extension")
    print("=" * 70)
    print(f"Train: {TEMPS_TRAIN}  Predict: {TEMPS_PREDICT}")
    print(f"Ligas: {list(LIGAS.keys())}")
    print()

    out_per_liga = {}
    summary_rows = []

    for liga, codigo in LIGAS.items():
        print(f"\n{'='*70}")
        print(f"[LIGA] {liga} ({codigo})")
        print(f"{'='*70}")

        # Cargar
        partidos = cargar_liga(codigo)
        print(f"   N total = {len(partidos)}")
        if len(partidos) < 100:
            print(f"   [SKIP] N insuficiente.")
            continue

        # promedio_liga
        prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
        print(f"   promedio_liga = {prom:.3f}")

        # Constants per liga
        rho = get_rho_liga(liga)
        coef_c = get_coef_corner_liga(liga)
        print(f"   rho = {rho:+.4f}")
        print(f"   coef_corner = {coef_c:.4f}")

        # Walk-forward
        estado = {}
        predicciones = []
        train_count = 0
        for p in partidos:
            es_target = p["temp"] in TEMPS_PREDICT

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

            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], BETA_SOT, coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], BETA_SOT, coef_c)
            actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
            actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

            if not es_target:
                train_count += 1

        m = metricas(predicciones)
        print(f"\n   N target = {m['n']}, train warmup = {train_count}")
        print(f"   hit_rate    = {m['hit_rate']:.4f}  (base_rate_local={m['base_rate_local']:.3f})")
        print(f"   brier_mean  = {m['brier_mean']:.4f}")
        print(f"   xg_bias L   = {m['xg_bias_local']:+.3f}")
        print(f"   xg_bias V   = {m['xg_bias_visita']:+.3f}")
        print(f"   xg_MSE L    = {m['xg_mse_local']:.4f}")
        print(f"   xg_MSE V    = {m['xg_mse_visita']:.4f}")

        out_per_liga[liga] = {
            "config": {
                "rho": rho,
                "coef_corner": coef_c,
                "promedio_liga": round(prom, 4),
            },
            "metricas": m,
        }
        summary_rows.append((liga, m))

    # Tabla resumen
    print(f"\n{'='*70}")
    print(f"RESUMEN MULTI-LIGA (target temp 2024-25)")
    print(f"{'='*70}")
    print(f"{'Liga':<11} {'N':>4} {'Hit':>6} {'Base':>6}  {'Brier':>7} {'xG_bias_L':>10} {'xG_MSE_L':>10}")
    print("-" * 70)
    for liga, m in summary_rows:
        print(f"{liga:<11} {m['n']:>4} {m['hit_rate']:>6.3f} {m['base_rate_local']:>6.3f}  "
              f"{m['brier_mean']:>7.4f} {m['xg_bias_local']:>+10.3f} {m['xg_mse_local']:>10.4f}")

    output = {
        "bead_id": "adepor-bgt",
        "scope": "multi-liga EUR (CSV football-data.co.uk)",
        "config_global": {
            "alfa_ema": ALFA_EMA,
            "n0_ancla": N0_ANCLA,
            "beta_sot": BETA_SOT,
            "beta_shots_off": BETA_SHOTS_OFF,
            "temps_train": TEMPS_TRAIN,
            "temps_predict": TEMPS_PREDICT,
        },
        "ligas": out_per_liga,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

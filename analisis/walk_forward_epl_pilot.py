"""Walk-forward backtest piloto EPL — adepor-bgt 'maquina del tiempo'.

Replay cronologico de 4 temporadas EPL (2021-22 a 2024-25) reproduciendo
motor_data.actualizar_estado() + motor_calculadora prediccion.

Setup:
  - Train (warmup, sin metricas): 2021-22 + 2022-23 + 2023-24 (1140 partidos)
  - Predict (target, con metricas): 2024-25 (380 partidos)
  - Hold-out (sanity): 2025-26 disponible pero no usado en este piloto

Para cada partido en target:
  ANTES de procesar:
    1. Lookup estado EMA actual del local (fav_home, con_home)
    2. Lookup estado EMA actual del visitante (fav_away, con_away)
    3. Calcular xg_local_pred = (fav_home * con_away) / promedio_liga
    4. Calcular xg_visita_pred = (fav_away * con_home) / promedio_liga
    5. Aplicar Poisson + tau Dixon-Coles -> prob_1, prob_x, prob_2
    6. Comparar con resultado real
  DESPUES de procesar:
    7. Calcular xg_real_local = beta_sot*sot + beta_off*shots_off + coef_corner*corners
       Mezclar 0.70*xg_calc + 0.30*goles
    8. Update estado_equipos via EMA Bayesiano

Metricas (solo sobre los 380 partidos de target):
  - hit_rate: argmax(prob_1, prob_x, prob_2) == argmax(resultado real)
  - Brier: mean(sum_i (p_i - 1[outcome=i])^2)
  - xG MSE local + visita
  - xG bias (mean(xg_pred - g_real))
  - Calibration por bucket prob (40-50%, 50-60%, etc.)
"""
import csv
import io
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analisis" / "walk_forward_epl_pilot.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
# Constantes (consistentes con motor_data + motor_calculadora)
# ============================================================
ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
COEF_CORNER_EPL = 0.02
RHO_EPL = -0.030  # rho actual EPL post-update (adepor-0yy)
RANGO_POISSON = 10

EMA_INIT = 1.4  # ema inicial para equipos sin historial
PROMEDIO_LIGA_INIT = 1.5  # avg goals por equipo en EPL (recalculado al cargar)

URLS_EPL = [
    ("2122", "https://www.football-data.co.uk/mmz4281/2122/E0.csv"),
    ("2223", "https://www.football-data.co.uk/mmz4281/2223/E0.csv"),
    ("2324", "https://www.football-data.co.uk/mmz4281/2324/E0.csv"),
    ("2425", "https://www.football-data.co.uk/mmz4281/2425/E0.csv"),
    ("2526", "https://www.football-data.co.uk/mmz4281/2526/E0.csv"),
]
TEMPS_TRAIN = ["2122", "2223", "2324"]
TEMPS_PREDICT = ["2425"]


# ============================================================
# Helpers Poisson + Dixon-Coles
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
# Carga datos
# ============================================================
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
                "temp": codigo,
                "fecha": d,
                "ht": ht, "at": at,
                "hg": hg, "ag": ag,
                "hst": hst, "ast": ast,
                "hs": hs, "as": as_,
                "hc": hc, "ac": ac,
            })
        except (ValueError, TypeError):
            continue
    return rows


# ============================================================
# xG hibrido (replica motor_data.calcular_xg_hibrido)
# ============================================================
def xg_hibrido(sot, shots, corners, goles_reales, beta_sot=BETA_SOT,
               beta_off=BETA_SHOTS_OFF, coef_c=COEF_CORNER_EPL):
    shots_off = max(0, shots - sot)
    xg_calc = (sot * beta_sot) + (shots_off * beta_off) + (corners * coef_c)
    if xg_calc == 0 and goles_reales > 0:
        return float(goles_reales)
    return xg_calc * 0.70 + goles_reales * 0.30


# ============================================================
# EMA + Bayesian update (replica motor_data.actualizar_estado, simplificado)
# ============================================================
def init_estado_equipo(nombre):
    return {
        "fav_home": EMA_INIT, "con_home": EMA_INIT, "p_home": 0,
        "fav_away": EMA_INIT, "con_away": EMA_INIT, "p_away": 0,
    }


def actualizar_estado(estado, equipo, xg_f, xg_c, is_home, promedio_liga):
    if equipo not in estado:
        estado[equipo] = init_estado_equipo(equipo)
    e = estado[equipo]
    if is_home:
        viejo_fav, viejo_con = e["fav_home"], e["con_home"]
        nuevo_ema_fav = xg_f * ALFA_EMA + viejo_fav * (1 - ALFA_EMA)
        nuevo_ema_con = xg_c * ALFA_EMA + viejo_con * (1 - ALFA_EMA)
        N = e["p_home"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_home"] = w_ema * nuevo_ema_fav + w_liga * promedio_liga
        e["con_home"] = w_ema * nuevo_ema_con + w_liga * promedio_liga
        e["p_home"] += 1
    else:
        viejo_fav, viejo_con = e["fav_away"], e["con_away"]
        nuevo_ema_fav = xg_f * ALFA_EMA + viejo_fav * (1 - ALFA_EMA)
        nuevo_ema_con = xg_c * ALFA_EMA + viejo_con * (1 - ALFA_EMA)
        N = e["p_away"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_away"] = w_ema * nuevo_ema_fav + w_liga * promedio_liga
        e["con_away"] = w_ema * nuevo_ema_con + w_liga * promedio_liga
        e["p_away"] += 1


def prediccion_xg(estado, ht, at, promedio_liga):
    """Replica motor_calculadora linea 902-903: PROMEDIO ARITMETICO (no producto/liga).
    xg_local  = (ema_l.fav_home + ema_v.con_away) / 2.0
    xg_visita = (ema_v.fav_away + ema_l.con_home) / 2.0
    """
    el = estado.get(ht, init_estado_equipo(ht))
    ev = estado.get(at, init_estado_equipo(at))
    xg_l = (el["fav_home"] + ev["con_away"]) / 2.0
    xg_v = (ev["fav_away"] + el["con_home"]) / 2.0
    return xg_l, xg_v


# ============================================================
# Metricas
# ============================================================
def metricas_aggr(predicciones):
    n = len(predicciones)
    if n == 0:
        return {}
    hits = sum(1 for p in predicciones if p["hit"])
    brier_sum = sum(p["brier"] for p in predicciones)
    xg_mse_l = sum((p["xg_l_pred"] - p["g_l"])**2 for p in predicciones) / n
    xg_mse_v = sum((p["xg_v_pred"] - p["g_v"])**2 for p in predicciones) / n
    xg_bias_l = sum(p["xg_l_pred"] - p["g_l"] for p in predicciones) / n
    xg_bias_v = sum(p["xg_v_pred"] - p["g_v"] for p in predicciones) / n

    # Calibracion por bucket de prob max
    buckets = defaultdict(lambda: {"n": 0, "hits": 0, "sum_p_max": 0.0})
    for p in predicciones:
        p_max = max(p["p1"], p["px"], p["p2"])
        b = int(p_max * 10) * 10  # 30, 40, 50, 60, 70, 80
        b_label = f"{b}-{b+10}"
        buckets[b_label]["n"] += 1
        buckets[b_label]["sum_p_max"] += p_max
        if p["hit"]:
            buckets[b_label]["hits"] += 1

    calib = {}
    for b, d in sorted(buckets.items()):
        if d["n"] > 0:
            calib[b] = {
                "n": d["n"],
                "p_max_avg": d["sum_p_max"] / d["n"],
                "hit_rate": d["hits"] / d["n"],
                "delta": (d["hits"] / d["n"]) - (d["sum_p_max"] / d["n"]),
            }

    return {
        "n": n,
        "hit_rate": hits / n,
        "brier_mean": brier_sum / n,
        "xg_mse_local": xg_mse_l,
        "xg_mse_visita": xg_mse_v,
        "xg_bias_local": xg_bias_l,
        "xg_bias_visita": xg_bias_v,
        "calibracion_por_bucket": calib,
    }


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("Walk-forward EPL — adepor-bgt piloto")
    print("=" * 70)
    print(f"Train temps: {TEMPS_TRAIN}")
    print(f"Predict temp: {TEMPS_PREDICT}")
    print()

    # 1. Cargar todas las temps
    todos = []
    for codigo, url in URLS_EPL:
        if codigo == "2526":
            continue  # hold-out, no lo usamos
        print(f"[LOAD] {codigo}...")
        texto = descargar_csv(url)
        partidos = parsear_temp(texto, codigo)
        print(f"   N={len(partidos)} partidos")
        todos.extend(partidos)

    # Ordenar cronologicamente
    todos.sort(key=lambda x: x["fecha"])
    print(f"\n[TOTAL] {len(todos)} partidos cargados, ordenados por fecha")

    # 2. Calcular promedio_liga estable (avg goles por equipo por partido)
    total_goals = sum(p["hg"] + p["ag"] for p in todos)
    n_eq_partidos = len(todos) * 2
    promedio_liga = total_goals / n_eq_partidos
    print(f"[CONFIG] promedio_liga_EPL = {promedio_liga:.3f} goles/equipo/partido")

    # 3. Walk-forward
    estado = {}
    predicciones = []
    train_count = 0

    print(f"\n[REPLAY] Walk-forward {len(todos)} partidos...")
    for p in todos:
        es_target = p["temp"] in TEMPS_PREDICT

        # 3a. Predict ANTES de procesar (solo si target)
        if es_target:
            xg_l_pred, xg_v_pred = prediccion_xg(estado, p["ht"], p["at"], promedio_liga)
            p1, px, p2 = calcular_probs_1x2(xg_l_pred, xg_v_pred, RHO_EPL)
            # Resultado real
            if p["hg"] > p["ag"]:
                outcome = "1"
                pi_correct = p1
            elif p["hg"] == p["ag"]:
                outcome = "X"
                pi_correct = px
            else:
                outcome = "2"
                pi_correct = p2
            argmax_idx = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
            hit = (argmax_idx == outcome)
            # Brier 1X2: sum (p_i - 1[outcome==i])^2
            brier = (
                (p1 - (1.0 if outcome == "1" else 0.0))**2
                + (px - (1.0 if outcome == "X" else 0.0))**2
                + (p2 - (1.0 if outcome == "2" else 0.0))**2
            )

            predicciones.append({
                "fecha": p["fecha"].isoformat(),
                "ht": p["ht"], "at": p["at"],
                "g_l": p["hg"], "g_v": p["ag"],
                "outcome": outcome,
                "xg_l_pred": xg_l_pred,
                "xg_v_pred": xg_v_pred,
                "p1": p1, "px": px, "p2": p2,
                "argmax": argmax_idx,
                "hit": hit,
                "brier": brier,
            })

        # 3b. Procesar (update estado con stats reales)
        xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"])
        xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"])
        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, is_home=True, promedio_liga=promedio_liga)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, is_home=False, promedio_liga=promedio_liga)

        if not es_target:
            train_count += 1

    # 4. Reporte
    print(f"\n[REPLAY DONE] Train (warmup) procesados: {train_count}")
    print(f"            Target predicciones: {len(predicciones)}")
    print()
    print("=" * 70)
    print("METRICAS sobre TEMP TARGET 2024-25")
    print("=" * 70)
    m = metricas_aggr(predicciones)
    print(f"N predicciones:       {m['n']}")
    print(f"Hit rate:             {m['hit_rate']:.4f}  (argmax matches outcome)")
    print(f"Brier mean:           {m['brier_mean']:.4f}  (lower = better, ideal=0)")
    print(f"xG MSE local:         {m['xg_mse_local']:.4f}")
    print(f"xG MSE visita:        {m['xg_mse_visita']:.4f}")
    print(f"xG bias local:        {m['xg_bias_local']:+.4f}  (>0 sobre-estima)")
    print(f"xG bias visita:       {m['xg_bias_visita']:+.4f}")
    print()
    print("Calibracion por bucket prob_max:")
    print(f"{'Bucket':<10} {'N':>4}  {'p_max':>6}  {'hit_rate':>8}  {'delta':>7}")
    for b, d in m["calibracion_por_bucket"].items():
        print(f"{b:<10} {d['n']:>4}  {d['p_max_avg']:>6.3f}  {d['hit_rate']:>8.3f}  {d['delta']:>+7.3f}")

    # 5. Guardar JSON
    output = {
        "bead_id": "adepor-bgt",
        "config": {
            "alfa_ema": ALFA_EMA,
            "n0_ancla": N0_ANCLA,
            "rho_epl": RHO_EPL,
            "beta_sot": BETA_SOT,
            "beta_shots_off": BETA_SHOTS_OFF,
            "coef_corner_epl": COEF_CORNER_EPL,
            "promedio_liga_calculado": promedio_liga,
            "temps_train": TEMPS_TRAIN,
            "temps_predict": TEMPS_PREDICT,
        },
        "metricas": m,
        "predicciones_sample_5": predicciones[:5],
        "n_total": len(predicciones),
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

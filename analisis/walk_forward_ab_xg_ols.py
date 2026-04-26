"""Walk-forward A/B: motor actual (β coef hardcoded) vs motor con OLS coef por liga.

Pregunta clave: arreglar signos invertidos β_shots_off y coef_corner mejora
el predictor (hit_rate / Brier / xG MSE) cuando el train propaga a EMA?

Setup:
  - Lado A (motor actual): β_sot global=0.352, β_off=+0.010, coef_corner=+0.020 default.
  - Lado B (OLS por liga): cada liga usa sus β estimados via OLS sobre partidos_historico_externo.

Train: temps 2022, 2023.
Predict: temp 2024.
Mismo Dixon-Coles + Poisson + Bayesian shrinkage en ambos lados.
Diferencia: SOLO la fórmula xg_hibrido durante el replay.

OUTPUT: walk_forward_ab_xg_ols.json con per-liga delta_hit, delta_brier, delta_mse.
"""
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
CACHE = ROOT / "analisis" / "cache_espn"
COEF_OLS = ROOT / "analisis" / "calibracion_xg_ols_por_liga.json"
OUT = ROOT / "analisis" / "walk_forward_ab_xg_ols.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# === Constants motor actual ===
ALFA_EMA = 0.18
N0_ANCLA = 5
RANGO_POISSON = 10
EMA_INIT = 1.4

# Lado A — motor actual (P4 fase3 globals)
BETA_SOT_A = 0.352
BETA_OFF_A = 0.010
COEF_CORNER_A_DEFAULT = 0.020

# Lado B — OLS por liga (cargar desde JSON)
def cargar_coef_ols():
    data = json.loads(COEF_OLS.read_text(encoding="utf-8"))
    out = {}
    for liga, info in data.items():
        if liga.startswith("__"):
            continue
        if "beta_sot" not in info:
            continue
        out[liga] = {
            "beta_sot": info["beta_sot"],
            "beta_off": info["beta_shots_off"],
            "coef_corner": info["coef_corner"],
            "intercept": info["intercept"],
        }
    return out


COEF_OLS_POR_LIGA = cargar_coef_ols()
print(f"OLS coefs cargados para {len(COEF_OLS_POR_LIGA)} ligas: {sorted(COEF_OLS_POR_LIGA.keys())}", flush=True)

TEMPS_TRAIN = [2022, 2023]
TEMP_PREDICT = 2024


# === Helpers (Poisson + tau) ===
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


# === xg_hibrido: lado A vs lado B ===
def xg_hibrido_actual(sot, shots, corners, goles, coef_corner_liga):
    """Motor real. Coef hardcoded globales."""
    shots_off = max(0, shots - sot)
    xg_calc = (sot * BETA_SOT_A) + (shots_off * BETA_OFF_A) + (corners * coef_corner_liga)
    if xg_calc == 0 and goles > 0:
        return float(goles)
    return xg_calc * 0.70 + goles * 0.30


def xg_hibrido_ols(sot, shots, corners, goles, liga):
    """OLS coef por liga + intercept. Floor a 0 si negativo (clip)."""
    if liga not in COEF_OLS_POR_LIGA:
        # Sin OLS para esta liga: fallback al lado A
        cc = 0.02
        return xg_hibrido_actual(sot, shots, corners, goles, cc)
    coef = COEF_OLS_POR_LIGA[liga]
    shots_off = max(0, shots - sot)
    xg_calc = (
        coef["intercept"]
        + sot * coef["beta_sot"]
        + shots_off * coef["beta_off"]
        + corners * coef["coef_corner"]
    )
    xg_calc = max(0.0, xg_calc)  # floor: no goles negativos posibles
    if xg_calc == 0 and goles > 0:
        return float(goles)
    return xg_calc * 0.70 + goles * 0.30


# === EMA con Bayesian shrinkage ===
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
    return (el["fav_home"] + ev["con_away"]) / 2.0, (ev["fav_away"] + el["con_home"]) / 2.0


def get_rho_y_corner(liga):
    con = sqlite3.connect(DB)
    r = con.execute(
        "SELECT rho_calculado, coef_corner_calculado FROM ligas_stats WHERE liga = ?",
        (liga,),
    ).fetchone()
    con.close()
    rho = r[0] if r else -0.09
    coef_c = r[1] if r and r[1] is not None else 0.02
    return rho, coef_c


def cargar_partidos_liga(liga, temps):
    todos = []
    for t in temps:
        f = CACHE / f"{liga}_{t}.json"
        if not f.exists():
            continue
        partidos = json.loads(f.read_text(encoding="utf-8"))
        for p in partidos:
            p["temp"] = t
            fe = p.get("fecha", "")
            if isinstance(fe, str) and "T" in fe:
                p["fecha"] = fe.replace("T", " ").replace("Z", "")
        todos.extend(partidos)

    def parse_fecha(p):
        try:
            return datetime.fromisoformat(p["fecha"][:19].replace(" ", "T"))
        except (ValueError, KeyError):
            return datetime.min

    todos.sort(key=parse_fecha)
    return todos


def correr_lado(liga, partidos, lado, rho, coef_c, prom):
    """Replay walk-forward, returns predicciones del target temp."""
    estado = {}
    predicciones = []
    for p in partidos:
        try:
            year = datetime.fromisoformat(p["fecha"][:19].replace(" ", "T")).year
        except (ValueError, KeyError):
            continue
        es_target = year == TEMP_PREDICT or p.get("temp") == TEMP_PREDICT

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
                (p1 - (1.0 if outcome == "1" else 0.0)) ** 2
                + (px - (1.0 if outcome == "X" else 0.0)) ** 2
                + (p2 - (1.0 if outcome == "2" else 0.0)) ** 2
            )
            predicciones.append({
                "ht": p["ht"], "at": p["at"], "g_l": p["hg"], "g_v": p["ag"],
                "outcome": outcome,
                "xg_l_pred": xg_l_pred, "xg_v_pred": xg_v_pred,
                "p1": p1, "px": px, "p2": p2, "hit": hit, "brier": brier,
            })

        # Update estado: lado A o lado B segun
        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        elif lado == "A":
            xg_real_l = xg_hibrido_actual(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido_actual(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        else:  # lado B (OLS)
            xg_real_l = xg_hibrido_ols(p["hst"], p["hs"], p["hc"], p["hg"], liga)
            xg_real_v = xg_hibrido_ols(p["ast"], p["as"], p["ac"], p["ag"], liga)

        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

    return predicciones


def metricas(preds):
    n = len(preds)
    if n == 0:
        return {"n": 0}
    hits = sum(1 for p in preds if p["hit"])
    brier = sum(p["brier"] for p in preds) / n
    mse_l = sum((p["xg_l_pred"] - p["g_l"]) ** 2 for p in preds) / n
    mse_v = sum((p["xg_v_pred"] - p["g_v"]) ** 2 for p in preds) / n
    bias_l = sum(p["xg_l_pred"] - p["g_l"] for p in preds) / n
    bias_v = sum(p["xg_v_pred"] - p["g_v"] for p in preds) / n
    cnt_1 = sum(1 for p in preds if p["outcome"] == "1")
    return {
        "n": n,
        "hit_rate": round(hits / n, 4),
        "brier_mean": round(brier, 4),
        "xg_mse_local": round(mse_l, 4),
        "xg_mse_visita": round(mse_v, 4),
        "xg_bias_local": round(bias_l, 4),
        "xg_bias_visita": round(bias_v, 4),
        "base_rate_local": round(cnt_1 / n, 4),
        "edge_pp": round(100 * (hits / n - cnt_1 / n), 4),
    }


def main():
    LIGAS_FULL_STATS = sorted(COEF_OLS_POR_LIGA.keys())
    print(f"\n=== A/B Walk-forward — Motor actual vs OLS coef por liga ===")
    print(f"Train: {TEMPS_TRAIN}  Predict: {TEMP_PREDICT}")
    print(f"Ligas A/B (con OLS coef calibrados): {LIGAS_FULL_STATS}")
    print()

    out = {}
    summary = []
    for liga in LIGAS_FULL_STATS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            # EUR: cargar de partidos_historico_externo (CSV ya en DB) NOT ESPN cache
            con = sqlite3.connect(DB)
            cur = con.cursor()
            rows = cur.execute(
                """
                SELECT fecha, ht, at, hg, ag, hst, ast, hs, as_, hc, ac, temp
                FROM partidos_historico_externo
                WHERE liga = ? AND temp IN (2022, 2023, 2024) AND has_full_stats = 1
                ORDER BY fecha
                """,
                (liga,),
            ).fetchall()
            partidos = [{
                "fecha": r[0], "ht": r[1], "at": r[2], "hg": r[3], "ag": r[4],
                "hst": r[5] or 0, "ast": r[6] or 0, "hs": r[7] or 0,
                "as": r[8] or 0, "hc": r[9] or 0, "ac": r[10] or 0,
                "temp": r[11],
            } for r in rows]
            con.close()
        if not partidos:
            print(f"  {liga}: SKIP no data")
            continue

        rho, coef_c = get_rho_y_corner(liga)
        prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)

        preds_a = correr_lado(liga, partidos, "A", rho, coef_c, prom)
        preds_b = correr_lado(liga, partidos, "B", rho, coef_c, prom)

        m_a = metricas(preds_a)
        m_b = metricas(preds_b)

        if m_a.get("n", 0) == 0:
            print(f"  {liga}: skip sin target")
            continue

        d_hit = m_b["hit_rate"] - m_a["hit_rate"]
        d_brier = m_b["brier_mean"] - m_a["brier_mean"]
        d_mse_l = m_b["xg_mse_local"] - m_a["xg_mse_local"]
        d_bias_l = m_b["xg_bias_local"] - m_a["xg_bias_local"]

        veredicto = "MEJORA" if d_hit > 0.005 and d_brier < 0 else (
                    "IGUAL" if abs(d_hit) <= 0.005 else "EMPEORA")
        out[liga] = {
            "lado_A_motor_actual": m_a,
            "lado_B_ols_coef": m_b,
            "delta": {
                "hit_rate": round(d_hit, 4),
                "brier_mean": round(d_brier, 4),
                "xg_mse_local": round(d_mse_l, 4),
                "xg_bias_local": round(d_bias_l, 4),
            },
            "veredicto": veredicto,
        }
        summary.append((liga, m_a, m_b, d_hit, d_brier, veredicto))

    print(f"{'Liga':<13} {'N':>4}  {'Hit_A':>7} {'Hit_B':>7} {'Δ_Hit':>7}  "
          f"{'Brier_A':>8} {'Brier_B':>8} {'Δ_Brier':>8}  {'Veredicto':>10}")
    print("-" * 90)
    for liga, ma, mb, dh, db, ver in summary:
        print(f"{liga:<13} {ma['n']:>4}  {ma['hit_rate']:>7.4f} {mb['hit_rate']:>7.4f} {dh:>+7.4f}  "
              f"{ma['brier_mean']:>8.4f} {mb['brier_mean']:>8.4f} {db:>+8.4f}  {ver:>10}")

    # Agregar resumen global
    n_total = sum(s[1]["n"] for s in summary)
    sum_hit_a = sum(s[1]["n"] * s[1]["hit_rate"] for s in summary) / n_total if n_total else 0
    sum_hit_b = sum(s[2]["n"] * s[2]["hit_rate"] for s in summary) / n_total if n_total else 0
    sum_brier_a = sum(s[1]["n"] * s[1]["brier_mean"] for s in summary) / n_total if n_total else 0
    sum_brier_b = sum(s[2]["n"] * s[2]["brier_mean"] for s in summary) / n_total if n_total else 0
    print()
    print(f"GLOBAL pooled (N={n_total}):")
    print(f"  Hit_A   = {sum_hit_a:.4f}  Hit_B   = {sum_hit_b:.4f}  Δ = {sum_hit_b - sum_hit_a:+.4f}")
    print(f"  Brier_A = {sum_brier_a:.4f}  Brier_B = {sum_brier_b:.4f}  Δ = {sum_brier_b - sum_brier_a:+.4f}")
    print()
    n_mejora = sum(1 for s in summary if s[5] == "MEJORA")
    n_empeora = sum(1 for s in summary if s[5] == "EMPEORA")
    n_igual = sum(1 for s in summary if s[5] == "IGUAL")
    print(f"Veredictos: {n_mejora} MEJORA / {n_igual} IGUAL / {n_empeora} EMPEORA")

    out["__resumen__"] = {
        "n_ligas": len(summary),
        "n_obs_pool": n_total,
        "hit_pool_A": round(sum_hit_a, 4),
        "hit_pool_B": round(sum_hit_b, 4),
        "delta_hit_pool": round(sum_hit_b - sum_hit_a, 4),
        "brier_pool_A": round(sum_brier_a, 4),
        "brier_pool_B": round(sum_brier_b, 4),
        "delta_brier_pool": round(sum_brier_b - sum_brier_a, 4),
        "n_mejora": n_mejora, "n_igual": n_igual, "n_empeora": n_empeora,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

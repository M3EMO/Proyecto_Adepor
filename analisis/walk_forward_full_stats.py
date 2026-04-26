"""Walk-forward LATAM con FULL STATS (ESPN scraped) — adepor-bgt iter3.

Usa cache_espn/{liga}_{temp}.json (poblado por scraper_espn_historico.py)
para hacer walk-forward fiel al motor real (xG hibrido con SoT+shots+corners).

Comparativa esperable: iter2 (goals-only) vs iter3 (full stats):
  - El xG hibrido smooth out la varianza de goles -> EMA mas estable
  - Hit rate deberia subir
  - xG bias deberia ser menos negativo (full stats mas precisos)

Uso:
  py analisis/walk_forward_full_stats.py --ligas Argentina,Brasil,Bolivia
"""
import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "analisis" / "cache_espn"
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "walk_forward_full_stats.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# === Constantes (fiel al motor) ===
ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
RANGO_POISSON = 10
EMA_INIT = 1.4

TEMPS_TRAIN = [2022, 2023]
TEMP_PREDICT = 2024


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


def xg_hibrido(sot, shots, corners, goles, beta_sot=BETA_SOT,
               beta_off=BETA_SHOTS_OFF, coef_c=0.02):
    shots_off = max(0, shots - sot)
    xg_calc = (sot * beta_sot) + (shots_off * beta_off) + (corners * coef_c)
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


def get_rho_y_corner(liga):
    con = sqlite3.connect(DB)
    r = con.execute("SELECT rho_calculado, coef_corner_calculado FROM ligas_stats WHERE liga = ?", (liga,)).fetchone()
    con.close()
    rho = r[0] if r else -0.09
    coef_c = r[1] if r and r[1] is not None else 0.02
    return rho, coef_c


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


def cargar_partidos_liga(liga, temps):
    """Carga partidos de cache_espn ordenados cronologicamente."""
    todos = []
    for t in temps:
        f = CACHE / f"{liga}_{t}.json"
        if not f.exists():
            print(f"   [WARN] cache no existe: {f.name}")
            continue
        partidos = json.loads(f.read_text(encoding="utf-8"))
        todos.extend(partidos)

    # Ordenar por fecha
    def parse_fecha(p):
        try:
            return datetime.fromisoformat(p["fecha"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            return datetime.min
    todos.sort(key=parse_fecha)
    return todos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default="Argentina,Brasil,Bolivia",
                    help="Comma-separated league names")
    args = ap.parse_args()
    ligas = [l.strip() for l in args.ligas.split(",")]

    print("=" * 70)
    print(f"Walk-forward FULL STATS (ESPN scraped) — adepor-bgt iter3")
    print(f"Train: {TEMPS_TRAIN}  Predict: {TEMP_PREDICT}")
    print(f"Ligas: {ligas}")
    print("=" * 70)

    out_per_liga = {}
    summary = []

    for liga in ligas:
        print(f"\n--- {liga} ---")
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            print("   [SKIP] sin data")
            continue

        # Filter zero-stats partidos (data faltante)
        partidos_validos = [p for p in partidos if not (p["hs"] == 0 and p["hst"] == 0 and p["hc"] == 0)]
        zero_ratio = (len(partidos) - len(partidos_validos)) / len(partidos) if partidos else 0
        print(f"   N={len(partidos)} ({len(partidos)-len(partidos_validos)} con stats=0, ratio {zero_ratio:.1%})")

        prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
        rho, coef_c = get_rho_y_corner(liga)
        print(f"   promedio_liga={prom:.3f} rho={rho:+.4f} coef_corner={coef_c:.4f}")

        estado = {}
        predicciones = []
        train_count = 0
        for p in partidos:
            try:
                year = datetime.fromisoformat(p["fecha"].replace("Z", "+00:00")).year
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

            # Update estado con xG hibrido (full stats)
            if p["hs"] == 0 and p["hst"] == 0:
                # Stats faltantes: usar goles directos
                xg_real_l = float(p["hg"])
                xg_real_v = float(p["ag"])
            else:
                xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c=coef_c)
                xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c=coef_c)
            actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
            actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)
            if not es_target:
                train_count += 1

        m = metricas(predicciones)
        if not m:
            print("   [SKIP] sin predicciones target")
            continue
        print(f"   N target={m['n']}, train warmup={train_count}")
        print(f"   hit_rate    = {m['hit_rate']:.4f}  (base_rate_local={m['base_rate_local']:.3f})")
        print(f"   brier_mean  = {m['brier_mean']:.4f}")
        print(f"   xg_bias L   = {m['xg_bias_local']:+.3f}  V = {m['xg_bias_visita']:+.3f}")
        print(f"   xg_MSE L    = {m['xg_mse_local']:.4f}  V = {m['xg_mse_visita']:.4f}")

        out_per_liga[liga] = {
            "config": {"rho": rho, "coef_corner": coef_c, "promedio_liga": round(prom, 4)},
            "metricas": m,
            "n_total_input": len(partidos),
            "n_zero_stats": len(partidos) - len(partidos_validos),
        }
        summary.append((liga, m))

    print(f"\n{'='*70}")
    print(f"RESUMEN ITER3 (FULL STATS, target {TEMP_PREDICT})")
    print(f"{'='*70}")
    print(f"{'Liga':<11} {'N':>4} {'Hit':>6} {'Base':>6}  {'Brier':>7} {'xG_bias_L':>10} {'xG_MSE_L':>10}")
    print("-" * 70)
    for liga, m in summary:
        print(f"{liga:<11} {m['n']:>4} {m['hit_rate']:>6.3f} {m['base_rate_local']:>6.3f}  "
              f"{m['brier_mean']:>7.4f} {m['xg_bias_local']:>+10.3f} {m['xg_mse_local']:>10.4f}")

    # Comparativa con iter2
    print(f"\n{'='*70}")
    print(f"COMPARATIVA ITER2 (goals-only) vs ITER3 (full stats)")
    print(f"{'='*70}")
    iter2_path = ROOT / "analisis" / "walk_forward_latam.json"
    if iter2_path.exists():
        iter2 = json.loads(iter2_path.read_text(encoding="utf-8"))["ligas"]
        print(f"{'Liga':<11} {'iter2 Hit':>10} {'iter3 Hit':>10}  {'delta':>7}  {'iter2 Brier':>12} {'iter3 Brier':>12}")
        for liga, m in summary:
            if liga in iter2:
                m2 = iter2[liga]["metricas"]
                d_hit = m["hit_rate"] - m2["hit_rate"]
                d_brier = m["brier_mean"] - m2["brier_mean"]
                print(f"{liga:<11} {m2['hit_rate']:>10.4f} {m['hit_rate']:>10.4f}  {d_hit:>+7.4f}  {m2['brier_mean']:>12.4f} {m['brier_mean']:>12.4f}")

    output = {
        "bead_id": "adepor-bgt",
        "iter": 3,
        "scope": "LATAM full stats (ESPN scraped via scraper_espn_historico.py)",
        "config_global": {
            "alfa_ema": ALFA_EMA, "n0_ancla": N0_ANCLA,
            "beta_sot": BETA_SOT, "beta_shots_off": BETA_SHOTS_OFF,
            "temps_train": TEMPS_TRAIN, "temp_predict": TEMP_PREDICT,
        },
        "ligas": out_per_liga,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

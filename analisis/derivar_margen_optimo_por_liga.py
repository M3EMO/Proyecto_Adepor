"""Deriva threshold optimo de margen_predictivo_1x2 POR LIGA.

Para cada liga, evalua thresholds [0.00, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.07, 0.10]
sobre el walk-forward (predicciones temp 2024).

Define optimo como:
  threshold que maximiza hit_rate manteniendo volume kept >= 50%
  (trade-off: no filtrar mas del 50% para preservar volumen)

OUT: muestra threshold optimo + comparativa contra:
  - Valor actual en config_motor_valores
  - Opcion A (global 0.05)
  - Opcion B (per-liga optimo)
  - Opcion C (FLOOR 0.05 sobre per-liga)
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
OUT = ROOT / "analisis" / "margen_optimo_por_liga.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Constantes idem motor
ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
RANGO_POISSON = 10
EMA_INIT = 1.4
TEMPS_TRAIN = [2022, 2023]
TEMP_PREDICT = 2024
THRESHOLDS = [0.000, 0.005, 0.010, 0.015, 0.020, 0.025, 0.030, 0.040, 0.050, 0.070, 0.100]


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


def xg_hibrido(sot, shots, corners, goles, coef_c):
    shots_off = max(0, shots - sot)
    xg_calc = (sot * BETA_SOT) + (shots_off * BETA_SHOTS_OFF) + (corners * coef_c)
    if xg_calc == 0 and goles > 0:
        return float(goles)
    return xg_calc * 0.70 + goles * 0.30


def init_estado():
    return {
        "fav_home": EMA_INIT, "con_home": EMA_INIT, "p_home": 0,
        "fav_away": EMA_INIT, "con_away": EMA_INIT, "p_away": 0,
    }


def actualizar_estado(estado, equipo, xg_f, xg_c, is_home, prom):
    if equipo not in estado:
        estado[equipo] = init_estado()
    e = estado[equipo]
    if is_home:
        ema_f = xg_f * ALFA_EMA + e["fav_home"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_home"] * (1 - ALFA_EMA)
        N = e["p_home"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_home"] = w_ema * ema_f + w_liga * prom
        e["con_home"] = w_ema * ema_c + w_liga * prom
        e["p_home"] += 1
    else:
        ema_f = xg_f * ALFA_EMA + e["fav_away"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_away"] * (1 - ALFA_EMA)
        N = e["p_away"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_away"] = w_ema * ema_f + w_liga * prom
        e["con_away"] = w_ema * ema_c + w_liga * prom
        e["p_away"] += 1


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
        if f.exists():
            partidos = json.loads(f.read_text(encoding="utf-8"))
            for p in partidos:
                p["temp"] = t
                fe = p.get("fecha", "")
                if isinstance(fe, str) and "T" in fe:
                    p["fecha"] = fe.replace("T", " ").replace("Z", "")
            todos.extend(partidos)
    if not todos:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        rows = cur.execute(
            """
            SELECT fecha, ht, at, hg, ag, hst, ast, hs, as_, hc, ac, temp
            FROM partidos_historico_externo
            WHERE liga = ? AND temp IN (2022, 2023, 2024) AND has_full_stats = 1
            ORDER BY fecha
            """, (liga,)
        ).fetchall()
        todos = [{
            "fecha": r[0], "ht": r[1], "at": r[2], "hg": r[3], "ag": r[4],
            "hst": r[5] or 0, "ast": r[6] or 0, "hs": r[7] or 0,
            "as": r[8] or 0, "hc": r[9] or 0, "ac": r[10] or 0,
            "temp": r[11],
        } for r in rows]
        con.close()
    if not todos:
        return []

    def parse_fecha(p):
        try:
            return datetime.fromisoformat(p["fecha"][:19].replace(" ", "T"))
        except (ValueError, KeyError):
            return datetime.min

    todos.sort(key=parse_fecha)
    return todos


def correr_liga(liga, partidos):
    rho, coef_c = get_rho_y_corner(liga)
    prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
    estado = {}
    preds = []
    for p in partidos:
        try:
            year = datetime.fromisoformat(p["fecha"][:19].replace(" ", "T")).year
        except (ValueError, KeyError):
            continue
        es_target = year == TEMP_PREDICT or p.get("temp") == TEMP_PREDICT

        if es_target:
            el = estado.get(p["ht"], init_estado())
            ev = estado.get(p["at"], init_estado())
            xg_l = (el["fav_home"] + ev["con_away"]) / 2.0
            xg_v = (ev["fav_away"] + el["con_home"]) / 2.0
            p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)
            sorted_probs = sorted([p1, px, p2], reverse=True)
            margen = sorted_probs[0] - sorted_probs[1]
            if p["hg"] > p["ag"]:
                outcome = "1"
            elif p["hg"] == p["ag"]:
                outcome = "X"
            else:
                outcome = "2"
            argmax = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
            hit = argmax == outcome
            preds.append({"margen": margen, "hit": hit, "outcome": outcome, "argmax": argmax})

        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        else:
            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

    return preds


def evaluar_thresholds(preds):
    n_total = len(preds)
    if n_total == 0:
        return None
    base_hit = sum(1 for p in preds if p["hit"]) / n_total
    rows = []
    for thr in THRESHOLDS:
        kept = [p for p in preds if p["margen"] >= thr]
        n_kept = len(kept)
        if n_kept == 0:
            rows.append({"threshold": thr, "n_kept": 0, "pct_kept": 0.0,
                         "hit_rate": None})
            continue
        hit = sum(1 for p in kept if p["hit"]) / n_kept
        rows.append({
            "threshold": thr, "n_kept": n_kept,
            "pct_kept": round(100 * n_kept / n_total, 1),
            "hit_rate": round(hit, 4),
            "delta_vs_base": round(hit - base_hit, 4),
        })
    # Optimo: max hit rate con pct_kept >= 50%
    candidatos = [r for r in rows if r["pct_kept"] >= 50 and r["hit_rate"] is not None]
    if candidatos:
        optimo = max(candidatos, key=lambda r: r["hit_rate"])
    else:
        optimo = max((r for r in rows if r["hit_rate"] is not None),
                     key=lambda r: r["hit_rate"])
    return {"n_total": n_total, "hit_base": round(base_hit, 4),
            "thresholds": rows, "optimo": optimo}


def cargar_margen_actual_por_liga():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    out = {}
    for r in cur.execute("""
        SELECT scope, valor_real FROM config_motor_valores
        WHERE clave='margen_predictivo_1x2'
    """):
        scope, val = r[0], float(r[1])
        out[scope] = val
    con.close()
    return out


def main():
    LIGAS = [
        "Inglaterra", "Italia", "Espana", "Francia", "Alemania", "Turquia",
        "Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
        "Ecuador", "Peru", "Uruguay", "Venezuela",
    ]
    margen_actual = cargar_margen_actual_por_liga()
    global_actual = margen_actual.get("global", 0.030)
    print(f"=== Threshold optimo de margen por liga ===\n")
    print(f"Definicion 'optimo': max hit_rate con pct_kept >= 50%\n")
    print(f"Global actual config: {global_actual:.4f}")
    print()

    print(f"{'Liga':<13} {'N_pred':>6} {'hit_base':>8} {'actual':>8} "
          f"{'opt_thr':>8} {'opt_hit':>8} {'kept':>6}  {'eval'}")
    print("-" * 100)

    out_per_liga = {}
    summary = []
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            print(f"{liga:<13} sin data")
            continue
        preds = correr_liga(liga, partidos)
        result = evaluar_thresholds(preds)
        if not result:
            continue
        opt = result["optimo"]
        actual = margen_actual.get(liga, global_actual)

        # ¿es 0.05 mejor o peor que el actual?
        actual_row = next((r for r in result["thresholds"]
                           if abs(r["threshold"] - actual) < 0.001), None)
        thr_005 = next(r for r in result["thresholds"] if r["threshold"] == 0.05)

        eval_str = ""
        if actual_row and actual_row["hit_rate"] is not None:
            d_005_vs_actual = thr_005["hit_rate"] - actual_row["hit_rate"]
            d_opt_vs_actual = opt["hit_rate"] - actual_row["hit_rate"]
            eval_str = f"d_005={d_005_vs_actual:+.3f}, d_opt={d_opt_vs_actual:+.3f}"

        print(f"{liga:<13} {result['n_total']:>6} {result['hit_base']:>8.4f} "
              f"{actual:>8.4f} {opt['threshold']:>8.3f} {opt['hit_rate']:>8.4f} "
              f"{opt['pct_kept']:>5.1f}%  {eval_str}")

        out_per_liga[liga] = {
            "n_total": result["n_total"],
            "hit_base": result["hit_base"],
            "margen_actual_config": actual,
            "actual_eval": actual_row,
            "thr_005_eval": thr_005,
            "optimo": opt,
            "todas_evaluaciones": result["thresholds"],
        }
        summary.append((liga, actual, opt, thr_005, actual_row))

    # Comparativa de las 3 opciones (proyectar al pool sin overlapping data)
    print()
    print("=" * 95)
    print("COMPARATIVA OPCIONES A/B/C (suma N por liga)")
    print("=" * 95)

    n_total = sum(s[3]["n_kept"] for s in summary if s[3]["hit_rate"] is not None)
    sums_actual = sum(s[4]["n_kept"] for s in summary if s[4] and s[4].get("hit_rate") is not None)
    if sums_actual > 0:
        hit_actual = sum(s[4]["n_kept"] * s[4]["hit_rate"] for s in summary
                         if s[4] and s[4].get("hit_rate") is not None) / sums_actual
        print(f"  Actual config (mix per-liga): N_kept={sums_actual}, hit={hit_actual:.4f}")
    else:
        hit_actual = None

    # Opcion A: default global 0.05, ligas con per-liga value mantienen
    n_a = 0
    hits_a = 0
    for liga, actual, opt, thr_005, actual_row in summary:
        if liga in margen_actual:  # tiene per-liga, no afecta
            row = actual_row
        else:
            row = thr_005  # default sube de 0.030 a 0.050
        if row and row.get("hit_rate") is not None:
            n_a += row["n_kept"]
            hits_a += int(round(row["n_kept"] * row["hit_rate"]))
    hit_a = hits_a / n_a if n_a > 0 else None
    print(f"  Opcion A (def 0.05, per-liga intacto): N_kept={n_a}, hit={hit_a:.4f}" if hit_a else f"  Opcion A: N=0")

    # Opcion B: per-liga optimo (cada liga su mejor threshold)
    n_b = 0
    hits_b = 0
    for liga, actual, opt, thr_005, _ in summary:
        if opt and opt.get("hit_rate") is not None:
            n_b += opt["n_kept"]
            hits_b += int(round(opt["n_kept"] * opt["hit_rate"]))
    hit_b = hits_b / n_b if n_b > 0 else None
    print(f"  Opcion B (per-liga optimo derivado):  N_kept={n_b}, hit={hit_b:.4f}" if hit_b else f"  Opcion B: N=0")

    # Opcion C: FLOOR max(per_liga, 0.05) — todas usan 0.05
    n_c = 0
    hits_c = 0
    for liga, actual, opt, thr_005, _ in summary:
        if thr_005 and thr_005.get("hit_rate") is not None:
            n_c += thr_005["n_kept"]
            hits_c += int(round(thr_005["n_kept"] * thr_005["hit_rate"]))
    hit_c = hits_c / n_c if n_c > 0 else None
    print(f"  Opcion C (FLOOR 0.05 todas):           N_kept={n_c}, hit={hit_c:.4f}" if hit_c else f"  Opcion C: N=0")

    print()
    print("=" * 95)
    print("RECOMENDACION ESPECIFICA POR LIGA (Opcion B detalle)")
    print("=" * 95)
    cambios = []
    sin_cambio = []
    for liga, actual, opt, thr_005, _ in summary:
        if opt and abs(opt["threshold"] - actual) > 0.005:
            cambios.append((liga, actual, opt["threshold"], opt["hit_rate"], opt["pct_kept"]))
        else:
            sin_cambio.append(liga)

    print(f"\nSugiere CAMBIAR ({len(cambios)} ligas):")
    for liga, actual, opt_thr, opt_hit, opt_kept in cambios:
        print(f"  {liga:<12} {actual:.3f} -> {opt_thr:.3f}  hit={opt_hit:.4f} kept={opt_kept:.1f}%")
    print(f"\nSugiere MANTENER ({len(sin_cambio)} ligas): {sin_cambio}")

    out_data = {
        "fecha": datetime.now().isoformat(),
        "global_actual": global_actual,
        "per_liga": out_per_liga,
        "comparativa_opciones": {
            "actual_mix": {"n": sums_actual, "hit": hit_actual},
            "opcion_A_default_005_per_liga_intacto": {"n": n_a, "hit": hit_a},
            "opcion_B_per_liga_optimo": {"n": n_b, "hit": hit_b},
            "opcion_C_floor_005": {"n": n_c, "hit": hit_c},
        },
    }
    OUT.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

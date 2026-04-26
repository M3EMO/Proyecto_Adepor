"""Walk-forward + analisis margen de decision.

Pregunta del user: si abstenemos cuando margen(top1, top2) < 5pp, ¿cómo
queda el hit_rate sobre los partidos donde sí se decide?

Replica el walk-forward (mismo core que walk_forward_full_stats.py + multiliga.py)
pero guarda CADA predicción con: p1, px, p2, outcome, hit, margen.

Después aplica thresholds de margen y reporta hit_rate filtrado.

Input: cache_espn/ + partidos_historico_externo (DB).
Output: walk_forward_con_margen.json
"""
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
CACHE = ROOT / "analisis" / "cache_espn"
OUT = ROOT / "analisis" / "walk_forward_con_margen.json"

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
    """Carga de cache_espn (LATAM) o DB partidos_historico_externo (EUR)."""
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
        # Fallback DB (EUR)
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
    predicciones = []
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
            argmax_pair = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])
            argmax = argmax_pair[0]
            hit = argmax == outcome
            predicciones.append({
                "p1": round(p1, 4), "px": round(px, 4), "p2": round(p2, 4),
                "argmax": argmax, "outcome": outcome, "hit": hit,
                "margen": round(margen, 4),
            })

        # Update estado
        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        else:
            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

    return predicciones


def analizar_thresholds(predicciones, thresholds=(0.00, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20)):
    n_total = len(predicciones)
    if n_total == 0:
        return {}
    base_hit = sum(1 for p in predicciones if p["hit"]) / n_total
    rows = []
    for thr in thresholds:
        kept = [p for p in predicciones if p["margen"] >= thr]
        n_kept = len(kept)
        if n_kept == 0:
            rows.append({"threshold": thr, "n_kept": 0, "pct_kept": 0,
                         "hit_rate": None, "delta_vs_base": None})
            continue
        hit_kept = sum(1 for p in kept if p["hit"]) / n_kept
        rows.append({
            "threshold": thr,
            "n_kept": n_kept,
            "pct_kept": round(100 * n_kept / n_total, 1),
            "hit_rate": round(hit_kept, 4),
            "delta_vs_base": round(hit_kept - base_hit, 4),
        })
    return {"n_total": n_total, "hit_rate_base": round(base_hit, 4), "thresholds": rows}


def main():
    LIGAS_EUR = ["Inglaterra", "Italia", "Espana", "Francia", "Alemania", "Turquia"]
    LIGAS_LATAM = ["Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
                   "Ecuador", "Peru", "Uruguay", "Venezuela"]
    LIGAS = LIGAS_EUR + LIGAS_LATAM

    print(f"=== Walk-forward con analisis de MARGEN de decision ===")
    print(f"Train: {TEMPS_TRAIN}  Predict: {TEMP_PREDICT}\n", flush=True)

    out = {}
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            print(f"  {liga}: sin datos")
            continue
        preds = correr_liga(liga, partidos)
        if not preds:
            continue
        analisis = analizar_thresholds(preds)
        out[liga] = analisis
        print(f"\n--- {liga} (N={analisis['n_total']}, hit_base={analisis['hit_rate_base']}) ---", flush=True)
        for r in analisis["thresholds"]:
            if r["hit_rate"] is None:
                print(f"  margen>={r['threshold']:.2f}: n=0")
                continue
            print(f"  margen>={r['threshold']:.2f}: n={r['n_kept']:>3} ({r['pct_kept']:>5.1f}%)  "
                  f"hit={r['hit_rate']:.4f}  Δ={r['delta_vs_base']:+.4f}", flush=True)

    # Pool global
    all_preds = []
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            continue
        preds = correr_liga(liga, partidos)
        for p in preds:
            p["liga"] = liga
        all_preds.extend(preds)

    print(f"\n=== POOL GLOBAL (N={len(all_preds)}) ===", flush=True)
    pool_analysis = analizar_thresholds(all_preds)
    out["__pool__"] = pool_analysis
    print(f"Hit_base = {pool_analysis['hit_rate_base']}")
    for r in pool_analysis["thresholds"]:
        if r["hit_rate"] is None:
            continue
        print(f"  margen>={r['threshold']:.2f}: n={r['n_kept']:>4} ({r['pct_kept']:>5.1f}%)  "
              f"hit={r['hit_rate']:.4f}  Δ={r['delta_vs_base']:+.4f}", flush=True)

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

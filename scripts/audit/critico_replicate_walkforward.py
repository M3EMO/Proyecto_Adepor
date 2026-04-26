"""Critico independent replication of walk_forward_con_margen + bootstrap CI.

Re-runs the SAME walk-forward logic, captures all predictions, computes:
  - Pool hit_base, hit_filtered_5pp, delta
  - Pool Brier_base, Brier_filtered_5pp, delta_brier (NUEVO: el Lead NO calculó esto)
  - Bootstrap CI 95% on delta_hit and delta_brier
  - Per-liga hit_base / hit_filtered_5pp para audit consistency
"""
import json
import math
import random
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "fondo_quant.db"
CACHE = ROOT / "analisis" / "cache_espn"
OUT = Path("/tmp/critico_audit_dx8.json")

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
            brier = (
                (p1 - (1.0 if outcome == "1" else 0.0)) ** 2
                + (px - (1.0 if outcome == "X" else 0.0)) ** 2
                + (p2 - (1.0 if outcome == "2" else 0.0)) ** 2
            )
            predicciones.append({
                "liga": liga, "p1": p1, "px": px, "p2": p2,
                "argmax": argmax, "outcome": outcome, "hit": int(hit),
                "margen": margen, "brier": brier,
            })

        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        else:
            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

    return predicciones


def main():
    LIGAS = ["Inglaterra", "Italia", "Espana", "Francia", "Alemania", "Turquia",
             "Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
             "Ecuador", "Peru", "Uruguay", "Venezuela"]

    all_preds = []
    per_liga = {}
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            continue
        preds = correr_liga(liga, partidos)
        all_preds.extend(preds)
        n = len(preds)
        if n == 0:
            continue
        hits_base = sum(p["hit"] for p in preds)
        brier_base = sum(p["brier"] for p in preds) / n
        kept = [p for p in preds if p["margen"] >= 0.05]
        n_k = len(kept)
        if n_k == 0:
            continue
        hits_k = sum(p["hit"] for p in kept)
        brier_k = sum(p["brier"] for p in kept) / n_k
        per_liga[liga] = {
            "n": n,
            "hit_base": hits_base / n,
            "brier_base": brier_base,
            "n_kept": n_k,
            "pct_kept": 100 * n_k / n,
            "hit_kept": hits_k / n_k,
            "brier_kept": brier_k,
            "delta_hit": (hits_k / n_k) - (hits_base / n),
            "delta_brier": brier_k - brier_base,
        }

    n_total = len(all_preds)
    hits_base = sum(p["hit"] for p in all_preds)
    brier_base = sum(p["brier"] for p in all_preds) / n_total

    kept_5 = [p for p in all_preds if p["margen"] >= 0.05]
    n_kept = len(kept_5)
    hits_kept = sum(p["hit"] for p in kept_5)
    brier_kept = sum(p["brier"] for p in kept_5) / n_kept

    print("=" * 80)
    print("CRITICO — INDEPENDENT REPLICATION (deterministic, no random seed needed)")
    print("=" * 80)
    print(f"N_total       = {n_total}")
    print(f"Hits base     = {hits_base}  hit_rate_base = {hits_base/n_total:.4f}")
    print(f"Brier_base    = {brier_base:.4f}")
    print()
    print(f"WITH FILTRO margen >= 0.05:")
    print(f"  N_kept     = {n_kept}  ({100*n_kept/n_total:.1f}%)")
    print(f"  Hits_kept  = {hits_kept}  hit_rate = {hits_kept/n_kept:.4f}")
    print(f"  Brier      = {brier_kept:.4f}")
    print()
    delta_hit = hits_kept/n_kept - hits_base/n_total
    delta_brier = brier_kept - brier_base
    print(f"DELTAS:")
    print(f"  delta_hit   = {delta_hit:+.4f} ({delta_hit*100:+.2f}pp)")
    print(f"  delta_brier = {delta_brier:+.4f}  (NEGATIVO = MEJORA)")
    print()

    # Bootstrap CI on delta_hit
    print("BOOTSTRAP CI 95% on delta_hit (5000 resamples):")
    random.seed(42)
    deltas_hit = []
    deltas_brier = []
    n_iters = 5000
    for it in range(n_iters):
        sample = [random.choice(all_preds) for _ in range(n_total)]
        h_base = sum(p["hit"] for p in sample) / n_total
        b_base = sum(p["brier"] for p in sample) / n_total
        kept_s = [p for p in sample if p["margen"] >= 0.05]
        if len(kept_s) < 100:
            continue
        h_kept = sum(p["hit"] for p in kept_s) / len(kept_s)
        b_kept = sum(p["brier"] for p in kept_s) / len(kept_s)
        deltas_hit.append(h_kept - h_base)
        deltas_brier.append(b_kept - b_base)
    deltas_hit.sort()
    deltas_brier.sort()
    print(f"  N bootstraps  = {len(deltas_hit)}")
    print(f"  delta_hit mean= {sum(deltas_hit)/len(deltas_hit):+.4f}")
    print(f"  CI 2.5%       = {deltas_hit[int(0.025*len(deltas_hit))]:+.4f}")
    print(f"  CI 97.5%      = {deltas_hit[int(0.975*len(deltas_hit))]:+.4f}")
    p_pos_hit = sum(1 for d in deltas_hit if d > 0) / len(deltas_hit)
    print(f"  P(delta>0)    = {p_pos_hit:.4f}")
    print()
    print(f"  delta_brier mean= {sum(deltas_brier)/len(deltas_brier):+.4f}")
    print(f"  CI 2.5%         = {deltas_brier[int(0.025*len(deltas_brier))]:+.4f}")
    print(f"  CI 97.5%        = {deltas_brier[int(0.975*len(deltas_brier))]:+.4f}")
    p_neg_brier = sum(1 for d in deltas_brier if d < 0) / len(deltas_brier)
    print(f"  P(delta<0)      = {p_neg_brier:.4f}  (NEGATIVO = MEJORA)")

    # Per-liga
    print()
    print("=" * 80)
    print("Per-liga (delta_hit, delta_brier)")
    print("=" * 80)
    for liga, m in sorted(per_liga.items(), key=lambda x: -x[1]["delta_hit"]):
        print(f"{liga:<13}  N={m['n']:>4}  hit_base={m['hit_base']:.4f}  hit_kept={m['hit_kept']:.4f}  "
              f"d_hit={m['delta_hit']:+.4f}  d_brier={m['delta_brier']:+.4f}  "
              f"kept={m['pct_kept']:.0f}%")

    # Save
    out = {
        "n_total": n_total,
        "hit_base": hits_base / n_total,
        "brier_base": brier_base,
        "n_kept": n_kept,
        "pct_kept": 100 * n_kept / n_total,
        "hit_kept": hits_kept / n_kept,
        "brier_kept": brier_kept,
        "delta_hit": delta_hit,
        "delta_brier": delta_brier,
        "bootstrap_ci_hit_low": deltas_hit[int(0.025*len(deltas_hit))],
        "bootstrap_ci_hit_high": deltas_hit[int(0.975*len(deltas_hit))],
        "p_delta_hit_positive": p_pos_hit,
        "bootstrap_ci_brier_low": deltas_brier[int(0.025*len(deltas_brier))],
        "bootstrap_ci_brier_high": deltas_brier[int(0.975*len(deltas_brier))],
        "p_delta_brier_negative": p_neg_brier,
        "per_liga": per_liga,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print()
    print(f"[OK] Output: {OUT}")


if __name__ == "__main__":
    main()

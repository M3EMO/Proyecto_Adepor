"""Fase 4 (C): score apostable compuesto basado en EMA stats pre-partido.

Score = combinación lineal ponderada de stats EMA del equipo local:
  score_local = +SoTs_norm + ShotPct_norm + Clearance_norm
                -Pos_norm -Crosses_norm -Pases_norm -Longball_pct_norm

Pesos derivados de Fase 3 (delta_g_pct global × signo: shots_on_target +30.97pp,
posesion -13.54pp, etc).

Validación:
  - Calcular score para cada partido OOS donde el motor apostó local
  - Ver si yield del motor correlaciona con score
  - Test buckets de score: top quintil vs bottom quintil del score

Output: analisis/fase4_score_validation.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT_DIR = Path(__file__).resolve().parent

# Pesos derivados de Fase 3 (ratio stat impact en yield):
# +30.97 sots, +28.54 shot_pct, +21.24 clearance,
# -20.53 crosses, -13.54 pos, -12.52 pases, -8.45 pass_pct (raro), -6.43 longball_pct
# Ya que pos/pases/crosses tienen el mismo signo (-) y altamente correlacionadas,
# reducir co-linealidad usando solo las top 3 + 3 pares.
PESOS = {
    # Positivos (alta = motor gana)
    "sots":      +1.0,
    "shot_pct":  +0.92,    # ratio 28.54/30.97
    "clearance": +0.69,    # ratio 21.24/30.97
    # Negativos (alta = motor pierde)
    "pos":       -0.44,    # ratio 13.54/30.97
    "crosses":   -0.66,    # ratio 20.53/30.97
    "pass_pct":  -0.27,    # ratio 8.45/30.97
}


def cargar_oos_con_emas(con):
    """OOS predicciones + EMA stats pre-partido del local + visita."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               -- EMA local pre-partido (snapshot anterior a fecha)
               (SELECT ema_l_sots FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_sots_l,
               (SELECT ema_l_shot_pct FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_shotpct_l,
               (SELECT ema_l_clearance FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_clearance_l,
               (SELECT ema_l_pos FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_pos_l,
               (SELECT ema_l_crosses FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_crosses_l,
               (SELECT ema_l_pass_pct FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS ema_passpct_l,
               (SELECT n_acum FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS n_acum_l
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def normalizar_stat(val, mean, std):
    """Z-score: si una stat es alta para la liga, val_norm > 0."""
    if val is None or std == 0:
        return 0.0
    return (val - mean) / std


def calcular_score(row, mu_std):
    """Aplica pesos a stats normalizadas. Devuelve None si faltan datos críticos."""
    if row.get("ema_sots_l") is None:
        return None
    score = 0.0
    for stat_key, peso in PESOS.items():
        col = f"ema_{stat_key}_l" if stat_key not in ("shot_pct", "pass_pct") else f"ema_{stat_key.replace('_pct', 'pct')}_l"
        # Manejar variantes
        if stat_key == "shot_pct":
            col = "ema_shotpct_l"
        elif stat_key == "pass_pct":
            col = "ema_passpct_l"
        elif stat_key == "pos":
            col = "ema_pos_l"
        else:
            col = f"ema_{stat_key}_l"
        val = row.get(col)
        if val is None:
            continue
        mu, std = mu_std.get(stat_key, (0, 1))
        if std == 0:
            continue
        score += peso * (val - mu) / std
    return score


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, 0.025))


def evaluar_oos(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05:
        return False, 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0
    if prob * cuota - 1 < 0.03:
        return False, 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0
    if label == outcome:
        return True, stake, stake*(cuota-1)
    return True, stake, -stake


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS con EMAs pre-partido...")
    rows = cargar_oos_con_emas(con)
    rows = [r for r in rows if r.get("ema_sots_l") is not None and r.get("n_acum_l", 0) >= 5]
    print(f"N OOS con EMA local pre-partido (n_acum>=5): {len(rows)}")

    # Calcular media + std de cada stat sobre la cohorte
    mu_std = {}
    for stat_key in PESOS:
        if stat_key == "shot_pct":
            col = "ema_shotpct_l"
        elif stat_key == "pass_pct":
            col = "ema_passpct_l"
        else:
            col = f"ema_{stat_key}_l"
        vals = [r.get(col) for r in rows if r.get(col) is not None]
        if not vals:
            mu_std[stat_key] = (0, 1)
            continue
        mu_std[stat_key] = (float(np.mean(vals)), float(np.std(vals)))
    print(f"Mu/std calculados sobre {len(rows)} OOS")
    for k, (mu, std) in mu_std.items():
        print(f"  {k:<12} mu={mu:>+8.2f}  std={std:>6.2f}")

    # Calcular score por partido
    print("\nCalculando scores...")
    for r in rows:
        r["score"] = calcular_score(r, mu_std)
    rows = [r for r in rows if r.get("score") is not None]
    scores = [r["score"] for r in rows]
    print(f"Score distribution: min={min(scores):.2f} max={max(scores):.2f} "
          f"mean={np.mean(scores):.2f} std={np.std(scores):.2f}")

    # Quintiles del score
    cuts = list(np.percentile(scores, [20, 40, 60, 80]))
    print(f"\n=== YIELD por quintil de score (con filtros M>=5%, EV>=3%, K=2.5%) ===")
    print(f"{'Quintil':<10} {'rango_score':<22} {'NPred':>5} {'NApost':>6} {'Hit%':>6} {'Yield%':>7}")
    payload = {"n_total": len(rows), "pesos": PESOS, "mu_std": mu_std,
                "score_cuts": cuts, "quintiles": {}}
    by_q = defaultdict(list)
    for r in rows:
        s = r["score"]
        if s <= cuts[0]: q = "Q1"
        elif s <= cuts[1]: q = "Q2"
        elif s <= cuts[2]: q = "Q3"
        elif s <= cuts[3]: q = "Q4"
        else: q = "Q5"
        by_q[q].append(r)
    for q in ["Q1","Q2","Q3","Q4","Q5"]:
        sub = by_q[q]
        if not sub:
            continue
        scores_q = [r["score"] for r in sub]
        rango = f"[{min(scores_q):>+5.2f}, {max(scores_q):>+5.2f}]"
        n_apost = 0; n_gano = 0; sum_stake = 0; sum_pl = 0
        for r in sub:
            ap, stk, prof = evaluar_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                                          r["psch"], r["pscd"], r["psca"], r["outcome"])
            if ap:
                n_apost += 1
                if prof > 0: n_gano += 1
                sum_stake += stk; sum_pl += prof
        yld = (sum_pl/sum_stake*100) if sum_stake > 0 else 0
        hit = (n_gano/n_apost*100) if n_apost > 0 else 0
        print(f"{q:<10} {rango:<22} {len(sub):>5} {n_apost:>6} {hit:>6.1f} {yld:>+7.1f}")
        payload["quintiles"][q] = {"n_pred": len(sub), "n_apost": n_apost,
                                     "n_gano": n_gano, "yield_pct": yld, "hit_pct": hit}

    # Validar: si Q5-Q1 muestra asimetría > 30pp, el score discrimina
    if "Q1" in payload["quintiles"] and "Q5" in payload["quintiles"]:
        q1y = payload["quintiles"]["Q1"]["yield_pct"]
        q5y = payload["quintiles"]["Q5"]["yield_pct"]
        delta = q5y - q1y
        print(f"\n=== ASIMETRIA Q5 - Q1: {delta:+.1f}pp ===")
        if delta > 30:
            print("  ✓ Score discrimina yield positivamente (Q5 mejor que Q1)")
        elif delta < -30:
            print("  ⚠ Score discrimina pero al revés (Q5 peor que Q1)")
        else:
            print("  Score no discrimina suficiente")

    out = OUT_DIR / "fase4_score_validation.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")

    # Tambien: por bucket de N_acum (para ver si EMA poca data es ruido)
    print(f"\n=== Yield por bucket de N_acum (madurez de EMA) ===")
    print(f"{'N_acum_bucket':<14} {'NApost':>6} {'Hit%':>6} {'Yield%':>7}")
    by_n = defaultdict(list)
    for r in rows:
        n = r.get("n_acum_l", 0)
        if n < 10: bucket = "<10"
        elif n < 30: bucket = "10-29"
        elif n < 60: bucket = "30-59"
        else: bucket = ">=60"
        by_n[bucket].append(r)
    for bucket in ["<10", "10-29", "30-59", ">=60"]:
        sub = by_n.get(bucket, [])
        if not sub:
            continue
        n_apost = 0; n_gano = 0; sum_stake = 0; sum_pl = 0
        for r in sub:
            ap, stk, prof = evaluar_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                                          r["psch"], r["pscd"], r["psca"], r["outcome"])
            if ap:
                n_apost += 1
                if prof > 0: n_gano += 1
                sum_stake += stk; sum_pl += prof
        yld = (sum_pl/sum_stake*100) if sum_stake > 0 else 0
        hit = (n_gano/n_apost*100) if n_apost > 0 else 0
        print(f"{bucket:<14} {n_apost:>6} {hit:>6.1f} {yld:>+7.1f}")

    con.close()


if __name__ == "__main__":
    main()

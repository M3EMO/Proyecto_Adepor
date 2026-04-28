"""Fase 3 (parte 3): yield del motor por bucket de cada stat (no solo posesion).

Para cada stat top: dividir en quintiles (Q1-Q5) y calcular yield por bucket.
Identificar stats con asimetria mas fuerte (Q1 vs Q5).
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

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025

# Stats a evaluar (h_key local, label)
STATS_LOCAL = [
    ("h_pos", "posesion"), ("h_passes", "pases_total"),
    ("h_pass_pct", "pass_pct"), ("h_crosses", "crosses_total"),
    ("h_cross_pct", "cross_pct"), ("h_longballs", "longballs_total"),
    ("h_longball_pct", "longball_pct"), ("hs", "shots_total"),
    ("hst", "shots_on_target"), ("h_shot_pct", "shot_pct"),
    ("h_blocks", "blocks"), ("hc", "corners"),
    ("h_fouls", "fouls"), ("h_yellow", "yellow"),
    ("h_red", "red"), ("h_offsides", "offsides"),
    ("h_saves", "saves"), ("h_tackles", "tackles"),
    ("h_tackle_pct", "tackle_pct"), ("h_interceptions", "interceptions"),
    ("h_clearance", "clearance"),
]


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < MARGEN_MIN:
        return False, 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0
    if prob * cuota - 1 < EV_MIN:
        return False, 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0
    if label == outcome:
        return True, stake, stake*(cuota-1)
    return True, stake, -stake


def bootstrap_yield(per_partido, B=1500, seed=42):
    if not per_partido:
        return None
    n = len(per_partido)
    rng = np.random.default_rng(seed)
    stakes = np.array([p[0] for p in per_partido])
    pls = np.array([p[1] for p in per_partido])
    ys = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        s = stakes[idx].sum()
        p = pls[idx].sum()
        ys[b] = (p/s*100) if s > 0 else 0
    return float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))


def agg_subset(rows):
    n_apost = 0
    n_gano = 0
    sum_stake = 0
    sum_pl = 0
    per_partido = []
    for r in rows:
        ap, stk, prof = evaluar(r["p1"], r["px"], r["p2"],
                                  r["c1"], r["cx"], r["c2"], r["outcome"])
        if ap:
            n_apost += 1
            if prof > 0:
                n_gano += 1
            sum_stake += stk
            sum_pl += prof
            per_partido.append((stk, prof))
    if not per_partido:
        return None
    return {
        "n": len(rows), "n_apost": n_apost, "n_gano": n_gano,
        "yield_pct": (sum_pl/sum_stake*100) if sum_stake > 0 else 0,
        "hit_pct": (n_gano/n_apost*100) if n_apost > 0 else 0,
        "per_partido": per_partido,
    }


def cargar(con):
    """JOIN OOS predicciones con stats para tener todas las stats home/away."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               s.h_pos, s.a_pos, s.h_passes, s.a_passes, s.h_pass_pct, s.a_pass_pct,
               s.h_crosses, s.a_crosses, s.h_cross_pct, s.a_cross_pct,
               s.h_longballs, s.a_longballs, s.h_longball_pct, s.a_longball_pct,
               s.hs, s.as_v, s.hst, s.ast, s.h_shot_pct, s.a_shot_pct,
               s.h_blocks, s.a_blocks, s.hc, s.ac,
               s.h_fouls, s.a_fouls, s.h_yellow, s.a_yellow, s.h_red, s.a_red,
               s.h_offsides, s.a_offsides, s.h_saves, s.a_saves,
               s.h_tackles, s.a_tackles, s.h_tackle_pct, s.a_tackle_pct,
               s.h_interceptions, s.a_interceptions, s.h_clearance, s.a_clearance
        FROM predicciones_oos_con_features p
        JOIN stats_partido_espn s
          ON p.liga = s.liga AND p.fecha = s.fecha
         AND p.local = s.ht AND p.visita = s.at
        WHERE s.h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        # alias para evaluar()
        d["p1"] = d["prob_1"]; d["px"] = d["prob_x"]; d["p2"] = d["prob_2"]
        d["c1"] = d["psch"]; d["cx"] = d["pscd"]; d["c2"] = d["psca"]
        out.append(d)
    return out


def main():
    con = sqlite3.connect(DB)
    rows = cargar(con)
    print(f"=== FASE 3 yield por bucket de stat (cada stat individualmente) ===")
    print(f"N OOS con stats completas: {len(rows)}")
    if len(rows) < 100:
        print("[FATAL] N insuficiente.")
        return

    payload = {"n_total": len(rows), "stats_yield": {}}

    print(f"\n{'Stat':<22} {'Q1':>8} {'Q2':>8} {'Q3':>8} {'Q4':>8} {'Q5':>8} {'Q5-Q1':>8}")
    for h_key, label in STATS_LOCAL:
        vals = [r[h_key] for r in rows if r.get(h_key) is not None]
        if len(vals) < 50:
            continue
        # Quintiles
        cuts = np.percentile(vals, [20, 40, 60, 80])
        # Asignar a bucket
        buckets = defaultdict(list)
        for r in rows:
            v = r.get(h_key)
            if v is None:
                continue
            if v <= cuts[0]: b = "Q1"
            elif v <= cuts[1]: b = "Q2"
            elif v <= cuts[2]: b = "Q3"
            elif v <= cuts[3]: b = "Q4"
            else: b = "Q5"
            buckets[b].append(r)
        cell_yields = {}
        cells_str = []
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            sub = buckets.get(q, [])
            m = agg_subset(sub)
            if m and m["n_apost"] >= 10:
                ci = bootstrap_yield(m["per_partido"]) or (None, None)
                sig = "+" if ci[0] is not None and ci[0] > 0 else ("-" if ci[1] is not None and ci[1] < 0 else "0")
                cells_str.append(f"{m['yield_pct']:>+7.1f}{sig if sig != '0' else ' '}")
                cell_yields[q] = {
                    "n_apost": m["n_apost"], "hit_pct": m["hit_pct"],
                    "yield_pct": m["yield_pct"], "ci95_lo": ci[0], "ci95_hi": ci[1],
                    "sig": sig,
                }
            else:
                cells_str.append(f"{('n=' + str(m['n_apost'] if m else 0)):>8}")
                cell_yields[q] = {"n_apost": m["n_apost"] if m else 0, "yield_pct": None}
        # Asimetria Q5 - Q1
        y_q1 = cell_yields["Q1"].get("yield_pct")
        y_q5 = cell_yields["Q5"].get("yield_pct")
        if y_q1 is not None and y_q5 is not None:
            asim = y_q5 - y_q1
            asim_str = f"{asim:>+7.1f}"
        else:
            asim_str = "      -"
        print(f"{label:<22} {cells_str[0]} {cells_str[1]} {cells_str[2]} {cells_str[3]} {cells_str[4]} {asim_str}")
        payload["stats_yield"][label] = {
            "h_key": h_key, "cuts_quintiles": list(cuts),
            "buckets": cell_yields, "asimetria_q5_q1": asim if y_q1 is not None and y_q5 is not None else None,
        }

    out = OUT_DIR / "fase3_yield_por_stats.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")

    # === RANKING DE ASIMETRIA ===
    print(f"\n=== RANKING DE STATS POR ASIMETRIA Q5 - Q1 ===")
    ranked = [(lbl, d["asimetria_q5_q1"]) for lbl, d in payload["stats_yield"].items()
              if d.get("asimetria_q5_q1") is not None]
    ranked.sort(key=lambda x: -abs(x[1]))
    print(f"{'Stat':<22} {'Q5-Q1':>10}  {'Interpretacion'}")
    for lbl, asim in ranked[:15]:
        if asim > 50:
            interp = "Q5 mucho mejor que Q1 (apostar locales con stat alta)"
        elif asim > 20:
            interp = "Q5 mejor que Q1"
        elif asim < -50:
            interp = "Q5 mucho peor que Q1 (NO apostar con stat alta)"
        elif asim < -20:
            interp = "Q5 peor que Q1"
        else:
            interp = "casi simetrico"
        print(f"{lbl:<22} {asim:>+10.2f}  {interp}")

    con.close()


if __name__ == "__main__":
    main()

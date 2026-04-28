"""Fase 3: yield x CADA stat x bin (4/8/12) x temp.

Para cada stat individual:
  - buckets quintiles Q1-Q5
  - cross con momento_bin (4/8/12)
  - drill-down por temp (OOS) / agregado in-sample
  - identifica si delta_yield(Q5-Q1) cambia segun altura de temp

Output:
  analisis/fase3_yield_x_stats_x_bin{4,8,12}_oos.json
  analisis/fase3_yield_x_stats_x_bin{4,8,12}_insample.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT_DIR = Path(__file__).resolve().parent

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025

STATS_LOCAL = [
    ("h_pos", "posesion"),
    ("h_passes", "pases_total"),
    ("h_pass_pct", "pass_pct"),
    ("h_crosses", "crosses_total"),
    ("h_cross_pct", "cross_pct"),
    ("h_longballs", "longballs_total"),
    ("h_longball_pct", "longball_pct"),
    ("hs", "shots_total"),
    ("hst", "shots_on_target"),
    ("h_shot_pct", "shot_pct"),
    ("h_blocks", "blocks"),
    ("hc", "corners"),
    ("h_fouls", "fouls"),
    ("h_yellow", "yellow"),
    ("h_red", "red"),
    ("h_offsides", "offsides"),
    ("h_saves", "saves"),
    ("h_tackles", "tackles"),
    ("h_tackle_pct", "tackle_pct"),
    ("h_interceptions", "interceptions"),
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


def agg_oos(rows):
    n_apost = 0; n_gano = 0; sum_stake = 0; sum_pl = 0
    for r in rows:
        ap, stk, prof = evaluar(r["p1"], r["px"], r["p2"],
                                  r["c1"], r["cx"], r["c2"], r["outcome"])
        if ap:
            n_apost += 1
            if prof > 0: n_gano += 1
            sum_stake += stk; sum_pl += prof
    if n_apost == 0:
        return None
    return {
        "n_pred": len(rows), "n_apost": n_apost, "n_gano": n_gano,
        "yield_pct": (sum_pl/sum_stake*100) if sum_stake > 0 else 0,
        "hit_pct": (n_gano/n_apost*100),
    }


def agg_insample_unit(picks_sub):
    """Yield unitario sobre picks reales del Excel."""
    n = len(picks_sub)
    if n == 0:
        return None
    n_g = sum(1 for p in picks_sub if p["resultado"] == "GANADA")
    pls = [(p["cuota"]-1) if p["resultado"] == "GANADA" else -1.0 for p in picks_sub]
    return {"n": n, "n_gano": n_g, "hit_pct": n_g/n*100,
            "yield_pct": sum(pls)/n*100}


def cargar_oos(con):
    """JOIN predicciones_oos_con_features + stats_partido_espn (todas las stats h_*)."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4, p.momento_octavo, p.momento_bin_12,
               s.h_pos, s.h_passes, s.h_pass_pct, s.h_crosses, s.h_cross_pct,
               s.h_longballs, s.h_longball_pct, s.hs, s.hst, s.h_shot_pct,
               s.h_blocks, s.hc, s.h_fouls, s.h_yellow, s.h_red, s.h_offsides,
               s.h_saves, s.h_tackles, s.h_tackle_pct, s.h_interceptions, s.h_clearance
        FROM predicciones_oos_con_features p
        JOIN stats_partido_espn s
          ON p.liga = s.liga AND p.fecha = s.fecha
         AND p.local = s.ht AND p.visita = s.at
        WHERE s.h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    stat_cols = [c for c in cols if c.startswith("h_") or c in ("hs","hst","hc")]
    for r in rows:
        d = dict(zip(cols, r))
        d["p1"] = d["prob_1"]; d["px"] = d["prob_x"]; d["p2"] = d["prob_2"]
        d["c1"] = d["psch"]; d["cx"] = d["pscd"]; d["c2"] = d["psca"]
        d["bin_4"] = d["momento_bin_4"]; d["bin_8"] = d["momento_octavo"]
        d["bin_12"] = d["momento_bin_12"]
        out.append(d)
    return out


def cargar_insample(con):
    """Carga picks Excel + JOIN partidos_con_features + stats_partido_espn."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    cur = con.cursor()
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        try:
            fecha = datetime.strptime(str(row[0]), "%d/%m/%Y").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if row[7] not in ("GANADA", "PERDIDA"):
            continue
        partido = row[1]
        if not partido or " vs " not in partido:
            continue
        local, visita = partido.split(" vs ", 1)
        liga = row[2]
        # JOIN con stats ESPN
        s = cur.execute("""
            SELECT h_pos, h_passes, h_pass_pct, h_crosses, h_cross_pct,
                   h_longballs, h_longball_pct, hs, hst, h_shot_pct,
                   h_blocks, hc, h_fouls, h_yellow, h_red, h_offsides,
                   h_saves, h_tackles, h_tackle_pct, h_interceptions, h_clearance
            FROM stats_partido_espn
            WHERE liga=? AND fecha=? AND ht=? AND at=?
        """, (liga, fecha, local, visita)).fetchone()
        # JOIN momento_bin
        mt = cur.execute("""
            SELECT bin_4, bin_8, bin_12, pct_temp
            FROM momento_temporada
            WHERE liga=? AND fecha=?
        """, (liga, fecha)).fetchone()
        if not s or not s[0] is not None:
            continue
        if not mt:
            continue
        d = {
            "fecha": fecha, "liga": liga, "local": local, "visita": visita,
            "pick": row[3], "cuota": row[4] or 0, "camino": row[5],
            "resultado": row[7], "stake": row[8] or 0, "pl": row[9] or 0,
            "h_pos": s[0], "h_passes": s[1], "h_pass_pct": s[2],
            "h_crosses": s[3], "h_cross_pct": s[4],
            "h_longballs": s[5], "h_longball_pct": s[6],
            "hs": s[7], "hst": s[8], "h_shot_pct": s[9],
            "h_blocks": s[10], "hc": s[11], "h_fouls": s[12],
            "h_yellow": s[13], "h_red": s[14], "h_offsides": s[15],
            "h_saves": s[16], "h_tackles": s[17], "h_tackle_pct": s[18],
            "h_interceptions": s[19], "h_clearance": s[20],
            "bin_4": mt[0], "bin_8": mt[1], "bin_12": mt[2], "pct_temp": mt[3],
        }
        picks.append(d)
    return picks


def analizar_oos_stat_x_bin(rows, h_key, label, n_bins):
    """Para una stat: 5 quintiles del valor + matriz bin temporal x quintil."""
    bin_key = f"bin_{n_bins}"
    vals = [r[h_key] for r in rows if r.get(h_key) is not None and r.get(bin_key) is not None]
    if len(vals) < 50:
        return None
    cuts = list(np.percentile(vals, [20, 40, 60, 80]))
    out = {"label": label, "h_key": h_key, "n_bins": n_bins,
            "cuts_quintiles": cuts, "n_obs": len(vals),
            "agregado_quintiles": {}, "cross_bin_x_quintil": {}}
    # Funcion bucket
    def quint(v):
        if v <= cuts[0]: return "Q1"
        elif v <= cuts[1]: return "Q2"
        elif v <= cuts[2]: return "Q3"
        elif v <= cuts[3]: return "Q4"
        return "Q5"

    # Agregado por quintil
    by_q = defaultdict(list)
    for r in rows:
        v = r.get(h_key)
        b = r.get(bin_key)
        if v is None or b is None:
            continue
        q = quint(v)
        by_q[q].append(r)
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        m = agg_oos(by_q.get(q, []))
        if m and m["n_apost"] >= 10:
            out["agregado_quintiles"][q] = m

    # Cross bin x quintil
    cross = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = r.get(h_key)
        b = r.get(bin_key)
        if v is None or b is None:
            continue
        cross[b][quint(v)].append(r)
    for b in sorted(cross.keys()):
        cell_data = {}
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            sub = cross[b].get(q, [])
            m = agg_oos(sub) if sub else None
            if m and m["n_apost"] >= 5:
                cell_data[q] = {
                    "n_apost": m["n_apost"], "yield_pct": m["yield_pct"],
                    "hit_pct": m["hit_pct"]
                }
            else:
                cell_data[q] = {"n_apost": m["n_apost"] if m else 0, "yield_pct": None}
        out["cross_bin_x_quintil"][f"bin{b+1}"] = cell_data

    return out


def analizar_insample_stat_x_bin(picks, h_key, label, n_bins):
    """Mismo pero para in-sample (yield unitario)."""
    bin_key = f"bin_{n_bins}"
    vals = [p[h_key] for p in picks if p.get(h_key) is not None and p.get(bin_key) is not None]
    if len(vals) < 20:
        return None
    cuts = list(np.percentile(vals, [20, 40, 60, 80]))
    out = {"label": label, "h_key": h_key, "n_bins": n_bins,
            "cuts_quintiles": cuts, "n_obs": len(vals),
            "agregado_quintiles": {}, "cross_bin_x_quintil": {}}
    def quint(v):
        if v <= cuts[0]: return "Q1"
        elif v <= cuts[1]: return "Q2"
        elif v <= cuts[2]: return "Q3"
        elif v <= cuts[3]: return "Q4"
        return "Q5"

    by_q = defaultdict(list)
    for p in picks:
        v = p.get(h_key); b = p.get(bin_key)
        if v is None or b is None:
            continue
        by_q[quint(v)].append(p)
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        m = agg_insample_unit(by_q.get(q, []))
        if m and m["n"] >= 5:
            out["agregado_quintiles"][q] = m

    cross = defaultdict(lambda: defaultdict(list))
    for p in picks:
        v = p.get(h_key); b = p.get(bin_key)
        if v is None or b is None:
            continue
        cross[b][quint(v)].append(p)
    for b in sorted(cross.keys()):
        cell_data = {}
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            sub = cross[b].get(q, [])
            m = agg_insample_unit(sub) if sub else None
            if m and m["n"] >= 3:
                cell_data[q] = {"n": m["n"], "yield_pct": m["yield_pct"],
                                  "hit_pct": m["hit_pct"]}
            else:
                cell_data[q] = {"n": m["n"] if m else 0, "yield_pct": None}
        out["cross_bin_x_quintil"][f"bin{b+1}"] = cell_data

    return out


def main():
    con = sqlite3.connect(DB)
    print("=== Cargando data ===")
    rows_oos = cargar_oos(con)
    print(f"OOS rows: {len(rows_oos)}")
    picks_in = cargar_insample(con)
    print(f"In-sample picks con stats + bin: {len(picks_in)}")

    for nb in (4, 8, 12):
        print(f"\n=== bin{nb} OOS ===")
        payload_oos = {"n_total": len(rows_oos), "n_bins": nb, "stats": {}}
        for h_key, label in STATS_LOCAL:
            r = analizar_oos_stat_x_bin(rows_oos, h_key, label, nb)
            if r:
                payload_oos["stats"][label] = r
                # Print Q1 vs Q5 con asimetria
                ag = r["agregado_quintiles"]
                q1y = ag.get("Q1", {}).get("yield_pct")
                q5y = ag.get("Q5", {}).get("yield_pct")
                if q1y is not None and q5y is not None:
                    asim = q5y - q1y
                    print(f"  {label:<22} Q1={q1y:>+7.1f}  Q5={q5y:>+7.1f}  asim={asim:>+7.1f}")
        out = OUT_DIR / f"fase3_yield_x_stats_x_bin{nb}_oos.json"
        out.write_text(json.dumps(payload_oos, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"  [OK] {out}")

        print(f"\n=== bin{nb} IN-SAMPLE ===")
        payload_in = {"n_total": len(picks_in), "n_bins": nb, "stats": {}}
        for h_key, label in STATS_LOCAL:
            r = analizar_insample_stat_x_bin(picks_in, h_key, label, nb)
            if r:
                payload_in["stats"][label] = r
                ag = r["agregado_quintiles"]
                q1y = ag.get("Q1", {}).get("yield_pct")
                q5y = ag.get("Q5", {}).get("yield_pct")
                if q1y is not None and q5y is not None:
                    asim = q5y - q1y
                    print(f"  {label:<22} Q1={q1y:>+7.1f}  Q5={q5y:>+7.1f}  asim={asim:>+7.1f}")
        out = OUT_DIR / f"fase3_yield_x_stats_x_bin{nb}_insample.json"
        out.write_text(json.dumps(payload_in, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"  [OK] {out}")

    con.close()


if __name__ == "__main__":
    main()

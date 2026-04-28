"""Fase 3: stats discriminantes G vs P por (liga, equipo, bin) en bin4/bin8/bin12.

Pregunta: ¿el patron de stat-discriminante cambia segun altura de temporada?
Para cada (liga, bin): top stats discriminantes.
Para cada (liga, temp, bin): drill-down.
Tambien per equipo si N permite.

Output: analisis/fase3_stats_por_equipo_bin{4,8,12}.json
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

STATS = [
    ("h_pos", "a_pos", "posesion"),
    ("h_passes", "a_passes", "pases_total"),
    ("h_pass_pct", "a_pass_pct", "pass_pct"),
    ("h_crosses", "a_crosses", "crosses_total"),
    ("h_cross_pct", "a_cross_pct", "cross_pct"),
    ("h_longballs", "a_longballs", "longballs_total"),
    ("h_longball_pct", "a_longball_pct", "longball_pct"),
    ("hs", "as_v", "shots_total"),
    ("hst", "ast", "shots_on_target"),
    ("h_shot_pct", "a_shot_pct", "shot_pct"),
    ("h_blocks", "a_blocks", "blocks"),
    ("hc", "ac", "corners"),
    ("h_pk_goals", "a_pk_goals", "pk_goals"),
    ("h_pk_shots", "a_pk_shots", "pk_shots"),
    ("h_fouls", "a_fouls", "fouls"),
    ("h_yellow", "a_yellow", "yellow"),
    ("h_red", "a_red", "red"),
    ("h_offsides", "a_offsides", "offsides"),
    ("h_saves", "a_saves", "saves"),
    ("h_tackles", "a_tackles", "tackles"),
    ("h_tackle_pct", "a_tackle_pct", "tackle_pct"),
    ("h_interceptions", "a_interceptions", "interceptions"),
    ("h_clearance", "a_clearance", "clearance"),
]


def cargar_obs_con_bin(con, n_bins):
    """JOIN stats_partido_espn con momento_temporada para tener bin."""
    bin_col = f"mt.bin_{n_bins}" if n_bins != 8 else "mt.bin_8"
    cur = con.cursor()
    rows = cur.execute(f"""
        SELECT s.*, {bin_col} AS bin_idx
        FROM stats_partido_espn s
        JOIN momento_temporada mt
          ON s.liga = mt.liga AND s.temp = mt.temp AND s.fecha = mt.fecha
        WHERE s.h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    obs = []
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("hg") is None or d.get("ag") is None or d.get("bin_idx") is None:
            continue
        if d["hg"] > d["ag"]:
            out_l, out_v = "G", "P"
        elif d["hg"] == d["ag"]:
            out_l, out_v = "E", "E"
        else:
            out_l, out_v = "P", "G"
        stats_l = {label: d.get(h) for h, _, label in STATS}
        stats_v = {label: d.get(a) for _, a, label in STATS}
        obs.append({"liga": d["liga"], "temp": d["temp"], "equipo": d["ht"],
                     "bin": int(d["bin_idx"]), "outcome": out_l, "stats": stats_l})
        obs.append({"liga": d["liga"], "temp": d["temp"], "equipo": d["at"],
                     "bin": int(d["bin_idx"]), "outcome": out_v, "stats": stats_v})
    return obs


def t_stat(grupo_a, grupo_b):
    if len(grupo_a) < 5 or len(grupo_b) < 5:
        return None
    a = np.array(grupo_a, dtype=float); a = a[~np.isnan(a)]
    b = np.array(grupo_b, dtype=float); b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return None
    se_a = a.var(ddof=1) / len(a) if len(a) > 1 else 0
    se_b = b.var(ddof=1) / len(b) if len(b) > 1 else 0
    se = np.sqrt(se_a + se_b)
    if se == 0:
        return None
    return float((a.mean() - b.mean()) / se)


def analizar(obs):
    g = [o for o in obs if o["outcome"] == "G"]
    p = [o for o in obs if o["outcome"] == "P"]
    if len(g) < 5 or len(p) < 5:
        return None
    out = {"n_g": len(g), "n_p": len(p), "stats": {}}
    for _, _, stat in STATS:
        vg = [o["stats"].get(stat) for o in g if o["stats"].get(stat) is not None]
        vp = [o["stats"].get(stat) for o in p if o["stats"].get(stat) is not None]
        if len(vg) < 5 or len(vp) < 5:
            continue
        ts = t_stat(vg, vp)
        if ts is None:
            continue
        out["stats"][stat] = {
            "mean_g": float(np.mean(vg)), "mean_p": float(np.mean(vp)),
            "diff": float(np.mean(vg) - np.mean(vp)),
            "n_g": len(vg), "n_p": len(vp), "t_stat": ts,
        }
    return out


def run(n_bins, out_path):
    con = sqlite3.connect(DB)
    obs = cargar_obs_con_bin(con, n_bins)
    print(f"\n{'='*70}")
    print(f"=== FASE 3 stats por equipo x BIN{n_bins} ===")
    print(f"{'='*70}")
    print(f"N obs: {len(obs)}")
    payload = {"n_obs": len(obs), "n_bins": n_bins}

    bin_letter = {4: "Q", 8: "O", 12: "D"}.get(n_bins, "B")

    # === 1. Por (liga, bin) ===
    print(f"\n=== Por (liga, {bin_letter}_bin) — top 3 stats discriminantes ===")
    payload["por_liga_bin"] = {}
    por_lb = defaultdict(list)
    for o in obs:
        por_lb[(o["liga"], o["bin"])].append(o)
    print(f"  {'Liga':<14} {'Bin':<5} {'NG':>4} {'NP':>4} {'Top stats (t-stat)'}")
    for liga in sorted({k[0] for k in por_lb.keys()}):
        for b in range(n_bins):
            sub = por_lb.get((liga, b), [])
            if len(sub) < 30:
                continue
            g = analizar(sub)
            if not g:
                continue
            top = sorted(g["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"]))[:3]
            top_str = ", ".join(f"{s}({info['t_stat']:+.1f})" for s, info in top)
            print(f"  {liga:<14} {bin_letter}{b+1:<4} {g['n_g']:>4} {g['n_p']:>4} {top_str}")
            payload["por_liga_bin"][f"{liga}_{bin_letter}{b+1}"] = g

    # === 2. Por (liga, bin) — DELTA t-stat entre primer y ultimo bin ===
    print(f"\n=== DELTA discriminacion: bin1 vs bin{n_bins} (cambia el patron?) ===")
    print(f"  {'Liga':<14} {'Stat':<22} {'t bin1':>7} {'t bin'+str(n_bins):>7} {'delta':>8}")
    payload["delta_bin1_binN"] = {}
    for liga in sorted({k[0] for k in por_lb.keys()}):
        sub_first = por_lb.get((liga, 0), [])
        sub_last = por_lb.get((liga, n_bins - 1), [])
        if len(sub_first) < 30 or len(sub_last) < 30:
            continue
        g_first = analizar(sub_first)
        g_last = analizar(sub_last)
        if not g_first or not g_last:
            continue
        # Para cada stat, calcular delta t
        deltas = {}
        for stat in g_first["stats"]:
            if stat in g_last["stats"]:
                t1 = g_first["stats"][stat]["t_stat"]
                t2 = g_last["stats"][stat]["t_stat"]
                deltas[stat] = {"t_first": t1, "t_last": t2, "delta": t2 - t1}
        # Top 3 con mayor |delta|
        top_deltas = sorted(deltas.items(), key=lambda kv: -abs(kv[1]["delta"]))[:3]
        for stat, d in top_deltas:
            delta_s = f"{d['delta']:>+8.2f}"
            print(f"  {liga:<14} {stat:<22} {d['t_first']:>+7.2f} {d['t_last']:>+7.2f} {delta_s}")
        payload["delta_bin1_binN"][liga] = dict(top_deltas)

    # === 3. Por (liga, temp, bin) — solo top 1 stat ===
    print(f"\n=== Por (liga, temp, bin) — top 1 stat por celda con N>=20 G y >=20 P ===")
    payload["por_liga_temp_bin"] = {}
    por_ltb = defaultdict(list)
    for o in obs:
        por_ltb[(o["liga"], o["temp"], o["bin"])].append(o)
    # Tabla: liga × temp con top stat por bin
    n_celdas_validas = 0
    for liga in sorted({k[0] for k in por_ltb.keys()}):
        for temp in sorted({k[1] for k in por_ltb.keys() if k[0] == liga}):
            row = []
            for b in range(n_bins):
                sub = por_ltb.get((liga, temp, b), [])
                if len(sub) < 30:
                    row.append("-")
                    continue
                g = analizar(sub)
                if not g or not g["stats"]:
                    row.append("-")
                    continue
                top = sorted(g["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"]))[0]
                stat, info = top
                row.append(f"{stat[:8]}({info['t_stat']:+.1f})")
                payload["por_liga_temp_bin"][f"{liga}_{temp}_{bin_letter}{b+1}"] = g
                n_celdas_validas += 1
            if any(c != "-" for c in row):
                print(f"  {liga:<14} {temp} | {' | '.join(row)}")
    print(f"\n  Total celdas validas: {n_celdas_validas} de {len(payload['por_liga_temp_bin'])}")

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out_path}")
    con.close()


def main():
    for nb in (4, 8, 12):
        run(nb, OUT_DIR / f"fase3_stats_por_equipo_bin{nb}.json")


if __name__ == "__main__":
    main()

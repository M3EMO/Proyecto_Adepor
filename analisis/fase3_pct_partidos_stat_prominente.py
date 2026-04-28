"""Fase 3: para cada (liga, equipo), % de partidos donde una stat fue PROMINENTE
(top 25% propio del equipo) y su desenlace V/E/D.

Pregunta: ¿cuando este equipo tiene esta stat alta (relativa a SU media), gana mas?
Output: per-equipo, ranking de stats por |delta_hit_local|.

Output: analisis/fase3_pct_partidos_stat_prominente.json
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


def cargar_obs(con):
    """Cada partido genera 2 obs (local, visita) con stats + outcome."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT * FROM stats_partido_espn WHERE h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    obs = []
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("hg") is None or d.get("ag") is None:
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
                     "outcome": out_l, "stats": stats_l})
        obs.append({"liga": d["liga"], "temp": d["temp"], "equipo": d["at"],
                     "outcome": out_v, "stats": stats_v})
    return obs


def analizar_equipo(obs_eq, n_min=15):
    """Para un equipo: para cada stat, % G/E/P cuando stat esta en top25% propio
    vs bottom25% propio. Devuelve ranking por |delta_g|."""
    if len(obs_eq) < n_min:
        return None
    n = len(obs_eq)
    n_g = sum(1 for o in obs_eq if o["outcome"] == "G")
    n_e = sum(1 for o in obs_eq if o["outcome"] == "E")
    n_p = sum(1 for o in obs_eq if o["outcome"] == "P")
    out = {"n_partidos": n, "n_g": n_g, "n_e": n_e, "n_p": n_p,
            "pct_g_global": n_g/n*100, "pct_p_global": n_p/n*100,
            "stats": {}}
    for _, _, stat in STATS:
        vals = [o["stats"].get(stat) for o in obs_eq if o["stats"].get(stat) is not None]
        if len(vals) < n_min:
            continue
        p25, p75 = np.percentile(vals, [25, 75])
        if p25 == p75:
            continue
        # Subset HIGH (stat >= P75 propio)
        sub_h = [o for o in obs_eq if o["stats"].get(stat) is not None and o["stats"][stat] >= p75]
        sub_l = [o for o in obs_eq if o["stats"].get(stat) is not None and o["stats"][stat] <= p25]
        if len(sub_h) < 4 or len(sub_l) < 4:
            continue
        n_g_h = sum(1 for o in sub_h if o["outcome"] == "G")
        n_p_h = sum(1 for o in sub_h if o["outcome"] == "P")
        n_g_l = sum(1 for o in sub_l if o["outcome"] == "G")
        n_p_l = sum(1 for o in sub_l if o["outcome"] == "P")
        pct_g_h = n_g_h/len(sub_h)*100
        pct_g_l = n_g_l/len(sub_l)*100
        delta_g = pct_g_h - pct_g_l
        out["stats"][stat] = {
            "p25": float(p25), "p75": float(p75),
            "n_high": len(sub_h), "n_low": len(sub_l),
            "pct_g_high": pct_g_h, "pct_p_high": n_p_h/len(sub_h)*100,
            "pct_g_low": pct_g_l, "pct_p_low": n_p_l/len(sub_l)*100,
            "delta_g_pct": delta_g,
        }
    return out


def main():
    con = sqlite3.connect(DB)
    obs = cargar_obs(con)
    print(f"=== FASE 3: % partidos por equipo donde stat es PROMINENTE (P75 propio) y G/P ===")
    print(f"N obs: {len(obs)}")
    if len(obs) < 1000:
        print("[FATAL] N insuficiente")
        return

    payload = {"n_obs": len(obs), "equipos": {}}

    # === POR EQUIPO ===
    por_eq = defaultdict(list)
    for o in obs:
        por_eq[(o["liga"], o["equipo"])].append(o)
    print(f"N equipos (liga x eq): {len(por_eq)}")
    print(f"Equipos con N>=30: {sum(1 for k, v in por_eq.items() if len(v) >= 30)}")

    eq_resultados = []
    for (liga, eq), sub in por_eq.items():
        a = analizar_equipo(sub, n_min=15)
        if not a:
            continue
        a["liga"] = liga
        a["equipo"] = eq
        eq_resultados.append(a)
        payload["equipos"][f"{liga}__{eq}"] = a

    # === GLOBAL: promedio delta_g por stat ===
    print(f"\n=== Stats con mayor IMPACTO PROMEDIO por equipo (alta vs baja propia) ===")
    print(f"  {'Stat':<22} {'avg delta_G':>12} {'N equipos':>10}")
    avg_deltas = defaultdict(list)
    for a in eq_resultados:
        for stat, info in a["stats"].items():
            avg_deltas[stat].append(info["delta_g_pct"])
    sintesis = {}
    for stat, deltas in sorted(avg_deltas.items(), key=lambda kv: -abs(np.mean(kv[1]))):
        avg = np.mean(deltas)
        print(f"  {stat:<22} {avg:>+11.2f}pp {len(deltas):>10}")
        sintesis[stat] = {"avg_delta_g_pct": float(avg), "n_equipos": len(deltas)}
    payload["sintesis_stats"] = sintesis

    # === TOP 30 EQUIPOS por |delta_g| en su top stat ===
    print(f"\n=== TOP 30 EQUIPOS por |delta_g| de su top stat ===")
    print(f"  {'Liga':<14} {'Equipo':<28} {'N':>4} {'pct_G_glob':>10} | {'Stat':<22} {'%G_high':>7} {'%G_low':>7} {'delta':>7}")
    eq_top = []
    for a in eq_resultados:
        if not a["stats"]:
            continue
        top_stat, top_info = max(a["stats"].items(), key=lambda kv: abs(kv[1]["delta_g_pct"]))
        eq_top.append({
            "liga": a["liga"], "equipo": a["equipo"], "n": a["n_partidos"],
            "pct_g_global": a["pct_g_global"],
            "top_stat": top_stat,
            "pct_g_high": top_info["pct_g_high"],
            "pct_g_low": top_info["pct_g_low"],
            "delta_g": top_info["delta_g_pct"],
            "n_high": top_info["n_high"], "n_low": top_info["n_low"],
        })
    eq_top.sort(key=lambda x: -abs(x["delta_g"]))
    for e in eq_top[:30]:
        delta_s = f"{e['delta_g']:>+7.1f}"
        print(f"  {e['liga']:<14} {e['equipo'][:26]:<28} {e['n']:>4} "
              f"{e['pct_g_global']:>9.1f}% | {e['top_stat']:<22} "
              f"{e['pct_g_high']:>6.1f}% {e['pct_g_low']:>6.1f}% {delta_s}")
    payload["top30_equipos"] = eq_top[:50]

    # === POR LIGA: promedio delta por liga ===
    print(f"\n=== POR LIGA: top 5 stats con mayor delta_G PROMEDIO ===")
    payload["por_liga"] = {}
    por_liga = defaultdict(list)
    for a in eq_resultados:
        por_liga[a["liga"]].append(a)
    for liga in sorted(por_liga.keys()):
        sub = por_liga[liga]
        if len(sub) < 5:
            continue
        liga_deltas = defaultdict(list)
        for a in sub:
            for stat, info in a["stats"].items():
                liga_deltas[stat].append(info["delta_g_pct"])
        sorted_deltas = sorted(liga_deltas.items(),
                                 key=lambda kv: -abs(np.mean(kv[1])))[:5]
        liga_sintesis = {}
        print(f"\n  {liga} ({len(sub)} equipos):")
        for stat, deltas in sorted_deltas:
            avg = np.mean(deltas)
            std = np.std(deltas)
            print(f"    {stat:<22} avg_delta_G={avg:>+7.2f}pp  std={std:>5.2f}pp  N={len(deltas)}")
            liga_sintesis[stat] = {"avg_delta_g": float(avg), "std_delta_g": float(std),
                                     "n": len(deltas)}
        payload["por_liga"][liga] = liga_sintesis

    out = OUT_DIR / "fase3_pct_partidos_stat_prominente.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")
    con.close()


if __name__ == "__main__":
    main()

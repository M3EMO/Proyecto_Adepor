"""Fase 3 (parte 4): analisis stats POR EQUIPO con outcome (G vs P).

Pregunta del usuario: ¿que stats discriminan VICTORIA vs DERROTA POR EQUIPO?
Separar por año (temp) y liga.

Para cada (liga, temp, equipo):
  - Particionar partidos en GANADOS / PERDIDOS / EMPATADOS (como local y visita)
  - Para cada stat: mean_ganado, mean_perdido, diff
  - Welch's t-test simplificado: |diff| / pooled_std
  - Ordenar stats por |t-stat| desc

Tambien agregado:
  - Por liga: cuales stats discriminan en general (promedio across equipos)
  - Por temp: idem
  - Top 20 equipos con discriminacion mas fuerte por stat key

Output: analisis/fase3_stats_por_equipo.json
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
    ("h_passes_acc", "a_passes_acc", "pases_acertados"),
    ("h_pass_pct", "a_pass_pct", "pass_pct"),
    ("h_crosses", "a_crosses", "crosses_total"),
    ("h_crosses_acc", "a_crosses_acc", "crosses_acertados"),
    ("h_cross_pct", "a_cross_pct", "cross_pct"),
    ("h_longballs", "a_longballs", "longballs_total"),
    ("h_longballs_acc", "a_longballs_acc", "longballs_acertados"),
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
    ("h_tackles_eff", "a_tackles_eff", "tackles_eff"),
    ("h_tackle_pct", "a_tackle_pct", "tackle_pct"),
    ("h_interceptions", "a_interceptions", "interceptions"),
    ("h_clearance", "a_clearance", "clearance"),
    ("h_clearance_eff", "a_clearance_eff", "clearance_eff"),
]


def cargar_partidos_por_equipo(con):
    """Convierte cada partido en 2 observaciones (local + visita) con stats + outcome."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT * FROM stats_partido_espn WHERE h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    obs = []  # (liga, temp, equipo, outcome, stats_dict_for_equipo)
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("hg") is None or d.get("ag") is None:
            continue
        # Outcome desde perspectiva LOCAL
        if d["hg"] > d["ag"]:
            out_l, out_v = "G", "P"
        elif d["hg"] == d["ag"]:
            out_l, out_v = "E", "E"
        else:
            out_l, out_v = "P", "G"
        # Local
        stats_l = {label: d.get(h) for h, _, label in STATS}
        obs.append({
            "liga": d["liga"], "temp": d["temp"], "equipo": d["ht"],
            "es_local": True, "outcome": out_l,
            "goles_propios": d["hg"], "goles_rival": d["ag"],
            "stats": stats_l,
        })
        # Visita
        stats_v = {label: d.get(a) for _, a, label in STATS}
        obs.append({
            "liga": d["liga"], "temp": d["temp"], "equipo": d["at"],
            "es_local": False, "outcome": out_v,
            "goles_propios": d["ag"], "goles_rival": d["hg"],
            "stats": stats_v,
        })
    return obs


def t_stat(grupo_a, grupo_b):
    """Welch's t-statistic simplificado: |diff_means| / pooled_se."""
    if len(grupo_a) < 5 or len(grupo_b) < 5:
        return None
    a = np.array(grupo_a, dtype=float)
    b = np.array(grupo_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return None
    mean_a = a.mean()
    mean_b = b.mean()
    se_a = a.var(ddof=1) / len(a) if len(a) > 1 else 0
    se_b = b.var(ddof=1) / len(b) if len(b) > 1 else 0
    se = np.sqrt(se_a + se_b)
    if se == 0:
        return None
    return float((mean_a - mean_b) / se)


def analizar_grupo(obs, label_grupo):
    """Para un conjunto de obs, calcula stats medias en G vs P y t-stat."""
    g = [o for o in obs if o["outcome"] == "G"]
    p = [o for o in obs if o["outcome"] == "P"]
    if len(g) < 5 or len(p) < 5:
        return None
    out = {"n_total": len(obs), "n_g": len(g), "n_p": len(p), "stats": {}}
    for _, _, stat in STATS:
        vals_g = [o["stats"].get(stat) for o in g if o["stats"].get(stat) is not None]
        vals_p = [o["stats"].get(stat) for o in p if o["stats"].get(stat) is not None]
        if len(vals_g) < 5 or len(vals_p) < 5:
            continue
        mean_g = float(np.mean(vals_g))
        mean_p = float(np.mean(vals_p))
        ts = t_stat(vals_g, vals_p)
        if ts is None:
            continue
        out["stats"][stat] = {
            "mean_g": mean_g, "mean_p": mean_p,
            "diff": mean_g - mean_p,
            "n_g": len(vals_g), "n_p": len(vals_p),
            "t_stat": ts,
        }
    return out


def main():
    con = sqlite3.connect(DB)
    obs = cargar_partidos_por_equipo(con)
    print(f"=== FASE 3 stats por equipo (G vs P) ===")
    print(f"N observaciones (partidos × 2 equipos): {len(obs)}")
    if len(obs) < 100:
        print("[FATAL] N insuficiente.")
        return

    payload = {"n_obs_total": len(obs)}

    # === GLOBAL ===
    print(f"\n=== GLOBAL: stats que discriminan G vs P (top 15 por |t-stat|) ===")
    g_global = analizar_grupo(obs, "global")
    if g_global:
        print(f"N: {g_global['n_g']} G, {g_global['n_p']} P")
        sorted_stats = sorted(g_global["stats"].items(),
                                key=lambda kv: -abs(kv[1]["t_stat"]))
        print(f"  {'Stat':<22} {'mean_G':>8} {'mean_P':>8} {'diff':>8} {'t-stat':>8}")
        for stat, s in sorted_stats[:15]:
            print(f"  {stat:<22} {s['mean_g']:>8.2f} {s['mean_p']:>8.2f} "
                  f"{s['diff']:>+8.2f} {s['t_stat']:>+8.2f}")
        payload["global"] = g_global

    # === POR LIGA ===
    print(f"\n=== POR LIGA (top 5 stats discriminantes) ===")
    payload["por_liga"] = {}
    por_liga = defaultdict(list)
    for o in obs:
        por_liga[o["liga"]].append(o)
    for liga in sorted(por_liga.keys()):
        sub = por_liga[liga]
        if len(sub) < 50:
            continue
        g = analizar_grupo(sub, liga)
        if not g:
            continue
        payload["por_liga"][liga] = g
        sorted_stats = sorted(g["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"]))
        top5 = sorted_stats[:5]
        print(f"\n  {liga} (N obs={len(sub)}, G={g['n_g']}, P={g['n_p']}):")
        for stat, s in top5:
            print(f"    {stat:<22} mean_G={s['mean_g']:>7.2f} "
                  f"mean_P={s['mean_p']:>7.2f}  diff={s['diff']:>+7.2f}  t={s['t_stat']:>+6.2f}")

    # === POR LIGA × TEMP ===
    print(f"\n=== POR LIGA x TEMP (top 5 stats discriminantes) ===")
    payload["por_liga_temp"] = {}
    por_lt = defaultdict(list)
    for o in obs:
        por_lt[(o["liga"], o["temp"])].append(o)
    for (liga, temp), sub in sorted(por_lt.items()):
        if len(sub) < 50:
            continue
        g = analizar_grupo(sub, f"{liga}_{temp}")
        if not g:
            continue
        payload["por_liga_temp"][f"{liga}_{temp}"] = g
        sorted_stats = sorted(g["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"]))
        top5 = sorted_stats[:5]
        top_str = ", ".join(f"{stat}({s['t_stat']:+.1f})" for stat, s in top5)
        print(f"  {liga} {temp} (N={len(sub)}): {top_str}")

    # === POR EQUIPO (top 30 con discriminacion mas fuerte por stat) ===
    print(f"\n=== POR EQUIPO (N>=15) — TOP 30 mas discriminantes por |t-stat| ===")
    por_eq = defaultdict(list)
    for o in obs:
        por_eq[(o["liga"], o["temp"], o["equipo"])].append(o)

    eq_resultados = []
    for (liga, temp, eq), sub in por_eq.items():
        g = analizar_grupo(sub, f"{liga}_{temp}_{eq}")
        if not g:
            continue
        sorted_stats = sorted(g["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"]))
        if not sorted_stats:
            continue
        top_stat, top_s = sorted_stats[0]
        eq_resultados.append({
            "liga": liga, "temp": temp, "equipo": eq,
            "n_g": g["n_g"], "n_p": g["n_p"],
            "top_stat": top_stat,
            "top_diff": top_s["diff"],
            "top_t_stat": top_s["t_stat"],
            "top_mean_g": top_s["mean_g"],
            "top_mean_p": top_s["mean_p"],
            "all_stats_top5": [(s, info["t_stat"], info["diff"])
                                 for s, info in sorted_stats[:5]],
        })
    eq_resultados.sort(key=lambda x: -abs(x["top_t_stat"]))
    print(f"  {'Liga':<14} {'Temp':>4} {'Equipo':<28} {'NG':>3} {'NP':>3} {'Top stat':<22} {'meanG':>7} {'meanP':>7} {'t':>7}")
    for e in eq_resultados[:30]:
        print(f"  {e['liga']:<14} {e['temp']:>4} {e['equipo'][:26]:<28} "
              f"{e['n_g']:>3} {e['n_p']:>3} {e['top_stat']:<22} "
              f"{e['top_mean_g']:>7.2f} {e['top_mean_p']:>7.2f} {e['top_t_stat']:>+7.2f}")
    payload["por_equipo_top30"] = eq_resultados[:50]
    payload["por_equipo_total"] = len(eq_resultados)

    # === SINTESIS: STATS QUE DISCRIMINAN MEJOR EN PROMEDIO POR EQUIPO ===
    print(f"\n=== SINTESIS: stats que aparecen como TOP en mas equipos ===")
    stat_counts = defaultdict(int)
    for e in eq_resultados:
        for s, _, _ in e["all_stats_top5"][:3]:
            stat_counts[s] += 1
    sorted_counts = sorted(stat_counts.items(), key=lambda kv: -kv[1])
    print(f"  {'Stat':<22} {'Aparece en top-3 de N equipos':>30}")
    for s, c in sorted_counts[:15]:
        print(f"  {s:<22} {c:>20}/{len(eq_resultados)}")
    payload["sintesis_top_stats_por_equipo"] = dict(sorted_counts[:15])

    out = OUT_DIR / "fase3_stats_por_equipo.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")
    con.close()


if __name__ == "__main__":
    main()

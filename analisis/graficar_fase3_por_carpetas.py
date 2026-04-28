"""Genera graficos Fase 3 organizados por estructura de carpetas:

  graficos/fase3/
    {liga}/
      _resumen_liga.png              — heatmap equipos x stats agregado liga
      {temp}/
        _resumen_{temp}.png          — heatmap equipos x stats temp
        {equipo}.png                  — perfil del equipo:
                                          - barras Δ%G por stat
                                          - heatmap stats x bin8 si tiene N
                                          - distribución G/E/P por bucket pos

Skip equipos con N < 10 partidos en esa temp.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUTDIR = ROOT / "graficos" / "fase3"
OUTDIR.mkdir(parents=True, exist_ok=True)

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


def safe_filename(s: str) -> str:
    """Convierte nombre con caracteres raros a archivo seguro."""
    s = re.sub(r"[^\w\s\-\(\)]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:80]


def cargar_obs(con, liga=None, temp=None, equipo=None):
    """Devuelve obs (1 partido = 2 obs: local, visita) con stats + outcome."""
    cur = con.cursor()
    where = ["h_pos IS NOT NULL"]
    params = []
    if liga:
        where.append("liga=?"); params.append(liga)
    if temp:
        where.append("temp=?"); params.append(temp)
    sql = f"SELECT * FROM stats_partido_espn WHERE {' AND '.join(where)}"
    rows = cur.execute(sql, params).fetchall()
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
        if not equipo or d["ht"] == equipo:
            obs.append({"liga": d["liga"], "temp": d["temp"], "equipo": d["ht"],
                         "es_local": True, "rival": d["at"],
                         "outcome": out_l, "stats": stats_l,
                         "goles_propios": d["hg"], "goles_rival": d["ag"]})
        if not equipo or d["at"] == equipo:
            obs.append({"liga": d["liga"], "temp": d["temp"], "equipo": d["at"],
                         "es_local": False, "rival": d["ht"],
                         "outcome": out_v, "stats": stats_v,
                         "goles_propios": d["ag"], "goles_rival": d["hg"]})
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


def delta_g_pct(obs_eq, n_min=12):
    """Para cada stat: (mean_G - mean_P, t_stat, %G_high - %G_low propio)."""
    if len(obs_eq) < n_min:
        return None
    n_g = sum(1 for o in obs_eq if o["outcome"] == "G")
    n_p = sum(1 for o in obs_eq if o["outcome"] == "P")
    n_e = sum(1 for o in obs_eq if o["outcome"] == "E")
    if n_g < 3 or n_p < 3:
        return None
    out = {"n": len(obs_eq), "n_g": n_g, "n_e": n_e, "n_p": n_p,
            "pct_g": n_g/len(obs_eq)*100, "stats": {}}
    for _, _, stat in STATS:
        vals_g = [o["stats"].get(stat) for o in obs_eq if o["outcome"] == "G" and o["stats"].get(stat) is not None]
        vals_p = [o["stats"].get(stat) for o in obs_eq if o["outcome"] == "P" and o["stats"].get(stat) is not None]
        if len(vals_g) < 3 or len(vals_p) < 3:
            continue
        ts = t_stat(vals_g, vals_p)
        # Quintiles propios
        vals = [o["stats"].get(stat) for o in obs_eq if o["stats"].get(stat) is not None]
        if len(vals) < 8:
            continue
        p25, p75 = np.percentile(vals, [25, 75])
        sub_h = [o for o in obs_eq if o["stats"].get(stat) is not None and o["stats"][stat] >= p75]
        sub_l = [o for o in obs_eq if o["stats"].get(stat) is not None and o["stats"][stat] <= p25]
        if len(sub_h) < 2 or len(sub_l) < 2:
            continue
        ng_h = sum(1 for o in sub_h if o["outcome"] == "G")
        ng_l = sum(1 for o in sub_l if o["outcome"] == "G")
        out["stats"][stat] = {
            "mean_g": float(np.mean(vals_g)),
            "mean_p": float(np.mean(vals_p)),
            "t_stat": ts,
            "pct_g_high": ng_h/len(sub_h)*100,
            "pct_g_low": ng_l/len(sub_l)*100,
            "delta_g": ng_h/len(sub_h)*100 - ng_l/len(sub_l)*100,
        }
    return out


def grafico_equipo(obs_eq, liga, temp, equipo, out_path):
    """Perfil de un equipo: barras Δ%G por stat + scatter G/E/P por bucket pos."""
    res = delta_g_pct(obs_eq)
    if not res:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))

    # Panel 1: Barras Δ%G por stat (top 10)
    ax = axes[0]
    sorted_stats = sorted(res["stats"].items(), key=lambda kv: -abs(kv[1]["delta_g"]))[:12]
    labels = [s for s, _ in sorted_stats]
    deltas = [s["delta_g"] for _, s in sorted_stats]
    colors = ["tab:green" if d > 0 else "tab:red" for d in deltas]
    y = np.arange(len(labels))
    ax.barh(y, deltas, color=colors, alpha=0.75)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.axvline(0, color="black", linestyle="--", alpha=0.5)
    for i, (s, info) in enumerate(sorted_stats):
        text_x = info["delta_g"] + (1 if info["delta_g"] >= 0 else -1)
        ax.text(text_x, i,
                 f"H={info['pct_g_high']:.0f}% L={info['pct_g_low']:.0f}% Δ{info['delta_g']:+.0f}",
                 va="center", ha="left" if info["delta_g"] >= 0 else "right", fontsize=8)
    ax.set_xlabel("Δ%G high vs low propio")
    ax.set_title(f"{equipo} — top 12 stats discriminantes (N={res['n']}, "
                  f"G={res['n_g']} E={res['n_e']} P={res['n_p']})")
    ax.grid(True, alpha=0.3, axis="x")

    # Panel 2: Mean stat G vs P (top 10 más discriminantes)
    ax = axes[1]
    sorted_t = sorted(res["stats"].items(), key=lambda kv: -abs(kv[1]["t_stat"] or 0))[:12]
    labels_t = [s for s, _ in sorted_t]
    means_g = [info["mean_g"] for _, info in sorted_t]
    means_p = [info["mean_p"] for _, info in sorted_t]
    x = np.arange(len(labels_t))
    w = 0.4
    ax.barh(x - w/2, means_g, w, label="GANA", color="tab:green", alpha=0.7)
    ax.barh(x + w/2, means_p, w, label="PIERDE", color="tab:red", alpha=0.7)
    ax.set_yticks(x)
    ax.set_yticklabels(labels_t, fontsize=10)
    ax.invert_yaxis()
    for i, (s, info) in enumerate(sorted_t):
        ts = info["t_stat"] or 0
        ax.text(max(info["mean_g"], info["mean_p"]) * 1.02, i,
                 f"t={ts:+.2f}",
                 va="center", ha="left", fontsize=8)
    ax.set_xlabel("media stat (en partidos GANADOS vs PERDIDOS)")
    ax.set_title(f"{equipo} — medias G vs P (top 12 |t-stat|)")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3, axis="x")

    fig.suptitle(f"{liga} {temp} — {equipo}", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return True


def grafico_resumen_liga_temp(obs_lt, liga, temp, out_path, equipos_filtro=None):
    """Heatmap top 12 equipos × top 8 stats con Δ%G."""
    por_eq = defaultdict(list)
    for o in obs_lt:
        por_eq[o["equipo"]].append(o)
    eq_results = []
    for eq, sub in por_eq.items():
        if equipos_filtro and eq not in equipos_filtro:
            continue
        res = delta_g_pct(sub, n_min=12)
        if res:
            eq_results.append((eq, res))
    if not eq_results:
        return False
    # Stats globales que aparecen en mayoría
    counts = defaultdict(int)
    for _, r in eq_results:
        for s in r["stats"]:
            counts[s] += 1
    top_stats = sorted(counts, key=lambda s: -counts[s])[:8]
    # Top 12 equipos por N
    eq_results.sort(key=lambda x: -x[1]["n"])
    top_eq = eq_results[:12]
    matrix = np.full((len(top_eq), len(top_stats)), np.nan)
    for i, (eq, res) in enumerate(top_eq):
        for j, stat in enumerate(top_stats):
            if stat in res["stats"]:
                matrix[i, j] = res["stats"][stat]["delta_g"]

    fig, ax = plt.subplots(figsize=(11, max(5, len(top_eq) * 0.6)))
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=-50, vmax=50)
    ax.set_xticks(range(len(top_stats)))
    ax.set_xticklabels(top_stats, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(top_eq)))
    ax.set_yticklabels([f"{e} (N={r['n']})" for e, r in top_eq], fontsize=9)
    for i in range(len(top_eq)):
        for j in range(len(top_stats)):
            v = matrix[i, j]
            if not np.isnan(v):
                color = "black" if abs(v) < 30 else "white"
                ax.text(j, i, f"{v:+.0f}", ha="center", va="center",
                         color=color, fontsize=8)
    ax.set_title(f"{liga} {temp} — top 12 equipos × top 8 stats (Δ%G high vs low propio)",
                  fontsize=11)
    fig.colorbar(im, ax=ax, label="Δ%G")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return True


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    lt_pairs = cur.execute("""
        SELECT DISTINCT liga, temp FROM stats_partido_espn WHERE h_pos IS NOT NULL
        ORDER BY liga, temp
    """).fetchall()
    print(f"Procesando {len(lt_pairs)} (liga, temp) pares...")
    n_eq = 0; n_lt = 0
    for liga, temp in lt_pairs:
        n_total = cur.execute(
            "SELECT COUNT(*) FROM stats_partido_espn WHERE liga=? AND temp=? AND h_pos IS NOT NULL",
            (liga, temp)).fetchone()[0]
        if n_total < 30:
            continue
        liga_safe = safe_filename(liga)
        temp_dir = OUTDIR / liga_safe / str(temp)
        temp_dir.mkdir(parents=True, exist_ok=True)
        obs_lt = cargar_obs(con, liga=liga, temp=temp)
        resumen_path = temp_dir / f"_resumen_{liga_safe}_{temp}.png"
        if grafico_resumen_liga_temp(obs_lt, liga, temp, resumen_path):
            n_lt += 1
        por_eq = defaultdict(list)
        for o in obs_lt:
            por_eq[o["equipo"]].append(o)
        for eq, sub in por_eq.items():
            if len(sub) < 12:
                continue
            eq_safe = safe_filename(eq)
            out_path = temp_dir / f"{eq_safe}.png"
            if grafico_equipo(sub, liga, temp, eq, out_path):
                n_eq += 1
    con.close()
    print(f"\n[OK] Generados:")
    print(f"  resumenes liga-temp : {n_lt}")
    print(f"  perfiles equipo     : {n_eq}")
    print(f"  estructura           : graficos/fase3/{{liga}}/{{temp}}/{{equipo}}.png")


if __name__ == "__main__":
    main()

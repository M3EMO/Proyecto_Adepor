"""Graficos consolidados Fase 3:
  - fase3_stats_avg_delta_g_por_liga.png   (heatmap liga x stat con avg_delta_g)
  - fase3_top_equipos_delta.png             (bar chart top 30 equipos)
  - fase3_correlacion_global_v2.png         (re-genera con N grande)
  - fase3_buckets_pos_outcome_v2.png        (re-genera con N grande)
  - fase3_yield_pos_x_bin{4,8,12}_v2.png    (re-genera con N grande)
"""
from __future__ import annotations

import json
import sys
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
ANL = ROOT / "analisis"
OUTDIR = ROOT / "graficos"
OUTDIR.mkdir(exist_ok=True)


def heatmap_stats_x_ligas():
    f = ANL / "fase3_pct_partidos_stat_prominente.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    pl = data.get("por_liga", {})
    if not pl:
        return

    # Construir matrix liga x stat con avg_delta_g
    todas_stats = set()
    for lstats in pl.values():
        todas_stats.update(lstats.keys())
    # Ordenar stats por |avg_delta_g| global
    sint = data.get("sintesis_stats", {})
    stats_ordered = sorted(todas_stats,
                            key=lambda s: -abs(sint.get(s, {}).get("avg_delta_g_pct", 0)))
    ligas = sorted(pl.keys())

    matrix = np.full((len(ligas), len(stats_ordered)), np.nan)
    for i, liga in enumerate(ligas):
        for j, stat in enumerate(stats_ordered):
            if stat in pl[liga]:
                matrix[i, j] = pl[liga][stat]["avg_delta_g"]

    fig, ax = plt.subplots(figsize=(max(14, len(stats_ordered) * 0.6), max(8, len(ligas) * 0.4)))
    vmax = max(40, np.nanmax(np.abs(matrix)))
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(stats_ordered)))
    ax.set_xticklabels(stats_ordered, rotation=60, ha="right", fontsize=9)
    ax.set_yticks(range(len(ligas)))
    ax.set_yticklabels(ligas, fontsize=10)
    for i in range(len(ligas)):
        for j in range(len(stats_ordered)):
            v = matrix[i, j]
            if not np.isnan(v):
                color = "black" if abs(v) < 25 else "white"
                ax.text(j, i, f"{v:+.0f}", ha="center", va="center",
                         color=color, fontsize=8)
    fig.colorbar(im, ax=ax, label="Δ % G (high vs low propio del equipo)")
    ax.set_title("Heatmap stats x liga: Δ % victoria cuando stat alta vs baja (promedio sobre equipos)\n"
                  "Verde = stat alta correlaciona con +victorias, Rojo = stat alta = +derrotas",
                  fontsize=11)
    fig.tight_layout()
    out = OUTDIR / "fase3_stats_avg_delta_g_por_liga.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def top_equipos_delta():
    f = ANL / "fase3_pct_partidos_stat_prominente.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    top = data.get("top30_equipos", [])[:30]
    if not top:
        return

    fig, ax = plt.subplots(figsize=(13, 11))
    labels = [f"{e['equipo'][:24]} ({e['liga'][:5]} N={e['n']})\n→ {e['top_stat']}" for e in top]
    deltas = [e["delta_g"] for e in top]
    colors = ["tab:green" if d > 0 else "tab:red" for d in deltas]
    y = np.arange(len(top))
    ax.barh(y, deltas, color=colors, alpha=0.75)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.axvline(0, color="black", linestyle="--", alpha=0.5)
    for i, e in enumerate(top):
        x = e["delta_g"]
        text_x = x + (1 if x >= 0 else -1)
        ax.text(text_x, i,
                 f"high={e['pct_g_high']:.0f}% low={e['pct_g_low']:.0f}% Δ={x:+.0f}",
                 va="center", ha="left" if x >= 0 else "right", fontsize=8)
    ax.set_xlabel("Δ %G high - %G low (propio del equipo)")
    ax.set_title("Top 30 equipos por |Δ%G|: cuando su STAT TOP esta alta vs baja propia")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    out = OUTDIR / "fase3_top_equipos_delta.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def stats_globales_resumen():
    """Bar chart sintesis: avg_delta_G global por stat."""
    f = ANL / "fase3_pct_partidos_stat_prominente.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    sint = data.get("sintesis_stats", {})
    if not sint:
        return
    stats_sorted = sorted(sint.items(), key=lambda kv: -kv[1]["avg_delta_g_pct"])
    labels = [s for s, _ in stats_sorted]
    vals = [d["avg_delta_g_pct"] for _, d in stats_sorted]
    ns = [d["n_equipos"] for _, d in stats_sorted]
    colors = ["tab:green" if v > 0 else "tab:red" for v in vals]

    fig, ax = plt.subplots(figsize=(11, 9))
    y = np.arange(len(labels))
    ax.barh(y, vals, color=colors, alpha=0.75)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.axvline(0, color="black", linestyle="--", alpha=0.5)
    for i, (v, n) in enumerate(zip(vals, ns)):
        text_x = v + (0.5 if v >= 0 else -0.5)
        ax.text(text_x, i, f"{v:+.1f}pp (N={n})",
                 va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax.set_xlabel("Δ %G global cuando stat alta vs baja (promedio sobre equipos)")
    ax.set_title("Stats por impacto en victorias propias\n"
                  "(Cada equipo es 1 obs; valores son Δ%G high-vs-low PROPIO del equipo)")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    out = OUTDIR / "fase3_stats_avg_delta_g_global.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def comparativo_bin_stats_discriminantes():
    """Compara stats discriminantes G/P por bin (4/8/12)."""
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    for ax, nb in zip(axes, [4, 8, 12]):
        f = ANL / f"fase3_stats_por_equipo_bin{nb}.json"
        if not f.exists():
            ax.set_title(f"bin{nb}: no data")
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        plb = data.get("por_liga_bin", {})
        # Top 8 stats por |avg t-stat|
        avg_t = {}
        for key, v in plb.items():
            for stat, info in v.get("stats", {}).items():
                avg_t.setdefault(stat, []).append(info["t_stat"])
        avg_t_mean = {s: np.mean(ts) for s, ts in avg_t.items() if len(ts) > 5}
        sorted_stats = sorted(avg_t_mean.items(), key=lambda kv: -abs(kv[1]))[:10]
        labels = [s for s, _ in sorted_stats]
        vals = [v for _, v in sorted_stats]
        colors = ["tab:green" if v > 0 else "tab:red" for v in vals]
        ax.barh(labels, vals, color=colors, alpha=0.75)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linestyle="--", alpha=0.5)
        for i, v in enumerate(vals):
            text_x = v + (0.2 if v >= 0 else -0.2)
            ax.text(text_x, i, f"{v:+.2f}", va="center",
                     ha="left" if v >= 0 else "right", fontsize=9)
        ax.set_xlabel("avg t-stat (across liga × bin cells)")
        ax.set_title(f"bin{nb}: top 10 stats discriminantes G vs P")
        ax.grid(True, alpha=0.3, axis="x")
    fig.suptitle("FASE 3 — Stats discriminantes G/P por granularidad de bin", fontsize=13)
    fig.tight_layout()
    out = OUTDIR / "fase3_stats_discriminantes_por_bin.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def equipos_por_liga_small_multiples():
    """Para cada liga, top 10 equipos por |delta_g| con su top stat."""
    f = ANL / "fase3_pct_partidos_stat_prominente.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    equipos_dict = data.get("equipos", {})
    if not equipos_dict:
        return
    # Agrupar por liga
    por_liga = {}
    for key, info in equipos_dict.items():
        liga = info.get("liga")
        if not liga:
            continue
        # Top stat del equipo
        stats = info.get("stats", {})
        if not stats:
            continue
        top_stat, top_info = max(stats.items(), key=lambda kv: abs(kv[1]["delta_g_pct"]))
        por_liga.setdefault(liga, []).append({
            "equipo": info["equipo"], "n": info["n_partidos"],
            "pct_g_global": info["pct_g_global"],
            "top_stat": top_stat,
            "delta_g": top_info["delta_g_pct"],
            "pct_g_high": top_info["pct_g_high"],
            "pct_g_low": top_info["pct_g_low"],
        })

    ligas_ord = sorted(por_liga.keys())
    n_ligas = len(ligas_ord)
    ncol = 3
    nrow = (n_ligas + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(20, 5 * nrow))
    axes = axes.flatten() if nrow > 1 else [axes] if ncol == 1 else list(axes)
    for ax in axes[n_ligas:]:
        ax.axis("off")
    for ax_idx, liga in enumerate(ligas_ord):
        ax = axes[ax_idx]
        eqs = sorted(por_liga[liga], key=lambda e: -abs(e["delta_g"]))[:10]
        labels = [f"{e['equipo'][:18]}\n→{e['top_stat'][:14]}" for e in eqs]
        deltas = [e["delta_g"] for e in eqs]
        colors = ["tab:green" if d > 0 else "tab:red" for d in deltas]
        y = np.arange(len(eqs))
        ax.barh(y, deltas, color=colors, alpha=0.75)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=7)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linestyle="--", alpha=0.4)
        for i, e in enumerate(eqs):
            text_x = e["delta_g"] + (1 if e["delta_g"] >= 0 else -1)
            ax.text(text_x, i,
                     f"{e['pct_g_high']:.0f}%/{e['pct_g_low']:.0f}% Δ{e['delta_g']:+.0f}",
                     va="center", ha="left" if e["delta_g"] >= 0 else "right",
                     fontsize=7)
        ax.set_title(f"{liga} — top 10 equipos (N≥15) por |Δ%G|", fontsize=11)
        ax.set_xlabel("Δ%G high vs low propio")
        ax.grid(True, alpha=0.3, axis="x")
    fig.suptitle("FASE 3 — Equipos POR LIGA: top 10 con stat más discriminante (G alta vs baja propia)",
                  fontsize=14)
    fig.tight_layout()
    out = OUTDIR / "fase3_equipos_por_liga_top10.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def heatmap_top_equipos_x_stats_por_liga():
    """Para cada liga, heatmap top 12 equipos x top 8 stats con su delta_g."""
    f = ANL / "fase3_pct_partidos_stat_prominente.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    equipos_dict = data.get("equipos", {})
    sint = data.get("sintesis_stats", {})
    # Top 8 stats globales (por |avg_delta_g|)
    top8 = sorted(sint.items(), key=lambda kv: -abs(kv[1]["avg_delta_g_pct"]))[:8]
    stats_show = [s for s, _ in top8]

    # Agrupar por liga
    por_liga = {}
    for key, info in equipos_dict.items():
        liga = info.get("liga")
        if not liga:
            continue
        por_liga.setdefault(liga, []).append(info)

    ligas_ord = sorted(por_liga.keys())
    n_ligas = len(ligas_ord)
    ncol = 3
    nrow = (n_ligas + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(20, 4.5 * nrow))
    axes = axes.flatten() if nrow > 1 else [axes]
    for ax in axes[n_ligas:]:
        ax.axis("off")
    for ax_idx, liga in enumerate(ligas_ord):
        ax = axes[ax_idx]
        eqs = sorted(por_liga[liga], key=lambda e: -e["n_partidos"])[:12]
        if not eqs:
            ax.axis("off")
            continue
        matrix = np.full((len(eqs), len(stats_show)), np.nan)
        for i, e in enumerate(eqs):
            for j, stat in enumerate(stats_show):
                if stat in e.get("stats", {}):
                    matrix[i, j] = e["stats"][stat]["delta_g_pct"]
        im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=-50, vmax=50)
        ax.set_xticks(range(len(stats_show)))
        ax.set_xticklabels([s[:10] for s in stats_show], rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(eqs)))
        ax.set_yticklabels([e["equipo"][:18] for e in eqs], fontsize=7)
        for i in range(len(eqs)):
            for j in range(len(stats_show)):
                v = matrix[i, j]
                if not np.isnan(v):
                    color = "black" if abs(v) < 30 else "white"
                    ax.text(j, i, f"{v:+.0f}", ha="center", va="center",
                             color=color, fontsize=7)
        ax.set_title(f"{liga} (top 12 equipos por N partidos)", fontsize=10)
    fig.suptitle("FASE 3 — Heatmap por liga: equipos × top 8 stats × Δ%G",
                  fontsize=13)
    fig.tight_layout()
    out = OUTDIR / "fase3_heatmap_equipos_x_stats_por_liga.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def main():
    heatmap_stats_x_ligas()
    top_equipos_delta()
    stats_globales_resumen()
    comparativo_bin_stats_discriminantes()
    equipos_por_liga_small_multiples()
    heatmap_top_equipos_x_stats_por_liga()


if __name__ == "__main__":
    main()

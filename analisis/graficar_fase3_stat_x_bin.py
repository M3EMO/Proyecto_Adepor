"""Heatmaps comparativos por stat: quintil × bin × yield (OOS + in-sample).
Output: grid de heatmaps por stat con OOS + in-sample side-by-side.
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

QUINTILES = ["Q1", "Q2", "Q3", "Q4", "Q5"]
LETTER = {4: "Q", 8: "O", 12: "D"}


def heatmap_stat(ax, stat_data, n_bins, title, vmin=-100, vmax=100):
    """Render heatmap quintil × bin para una stat."""
    cross = stat_data.get("cross_bin_x_quintil", {})
    bins_present = sorted(cross.keys(), key=lambda x: int(x.replace("bin","")))
    if not bins_present:
        ax.axis("off")
        return
    matrix = np.full((len(QUINTILES), len(bins_present)), np.nan)
    for i, q in enumerate(QUINTILES):
        for j, b in enumerate(bins_present):
            cell = cross[b].get(q, {})
            yp = cell.get("yield_pct")
            if yp is not None:
                matrix[i, j] = yp
    letter = LETTER.get(n_bins, "B")
    bin_labels = [f"{letter}{b.replace('bin','')}" for b in bins_present]
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(bins_present)))
    ax.set_xticklabels(bin_labels, fontsize=7, rotation=0)
    ax.set_yticks(range(len(QUINTILES)))
    ax.set_yticklabels(QUINTILES, fontsize=8)
    ax.set_title(title, fontsize=9)
    for i in range(len(QUINTILES)):
        for j in range(len(bins_present)):
            v = matrix[i, j]
            if not np.isnan(v):
                color = "black" if abs(v) < 50 else "white"
                ax.text(j, i, f"{v:+.0f}", ha="center", va="center",
                         color=color, fontsize=6)


def grid_stats_oos_vs_insample(n_bins):
    f_oos = ANL / f"fase3_yield_x_stats_x_bin{n_bins}_oos.json"
    f_in = ANL / f"fase3_yield_x_stats_x_bin{n_bins}_insample.json"
    if not (f_oos.exists() and f_in.exists()):
        return
    d_oos = json.loads(f_oos.read_text(encoding="utf-8"))
    d_in = json.loads(f_in.read_text(encoding="utf-8"))
    stats_oos = d_oos.get("stats", {})
    stats_in = d_in.get("stats", {})

    # Stats que aparecen en AMBOS
    stats_comunes = sorted(set(stats_oos.keys()) & set(stats_in.keys()))
    if not stats_comunes:
        return

    # Para cada stat: 2 paneles side-by-side (OOS, in-sample)
    n = len(stats_comunes)
    ncols = 4  # 4 pares por fila = 8 columnas reales
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols * 2, figsize=(ncols * 5, nrows * 2.6))
    axes = axes.reshape(nrows, ncols * 2) if nrows > 1 else axes.reshape(1, ncols * 2)

    for i, stat in enumerate(stats_comunes):
        row = i // ncols
        col = (i % ncols) * 2
        # OOS
        heatmap_stat(axes[row, col], stats_oos[stat], n_bins,
                       f"{stat[:18]} OOS", vmin=-80, vmax=80)
        # IN-SAMPLE (los valores son mucho mayores en magnitud)
        heatmap_stat(axes[row, col+1], stats_in[stat], n_bins,
                       f"{stat[:18]} IN-SAMPLE", vmin=-150, vmax=200)

    # Apagar ejes vacíos
    for k in range(n, nrows * ncols):
        row = k // ncols
        col = (k % ncols) * 2
        axes[row, col].axis("off")
        axes[row, col+1].axis("off")

    fig.suptitle(f"FASE 3 — Yield × stat × quintil × bin{n_bins} (OOS vs IN-SAMPLE)\n"
                  "Cada par: izq=OOS (vmin/max ±80), der=in-sample (vmin/max -150/+200)",
                  fontsize=12)
    fig.tight_layout()
    out = OUTDIR / f"fase3_stats_x_bin{n_bins}_oos_vs_insample.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def main():
    for nb in (4, 8, 12):
        grid_stats_oos_vs_insample(nb)


if __name__ == "__main__":
    main()

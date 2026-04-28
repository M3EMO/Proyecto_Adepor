"""Genera graficos para FASE 2 (in-sample + OOS por temp x bin x diff_pos).

Output:
  - graficos/fase2_in_sample_bin{N}.png       — yield por bin x diff_pos
  - graficos/fase2_oos_agregado_bin{N}.png    — yield agregado OOS bin x diff_pos
  - graficos/fase2_oos_por_temp_bin{N}.png    — drill-down 3 temps x bin
  - graficos/fase2_diff_pos_overview.png      — yield por diff_pos comparativo
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

DIFF_POS_LABELS = ["vis_mucho_mejor", "vis_mejor", "igual", "loc_mejor", "loc_mucho_mejor"]
DIFF_POS_SHORT = ["vis++", "vis+", "0", "loc+", "loc++"]
LETTER_MAP = {4: "Q", 8: "O", 12: "D"}


def heatmap_cross(ax, cross_data, n_bins, title, vmin=-100, vmax=100):
    """Render heatmap of yield per (bin, diff_pos). Borde * si CI95 excluye 0."""
    letter = LETTER_MAP.get(n_bins, "B")
    bins = [f"{letter}{i+1}" for i in range(n_bins)]
    matrix = np.full((n_bins, len(DIFF_POS_LABELS)), np.nan)
    sig_matrix = [["" for _ in DIFF_POS_LABELS] for _ in range(n_bins)]
    for i, b in enumerate(bins):
        bin_data = cross_data.get(b, {})
        for j, dp in enumerate(DIFF_POS_LABELS):
            cell = bin_data.get(dp, {})
            yp = cell.get("yield_pct")
            if yp is not None:
                matrix[i, j] = yp
                if cell.get("sig") in ("+", "-"):
                    sig_matrix[i][j] = "*"
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(DIFF_POS_LABELS)))
    ax.set_xticklabels(DIFF_POS_SHORT, fontsize=10)
    ax.set_yticks(range(n_bins))
    ax.set_yticklabels(bins, fontsize=10)
    ax.set_xlabel("diff_pos (vis − loc)")
    ax.set_ylabel(f"momento_bin{n_bins}")
    ax.set_title(title, fontsize=11)
    for i in range(n_bins):
        for j in range(len(DIFF_POS_LABELS)):
            v = matrix[i, j]
            if not np.isnan(v):
                color = "black" if abs(v) < 60 else "white"
                txt = f"{v:+.0f}{sig_matrix[i][j]}"
                ax.text(j, i, txt, ha="center", va="center",
                         color=color, fontsize=8)
    return im


def grafico_in_sample(n_bins):
    f = ANL / f"fase2_in_sample_bin{n_bins}.json"
    if not f.exists():
        print(f"[SKIP] {f} no existe")
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))

    # Panel 1: yield por momento_bin (unit + real)
    ax = axes[0]
    letter = LETTER_MAP.get(n_bins, "B")
    bins = sorted(data["por_momento_bin"].keys(),
                   key=lambda x: int(x[1:]))
    yld_unit = [data["por_momento_bin"][b].get("unit", {}).get("yield_pct") for b in bins]
    yld_real = [data["por_momento_bin"][b].get("real", {}).get("yield_pct") if data["por_momento_bin"][b].get("real") else None for b in bins]
    ax.plot(range(len(bins)), yld_unit, marker="o", markersize=10,
             linewidth=2.5, color="tab:blue", label="Yield unitario")
    yld_real_clean = [(i, y) for i, y in enumerate(yld_real) if y is not None]
    if yld_real_clean:
        xs = [x for x, _ in yld_real_clean]
        ys = [y for _, y in yld_real_clean]
        ax.plot(xs, ys, marker="s", markersize=8, linewidth=2,
                 color="tab:orange", label="Yield $ real (stake>0)", alpha=0.85)
    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xticks(range(len(bins)))
    ax.set_xticklabels(bins, fontsize=10)
    ax.set_xlabel(f"momento_bin{n_bins}")
    ax.set_ylabel("Yield %")
    ax.set_title(f"In-sample yield por momento_bin{n_bins}")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Panel 2: heatmap cross bin x diff_pos
    cross = data.get("cross_bin_x_diff_pos", {})
    heatmap_cross(axes[1], cross, n_bins,
                    f"In-sample yield: bin{n_bins} x diff_pos (yield unitario)",
                    vmin=-100, vmax=200)

    fig.suptitle(f"FASE 2 IN-SAMPLE bin{n_bins} — N={data['n_total']}", fontsize=13)
    fig.tight_layout()
    out = OUTDIR / f"fase2_in_sample_bin{n_bins}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def grafico_oos_agregado(n_bins):
    f = ANL / f"fase2_oos_bin{n_bins}.json"
    if not f.exists():
        print(f"[SKIP] {f} no existe")
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    agg = data["agregado"]
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    # Panel 1: yield por momento_bin
    ax = axes[0]
    letter = LETTER_MAP.get(n_bins, "B")
    bins = sorted(agg["por_momento_bin"].keys(), key=lambda x: int(x[1:]))
    ylds = [agg["por_momento_bin"][b]["yield_pct"] for b in bins]
    hits = [agg["por_momento_bin"][b]["hit_pct"] for b in bins]
    briers = [agg["por_momento_bin"][b]["brier_avg"] for b in bins]
    ax.plot(range(len(bins)), ylds, marker="o", markersize=10,
             linewidth=2.5, color="tab:blue", label="Yield %")
    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xticks(range(len(bins)))
    ax.set_xticklabels(bins, fontsize=10)
    ax.set_xlabel(f"momento_bin{n_bins}")
    ax.set_ylabel("Yield %")
    ax.set_title(f"OOS yield por momento_bin{n_bins} (agregado)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Panel 2: yield por diff_pos
    ax = axes[1]
    dp_data = agg.get("por_diff_pos", {})
    labels_dp = [dp for dp in DIFF_POS_LABELS if dp in dp_data]
    ys_dp = [dp_data[dp]["yield_pct"] for dp in labels_dp]
    ns_dp = [dp_data[dp]["n_apost"] for dp in labels_dp]
    colors = ["tab:green" if y >= 0 else "tab:red" for y in ys_dp]
    ax.bar([DIFF_POS_SHORT[DIFF_POS_LABELS.index(dp)] for dp in labels_dp],
            ys_dp, color=colors, alpha=0.7)
    for i, (n, y) in enumerate(zip(ns_dp, ys_dp)):
        ax.text(i, y + (1 if y >= 0 else -2), f"N={n}",
                 ha="center", fontsize=9)
    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xlabel("diff_pos bucket")
    ax.set_ylabel("Yield % apostado")
    ax.set_title("OOS yield por diff_pos (agregado)")
    ax.grid(True, alpha=0.3, axis="y")

    # Panel 3: heatmap cross bin x diff_pos
    cross = agg.get("cross_bin_x_diff_pos", {})
    heatmap_cross(axes[2], cross, n_bins,
                    f"OOS cross: bin{n_bins} x diff_pos",
                    vmin=-60, vmax=60)

    fig.suptitle(f"FASE 2 OOS AGREGADO bin{n_bins} — N={data['n_total']}", fontsize=13)
    fig.tight_layout()
    out = OUTDIR / f"fase2_oos_agregado_bin{n_bins}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def grafico_oos_por_temp(n_bins):
    f = ANL / f"fase2_oos_bin{n_bins}.json"
    if not f.exists():
        print(f"[SKIP] {f} no existe")
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    por_temp = data.get("por_temp", {})
    if not por_temp:
        return
    temps = sorted(por_temp.keys())
    fig, axes = plt.subplots(2, len(temps), figsize=(7 * len(temps), 12))
    if len(temps) == 1:
        axes = axes.reshape(2, 1)

    letter = LETTER_MAP.get(n_bins, "B")
    bins = [f"{letter}{i+1}" for i in range(n_bins)]
    cmap = plt.cm.tab10

    for ti, temp in enumerate(temps):
        td = por_temp[temp]

        # Top: yield por momento_bin con linea
        ax = axes[0, ti]
        bin_data = td.get("por_momento_bin", {})
        ylds = [bin_data.get(b, {}).get("yield_pct") for b in bins]
        hits = [bin_data.get(b, {}).get("hit_pct") for b in bins]
        ax.plot(range(len(bins)), ylds, marker="o", markersize=9,
                 linewidth=2.5, color=cmap(ti), label="Yield %")
        ax2 = ax.twinx()
        ax2.plot(range(len(bins)), hits, marker="^", markersize=7,
                  linewidth=1.5, color="gray", alpha=0.6, linestyle="--", label="Hit %")
        ax2.set_ylabel("Hit %", fontsize=9, color="gray")
        ax2.tick_params(axis="y", labelcolor="gray", labelsize=8)
        ax.axhline(0, color="black", linestyle="--", alpha=0.4)
        ax.set_xticks(range(len(bins)))
        ax.set_xticklabels(bins, fontsize=9)
        ax.set_xlabel(f"momento_bin{n_bins}")
        ax.set_ylabel("Yield %")
        ax.set_title(f"OOS Temp {temp} — yield por bin")
        ax.grid(True, alpha=0.3)

        # Bottom: heatmap cross
        cross = td.get("cross_bin_x_diff_pos", {})
        heatmap_cross(axes[1, ti], cross, n_bins,
                        f"Cross bin{n_bins} x diff_pos — Temp {temp}",
                        vmin=-80, vmax=80)

    fig.suptitle(f"FASE 2 OOS POR TEMP bin{n_bins}", fontsize=14)
    fig.tight_layout()
    out = OUTDIR / f"fase2_oos_por_temp_bin{n_bins}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def grafico_diff_pos_overview():
    """Overview yield por diff_pos: in-sample vs OOS por temp."""
    fig, ax = plt.subplots(figsize=(12, 7))
    # Tomar de bin8 ya que el agregado es independiente del bin
    in_data = json.loads((ANL / "fase2_in_sample_bin8.json").read_text(encoding="utf-8"))
    oos_data = json.loads((ANL / "fase2_oos_bin8.json").read_text(encoding="utf-8"))
    by_dp_in = in_data["por_diff_pos"]

    # Series: in-sample, oos agregado, oos por temp
    rows = [("In-sample (unit)", by_dp_in, "unit", "tab:purple", "o", 10)]
    rows.append(("OOS agregado", oos_data["agregado"]["por_diff_pos"], None, "tab:blue", "s", 10))
    cmap = plt.cm.tab10
    for ti, temp in enumerate(sorted(oos_data["por_temp"].keys())):
        rows.append((f"OOS {temp}", oos_data["por_temp"][temp]["por_diff_pos"], None, cmap(ti+1), "^", 8))

    for label, dp_data, sub_key, color, marker, size in rows:
        ys = []
        xs = []
        ci_lo = []
        ci_hi = []
        for j, dp in enumerate(DIFF_POS_LABELS):
            if dp not in dp_data:
                continue
            entry = dp_data[dp]
            # In-sample tiene CI95 unitario en el wrapper; OOS lo tiene directo
            ylo = entry.get("ci95_lo_unit") if sub_key else entry.get("ci95_lo")
            yhi = entry.get("ci95_hi_unit") if sub_key else entry.get("ci95_hi")
            if sub_key:
                entry = entry.get(sub_key) or {}
            y = entry.get("yield_pct")
            if y is not None:
                ys.append(y)
                xs.append(j)
                ci_lo.append(ylo if ylo is not None else y)
                ci_hi.append(yhi if yhi is not None else y)
        if not xs:
            continue
        err_low = [y - lo for y, lo in zip(ys, ci_lo)]
        err_high = [hi - y for y, hi in zip(ys, ci_hi)]
        ax.errorbar(xs, ys, yerr=[err_low, err_high], marker=marker,
                     markersize=size, linewidth=2, color=color, label=label,
                     alpha=0.8, capsize=4)

    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xticks(range(len(DIFF_POS_LABELS)))
    ax.set_xticklabels(DIFF_POS_SHORT, fontsize=11)
    ax.set_xlabel("diff_pos bucket (vis − loc)")
    ax.set_ylabel("Yield %")
    ax.set_title("FASE 2 — Yield por diff_pos: in-sample vs OOS por temp")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = OUTDIR / "fase2_diff_pos_overview.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def main():
    for nb in (4, 8, 12):
        grafico_in_sample(nb)
        grafico_oos_agregado(nb)
        grafico_oos_por_temp(nb)
    grafico_diff_pos_overview()


if __name__ == "__main__":
    main()

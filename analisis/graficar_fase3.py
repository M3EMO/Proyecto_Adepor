"""Genera graficos para FASE 3 (correlacion posesion x xG + yield x pos x bin).

Output:
  - graficos/fase3_pos_vs_xg_global.png       — scatter pos vs xG con OLS
  - graficos/fase3_pos_vs_xg_por_liga.png     — small multiples 15 ligas
  - graficos/fase3_pos_vs_xg_por_temp.png     — comparativo 3 temps
  - graficos/fase3_pos_buckets_outcome.png    — hit_local% por bucket pos
  - graficos/fase3_yield_x_pos_x_bin{4,8,12}.png — heatmap pos x bin yield
  - graficos/fase3_yield_pos_por_temp_bin{4,8,12}.png — drill-down por temp
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

POS_BUCKETS = ["muy_baja", "baja", "media", "alta", "muy_alta"]
POS_LABELS = ["<35%", "35-45", "45-55", "55-65", ">65%"]
LETTER_MAP = {4: "Q", 8: "O", 12: "D"}


def grafico_correlacion_global():
    """Bar chart: Pearson(pos, xG) global + por liga + por temp."""
    f = ANL / "fase3_correlacion_pos_xg.json"
    if not f.exists():
        print(f"[SKIP] {f}")
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    corr = data["correlacion"]

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # Panel 1: por liga
    ax = axes[0]
    if "por_liga" in corr and corr["por_liga"]:
        ligas = sorted(corr["por_liga"].keys())
        pearsons = [corr["por_liga"][l]["pearson"] for l in ligas]
        colors = ["tab:green" if p > 0.3 else "tab:olive" if p > 0.1 else "tab:red" for p in pearsons]
        ax.barh(ligas, pearsons, color=colors, alpha=0.7)
        ax.axvline(0, color="black", linestyle="--", alpha=0.5)
        for i, p in enumerate(pearsons):
            ax.text(p + (0.005 if p >= 0 else -0.005), i, f"{p:+.3f}",
                     va="center", ha="left" if p >= 0 else "right", fontsize=9)
        ax.set_xlabel("Pearson(pos, xG_proxy)")
        ax.set_title("Correlacion posesion x xG por liga")
        ax.grid(True, alpha=0.3, axis="x")

    # Panel 2: por temp
    ax = axes[1]
    if "por_temp" in corr and corr["por_temp"]:
        temps = sorted(corr["por_temp"].keys())
        pearsons = [corr["por_temp"][t]["pearson"] for t in temps]
        ax.bar(temps, pearsons, color="tab:blue", alpha=0.7)
        ax.axhline(0, color="black", linestyle="--", alpha=0.5)
        for i, p in enumerate(pearsons):
            ax.text(i, p + 0.005, f"{p:+.3f}", ha="center", fontsize=10)
        ax.set_xlabel("Temporada")
        ax.set_ylabel("Pearson")
        ax.set_title("Correlacion posesion x xG por temp")
        ax.grid(True, alpha=0.3, axis="y")

    # Panel 3: top equipos por correlacion
    ax = axes[2]
    if "por_equipo" in corr and corr["por_equipo"]:
        top = corr["por_equipo"][:15]
        labels = [f"{e['equipo'][:18]}\n({e['liga'][:5]} N={e['n']})" for e in top]
        pearsons = [e["pearson"] for e in top]
        colors = ["tab:green" if p > 0 else "tab:red" for p in pearsons]
        ax.barh(range(len(top)), pearsons, color=colors, alpha=0.7)
        ax.set_yticks(range(len(top)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.axvline(0, color="black", linestyle="--", alpha=0.5)
        ax.set_xlabel("Pearson(pos_eq, xG_eq)")
        ax.set_title("Top 15 equipos por |Pearson|")
        ax.grid(True, alpha=0.3, axis="x")

    fig.suptitle(f"FASE 3 — Correlacion posesion vs xG_proxy "
                  f"(global Pearson={corr['global']['pearson']:+.4f}, "
                  f"R²={corr['global']['ols']['r2']:.4f}, N obs={corr['global']['n_obs']})",
                  fontsize=12)
    fig.tight_layout()
    out = OUTDIR / "fase3_correlacion_global.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def grafico_pos_buckets_outcome():
    """Bar chart: hit_local%, empate%, hit_visita% por bucket pos local."""
    f = ANL / "fase3_correlacion_pos_xg.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    pb = data.get("pos_buckets_outcome", {})
    if not pb:
        return
    buckets = [b for b in POS_BUCKETS if b in pb]
    if not buckets:
        return

    fig, ax = plt.subplots(figsize=(11, 6))
    x = np.arange(len(buckets))
    w = 0.27
    hit_l = [pb[b]["hit_local_pct"] for b in buckets]
    emp = [pb[b]["empate_pct"] for b in buckets]
    hit_v = [pb[b]["hit_visita_pct"] for b in buckets]
    ns = [pb[b]["n"] for b in buckets]

    ax.bar(x - w, hit_l, w, label="GANA Local", color="tab:green", alpha=0.8)
    ax.bar(x, emp, w, label="EMPATE", color="tab:gray", alpha=0.6)
    ax.bar(x + w, hit_v, w, label="GANA Visita", color="tab:red", alpha=0.8)
    for i, (h, e, v, n) in enumerate(zip(hit_l, emp, hit_v, ns)):
        ax.text(i - w, h + 0.5, f"{h:.0f}%", ha="center", fontsize=9)
        ax.text(i, e + 0.5, f"{e:.0f}%", ha="center", fontsize=9)
        ax.text(i + w, v + 0.5, f"{v:.0f}%", ha="center", fontsize=9)
        ax.text(i, -3, f"N={n}", ha="center", fontsize=9, color="dimgray")

    pos_label_map = dict(zip(POS_BUCKETS, POS_LABELS))
    ax.set_xticks(x)
    ax.set_xticklabels([f"{b}\n{pos_label_map[b]}" for b in buckets])
    ax.set_xlabel("Bucket de posesion LOCAL")
    ax.set_ylabel("% partidos")
    ax.set_title("FASE 3 — Distribucion de outcome por bucket de posesion local")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    out = OUTDIR / "fase3_pos_buckets_outcome.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def heatmap_pos_x_bin(ax, cross_data, n_bins, title):
    """Heatmap pos_bucket x bin yield."""
    letter = LETTER_MAP.get(n_bins, "B")
    bins_x = [f"{letter}{i+1}" for i in range(n_bins)]
    matrix = np.full((len(POS_BUCKETS), n_bins), np.nan)
    for i, pb in enumerate(POS_BUCKETS):
        if pb not in cross_data:
            continue
        for j, b in enumerate(bins_x):
            cell = cross_data[pb].get(b, {})
            yp = cell.get("yield_pct")
            if yp is not None:
                matrix[i, j] = yp
    im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto", vmin=-50, vmax=50)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bins_x, fontsize=9)
    ax.set_yticks(range(len(POS_BUCKETS)))
    ax.set_yticklabels(POS_LABELS, fontsize=9)
    ax.set_xlabel(f"momento_bin{n_bins}")
    ax.set_ylabel("Posesion local")
    ax.set_title(title, fontsize=10)
    for i in range(len(POS_BUCKETS)):
        for j in range(n_bins):
            v = matrix[i, j]
            if not np.isnan(v):
                color = "black" if abs(v) < 30 else "white"
                ax.text(j, i, f"{v:+.0f}", ha="center", va="center",
                         color=color, fontsize=8)
    return im


def grafico_yield_pos_x_bin(n_bins):
    f = ANL / f"fase3_yield_posesion_oos_bin{n_bins}.json"
    if not f.exists():
        print(f"[SKIP] {f}")
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    agg = data["agregado"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    # Panel 1: yield por bucket pos local
    ax = axes[0]
    pp = agg.get("por_pos_local", {})
    pos_present = [b for b in POS_BUCKETS if b in pp]
    if pos_present:
        ys = [pp[b]["yield_pct"] for b in pos_present]
        ns = [pp[b]["n_apost"] for b in pos_present]
        sigs = [pp[b].get("sig", "?") for b in pos_present]
        colors = []
        for s, y in zip(sigs, ys):
            if s == "+":
                colors.append("tab:green")
            elif s == "-":
                colors.append("tab:red")
            elif y >= 0:
                colors.append("tab:olive")
            else:
                colors.append("tab:gray")
        labels = [f"{b}\n{POS_LABELS[POS_BUCKETS.index(b)]}" for b in pos_present]
        ax.bar(labels, ys, color=colors, alpha=0.7)
        for i, (n, y) in enumerate(zip(ns, ys)):
            ax.text(i, y + (0.5 if y >= 0 else -2), f"N={n}",
                     ha="center", fontsize=9)
        ax.axhline(0, color="black", linestyle="--", alpha=0.5)
        ax.set_xlabel("Bucket pos local")
        ax.set_ylabel("Yield % apostado")
        ax.set_title(f"OOS yield por bucket pos local (bin{n_bins} agregado)")
        ax.grid(True, alpha=0.3, axis="y")

    # Panel 2: heatmap pos x bin
    cross = agg.get("cross_pos_x_bin", {})
    heatmap_pos_x_bin(axes[1], cross, n_bins,
                       f"OOS yield: pos_local x momento_bin{n_bins}")

    fig.suptitle(f"FASE 3 — yield x posesion x bin{n_bins} agregado (N={data['n_total']})",
                  fontsize=12)
    fig.tight_layout()
    out = OUTDIR / f"fase3_yield_x_pos_x_bin{n_bins}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def grafico_yield_pos_por_temp(n_bins):
    f = ANL / f"fase3_yield_posesion_oos_bin{n_bins}.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8"))
    por_temp = data.get("por_temp", {})
    if not por_temp:
        return
    temps = sorted(por_temp.keys())
    fig, axes = plt.subplots(1, len(temps), figsize=(7 * len(temps), 6))
    if len(temps) == 1:
        axes = [axes]
    for ti, temp in enumerate(temps):
        td = por_temp[temp]
        cross = td.get("cross_pos_x_bin", {})
        heatmap_pos_x_bin(axes[ti], cross, n_bins,
                           f"Temp {temp} — pos x bin{n_bins}")
    fig.suptitle(f"FASE 3 yield posesion x bin{n_bins} por TEMP", fontsize=13)
    fig.tight_layout()
    out = OUTDIR / f"fase3_yield_pos_por_temp_bin{n_bins}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out}")


def main():
    grafico_correlacion_global()
    grafico_pos_buckets_outcome()
    for nb in (4, 8, 12):
        grafico_yield_pos_x_bin(nb)
        grafico_yield_pos_por_temp(nb)


if __name__ == "__main__":
    main()

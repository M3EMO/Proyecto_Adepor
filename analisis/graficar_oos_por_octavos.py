"""Genera graficos OOS por altura de temporada (octavos) desde JSON
yield_por_altura_temporada.json.

Output:
  - graficos/oos_curva_por_octavo_agregado.png   — yield + hit + brier sistema A
  - graficos/oos_yield_por_temp_x_octavo.png     — drill-down V4.7 dY por temp
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
OUTDIR = ROOT / "graficos"
OUTDIR.mkdir(exist_ok=True)


def run(input_json: Path, suffix: str):
    data = json.loads(input_json.read_text(encoding="utf-8"))
    n_bins = data.get("n_bins", 8)
    letter_map = {4: "Q", 8: "O", 12: "D"}
    bin_letter = letter_map.get(n_bins, "B")
    octavos = [f"{bin_letter}{i+1}" for i in range(n_bins)]

    # === GRAFICO 1: agregado A baseline por octavo (Y + Hit + Brier) ===
    yields_a = []
    hits_a = []
    briers_a = []
    yields_d = []
    hits_d = []
    briers_d = []
    ns = []
    for i in range(n_bins):
        bin_data = data["agregado_por_bin"].get(f"Q{i+1}", {})
        yields_a.append(bin_data.get("yield_A", 0))
        hits_a.append(bin_data.get("hit_A", 0))
        briers_a.append(bin_data.get("brier_A", 0))
        yields_d.append(bin_data.get("yield_D", 0))
        hits_d.append(bin_data.get("hit_D", 0))
        briers_d.append(bin_data.get("brier_D", 0))
        ns.append(bin_data.get("n", 0))

    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    ax = axes[0]
    ax.plot(range(n_bins), yields_a, marker="o", markersize=10, linewidth=2.5,
             color="tab:blue", label="A (HG+Fix5)")
    ax.plot(range(n_bins), yields_d, marker="s", markersize=8, linewidth=1.8,
             color="tab:orange", label="D (V4.7 puro)", alpha=0.7)
    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(octavos)
    ax.set_xlabel("Octavo de temporada (% trayecto liga, OOS 2022-2024)")
    ax.set_ylabel("Yield %")
    ax.set_title(f"OOS yield por octavo de temp\nN={sum(ns)} sobre Pinnacle closing")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(range(n_bins), hits_a, marker="o", markersize=10, linewidth=2.5,
             color="tab:blue", label="A (HG+Fix5)")
    ax.plot(range(n_bins), hits_d, marker="s", markersize=8, linewidth=1.8,
             color="tab:orange", label="D (V4.7 puro)", alpha=0.7)
    ax.axhline(33.3, color="red", linestyle="--", alpha=0.4, label="Random 33.3%")
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(octavos)
    ax.set_xlabel("Octavo de temporada")
    ax.set_ylabel("Hit rate %")
    ax.set_title("OOS hit rate por octavo")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    ax.set_ylim(20, 50)

    ax = axes[2]
    ax.plot(range(n_bins), briers_a, marker="o", markersize=10, linewidth=2.5,
             color="tab:blue", label="A (HG+Fix5)")
    ax.plot(range(n_bins), briers_d, marker="s", markersize=8, linewidth=1.8,
             color="tab:orange", label="D (V4.7 puro)", alpha=0.7)
    ax.axhline(0.667, color="red", linestyle="--", alpha=0.4, label="Random 0.667")
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(octavos)
    ax.set_xlabel("Octavo de temporada")
    ax.set_ylabel("Brier 1x2 (menor=mejor)")
    ax.set_title("OOS Brier por octavo")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    fig.suptitle("OOS walk-forward: forma de U invertida (mejor en mitad, peor en arranque/cierre)",
                  fontsize=12)
    fig.tight_layout()
    out1 = OUTDIR / f"oos_curva_por_octavo_agregado_{suffix}.png"
    fig.savefig(out1, dpi=120)
    plt.close(fig)
    print(f"[OK] {out1}")

    # === GRAFICO 2: drill-down V4.7 dY por temp x octavo ===
    fig, ax = plt.subplots(figsize=(14, 7))
    temps = sorted({k.split("_")[0] for k in data["por_temp_bin"].keys()})
    cmap = plt.cm.tab10
    for ti, temp in enumerate(temps):
        dys = []
        ns_t = []
        for i in range(n_bins):
            key = f"{temp}_Q{i+1}"
            entry = data["por_temp_bin"].get(key, {})
            paired = entry.get("paired_DvsA", {})
            dys.append(paired.get("delta_yield_obs", np.nan))
            ns_t.append(entry.get("n", 0))
        ax.plot(range(n_bins), dys, marker="o", markersize=9, linewidth=2.5,
                 color=cmap(ti), label=f"Temp {temp}", alpha=0.8)
    ax.axhline(0, color="black", linestyle="--", alpha=0.4)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(octavos)
    ax.set_xlabel("Octavo de temporada")
    ax.set_ylabel("ΔYield V4.7 vs A baseline (pp)")
    ax.set_title("OOS drill-down: V4.7 dY por temp x octavo")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out2 = OUTDIR / f"oos_yield_por_temp_x_octavo_{suffix}.png"
    fig.savefig(out2, dpi=120)
    plt.close(fig)
    print(f"[OK] {out2}")


if __name__ == "__main__":
    base = ROOT / "analisis"
    for nb in (4, 8, 12):
        suffix = f"bin{nb}"
        path = base / f"yield_por_altura_temporada_{suffix}.json"
        if path.exists():
            print(f"\n=== Generating OOS {suffix} plots ===")
            run(path, suffix)
        else:
            print(f"[SKIP] {path} no existe")

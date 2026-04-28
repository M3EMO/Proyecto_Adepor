"""Genera graficos PNG de las curvas yield + hit rate por liga × cuartos
desde el JSON de si_hubiera_por_liga_cuartos.

Output:
  - graficos/yield_curva_por_liga.png      — yield Q1-Q4 por liga
  - graficos/hitrate_curva_por_liga.png    — hit rate Q1-Q4 por liga
  - graficos/yield_global_con_ci95.png     — yield agregado por liga + CI95
  - graficos/curva_combinada.png           — yield + hit rate side-by-side
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

TOP5 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}


def run(input_json: Path, suffix: str):
    """Genera plots desde un JSON especifico (bin4 o bin8)."""
    data = json.loads(input_json.read_text(encoding="utf-8"))
    ligas = data["ligas"]

    # Separar ligas con datos de cuartos vs sin
    ligas_completas = {l: d for l, d in ligas.items()
                       if d.get("quartiles") and len(d["quartiles"]) >= 2}
    ligas_solo_global = {l: d for l, d in ligas.items()
                          if l not in ligas_completas}

    print(f"Ligas con cuartiles: {len(ligas_completas)}")
    for l in sorted(ligas_completas.keys()):
        n_q = len(ligas_completas[l]["quartiles"])
        print(f"  {l}: {n_q} cuartiles cubiertos (etiqueta: {ligas_completas[l]['etiqueta']})")
    print(f"Ligas solo global: {len(ligas_solo_global)}")

    # Detectar n_bins desde el primer JSON con quartiles completos
    n_bins = 4
    for liga, d in ligas.items():
        qs = d.get("quartiles") or {}
        if qs:
            n_bins = max(n_bins, max(int(k.lstrip("Q")) for k in qs.keys()))
    # Claves internas del JSON (siempre "Q<n>") vs labels visuales
    letter_map = {4: "Q", 8: "O", 12: "D"}
    bin_letter = letter_map.get(n_bins, "B")
    word = {4: "cuartos", 8: "octavos", 12: "dozavos"}.get(n_bins, "bins")
    bin_word_singular = {4: "Cuarto", 8: "Octavo", 12: "Dozavo"}.get(n_bins, "Bin")
    dict_keys = [f"Q{i+1}" for i in range(n_bins)]
    display_labels = [f"{bin_letter}{i+1}" for i in range(n_bins)]
    quarter_labels = display_labels  # alias usado en plots
    print(f"Detectado N_BINS = {n_bins} (labels {display_labels[0]} a {display_labels[-1]})")

    # === GRAFICO 1: Yield por liga × cuartos ===
    fig, ax = plt.subplots(figsize=(12, 7))
    cmap_top = plt.cm.tab10
    cmap_other = plt.cm.Set2
    top_idx = 0
    other_idx = 0
    for liga in sorted(ligas_completas.keys()):
        qs = ligas_completas[liga]["quartiles"]
        ys = [qs.get(q, {}).get("yield_pct") for q in dict_keys]
        xs_with = [(i, y) for i, y in enumerate(ys) if y is not None]
        if len(xs_with) < 2:
            continue
        xs = [x for x, _ in xs_with]
        ys_clean = [y for _, y in xs_with]
        is_top = liga in TOP5
        if is_top:
            color = cmap_top(top_idx)
            top_idx += 1
            lw = 2.5
            marker = "o"
            ms = 9
        else:
            color = cmap_other(other_idx)
            other_idx += 1
            lw = 1.5
            marker = "s"
            ms = 6
        ax.plot(xs, ys_clean, marker=marker, markersize=ms, linewidth=lw,
                color=color, label=f"{liga} (N={ligas_completas[liga]['n']})",
                alpha=0.85 if is_top else 0.6)
    ax.axhline(0, color="black", linestyle="--", alpha=0.4, linewidth=1)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(quarter_labels)
    ax.set_xlabel(f"{bin_word_singular} temporal del periodo in-sample (2026-03-16 a 2026-04-26)")
    ax.set_ylabel("Yield % (unitario)")
    ax.set_title(f"Curva yield por liga x {word} in-sample")
    ax.legend(loc="upper right", fontsize=9, ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out1 = OUTDIR / f"yield_curva_por_liga_{suffix}.png"
    fig.savefig(out1, dpi=120)
    plt.close(fig)
    print(f"[OK] {out1}")

    # === GRAFICO 2: Hit rate por liga × cuartos ===
    fig, ax = plt.subplots(figsize=(12, 7))
    top_idx = 0
    other_idx = 0
    for liga in sorted(ligas_completas.keys()):
        qs = ligas_completas[liga]["quartiles"]
        hs = [qs.get(q, {}).get("hit_pct") for q in dict_keys]
        xs_with = [(i, h) for i, h in enumerate(hs) if h is not None]
        if len(xs_with) < 2:
            continue
        xs = [x for x, _ in xs_with]
        hs_clean = [h for _, h in xs_with]
        is_top = liga in TOP5
        color = cmap_top(top_idx) if is_top else cmap_other(other_idx)
        if is_top:
            top_idx += 1
            lw, ms = 2.5, 9
            marker = "o"
        else:
            other_idx += 1
            lw, ms = 1.5, 6
            marker = "s"
        ax.plot(xs, hs_clean, marker=marker, markersize=ms, linewidth=lw,
                color=color, label=f"{liga} (N={ligas_completas[liga]['n']})",
                alpha=0.85 if is_top else 0.6)
    ax.axhline(50, color="red", linestyle="--", alpha=0.4, linewidth=1, label="50% (random 1X2)")
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(quarter_labels)
    ax.set_xlabel(f"{bin_word_singular} temporal del periodo in-sample")
    ax.set_ylabel("Hit rate %")
    ax.set_title(f"Curva hit rate por liga x {word} in-sample")
    ax.legend(loc="lower right", fontsize=9, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 105)
    fig.tight_layout()
    out2 = OUTDIR / f"hitrate_curva_por_liga_{suffix}.png"
    fig.savefig(out2, dpi=120)
    plt.close(fig)
    print(f"[OK] {out2}")

    # === GRAFICO 3: Yield global por liga + CI95 (todas las ligas) ===
    ligas_ordenadas = sorted(ligas.items(), key=lambda x: -x[1]["yield_pct"])
    nombres = [l for l, _ in ligas_ordenadas]
    yields = [d["yield_pct"] for _, d in ligas_ordenadas]
    ci_los = [d["ci95_lo"] for _, d in ligas_ordenadas]
    ci_his = [d["ci95_hi"] for _, d in ligas_ordenadas]
    ns = [d["n"] for _, d in ligas_ordenadas]
    err_low = [y - lo for y, lo in zip(yields, ci_los)]
    err_high = [hi - y for y, hi in zip(yields, ci_his)]
    colors = ["tab:green" if l in TOP5 else "tab:gray" for l in nombres]

    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(nombres, yields, color=colors, alpha=0.7,
                   yerr=[err_low, err_high], capsize=5, ecolor="black")
    ax.axhline(0, color="black", linestyle="--", alpha=0.5)
    for i, (n, y) in enumerate(zip(ns, yields)):
        ax.text(i, y + (5 if y >= 0 else -10), f"N={n}", ha="center", fontsize=8)
    ax.set_ylabel("Yield % (unitario)")
    ax.set_title("Yield global por liga in-sample con CI95 paired (verde=TOP-5)")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    out3 = OUTDIR / f"yield_global_con_ci95_{suffix}.png"
    fig.savefig(out3, dpi=120)
    plt.close(fig)
    print(f"[OK] {out3}")

    # === GRAFICO 4: Combinado yield + hit + Brier (3 paneles) ===
    fig, axes = plt.subplots(1, 3, figsize=(24, 9))
    for ax_idx, (titulo, key, ylabel, ylim, ref_line) in enumerate([
        (f"Yield por liga x {word}", "yield_pct", "Yield %", None, 0),
        (f"Hit rate por liga x {word}", "hit_pct", "Hit rate %", (0, 105), 50),
        (f"Brier 1x2 por liga x {word}", "brier_avg", "Brier (menor=mejor)", None, 0.667),
    ]):
        ax = axes[ax_idx]
        top_idx = 0
        other_idx = 0
        for liga in sorted(ligas_completas.keys()):
            qs = ligas_completas[liga]["quartiles"]
            vs = [qs.get(q, {}).get(key) for q in dict_keys]
            xs_with = [(i, v) for i, v in enumerate(vs) if v is not None]
            if len(xs_with) < 2:
                continue
            xs = [x for x, _ in xs_with]
            vs_clean = [v for _, v in xs_with]
            is_top = liga in TOP5
            color = cmap_top(top_idx) if is_top else cmap_other(other_idx)
            if is_top:
                top_idx += 1
                lw, ms, marker = 2.5, 9, "o"
            else:
                other_idx += 1
                lw, ms, marker = 1.5, 6, "s"
            ax.plot(xs, vs_clean, marker=marker, markersize=ms, linewidth=lw,
                    color=color, label=f"{liga}", alpha=0.85 if is_top else 0.6)
        ax.axhline(ref_line, color="black", linestyle="--", alpha=0.4, linewidth=1,
                    label=f"ref {ref_line}" if key == "brier_avg" else None)
        ax.set_xticks(range(n_bins))
        ax.set_xticklabels(quarter_labels, fontsize=11)
        ax.set_xlabel(f"{bin_word_singular} temporal ({n_bins} bins)", fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(titulo, fontsize=13)
        ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=10)
        if ylim:
            ax.set_ylim(*ylim)
    granularidad = f"{n_bins} {word}"
    fig.suptitle(f"Snapshot in-sample 2026-03-16 a 2026-04-26 (TOP-5=marcadores grandes verdes) -- {granularidad}",
                  fontsize=14)
    fig.tight_layout()
    out4 = OUTDIR / f"curva_combinada_{suffix}.png"
    fig.savefig(out4, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {out4}")

    # === GRAFICO 5: Bar chart yield por liga (todas) con etiqueta + N + CI95 horizontal ===
    fig, ax = plt.subplots(figsize=(11, 8))
    sorted_data = sorted(ligas.items(), key=lambda x: x[1]["yield_pct"])
    nombres = [l for l, _ in sorted_data]
    yields = [d["yield_pct"] for _, d in sorted_data]
    ci_los = [d["ci95_lo"] for _, d in sorted_data]
    ci_his = [d["ci95_hi"] for _, d in sorted_data]
    ns = [d["n"] for _, d in sorted_data]
    colors = []
    for liga, d in sorted_data:
        if liga in TOP5:
            colors.append("tab:green")
        elif d["n"] < 12:
            colors.append("tab:gray")
        elif d["yield_pct"] >= 0:
            colors.append("tab:olive")
        else:
            colors.append("tab:red")
    err_low = [y - lo for y, lo in zip(yields, ci_los)]
    err_high = [hi - y for y, hi in zip(yields, ci_his)]
    y_pos = np.arange(len(nombres))
    ax.barh(y_pos, yields, color=colors, alpha=0.7,
            xerr=[err_low, err_high], capsize=4, ecolor="black")
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{l} (N={n})" for l, n in zip(nombres, ns)])
    ax.axvline(0, color="black", linestyle="--", alpha=0.5)
    ax.set_xlabel("Yield % (unitario) +/- CI95 paired")
    ax.set_title("Yield por liga in-sample\nverde=TOP-5 sig pos | oliva=positivo no-sig | rojo=negativo | gris=N<12")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    out5 = OUTDIR / f"yield_por_liga_horizontal_{suffix}.png"
    fig.savefig(out5, dpi=120)
    plt.close(fig)
    print(f"[OK] {out5}")


if __name__ == "__main__":
    base = ROOT / "analisis"
    for nb in (4, 8, 12):
        suffix = f"bin{nb}"
        path = base / f"si_hubiera_por_liga_{suffix}.json"
        if path.exists():
            print(f"\n=== Generating {suffix} plots ===")
            run(path, suffix)
        else:
            print(f"[SKIP] {path} no existe")

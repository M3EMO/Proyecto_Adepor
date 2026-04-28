"""Fase 4 (D): Timeline EMA por equipo.

Gráficos timeline (X=fecha, Y=EMA stat) por equipo individual.
Muestra evolución de cada stat clave con EMA largo + EMA corto.
También gráficos comparativos: top equipos por liga juntos.

Output:
  graficos/fase4/{liga}/{equipo}_timeline.png
  graficos/fase4/{liga}/_top_pos_evolucion.png      # comparativo top 5 ema_pos
  graficos/fase4/{liga}/_top_sots_evolucion.png     # comparativo top 5 ema_sots
  graficos/fase4/_global_arquetipos.png             # 6 equipos paradigma
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUTDIR = ROOT / "graficos" / "fase4"
OUTDIR.mkdir(parents=True, exist_ok=True)

# Stats clave para timeline (las más informativas según Fase 3)
STATS_TIMELINE = [
    ("pos", "Posesión %", "tab:blue"),
    ("sots", "Shots on target", "tab:green"),
    ("shot_pct", "Shot %", "tab:purple"),
    ("clearance", "Clearance", "tab:orange"),
    ("crosses", "Crosses total", "tab:red"),
    ("pass_pct", "Pass %", "tab:cyan"),
]


def safe_filename(s):
    s = re.sub(r"[^\w\s\-\(\)]", "", s, flags=re.UNICODE)
    return re.sub(r"\s+", "_", s.strip())[:80]


def cargar_timeline_equipo(con, liga, equipo):
    """Devuelve lista ordenada de snapshots del equipo con EMAs."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT fecha, n_acum, outcome,
               ema_l_pos, ema_c_pos,
               ema_l_sots, ema_c_sots,
               ema_l_shot_pct, ema_c_shot_pct,
               ema_l_clearance, ema_c_clearance,
               ema_l_crosses, ema_c_crosses,
               ema_l_pass_pct, ema_c_pass_pct
        FROM historial_equipos_stats
        WHERE liga=? AND equipo=?
        ORDER BY fecha
    """, (liga, equipo)).fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def grafico_timeline_equipo(snaps, liga, equipo, out_path):
    """Timeline 6 paneles (1 por stat) con EMA largo + corto + outcomes G/E/P."""
    if len(snaps) < 10:
        return False
    from datetime import datetime
    fechas = [datetime.strptime(s["fecha"][:10], "%Y-%m-%d") for s in snaps]
    outcomes = [s["outcome"] for s in snaps]

    fig, axes = plt.subplots(3, 2, figsize=(16, 11))
    axes = axes.flatten()
    for i, (key, label, color) in enumerate(STATS_TIMELINE):
        ax = axes[i]
        ema_l_key = f"ema_l_{key}"
        ema_c_key = f"ema_c_{key}"
        ema_l_vals = [s.get(ema_l_key) for s in snaps]
        ema_c_vals = [s.get(ema_c_key) for s in snaps]
        # Filter None
        valid_l = [(f, v) for f, v in zip(fechas, ema_l_vals) if v is not None]
        valid_c = [(f, v) for f, v in zip(fechas, ema_c_vals) if v is not None]
        if not valid_l:
            ax.axis("off")
            continue
        f_l, v_l = zip(*valid_l)
        f_c, v_c = zip(*valid_c)
        ax.plot(f_l, v_l, "-", color=color, linewidth=2, label="EMA largo (α=0.10)")
        ax.plot(f_c, v_c, "--", color=color, linewidth=1, alpha=0.6, label="EMA corto (α=0.40)")
        # Marcar G/E/P en eje X
        for j, (f, o) in enumerate(zip(fechas, outcomes)):
            color_o = {"G": "green", "E": "gray", "P": "red"}.get(o, "black")
            ax.scatter([f], [ax.get_ylim()[0]], marker="|", color=color_o, s=20, alpha=0.4)
        ax.set_title(f"{label} — {equipo}", fontsize=10)
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        if i == 0:
            ax.legend(loc="best", fontsize=8)
    fig.suptitle(f"FASE 4 — Timeline EMA stats: {liga} {equipo} (N partidos={len(snaps)})\n"
                  f"verde=ganado | gris=empate | rojo=perdido", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return True


def grafico_comparativo_liga(con, liga, key, label_stat, out_path, top_n=5):
    """Para una stat: top N equipos de la liga por ema_l final."""
    cur = con.cursor()
    # Equipos top por ema final
    rows = cur.execute(f"""
        WITH ultimo AS (
            SELECT liga, equipo, MAX(fecha) AS ult_fecha
            FROM historial_equipos_stats
            WHERE liga=? AND n_acum >= 15
            GROUP BY liga, equipo
        )
        SELECT h.equipo, h.ema_l_{key}
        FROM historial_equipos_stats h
        JOIN ultimo u ON h.liga=u.liga AND h.equipo=u.equipo AND h.fecha=u.ult_fecha
        WHERE h.ema_l_{key} IS NOT NULL
        ORDER BY h.ema_l_{key} DESC
        LIMIT {top_n}
    """, (liga,)).fetchall()
    if not rows:
        return False
    top_eq = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(13, 6))
    cmap = plt.cm.tab10
    from datetime import datetime
    for i, eq in enumerate(top_eq):
        snaps = cargar_timeline_equipo(con, liga, eq)
        valid = [(datetime.strptime(s["fecha"][:10], "%Y-%m-%d"), s.get(f"ema_l_{key}"))
                 for s in snaps if s.get(f"ema_l_{key}") is not None]
        if len(valid) < 5:
            continue
        f, v = zip(*valid)
        ax.plot(f, v, "-", color=cmap(i), linewidth=2,
                 label=f"{eq[:25]} ({snaps[-1]['ema_l_'+key]:.1f})", alpha=0.85)
    ax.set_xlabel("Fecha")
    ax.set_ylabel(label_stat)
    ax.set_title(f"{liga} — Top {top_n} equipos por EMA largo {label_stat}\n"
                  "(Línea = EMA largo α=0.10, valor entre paréntesis = último valor)", fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return True


def grafico_arquetipos(con, out_path):
    """6 equipos paradigma + posesivo extremo, defensivo extremo, drift."""
    arquetipos = [
        ("Espana", "Barcelona", "Posesivo extremo (España)"),
        ("Francia", "Paris Saint-Germain", "Posesivo extremo (Francia)"),
        ("Inglaterra", "Manchester City", "Posesivo elite (Inglaterra)"),
        ("Inglaterra", "Crystal Palace", "Defensivo (Inglaterra)"),
        ("Italia", "Hellas Verona", "Defensivo (Italia)"),
        ("Argentina", "Boca Juniors", "Mediano (Argentina)"),
    ]
    fig, ax = plt.subplots(figsize=(14, 7))
    cmap = plt.cm.tab10
    from datetime import datetime
    for i, (liga, eq, label) in enumerate(arquetipos):
        snaps = cargar_timeline_equipo(con, liga, eq)
        valid = [(datetime.strptime(s["fecha"][:10], "%Y-%m-%d"), s.get("ema_l_pos"))
                 for s in snaps if s.get("ema_l_pos") is not None]
        if len(valid) < 5:
            continue
        f, v = zip(*valid)
        ax.plot(f, v, "-", color=cmap(i), linewidth=2,
                 label=f"{label}: {eq} (N={len(snaps)}, ult={snaps[-1]['ema_l_pos']:.1f}%)", alpha=0.85)
    ax.axhline(55, color="red", linestyle="--", alpha=0.5, label="Umbral filtro (55%)")
    ax.axhline(45, color="green", linestyle="--", alpha=0.5, label="Umbral inverso (45%)")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("EMA largo Posesión %")
    ax.set_title("FASE 4 — Arquetipos de equipos: timeline EMA pos\n"
                  "Filtro Fase 3: si EMA > 55% local → no apostar (yield −49% sig OOS)", fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return True


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1. Gráfico arquetipos global
    print("=== Arquetipos globales ===")
    grafico_arquetipos(con, OUTDIR / "_global_arquetipos.png")
    print(f"  [OK] {OUTDIR / '_global_arquetipos.png'}")

    # 2. Per liga: comparativos top 5 por pos / sots
    print("\n=== Comparativos por liga ===")
    ligas = [r[0] for r in cur.execute(
        "SELECT DISTINCT liga FROM historial_equipos_stats ORDER BY liga")]
    for liga in ligas:
        liga_dir = OUTDIR / safe_filename(liga)
        liga_dir.mkdir(parents=True, exist_ok=True)
        for key, label, _ in STATS_TIMELINE[:3]:  # top 3 stats clave
            out_path = liga_dir / f"_top5_{key}_evolucion.png"
            if grafico_comparativo_liga(con, liga, key, label, out_path):
                print(f"  [OK] {out_path}")

    # 3. Per equipo: timeline individual (limitar a equipos con N>=20 y top 8 por liga)
    print("\n=== Timeline individual por equipo ===")
    n_total = 0
    for liga in ligas:
        liga_dir = OUTDIR / safe_filename(liga)
        # Top equipos por N partidos
        rows = cur.execute("""
            SELECT equipo, COUNT(*) FROM historial_equipos_stats
            WHERE liga=? GROUP BY equipo HAVING COUNT(*) >= 20
            ORDER BY COUNT(*) DESC LIMIT 12
        """, (liga,)).fetchall()
        for eq, n in rows:
            snaps = cargar_timeline_equipo(con, liga, eq)
            if len(snaps) < 20:
                continue
            out_path = liga_dir / f"{safe_filename(eq)}_timeline.png"
            if grafico_timeline_equipo(snaps, liga, eq, out_path):
                n_total += 1
        print(f"  {liga}: {len(rows)} equipos procesados")
    con.close()
    print(f"\n[OK] Total timelines individuales generadas: {n_total}")
    print(f"     Estructura: graficos/fase4/{{liga}}/{{equipo}}_timeline.png")


if __name__ == "__main__":
    main()

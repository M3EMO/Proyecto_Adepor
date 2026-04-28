"""Refinamiento del analisis 'Si Hubiera' por cuartos:
filtrando a top-5 ligas confiables (ARG/BRA/ING/NOR/TUR) y al camino C4.

Vistas:
  1. TOP-5 ligas + TODOS los caminos
  2. TOP-5 ligas + SOLO C4 (camino dominante, hit 76% global)
  3. Comparativo: TODAS ligas vs TOP-5 (para cuantificar 'descartar' Esp/Bol/Chi/etc)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT_DIR = Path(__file__).resolve().parent

TOP5 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
N_BOOTSTRAP = 2000


def parse_fecha(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%d/%m/%Y")
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None


def cargar_picks():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha = parse_fecha(row[0])
        if fecha is None:
            continue
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"):
            continue
        picks.append({
            "fecha": fecha, "partido": row[1], "liga": row[2],
            "pick": row[3], "cuota": row[4] or 0, "camino": row[5],
            "resultado": resultado, "stake": row[8] or 0, "pl": row[9] or 0,
        })
    return picks


def agg(sub, usar_stake_real):
    if usar_stake_real:
        sub = [p for p in sub if p["stake"] > 0]
    n = len(sub)
    if n == 0:
        return None
    n_gano = sum(1 for p in sub if p["resultado"] == "GANADA")
    if usar_stake_real:
        sum_stake = sum(p["stake"] for p in sub)
        sum_pl = sum(p["pl"] for p in sub)
    else:
        sum_stake = n
        sum_pl = sum((p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub)
    yield_pct = (sum_pl / sum_stake * 100) if sum_stake > 0 else 0.0
    return {"n": n, "n_gano": n_gano, "hit_pct": n_gano / n * 100,
            "yield_pct": yield_pct, "sum_stake": sum_stake, "sum_pl": sum_pl}


def boot_ci(sub, B=N_BOOTSTRAP, seed=42, usar_stake_real=False):
    if usar_stake_real:
        sub = [p for p in sub if p["stake"] > 0]
    if not sub:
        return None
    n = len(sub)
    rng = np.random.default_rng(seed)
    if usar_stake_real:
        stakes = np.array([p["stake"] for p in sub])
        pls = np.array([p["pl"] for p in sub])
    else:
        stakes = np.ones(n)
        pls = np.array([(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub])
    ys = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        s = stakes[idx].sum()
        p = pls[idx].sum()
        ys[b] = (p / s * 100) if s > 0 else 0
    return {"ci95_lo": float(np.percentile(ys, 2.5)),
            "ci95_hi": float(np.percentile(ys, 97.5))}


def imprimir_quartiles(picks, fmin, fmax, label, usar_stake_real, n_bins=8):
    N_BINS = n_bins
    print(f"=== {label} ===")
    if usar_stake_real:
        print(f"{'Q':<4} {'fechas':<13} {'N':>4} {'NG':>4} {'Hit%':>6} "
              f"{'Stake$':>11} {'P/L $':>11} {'Yield%':>8} {'CI95':>22}")
    else:
        print(f"{'Q':<4} {'fechas':<13} {'N':>4} {'NG':>4} {'Hit%':>6} "
              f"{'Yield%':>8} {'CI95':>22}")
    out = {}
    for q in range(N_BINS):
        f_lo = fmin + (fmax - fmin) * q / N_BINS
        f_hi = fmin + (fmax - fmin) * (q + 1) / N_BINS
        if q == N_BINS - 1:
            sub = [p for p in picks if p["fecha"] >= f_lo and p["fecha"] <= fmax]
        else:
            sub = [p for p in picks if p["fecha"] >= f_lo and p["fecha"] < f_hi]
        m = agg(sub, usar_stake_real)
        ci = boot_ci(sub, usar_stake_real=usar_stake_real)
        if m is None:
            print(f"Q{q+1:<3} (vacio)")
            continue
        ci_str = f"[{ci['ci95_lo']:+.2f}, {ci['ci95_hi']:+.2f}]" if ci else "—"
        if usar_stake_real:
            print(f"Q{q+1:<3} {f_lo.strftime('%m/%d')}-{f_hi.strftime('%m/%d')} "
                  f"{m['n']:>4} {m['n_gano']:>4} {m['hit_pct']:>6.2f} "
                  f"{m['sum_stake']:>11.0f} {m['sum_pl']:>+11.0f} "
                  f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
        else:
            print(f"Q{q+1:<3} {f_lo.strftime('%m/%d')}-{f_hi.strftime('%m/%d')} "
                  f"{m['n']:>4} {m['n_gano']:>4} {m['hit_pct']:>6.2f} "
                  f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
        out[f"Q{q+1}"] = {**m, **(ci or {}), "fecha_lo": f_lo.strftime("%Y-%m-%d"),
                          "fecha_hi": f_hi.strftime("%Y-%m-%d")}
    return out


def run(picks, n_bins: int, out_path: Path):
    if not picks:
        print("Sin picks")
        return
    label_map = {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}
    label_bins = label_map.get(n_bins, f"BIN_{n_bins}")
    fmin = min(p["fecha"] for p in picks)
    fmax = max(p["fecha"] for p in picks)
    print(f"\n{'='*70}")
    print(f"=== Refinamiento Si Hubiera: TOP-5 ligas + C4 (n_bins={n_bins}, {label_bins}) ===")
    print(f"{'='*70}")
    print(f"Fechas {fmin.strftime('%Y-%m-%d')} a {fmax.strftime('%Y-%m-%d')}")
    print(f"TOP-5 ligas: {sorted(TOP5)}")
    print(f"N picks total: {len(picks)}")
    picks_top5 = [p for p in picks if p["liga"] in TOP5]
    picks_top5_c4 = [p for p in picks_top5 if p["camino"] == "C4"]
    picks_no_top5 = [p for p in picks if p["liga"] not in TOP5]
    print(f"N TOP-5: {len(picks_top5)}  ({len(picks_top5)*100/len(picks):.1f}%)")
    print(f"N TOP-5 + C4: {len(picks_top5_c4)}  ({len(picks_top5_c4)*100/len(picks):.1f}%)")
    print(f"N descartado (Esp/Bol/Chi/Col/Ecu/Per/Uru/Ale/Fra/Ita): {len(picks_no_top5)}")
    print()

    payload = {
        "fmin": fmin.strftime("%Y-%m-%d"), "fmax": fmax.strftime("%Y-%m-%d"),
        "top5": sorted(TOP5), "n_bins": n_bins,
        "n_total": len(picks), "n_top5": len(picks_top5),
        "n_top5_c4": len(picks_top5_c4), "n_descartado": len(picks_no_top5),
    }

    # === 1. TOP-5 todos los caminos, vista TOTAL unitario ===
    payload["top5_unit_quartiles"] = imprimir_quartiles(
        picks_top5, fmin, fmax,
        f"TOP-5 LIGAS (todos los caminos, {label_bins}) -- yield unitario",
        usar_stake_real=False, n_bins=n_bins)
    print()
    payload["top5_stake_quartiles"] = imprimir_quartiles(
        picks_top5, fmin, fmax,
        f"TOP-5 LIGAS (todos los caminos, {label_bins}) -- stake $ real",
        usar_stake_real=True, n_bins=n_bins)
    print()
    payload["top5_c4_unit_quartiles"] = imprimir_quartiles(
        picks_top5_c4, fmin, fmax,
        f"TOP-5 LIGAS + SOLO C4 ({label_bins}) -- yield unitario",
        usar_stake_real=False, n_bins=n_bins)
    print()
    payload["top5_c4_stake_quartiles"] = imprimir_quartiles(
        picks_top5_c4, fmin, fmax,
        f"TOP-5 LIGAS + SOLO C4 ({label_bins}) -- stake $ real",
        usar_stake_real=True, n_bins=n_bins)
    print()

    # === Comparativo agregado: TODAS vs TOP-5 vs TOP-5+C4 ===
    print(f"=== COMPARATIVO AGREGADO (vista unitario, sin filtro stake) ===")
    print(f"{'Conjunto':<28} {'N':>4} {'NG':>4} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    for label, sub in [("TODAS las ligas", picks),
                         ("TOP-5 (Arg/Bra/Ing/Nor/Tur)", picks_top5),
                         ("TOP-5 + SOLO C4", picks_top5_c4)]:
        m = agg(sub, usar_stake_real=False)
        ci = boot_ci(sub)
        ci_str = f"[{ci['ci95_lo']:+.2f}, {ci['ci95_hi']:+.2f}]" if ci else "—"
        print(f"{label:<28} {m['n']:>4} {m['n_gano']:>4} {m['hit_pct']:>6.2f} "
              f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
    print()

    # === Stake real comparativo ===
    print(f"=== COMPARATIVO STAKE REAL ===")
    print(f"{'Conjunto':<28} {'N':>4} {'Hit%':>6} {'Stake$':>11} {'P/L $':>11} "
          f"{'Yield%':>8} {'CI95':>22}")
    for label, sub in [("TODAS las ligas", picks),
                         ("TOP-5 (Arg/Bra/Ing/Nor/Tur)", picks_top5),
                         ("TOP-5 + SOLO C4", picks_top5_c4)]:
        m = agg(sub, usar_stake_real=True)
        ci = boot_ci(sub, usar_stake_real=True)
        if m is None:
            continue
        ci_str = f"[{ci['ci95_lo']:+.2f}, {ci['ci95_hi']:+.2f}]" if ci else "—"
        print(f"{label:<28} {m['n']:>4} {m['hit_pct']:>6.2f} "
              f"{m['sum_stake']:>11.0f} {m['sum_pl']:>+11.0f} "
              f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
    print()

    # === Per liga del TOP-5 desglose primer-eighth vs last-eighth (drift por liga) ===
    print(f"=== Per-liga TOP-5: primer 25% vs ultimo 25% del periodo (octavos O1-O2 vs O7-O8) ===")
    print(f"{'Liga':<14} {'N_ini':>5} {'Y_ini':>8} {'N_fin':>5} {'Y_fin':>8} {'dY':>8}")
    f25 = fmin + (fmax - fmin) * 0.25
    f75 = fmin + (fmax - fmin) * 0.75
    for liga in sorted(TOP5):
        sub_l = [p for p in picks_top5 if p["liga"] == liga]
        sub_q1 = [p for p in sub_l if p["fecha"] < f25]
        sub_q4 = [p for p in sub_l if p["fecha"] >= f75]
        if not sub_q1 or not sub_q4:
            continue
        m1 = agg(sub_q1, usar_stake_real=False)
        m4 = agg(sub_q4, usar_stake_real=False)
        print(f"{liga:<14} {m1['n']:>5} {m1['yield_pct']:>+8.2f} "
              f"{m4['n']:>5} {m4['yield_pct']:>+8.2f} "
              f"{m4['yield_pct']-m1['yield_pct']:>+8.2f}")
    print()

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[OK] {out_path}")
    return payload


if __name__ == "__main__":
    picks = cargar_picks()
    for nb in (4, 8, 12):
        run(picks, n_bins=nb, out_path=OUT_DIR / f"si_hubiera_top5_y_c4_bin{nb}.json")

"""Analisis de la hoja 'Si Hubiera' (Backtest_Modelo.xlsx) por OCTAVOS temporales.

In-sample: 358 picks desde 2026-03-16. Cada pick: fecha, liga, camino, cuota,
resultado (GANADA/PERDIDA), stake $, P/L $.

JOIN con partidos_backtest (DB) provee: prob_1, prob_x, prob_2, goles_l/v
para calcular Brier 1x2 por partido.

Cortes:
  1. Octavos temporales (O1..O8) — ventanas iguales en fechas
  2. Stake>0 vs todos picks
  3. Por camino C1/C2/C2B/C3/C4/OU
  4. Por liga top-5

Output: tabla por octavo con N, hit%, yield%, Brier 1x2, P/L
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl
import numpy as np

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT_DIR = Path(__file__).resolve().parent

N_BOOTSTRAP = 2000


def parse_fecha(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y")
    except (ValueError, TypeError):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None


def cargar_picks():
    """Carga picks del Excel + JOIN con partidos_backtest para obtener probs y outcome."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    con = sqlite3.connect(DB)
    cur = con.cursor()
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha = parse_fecha(str(row[0]))
        if fecha is None:
            continue
        partido = row[1]
        liga = row[2]
        if not partido or " vs " not in partido:
            continue
        local, visita = partido.split(" vs ", 1)
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"):
            continue
        # JOIN con DB para obtener probs (in-sample real del motor)
        d = fecha.strftime("%Y-%m-%d")
        db_row = cur.execute("""
            SELECT prob_1, prob_x, prob_2, prob_o25, prob_u25, goles_l, goles_v
            FROM partidos_backtest
            WHERE substr(fecha,1,10)=? AND pais=? AND local=? AND visita=?
        """, (d, liga, local, visita)).fetchone()
        if db_row:
            p1, px, p2, po25, pu25, gl, gv = db_row
            outcome_1x2 = "1" if (gl or 0) > (gv or 0) else ("X" if (gl or 0) == (gv or 0) else "2")
        else:
            p1 = px = p2 = po25 = pu25 = None
            outcome_1x2 = None
        picks.append({
            "fecha": fecha, "partido": partido, "liga": liga,
            "pick": row[3], "cuota": row[4] or 0,
            "camino": row[5], "goles": row[6],
            "resultado": resultado, "stake": row[8] or 0, "pl": row[9] or 0,
            "prob_1": p1, "prob_x": px, "prob_2": p2,
            "prob_o25": po25, "prob_u25": pu25,
            "outcome_1x2": outcome_1x2,
        })
    con.close()
    return picks


def brier_1x2_partido(p):
    """Brier 1x2 score para un partido. None si faltan datos."""
    if p["prob_1"] is None or p["outcome_1x2"] is None:
        return None
    o = p["outcome_1x2"]
    o1 = 1 if o == "1" else 0
    ox = 1 if o == "X" else 0
    o2 = 1 if o == "2" else 0
    return (p["prob_1"] - o1) ** 2 + (p["prob_x"] - ox) ** 2 + (p["prob_2"] - o2) ** 2


def agg_picks(picks, usar_stake_real=True):
    """Agrega un grupo de picks. Si usar_stake_real=True, yield se computa solo
    sobre picks con stake>0. Si False, asume stake=1 unitario para todos."""
    if usar_stake_real:
        sub = [p for p in picks if p["stake"] > 0]
    else:
        sub = picks
    n = len(sub)
    if n == 0:
        return None
    n_gano = sum(1 for p in sub if p["resultado"] == "GANADA")
    if usar_stake_real:
        sum_stake = sum(p["stake"] for p in sub)
        sum_pl = sum(p["pl"] for p in sub)
    else:
        sum_stake = 0
        sum_pl = 0
        for p in sub:
            sum_stake += 1
            if p["resultado"] == "GANADA":
                sum_pl += (p["cuota"] - 1)
            else:
                sum_pl += -1
    yield_pct = (sum_pl / sum_stake * 100) if sum_stake > 0 else 0.0
    hit_pct = n_gano / n * 100 if n > 0 else 0.0
    # Brier 1x2 promedio sobre picks que tienen probs
    briers = [brier_1x2_partido(p) for p in sub]
    briers_valid = [b for b in briers if b is not None]
    brier_avg = sum(briers_valid) / len(briers_valid) if briers_valid else None
    return {
        "n": n, "n_gano": n_gano,
        "hit_pct": hit_pct,
        "yield_pct": yield_pct,
        "sum_stake": sum_stake, "sum_pl": sum_pl,
        "brier_avg": brier_avg, "n_brier": len(briers_valid),
    }


def bootstrap_yield_ci(picks, B=N_BOOTSTRAP, seed=42, usar_stake_real=True):
    if usar_stake_real:
        sub = [p for p in picks if p["stake"] > 0]
    else:
        sub = picks
    if not sub:
        return None
    n = len(sub)
    rng = np.random.default_rng(seed)
    yields = np.empty(B)
    if usar_stake_real:
        stakes = np.array([p["stake"] for p in sub])
        pls = np.array([p["pl"] for p in sub])
    else:
        stakes = np.ones(n)
        pls = np.array([(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub])
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        s = stakes[idx].sum()
        p = pls[idx].sum()
        yields[b] = (p / s * 100) if s > 0 else 0
    return {
        "yield_mean": float(yields.mean()),
        "ci95_lo": float(np.percentile(yields, 2.5)),
        "ci95_hi": float(np.percentile(yields, 97.5)),
    }


def run(picks, n_bins: int, out_path: Path):
    """Ejecuta analisis para una granularidad especifica (n_bins)."""
    label_map = {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}
    letter_map = {4: "Q", 8: "O", 12: "D"}
    label = label_map.get(n_bins, f"BIN_{n_bins}")
    bin_letter = letter_map.get(n_bins, "B")
    N_BINS = n_bins  # alias local, codigo legacy lo usa
    OUT = out_path
    print(f"\n{'='*70}")
    print(f"=== Analisis 'Si Hubiera' por {label} (n_bins={n_bins}) ===")
    print(f"{'='*70}")
    print(f"N picks total: {len(picks)}")
    if not picks:
        print("No hay picks para analizar")
        return None

    # Rango de fechas
    fechas = [p["fecha"] for p in picks]
    fmin, fmax = min(fechas), max(fechas)
    delta = (fmax - fmin).days
    print(f"Rango fechas: {fmin.strftime('%Y-%m-%d')} a {fmax.strftime('%Y-%m-%d')} ({delta} dias)")
    print()

    # === Vista 1: TODOS los picks (incluyendo stake=0 simulados con unidad) ===
    print(f"=== VISTA 1: TODOS los picks por {label} (yield unitario, simulando stake=1) ===")
    print(f"{'O':<4} {'fechas':<13} {'N':>4} {'NGana':>5} {'Hit%':>6} "
          f"{'Yield%':>8} {'CI95_lo':>8} {'CI95_hi':>8} {'Brier':>7}")
    payload = {"vista_total_unitario": {}, "vista_stake_real": {},
                "global_stake_real": None, "por_camino": {}, "por_liga": {},
                "n_bins": N_BINS}
    quartiles = {}
    for q in range(N_BINS):
        f_lo = fmin + (fmax - fmin) * q / N_BINS
        f_hi = fmin + (fmax - fmin) * (q + 1) / N_BINS
        if q == N_BINS - 1:
            f_hi_check = lambda f: f <= fmax
        else:
            f_hi_check = lambda f, fh=f_hi: f < fh
        sub = [p for p in picks if p["fecha"] >= f_lo and f_hi_check(p["fecha"])]
        m = agg_picks(sub, usar_stake_real=False)
        if m:
            ci = bootstrap_yield_ci(sub, usar_stake_real=False)
            br_str = f"{m['brier_avg']:.4f}" if m["brier_avg"] is not None else "  n/a "
            print(f"{bin_letter}{q+1:<3} {f_lo.strftime('%m/%d')}-{f_hi.strftime('%m/%d')} "
                  f"{m['n']:>4} {m['n_gano']:>5} {m['hit_pct']:>6.2f} "
                  f"{m['yield_pct']:>+8.2f} {ci['ci95_lo']:>+8.2f} {ci['ci95_hi']:>+8.2f} {br_str:>7}")
            quartiles[f"Q{q+1}"] = {
                "fecha_lo": f_lo.strftime("%Y-%m-%d"),
                "fecha_hi": f_hi.strftime("%Y-%m-%d"),
                "n": m["n"], "n_gano": m["n_gano"],
                "hit_pct": m["hit_pct"], "yield_pct": m["yield_pct"],
                "ci95_lo": ci["ci95_lo"], "ci95_hi": ci["ci95_hi"],
                "brier_avg": m["brier_avg"], "n_brier": m["n_brier"],
            }
    payload["vista_total_unitario"] = quartiles
    print()

    # === Vista 2: Solo stake>0 (apuestas operativas reales) ===
    print(f"=== VISTA 2: Solo apuestas con stake operativo ($ real) por {label} ===")
    print(f"{'O':<4} {'fechas':<13} {'N':>4} {'NGa':>4} {'Hit%':>6} "
          f"{'Stake$':>10} {'P/L $':>10} {'Yld%':>7} {'CI95_lo':>8} {'CI95_hi':>8} {'Brier':>7}")
    quartiles2 = {}
    for q in range(N_BINS):
        f_lo = fmin + (fmax - fmin) * q / N_BINS
        f_hi = fmin + (fmax - fmin) * (q + 1) / N_BINS
        if q == N_BINS - 1:
            f_hi_check = lambda f: f <= fmax
        else:
            f_hi_check = lambda f, fh=f_hi: f < fh
        sub = [p for p in picks if p["fecha"] >= f_lo and f_hi_check(p["fecha"])]
        m = agg_picks(sub, usar_stake_real=True)
        if m:
            ci = bootstrap_yield_ci(sub, usar_stake_real=True) or {"ci95_lo":0, "ci95_hi":0}
            br_str = f"{m['brier_avg']:.4f}" if m["brier_avg"] is not None else "  n/a "
            print(f"{bin_letter}{q+1:<3} {f_lo.strftime('%m/%d')}-{f_hi.strftime('%m/%d')} "
                  f"{m['n']:>4} {m['n_gano']:>4} {m['hit_pct']:>6.2f} "
                  f"{m['sum_stake']:>10.0f} {m['sum_pl']:>+10.0f} "
                  f"{m['yield_pct']:>+7.1f} {ci['ci95_lo']:>+8.1f} {ci['ci95_hi']:>+8.1f} {br_str:>7}")
            quartiles2[f"Q{q+1}"] = {
                "fecha_lo": f_lo.strftime("%Y-%m-%d"),
                "fecha_hi": f_hi.strftime("%Y-%m-%d"),
                "n": m["n"], "n_gano": m["n_gano"],
                "hit_pct": m["hit_pct"], "yield_pct": m["yield_pct"],
                "sum_stake": m["sum_stake"], "sum_pl": m["sum_pl"],
                "ci95_lo": ci["ci95_lo"], "ci95_hi": ci["ci95_hi"],
                "brier_avg": m["brier_avg"], "n_brier": m["n_brier"],
            }
    payload["vista_stake_real"] = quartiles2
    print()

    # Global stake real
    g = agg_picks(picks, usar_stake_real=True)
    g_ci = bootstrap_yield_ci(picks, usar_stake_real=True)
    print(f"=== GLOBAL stake real ===")
    print(f"  N={g['n']} ganados={g['n_gano']} hit={g['hit_pct']:.2f}%  "
          f"stake=${g['sum_stake']:,.0f}  P/L=${g['sum_pl']:+,.0f}  "
          f"yield={g['yield_pct']:+.2f}% CI95=[{g_ci['ci95_lo']:+.2f}, {g_ci['ci95_hi']:+.2f}]")
    payload["global_stake_real"] = {**g, **g_ci}
    print()

    # === Vista 3: Por camino (TODOS picks unitario) ===
    print(f"=== VISTA 3: Por camino (yield unitario, TODOS picks) ===")
    por_camino = defaultdict(list)
    for p in picks:
        por_camino[p["camino"]].append(p)
    print(f"{'Camino':<8} {'N':>5} {'NGana':>6} {'Hit%':>7} {'Yield%':>8} {'CI95':>22}")
    for camino in sorted(por_camino.keys()):
        sub = por_camino[camino]
        m = agg_picks(sub, usar_stake_real=False)
        ci = bootstrap_yield_ci(sub, usar_stake_real=False)
        if m and ci:
            ci_str = f"[{ci['ci95_lo']:+.2f}, {ci['ci95_hi']:+.2f}]"
            print(f"{camino:<8} {m['n']:>5} {m['n_gano']:>6} {m['hit_pct']:>7.2f} "
                  f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
            payload["por_camino"][camino] = {
                "n": m["n"], "hit_pct": m["hit_pct"], "yield_pct": m["yield_pct"],
                "ci95_lo": ci["ci95_lo"], "ci95_hi": ci["ci95_hi"],
            }
    print()

    # === Vista 4: Por liga top-8 (agregada) ===
    print(f"=== VISTA 4: Top 8 ligas por N picks (yield unitario, agregada) ===")
    por_liga = defaultdict(list)
    for p in picks:
        por_liga[p["liga"]].append(p)
    top = sorted(por_liga.items(), key=lambda x: -len(x[1]))[:8]
    print(f"{'Liga':<14} {'N':>5} {'NGana':>6} {'Hit%':>7} {'Yield%':>8} {'CI95':>22}")
    for liga, sub in top:
        m = agg_picks(sub, usar_stake_real=False)
        ci = bootstrap_yield_ci(sub, usar_stake_real=False)
        ci_str = f"[{ci['ci95_lo']:+.2f}, {ci['ci95_hi']:+.2f}]"
        print(f"{liga:<14} {m['n']:>5} {m['n_gano']:>6} {m['hit_pct']:>7.2f} "
              f"{m['yield_pct']:>+8.2f} {ci_str:>22}")
        payload["por_liga"][liga] = {
            "n": m["n"], "hit_pct": m["hit_pct"], "yield_pct": m["yield_pct"],
            "ci95_lo": ci["ci95_lo"], "ci95_hi": ci["ci95_hi"],
        }
    print()

    # === Vista 5: Liga x BIN (breakdown granular) ===
    print(f"=== VISTA 5: LIGA x {label} (yield unitario por bin) ===")
    headers_y = " ".join(f"{f'Y{bin_letter}{i+1}':>7}" for i in range(N_BINS))
    headers_h = " ".join(f"{f'H{bin_letter}{i+1}':>5}" for i in range(N_BINS))
    print(f"{'Liga':<14} {'N':>4} {'YGl%':>7} {headers_y} | {headers_h}")
    payload["liga_x_bin"] = {}
    for liga, sub in top:
        bins_data = {}
        ys = []
        hs = []
        for q in range(N_BINS):
            f_lo = fmin + (fmax - fmin) * q / N_BINS
            f_hi = fmin + (fmax - fmin) * (q + 1) / N_BINS
            if q == N_BINS - 1:
                sq = [p for p in sub if p["fecha"] >= f_lo and p["fecha"] <= fmax]
            else:
                sq = [p for p in sub if p["fecha"] >= f_lo and p["fecha"] < f_hi]
            mb = agg_picks(sq, usar_stake_real=False)
            if mb:
                bins_data[f"Q{q+1}"] = {"n": mb["n"], "hit_pct": mb["hit_pct"],
                                         "yield_pct": mb["yield_pct"],
                                         "brier_avg": mb["brier_avg"]}
                ys.append(f"{mb['yield_pct']:>+7.1f}")
                hs.append(f"{mb['hit_pct']:>5.0f}")
            else:
                ys.append("    n/a")
                hs.append("  n/a")
        m_glob = agg_picks(sub, usar_stake_real=False)
        print(f"{liga:<14} {m_glob['n']:>4} {m_glob['yield_pct']:>+7.1f} {' '.join(ys)} | {' '.join(hs)}")
        payload["liga_x_bin"][liga] = bins_data
    print()

    # === DIAGNOSTICO TENDENCIA ===
    print(f"=== DIAGNOSTICO TENDENCIA ===")
    yields_tot = [quartiles.get(f"Q{q+1}", {}).get("yield_pct", 0.0) for q in range(N_BINS)]
    hits_tot = [quartiles.get(f"Q{q+1}", {}).get("hit_pct", 0.0) for q in range(N_BINS)]
    print(f"Vista TOTAL unitario:")
    print(f"  Hit%:    {' '.join(f'{bin_letter}{i+1}={hits_tot[i]:.1f}' for i in range(N_BINS))}")
    print(f"  Yield%:  {' '.join(f'{bin_letter}{i+1}={yields_tot[i]:+.1f}' for i in range(N_BINS))}")
    if len(quartiles2) >= N_BINS // 2:
        yields_real = [quartiles2.get(f"Q{q+1}", {}).get("yield_pct", 0.0) for q in range(N_BINS)]
        hits_real = [quartiles2.get(f"Q{q+1}", {}).get("hit_pct", 0.0) for q in range(N_BINS)]
        print(f"Vista STAKE REAL:")
        print(f"  Hit%:    {' '.join(f'{bin_letter}{i+1}={hits_real[i]:.1f}' for i in range(N_BINS))}")
        print(f"  Yield%:  {' '.join(f'{bin_letter}{i+1}={yields_real[i]:+.1f}' for i in range(N_BINS))}")
    payload["tendencia"] = {
        "yield_total_unitario": yields_tot,
        "hit_total_unitario": hits_tot,
        "n_bins": N_BINS,
    }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    return payload


if __name__ == "__main__":
    picks = cargar_picks()
    for nb in (4, 8, 12):
        run(picks, n_bins=nb, out_path=OUT_DIR / f"si_hubiera_por_cuartos_bin{nb}.json")

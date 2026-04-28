"""adepor-6kw FASE 2: yield/hit/Brier por momento_bin x diff_pos.

Analisis comparativo de las features ampliadas (Fase 1) sobre:
  - IN-SAMPLE: picks reales de "Si Hubiera" JOIN partidos_con_features
  - OOS:       predicciones_oos_con_features (walk_forward_sistema_real
               + cuotas Pinnacle, con filtros operativos del motor)

Para cada (in-sample, OOS) y cada granularidad (bin4, bin8, bin12):
  1. Tabla por momento_bin (yield, hit, brier, N)
  2. Tabla por diff_pos bucket
  3. Cross: heatmap (momento_bin, diff_pos)
  4. Output JSON paralelo a las versiones anteriores

Output:
  analisis/fase2_in_sample_bin{4,8,12}.json
  analisis/fase2_oos_bin{4,8,12}.json
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

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT_DIR = Path(__file__).resolve().parent

# Filtros operativos (mismos que los otros scripts)
MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025

# Buckets de diff_pos
DIFF_POS_BUCKETS = [
    ("vis_mucho_mejor", -100, -5),
    ("vis_mejor", -4, -1),
    ("igual", 0, 0),
    ("loc_mejor", 1, 4),
    ("loc_mucho_mejor", 5, 100),
]


def parse_fecha_excel(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def diff_pos_bucket(diff):
    if diff is None:
        return None
    for name, lo, hi in DIFF_POS_BUCKETS:
        if lo <= diff <= hi:
            return name
    return None


def label_bin(n_bins):
    return {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}.get(n_bins, f"BIN{n_bins}")


def letter_bin(n_bins):
    return {4: "Q", 8: "O", 12: "D"}.get(n_bins, "B")


# ============================================================
# IN-SAMPLE
# ============================================================

def cargar_picks_in_sample(con):
    """Carga picks del Excel + JOIN con partidos_con_features."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    cur = con.cursor()
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha_db = parse_fecha_excel(row[0])
        if fecha_db is None:
            continue
        if row[7] not in ("GANADA", "PERDIDA"):
            continue
        partido = row[1]
        liga = row[2]
        if not partido or " vs " not in partido:
            continue
        local, visita = partido.split(" vs ", 1)
        cuota = row[4] or 0
        camino = row[5]
        resultado = row[7]
        stake = row[8] or 0
        pl = row[9] or 0
        # JOIN con partidos_con_features
        feat = cur.execute("""
            SELECT pct_temp, momento_bin_4, momento_octavo, momento_bin_12,
                   pos_local, pos_visita, pj_local, pj_visita, diff_pos
            FROM partidos_con_features
            WHERE liga=? AND fecha=? AND local=? AND visita=?
        """, (liga, fecha_db, local, visita)).fetchone()
        if not feat:
            continue
        pct, b4, b8, b12, pl_pos, pv_pos, pjl, pjv, dp = feat
        picks.append({
            "fecha": fecha_db, "liga": liga, "local": local, "visita": visita,
            "pick": row[3], "cuota": cuota, "camino": camino,
            "resultado": resultado, "stake": stake, "pl": pl,
            "pct_temp": pct, "bin_4": b4, "bin_8": b8, "bin_12": b12,
            "pos_local": pl_pos, "pos_visita": pv_pos,
            "pj_local": pjl, "pj_visita": pjv, "diff_pos": dp,
        })
    return picks


def yield_unit_picks(sub):
    n = len(sub)
    if n == 0:
        return None
    n_g = sum(1 for p in sub if p["resultado"] == "GANADA")
    pls = [(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub]
    return {"n": n, "n_gano": n_g, "hit_pct": n_g/n*100,
            "yield_pct": sum(pls)/n*100}


def yield_real_picks(sub):
    sub_s = [p for p in sub if p["stake"] > 0]
    n = len(sub_s)
    if n == 0:
        return None
    n_g = sum(1 for p in sub_s if p["resultado"] == "GANADA")
    s = sum(p["stake"] for p in sub_s)
    pl = sum(p["pl"] for p in sub_s)
    return {"n": n, "n_gano": n_g, "hit_pct": n_g/n*100,
            "yield_pct": (pl/s*100) if s > 0 else 0,
            "stake": s, "pl": pl}


def run_in_sample(picks, n_bins, out_path):
    label = label_bin(n_bins)
    letter = letter_bin(n_bins)
    bin_key = f"bin_{n_bins}"
    print(f"\n{'='*70}")
    print(f"=== FASE 2 IN-SAMPLE bin{n_bins} ({label}) ===")
    print(f"{'='*70}")
    print(f"N picks total: {len(picks)}")
    n_with_bin = sum(1 for p in picks if p.get(bin_key) is not None)
    n_with_pos = sum(1 for p in picks if p.get("diff_pos") is not None)
    print(f"  con momento_{bin_key}: {n_with_bin}")
    print(f"  con diff_pos: {n_with_pos}")
    print()

    payload = {"n_total": len(picks), "n_bins": n_bins,
                "n_con_bin": n_with_bin, "n_con_pos": n_with_pos,
                "filtro": "in_sample"}

    # === 1. Por momento_bin ===
    print(f"=== 1. Por momento_{bin_key} ===")
    print(f"{'Bin':<5} {'N_unit':>6} {'Hit%U':>6} {'YldU%':>7} | "
          f"{'N_real':>6} {'Hit%R':>6} {'YldR%':>7}")
    by_bin = defaultdict(list)
    for p in picks:
        b = p.get(bin_key)
        if b is not None:
            by_bin[b].append(p)
    payload["por_momento_bin"] = {}
    for b in sorted(by_bin.keys()):
        sub = by_bin[b]
        u = yield_unit_picks(sub)
        r = yield_real_picks(sub)
        u_str = f"{u['n']:>6} {u['hit_pct']:>6.1f} {u['yield_pct']:>+7.1f}" if u else f"{'-':>6} {'-':>6} {'-':>7}"
        r_str = f"{r['n']:>6} {r['hit_pct']:>6.1f} {r['yield_pct']:>+7.1f}" if r else f"{'-':>6} {'-':>6} {'-':>7}"
        print(f"{letter}{b+1:<4} {u_str} | {r_str}")
        payload["por_momento_bin"][f"{letter}{b+1}"] = {"unit": u, "real": r}

    # === 2. Por diff_pos bucket (con CI95 unitario) ===
    print()
    print(f"=== 2. Por diff_pos bucket (con CI95 bootstrap unitario) ===")
    print(f"{'Bucket':<22} {'N_unit':>6} {'Hit%U':>6} {'YldU%':>7} {'CI95':>20} | "
          f"{'N_real':>6} {'Hit%R':>6} {'YldR%':>7}")
    by_dp = defaultdict(list)
    for p in picks:
        b = diff_pos_bucket(p.get("diff_pos"))
        if b is not None:
            by_dp[b].append(p)
    payload["por_diff_pos"] = {}
    for name, lo, hi in DIFF_POS_BUCKETS:
        sub = by_dp.get(name, [])
        if not sub:
            continue
        u = yield_unit_picks(sub)
        r = yield_real_picks(sub)
        ci = bootstrap_picks_yield(sub) if u else None
        ci_str = f"[{ci['ci95_lo']:+.1f},{ci['ci95_hi']:+.1f}]" if ci else "—"
        sig = ("+" if ci and ci["ci95_lo"] > 0 else
               ("-" if ci and ci["ci95_hi"] < 0 else "0"))
        u_str = f"{u['n']:>6} {u['hit_pct']:>6.1f} {u['yield_pct']:>+7.1f}" if u else f"{'-':>6} {'-':>6} {'-':>7}"
        r_str = f"{r['n']:>6} {r['hit_pct']:>6.1f} {r['yield_pct']:>+7.1f}" if r else f"{'-':>6} {'-':>6} {'-':>7}"
        print(f"{name:<22} {u_str} {ci_str:>20} | {r_str} sig={sig}")
        payload["por_diff_pos"][name] = {
            "unit": u, "real": r,
            "ci95_lo_unit": ci["ci95_lo"] if ci else None,
            "ci95_hi_unit": ci["ci95_hi"] if ci else None,
            "sig_unit": sig,
        }

    # === 3. Cross momento_bin x diff_pos (yield unitario) ===
    print()
    print(f"=== 3. Cross momento_bin x diff_pos (yield unitario, N_min=5) ===")
    headers = " ".join(f"{name[:14]:>9}" for name, _, _ in DIFF_POS_BUCKETS)
    print(f"{'Bin':<5} {headers}")
    cross = defaultdict(lambda: defaultdict(list))
    for p in picks:
        b = p.get(bin_key)
        dp = diff_pos_bucket(p.get("diff_pos"))
        if b is not None and dp is not None:
            cross[b][dp].append(p)
    payload["cross_bin_x_diff_pos"] = {}
    for b in sorted(cross.keys()):
        cells = []
        bin_payload = {}
        for name, _, _ in DIFF_POS_BUCKETS:
            sub = cross[b].get(name, [])
            if len(sub) < 5:
                cells.append(f"{('n=' + str(len(sub))):>9}")
                bin_payload[name] = {"n": len(sub), "yield_pct": None}
            else:
                u = yield_unit_picks(sub)
                cells.append(f"{u['yield_pct']:>+9.1f}")
                bin_payload[name] = {"n": len(sub), "yield_pct": u["yield_pct"],
                                       "hit_pct": u["hit_pct"]}
        print(f"{letter}{b+1:<4} {' '.join(cells)}")
        payload["cross_bin_x_diff_pos"][f"{letter}{b+1}"] = bin_payload

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out_path}")
    return payload


# ============================================================
# OOS
# ============================================================

def cargar_oos(con):
    """Carga predicciones_oos_con_features (ya joineadas con features)."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT fecha, liga, temp, local, visita, outcome,
               prob_1, prob_x, prob_2, psch, pscd, psca,
               pct_temp, momento_bin_4, momento_octavo, momento_bin_12,
               pos_local, pos_visita, pj_local, pj_visita, diff_pos
        FROM predicciones_oos_con_features
    """).fetchall()
    out = []
    for r in rows:
        out.append({
            "fecha": r[0], "liga": r[1], "temp": r[2],
            "local": r[3], "visita": r[4], "outcome": r[5],
            "p1": r[6], "px": r[7], "p2": r[8],
            "c1": r[9], "cx": r[10], "c2": r[11],
            "pct_temp": r[12], "bin_4": r[13], "bin_8": r[14], "bin_12": r[15],
            "pos_local": r[16], "pos_visita": r[17],
            "pj_local": r[18], "pj_visita": r[19], "diff_pos": r[20],
        })
    return out


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_oos(p1, px, p2, c1, cx, c2, outcome):
    """Devuelve (apostado, stake, profit, brier)."""
    o1 = 1 if outcome == "1" else 0
    ox = 1 if outcome == "X" else 0
    o2 = 1 if outcome == "2" else 0
    brier = (p1-o1)**2 + (px-ox)**2 + (p2-o2)**2
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < MARGEN_MIN:
        return False, 0.0, 0.0, brier
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0, brier
    if prob * cuota - 1 < EV_MIN:
        return False, 0.0, 0.0, brier
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0, brier
    if label == outcome:
        return True, stake, stake*(cuota-1), brier
    return True, stake, -stake, brier


def agg_oos(rows, with_ci=False, B=1500, seed=42):
    """Yield/hit/brier agregados sobre lista de OOS rows.
    Si with_ci=True, agrega bootstrap CI95 sobre yield."""
    if not rows:
        return None
    n = len(rows)
    n_apost = 0
    n_gano = 0
    sum_stake = 0
    sum_pl = 0
    sum_brier = 0
    per_partido = []  # (stake, profit) para apostados
    for r in rows:
        ap, stk, prof, br = evaluar_oos(r["p1"], r["px"], r["p2"],
                                          r["c1"], r["cx"], r["c2"], r["outcome"])
        sum_brier += br
        if ap:
            n_apost += 1
            if prof > 0:
                n_gano += 1
            sum_stake += stk
            sum_pl += prof
            per_partido.append((stk, prof))
    out = {
        "n_pred": n, "n_apost": n_apost, "n_gano": n_gano,
        "stake": sum_stake, "pl": sum_pl,
        "yield_pct": (sum_pl/sum_stake*100) if sum_stake > 0 else 0,
        "hit_pct": (n_gano/n_apost*100) if n_apost > 0 else 0,
        "brier_avg": sum_brier/n,
    }
    if with_ci and per_partido:
        rng = np.random.default_rng(seed)
        n_a = len(per_partido)
        stakes = np.array([p[0] for p in per_partido])
        pls = np.array([p[1] for p in per_partido])
        yields = np.empty(B)
        for b in range(B):
            idx = rng.integers(0, n_a, size=n_a)
            s = stakes[idx].sum()
            p = pls[idx].sum()
            yields[b] = (p/s*100) if s > 0 else 0
        out["ci95_lo"] = float(np.percentile(yields, 2.5))
        out["ci95_hi"] = float(np.percentile(yields, 97.5))
        out["sig"] = "+" if out["ci95_lo"] > 0 else ("-" if out["ci95_hi"] < 0 else "0")
    return out


def bootstrap_picks_yield(picks, B=1500, seed=42):
    """CI95 yield unitario sobre lista de picks in-sample."""
    if not picks:
        return None
    n = len(picks)
    rng = np.random.default_rng(seed)
    pls = np.array([(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in picks])
    yields = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        yields[b] = pls[idx].mean() * 100
    return {"ci95_lo": float(np.percentile(yields, 2.5)),
            "ci95_hi": float(np.percentile(yields, 97.5))}


def _resumen_oos_section(rows, n_bins, label_section, payload_key, payload):
    """Subroutine: corre las 3 vistas (por bin, por diff_pos, cross) para una seccion."""
    letter = letter_bin(n_bins)
    bin_key = f"bin_{n_bins}"
    print(f"\n--- {label_section} (N={len(rows)}) ---")
    section = {}

    # 1. Por momento_bin
    print(f"{'Bin':<5} {'NPred':>5} {'NApost':>6} {'Hit%':>6} {'Yld%':>7} {'Brier':>7}")
    by_bin = defaultdict(list)
    for r in rows:
        b = r.get(bin_key)
        if b is not None:
            by_bin[b].append(r)
    section["por_momento_bin"] = {}
    for b in sorted(by_bin.keys()):
        sub = by_bin[b]
        m = agg_oos(sub)
        if m:
            print(f"{letter}{b+1:<4} {m['n_pred']:>5} {m['n_apost']:>6} {m['hit_pct']:>6.1f} "
                  f"{m['yield_pct']:>+7.1f} {m['brier_avg']:>7.4f}")
            section["por_momento_bin"][f"{letter}{b+1}"] = m

    # 2. Por diff_pos (con CI95)
    print(f"\n  Por diff_pos (con CI95 bootstrap):")
    by_dp = defaultdict(list)
    for r in rows:
        if (r.get("pj_local") or 0) < 3 or (r.get("pj_visita") or 0) < 3:
            continue
        b = diff_pos_bucket(r.get("diff_pos"))
        if b is not None:
            by_dp[b].append(r)
    section["por_diff_pos"] = {}
    for name, lo, hi in DIFF_POS_BUCKETS:
        sub = by_dp.get(name, [])
        if not sub:
            continue
        m = agg_oos(sub, with_ci=True)
        if m:
            ci_str = f"[{m.get('ci95_lo', 0):+.1f}, {m.get('ci95_hi', 0):+.1f}]"
            sig = m.get("sig", "?")
            print(f"  {name:<22} N={m['n_pred']:>5} NA={m['n_apost']:>4} hit={m['hit_pct']:>5.1f}% "
                  f"yld={m['yield_pct']:>+6.1f}% CI95={ci_str:<18} sig={sig}")
            section["por_diff_pos"][name] = m

    # 3. Cross (con CI95 sobre celdas con N_apostado >= 20)
    print(f"\n  Cross bin x diff_pos (N_apost>=10 muestra yield, >=20 muestra * sig):")
    headers = " ".join(f"{name[:14]:>10}" for name, _, _ in DIFF_POS_BUCKETS)
    print(f"  {'Bin':<5} {headers}")
    cross = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if (r.get("pj_local") or 0) < 3 or (r.get("pj_visita") or 0) < 3:
            continue
        b = r.get(bin_key)
        dp = diff_pos_bucket(r.get("diff_pos"))
        if b is not None and dp is not None:
            cross[b][dp].append(r)
    section["cross_bin_x_diff_pos"] = {}
    for b in sorted(cross.keys()):
        cells = []
        bin_payload = {}
        for name, _, _ in DIFF_POS_BUCKETS:
            sub = cross[b].get(name, [])
            with_ci = len(sub) >= 20  # CI95 solo si N suficiente
            m = agg_oos(sub, with_ci=with_ci) if sub else None
            if not m or m["n_apost"] < 10:
                n_a = m["n_apost"] if m else 0
                cells.append(f"{('n=' + str(n_a)):>10}")
                bin_payload[name] = {"n_apost": n_a, "yield_pct": None}
            else:
                # Marcar significancia con * si CI95 excluye 0
                sig = m.get("sig", "?")
                marker = "*" if sig in ("+", "-") else " "
                cells.append(f"{m['yield_pct']:>+9.1f}{marker}")
                bin_payload[name] = {
                    "n_pred": m["n_pred"], "n_apost": m["n_apost"],
                    "yield_pct": m["yield_pct"], "hit_pct": m["hit_pct"],
                    "ci95_lo": m.get("ci95_lo"), "ci95_hi": m.get("ci95_hi"),
                    "sig": m.get("sig"),
                }
        print(f"  {letter}{b+1:<4} {' '.join(cells)}")
        section["cross_bin_x_diff_pos"][f"{letter}{b+1}"] = bin_payload

    # Por momento_bin tambien con CI95
    section_bin_ci = {}
    for b in sorted(by_bin.keys()):
        m = agg_oos(by_bin[b], with_ci=True)
        if m:
            section_bin_ci[f"{letter}{b+1}"] = m
    section["por_momento_bin"] = section_bin_ci

    payload[payload_key] = section


def run_oos(rows, n_bins, out_path):
    label = label_bin(n_bins)
    letter = letter_bin(n_bins)
    bin_key = f"bin_{n_bins}"
    print(f"\n{'='*70}")
    print(f"=== FASE 2 OOS bin{n_bins} ({label}) ===")
    print(f"{'='*70}")
    print(f"N predicciones OOS: {len(rows)}")
    n_with_bin = sum(1 for r in rows if r.get(bin_key) is not None)
    n_with_pos = sum(1 for r in rows if r.get("diff_pos") is not None
                       and (r.get("pj_local") or 0) >= 3 and (r.get("pj_visita") or 0) >= 3)
    print(f"  con momento_{bin_key}: {n_with_bin}")
    print(f"  con diff_pos pj>=3: {n_with_pos}")

    payload = {"n_total": len(rows), "n_bins": n_bins,
                "n_con_bin": n_with_bin, "n_con_pos": n_with_pos,
                "filtro": "oos"}

    # === AGREGADO (todas las temps) ===
    _resumen_oos_section(rows, n_bins,
        f"AGREGADO (filtros M>={MARGEN_MIN} EV>={EV_MIN} K={KELLY_CAP})",
        "agregado", payload)

    # === POR TEMP ===
    print(f"\n=== DIVIDIDO POR TEMP ===")
    payload["por_temp"] = {}
    temps = sorted({r["temp"] for r in rows if r.get("temp") is not None})
    for temp in temps:
        rows_t = [r for r in rows if r.get("temp") == temp]
        sub_payload = {}
        _resumen_oos_section(rows_t, n_bins, f"TEMP {temp}", "data", sub_payload)
        payload["por_temp"][str(temp)] = sub_payload["data"]

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out_path}")
    return payload


# ============================================================
# MAIN
# ============================================================

def main():
    con = sqlite3.connect(DB)
    print("=== FASE 2 — Cargando data ===")
    picks_in = cargar_picks_in_sample(con)
    print(f"In-sample picks (con features): {len(picks_in)}")
    rows_oos = cargar_oos(con)
    print(f"OOS predicciones (con features): {len(rows_oos)}")
    con.close()

    for nb in (4, 8, 12):
        run_in_sample(picks_in, nb, OUT_DIR / f"fase2_in_sample_bin{nb}.json")
        run_oos(rows_oos, nb, OUT_DIR / f"fase2_oos_bin{nb}.json")


if __name__ == "__main__":
    main()

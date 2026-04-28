"""adepor-3ip Audit FULL: M.1, M.2, M.3 por liga × bin × año individual.

Pregunta usuario: aplicar mismo formato (separar siempre por año) a M.1 y M.2,
restringido al subset de (liga, bin) que aparece en in-sample 2026.

Reportes:
  M.1 (filtro liga TOP-5):
    Por año, yield TOP-5 vs no-TOP-5, restringido a ligas con picks 2026.
  M.2 (filtro n_acum<60):
    Por año, yield n_acum<60 vs n_acum>=60, restringido a (liga, bin) 2026.
  M.3 (filtro bin!=Q4):
    Ya cubierto por audit_M3_por_liga_bin_año.py — re-evaluar agregado.
  COMBO M.1+M.2 por año: yield del filtro completo, año a año.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT = Path(__file__).resolve().parent / "audit_M1_M2_M3_por_año_full.json"

LIGAS_TOP5 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]
N_ACUM_MAX = 60


def momento_bin_NEW(con, liga, fecha_str):
    cur = con.cursor()
    ano = int(fecha_str[:4])
    for temp in (ano, ano + 1):
        r = cur.execute("""
            SELECT fecha_inicio, fecha_fin FROM liga_calendario_temp
            WHERE liga=? AND temp=?
        """, (liga, temp)).fetchone()
        if not r: continue
        if r[0] <= fecha_str <= r[1]:
            f_min, f_max = r[0], r[1]
            r_pct = cur.execute(
                "SELECT julianday(?) - julianday(?), julianday(?) - julianday(?)",
                (fecha_str, f_min, f_max, f_min)).fetchone()
            delta_p, delta_t = r_pct[0], r_pct[1]
            if delta_t and delta_t > 0:
                pct = max(0.0, min(1.0, delta_p / delta_t))
                if pct < 0.25: return 0
                if pct < 0.50: return 1
                if pct < 0.75: return 2
                return 3
    return None


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05: return None
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(opts, key=lambda x: x[1])
    if not cuota or cuota <= 1.0 or prob * cuota - 1 < 0.03: return None
    stake = kelly(prob, cuota)
    if stake <= 0: return None
    return {"stake": stake,
            "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def yield_metrics(picks):
    n = sum(1 for p in picks if p)
    g = sum(1 for p in picks if p and p["gano"])
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    yld = pl / s * 100 if s > 0 else 0
    hit = g / n * 100 if n > 0 else 0
    pares = [(p["stake"], p["profit"]) for p in picks if p]
    if pares and len(pares) >= 5:
        rng = np.random.default_rng(42)
        sk = np.array([p[0] for p in pares]); pr = np.array([p[1] for p in pares])
        ys = []
        for _ in range(2000):
            idx = rng.integers(0, len(pares), size=len(pares))
            ss, pp = sk[idx].sum(), pr[idx].sum()
            if ss > 0: ys.append(pp / ss * 100)
        lo = float(np.percentile(ys, 2.5)) if ys else None
        hi = float(np.percentile(ys, 97.5)) if ys else None
    else:
        lo = hi = None
    return {"n_apost": n, "n_gano": g, "hit_pct": round(hit, 2),
            "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def parse_fecha(s):
    if not s: return None
    try:
        from datetime import datetime as _dt
        return _dt.strptime(str(s), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(str(s)[:10], "%Y-%m-%d").date()
        except: return None


def cargar_picks_2026():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None: continue
        fecha = parse_fecha(row[0])
        if fecha is None: continue
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"): continue
        partido = row[1] or ""
        local = visita = None
        for sep in [" vs ", " - ", " v ", "-"]:
            if sep in partido:
                parts = partido.split(sep, 1)
                if len(parts) == 2:
                    local, visita = parts[0].strip(), parts[1].strip()
                    break
        picks.append({
            "fecha_str": fecha.isoformat(), "local": local, "visita": visita,
            "liga": row[2], "cuota": float(row[4] or 0),
            "resultado": resultado,
            "stake": float(row[8] or 0), "pl": float(row[9] or 0),
        })
    return picks


def yield_real(picks_real, n_acum_dict=None, max_n_acum=None):
    """Yield $ real para in-sample 2026 con stake>0."""
    sub = [p for p in picks_real if p["stake"] > 0]
    if max_n_acum is not None and n_acum_dict is not None:
        sub = [p for p in sub
               if n_acum_dict.get((p["liga"], p["local"], p["fecha_str"])) is None
               or n_acum_dict.get((p["liga"], p["local"], p["fecha_str"])) < max_n_acum]
    s = sum(p["stake"] for p in sub)
    pl = sum(p["pl"] for p in sub)
    return (pl / s * 100) if s > 0 else 0, len(sub)


def main():
    con = sqlite3.connect(DB)

    print("=" * 95)
    print("AUDIT FULL POR AÑO: M.1, M.2, M.3 separados, mismo (liga, bin) que 2026")
    print("=" * 95)

    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.liga, p.temp, substr(p.fecha,1,10) as fecha, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga=p.liga AND h.equipo=p.local AND h.fecha < p.fecha AND h.n_acum>=5
                ORDER BY h.fecha DESC LIMIT 1) as n_acum_l
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca", "n_acum_l"]
    rows_d = [dict(zip(cols, r)) for r in rows]
    for r in rows_d:
        r["bin"] = momento_bin_NEW(con, r["liga"], r["fecha"])

    # In-sample 2026
    picks_26 = cargar_picks_2026()
    for p in picks_26:
        if p.get("liga") and p.get("local"):
            p["bin"] = momento_bin_NEW(con, p["liga"], p["fecha_str"])
            r = cur.execute("""
                SELECT n_acum FROM historial_equipos_stats
                WHERE liga=? AND equipo=? AND fecha < ? AND n_acum>=5
                ORDER BY fecha DESC LIMIT 1
            """, (p["liga"], p["local"], p["fecha_str"])).fetchone()
            p["n_acum_l"] = r[0] if r else None
        else:
            p["bin"] = None
            p["n_acum_l"] = None

    # Bins presentes en 2026 por liga
    bins_2026 = defaultdict(set)
    for p in picks_26:
        if p["liga"] and p["bin"] is not None:
            bins_2026[p["liga"]].add(p["bin"])

    payload = {"fecha": datetime.now().isoformat(), "tests": {}}

    # ========== M.1: ligas TOP-5 vs todas ==========
    print(f"\n{'='*95}")
    print("M.1 (filtro liga TOP-5) por año — yield agregado")
    print(f"{'='*95}")
    print(f"{'subset':<25} | {'2022':>22} | {'2023':>22} | {'2024':>22}")
    print("-" * 110)
    m1_data = {}
    for nombre, fn in [
        ("BASELINE (todas ligas)", lambda r: True),
        ("M.1 (solo TOP-5)",        lambda r: r["liga"] in LIGAS_TOP5),
        ("NO TOP-5 (resto)",        lambda r: r["liga"] not in LIGAS_TOP5),
    ]:
        row_str = f"{nombre:<25} | "
        m1_data[nombre] = {}
        for ano in [2022, 2023, 2024]:
            sub = [r for r in rows_d if r["temp"] == ano and fn(r)]
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                   r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            cell = f"N={m['n_apost']:>4} y={m['yield_pct']:>+6.1f} {ci}"
            row_str += f"{cell:>22} | "
            m1_data[nombre][str(ano)] = m
        print(row_str)
    payload["tests"]["M1_por_año"] = m1_data

    # ========== M.2: n_acum<60 vs >=60, restringido TOP-5, por año ==========
    print(f"\n{'='*95}")
    print("M.2 (filtro n_acum<60) por año — restringido a TOP-5 ligas")
    print(f"{'='*95}")
    print(f"{'subset':<35} | {'2022':>22} | {'2023':>22} | {'2024':>22}")
    print("-" * 110)
    m2_data = {}
    for nombre, fn in [
        ("TOP-5 baseline (sin M.2)", lambda r: r["liga"] in LIGAS_TOP5),
        ("TOP-5 + M.2 (n_acum<60)",  lambda r: r["liga"] in LIGAS_TOP5
                                      and (r["n_acum_l"] is None or r["n_acum_l"] < N_ACUM_MAX)),
        ("TOP-5 con n_acum>=60",     lambda r: r["liga"] in LIGAS_TOP5
                                      and r["n_acum_l"] is not None and r["n_acum_l"] >= N_ACUM_MAX),
    ]:
        row_str = f"{nombre:<35} | "
        m2_data[nombre] = {}
        for ano in [2022, 2023, 2024]:
            sub = [r for r in rows_d if r["temp"] == ano and fn(r)]
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                   r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            cell = f"N={m['n_apost']:>4} y={m['yield_pct']:>+6.1f} {ci}"
            row_str += f"{cell:>22} | "
            m2_data[nombre][str(ano)] = m
        print(row_str)
    payload["tests"]["M2_por_año"] = m2_data

    # ========== M.3: por (liga, bin) año a año, RESTRINGIDO al subset 2026 ==========
    print(f"\n{'='*95}")
    print("M.3 SELECTIVO: yield por (liga, bin) año a año, RESTRINGIDO al subset 2026")
    print(f"{'='*95}")
    print(f"  Para cada (liga, bin) presente en 2026, ¿qué pasaba en cada año OOS?")
    print()
    m3_subset = {}
    for liga in LIGAS_TOP5:
        bins = sorted(bins_2026.get(liga, []))
        if not bins: continue
        print(f"\n{liga} (bins 2026: {[f'Q{b+1}' for b in bins]}):")
        print(f"{'bin':<5} | {'2022':>22} | {'2023':>22} | {'2024':>22} | {'2026':>20}")
        m3_subset[liga] = {}
        for bin_v in bins:
            row_str = f"Q{bin_v+1}    | "
            m3_subset[liga][f"Q{bin_v+1}"] = {}
            for ano in [2022, 2023, 2024]:
                sub = [r for r in rows_d if r["liga"] == liga and r["temp"] == ano and r["bin"] == bin_v]
                picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
                m = yield_metrics(picks)
                ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:>+6.1f} {ci}"
                row_str += f"{cell:>22} | "
                m3_subset[liga][f"Q{bin_v+1}"][str(ano)] = m
            # In-sample 2026
            sub_26 = [p for p in picks_26 if p["liga"] == liga and p["bin"] == bin_v and p["stake"] > 0]
            if sub_26:
                s = sum(p["stake"] for p in sub_26); pl = sum(p["pl"] for p in sub_26)
                y26 = (pl / s * 100) if s > 0 else 0
                cell_26 = f"N={len(sub_26):>3} y={y26:>+6.1f}%"
            else:
                cell_26 = "(no datos)"
            row_str += f"{cell_26:>20}"
            print(row_str)
    payload["tests"]["M3_subset_2026_por_año"] = m3_subset

    # ========== COMBO M.1 + M.2 por año (estado actual V5.1.2) ==========
    print(f"\n{'='*95}")
    print(f"COMBO M.1 + M.2 (estado V5.1.2 actual, M.3 OFF) por año")
    print(f"  En el SUBSET de bins presentes en 2026 vs todos los bins")
    print(f"{'='*95}")
    print(f"{'subset':<60} | {'2022':>22} | {'2023':>22} | {'2024':>22}")
    print("-" * 130)
    combo = {}
    for nombre, fn in [
        ("TOP-5 + n_acum<60 (todos los bins)",
         lambda r: r["liga"] in LIGAS_TOP5 and (r["n_acum_l"] is None or r["n_acum_l"] < N_ACUM_MAX)),
        ("TOP-5 + n_acum<60 + bins ∈ 2026 subset",
         lambda r: r["liga"] in LIGAS_TOP5 and (r["n_acum_l"] is None or r["n_acum_l"] < N_ACUM_MAX)
                    and r["bin"] in bins_2026.get(r["liga"], set())),
    ]:
        row_str = f"{nombre:<60} | "
        combo[nombre] = {}
        for ano in [2022, 2023, 2024]:
            sub = [r for r in rows_d if r["temp"] == ano and fn(r)]
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                   r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            cell = f"N={m['n_apost']:>4} y={m['yield_pct']:>+6.1f} {ci}"
            row_str += f"{cell:>22} | "
            combo[nombre][str(ano)] = m
        print(row_str)
    payload["tests"]["combo_M1_M2_por_año"] = combo

    # In-sample 2026 stake real M.1 + M.2
    sub_26 = [p for p in picks_26 if p["stake"] > 0
              and p["liga"] in LIGAS_TOP5
              and (p.get("n_acum_l") is None or p["n_acum_l"] < N_ACUM_MAX)]
    s = sum(p["stake"] for p in sub_26); pl = sum(p["pl"] for p in sub_26)
    y26 = (pl / s * 100) if s > 0 else 0
    g = sum(1 for p in sub_26 if p["resultado"] == "GANADA")
    print(f"\n  IN-SAMPLE 2026 (stake $ real): N={len(sub_26)}, hit={g/len(sub_26)*100:.1f}%, "
          f"stake=${s:,.0f}, P/L=${pl:+,.0f}, yield={y26:+.1f}%")
    payload["tests"]["in_sample_2026_M1_M2"] = {
        "n": len(sub_26), "hit_pct": round(g/len(sub_26)*100, 2),
        "yield_pct": round(y26, 2), "stake": round(s, 2), "pl": round(pl, 2)
    }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

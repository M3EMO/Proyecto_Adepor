"""adepor-3ip Audit comparativo 2026 in-sample vs OOS historico bajo M.1+M.2+M.3,
condicionado al MISMO momento Q por liga.

Pregunta usuario: comparar yields en condiciones EQUIVALENTES (mismo liga, mismo
bin temporal calendario) para separar efecto regimen vs efecto timing.

Si 2026 in-sample tiene Argentina Q3 (Apertura mid), comparar contra OOS donde
Argentina tambien estuvo en Q3. Idem para EUR top en Q4 cierre.

Output:
  - Distribucion in-sample 2026 por (liga, bin_NEW).
  - Yield V0 2026 vs OOS por mismo (liga, bin_NEW).
  - Yield M.1+M.2 (sin M.3) por (liga, bin) — ¿similar 2026 vs OOS?
  - Yield M.1+M.2+M.3 NEW por (liga, bin)
  - Veredicto: ¿el regimen 2026 cambia el comportamiento, o es solo timing?
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
OUT = Path(__file__).resolve().parent / "audit_2026_vs_oos_por_liga_y_Q.json"

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


def lookup_n_acum(con, liga, equipo, fecha_str):
    cur = con.cursor()
    r = cur.execute("""
        SELECT n_acum FROM historial_equipos_stats
        WHERE liga=? AND equipo=? AND fecha < ? AND n_acum >= 5
        ORDER BY fecha DESC LIMIT 1
    """, (liga, equipo, fecha_str)).fetchone()
    return r[0] if r else None


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


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick_oos(p1, px, p2, c1, cx, c2, outcome):
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


def yield_pct(picks):
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    return (pl / s * 100) if s > 0 else 0


def yield_real_2026(picks):
    """Para in-sample 2026: usa stake real $."""
    s = sum(p["stake"] for p in picks)
    pl = sum(p["pl"] for p in picks)
    return (pl / s * 100) if s > 0 else 0


def n_apost(picks):
    return sum(1 for p in picks if p)


def main():
    con = sqlite3.connect(DB)

    # ==== 1. Picks 2026 in-sample con bin_NEW + n_acum ====
    print("=" * 80)
    print("Audit 2026 in-sample vs OOS por (liga, momento_bin NEW)")
    print("=" * 80)
    picks_26 = cargar_picks_2026()
    for p in picks_26:
        if p.get("liga") and p.get("local"):
            p["bin"] = momento_bin_NEW(con, p["liga"], p["fecha_str"])
            p["n_acum_l"] = lookup_n_acum(con, p["liga"], p["local"], p["fecha_str"])
        else:
            p["bin"] = None
            p["n_acum_l"] = None

    # Distribucion 2026
    print(f"\n=== Distribucion picks 2026 in-sample por (liga, bin_NEW) ===")
    print(f"{'liga':<14} | Q1 | Q2 | Q3 | Q4 | total")
    print("-" * 60)
    dist_26 = defaultdict(lambda: defaultdict(int))
    for p in picks_26:
        if p["liga"] and p["bin"] is not None:
            dist_26[p["liga"]][p["bin"]] += 1
    for liga in LIGAS_TOP5 + ["Brasil", "Espana", "Italia", "Francia", "Alemania"]:
        if liga not in dist_26: continue
        d = dist_26[liga]
        t = sum(d.values())
        print(f"{liga:<14} | {d.get(0, 0):>2} | {d.get(1, 0):>2} | {d.get(2, 0):>2} | {d.get(3, 0):>2} | {t:>5}")

    # ==== 2. Cargar OOS 2022/2023/2024 con bin_NEW + n_acum ====
    print("\n=== Cargando OOS 2022-2024 con bin_NEW + n_acum...")
    cur = con.cursor()
    rows_oos = cur.execute("""
        SELECT p.liga, p.temp, substr(p.fecha,1,10) as fecha, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga=p.liga AND h.equipo=p.local AND h.fecha < p.fecha AND h.n_acum>=5
                ORDER BY h.fecha DESC LIMIT 1) as n_acum_l
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca", "n_acum_l"]
    rows_oos = [dict(zip(cols, r)) for r in rows_oos]
    print(f"  N OOS total: {len(rows_oos):,}")
    # Enriquecer bin
    for r in rows_oos:
        r["bin"] = momento_bin_NEW(con, r["liga"], r["fecha"])

    # ==== 3. Comparativa por (liga, bin) ====
    print(f"\n=== Yield 2026 in-sample vs OOS POR (liga, bin) — apples-to-apples ===")
    print(f"  Para cada (liga, bin) presente en 2026, mostrar:")
    print(f"    - 2026 yield real ($)")
    print(f"    - OOS apilado (22+23+24) yield unitario, mismo (liga, bin)")
    print(f"    - Comparativa con/sin filtros M.2")
    print()
    print(f"{'liga':<11} {'bin':<3} | {'N_26':>4} {'Y_26%':>7} | {'N_oos':>5} {'Y_oos%':>7} | "
          f"{'N_26_M2':>7} {'Y_26_M2%':>9} | {'N_oos_M2':>8} {'Y_oos_M2%':>10}")
    print("-" * 110)

    payload = {"fecha": datetime.now().isoformat(), "comparativa": defaultdict(dict)}

    for liga in LIGAS_TOP5:
        for bin_v in [0, 1, 2, 3]:
            sub_26 = [p for p in picks_26 if p["liga"] == liga and p["bin"] == bin_v]
            sub_oos = [r for r in rows_oos if r["liga"] == liga and r["bin"] == bin_v]
            if not sub_26 and not sub_oos: continue

            # 2026 yield real (todas)
            sub_26_real = [p for p in sub_26 if p["stake"] > 0]
            y26 = yield_real_2026(sub_26_real) if sub_26_real else 0
            n26 = len(sub_26_real)

            # OOS yield unitario (todas)
            picks_oos = [evaluar_pick_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                                           r["psch"], r["pscd"], r["psca"], r["outcome"])
                         for r in sub_oos]
            y_oos = yield_pct(picks_oos)
            n_oos = n_apost(picks_oos)

            # Con M.2 (n_acum<60)
            sub_26_m2 = [p for p in sub_26_real if p.get("n_acum_l") is None or p["n_acum_l"] < N_ACUM_MAX]
            y26_m2 = yield_real_2026(sub_26_m2) if sub_26_m2 else 0
            n26_m2 = len(sub_26_m2)

            sub_oos_m2 = [r for r in sub_oos if r.get("n_acum_l") is None or r["n_acum_l"] < N_ACUM_MAX]
            picks_oos_m2 = [evaluar_pick_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                                              r["psch"], r["pscd"], r["psca"], r["outcome"])
                            for r in sub_oos_m2]
            y_oos_m2 = yield_pct(picks_oos_m2)
            n_oos_m2 = n_apost(picks_oos_m2)

            print(f"{liga:<11} Q{bin_v+1}  | {n26:>4} {y26:>+7.1f} | {n_oos:>5} {y_oos:>+7.1f} | "
                  f"{n26_m2:>7} {y26_m2:>+9.1f} | {n_oos_m2:>8} {y_oos_m2:>+10.1f}")

            payload["comparativa"][liga][f"Q{bin_v+1}"] = {
                "in_sample_2026": {"n_real": n26, "yield_real": round(y26, 1),
                                    "n_M2": n26_m2, "yield_M2": round(y26_m2, 1)},
                "oos_22_23_24": {"n_apost": n_oos, "yield_unit": round(y_oos, 1),
                                  "n_apost_M2": n_oos_m2, "yield_unit_M2": round(y_oos_m2, 1)},
            }

    # ==== 4. Veredicto: agregado por liga ====
    print(f"\n=== Agregado por liga TOP-5: si filtramos OOS al MISMO subset bin que 2026 ===")
    print(f"  Esto responde: '¿la calibracion OOS funciona en el subset que tenemos hoy?'")
    print(f"{'liga':<14} | {'N_oos_subset':>13} | {'Y_oos_subset%':>14} | {'N_2026':>7} | {'Y_2026%':>9}")
    veredicto = {}
    for liga in LIGAS_TOP5:
        # Bins presentes en 2026 para esta liga
        bins_26 = set(p["bin"] for p in picks_26 if p["liga"] == liga and p["bin"] is not None)
        if not bins_26: continue
        # OOS apilado restringido a esos bins
        sub_oos = [r for r in rows_oos if r["liga"] == liga and r["bin"] in bins_26]
        picks_oos = [evaluar_pick_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"])
                     for r in sub_oos]
        y_oos = yield_pct(picks_oos)
        # 2026 stake real
        sub_26 = [p for p in picks_26 if p["liga"] == liga and p["bin"] in bins_26 and p["stake"] > 0]
        y_26 = yield_real_2026(sub_26)
        print(f"{liga:<14} | {n_apost(picks_oos):>13} | {y_oos:>+14.1f} | {len(sub_26):>7} | {y_26:>+9.1f}")
        veredicto[liga] = {"bins_26": sorted(bins_26),
                            "oos_subset": {"n_apost": n_apost(picks_oos), "yield": round(y_oos, 1)},
                            "in_sample_2026": {"n": len(sub_26), "yield": round(y_26, 1)}}
    payload["veredicto_por_liga"] = veredicto

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

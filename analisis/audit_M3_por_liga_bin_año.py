"""adepor-3ip Audit M.3 selectivo por (liga, bin, año):

Pregunta usuario: ¿M.3 funciona DIFERENTE por año?
  Si yield Q4 Inglaterra fue +20 en 2022, +5 en 2023, -50 en 2024, hay DRIFT.
  Cualquier filtro M.3 calibrado en una temp NO se transfiere a otras.

Audit:
  Para cada (liga TOP-5, bin Q1-Q4, año 2022/2023/2024) sobre OOS Pinnacle:
    - N picks
    - Yield V0 unitario
    - CI95
    - ¿Sig negativo (CI95_hi < 0)? -> M.3 candidato bloqueo
    - ¿Sig positivo (CI95_lo > 0)? -> M.3 NO debe bloquear

Comparativa final: agregar in-sample 2026 al cuadro.
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
OUT = Path(__file__).resolve().parent / "audit_M3_por_liga_bin_año.json"

LIGAS_TOP5 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]


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
        picks.append({
            "fecha_str": fecha.isoformat(),
            "liga": row[2], "cuota": float(row[4] or 0),
            "resultado": resultado, "stake": float(row[8] or 0),
            "pl": float(row[9] or 0),
        })
    return picks


def yield_real_2026(picks):
    sub = [p for p in picks if p["stake"] > 0]
    s = sum(p["stake"] for p in sub)
    pl = sum(p["pl"] for p in sub)
    return (pl / s * 100) if s > 0 else 0, len(sub)


def main():
    con = sqlite3.connect(DB)
    print("=" * 90)
    print("Audit M.3 selectivo: yield V0 por (liga TOP-5, bin Q1-Q4, año 2022/2023/2024)")
    print("=" * 90)

    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, temp, substr(fecha,1,10) as fecha, local, visita, outcome,
               prob_1, prob_x, prob_2, psch, pscd, psca
        FROM predicciones_oos_con_features
    """).fetchall()
    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca"]
    rows_d = [dict(zip(cols, r)) for r in rows]
    for r in rows_d:
        r["bin"] = momento_bin_NEW(con, r["liga"], r["fecha"])

    # In-sample 2026
    picks_26 = cargar_picks_2026()
    for p in picks_26:
        if p.get("liga"):
            p["bin"] = momento_bin_NEW(con, p["liga"], p["fecha_str"])

    payload = {"fecha": datetime.now().isoformat(),
                "yield_por_liga_bin_año": defaultdict(lambda: defaultdict(dict))}

    # Tabla principal
    for liga in LIGAS_TOP5:
        print(f"\n{liga}:")
        print(f"{'bin':<5} | {'2022':>22} | {'2023':>22} | {'2024':>22} | {'2026 in-sample':>22} | RECOMENDACION")
        print("-" * 130)
        for bin_v in [0, 1, 2, 3]:
            row_str = f"Q{bin_v+1}    | "
            yields_anuales = {}
            for ano in [2022, 2023, 2024]:
                sub = [r for r in rows_d if r["liga"] == liga and r["temp"] == ano and r["bin"] == bin_v]
                if not sub:
                    row_str += f"{'-':>22} | "
                    yields_anuales[ano] = None
                    continue
                picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
                m = yield_metrics(picks)
                ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:>+6.1f} {ci_str}"
                row_str += f"{cell:>22} | "
                yields_anuales[ano] = m
            # In-sample 2026
            sub_26 = [p for p in picks_26 if p["liga"] == liga and p["bin"] == bin_v]
            sub_26_real = [p for p in sub_26 if p["stake"] > 0]
            if sub_26_real:
                y26, n26 = yield_real_2026(sub_26)
                cell_26 = f"N={n26:>3} y={y26:>+6.1f}%"
                row_str += f"{cell_26:>22} | "
            else:
                row_str += f"{'(no datos)':>22} | "

            # Recomendacion: si TODOS los anos OOS muestran yield < 0 (CI95_hi <0),
            # M.3 deberia bloquear este (liga, bin). Si AL MENOS 1 ano es positivo,
            # NO bloquear (regimen variable).
            sig_neg_count = 0
            sig_pos_count = 0
            mixed = 0
            for ano, m in yields_anuales.items():
                if m is None or m["ci95_lo"] is None:
                    continue
                if m["ci95_hi"] < 0:
                    sig_neg_count += 1
                elif m["ci95_lo"] > 0:
                    sig_pos_count += 1
                else:
                    mixed += 1
            if sig_neg_count >= 2:
                rec = "★ BLOQUEAR M.3 (sig neg en 2+ anos)"
            elif sig_pos_count >= 2:
                rec = "DEJAR PASAR (sig pos en 2+ anos)"
            elif sig_neg_count >= 1 and sig_pos_count == 0:
                rec = "Bloqueo dudoso (1 ano neg, otros mixed)"
            else:
                rec = "Mixed (no clara tendencia)"
            row_str += rec
            print(row_str)
            payload["yield_por_liga_bin_año"][liga][f"Q{bin_v+1}"] = {
                "yields_anuales": {str(k): v for k, v in yields_anuales.items()},
                "recomendacion": rec,
            }

    # Resumen final: ¿En que (liga, bin) M.3 SI tiene base OOS para bloquear?
    print(f"\n{'='*90}")
    print("RESUMEN: (liga, bin) candidatos para M.3 SELECTIVO por OOS multi-año")
    print(f"{'='*90}")
    print(f"{'(liga, bin)':<25} {'OOS 2022 y':>12} {'2023 y':>10} {'2024 y':>10} {'rec':<40}")
    candidatos_bloqueo = []
    for liga in LIGAS_TOP5:
        for bin_v in [0, 1, 2, 3]:
            data = payload["yield_por_liga_bin_año"][liga].get(f"Q{bin_v+1}")
            if not data: continue
            ys = data["yields_anuales"]
            y22 = ys.get("2022", {}).get("yield_pct") if ys.get("2022") else None
            y23 = ys.get("2023", {}).get("yield_pct") if ys.get("2023") else None
            y24 = ys.get("2024", {}).get("yield_pct") if ys.get("2024") else None
            rec = data["recomendacion"]
            if "BLOQUEAR" in rec or "dudoso" in rec.lower():
                key = f"{liga}, Q{bin_v+1}"
                y22_str = f"{y22:+6.1f}" if y22 is not None else "  -  "
                y23_str = f"{y23:+6.1f}" if y23 is not None else "  -  "
                y24_str = f"{y24:+6.1f}" if y24 is not None else "  -  "
                print(f"{key:<25} {y22_str:>12} {y23_str:>10} {y24_str:>10} {rec:<40}")
                candidatos_bloqueo.append({"liga": liga, "bin": bin_v + 1,
                                            "y22": y22, "y23": y23, "y24": y24, "rec": rec})
    payload["candidatos_M3_selectivo"] = candidatos_bloqueo

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

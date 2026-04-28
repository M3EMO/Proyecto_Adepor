"""adepor-3ip Audit dual:
  TAREA 2: validez estadistica de adaptacion motor por POSICION TABLA.
           Yield V0 por bucket pos_local sobre OOS 2024 con CI95 robusto.
  TAREA 3: re-evaluacion M.2/M.3 con calendario CORRECTO (post bug fix).
           ¿La calibracion OOS sigue valida tras el fix de momento_bin_4?
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "audit_posicion_y_M3_recalibracion.json"


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
        lo, hi = (float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))) if ys else (None, None)
    else:
        lo = hi = None
    return {"n_apost": n, "n_gano": g, "hit_pct": round(hit, 2),
            "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def pos_bucket(pos):
    if pos is None: return None
    if pos <= 3: return "TOP-3"
    if pos <= 6: return "TOP-6"
    if pos <= 12: return "MID"
    if pos <= 16: return "BOT-6"
    return "BOT-3"


# ============== T2: ADAPTACION MOTOR POR POSICION ==============
def cargar_oos_con_pos(con):
    """OOS 2024 con probs V0 + cuotas + posicion del local y visita."""
    cur = con.cursor()
    return cur.execute("""
        SELECT liga, temp, fecha, local, visita, outcome,
               prob_1, prob_x, prob_2, psch, pscd, psca,
               pos_local, pos_visita, diff_pos
        FROM predicciones_oos_con_features
        WHERE temp = 2024 AND pos_local IS NOT NULL AND pos_visita IS NOT NULL
    """).fetchall()


def main_t2(con):
    print("=" * 80)
    print("TAREA 2: Adaptacion motor por POSICION — validez estadistica OOS 2024")
    print("=" * 80)
    rows = cargar_oos_con_pos(con)
    print(f"  N OOS 2024 con pos completa: {len(rows):,}")
    print()

    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca",
            "pos_local", "pos_visita", "diff_pos"]
    rows_d = [dict(zip(cols, r)) for r in rows]

    # T2A. Yield por bucket pos_local
    print("=== T2A. Yield V0 por bucket pos_local ===")
    print(f"{'bucket':<8} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    t2a = {}
    for b in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
        sub = [r for r in rows_d if pos_bucket(r["pos_local"]) == b]
        if not sub: continue
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{b:<8} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t2a[b] = m

    # T2B. Yield por matchup pos_local x pos_visita (top vs bottom etc)
    print("\n=== T2B. Yield por matchup top vs bottom (significativo si CI95 excluye 0) ===")
    print(f"{'matchup':<25} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    matchups = {
        "TOP-3 vs BOT-3":  lambda r: pos_bucket(r["pos_local"]) == "TOP-3" and pos_bucket(r["pos_visita"]) == "BOT-3",
        "TOP-6 vs BOT-3":  lambda r: pos_bucket(r["pos_local"]) == "TOP-6" and pos_bucket(r["pos_visita"]) == "BOT-3",
        "BOT-3 vs TOP-3":  lambda r: pos_bucket(r["pos_local"]) == "BOT-3" and pos_bucket(r["pos_visita"]) == "TOP-3",
        "BOT-3 vs TOP-6":  lambda r: pos_bucket(r["pos_local"]) == "BOT-3" and pos_bucket(r["pos_visita"]) == "TOP-6",
        "MID vs MID":      lambda r: pos_bucket(r["pos_local"]) == "MID" and pos_bucket(r["pos_visita"]) == "MID",
        "TOP-vs-TOP":      lambda r: pos_bucket(r["pos_local"]) in ("TOP-3", "TOP-6") and pos_bucket(r["pos_visita"]) in ("TOP-3", "TOP-6"),
        "BOT-vs-BOT":      lambda r: pos_bucket(r["pos_local"]) in ("BOT-3", "BOT-6") and pos_bucket(r["pos_visita"]) in ("BOT-3", "BOT-6"),
    }
    t2b = {}
    for nombre, fn in matchups.items():
        sub = [r for r in rows_d if fn(r)]
        if not sub: continue
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<25} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t2b[nombre] = m

    # T2C. diff_pos buckets (gap en tabla)
    print("\n=== T2C. Yield por diff_pos (negativo = local mejor en tabla) ===")
    def diff_bucket(d):
        if d is None: return None
        if d <= -10: return "L<<V (local +10 mejor)"
        if d <= -3:  return "L<V"
        if d <= 3:   return "L~V (parejos)"
        if d <= 10:  return "L>V"
        return "L>>V (local +10 peor)"
    print(f"{'diff_pos':<28} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    t2c = {}
    for b in ["L<<V (local +10 mejor)", "L<V", "L~V (parejos)", "L>V", "L>>V (local +10 peor)"]:
        sub = [r for r in rows_d if diff_bucket(r["diff_pos"]) == b]
        if not sub: continue
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{b:<28} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t2c[b] = m

    return {"T2A_pos_local": t2a, "T2B_matchup": t2b, "T2C_diff_pos": t2c}


# ============== T3: RECALIBRACION M.2/M.3 ==============
def cargar_oos_24_con_n_acum(con):
    """OOS 2024 con prob V0 + cuotas + n_acum_l + momento_bin_4 (con calendario fix)."""
    # Importar la nueva funcion del motor para recalcular momento_bin_4
    sys.path.insert(0, str(ROOT / "src" / "nucleo"))
    # No vamos a importar motor_calculadora.py entera para no inicializar V13.
    # Reutilizamos consulta SQL directa al calendario.
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.liga, p.temp, p.fecha, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4 AS momento_bin_4_OLD,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga=p.liga AND h.equipo=p.local
                  AND h.fecha < p.fecha AND h.n_acum >= 5
                ORDER BY h.fecha DESC LIMIT 1) AS n_acum_l,
               (SELECT fecha_inicio FROM liga_calendario_temp lc
                WHERE lc.liga=p.liga AND lc.temp=p.temp) AS fec_ini,
               (SELECT fecha_fin FROM liga_calendario_temp lc
                WHERE lc.liga=p.liga AND lc.temp=p.temp) AS fec_fin
        FROM predicciones_oos_con_features p
        WHERE p.temp = 2024
    """).fetchall()
    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca",
            "momento_bin_4_OLD", "n_acum_l", "fec_ini", "fec_fin"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        # Recalcular momento_bin_4 con calendario (NEW)
        if d["fec_ini"] and d["fec_fin"]:
            try:
                from datetime import date as _date
                fp = _date.fromisoformat(d["fecha"][:10])
                fi = _date.fromisoformat(d["fec_ini"])
                ff = _date.fromisoformat(d["fec_fin"])
                if ff > fi:
                    pct = (fp - fi).days / (ff - fi).days
                    pct = max(0.0, min(1.0, pct))
                    if pct < 0.25: d["momento_bin_4_NEW"] = 0
                    elif pct < 0.50: d["momento_bin_4_NEW"] = 1
                    elif pct < 0.75: d["momento_bin_4_NEW"] = 2
                    else: d["momento_bin_4_NEW"] = 3
                else:
                    d["momento_bin_4_NEW"] = None
            except Exception:
                d["momento_bin_4_NEW"] = None
        else:
            d["momento_bin_4_NEW"] = None
        out.append(d)
    return out


def main_t3(con):
    print("\n" + "=" * 80)
    print("TAREA 3: Re-evaluar M.2/M.3 con calendario CORRECTO (post bug fix)")
    print("=" * 80)
    rows = cargar_oos_24_con_n_acum(con)
    print(f"  N OOS 2024: {len(rows):,}")

    # Comparar momento_bin_4_OLD vs NEW
    n_iguales = sum(1 for r in rows if r["momento_bin_4_OLD"] == r["momento_bin_4_NEW"])
    n_diff = len(rows) - n_iguales
    print(f"  Bins iguales OLD vs NEW: {n_iguales:,} ({100*n_iguales/len(rows):.1f}%)")
    print(f"  Bins distintos: {n_diff:,} ({100*n_diff/len(rows):.1f}%)")
    print()

    # T3A. Yield por momento_bin_4_NEW (filtro M.3 con calendario fix)
    print("=== T3A. Yield V0 por momento_bin_4 (con calendario CORRECTO) ===")
    print(f"{'bin':<10} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    t3a = {}
    for bin_v in [0, 1, 2, 3]:
        sub = [r for r in rows if r["momento_bin_4_NEW"] == bin_v]
        if not sub: continue
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        label = {0: "Q1_arr", 1: "Q2_ini", 2: "Q3_mit", 3: "Q4_cie"}[bin_v]
        print(f"{label:<10} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t3a[label] = m

    # T3B. Filtro M.3 (excluir Q4) con NEW vs OLD
    print("\n=== T3B. Filtro M.3 (excluir Q4) — comparativa OLD vs NEW calendario ===")
    print(f"{'subset':<35} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    t3b = {}
    for nombre, fn in [
        ("BASELINE (sin filtro M.3)",        lambda r: True),
        ("M.3 OLD (excluir bin_OLD=Q4)",     lambda r: r["momento_bin_4_OLD"] != 3),
        ("M.3 NEW (excluir bin_NEW=Q4)",     lambda r: r["momento_bin_4_NEW"] != 3),
    ]:
        sub = [r for r in rows if fn(r)]
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<35} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t3b[nombre] = m

    # T3C. Filtro M.2 (n_acum < 60) sigue igual? (no afectado por calendario)
    print("\n=== T3C. Filtro M.2 (n_acum_l < 60) — control (no afectado por calendario) ===")
    print(f"{'subset':<35} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
    t3c = {}
    for nombre, fn in [
        ("BASELINE",                                 lambda r: True),
        ("M.2 (excluir n_acum >= 60)",               lambda r: r["n_acum_l"] is None or r["n_acum_l"] < 60),
        ("M.2 + M.3 NEW (n_acum<60 AND bin!=Q4)",   lambda r: (r["n_acum_l"] is None or r["n_acum_l"] < 60) and r["momento_bin_4_NEW"] != 3),
    ]:
        sub = [r for r in rows if fn(r)]
        picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<35} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
        t3c[nombre] = m

    return {"T3A_yield_por_bin_NEW": t3a, "T3B_M3_OLD_vs_NEW": t3b,
            "T3C_M2_y_M2M3": t3c, "n_diff_OLD_NEW": n_diff,
            "n_iguales_OLD_NEW": n_iguales, "pct_iguales": round(100*n_iguales/len(rows), 1)}


def main():
    con = sqlite3.connect(DB)
    payload = {"fecha": datetime.now().isoformat()}
    payload["T2"] = main_t2(con)
    payload["T3"] = main_t3(con)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

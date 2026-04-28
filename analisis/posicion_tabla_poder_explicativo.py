"""adepor-6kw Fase 2: poder explicativo de posicion_tabla + momento_bin.

Tests sobre OOS Pinnacle 2022-24 N=4584 (con stats integradas) + N=7743
(con pos):

  T1. Yield por bucket pos_local (top-3, top-6, mid, bottom-6, bottom-3)
  T2. Yield por bucket diff_pos (gap entre local y visita en tabla)
  T3. Matriz pos_local x pos_visita (top vs bottom, mid vs mid, etc)
  T4. Yield por momento_bin x pos_local (interaction effect)
  T5. Yield del filtro V5.1 + filtro pos_diff (agrega valor incremental?)
  T6. Heterogeneidad por liga

Logica de pick: identica a Fase 4 (argmax con gap >= 5%, EV >= 3%, K cap 2.5%).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "posicion_tabla_poder_explicativo.json"


def cargar_oos(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4, p.pos_local, p.pos_visita, p.diff_pos,
               p.pj_local, p.pj_visita,
               (SELECT n_acum FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS n_acum_l
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def kelly_fraction(p, cuota, cap=0.025):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05:
        return False, 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return False, 0.0, 0.0
    if prob * cuota - 1 < 0.03:
        return False, 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return False, 0.0, 0.0
    if label == outcome:
        return True, stake, stake * (cuota - 1)
    return True, stake, -stake


def yield_metrics(rows, B=1000):
    n_apost = 0
    n_gano = 0
    sum_stake = 0.0
    sum_pl = 0.0
    pares = []
    for r in rows:
        ap, stk, prof = evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                      r["psch"], r["pscd"], r["psca"], r["outcome"])
        if ap:
            n_apost += 1
            if prof > 0:
                n_gano += 1
            sum_stake += stk
            sum_pl += prof
            pares.append((stk, prof))
    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
    hit = n_gano / n_apost * 100 if n_apost > 0 else 0
    if pares:
        rng = np.random.default_rng(42)
        stks = np.array([p[0] for p in pares])
        profs = np.array([p[1] for p in pares])
        ys = []
        for _ in range(B):
            idx = rng.integers(0, len(pares), size=len(pares))
            s, p = stks[idx].sum(), profs[idx].sum()
            if s > 0:
                ys.append(p / s * 100)
        ci_lo = float(np.percentile(ys, 2.5)) if ys else None
        ci_hi = float(np.percentile(ys, 97.5)) if ys else None
    else:
        ci_lo = ci_hi = None
    return {
        "n_pred": len(rows),
        "n_apost": n_apost,
        "n_gano": n_gano,
        "hit_pct": round(hit, 2),
        "yield_pct": round(yld, 2),
        "ci95_lo": round(ci_lo, 2) if ci_lo is not None else None,
        "ci95_hi": round(ci_hi, 2) if ci_hi is not None else None,
    }


def pos_bucket(pos, pj_max=20):
    """Categoriza posicion_tabla relativa al tamaño de liga."""
    if pos is None:
        return None
    if pos <= 3:
        return "TOP-3"
    elif pos <= 6:
        return "TOP-6"
    elif pos <= 12:
        return "MID"
    elif pos <= 16:
        return "BOT-6"
    else:
        return "BOT-3"


def diff_pos_bucket(diff):
    if diff is None:
        return None
    if diff <= -10:
        return "L<<V"   # local mucho peor que visita en tabla (pos numero alto = peor)
    elif diff <= -3:
        return "L<V"
    elif diff <= 3:
        return "L~V"
    elif diff <= 10:
        return "L>V"
    else:
        return "L>>V"


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS...")
    rows = cargar_oos(con)
    rows_full = [r for r in rows if r["pos_local"] is not None and r["pos_visita"] is not None]
    print(f"  N OOS total: {len(rows):,}")
    print(f"  N con pos completa: {len(rows_full):,}")

    payload = {
        "n_total_oos": len(rows),
        "n_con_pos": len(rows_full),
        "tests": {},
    }

    # ==========================================
    # T1. Yield por bucket pos_local
    # ==========================================
    print("\n=== T1. Yield por bucket pos_local ===")
    print(f"{'bucket':<10} {'NPred':>6} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    t1 = {}
    for b in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
        sub = [r for r in rows_full if pos_bucket(r["pos_local"]) == b]
        if not sub:
            continue
        m = yield_metrics(sub)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{b:<10} {m['n_pred']:>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t1[b] = m
    payload["tests"]["T1_pos_local"] = t1

    # ==========================================
    # T2. Yield por diff_pos bucket
    # ==========================================
    print("\n=== T2. Yield por diff_pos bucket (negativo = local mejor) ===")
    print(f"{'bucket':<10} {'NPred':>6} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    t2 = {}
    for b in ["L<<V", "L<V", "L~V", "L>V", "L>>V"]:
        sub = [r for r in rows_full if diff_pos_bucket(r["diff_pos"]) == b]
        if not sub:
            continue
        m = yield_metrics(sub)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{b:<10} {m['n_pred']:>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t2[b] = m
    payload["tests"]["T2_diff_pos"] = t2

    # ==========================================
    # T3. Matriz pos_local x pos_visita
    # ==========================================
    print("\n=== T3. Matriz pos_local x pos_visita (yield%) ===")
    print(f"{'pos_local':<10} | {'TOP-3':>15} | {'TOP-6':>15} | {'MID':>15} | {'BOT-6':>15} | {'BOT-3':>15}")
    print("-" * 105)
    t3 = {}
    for bl in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
        row_str = f"{bl:<10} | "
        t3[bl] = {}
        for bv in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
            sub = [r for r in rows_full if pos_bucket(r["pos_local"]) == bl and pos_bucket(r["pos_visita"]) == bv]
            if len(sub) >= 20:
                m = yield_metrics(sub, B=500)
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:+5.1f}"
                row_str += f"{cell:>15} | "
                t3[bl][bv] = m
            else:
                row_str += f"{'-':>15} | "
                t3[bl][bv] = None
        print(row_str)
    payload["tests"]["T3_matriz_pos"] = t3

    # ==========================================
    # T4. Momento_bin x pos_diff (interaction effect)
    # ==========================================
    print("\n=== T4. Momento x diff_pos (yield% por celda) ===")
    print(f"{'momento':<8} | {'L<<V':>15} | {'L<V':>15} | {'L~V':>15} | {'L>V':>15} | {'L>>V':>15}")
    print("-" * 95)
    t4 = {}
    for mb in [0, 1, 2, 3]:
        label = {0:"Q1_arr", 1:"Q2_ini", 2:"Q3_mit", 3:"Q4_cie"}[mb]
        row_str = f"{label:<8} | "
        t4[label] = {}
        for db in ["L<<V", "L<V", "L~V", "L>V", "L>>V"]:
            sub = [r for r in rows_full if r["momento_bin_4"] == mb and diff_pos_bucket(r["diff_pos"]) == db]
            if len(sub) >= 20:
                m = yield_metrics(sub, B=500)
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:+5.1f}"
                row_str += f"{cell:>15} | "
                t4[label][db] = m
            else:
                row_str += f"{'-':>15} | "
                t4[label][db] = None
        print(row_str)
    payload["tests"]["T4_momento_x_diff_pos"] = t4

    # ==========================================
    # T5. V5.1 vs V5.1 + filtro pos_diff (incremental)
    # ==========================================
    print("\n=== T5. Filtro V5.1 + filtro pos_diff (valor incremental) ===")
    print(f"{'filtro':<55} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    ligas_top = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
    # En OOS solo hay 4 de las TOP-5 (no Noruega). Ajustamos.
    ligas_top_oos = ligas_top & set(r["liga"] for r in rows_full)

    filtros = {
        "BASELINE (sin filtros)": rows_full,
        "V5.1 puro (TOP-4 OOS + n_acum<60 + Q!=3)":
            [r for r in rows_full
             if r["liga"] in ligas_top_oos
             and (r.get("n_acum_l") is None or r["n_acum_l"] < 60)
             and r["momento_bin_4"] != 3],
        "V5.1 + diff_pos NOT in (L<<V, L>>V) (mid-balanced)":
            [r for r in rows_full
             if r["liga"] in ligas_top_oos
             and (r.get("n_acum_l") is None or r["n_acum_l"] < 60)
             and r["momento_bin_4"] != 3
             and diff_pos_bucket(r["diff_pos"]) in ("L<V", "L~V", "L>V")],
        "V5.1 + pos_local <= 6 (locales TOP)":
            [r for r in rows_full
             if r["liga"] in ligas_top_oos
             and (r.get("n_acum_l") is None or r["n_acum_l"] < 60)
             and r["momento_bin_4"] != 3
             and r["pos_local"] is not None and r["pos_local"] <= 6],
        "V5.1 + pos_local > 6 (locales NO TOP)":
            [r for r in rows_full
             if r["liga"] in ligas_top_oos
             and (r.get("n_acum_l") is None or r["n_acum_l"] < 60)
             and r["momento_bin_4"] != 3
             and r["pos_local"] is not None and r["pos_local"] > 6],
    }
    t5 = {}
    for nombre, sub in filtros.items():
        m = yield_metrics(sub)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<55} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t5[nombre] = m
    payload["tests"]["T5_v51_plus_pos"] = t5

    # ==========================================
    # T6. Por liga
    # ==========================================
    print("\n=== T6. Yield por liga x bucket diff_pos ===")
    print(f"{'liga':<14} | {'L<<V':>12} | {'L<V':>12} | {'L~V':>12} | {'L>V':>12} | {'L>>V':>12}")
    print("-" * 90)
    t6 = {}
    ligas = sorted(set(r["liga"] for r in rows_full))
    for liga in ligas:
        row_str = f"{liga:<14} | "
        t6[liga] = {}
        for db in ["L<<V", "L<V", "L~V", "L>V", "L>>V"]:
            sub = [r for r in rows_full if r["liga"] == liga and diff_pos_bucket(r["diff_pos"]) == db]
            if len(sub) >= 15:
                m = yield_metrics(sub, B=500)
                cell = f"N={m['n_apost']:>3} y={m['yield_pct']:+5.1f}"
                row_str += f"{cell:>12} | "
                t6[liga][db] = m
            else:
                row_str += f"{'-':>12} | "
                t6[liga][db] = None
        print(row_str)
    payload["tests"]["T6_por_liga"] = t6

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

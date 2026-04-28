"""adepor-3ip Audit posicion FORWARD vs BACKWARD por temp:

FORWARD (en runtime): posicion acumulada hasta justo antes del partido.
  Es lo que el bookie ve en tiempo real. Predicciones_oos_con_features.pos_local
  fue calculada asi (forward cumulative).

BACKWARD (estructural): posicion FINAL de la temp como referencia constante.
  Para cada (liga, temp, formato, equipo): tomar la posicion al ultimo snapshot
  de la temp (post-partido final). Asignar a TODOS los partidos del equipo.

Pregunta: ¿pos_backward predice yield mejor que pos_forward?
  - pos_backward refleja calidad estructural ("¿es realmente un top o bottom?")
  - pos_forward refleja momento volatil del campeonato.

Audit por temp 2022/2023/2024 separadamente (LOTO no aplica aqui; la pos_backward
incluye info post-partido pero solo como AUDIT, no como pricing).

Output:
  - Yield V0 por bucket pos_FORWARD vs pos_BACKWARD por temp.
  - Test de divergencia: cuando |pos_forward - pos_backward| > 5, ¿el yield
    cambia segun cual usemos?
"""
from __future__ import annotations

import json
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
OUT = Path(__file__).resolve().parent / "audit_pos_forward_vs_backward.json"


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


def cargar_pos_backward(con):
    """Para cada (liga, temp, formato, equipo): ultima posicion en
    posiciones_tabla_snapshot = posicion FINAL backward.

    Retorna dict {(liga, temp, equipo): pos_final_backward}.
    Para Argentina con multiples formatos, prefiere 'anual' (mas estable).
    """
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pts.liga, pts.temp, pts.formato, pts.equipo, pts.posicion
        FROM posiciones_tabla_snapshot pts
        WHERE pts.fecha_snapshot = (
            SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
            WHERE liga = pts.liga AND temp = pts.temp AND formato = pts.formato
        )
    """).fetchall()
    out = {}
    for liga, temp, fm, eq, pos in rows:
        # Para Argentina prefer 'anual' (mas estable); para EUR usar 'liga'
        key = (liga, temp, eq)
        if key in out:
            # solo overwrite si current es menor prioridad (apertura/clausura)
            if fm == "anual":
                out[key] = pos  # anual gana siempre
            elif "apertura" in [out.get(("_fm_" + str(key), ))]:
                pass  # no overwrite
        else:
            out[key] = pos
    # Override con anual donde existe
    for liga, temp, fm, eq, pos in rows:
        if fm in ("anual", "liga"):
            out[(liga, temp, eq)] = pos
    return out


def cargar_oos_con_pos(con):
    """OOS 2022/2023/2024 con probs V0 + cuotas + pos_local/visita FORWARD."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, temp, fecha, local, visita, outcome,
               prob_1, prob_x, prob_2, psch, pscd, psca,
               pos_local, pos_visita, diff_pos
        FROM predicciones_oos_con_features
        WHERE pos_local IS NOT NULL AND pos_visita IS NOT NULL
    """).fetchall()
    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca",
            "pos_local_fwd", "pos_visita_fwd", "diff_pos_fwd"]
    return [dict(zip(cols, r)) for r in rows]


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS 2022/2023/2024 con pos forward...")
    rows = cargar_oos_con_pos(con)
    print(f"  N OOS total: {len(rows):,}")

    print("Cargando posicion FINAL backward por (liga, temp, equipo)...")
    pos_back = cargar_pos_backward(con)
    print(f"  N tuples (liga, temp, equipo) con pos_backward: {len(pos_back):,}")

    # Asignar pos_backward a cada row
    enriched = 0
    for r in rows:
        bl = pos_back.get((r["liga"], r["temp"], r["local"]))
        bv = pos_back.get((r["liga"], r["temp"], r["visita"]))
        r["pos_local_bwd"] = bl
        r["pos_visita_bwd"] = bv
        r["diff_pos_bwd"] = (bl - bv) if (bl and bv) else None
        if bl is not None and bv is not None:
            enriched += 1
    print(f"  N rows con pos_backward enriquecida: {enriched:,}")
    print()

    payload = {"fecha": datetime.now().isoformat(), "n_total": len(rows),
                "n_enriched_bwd": enriched, "tests": {}}

    # ============== AUDIT POR TEMP ==============
    for temp_test in [2022, 2023, 2024]:
        rows_t = [r for r in rows if r["temp"] == temp_test and r.get("pos_local_bwd")]
        if len(rows_t) < 100:
            continue
        print(f"=" * 80)
        print(f"TEMP {temp_test} (N={len(rows_t):,})")
        print(f"=" * 80)
        payload["tests"][str(temp_test)] = {}

        # Yield por bucket pos_local FORWARD
        print(f"\n--- Yield por bucket pos_local FORWARD (en runtime) ---")
        print(f"{'bucket':<8} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
        fwd = {}
        for b in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
            sub = [r for r in rows_t if pos_bucket(r["pos_local_fwd"]) == b]
            if not sub: continue
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                    r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            print(f"{b:<8} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
            fwd[b] = m
        payload["tests"][str(temp_test)]["forward"] = fwd

        # Yield por bucket pos_local BACKWARD
        print(f"\n--- Yield por bucket pos_local BACKWARD (final temp) ---")
        print(f"{'bucket':<8} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
        bwd = {}
        for b in ["TOP-3", "TOP-6", "MID", "BOT-6", "BOT-3"]:
            sub = [r for r in rows_t if pos_bucket(r["pos_local_bwd"]) == b]
            if not sub: continue
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                    r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            print(f"{b:<8} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
            bwd[b] = m
        payload["tests"][str(temp_test)]["backward"] = bwd

        # Divergencia: cuando |fwd - bwd| > 5, ¿el yield cambia?
        print(f"\n--- Divergencia |pos_fwd - pos_bwd| (motor capta calidad estructural?) ---")
        print(f"{'div_bucket':<25} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
        div_test = {}
        for nombre, fn in [
            ("|div_local| <= 2 (estable)",  lambda r: abs(r["pos_local_fwd"] - r["pos_local_bwd"]) <= 2),
            ("|div_local| 3-5 (medio)",     lambda r: 3 <= abs(r["pos_local_fwd"] - r["pos_local_bwd"]) <= 5),
            ("|div_local| > 5 (volatil)",   lambda r: abs(r["pos_local_fwd"] - r["pos_local_bwd"]) > 5),
            ("local SUBI fwd>bwd (mejorando final)",  lambda r: r["pos_local_fwd"] > r["pos_local_bwd"] + 3),
            ("local BAJÓ fwd<bwd (empeorando final)", lambda r: r["pos_local_fwd"] < r["pos_local_bwd"] - 3),
        ]:
            sub = [r for r in rows_t if r.get("pos_local_bwd") and r.get("pos_local_fwd") and fn(r)]
            if not sub: continue
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                    r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            print(f"{nombre:<40} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
            div_test[nombre] = m
        payload["tests"][str(temp_test)]["divergencia"] = div_test

        # Diff_pos backward (mismatches REALES de calidad)
        print(f"\n--- Diff_pos BACKWARD (mismatch real de calidad) ---")
        print(f"{'diff_bwd':<28} {'N_pred':>6} {'N_apost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
        def diff_b(d):
            if d is None: return None
            if d <= -10: return "L<<V (mismatch local mejor)"
            if d <= -3:  return "L<V"
            if d <= 3:   return "L~V (parejos REAL)"
            if d <= 10:  return "L>V"
            return "L>>V (mismatch local peor)"
        diff_bwd_t = {}
        for b in ["L<<V (mismatch local mejor)", "L<V", "L~V (parejos REAL)", "L>V", "L>>V (mismatch local peor)"]:
            sub = [r for r in rows_t if diff_b(r.get("diff_pos_bwd")) == b]
            if not sub: continue
            picks = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                    r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
            m = yield_metrics(picks)
            ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
            print(f"{b:<32} {len(sub):>6} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci:>22}")
            diff_bwd_t[b] = m
        payload["tests"][str(temp_test)]["diff_pos_bwd"] = diff_bwd_t
        print()

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

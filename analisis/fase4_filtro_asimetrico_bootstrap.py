"""Fase 4 (re-eval): paired bootstrap del filtro asimetrico ratio_pos.

Hipotesis: si EMA_pos_local / (EMA_pos_l + EMA_pos_v) > 0.55,
NO apostar local (motor pierde yield −18.2 sobre N=44 apostadas).

Compara yield(con_filtro) vs yield(sin_filtro) sobre OOS pareado, B=2000.

Output: analisis/fase4_filtro_asimetrico_bootstrap.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "fase4_filtro_asimetrico_bootstrap.json"

RATIO_CUT = 0.55
N_ACUM_MIN = 10
B = 2000
SEED = 42


def kelly_fraction(p, cuota, cap=0.025):
    if cuota <= 1 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, cap))


def evaluar_oos(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05:
        return None
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return None
    if prob * cuota - 1 < 0.03:
        return None
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return None
    profit = stake * (cuota - 1) if label == outcome else -stake
    return label, stake, profit


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2,
               p.psch, p.pscd, p.psca,
               (SELECT ema_l_pos FROM historial_equipos_stats
                 WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                 ORDER BY fecha DESC LIMIT 1) AS pos_l,
               (SELECT ema_l_pos FROM historial_equipos_stats
                 WHERE liga=p.liga AND equipo=p.visita AND fecha < p.fecha
                 ORDER BY fecha DESC LIMIT 1) AS pos_v,
               (SELECT n_acum FROM historial_equipos_stats
                 WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                 ORDER BY fecha DESC LIMIT 1) AS n_l,
               (SELECT n_acum FROM historial_equipos_stats
                 WHERE liga=p.liga AND equipo=p.visita AND fecha < p.fecha
                 ORDER BY fecha DESC LIMIT 1) AS n_v
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = [d[0] for d in cur.description]
    data = [dict(zip(cols, r)) for r in rows]
    con.close()

    data = [r for r in data
            if r["pos_l"] is not None and r["pos_v"] is not None
            and (r.get("n_l") or 0) >= N_ACUM_MIN
            and (r.get("n_v") or 0) >= N_ACUM_MIN]

    # Construir vector de stake/profit por OOS bajo cada politica
    for r in data:
        ev = evaluar_oos(r["prob_1"], r["prob_x"], r["prob_2"],
                          r["psch"], r["pscd"], r["psca"], r["outcome"])
        if ev is None:
            r["stake_base"] = 0.0
            r["pl_base"] = 0.0
            r["label"] = None
        else:
            r["label"], r["stake_base"], r["pl_base"] = ev
        # Filtro: si label=1 y ratio >cut → no apuesta
        ratio = r["pos_l"] / (r["pos_l"] + r["pos_v"]) if (r["pos_l"] + r["pos_v"]) > 0 else 0.5
        r["ratio"] = ratio
        if r["label"] == "1" and ratio > RATIO_CUT:
            r["stake_filt"] = 0.0
            r["pl_filt"] = 0.0
        else:
            r["stake_filt"] = r["stake_base"]
            r["pl_filt"] = r["pl_base"]

    n_total = len(data)
    n_apost_base = sum(1 for r in data if r["stake_base"] > 0)
    n_apost_filt = sum(1 for r in data if r["stake_filt"] > 0)
    n_blocked = n_apost_base - n_apost_filt
    sum_stake_base = sum(r["stake_base"] for r in data)
    sum_pl_base = sum(r["pl_base"] for r in data)
    sum_stake_filt = sum(r["stake_filt"] for r in data)
    sum_pl_filt = sum(r["pl_filt"] for r in data)
    yield_base = sum_pl_base / sum_stake_base * 100 if sum_stake_base > 0 else 0
    yield_filt = sum_pl_filt / sum_stake_filt * 100 if sum_stake_filt > 0 else 0
    delta = yield_filt - yield_base

    print(f"N OOS (n_acum>=10 ambos): {n_total}")
    print(f"N apostadas base:    {n_apost_base}")
    print(f"N apostadas filtro:  {n_apost_filt}  (bloqueadas={n_blocked})")
    print(f"Yield base:    {yield_base:>+6.2f}%  PL={sum_pl_base:+.4f}")
    print(f"Yield filtro:  {yield_filt:>+6.2f}%  PL={sum_pl_filt:+.4f}")
    print(f"Delta yield (filtro-base): {delta:>+6.2f}pp")

    # Paired bootstrap
    print(f"\n=== Paired bootstrap (B={B}) ===")
    rng = np.random.default_rng(SEED)
    deltas = np.zeros(B)
    n = len(data)
    stakes_b = np.array([r["stake_base"] for r in data])
    pls_b = np.array([r["pl_base"] for r in data])
    stakes_f = np.array([r["stake_filt"] for r in data])
    pls_f = np.array([r["pl_filt"] for r in data])
    for b in range(B):
        idx = rng.integers(0, n, n)
        sb = stakes_b[idx].sum()
        pb = pls_b[idx].sum()
        sf = stakes_f[idx].sum()
        pf = pls_f[idx].sum()
        yb = pb / sb * 100 if sb > 0 else 0
        yf = pf / sf * 100 if sf > 0 else 0
        deltas[b] = yf - yb
    p25 = float(np.percentile(deltas, 2.5))
    p975 = float(np.percentile(deltas, 97.5))
    p_pos = float((deltas > 0).mean())
    print(f"Delta yield CI95: [{p25:>+6.2f}, {p975:>+6.2f}]pp")
    print(f"P(delta > 0) = {p_pos:.3f}")
    sig = "★ SIGNIFICATIVO" if p25 > 0 else "✗ NO sig"
    print(f"  → {sig}")

    payload = {
        "ratio_cut": RATIO_CUT,
        "n_acum_min": N_ACUM_MIN,
        "n_total": n_total,
        "n_apost_base": n_apost_base,
        "n_apost_filt": n_apost_filt,
        "n_blocked": n_blocked,
        "yield_base_pct": yield_base,
        "yield_filt_pct": yield_filt,
        "delta_yield_pp": delta,
        "ci95": [p25, p975],
        "p_delta_positive": p_pos,
        "B": B,
        "seed": SEED,
        "significativo": p25 > 0,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

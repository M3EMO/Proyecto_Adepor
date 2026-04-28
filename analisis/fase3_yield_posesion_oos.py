"""Fase 3: yield OOS condicionado en posesion + bin (4/8/12) + por temp + por liga.

Setup: predicciones_oos_con_features (ya tiene momento_bin + diff_pos)
JOIN con stats_partido_espn (h_pos, a_pos) para condicionar.

Para cada granularidad y temp:
  1. yield/hit/Brier por bucket de posesion local
  2. cross matrix: pos_bucket x momento_bin
  3. cross matrix: pos_bucket x diff_pos
  4. por liga
  5. por equipo (TOP-N)

Filtros operativos: MARGEN>=0.05, EV>=0.03, KELLY=0.025

Output:
  analisis/fase3_yield_posesion_oos_bin{4,8,12}.json
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
OUT_DIR = Path(__file__).resolve().parent

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025

POS_BUCKETS = [
    ("muy_baja", 0, 35),
    ("baja", 35, 45),
    ("media", 45, 55),
    ("alta", 55, 65),
    ("muy_alta", 65, 100),
]


def pos_bucket(pct):
    if pct is None:
        return None
    for name, lo, hi in POS_BUCKETS:
        if lo <= pct < hi:
            return name
    return None


def label_bin(n):
    return {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}.get(n, f"BIN{n}")


def letter_bin(n):
    return {4: "Q", 8: "O", 12: "D"}.get(n, "B")


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar(p1, px, p2, c1, cx, c2, outcome):
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


def agg(rows, with_ci=False, B=1500, seed=42):
    if not rows:
        return None
    n = len(rows)
    n_apost = 0
    n_gano = 0
    sum_stake = 0
    sum_pl = 0
    sum_brier = 0
    per_partido = []
    for r in rows:
        ap, stk, prof, br = evaluar(r["p1"], r["px"], r["p2"],
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
        ys = np.empty(B)
        for b in range(B):
            idx = rng.integers(0, n_a, size=n_a)
            s = stakes[idx].sum()
            p = pls[idx].sum()
            ys[b] = (p/s*100) if s > 0 else 0
        out["ci95_lo"] = float(np.percentile(ys, 2.5))
        out["ci95_hi"] = float(np.percentile(ys, 97.5))
        out["sig"] = "+" if out["ci95_lo"] > 0 else ("-" if out["ci95_hi"] < 0 else "0")
    return out


def cargar_oos_con_pos(con):
    """JOIN predicciones_oos_con_features con stats_partido_espn para tener pos."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4, p.momento_octavo, p.momento_bin_12,
               p.diff_pos, p.pj_local, p.pj_visita,
               s.h_pos, s.a_pos
        FROM predicciones_oos_con_features p
        LEFT JOIN stats_partido_espn s
          ON p.liga = s.liga AND p.fecha = s.fecha
         AND p.local = s.ht AND p.visita = s.at
        WHERE s.h_pos IS NOT NULL
    """).fetchall()
    out = []
    for r in rows:
        out.append({
            "fecha": r[0], "liga": r[1], "temp": r[2],
            "local": r[3], "visita": r[4], "outcome": r[5],
            "p1": r[6], "px": r[7], "p2": r[8],
            "c1": r[9], "cx": r[10], "c2": r[11],
            "bin_4": r[12], "bin_8": r[13], "bin_12": r[14],
            "diff_pos": r[15], "pj_local": r[16] or 0, "pj_visita": r[17] or 0,
            "h_pos": r[18], "a_pos": r[19],
        })
    return out


def _seccion(rows, n_bins, label, payload_dict):
    letter = letter_bin(n_bins)
    bin_key = f"bin_{n_bins}"
    section = {}

    # 1. Por bucket pos local
    print(f"\n  Por bucket pos LOCAL (con CI95):")
    print(f"  {'Bucket':<14} {'NPred':>5} {'NApost':>6} {'Hit%':>5} {'Yld%':>7} {'CI95':>20} {'sig':>3}")
    by_pos = defaultdict(list)
    for r in rows:
        b = pos_bucket(r["h_pos"])
        if b:
            by_pos[b].append(r)
    section["por_pos_local"] = {}
    for name, lo, hi in POS_BUCKETS:
        sub = by_pos.get(name, [])
        if not sub:
            continue
        m = agg(sub, with_ci=True)
        if m:
            ci_str = f"[{m.get('ci95_lo', 0):+.1f}, {m.get('ci95_hi', 0):+.1f}]"
            sig = m.get("sig", "?")
            print(f"  {name:<14} {m['n_pred']:>5} {m['n_apost']:>6} {m['hit_pct']:>5.1f} "
                  f"{m['yield_pct']:>+7.1f} {ci_str:>20} {sig:>3}")
            section["por_pos_local"][name] = m

    # 2. Cross pos_local x momento_bin
    print(f"\n  Cross pos_local x {bin_key} (yield apostado, N>=10):")
    cross = defaultdict(lambda: defaultdict(list))
    for r in rows:
        pb = pos_bucket(r["h_pos"])
        bb = r.get(bin_key)
        if pb and bb is not None:
            cross[pb][bb].append(r)
    pos_names = [b[0] for b in POS_BUCKETS]
    bins_present = sorted({bb for pb in cross for bb in cross[pb]})
    headers = " ".join(f"{f'{letter}{b+1}':>6}" for b in bins_present)
    print(f"  {'PosBucket':<14} {headers}")
    section["cross_pos_x_bin"] = {}
    for pb in pos_names:
        if pb not in cross:
            continue
        cells = []
        pos_payload = {}
        for bb in bins_present:
            sub = cross[pb].get(bb, [])
            m = agg(sub) if sub else None
            if not m or m["n_apost"] < 10:
                cells.append(f"{('n=' + str(m['n_apost'] if m else 0)):>6}")
                pos_payload[f"{letter}{bb+1}"] = {"n_apost": m["n_apost"] if m else 0,
                                                    "yield_pct": None}
            else:
                cells.append(f"{m['yield_pct']:>+6.1f}")
                pos_payload[f"{letter}{bb+1}"] = {"n_apost": m["n_apost"],
                                                    "yield_pct": m["yield_pct"],
                                                    "hit_pct": m["hit_pct"]}
        print(f"  {pb:<14} {' '.join(cells)}")
        section["cross_pos_x_bin"][pb] = pos_payload

    # 3. Por liga (con N>=30)
    print(f"\n  Por liga (yield apostado, N apostado>=30):")
    print(f"  {'Liga':<14} {'NPred':>5} {'NApost':>6} {'Hit%':>5} {'Yld%':>7} {'pos_avg':>7}")
    by_liga = defaultdict(list)
    for r in rows:
        by_liga[r["liga"]].append(r)
    section["por_liga"] = {}
    for liga in sorted(by_liga.keys()):
        sub = by_liga[liga]
        m = agg(sub, with_ci=True)
        if m and m["n_apost"] >= 30:
            pos_avg = float(np.mean([r["h_pos"] for r in sub if r.get("h_pos") is not None]))
            print(f"  {liga:<14} {m['n_pred']:>5} {m['n_apost']:>6} {m['hit_pct']:>5.1f} "
                  f"{m['yield_pct']:>+7.1f} {pos_avg:>7.1f}")
            section["por_liga"][liga] = {**m, "pos_avg_local": pos_avg}

    payload_dict[label] = section


def run(rows, n_bins, out_path):
    print(f"\n{'='*70}")
    print(f"=== FASE 3 yield x posesion x {label_bin(n_bins)} (n_bins={n_bins}) ===")
    print(f"{'='*70}")
    print(f"N OOS con pos: {len(rows)}")

    payload = {"n_total": len(rows), "n_bins": n_bins,
                "buckets_pos": [b[0] for b in POS_BUCKETS]}

    # === AGREGADO ===
    print(f"\n--- AGREGADO ---")
    _seccion(rows, n_bins, "agregado", payload)

    # === POR TEMP ===
    print(f"\n=== POR TEMP ===")
    payload["por_temp"] = {}
    temps = sorted({r["temp"] for r in rows if r.get("temp")})
    for temp in temps:
        rows_t = [r for r in rows if r.get("temp") == temp]
        print(f"\n--- TEMP {temp} (N={len(rows_t)}) ---")
        _seccion(rows_t, n_bins, str(temp), payload["por_temp"])

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out_path}")


def main():
    con = sqlite3.connect(DB)
    n_pos = con.execute("SELECT COUNT(*) FROM stats_partido_espn WHERE h_pos IS NOT NULL").fetchone()[0]
    print(f"=== FASE 3 yield x posesion ===")
    print(f"Stats con pos en DB: {n_pos}")
    if n_pos < 100:
        print("[FATAL] Insuficiente. Correr scraper primero.")
        return
    rows = cargar_oos_con_pos(con)
    print(f"OOS con pos joineado: {len(rows)}")
    if len(rows) < 100:
        print("[WARN] Cobertura OOS baja, completar scrape")
    con.close()

    for nb in (4, 8, 12):
        run(rows, nb, OUT_DIR / f"fase3_yield_posesion_oos_bin{nb}.json")


if __name__ == "__main__":
    main()

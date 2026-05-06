"""
Matriz formacion_l x formacion_v: %1 / %X / %2 (N) sobre SOFA 2026 (769 partidos).

Output:
- Matriz formacion_l x formacion_v con (n, %1, %X, %2)
- Marginal por formacion_l (todas visitas)
- Marginal por formacion_v (todos locales)
- Comparacion vs baseline global (todos partidos)
- Test chi-square aproximado para detectar desviaciones significativas

Salida: filtros_formaciones_matchup_ratio.json + impresion tabla.
"""
from __future__ import annotations
import sqlite3
import json
import math
from pathlib import Path
from collections import defaultdict, Counter

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    rows = cur.execute("""
        SELECT formation_l, formation_v, hg, ag, liga,
               xg_shotmap_l, xg_shotmap_v
        FROM sofascore_match_features
        WHERE error IS NULL
              AND formation_l IS NOT NULL AND formation_v IS NOT NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
    """).fetchall()
    print(f"Partidos SOFA con formacion + resultado: {len(rows)}")

    # Baseline global
    global_n = len(rows)
    global_1 = sum(1 for r in rows if r[2] > r[3])
    global_x = sum(1 for r in rows if r[2] == r[3])
    global_2 = sum(1 for r in rows if r[2] < r[3])
    p1_global = global_1 / global_n
    px_global = global_x / global_n
    p2_global = global_2 / global_n

    print(f"\n=== BASELINE GLOBAL (N={global_n}) ===")
    print(f"%1 = {p1_global:.1%}   %X = {px_global:.1%}   %2 = {p2_global:.1%}")
    print()

    # Compute global xG y goles avg
    n_with_xg = sum(1 for r in rows if r[5] is not None and r[6] is not None)
    sum_xg_l_global = sum(r[5] for r in rows if r[5] is not None)
    sum_xg_v_global = sum(r[6] for r in rows if r[6] is not None)
    sum_g_l_global = sum(r[2] for r in rows)
    sum_g_v_global = sum(r[3] for r in rows)
    xg_l_avg_global = sum_xg_l_global / n_with_xg if n_with_xg else 0
    xg_v_avg_global = sum_xg_v_global / n_with_xg if n_with_xg else 0
    g_l_avg_global = sum_g_l_global / global_n
    g_v_avg_global = sum_g_v_global / global_n
    print(f"xG_l_avg = {xg_l_avg_global:.3f}  xG_v_avg = {xg_v_avg_global:.3f}")
    print(f"g_l_avg = {g_l_avg_global:.3f}  g_v_avg = {g_v_avg_global:.3f}")
    print()

    # Marginales por formacion local
    by_l = defaultdict(lambda: {"n": 0, "1": 0, "X": 0, "2": 0,
                                  "xg_l_sum": 0, "xg_v_sum": 0, "n_xg": 0,
                                  "g_l_sum": 0, "g_v_sum": 0})
    by_v = defaultdict(lambda: {"n": 0, "1": 0, "X": 0, "2": 0,
                                  "xg_l_sum": 0, "xg_v_sum": 0, "n_xg": 0,
                                  "g_l_sum": 0, "g_v_sum": 0})
    by_lv = defaultdict(lambda: {"n": 0, "1": 0, "X": 0, "2": 0,
                                  "xg_l_sum": 0, "xg_v_sum": 0, "n_xg": 0,
                                  "g_l_sum": 0, "g_v_sum": 0})

    for fl, fv, hg, ag, liga, xg_l, xg_v in rows:
        if hg > ag: r = "1"
        elif hg < ag: r = "2"
        else: r = "X"
        for d in (by_l[fl], by_v[fv], by_lv[(fl, fv)]):
            d["n"] += 1
            d[r] += 1
            d["g_l_sum"] += hg
            d["g_v_sum"] += ag
            if xg_l is not None and xg_v is not None:
                d["xg_l_sum"] += xg_l
                d["xg_v_sum"] += xg_v
                d["n_xg"] += 1

    def fmt_xg(d):
        if d["n_xg"] > 0:
            return d["xg_l_sum"]/d["n_xg"], d["xg_v_sum"]/d["n_xg"]
        return None, None

    print("=== MARGINAL FORMACION LOCAL (N>=20) ===")
    print(f"{'formacion_l':<12} {'N':>4}  {'%1':>6} {'%X':>6} {'%2':>6}   {'xG_l':>5} {'xG_v':>5}   {'g_l':>4} {'g_v':>4}   {'lift_1':>7} {'lift_X':>7} {'lift_2':>7}")
    by_l_sorted = sorted(by_l.items(), key=lambda x: -x[1]["n"])
    for fl, d in by_l_sorted:
        if d["n"] < 20: continue
        p1 = d["1"]/d["n"]; px = d["X"]/d["n"]; p2 = d["2"]/d["n"]
        l1 = p1 - p1_global; lx = px - px_global; l2 = p2 - p2_global
        xgl, xgv = fmt_xg(d)
        gl = d["g_l_sum"]/d["n"]; gv = d["g_v_sum"]/d["n"]
        xg_str = f"{xgl:.2f} {xgv:.2f}" if xgl is not None else "n/a   n/a"
        print(f"{fl:<12} {d['n']:>4}  {p1:>6.1%} {px:>6.1%} {p2:>6.1%}   {xg_str:>11s}   {gl:>4.2f} {gv:>4.2f}   {l1:>+7.1%} {lx:>+7.1%} {l2:>+7.1%}")

    print()
    print("=== MARGINAL FORMACION VISITA (N>=20) ===")
    print(f"{'formacion_v':<12} {'N':>4}  {'%1':>6} {'%X':>6} {'%2':>6}   {'xG_l':>5} {'xG_v':>5}   {'g_l':>4} {'g_v':>4}   {'lift_1':>7} {'lift_X':>7} {'lift_2':>7}")
    by_v_sorted = sorted(by_v.items(), key=lambda x: -x[1]["n"])
    for fv, d in by_v_sorted:
        if d["n"] < 20: continue
        p1 = d["1"]/d["n"]; px = d["X"]/d["n"]; p2 = d["2"]/d["n"]
        l1 = p1 - p1_global; lx = px - px_global; l2 = p2 - p2_global
        xgl, xgv = fmt_xg(d)
        gl = d["g_l_sum"]/d["n"]; gv = d["g_v_sum"]/d["n"]
        xg_str = f"{xgl:.2f} {xgv:.2f}" if xgl is not None else "n/a   n/a"
        print(f"{fv:<12} {d['n']:>4}  {p1:>6.1%} {px:>6.1%} {p2:>6.1%}   {xg_str:>11s}   {gl:>4.2f} {gv:>4.2f}   {l1:>+7.1%} {lx:>+7.1%} {l2:>+7.1%}")

    print()
    print("=== MATRIZ formacion_L x formacion_V (N>=10) ===")
    # Solo top formaciones (>=20 partidos como local o visita)
    top_l = [fl for fl, d in by_l_sorted if d["n"] >= 20]
    top_v = [fv for fv, d in by_v_sorted if d["n"] >= 20]

    # Header
    header = f"{'L \\ V':<10}"
    for fv in top_v:
        header += f" {fv[:9]:>11s}"
    print(header)

    matriz_export = {}
    for fl in top_l:
        line = f"{fl:<10}"
        matriz_export[fl] = {}
        for fv in top_v:
            d = by_lv.get((fl, fv))
            if d is None or d["n"] < 5:
                line += f" {'.':>14s}"
                matriz_export[fl][fv] = {"n": d["n"] if d else 0}
                continue
            p1 = d["1"]/d["n"]; px = d["X"]/d["n"]; p2 = d["2"]/d["n"]
            xgl, xgv = fmt_xg(d)
            xg_str = f"{xgl:.1f}-{xgv:.1f}" if xgl is not None else "?"
            cell = f"{int(p1*100):>2}/{int(px*100):>2}/{int(p2*100):>2}({d['n']:>2}|{xg_str})"
            line += f" {cell:>16s}"
            matriz_export[fl][fv] = {
                "n": d["n"], "p1": p1, "px": px, "p2": p2,
                "xg_l_avg": xgl, "xg_v_avg": xgv,
                "g_l_avg": d["g_l_sum"]/d["n"],
                "g_v_avg": d["g_v_sum"]/d["n"],
                "lift_1": p1 - p1_global, "lift_x": px - px_global, "lift_2": p2 - p2_global,
                "lift_xg_l": (xgl - xg_l_avg_global) if xgl is not None else None,
                "lift_xg_v": (xgv - xg_v_avg_global) if xgv is not None else None,
            }
        print(line)

    print()
    print("=== TOP DESVIACIONES sig (N>=15, |lift| > 10pp) ===")
    desviaciones = []
    for (fl, fv), d in by_lv.items():
        if d["n"] < 15: continue
        p1, px, p2 = d["1"]/d["n"], d["X"]/d["n"], d["2"]/d["n"]
        xgl, xgv = fmt_xg(d)
        for outcome, p, base in [("1", p1, p1_global), ("X", px, px_global), ("2", p2, p2_global)]:
            lift = p - base
            if abs(lift) >= 0.10:
                se = math.sqrt(base * (1 - base) / d["n"])
                z = lift / se if se > 0 else 0
                desviaciones.append({
                    "formacion_l": fl, "formacion_v": fv,
                    "outcome": outcome, "n": d["n"],
                    "p_observed": p, "p_expected": base, "lift": lift,
                    "z_score": z,
                    "xg_l_avg": xgl, "xg_v_avg": xgv,
                    "g_l_avg": d["g_l_sum"]/d["n"], "g_v_avg": d["g_v_sum"]/d["n"],
                })
    desviaciones.sort(key=lambda x: abs(x["z_score"]), reverse=True)
    print(f"{'matchup':<28} {'outc':<5} {'N':>3}  {'p_obs':>6} {'p_exp':>6} {'lift':>7}  {'z':>6}  {'xG_l':>4} {'xG_v':>4}  {'g_l':>4} {'g_v':>4}")
    for d in desviaciones[:25]:
        m = f"{d['formacion_l']} vs {d['formacion_v']}"
        xgl_s = f"{d['xg_l_avg']:.2f}" if d['xg_l_avg'] is not None else "n/a"
        xgv_s = f"{d['xg_v_avg']:.2f}" if d['xg_v_avg'] is not None else "n/a"
        print(f"{m[:27]:<28} {d['outcome']:<5} {d['n']:>3}  {d['p_observed']:>6.1%} {d['p_expected']:>6.1%} {d['lift']:>+7.1%}  {d['z_score']:>+6.2f}  {xgl_s:>4} {xgv_s:>4}  {d['g_l_avg']:>4.2f} {d['g_v_avg']:>4.2f}")

    out_data = {
        "n_total": global_n,
        "baseline": {"p1": p1_global, "px": px_global, "p2": p2_global},
        "marginal_local": {fl: dict(d, p1=d["1"]/d["n"], px=d["X"]/d["n"], p2=d["2"]/d["n"])
                           for fl, d in by_l_sorted if d["n"] >= 10},
        "marginal_visita": {fv: dict(d, p1=d["1"]/d["n"], px=d["X"]/d["n"], p2=d["2"]/d["n"])
                            for fv, d in by_v_sorted if d["n"] >= 10},
        "matriz_l_x_v": matriz_export,
        "top_desviaciones": desviaciones[:30],
    }
    out = ROOT / "analisis" / "formaciones_matchup_ratio.json"
    out.write_text(json.dumps(out_data, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

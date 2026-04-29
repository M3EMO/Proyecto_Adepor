"""
[adepor V14 v2 SHADOW analysis] Drill copa_nacional hit 47.8% — buscar subsets
con hit rate >= 50% consistente que justifique aplicar V14 v2 SHADOW para
selección de picks.

Fuente: picks_shadow_v14_copa (9,300 filas, 9,164 liquidados).
"""
from __future__ import annotations
import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"


def wilson_lo(hits, n, z=1.96):
    if n == 0: return 0.0
    p = hits / n
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p) + z*z/(4*n))/n)) / (1 + z*z/n)


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    print("=" * 100)
    print("DRILL copa_nacional hit 47.8% (V14 v2 SHADOW, N=4,621 liquidados)")
    print("=" * 100)

    # 1. Por edición específica
    print("\n--- 1. Por edición específica ---")
    print(f"{'edicion':<25} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10} {'argmax':>20}")
    for r in cur.execute("""
        SELECT competicion, COUNT(*) as n,
               SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) as h
        FROM picks_shadow_v14_copa
        WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
        GROUP BY competicion
        ORDER BY n DESC
    """):
        ed, n, h = r
        if n < 30: continue
        hit_pct = 100.0 * h / n
        wlo = 100.0 * wilson_lo(h, n)
        # Distribution argmax
        argmax_dist = cur.execute("""
            SELECT argmax_v14_v2, COUNT(*),
                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
            FROM picks_shadow_v14_copa
            WHERE competicion_tipo='copa_nacional' AND competicion=?
              AND outcome_real IS NOT NULL
            GROUP BY argmax_v14_v2
        """, (ed,)).fetchall()
        am_str = ", ".join(f"{a[0]}:{100*a[2]/a[1]:.0f}%(N={a[1]})" for a in argmax_dist)
        flag = ""
        if hit_pct >= 50: flag = " *"
        if hit_pct >= 53: flag = " **"
        if hit_pct >= 56: flag = " ***"
        ed_safe = ed.encode('ascii','replace').decode('ascii')
        print(f"  {ed_safe:<25} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}% {am_str}{flag}")

    # 2. Por edición x argmax
    print("\n--- 2. Por edición x argmax (donde N >= 100) ---")
    print(f"{'edicion':<25} {'argmax':>7} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10}")
    for r in cur.execute("""
        SELECT competicion, argmax_v14_v2,
               COUNT(*) as n,
               SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) as h
        FROM picks_shadow_v14_copa
        WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
        GROUP BY competicion, argmax_v14_v2
        HAVING n >= 100
        ORDER BY (CAST(SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*)) DESC
    """):
        ed, am, n, h = r
        hit_pct = 100.0 * h / n
        wlo = 100.0 * wilson_lo(h, n)
        flag = ""
        if hit_pct >= 50 and wlo >= 47: flag = " *"
        if hit_pct >= 55 and wlo >= 50: flag = " **"
        ed_safe = ed.encode('ascii','replace').decode('ascii')
        print(f"  {ed_safe:<25} {am:>7s} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%{flag}")

    # 3. Por p_max bucket (confianza)
    print("\n--- 3. Por p_max_v14_v2 bucket (todos copa_nacional) ---")
    print(f"{'bucket':<15} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10}")
    buckets = [(0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65),
                (0.65, 0.70), (0.70, 1.0)]
    for lo, hi in buckets:
        r = cur.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
            FROM picks_shadow_v14_copa
            WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
              AND p_max_v14_v2 >= ? AND p_max_v14_v2 < ?
        """, (lo, hi)).fetchone()
        n, h = r
        if n < 20: continue
        hit_pct = 100.0 * h / n
        wlo = 100.0 * wilson_lo(h, n)
        bk = f"[{lo:.2f},{hi:.2f})"
        flag = ""
        if hit_pct >= 50: flag = " *"
        if hit_pct >= 55: flag = " **"
        if hit_pct >= 60: flag = " ***"
        print(f"  {bk:<15} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%{flag}")

    # 4. Por edición x p_max bucket
    print("\n--- 4. Por edición x p_max_v14_v2 (p_max >= 0.55, N >= 30) ---")
    print(f"{'edicion':<25} {'p_max_min':>10} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10}")
    for r in cur.execute("""
        SELECT competicion,
               COUNT(*) as n,
               SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) as h
        FROM picks_shadow_v14_copa
        WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
          AND p_max_v14_v2 >= 0.55
        GROUP BY competicion
        HAVING n >= 30
        ORDER BY (CAST(SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*)) DESC
    """):
        ed, n, h = r
        hit_pct = 100.0 * h / n
        wlo = 100.0 * wilson_lo(h, n)
        flag = ""
        if hit_pct >= 55: flag = " *"
        if hit_pct >= 60: flag = " **"
        if hit_pct >= 65: flag = " ***"
        ed_safe = ed.encode('ascii','replace').decode('ascii')
        print(f"  {ed_safe:<25} {0.55:>10.2f} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%{flag}")

    # 5. Por argmax x p_max bucket TODAS copa_nacional
    print("\n--- 5. argmax x p_max_v14_v2 bucket (todas copa_nacional) ---")
    print(f"{'argmax':>7} {'p_min':>6} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10}")
    for am in ['1','X','2']:
        for p_min in [0.40, 0.50, 0.55, 0.60, 0.65]:
            r = cur.execute("""
                SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                FROM picks_shadow_v14_copa
                WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                  AND argmax_v14_v2=? AND p_max_v14_v2 >= ?
            """, (am, p_min)).fetchone()
            n, h = r
            if n < 50: continue
            hit_pct = 100.0 * h / n
            wlo = 100.0 * wilson_lo(h, n)
            flag = ""
            if hit_pct >= 53 and wlo >= 50: flag = " *"
            if hit_pct >= 58: flag = " **"
            print(f"  {am:>7s} {p_min:>6.2f} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%{flag}")

    # 6. Por delta_elo absoluto (favoritos extremos)
    print("\n--- 6. Por |delta_elo_pre| (favoritos extremos) ---")
    print(f"{'rango':<20} {'N':>5} {'hits':>5} {'hit%':>6} {'wilson_lo':>10}")
    rangos = [(0,100),(100,200),(200,300),(300,400),(400,1000)]
    for lo, hi in rangos:
        r = cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
            FROM picks_shadow_v14_copa
            WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
              AND ABS(delta_elo_pre) >= ? AND ABS(delta_elo_pre) < ?
        """, (lo, hi)).fetchone()
        n, h = r
        if n < 30: continue
        hit_pct = 100.0 * h / n
        wlo = 100.0 * wilson_lo(h, n)
        flag = ""
        if hit_pct >= 55: flag = " *"
        if hit_pct >= 60: flag = " **"
        if hit_pct >= 65: flag = " ***"
        bk = f"[{lo},{hi})"
        print(f"  {bk:<20} {n:>5d} {h:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%{flag}")

    # 7. Por edición x year (estabilidad temporal)
    print("\n--- 7. Por edición x year (¿estabilidad temporal del hit rate?) ---")
    print(f"{'edicion':<25} {'2022':>7} {'2023':>7} {'2024':>7} {'2025':>7} {'2026':>7}")
    ediciones = [r[0] for r in cur.execute("""
        SELECT competicion FROM picks_shadow_v14_copa
        WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
        GROUP BY competicion HAVING COUNT(*) >= 100
    """)]
    for ed in ediciones:
        row = [ed.encode('ascii','replace').decode('ascii')[:24].ljust(25)]
        for yr in [2022, 2023, 2024, 2025, 2026]:
            r = cur.execute("""
                SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                FROM picks_shadow_v14_copa
                WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                  AND competicion=? AND substr(fecha_partido,1,4)=?
            """, (ed, str(yr))).fetchone()
            n, h = r
            if n >= 20:
                row.append(f"{100*h/n:>5.1f}%({n})")
            else:
                row.append(f"   -    ")
        print("  " + " ".join(row))

    # 8. Picks "high-confidence" cross-edición
    print("\n--- 8. PICKS HIGH-CONFIDENCE — argmax LOCAL + p_max >= 0.55 + delta_elo>=200 ---")
    r = cur.execute("""
        SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
        FROM picks_shadow_v14_copa
        WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
          AND argmax_v14_v2='1' AND p_max_v14_v2 >= 0.55 AND delta_elo_pre >= 200
    """).fetchone()
    n, h = r
    if n > 0:
        hit_pct = 100*h/n
        wlo = 100*wilson_lo(h, n)
        print(f"  TODAS COPA_NAC: N={n} hits={h} hit={hit_pct:.1f}% wilson_lo={wlo:.1f}%")
        for ed in ediciones:
            r = cur.execute("""
                SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                FROM picks_shadow_v14_copa
                WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                  AND argmax_v14_v2='1' AND p_max_v14_v2 >= 0.55 AND delta_elo_pre >= 200
                  AND competicion=?
            """, (ed,)).fetchone()
            ne, he = r
            if ne >= 20:
                ed_safe = ed.encode('ascii','replace').decode('ascii')
                wlo_e = 100*wilson_lo(he, ne)
                flag = ""
                if 100*he/ne >= 60: flag = " **"
                if 100*he/ne >= 65: flag = " ***"
                print(f"    {ed_safe:<25} N={ne:>4d} hit={100*he/ne:>5.1f}% wilson_lo={wlo_e:>5.1f}%{flag}")

    conn.close()


if __name__ == "__main__":
    main()

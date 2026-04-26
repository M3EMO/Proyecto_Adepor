"""Critico audit: ablation HG/FIX5 con tests de robustez estadistica.

Tests:
  1. Reproduccion ablation 5-fold CV
  2. Bootstrap CI 95% del yield (V_sin_FIX5_HG con N=22)
  3. Sensibilidad a outliers (que pasa si quitamos top-1, top-2 picks)
  4. Analisis por liga (donde HG aplica realmente)
  5. Distribucion temporal (drift?)
  6. Brier comparativo
  7. p-value contra azar
"""
import math
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
RANGO_POISSON = 10
N_MIN_HG = 50


def poisson(k, lam):
    if lam <= 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


def tau(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    if i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    if i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    if i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def calc_probs(xg_l, xg_v, rho):
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    total = p1 + px + p2
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p1/total, px/total, p2/total


def aplicar_hg(p1, px, p2, freq):
    if freq is None or freq <= p1:
        return p1, px, p2
    boost = (freq - p1) * 0.5
    p1n = min(p1 + boost, 0.95)
    rest = px + p2
    if rest <= 0:
        return p1n, 0.5*(1-p1n), 0.5*(1-p1n)
    target = 1 - p1n
    return p1n, px*target/rest, p2*target/rest


def aplicar_fix5(p1, px, p2):
    p1c, p2c = p1, p2
    if 0.40 <= p1 < 0.50:
        p1c = p1 + 0.042
    if 0.40 <= p2 < 0.50:
        p2c = p2 + 0.042
    s = p1c + px + p2c
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p1c/s, px/s, p2c/s


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0:
        return 0
    f = p - (1-p)/(c-1)
    return max(0, min(f, cap))


def simular(p1, px, p2, c1, cx, c2, floor=0.33, margen_min=0.05, ev_min=0.03, cap=0.025):
    sp = sorted([p1, px, p2], reverse=True)
    if sp[0] - sp[1] < margen_min:
        return None, 0
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    lab, p, c = max(opts, key=lambda x: x[1])
    if p < floor:
        return None, 0
    if not c or c <= 1.0:
        return None, 0
    if p*c - 1 < ev_min:
        return None, 0
    return lab, kelly(p, c, cap)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pais, xg_local, xg_visita, cuota_1, cuota_x, cuota_2, goles_l, goles_v, fecha
        FROM partidos_backtest
        WHERE estado='Liquidado' AND xg_local > 0 AND xg_visita > 0
          AND cuota_1 > 0 AND cuota_x > 0 AND cuota_2 > 0
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha
    """).fetchall()
    print(f"=== AUDIT CRITICO bead adepor-6rv: N={len(rows)} ===\n")

    freq_per_liga = {}
    for r in cur.execute("""
        SELECT pais, COUNT(*) as n,
               AVG(CASE WHEN goles_l > goles_v THEN 1.0 ELSE 0.0 END) as freq
        FROM partidos_backtest WHERE estado='Liquidado' AND goles_l IS NOT NULL
        GROUP BY pais
    """):
        if r[1] >= N_MIN_HG:
            freq_per_liga[r[0]] = r[2]
    rho_per_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    print(f"HG aplica en: {list(freq_per_liga.keys())}")
    print(f"  Argentina freq={freq_per_liga.get('Argentina', 0):.4f}, Brasil freq={freq_per_liga.get('Brasil', 0):.4f}")
    print()

    # ============================================
    # 1. ANALISIS DE FLIPS (HG/FIX5 vs sin nada)
    # ============================================
    print("=== 1. FLIPS analysis ===")
    flips_only_with = []
    flips_only_without = []
    same_pick_diff_prob = []

    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv, fch = r
        rho = rho_per_liga.get(pais, -0.09)
        p1, px, p2 = calc_probs(xg_l, xg_v, rho)
        # Con HG y FIX5
        freq = freq_per_liga.get(pais)
        p1A = p1; pxA = px; p2A = p2
        if freq is not None:
            p1A, pxA, p2A = aplicar_hg(p1A, pxA, p2A, freq)
        p1A, pxA, p2A = aplicar_fix5(p1A, pxA, p2A)
        # Sin HG ni FIX5
        p1B, pxB, p2B = p1, px, p2

        apA, stA = simular(p1A, pxA, p2A, c1, cx, c2)
        apB, stB = simular(p1B, pxB, p2B, c1, cx, c2)

        outcome = "1" if gl > gv else ("X" if gl == gv else "2")

        if apA and not apB:
            cuota = {"1": c1, "X": cx, "2": c2}[apA]
            flips_only_with.append((pais, apA, p1A, p1B, cuota, apA == outcome))
        elif apB and not apA:
            cuota = {"1": c1, "X": cx, "2": c2}[apB]
            flips_only_without.append((pais, apB, p1A, p1B, cuota, apB == outcome))
        elif apA and apB:
            same_pick_diff_prob.append((pais, apA == outcome))

    print(f"Picks que SOLO aparecen con HG/FIX5 activos: {len(flips_only_with)}")
    won = sum(1 for f in flips_only_with if f[5])
    if flips_only_with:
        print(f"  Hit: {won}/{len(flips_only_with)} = {won/len(flips_only_with)*100:.1f}%")
        print("  Por liga:")
        for liga, c in Counter(f[0] for f in flips_only_with).most_common():
            won_l = sum(1 for f in flips_only_with if f[0] == liga and f[5])
            print(f"    {liga:<14} N={c:>3} ganados={won_l} hit={won_l/c*100:.1f}%")

    print(f"\nPicks que SOLO aparecen sin HG/FIX5: {len(flips_only_without)}")
    won = sum(1 for f in flips_only_without if f[5])
    if flips_only_without:
        print(f"  Hit: {won}/{len(flips_only_without)} = {won/len(flips_only_without)*100:.1f}%")
    print()

    # ============================================
    # 2. REPRODUCIR CV 5-FOLD V_sin_FIX5_HG
    # ============================================
    print("=== 2. CV 5-fold V_sin_FIX5_HG (reproduccion exacta) ===")
    np.random.seed(42)
    idx = list(range(len(rows)))
    np.random.shuffle(idx)
    K = 5
    fs = len(rows) // K
    all_picks_cv = []
    for f in range(K):
        test_set = set(idx[f*fs:(f+1)*fs])
        test_rows = [rows[j] for j in idx if j in test_set]
        for r in test_rows:
            pais, xg_l, xg_v, c1, cx, c2, gl, gv, fch = r
            rho = rho_per_liga.get(pais, -0.09)
            p1, px, p2 = calc_probs(xg_l, xg_v, rho)
            ap, st = simular(p1, px, p2, c1, cx, c2)
            if ap:
                cuota = {"1": c1, "X": cx, "2": c2}[ap]
                outcome = "1" if gl > gv else ("X" if gl == gv else "2")
                won = ap == outcome
                all_picks_cv.append((st, cuota, won, pais, fch))

    print(f"Total picks V_sin_FIX5_HG: {len(all_picks_cv)}")
    print("Por liga:")
    for liga, c in Counter(p[3] for p in all_picks_cv).most_common():
        won_l = sum(1 for p in all_picks_cv if p[3] == liga and p[2])
        print(f"  {liga:<14} N={c:>3} ganados={won_l} hit={won_l/c*100:.1f}%")

    # ============================================
    # 3. BOOTSTRAP CI 95% del yield
    # ============================================
    print("\n=== 3. Bootstrap yield CI 95% (V_sin_FIX5_HG) ===")
    B = 5000
    yields = []
    np.random.seed(99)
    for _ in range(B):
        sample_idx = np.random.choice(len(all_picks_cv), len(all_picks_cv), replace=True)
        s_p = 0
        s_s = 0
        for i in sample_idx:
            st, cu, w, _, _ = all_picks_cv[i]
            s_s += st
            if w:
                s_p += st * (cu - 1)
            else:
                s_p -= st
        if s_s > 0:
            yields.append(s_p/s_s*100)
    yields.sort()
    print(f"  Bootstrap CI 95%: [{yields[int(B*0.025)]:.2f}%, {yields[int(B*0.975)]:.2f}%]")
    print(f"  Median: {yields[B//2]:.2f}%")
    print(f"  Mean: {np.mean(yields):.2f}%")
    print(f"  Std: {np.std(yields):.2f}%")
    print(f"  P(yield <= 0): {sum(1 for y in yields if y <= 0)/B:.4f}")
    print(f"  P(yield <= 50): {sum(1 for y in yields if y <= 50)/B:.4f}")

    # ============================================
    # 4. Sensibilidad outliers
    # ============================================
    print("\n=== 4. Sensibilidad a outliers (top picks) ===")
    profits = [(p[0]*(p[1]-1) if p[2] else -p[0], p) for p in all_picks_cv]
    profits.sort(reverse=True)
    print("  Top 5 picks por profit:")
    for prof, (st, c, w, pais, fch) in profits[:5]:
        print(f"    {pais:<14} stake={st:.4f} cuota={c:.2f} won={w} profit={prof:+.4f}")

    for k in [1, 2, 3]:
        rem = [p for prof, p in profits[k:]]
        sp = sum(p[0]*(p[1]-1) if p[2] else -p[0] for p in rem)
        ss = sum(p[0] for p in rem)
        if ss > 0:
            print(f"  Yield SIN top-{k}: {sp/ss*100:+.2f}% (N={len(rem)})")

    # ============================================
    # 5. Distribucion temporal (drift?)
    # ============================================
    print("\n=== 5. Drift temporal (V_sin_FIX5_HG: yield first half vs second half) ===")
    # Picks ordenados por fecha
    picks_by_date = sorted(all_picks_cv, key=lambda x: x[4] or "")
    half = len(picks_by_date) // 2
    for label, slc in [("Primera mitad", picks_by_date[:half]), ("Segunda mitad", picks_by_date[half:])]:
        sp = sum(p[0]*(p[1]-1) if p[2] else -p[0] for p in slc)
        ss = sum(p[0] for p in slc)
        ng = sum(1 for p in slc if p[2])
        if ss > 0:
            print(f"  {label}: N={len(slc)}, hit={ng/len(slc)*100:.1f}%, yield={sp/ss*100:+.2f}%")
            if slc:
                print(f"    fechas: {slc[0][4]} a {slc[-1][4]}")

    # ============================================
    # 6. Brier comparativo (HG/FIX5 vs sin)
    # ============================================
    print("\n=== 6. Brier comparativo ===")
    brier_with = brier_without = 0
    n_brier = 0
    for r in rows:
        pais, xg_l, xg_v, c1, cx, c2, gl, gv, fch = r
        rho = rho_per_liga.get(pais, -0.09)
        p1, px, p2 = calc_probs(xg_l, xg_v, rho)
        # Con HG y FIX5
        freq = freq_per_liga.get(pais)
        p1A = p1; pxA = px; p2A = p2
        if freq is not None:
            p1A, pxA, p2A = aplicar_hg(p1A, pxA, p2A, freq)
        p1A, pxA, p2A = aplicar_fix5(p1A, pxA, p2A)
        # Sin
        p1B, pxB, p2B = p1, px, p2
        outcome = (1 if gl > gv else (0 if gl == gv else -1))
        # one-hot: 1, X, 2
        oh1 = 1 if gl > gv else 0
        ohX = 1 if gl == gv else 0
        oh2 = 1 if gl < gv else 0
        bA = (p1A - oh1)**2 + (pxA - ohX)**2 + (p2A - oh2)**2
        bB = (p1B - oh1)**2 + (pxB - ohX)**2 + (p2B - oh2)**2
        brier_with += bA
        brier_without += bB
        n_brier += 1
    print(f"  Brier CON HG/FIX5: {brier_with/n_brier:.5f}")
    print(f"  Brier SIN HG/FIX5: {brier_without/n_brier:.5f}")
    print(f"  Delta: {(brier_with - brier_without)/n_brier:+.5f} (negativo = HG/FIX5 mejora Brier)")

    # ============================================
    # 7. Test estadistico binomial: hit rate 81.82% es significativo?
    # ============================================
    print("\n=== 7. Test binomial hit rate ===")
    n_picks = len(all_picks_cv)
    n_won = sum(1 for p in all_picks_cv if p[2])
    hit = n_won / n_picks
    # Prob de obtener n_won o más wins por azar (asumiendo prob_avg de los picks)
    avg_p = sum(1.0/p[1] for p in all_picks_cv) / n_picks  # implicit avg prob from cuotas
    # Mas simple: contra una baseline de 50% (azar coin flip)
    from scipy.stats import binom
    p_value_50 = 1 - binom.cdf(n_won - 1, n_picks, 0.5)
    p_value_avg = 1 - binom.cdf(n_won - 1, n_picks, avg_p)
    print(f"  N picks: {n_picks}, won: {n_won}, hit: {hit*100:.2f}%")
    print(f"  Avg implicit prob (1/cuota): {avg_p*100:.2f}%")
    print(f"  P-value vs 50%: {p_value_50:.6f}")
    print(f"  P-value vs implicit avg: {p_value_avg:.6f}")

    con.close()


if __name__ == "__main__":
    main()

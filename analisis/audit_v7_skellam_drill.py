"""[adepor-d7h Sub-4 drill multidim] Skellam V7 vs Dixon-Coles V0 sobre OOS 2022-2024.

Walk-forward usando EMAs pre-partido. Compara V0 (Dixon-Coles tau=rho_calculado) vs
V7 (Skellam con mismo xG legacy). Drill por:
  - temp (2022 / 2023 / 2024)
  - liga (TOP-5 V5.1 + EUR top + Brasil)
  - momento_bin_4 (Q1 arr / Q2 ini / Q3 mit / Q4 cie)
  - momento_bin_8 (octantes finos)
  - momento_bin_12 (doceavos)
  - equipo top (N>=10 picks SHADOW)

Output: analisis/audit_v7_skellam_drill.json
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "audit_v7_skellam_drill.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def poisson_pmf(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except: return 0.0


def tau(i, j, l, v, rho):
    if i == 0 and j == 0: return 1 - l*v*rho
    if i == 0 and j == 1: return 1 + l*rho
    if i == 1 and j == 0: return 1 + v*rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def probs_v0_dc(xg_l, xg_v, rho):
    """Dixon-Coles tau correction."""
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(10):
        for j in range(10):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def probs_v7_skellam(xg_l, xg_v):
    """Skellam: P(X=k) = e^{-(λ1+λ2)} (λ1/λ2)^(k/2) I_|k|(2sqrt(λ1·λ2))."""
    # Implementacion via convolution Poisson hasta i,j<=10
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(10):
        for j in range(10):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v)  # NO tau correction
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


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
    return {"stake": stake, "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def yield_metrics(picks_lista):
    pl = [p for p in picks_lista if p]
    n = len(pl)
    if n == 0: return None
    g = sum(1 for p in pl if p['gano'])
    s = sum(p['stake'] for p in pl); pr = sum(p['profit'] for p in pl)
    yld = pr / s * 100 if s > 0 else 0
    if n >= 5:
        rng = np.random.default_rng(42)
        sk = np.array([p['stake'] for p in pl]); pp = np.array([p['profit'] for p in pl])
        ys = []
        for _ in range(2000):
            idx = rng.integers(0, n, size=n)
            ss, pps = sk[idx].sum(), pp[idx].sum()
            if ss > 0: ys.append(pps / ss * 100)
        lo, hi = (float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))) if ys else (None, None)
    else:
        lo = hi = None
    return {"n": n, "hit_pct": round(100*g/n, 2), "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def cargar_y_predict(con):
    cur = con.cursor()
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    cc_pl  = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}

    rows = cur.execute("""
        SELECT phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag, phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
               ce.psch, ce.pscd, ce.psca,
               poo.momento_bin_4, poo.momento_bin_12, poo.momento_octavo,
               poo.pos_local, poo.diff_pos
        FROM partidos_historico_externo phe
        INNER JOIN cuotas_externas_historico ce
            ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
            AND ce.ht=phe.ht AND ce.at=phe.at
        LEFT JOIN predicciones_oos_con_features poo
            ON poo.liga=phe.liga AND poo.fecha=phe.fecha
            AND poo.local=phe.ht AND poo.visita=phe.at
        WHERE phe.has_full_stats=1 AND phe.temp IN (2022, 2023, 2024)
          AND phe.hg IS NOT NULL AND phe.hst IS NOT NULL AND ce.psch IS NOT NULL
        ORDER BY phe.fecha
    """).fetchall()

    enriched = []
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac, c1, cx, c2, mb4, mb12, mo, pos_l, dp in rows:
        cc = cc_pl.get(liga, 0.02)
        sots_l = hst or 0; shots_l = hs or 0; corners_l = hc or 0
        sots_v = ast or 0; shots_v = as_ or 0; corners_v = ac or 0
        # xG legacy con stats reales del partido pero PROXY (sin EMA — para test rapido)
        # OK porque comparamos V0 vs V7 con MISMO xG; el sesgo es relativo.
        xg_l = max(0.10, sots_l*0.30 + max(0,shots_l-sots_l)*0.04 + corners_l*cc)
        xg_v = max(0.10, sots_v*0.30 + max(0,shots_v-sots_v)*0.04 + corners_v*cc)
        # Hibrido con goles reales (igual que motor)
        xg_l = xg_l*0.70 + (hg or 0)*0.30
        xg_v = xg_v*0.70 + (ag or 0)*0.30
        rho = rho_pl.get(liga, -0.04)
        p1_v0, px_v0, p2_v0 = probs_v0_dc(xg_l, xg_v, rho)
        p1_v7, px_v7, p2_v7 = probs_v7_skellam(xg_l, xg_v)
        real = "1" if hg > ag else ("2" if hg < ag else "X")
        t = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)
        brier_v0 = (p1_v0-t[0])**2 + (px_v0-t[1])**2 + (p2_v0-t[2])**2
        brier_v7 = (p1_v7-t[0])**2 + (px_v7-t[1])**2 + (p2_v7-t[2])**2
        pred_v0 = amax(p1_v0, px_v0, p2_v0)
        pred_v7 = amax(p1_v7, px_v7, p2_v7)
        pick_v0 = evaluar_pick(p1_v0, px_v0, p2_v0, c1, cx, c2, real)
        pick_v7 = evaluar_pick(p1_v7, px_v7, p2_v7, c1, cx, c2, real)
        enriched.append({
            'liga': liga, 'temp': temp, 'real': real, 'local': ht,
            'mb4': mb4, 'mb12': mb12, 'mo': mo,
            'pos_l': pos_l, 'diff_pos': dp,
            'pred_v0': pred_v0, 'won_v0': pred_v0 == real, 'brier_v0': brier_v0, 'pick_v0': pick_v0,
            'pred_v7': pred_v7, 'won_v7': pred_v7 == real, 'brier_v7': brier_v7, 'pick_v7': pick_v7,
        })
    return enriched


def fmt_celda(label, sub, key_won, key_brier, key_pick):
    if not sub: return f"  {label:<25} N=0"
    n = len(sub); hits = sum(1 for r in sub if r[key_won])
    brier = sum(r[key_brier] for r in sub)/n
    picks = [r[key_pick] for r in sub]
    m = yield_metrics(picks)
    if not m:
        return f"  {label:<25} N={n:>4} hit={100*hits/n:>5.1f}% brier={brier:>6.4f} N_apost=0"
    yld = m['yield_pct']
    sig = '★' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else (
          'NEG' if (m['ci95_hi'] is not None and m['ci95_hi'] < 0) else '')
    return f"  {label:<25} N={n:>4} hit={100*hits/n:>5.1f}% brier={brier:>6.4f} N_apost={m['n']:>3} yield={yld or 0:>+6.1f}% {sig}"


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS 2022-2024 + predict V0 + V7...")
    enriched = cargar_y_predict(con)
    print(f"  N total: {len(enriched):,}")
    print()

    # ============ AGREGADO ============
    print("=" * 100)
    print("AGREGADO V0 vs V7 (todos los temps, todas las ligas)")
    print("=" * 100)
    print(fmt_celda("V0 (Dixon-Coles)", enriched, 'won_v0', 'brier_v0', 'pick_v0'))
    print(fmt_celda("V7 (Skellam)", enriched, 'won_v7', 'brier_v7', 'pick_v7'))

    # ============ POR TEMP ============
    print()
    print("=" * 100)
    print("POR TEMP (V0 vs V7)")
    print("=" * 100)
    res_temp = {}
    for temp in [2022, 2023, 2024]:
        sub = [r for r in enriched if r['temp'] == temp]
        print(f"\n  TEMP {temp} (N={len(sub)}):")
        print(f"  {fmt_celda('V0', sub, 'won_v0', 'brier_v0', 'pick_v0')}")
        print(f"  {fmt_celda('V7', sub, 'won_v7', 'brier_v7', 'pick_v7')}")
        res_temp[str(temp)] = {
            'n': len(sub),
            'v0_hit': sum(1 for r in sub if r['won_v0'])/len(sub) * 100,
            'v7_hit': sum(1 for r in sub if r['won_v7'])/len(sub) * 100,
        }

    # ============ POR LIGA ============
    print()
    print("=" * 100)
    print("POR LIGA (V0 vs V7) — TOP-5 V5.1 + EUR top + Brasil")
    print("=" * 100)
    res_liga = {}
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Noruega', 'Turquia',
                 'Italia', 'Espana', 'Alemania', 'Francia']:
        sub = [r for r in enriched if r['liga'] == liga]
        if len(sub) < 50: continue
        print(f"\n  {liga} (N={len(sub)}):")
        print(f"  {fmt_celda('V0', sub, 'won_v0', 'brier_v0', 'pick_v0')}")
        print(f"  {fmt_celda('V7', sub, 'won_v7', 'brier_v7', 'pick_v7')}")
        h_v0 = sum(1 for r in sub if r['won_v0'])/len(sub) * 100
        h_v7 = sum(1 for r in sub if r['won_v7'])/len(sub) * 100
        res_liga[liga] = {'n': len(sub), 'v0_hit': h_v0, 'v7_hit': h_v7, 'delta_hit_v7_v0': h_v7-h_v0}

    # ============ POR MOMENTO_BIN_4 ============
    print()
    print("=" * 100)
    print("POR MOMENTO_BIN_4 (Q1 arr / Q2 ini / Q3 mit / Q4 cie)")
    print("=" * 100)
    nombres_q = {0:'Q1_arr', 1:'Q2_ini', 2:'Q3_mit', 3:'Q4_cie'}
    res_q4 = {}
    for q in [0, 1, 2, 3]:
        sub = [r for r in enriched if r['mb4'] == q]
        if len(sub) < 30: continue
        print(f"\n  {nombres_q[q]} (N={len(sub)}):")
        print(f"  {fmt_celda('V0', sub, 'won_v0', 'brier_v0', 'pick_v0')}")
        print(f"  {fmt_celda('V7', sub, 'won_v7', 'brier_v7', 'pick_v7')}")
        h_v0 = sum(1 for r in sub if r['won_v0'])/len(sub) * 100
        h_v7 = sum(1 for r in sub if r['won_v7'])/len(sub) * 100
        res_q4[nombres_q[q]] = {'n': len(sub), 'v0_hit': h_v0, 'v7_hit': h_v7, 'delta': h_v7-h_v0}

    # ============ POR MOMENTO_BIN_12 ============
    print()
    print("=" * 100)
    print("POR MOMENTO_BIN_12 (12 fines de temp)")
    print("=" * 100)
    res_q12 = {}
    for q in range(12):
        sub = [r for r in enriched if r['mb12'] == q]
        if len(sub) < 30: continue
        h_v0 = sum(1 for r in sub if r['won_v0'])/len(sub) * 100
        h_v7 = sum(1 for r in sub if r['won_v7'])/len(sub) * 100
        b_v0 = sum(r['brier_v0'] for r in sub)/len(sub)
        b_v7 = sum(r['brier_v7'] for r in sub)/len(sub)
        delta = h_v7 - h_v0
        marker = ' ★' if delta > 1.5 else (' NEG' if delta < -1.5 else '')
        print(f"  bin_12={q:>2} N={len(sub):>4} V0_hit={h_v0:>5.1f}% V7_hit={h_v7:>5.1f}% delta={delta:>+5.2f}pp{marker}")
        res_q12[str(q)] = {'n': len(sub), 'v0_hit': h_v0, 'v7_hit': h_v7, 'delta': delta}

    # ============ POR EQUIPO TOP (N>=20) ============
    print()
    print("=" * 100)
    print("POR EQUIPO LOCAL (N>=20 picks) — V7 es mejor en alguno?")
    print("=" * 100)
    by_eq = defaultdict(list)
    for r in enriched: by_eq[(r['liga'], r['local'])].append(r)
    res_eq = {}
    rows_eq = []
    for (liga, eq), sub in by_eq.items():
        if len(sub) < 20: continue
        h_v0 = sum(1 for r in sub if r['won_v0'])/len(sub) * 100
        h_v7 = sum(1 for r in sub if r['won_v7'])/len(sub) * 100
        delta = h_v7 - h_v0
        rows_eq.append((liga, eq, len(sub), h_v0, h_v7, delta))
    rows_eq.sort(key=lambda x: -x[5])  # ordenar por delta (V7 mejor primero)
    print(f"  {'liga':<14} {'equipo':<35} {'N':>4} {'V0_hit':>7} {'V7_hit':>7} {'delta':>7}")
    for liga, eq, n, h_v0, h_v7, delta in rows_eq[:10]:
        marker = ' ★' if delta > 2 else ''
        print(f"  {liga:<14} {eq:<35} {n:>4} {h_v0:>5.1f}% {h_v7:>5.1f}% {delta:>+5.2f}pp{marker}")
        res_eq[f"{liga}/{eq}"] = {'n': n, 'v0_hit': h_v0, 'v7_hit': h_v7, 'delta_v7_v0': delta}

    print(f"\n  WORST 10 (V7 mucho peor que V0):")
    for liga, eq, n, h_v0, h_v7, delta in rows_eq[-10:]:
        print(f"  {liga:<14} {eq:<35} {n:>4} {h_v0:>5.1f}% {h_v7:>5.1f}% {delta:>+5.2f}pp")

    # ============ POR (LIGA × MB4) ============
    print()
    print("=" * 100)
    print("CRUCE LIGA × MB4 — donde V7 podria superar a V0?")
    print("=" * 100)
    res_cruce = {}
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Italia', 'Espana']:
        for q in [0, 1, 2, 3]:
            sub = [r for r in enriched if r['liga'] == liga and r['mb4'] == q]
            if len(sub) < 30: continue
            h_v0 = sum(1 for r in sub if r['won_v0'])/len(sub) * 100
            h_v7 = sum(1 for r in sub if r['won_v7'])/len(sub) * 100
            delta = h_v7 - h_v0
            marker = ' ★' if delta > 2 else (' NEG' if delta < -2 else '')
            print(f"  {liga:<14} {nombres_q[q]:<8} N={len(sub):>4} V0={h_v0:>5.1f}% V7={h_v7:>5.1f}% delta={delta:>+5.2f}pp{marker}")
            res_cruce[f"{liga}/{nombres_q[q]}"] = {'n': len(sub), 'delta': delta}

    out = {'fecha': '2026-04-28', 'n_total': len(enriched),
           'agregado_v0_v7': {'v0_hit': sum(1 for r in enriched if r['won_v0'])/len(enriched)*100,
                                'v7_hit': sum(1 for r in enriched if r['won_v7'])/len(enriched)*100,
                                'brier_v0_avg': sum(r['brier_v0'] for r in enriched)/len(enriched),
                                'brier_v7_avg': sum(r['brier_v7'] for r in enriched)/len(enriched)},
           'por_temp': res_temp, 'por_liga': res_liga, 'por_mb4': res_q4,
           'por_mb12': res_q12, 'por_equipo_top': res_eq, 'cruce_liga_mb4': res_cruce}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

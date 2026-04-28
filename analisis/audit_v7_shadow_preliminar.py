"""[adepor-d7h Sub-4 Track C] Audit preliminar V7 SHADOW vs V0 vs V12.

Trigger oficial: N>=80 picks SHADOW liquidados. Hoy hay 65 (81%). Audit preliminar
para ver direccion antes del trigger oficial.

Comparativa por liga TOP-5 V5.1: hit rate + Brier + yield H4-style usando cuotas
del partido (cuota_1, cuota_x, cuota_2 in partidos_backtest).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "audit_v7_shadow_preliminar.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


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
    if n == 0: return {"n_apost": 0, "yield_pct": None, "ci95_lo": None, "ci95_hi": None, "hit_pct": None}
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
    return {"n_apost": n, "hit_pct": round(100*g/n, 2), "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    # Pull SHADOW + outcomes desde partidos_backtest
    rows = cur.execute("""
        SELECT pb.pais AS liga, pb.fecha,
               psa.prob_1_actual, psa.prob_x_actual, psa.prob_2_actual,
               psa.prob_1_v6_recal, psa.prob_x_v6_recal, psa.prob_2_v6_recal,
               psa.prob_1_v7_recal_skellam, psa.prob_x_v7_recal_skellam, psa.prob_2_v7_recal_skellam,
               psa.prob_1_v12_lr, psa.prob_x_v12_lr, psa.prob_2_v12_lr,
               pb.cuota_1, pb.cuota_x, pb.cuota_2,
               pb.goles_l, pb.goles_v, pb.estado
        FROM picks_shadow_arquitecturas psa
        INNER JOIN partidos_backtest pb ON psa.id_partido = pb.id_partido
        WHERE pb.estado = 'Liquidado'
          AND pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
          AND psa.prob_1_v7_recal_skellam IS NOT NULL
          AND pb.cuota_1 > 1
        ORDER BY pb.fecha
    """).fetchall()
    print(f"N V7 SHADOW liquidados: {len(rows)}")

    enriched = []
    for liga, fecha, p1_v0, px_v0, p2_v0, p1_v6, px_v6, p2_v6, p1_v7, px_v7, p2_v7, \
        p1_v12, px_v12, p2_v12, c1, cx, c2, gl, gv, _ in rows:
        if gl is None or gv is None: continue
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        t = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)

        archs = {}
        for name, p in [('V0', (p1_v0, px_v0, p2_v0)),
                        ('V6', (p1_v6, px_v6, p2_v6)),
                        ('V7', (p1_v7, px_v7, p2_v7)),
                        ('V12', (p1_v12, px_v12, p2_v12))]:
            if not all(x is not None for x in p):
                archs[name] = None
                continue
            pred = amax(*p); won = pred == real
            brier = (p[0]-t[0])**2 + (p[1]-t[1])**2 + (p[2]-t[2])**2
            pick = evaluar_pick(p[0], p[1], p[2], c1, cx, c2, real)
            archs[name] = {'pred': pred, 'won': won, 'brier': brier, 'pick': pick}
        enriched.append({'liga': liga, 'fecha': fecha, 'real': real, 'archs': archs})

    # Resumen global por arquitectura
    print()
    print("=" * 100)
    print(f"COMPARATIVA ARCHITECTURAS — N={len(enriched)} liquidados")
    print("=" * 100)
    print(f"  {'arch':<6} {'N':>4} {'hit%':>6} {'brier':>8} {'N_apost':>7} {'yield%':>8} {'CI95':>22} {'sig':>5}")
    res_global = {}
    for arch in ['V0', 'V6', 'V7', 'V12']:
        sub = [r for r in enriched if r['archs'].get(arch)]
        if not sub: continue
        n = len(sub)
        hits = sum(1 for r in sub if r['archs'][arch]['won'])
        brier = sum(r['archs'][arch]['brier'] for r in sub)/n
        picks = [r['archs'][arch]['pick'] for r in sub]
        m = yield_metrics(picks)
        ci = f"[{m['ci95_lo'] or 0:>+5.1f},{m['ci95_hi'] or 0:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        sig = '★' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else (
              'N' if (m['ci95_hi'] is not None and m['ci95_hi'] < 0) else '')
        print(f"  {arch:<6} {n:>4} {100*hits/n:>5.1f}% {brier:>7.4f} {m['n_apost']:>7} "
              f"{m['yield_pct'] or 0:>+7.1f}% {ci:>22} {sig:>5}")
        res_global[arch] = {'n': n, 'hit_pct': round(100*hits/n,2), 'brier': round(brier,4),
                             'n_apost': m['n_apost'], 'yield_pct': m['yield_pct'],
                             'ci95_lo': m['ci95_lo'], 'ci95_hi': m['ci95_hi']}

    # Por liga
    print()
    print("=" * 100)
    print("POR LIGA (todas las architecturas, N>=4)")
    print("=" * 100)
    by_liga = defaultdict(list)
    for r in enriched: by_liga[r['liga']].append(r)
    res_liga = {}
    for liga in sorted(by_liga.keys()):
        sub = by_liga[liga]
        if len(sub) < 4: continue
        print(f"\n  {liga} (N={len(sub)}):")
        print(f"    {'arch':<6} {'hit%':>6} {'brier':>8} {'N_apost':>7} {'yield%':>8}")
        for arch in ['V0', 'V6', 'V7', 'V12']:
            picks = [r['archs'][arch]['pick'] for r in sub if r['archs'].get(arch)]
            n_arch = sum(1 for r in sub if r['archs'].get(arch))
            if n_arch == 0: continue
            hits = sum(1 for r in sub if r['archs'].get(arch) and r['archs'][arch]['won'])
            brier = sum(r['archs'][arch]['brier'] for r in sub if r['archs'].get(arch))/n_arch
            m = yield_metrics(picks)
            print(f"    {arch:<6} {100*hits/n_arch:>5.1f}% {brier:>7.4f} {m['n_apost']:>7} {m['yield_pct'] or 0:>+7.1f}%")
            res_liga[f"{liga}/{arch}"] = {'n': n_arch, 'hit_pct': round(100*hits/n_arch,2),
                                          'brier': round(brier,4), 'n_apost': m['n_apost'],
                                          'yield_pct': m['yield_pct']}

    # Comparativa head-to-head V7 vs V0 (¿en cuántos partidos coinciden? ¿en cuántos V7 supera a V0?)
    print()
    print("=" * 100)
    print("HEAD-TO-HEAD V7 vs V0 (mismo partido)")
    print("=" * 100)
    n_compared = 0; n_coincide = 0; n_v7_won_v0_lost = 0; n_v0_won_v7_lost = 0
    sum_brier_v7 = 0; sum_brier_v0 = 0
    for r in enriched:
        v0 = r['archs'].get('V0'); v7 = r['archs'].get('V7')
        if not v0 or not v7: continue
        n_compared += 1
        sum_brier_v7 += v7['brier']; sum_brier_v0 += v0['brier']
        if v0['pred'] == v7['pred']: n_coincide += 1
        if v7['won'] and not v0['won']: n_v7_won_v0_lost += 1
        if v0['won'] and not v7['won']: n_v0_won_v7_lost += 1
    print(f"  Partidos comparables: {n_compared}")
    print(f"  Argmax coincide: {n_coincide} ({100*n_coincide/n_compared:.1f}%)")
    print(f"  V7 acierta cuando V0 falla: {n_v7_won_v0_lost}")
    print(f"  V0 acierta cuando V7 falla: {n_v0_won_v7_lost}")
    print(f"  Net V7 vs V0: {n_v7_won_v0_lost - n_v0_won_v7_lost:+}")
    print(f"  Brier promedio V7: {sum_brier_v7/n_compared:.4f}")
    print(f"  Brier promedio V0: {sum_brier_v0/n_compared:.4f}")
    print(f"  Diferencia Brier: {(sum_brier_v0 - sum_brier_v7)/n_compared:+.4f} (positivo = V7 mejor)")

    payload = {'fecha': '2026-04-28', 'n_total': len(enriched),
               'res_global': res_global, 'res_liga': res_liga,
               'h2h_v7_vs_v0': {'n_comparables': n_compared, 'coincide_pct': round(100*n_coincide/n_compared,2),
                                  'net_v7_vs_v0': n_v7_won_v0_lost - n_v0_won_v7_lost,
                                  'brier_v7': round(sum_brier_v7/n_compared,4),
                                  'brier_v0': round(sum_brier_v0/n_compared,4)}}
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

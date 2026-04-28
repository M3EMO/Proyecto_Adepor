"""[adepor-4ic Track C drilling D] Argentina cold-start por equipo.

Pregunta: el yield agregado Argentina 0-4 (+74.4%) y 0-10 (+43.4%) viene de:
  (a) algunos equipos especificos (concentracion → curve-fitting riesgoso) o
  (b) distribuido cross-equipos (señal estructural mas robusta)

Drilling:
  - Por (equipo_local, bucket=0-4 / 5-10 / 0-10) con N_pred>=3
  - Per equipo + temp para ver consistencia
  - In-sample 2026 separado para validacion forward

NOTA: bucket per-equipo tiene N=2-7 → casi todas las celdas RUIDO.
      Pero permite ver TOP equipos drivers vs no-drivers.
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
OUT = ROOT / "analisis" / "audit_argentina_cold_por_equipo.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


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


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def yield_metrics(picks_lista):
    pl = [p for p in picks_lista if p]
    n = len(pl)
    if n == 0: return {"n_apost": 0, "hit_pct": None, "yield_pct": None, "ci95_lo": None, "ci95_hi": None}
    g = sum(1 for p in pl if p['gano'])
    s = sum(p['stake'] for p in pl); pr = sum(p['profit'] for p in pl)
    yld = pr / s * 100 if s > 0 else 0
    hit = g / n * 100
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
    return {"n_apost": n, "hit_pct": round(hit, 2), "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    # OOS Argentina con n_acum
    print("Cargando OOS Argentina con n_acum_l (predicciones_oos_con_features)...")
    rows_oos = cur.execute("""
        SELECT p.temp, p.fecha, p.local, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga='Argentina' AND h.equipo=p.local AND h.fecha < p.fecha
                  AND h.n_acum IS NOT NULL
                ORDER BY h.fecha DESC LIMIT 1) AS n_acum_l
        FROM predicciones_oos_con_features p
        WHERE p.liga='Argentina' AND p.psch IS NOT NULL AND p.outcome IN ('1','X','2')
        ORDER BY p.fecha
    """).fetchall()

    # In-sample 2026 Argentina
    print("Cargando in-sample 2026 Argentina (partidos_backtest)...")
    rows_2026 = cur.execute("""
        SELECT 2026, pb.fecha, pb.local, NULL AS outcome,
               pb.prob_1, pb.prob_x, pb.prob_2, pb.cuota_1, pb.cuota_x, pb.cuota_2,
               pb.goles_l, pb.goles_v,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga='Argentina' AND h.equipo=pb.local AND h.fecha < pb.fecha
                  AND h.n_acum IS NOT NULL
                ORDER BY h.fecha DESC LIMIT 1) AS n_acum_l
        FROM partidos_backtest pb
        WHERE pb.pais='Argentina' AND pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
          AND pb.prob_1 IS NOT NULL AND pb.cuota_1 > 1
          AND substr(pb.fecha, 1, 4) = '2026'
        ORDER BY pb.fecha
    """).fetchall()

    enriched = []
    for temp, fecha, ll, real, p1, px, p2, c1, cx, c2, n_acum_l in rows_oos:
        if not all([p1, px, p2, c1, cx, c2]): continue
        if n_acum_l is None or n_acum_l > 10: continue  # solo cold (0-10)
        pred = amax(p1, px, p2); won = pred == real
        pick = evaluar_pick(p1, px, p2, c1, cx, c2, real)
        bucket = '0-4' if n_acum_l < 5 else '5-10'
        enriched.append({'temp': temp, 'fecha': fecha, 'equipo': ll, 'n_acum_l': n_acum_l,
                          'bucket': bucket, 'fuente': 'oos', 'won': won, 'pick': pick})

    for temp, fecha, ll, _, p1, px, p2, c1, cx, c2, gl, gv, n_acum_l in rows_2026:
        if not all([p1, px, p2, c1, cx, c2]): continue
        if n_acum_l is None or n_acum_l > 10: continue
        if gl is None or gv is None: continue
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        pred = amax(p1, px, p2); won = pred == real
        pick = evaluar_pick(p1, px, p2, c1, cx, c2, real)
        bucket = '0-4' if n_acum_l < 5 else '5-10'
        enriched.append({'temp': temp, 'fecha': fecha, 'equipo': ll, 'n_acum_l': n_acum_l,
                          'bucket': bucket, 'fuente': 'in_sample', 'won': won, 'pick': pick})

    print(f"  N total Argentina cold (0-10): {len(enriched):,}")
    print()

    # Distribucion por temp + bucket (resumen)
    print("=" * 100)
    print("DISTRIBUCION ARGENTINA COLD-START (0-10) por temp × bucket")
    print("=" * 100)
    by_temp = defaultdict(lambda: defaultdict(int))
    for r in enriched:
        by_temp[r['temp']][r['bucket']] += 1
    print(f"  {'temp':<6} {'0-4 N':>7} {'5-10 N':>8} {'TOTAL':>7}")
    for t in sorted(by_temp.keys()):
        n04 = by_temp[t]['0-4']; n510 = by_temp[t]['5-10']
        print(f"  {t:<6} {n04:>7} {n510:>8} {n04+n510:>7}")

    # Por equipo (todos los temps combinados)
    print()
    print("=" * 100)
    print("ARGENTINA COLD-START (0-10) POR EQUIPO LOCAL — todos los temps combinados")
    print("=" * 100)
    by_eq = defaultdict(list)
    for r in enriched: by_eq[r['equipo']].append(r)
    rows_eq = []
    for eq, sub in by_eq.items():
        if len(sub) < 3: continue
        n = len(sub); hits = sum(1 for r in sub if r['won'])
        picks = [r['pick'] for r in sub]
        m = yield_metrics(picks)
        n04 = sum(1 for r in sub if r['bucket']=='0-4')
        n510 = sum(1 for r in sub if r['bucket']=='5-10')
        n_oos = sum(1 for r in sub if r['fuente']=='oos')
        n_is = sum(1 for r in sub if r['fuente']=='in_sample')
        rows_eq.append((eq, n, hits, n04, n510, n_oos, n_is, m))
    rows_eq.sort(key=lambda x: -(x[7]['yield_pct'] if x[7]['yield_pct'] is not None else -999))

    print(f"  {'equipo':<35} {'N':>3} {'hits':>4} {'0-4':>4} {'5-10':>5} {'oos':>4} {'is':>3} {'N_apost':>8} {'yield%':>9} {'CI95':>22}")
    payload_eq = {}
    for eq, n, hits, n04, n510, n_oos, n_is, m in rows_eq:
        ci = f"[{m['ci95_lo'] or 0:>+5.1f},{m['ci95_hi'] or 0:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        sig = '★' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else ''
        yld = m.get('yield_pct') or 0
        print(f"  {eq:<35} {n:>3} {hits:>4} {n04:>4} {n510:>5} {n_oos:>4} {n_is:>3} {m['n_apost']:>8} {yld:>+8.1f}% {ci:>22}{sig}")
        payload_eq[eq] = {'n': n, 'hits': hits, 'n04': n04, 'n510': n510,
                           'n_oos': n_oos, 'n_is': n_is, 'n_apost': m['n_apost'],
                           'yield_pct': m['yield_pct'], 'ci95_lo': m['ci95_lo'], 'ci95_hi': m['ci95_hi']}

    # Concentracion: ¿qué % del yield total viene de los top 5 equipos?
    print()
    print("=" * 100)
    print("CONCENTRACION DE YIELD: top equipos vs resto")
    print("=" * 100)
    rows_eq_sorted = sorted(rows_eq, key=lambda x: -x[7]['n_apost'])
    print(f"\n  TOP-5 equipos por N_apost:")
    top5 = rows_eq_sorted[:5]
    for eq, n, hits, n04, n510, n_oos, n_is, m in top5:
        yld = m.get('yield_pct') or 0
        print(f"    {eq:<35} N_apost={m['n_apost']:>3} yield={yld:>+6.1f}%")

    # Total profit: top5 vs resto
    profit_total = sum(p['profit'] for r in enriched if r['pick'] for p in [r['pick']])
    stake_total = sum(p['stake'] for r in enriched if r['pick'] for p in [r['pick']])
    eq_top5_set = set(t[0] for t in top5)
    profit_top5 = sum(r['pick']['profit'] for r in enriched
                     if r['pick'] and r['equipo'] in eq_top5_set)
    stake_top5 = sum(r['pick']['stake'] for r in enriched
                    if r['pick'] and r['equipo'] in eq_top5_set)
    print(f"\n  Stake total cold-start: {stake_total:.4f}")
    print(f"  Stake top-5: {stake_top5:.4f} ({100*stake_top5/stake_total:.1f}% del total)")
    print(f"  Profit total: {profit_total:+.4f}")
    print(f"  Profit top-5: {profit_top5:+.4f} ({100*profit_top5/profit_total:+.1f}% del total)")
    yield_top5 = profit_top5/stake_top5*100 if stake_top5 > 0 else 0
    yield_resto = (profit_total-profit_top5)/(stake_total-stake_top5)*100 if (stake_total-stake_top5) > 0 else 0
    print(f"  Yield top-5: {yield_top5:+.1f}%")
    print(f"  Yield resto: {yield_resto:+.1f}%")

    # Robustez cross-temp: equipos con N_apost>=3 en cada temp
    print()
    print("=" * 100)
    print("EQUIPOS CON COLD-START EN MULTIPLES TEMPS (validacion robustez)")
    print("=" * 100)
    by_eq_temp = defaultdict(lambda: defaultdict(list))
    for r in enriched:
        by_eq_temp[r['equipo']][r['temp']].append(r)
    print(f"  {'equipo':<35} {'2022':>20} {'2023':>20} {'2024':>20} {'2026':>20}")
    for eq, sub in by_eq.items():
        if len(sub) < 5: continue
        cells = []
        for t in [2022, 2023, 2024, 2026]:
            cell = by_eq_temp[eq].get(t, [])
            if not cell:
                cells.append('       -')
                continue
            picks = [r['pick'] for r in cell]
            m = yield_metrics(picks)
            yld = m.get('yield_pct')
            if yld is None or m['n_apost'] == 0:
                cells.append(f"   N={len(cell)} 0apost")
            else:
                cells.append(f"y={yld:+5.0f}%({m['n_apost']}/{len(cell)})")
        print(f"  {eq:<35} {cells[0]:>20} {cells[1]:>20} {cells[2]:>20} {cells[3]:>20}")

    payload = {'fecha': '2026-04-28', 'n_total_cold': len(enriched),
               'por_equipo': payload_eq,
               'concentracion_top5': {'stake_pct': round(100*stake_top5/stake_total,2) if stake_total else None,
                                       'profit_pct': round(100*profit_top5/profit_total,2) if profit_total else None,
                                       'yield_top5': round(yield_top5,2),
                                       'yield_resto': round(yield_resto,2)}}
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

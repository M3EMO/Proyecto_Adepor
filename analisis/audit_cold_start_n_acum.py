"""[adepor-4ic Track C v3] Audit n_acum_local con buckets finos + in-sample 2026.

V3 (2026-04-28): refinado tras observacion del usuario:
  - Buckets finos: 0-4 / 5-10 / 11-20 / 21-30 / 31-40 / 41-50 / 51-59 / >=60
    (antes 31-59 era un solo bucket y enmascaraba heterogeneidad)
  - Cross-temp: 2022 / 2023 / 2024 + IN-SAMPLE 2026 (partidos_backtest liquidados)
  - Por liga TOP-5 V5.1 con buckets finos
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "audit_cold_start_n_acum.json"

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


def bucket_n_acum(n):
    if n is None: return 'NULL'
    if n < 5: return '0-4'
    if n < 11: return '5-10'
    if n < 21: return '11-20'
    if n < 31: return '21-30'
    if n < 41: return '31-40'
    if n < 51: return '41-50'
    if n < 60: return '51-59'
    return '>=60'


BUCKETS_ORDER = ['0-4', '5-10', '11-20', '21-30', '31-40', '41-50', '51-59', '>=60']


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


def fmt_row(label, n, hit_pct, brier, m):
    ci = f"[{m['ci95_lo'] or 0:>+5.1f},{m['ci95_hi'] or 0:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
    sig = '***' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else (
          'NEG' if (m['ci95_hi'] is not None and m['ci95_hi'] < 0) else '.')
    return (f"{label:<13} {n:>5} {hit_pct:>5.1f}% {brier:>7.4f} {m['n_apost']:>7} "
            f"{m['yield_pct'] or 0:>+7.1f}% {ci:>22} {sig:>5}")


def cargar_oos(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.liga, p.temp, p.fecha, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga=p.liga AND h.equipo=p.local AND h.fecha < p.fecha
                  AND h.n_acum IS NOT NULL
                ORDER BY h.fecha DESC LIMIT 1) AS n_acum_l
        FROM predicciones_oos_con_features p
        WHERE p.psch IS NOT NULL AND p.outcome IN ('1','X','2')
        ORDER BY p.fecha
    """).fetchall()
    enriched = []
    for liga, temp, fecha, ll, vv, real, p1, px, p2, c1, cx, c2, n_acum_l in rows:
        if not all([p1, px, p2, c1, cx, c2]): continue
        pred = amax(p1, px, p2); won = pred == real
        t = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)
        brier = (p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2
        pick = evaluar_pick(p1, px, p2, c1, cx, c2, real)
        enriched.append({'liga': liga, 'temp': temp, 'fuente': 'oos', 'n_acum_l': n_acum_l,
                          'bucket': bucket_n_acum(n_acum_l), 'won': won, 'brier': brier, 'pick': pick})
    return enriched


def cargar_in_sample_2026(con):
    """Carga partidos_backtest 2026 liquidados con prob_1/x/2 + cuotas."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pb.pais AS liga, pb.fecha, pb.local, pb.visita, pb.goles_l, pb.goles_v,
               pb.prob_1, pb.prob_x, pb.prob_2, pb.cuota_1, pb.cuota_x, pb.cuota_2,
               (SELECT n_acum FROM historial_equipos_stats h
                WHERE h.liga=pb.pais AND h.equipo=pb.local AND h.fecha < pb.fecha
                  AND h.n_acum IS NOT NULL
                ORDER BY h.fecha DESC LIMIT 1) AS n_acum_l
        FROM partidos_backtest pb
        WHERE pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
          AND pb.prob_1 IS NOT NULL AND pb.cuota_1 > 1
          AND substr(pb.fecha, 1, 4) = '2026'
        ORDER BY pb.fecha
    """).fetchall()
    enriched = []
    for liga, fecha, ll, vv, gl, gv, p1, px, p2, c1, cx, c2, n_acum_l in rows:
        if gl is None or gv is None: continue
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        if not all([p1, px, p2, c1, cx, c2]): continue
        pred = amax(p1, px, p2); won = pred == real
        t = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)
        brier = (p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2
        pick = evaluar_pick(p1, px, p2, c1, cx, c2, real)
        enriched.append({'liga': liga, 'temp': 2026, 'fuente': 'in_sample', 'n_acum_l': n_acum_l,
                          'bucket': bucket_n_acum(n_acum_l), 'won': won, 'brier': brier, 'pick': pick})
    return enriched


def reporte(enriched_universo, titulo):
    print(f"\n{'='*100}")
    print(f"{titulo}")
    print(f"{'='*100}")
    print(f"{'bucket':<13} {'N':>5} {'hit%':>6} {'brier':>8} {'N_apost':>7} {'yield%':>8} {'CI95':>22} {'sig':>5}")
    res = {}
    for b in BUCKETS_ORDER:
        sub = [r for r in enriched_universo if r['bucket'] == b]
        if not sub: continue
        n = len(sub); hits = sum(1 for r in sub if r['won'])
        brier = sum(r['brier'] for r in sub)/n
        picks = [r['pick'] for r in sub]
        m = yield_metrics(picks)
        print(fmt_row(b, n, 100*hits/n, brier, m))
        res[b] = {'n': n, 'hit_pct': round(100*hits/n, 2), 'brier': round(brier, 4),
                  'n_apost': m['n_apost'], 'yield_pct': m['yield_pct'],
                  'ci95_lo': m['ci95_lo'], 'ci95_hi': m['ci95_hi']}
    return res


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS 2022-2024 (predicciones_oos_con_features)...")
    enriched_oos = cargar_oos(con)
    print(f"  N OOS: {len(enriched_oos):,}")

    print("Cargando in-sample 2026 (partidos_backtest)...")
    enriched_2026 = cargar_in_sample_2026(con)
    print(f"  N in-sample 2026: {len(enriched_2026):,}")

    todos = enriched_oos + enriched_2026

    # ============ POR TEMP (incluyendo 2026) ============
    payload = {'fecha': '2026-04-28', 'n_oos': len(enriched_oos), 'n_in_sample': len(enriched_2026),
               'por_temp': {}, 'por_liga_bucket': {}, 'in_sample_only': {}}
    for temp in [2022, 2023, 2024, 2026]:
        sub = [r for r in todos if r['temp'] == temp]
        if not sub: continue
        payload['por_temp'][str(temp)] = reporte(sub, f"TEMP {temp} (fuente={'in-sample' if temp==2026 else 'OOS'})")

    # ============ AGREGADO 2022-2024 ============
    reporte(enriched_oos, "AGREGADO OOS 2022-2024")

    # ============ POR LIGA × BUCKET × TEMP (3D grid) ============
    print(f"\n{'='*100}")
    print(f"GRID 3D: LIGA × BUCKET × TEMP — yield% (N_apost) — solo celdas con N>=8")
    print(f"{'='*100}")
    print(f"  Cells: 'yield% (N_apost/N_pred)' — '★' si CI95_lo>0, 'NEG' si CI95_hi<0, '~' si N<10")
    payload['grid_3d'] = {}
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Noruega', 'Turquia']:
        sub = [r for r in todos if r['liga'] == liga]
        if not sub: continue
        print(f"\n  {liga} (N total={len(sub)}):")
        print(f"    {'bucket':<8} | {'2022':>22} | {'2023':>22} | {'2024':>22} | {'2026 in-sample':>22}")
        print(f"    {'-'*8} + {'-'*22} + {'-'*22} + {'-'*22} + {'-'*22}")
        for b in BUCKETS_ORDER:
            cells = []
            for temp in [2022, 2023, 2024, 2026]:
                cell = [r for r in sub if r['bucket'] == b and r['temp'] == temp]
                if not cell:
                    cells.append('     -                ')
                    continue
                n = len(cell)
                picks = [r['pick'] for r in cell]
                m = yield_metrics(picks)
                tag = '~' if n < 10 else ('★' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else (
                                            'N' if (m['ci95_hi'] is not None and m['ci95_hi'] < 0) else ' '))
                yld = m.get('yield_pct')
                yld_s = f"{yld:+6.1f}%" if yld is not None else "  n/a "
                cells.append(f"{yld_s} ({m['n_apost']:>2}/{n:>2}){tag}     ")
                payload['grid_3d'][f"{liga}/{b}/{temp}"] = {
                    'n': n, 'n_apost': m['n_apost'], 'yield_pct': yld,
                    'ci95_lo': m['ci95_lo'], 'ci95_hi': m['ci95_hi']}
            row_has_data = any('     -' not in c for c in cells)
            if row_has_data:
                print(f"    {b:<8} | {cells[0]:>22} | {cells[1]:>22} | {cells[2]:>22} | {cells[3]:>22}")

    # ============ IN-SAMPLE 2026 SEPARADO + POR LIGA ============
    print(f"\n{'='*100}")
    print(f"IN-SAMPLE 2026 — bucket × liga (validacion régimen actual)")
    print(f"{'='*100}")
    print(f"  Total in-sample N={len(enriched_2026)}")
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Noruega', 'Turquia']:
        sub = [r for r in enriched_2026 if r['liga'] == liga]
        if len(sub) < 5: continue
        print(f"\n  {liga} (N_in_sample={len(sub)}):")
        print(f"    {'bucket':<13} {'N':>5} {'hit%':>6} {'brier':>8} {'N_apost':>7} {'yield%':>8} {'CI95':>22} {'sig':>5}")
        for b in BUCKETS_ORDER:
            cell = [r for r in sub if r['bucket'] == b]
            if not cell: continue
            n = len(cell); hits = sum(1 for r in cell if r['won'])
            brier = sum(r['brier'] for r in cell)/n
            picks = [r['pick'] for r in cell]
            m = yield_metrics(picks)
            print(f"    {fmt_row(b, n, 100*hits/n, brier, m)}")
            payload['in_sample_only'][f"{liga}/{b}"] = {'n': n, 'hit_pct': round(100*hits/n,2),
                                                         'n_apost': m['n_apost'], 'yield_pct': m['yield_pct'],
                                                         'ci95_lo': m['ci95_lo'], 'ci95_hi': m['ci95_hi']}

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

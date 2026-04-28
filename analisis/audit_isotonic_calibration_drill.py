"""[adepor-4ic Sub-3] Calibracion isotonica V0 — drill multidim.

Hipotesis: V0 puede estar mal calibrado en algun bucket (liga × temp × momento × pos).
La calibracion isotonica per-liga corrige el mapeo prob_predicha -> frecuencia_real
sin asumir forma parametrica.

Metodologia:
  1. Train fit sobre 2022 + 2023 (Train).
  2. Test predict sobre 2024 OOS held-out.
  3. Comparar V0 raw vs V0_isotonic: hit rate + Brier + yield.
  4. Drill por (liga, temp, momento_bin_4) y per-equipo top.

Resultado esperado: Brier mejora (por construccion). Yield: incierto (paradoja
Brier-Yield documentada — yield_v0 ya alto sin calibracion).

OUT: analisis/audit_isotonic_calibration_drill.json
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
OUT = ROOT / "analisis" / "audit_isotonic_calibration_drill.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from sklearn.isotonic import IsotonicRegression
except ImportError:
    print("sklearn requerido. Instalar: pip install scikit-learn")
    sys.exit(1)


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


def yield_metrics(picks):
    pl = [p for p in picks if p]
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


def fit_isotonic_per_outcome(train_rows):
    """Fit 3 IsotonicRegression: prob_1 -> P(real='1'); prob_x -> P(real='X'); prob_2 -> P(real='2')."""
    iso = {}
    for outcome, prob_key in [('1', 'prob_1'), ('X', 'prob_x'), ('2', 'prob_2')]:
        x = np.array([r[prob_key] for r in train_rows])
        y = np.array([1.0 if r['real'] == outcome else 0.0 for r in train_rows])
        m = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
        m.fit(x, y)
        iso[outcome] = m
    return iso


def apply_isotonic(iso, p1_raw, px_raw, p2_raw):
    p1 = float(iso['1'].predict([p1_raw])[0])
    px = float(iso['X'].predict([px_raw])[0])
    p2 = float(iso['2'].predict([p2_raw])[0])
    s = p1 + px + p2
    if s <= 0: return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


def cargar_oos(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.liga, p.temp, p.fecha, p.local, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4, p.momento_bin_12
        FROM predicciones_oos_con_features p
        WHERE p.psch IS NOT NULL AND p.outcome IN ('1','X','2')
        ORDER BY p.fecha
    """).fetchall()
    out = []
    for liga, temp, fecha, ll, real, p1, px, p2, c1, cx, c2, mb4, mb12 in rows:
        if not all([p1, px, p2, c1, cx, c2]): continue
        out.append({'liga': liga, 'temp': temp, 'fecha': fecha, 'local': ll,
                     'real': real, 'prob_1': p1, 'prob_x': px, 'prob_2': p2,
                     'c1': c1, 'cx': cx, 'c2': c2, 'mb4': mb4, 'mb12': mb12})
    return out


def fmt_compare(label_test, raw_picks, cal_picks, raw_brier_avg, cal_brier_avg, raw_hits, cal_hits, n):
    raw_y = yield_metrics(raw_picks)
    cal_y = yield_metrics(cal_picks)
    raw_yld = raw_y['yield_pct'] if raw_y else 0
    cal_yld = cal_y['yield_pct'] if cal_y else 0
    raw_n_apost = raw_y['n'] if raw_y else 0
    cal_n_apost = cal_y['n'] if cal_y else 0
    return (f"  {label_test:<32} N={n:>4} | "
            f"V0_raw  hit={100*raw_hits/n:>5.1f}% brier={raw_brier_avg:>6.4f} N_apost={raw_n_apost:>3} yield={raw_yld:>+6.1f}%\n"
            f"  {' '*32}        | V0_cal  hit={100*cal_hits/n:>5.1f}% brier={cal_brier_avg:>6.4f} N_apost={cal_n_apost:>3} yield={cal_yld:>+6.1f}%\n"
            f"  {' '*32}        | DELTA   hit={100*(cal_hits-raw_hits)/n:>+5.2f}pp brier={cal_brier_avg-raw_brier_avg:>+7.4f}     yield={cal_yld-raw_yld:>+6.1f}pp")


def evaluar_subset(test_rows, iso):
    """Para un subset de test, devuelve metricas raw + calibrado."""
    raw_hits = 0; cal_hits = 0
    raw_brier_sum = 0; cal_brier_sum = 0
    raw_picks = []; cal_picks = []
    for r in test_rows:
        p1_r, px_r, p2_r = r['prob_1'], r['prob_x'], r['prob_2']
        p1_c, px_c, p2_c = apply_isotonic(iso, p1_r, px_r, p2_r)
        real = r['real']
        t = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)
        # Raw
        if amax(p1_r, px_r, p2_r) == real: raw_hits += 1
        raw_brier_sum += (p1_r-t[0])**2 + (px_r-t[1])**2 + (p2_r-t[2])**2
        raw_picks.append(evaluar_pick(p1_r, px_r, p2_r, r['c1'], r['cx'], r['c2'], real))
        # Calibrado
        if amax(p1_c, px_c, p2_c) == real: cal_hits += 1
        cal_brier_sum += (p1_c-t[0])**2 + (px_c-t[1])**2 + (p2_c-t[2])**2
        cal_picks.append(evaluar_pick(p1_c, px_c, p2_c, r['c1'], r['cx'], r['c2'], real))
    n = len(test_rows)
    return {
        'n': n, 'raw_hits': raw_hits, 'cal_hits': cal_hits,
        'raw_brier_avg': raw_brier_sum/n if n else 0, 'cal_brier_avg': cal_brier_sum/n if n else 0,
        'raw_picks': raw_picks, 'cal_picks': cal_picks,
    }


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS predicciones_oos_con_features...")
    rows = cargar_oos(con)
    print(f"  N total: {len(rows):,}")

    train_rows = [r for r in rows if r['temp'] in (2022, 2023)]
    test_rows  = [r for r in rows if r['temp'] == 2024]
    print(f"  Train (2022+2023): {len(train_rows):,}")
    print(f"  Test (2024 held-out): {len(test_rows):,}")

    # ============ Calibracion GLOBAL ============
    print("\nFit isotonic GLOBAL (todas las ligas)...")
    iso_global = fit_isotonic_per_outcome(train_rows)

    print("\n" + "="*100)
    print("AGREGADO 2024 (calibracion GLOBAL)")
    print("="*100)
    res_global = evaluar_subset(test_rows, iso_global)
    print(fmt_compare("test 2024 global", res_global['raw_picks'], res_global['cal_picks'],
                       res_global['raw_brier_avg'], res_global['cal_brier_avg'],
                       res_global['raw_hits'], res_global['cal_hits'], res_global['n']))

    # ============ Calibracion PER-LIGA ============
    print("\n" + "="*100)
    print("PER-LIGA (calibracion isotonica fit en 2022+2023, test 2024)")
    print("="*100)
    payload = {'fecha': '2026-04-28', 'global_2024': res_global, 'per_liga': {}, 'per_mb4': {}, 'per_temp': {}, 'in_sample_2026': None}
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Noruega', 'Turquia',
                 'Italia', 'Espana', 'Alemania', 'Francia']:
        train_l = [r for r in train_rows if r['liga'] == liga]
        test_l  = [r for r in test_rows  if r['liga'] == liga]
        if len(train_l) < 50 or len(test_l) < 30: continue
        iso_l = fit_isotonic_per_outcome(train_l)
        res_l = evaluar_subset(test_l, iso_l)
        print(fmt_compare(f"{liga} (train={len(train_l)} test={len(test_l)})",
                            res_l['raw_picks'], res_l['cal_picks'],
                            res_l['raw_brier_avg'], res_l['cal_brier_avg'],
                            res_l['raw_hits'], res_l['cal_hits'], res_l['n']))
        payload['per_liga'][liga] = {
            'n_train': len(train_l), 'n_test': len(test_l),
            'raw_hit': 100*res_l['raw_hits']/res_l['n'],
            'cal_hit': 100*res_l['cal_hits']/res_l['n'],
            'raw_brier': res_l['raw_brier_avg'], 'cal_brier': res_l['cal_brier_avg'],
            'raw_yield': yield_metrics(res_l['raw_picks'])['yield_pct'] if res_l['raw_picks'] else None,
            'cal_yield': yield_metrics(res_l['cal_picks'])['yield_pct'] if res_l['cal_picks'] else None,
        }

    # ============ POR MOMENTO_BIN_4 (con calibracion global) ============
    print("\n" + "="*100)
    print("POR MOMENTO_BIN_4 (calibracion global, test 2024)")
    print("="*100)
    nombres_q = {0:'Q1_arr', 1:'Q2_ini', 2:'Q3_mit', 3:'Q4_cie'}
    for q in [0, 1, 2, 3]:
        sub_test = [r for r in test_rows if r['mb4'] == q]
        if len(sub_test) < 30: continue
        res_q = evaluar_subset(sub_test, iso_global)
        print(fmt_compare(f"{nombres_q[q]} 2024", res_q['raw_picks'], res_q['cal_picks'],
                            res_q['raw_brier_avg'], res_q['cal_brier_avg'],
                            res_q['raw_hits'], res_q['cal_hits'], res_q['n']))
        payload['per_mb4'][nombres_q[q]] = {
            'n': res_q['n'],
            'raw_hit': 100*res_q['raw_hits']/res_q['n'],
            'cal_hit': 100*res_q['cal_hits']/res_q['n'],
            'raw_brier': res_q['raw_brier_avg'], 'cal_brier': res_q['cal_brier_avg'],
            'raw_yield': yield_metrics(res_q['raw_picks'])['yield_pct'] if res_q['raw_picks'] else None,
            'cal_yield': yield_metrics(res_q['cal_picks'])['yield_pct'] if res_q['cal_picks'] else None,
        }

    # ============ TRAIN cross-temp: fit cada temp, evaluar en otra ============
    print("\n" + "="*100)
    print("CROSS-TEMP: fit en una temp, evaluar en otra (validacion robustez)")
    print("="*100)
    for fit_temp, eval_temp in [(2022, 2023), (2022, 2024), (2023, 2024), (2024, 2023)]:
        train_t = [r for r in rows if r['temp'] == fit_temp]
        test_t  = [r for r in rows if r['temp'] == eval_temp]
        if not train_t or not test_t: continue
        iso_t = fit_isotonic_per_outcome(train_t)
        res_t = evaluar_subset(test_t, iso_t)
        print(fmt_compare(f"fit {fit_temp} -> eval {eval_temp}", res_t['raw_picks'], res_t['cal_picks'],
                            res_t['raw_brier_avg'], res_t['cal_brier_avg'],
                            res_t['raw_hits'], res_t['cal_hits'], res_t['n']))
        payload['per_temp'][f"{fit_temp}_to_{eval_temp}"] = {
            'n_train': len(train_t), 'n_test': len(test_t),
            'raw_brier': res_t['raw_brier_avg'], 'cal_brier': res_t['cal_brier_avg'],
            'raw_yield': yield_metrics(res_t['raw_picks'])['yield_pct'] if res_t['raw_picks'] else None,
            'cal_yield': yield_metrics(res_t['cal_picks'])['yield_pct'] if res_t['cal_picks'] else None,
        }

    # ============ IN-SAMPLE 2026 (fit on full OOS 2022-2024) ============
    print("\n" + "="*100)
    print("IN-SAMPLE 2026 (fit calibracion en TODO OOS 2022-2024, test 2026)")
    print("="*100)
    cur = con.cursor()
    rows_2026 = cur.execute("""
        SELECT pb.pais AS liga, pb.fecha, pb.local, pb.goles_l, pb.goles_v,
               pb.prob_1, pb.prob_x, pb.prob_2, pb.cuota_1, pb.cuota_x, pb.cuota_2
        FROM partidos_backtest pb
        WHERE pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
          AND pb.prob_1 IS NOT NULL AND pb.cuota_1 > 1
          AND substr(pb.fecha, 1, 4) = '2026'
        ORDER BY pb.fecha
    """).fetchall()
    test_2026 = []
    for liga, fecha, ll, gl, gv, p1, px, p2, c1, cx, c2 in rows_2026:
        if not all([p1, px, p2, c1, cx, c2]): continue
        if gl is None or gv is None: continue
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        test_2026.append({'liga': liga, 'temp': 2026, 'fecha': fecha, 'local': ll,
                            'real': real, 'prob_1': p1, 'prob_x': px, 'prob_2': p2,
                            'c1': c1, 'cx': cx, 'c2': c2, 'mb4': None, 'mb12': None})
    iso_full = fit_isotonic_per_outcome(rows)
    res_2026 = evaluar_subset(test_2026, iso_full)
    print(fmt_compare("test 2026 in-sample", res_2026['raw_picks'], res_2026['cal_picks'],
                        res_2026['raw_brier_avg'], res_2026['cal_brier_avg'],
                        res_2026['raw_hits'], res_2026['cal_hits'], res_2026['n']))
    payload['in_sample_2026'] = {
        'n': res_2026['n'],
        'raw_hit': 100*res_2026['raw_hits']/res_2026['n'],
        'cal_hit': 100*res_2026['cal_hits']/res_2026['n'],
        'raw_brier': res_2026['raw_brier_avg'], 'cal_brier': res_2026['cal_brier_avg'],
        'raw_yield': yield_metrics(res_2026['raw_picks'])['yield_pct'] if res_2026['raw_picks'] else None,
        'cal_yield': yield_metrics(res_2026['cal_picks'])['yield_pct'] if res_2026['cal_picks'] else None,
    }

    # In-sample por liga
    print()
    print("IN-SAMPLE 2026 por liga TOP-5:")
    for liga in ['Argentina', 'Brasil', 'Inglaterra', 'Noruega', 'Turquia']:
        sub_test = [r for r in test_2026 if r['liga'] == liga]
        if len(sub_test) < 5: continue
        res_l = evaluar_subset(sub_test, iso_full)
        print(fmt_compare(f"in-sample {liga}", res_l['raw_picks'], res_l['cal_picks'],
                            res_l['raw_brier_avg'], res_l['cal_brier_avg'],
                            res_l['raw_hits'], res_l['cal_hits'], res_l['n']))

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

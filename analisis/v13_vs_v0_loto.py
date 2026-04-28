"""adepor-3ip Audit V13 vs V0 con leave-one-temp-out (LOTO).

Preguntas usuario:
  1. V0 vs V13 in sample, ¿como evoluciona por temporada?
  2. ¿Como le va a V13 en 2022 y 2023 (no solo 2024 OOS estricto)?
  3. ¿Volumen y yield V13 vs V0 in-sample?

Metodologia LOTO:
  Para test=2022: train V13 con 2023+2024.
  Para test=2023: train V13 con 2022+2024.
  Para test=2024: train V13 con 2022+2023 (igual que grid original).
  Asi cada temp se testea con calibracion fuera de su data (cleaner).

Uso solo BEST variant por liga (calibrada con metodo+feature_set del grid extended)
y replico la calibracion con el train_temps correspondiente.
"""
from __future__ import annotations

import json
import math
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
OUT = Path(__file__).resolve().parent / "v13_vs_v0_loto.json"

RHO_FALLBACK = -0.09

# Importar features y regs del grid extended
sys.path.insert(0, str(ROOT / "analisis"))
from v13_grid_search_extended import (
    FEATURE_SETS, _feat_value, fit_ols, fit_nnls, fit_ridge, fit_elasticnet,
    cv_ridge, cv_elasticnet, LAMBDAS_RIDGE
)


# === Setup BEST por liga (extraido de grid extended) ===
BEST_VARIANT = {
    "Argentina":  {"feat": "F5_ratio", "reg": "NNLS"},
    "Francia":    {"feat": "F4_disc",  "reg": "RIDGE"},
    "Inglaterra": {"feat": "F5_ratio", "reg": "NNLS"},
    "Italia":     {"feat": "F2_pos",   "reg": "RIDGE"},
}


def cargar_dataset_full(con):
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag,
               (SELECT json_object(
                    'ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners,
                    'ema_l_yellow', ema_l_yellow, 'ema_l_red', ema_l_red,
                    'ema_l_fouls', ema_l_fouls, 'ema_l_shots', ema_l_shots,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks,
                    'ema_c_yellow', ema_c_yellow)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.ht AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               (SELECT json_object(
                    'ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners,
                    'ema_l_yellow', ema_l_yellow, 'ema_l_red', ema_l_red,
                    'ema_l_fouls', ema_l_fouls, 'ema_l_shots', ema_l_shots,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks,
                    'ema_c_yellow', ema_c_yellow)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.at AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_v_json,
               (SELECT json_object(
                    'prob_1', prob_1, 'prob_x', prob_x, 'prob_2', prob_2,
                    'psch', psch, 'pscd', pscd, 'psca', psca, 'outcome', outcome)
                FROM predicciones_oos_con_features
                WHERE liga=phe.liga
                  AND substr(fecha,1,10) = substr(phe.fecha,1,10)
                  AND local=phe.ht AND visita=phe.at
                LIMIT 1) AS oos_json
        FROM partidos_historico_externo phe
        WHERE phe.hg IS NOT NULL AND phe.ag IS NOT NULL
          AND phe.temp IN (2022, 2023, 2024)
    """
    rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if not d["ema_l_json"] or not d["ema_v_json"] or not d["oos_json"]:
            continue
        try:
            d["ema_l"] = json.loads(d["ema_l_json"])
            d["ema_v"] = json.loads(d["ema_v_json"])
            d["oos"] = json.loads(d["oos_json"])
        except Exception:
            continue
        if any(v is None for v in d["ema_l"].values()):
            continue
        if any(v is None for v in d["ema_v"].values()):
            continue
        out.append(d)
    return out


def construir_features(row, feature_set, target_local=True):
    if target_local:
        ema_atk, ema_def = row["ema_l"], row["ema_v"]
    else:
        ema_atk, ema_def = row["ema_v"], row["ema_l"]
    feats = []
    for name in feature_set:
        v = _feat_value(name, ema_atk, ema_def)
        if v is None: return None
        feats.append(float(v))
    return np.array(feats)


def calibrar_loto(rows_liga, train_temps, feature_set, reg, target_local=True):
    """Calibra V13 sobre rows_liga con train_temps. Retorna (intercept, coefs)."""
    train = [r for r in rows_liga if r["temp"] in train_temps]
    if len(train) < 100: return None, None
    X = np.array([construir_features(r, feature_set, target_local) for r in train if construir_features(r, feature_set, target_local) is not None])
    if len(X) != len(train): return None, None
    y = np.array([r["hg"] if target_local else r["ag"] for r in train], dtype=float)

    if reg == "OLS":
        return fit_ols(X, y)
    if reg == "NNLS":
        return fit_nnls(X, y)
    if reg == "RIDGE":
        lam = cv_ridge(X, y, LAMBDAS_RIDGE)
        return fit_ridge(X, y, lam)
    if reg == "ENET":
        lam, alpha = cv_elasticnet(X, y, [0.001, 0.01, 0.1, 1.0], [0.1, 0.3, 0.5, 0.7, 0.9])
        return fit_elasticnet(X, y, lam, alpha, max_iter=500)
    return None, None


def poisson_pmf(k, lam):
    if lam <= 0: return 0.0 if k > 0 else 1.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def tau_dc(i, j, lam, mu, rho):
    if i == 0 and j == 0: return 1.0 - lam * mu * rho
    if i == 1 and j == 0: return 1.0 + mu * rho
    if i == 0 and j == 1: return 1.0 + lam * rho
    if i == 1 and j == 1: return 1.0 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho=RHO_FALLBACK, max_g=8):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    if s <= 0: return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


def kelly_fraction(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05: return None
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(opts, key=lambda x: x[1])
    if not cuota or cuota <= 1.0 or prob * cuota - 1 < 0.03: return None
    stake = kelly_fraction(prob, cuota)
    if stake <= 0: return None
    return {"stake": stake,
            "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def brier_3way(p1, px, p2, outcome):
    t = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(outcome)
    if t is None: return None
    return (p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2


def yield_metrics(picks):
    n = sum(1 for p in picks if p)
    g = sum(1 for p in picks if p and p["gano"])
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    yld = pl / s * 100 if s > 0 else 0
    hit = g / n * 100 if n > 0 else 0
    pares = [(p["stake"], p["profit"]) for p in picks if p]
    if pares:
        rng = np.random.default_rng(42)
        sk = np.array([p[0] for p in pares]); pr = np.array([p[1] for p in pares])
        ys = []
        for _ in range(500):
            idx = rng.integers(0, len(pares), size=len(pares))
            ss, pp = sk[idx].sum(), pr[idx].sum()
            if ss > 0: ys.append(pp / ss * 100)
        lo, hi = (float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))) if ys else (None, None)
    else:
        lo = hi = None
    return {"n_apost": n, "n_gano": g, "hit_pct": round(hit, 2),
            "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def main():
    con = sqlite3.connect(DB)
    print("Cargando dataset full (3 temps con OOS)...")
    rows = cargar_dataset_full(con)
    print(f"  N partidos con full features: {len(rows):,}")

    by_liga = defaultdict(list)
    for r in rows: by_liga[r["liga"]].append(r)

    payload = {"loto_results": {}}

    print("\n=== LOTO V13 vs V0 productivo por temp ===")
    print("V0 productivo = prob_1/prob_x/prob_2 de predicciones_oos_con_features (incluye HG+Fix5).")
    print()

    for test_temp in [2022, 2023, 2024]:
        train_temps = [t for t in [2022, 2023, 2024] if t != test_temp]
        print(f"\n--- TEST temp {test_temp} (train: {train_temps}) ---")
        print(f"{'liga':<14} {'arch':<5} {'NPred':>5} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'Brier':>7} {'CI95':>22}")
        payload["loto_results"][test_temp] = {}
        global_v0_picks, global_v0_briers = [], []
        global_v13_picks, global_v13_briers = [], []
        for liga, best in BEST_VARIANT.items():
            rows_liga = by_liga.get(liga, [])
            if not rows_liga: continue
            test_rows = [r for r in rows_liga if r["temp"] == test_temp]
            if len(test_rows) < 30: continue

            # Calibracion V13 LOTO
            fset = FEATURE_SETS[best["feat"]]
            ic_l, cf_l = calibrar_loto(rows_liga, train_temps, fset, best["reg"], True)
            ic_v, cf_v = calibrar_loto(rows_liga, train_temps, fset, best["reg"], False)

            # V0 picks (productivo)
            v0_picks_liga = []
            v0_briers_liga = []
            v13_picks_liga = []
            v13_briers_liga = []
            for r in test_rows:
                o = r["oos"]
                # V0
                p_v0 = evaluar_pick(o["prob_1"], o["prob_x"], o["prob_2"],
                                      o["psch"], o["pscd"], o["psca"], o["outcome"])
                v0_picks_liga.append(p_v0)
                b_v0 = brier_3way(o["prob_1"], o["prob_x"], o["prob_2"], o["outcome"])
                if b_v0 is not None: v0_briers_liga.append(b_v0)
                # V13
                if ic_l is not None and ic_v is not None:
                    feats_l = construir_features(r, fset, True)
                    feats_v = construir_features(r, fset, False)
                    if feats_l is not None and feats_v is not None:
                        xg_l = max(0.10, float(feats_l @ cf_l + ic_l))
                        xg_v = max(0.10, float(feats_v @ cf_v + ic_v))
                        p1, px, p2 = probs_dc(xg_l, xg_v)
                        b_v13 = brier_3way(p1, px, p2, o["outcome"])
                        if b_v13 is not None: v13_briers_liga.append(b_v13)
                        v13_picks_liga.append(evaluar_pick(p1, px, p2, o["psch"], o["pscd"], o["psca"], o["outcome"]))
                    else:
                        v13_picks_liga.append(None)

            m_v0 = yield_metrics(v0_picks_liga)
            m_v13 = yield_metrics(v13_picks_liga)
            br_v0 = round(float(np.mean(v0_briers_liga)), 4) if v0_briers_liga else None
            br_v13 = round(float(np.mean(v13_briers_liga)), 4) if v13_briers_liga else None

            for arch, m, br in [("V0", m_v0, br_v0), ("V13", m_v13, br_v13)]:
                ci = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
                print(f"{liga:<14} {arch:<5} {len(test_rows):>5} {m['n_apost']:>7} "
                      f"{m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {br or '-':>7} {ci:>22}")

            payload["loto_results"][test_temp][liga] = {
                "n_test": len(test_rows),
                "v0": {"brier": br_v0, **m_v0},
                "v13": {"brier": br_v13, **m_v13, "best": best},
            }
            global_v0_picks.extend(v0_picks_liga); global_v0_briers.extend(v0_briers_liga)
            global_v13_picks.extend(v13_picks_liga); global_v13_briers.extend(v13_briers_liga)

        # Global esa temp
        m_v0g = yield_metrics(global_v0_picks)
        m_v13g = yield_metrics(global_v13_picks)
        br_v0g = round(float(np.mean(global_v0_briers)), 4) if global_v0_briers else None
        br_v13g = round(float(np.mean(global_v13_briers)), 4) if global_v13_briers else None
        print(f"  {'GLOBAL':<14} {'V0':<5} {sum(len([r for r in by_liga[l] if r['temp']==test_temp]) for l in BEST_VARIANT):>5} "
              f"{m_v0g['n_apost']:>7} {m_v0g['hit_pct']:>6.1f} {m_v0g['yield_pct']:>+8.1f} {br_v0g or '-':>7}")
        print(f"  {'GLOBAL':<14} {'V13':<5} {'':<5} "
              f"{m_v13g['n_apost']:>7} {m_v13g['hit_pct']:>6.1f} {m_v13g['yield_pct']:>+8.1f} {br_v13g or '-':>7}")
        payload["loto_results"][test_temp]["GLOBAL"] = {
            "v0": {"brier": br_v0g, **m_v0g},
            "v13": {"brier": br_v13g, **m_v13g},
        }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

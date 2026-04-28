"""adepor-3ip Grid Search V13 EXTENDIDO: + disciplina + ratios derivados.

Feature sets nuevos (post-extension):
  F1_off:    sots, shot_pct, corners + def_sots_c, def_shot_pct_c (5)
  F2_pos:    F1 + pos, pass_pct (7)
  F3_def:    F2 + def_tackles_c, def_blocks_c (9)
  F4_disc:   F2 + atk_yellow, atk_red, atk_fouls (10)             [NUEVO]
  F5_ratio:  ratios derivados only:
                 atk_sots_per_shot = sots / shots
                 atk_pressure = pos * shot_pct / 100
                 atk_set_piece = corners
                 atk_red_card_rate = red / fouls (proxy disciplina dura)
                 def_solidez = def_tackles_c + def_blocks_c                 (5 ratios) [NUEVO]
  F6_full:   F2 + F4 (disciplina) + F5 (ratios) (15 features)              [NUEVO]

Regularizaciones:
  OLS, NNLS, RIDGE (CV), ENET (CV lambda x alpha)

Total: 4 reg x 6 feat = 24 variantes por (liga, target). Para 8 ligas x 2 targets:
       384 calibraciones. Train 22+23, test 24.

Output: tabla comparativa + JSON con TOP variants y BEST por liga.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "v13_grid_search_extended.json"

RHO_FALLBACK = -0.09
MIN_N_LIGA = 100
LAMBDAS_RIDGE = [0.01, 0.1, 1.0, 10.0, 100.0]
N_FOLDS_CV = 5

# ===== Feature sets =====
# Cada feature: (tipo, alias, formula). tipo in {ataque, defensa, ratio_atk, ratio_def}
# alias = nombre persistente. formula = funcion(ema_atk_dict, ema_def_dict) -> float

def _ratio(num, den, default=0.0):
    if den is None or den == 0 or num is None:
        return default
    return float(num) / float(den)


def _feat_value(name, ema_atk, ema_def):
    """Computa el valor numerico de la feature segun nombre."""
    # Crudas
    if name == "atk_sots":      return ema_atk["ema_l_sots"]
    if name == "atk_shot_pct":  return ema_atk["ema_l_shot_pct"]
    if name == "atk_pos":       return ema_atk["ema_l_pos"]
    if name == "atk_pass_pct":  return ema_atk["ema_l_pass_pct"]
    if name == "atk_corners":   return ema_atk["ema_l_corners"]
    if name == "atk_yellow":    return ema_atk["ema_l_yellow"]
    if name == "atk_red":       return ema_atk["ema_l_red"]
    if name == "atk_fouls":     return ema_atk["ema_l_fouls"]
    if name == "atk_shots":     return ema_atk["ema_l_shots"]
    if name == "def_sots_c":    return ema_def["ema_c_sots"]
    if name == "def_shot_pct_c":return ema_def["ema_c_shot_pct"]
    if name == "def_tackles_c": return ema_def["ema_c_tackles"]
    if name == "def_blocks_c":  return ema_def["ema_c_blocks"]
    if name == "def_yellow_c":  return ema_def["ema_c_yellow"]
    # Ratios derivados
    if name == "atk_sots_per_shot":
        return _ratio(ema_atk["ema_l_sots"], ema_atk["ema_l_shots"], default=0.4)
    if name == "atk_pressure":  # posesion x shot_pct -> intensidad ofensiva
        return float(ema_atk["ema_l_pos"]) * float(ema_atk["ema_l_shot_pct"]) / 100.0
    if name == "atk_set_piece":
        return ema_atk["ema_l_corners"]
    if name == "atk_red_card_rate":
        return _ratio(ema_atk["ema_l_red"], ema_atk["ema_l_fouls"], default=0.0)
    if name == "def_solidez":
        return float(ema_def["ema_c_tackles"]) + float(ema_def["ema_c_blocks"])
    return None


FEATURE_SETS = {
    "F1_off": [
        "atk_sots", "atk_shot_pct", "atk_corners",
        "def_sots_c", "def_shot_pct_c",
    ],
    "F2_pos": [
        "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
        "def_sots_c", "def_shot_pct_c",
    ],
    "F3_def": [
        "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
        "def_sots_c", "def_shot_pct_c", "def_tackles_c", "def_blocks_c",
    ],
    "F4_disc": [
        "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
        "atk_yellow", "atk_red", "atk_fouls",
        "def_sots_c", "def_shot_pct_c",
    ],
    "F5_ratio": [
        "atk_sots_per_shot", "atk_pressure", "atk_set_piece",
        "atk_red_card_rate", "def_solidez",
    ],
    "F6_full": [
        "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
        "atk_yellow", "atk_red", "atk_fouls",
        "atk_sots_per_shot", "atk_pressure", "atk_red_card_rate",
        "def_sots_c", "def_shot_pct_c", "def_solidez",
    ],
}


# ===== Carga dataset (full schema con disciplina + shots) =====
def cargar_dataset(con):
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
    """
    rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if not d["ema_l_json"] or not d["ema_v_json"]:
            continue
        try:
            d["ema_l"] = json.loads(d["ema_l_json"])
            d["ema_v"] = json.loads(d["ema_v_json"])
        except Exception:
            continue
        if any(v is None for v in d["ema_l"].values()):
            continue
        if any(v is None for v in d["ema_v"].values()):
            continue
        d["oos"] = json.loads(d["oos_json"]) if d["oos_json"] else None
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
        if v is None:
            return None
        feats.append(float(v))
    return np.array(feats)


# ===== Regularizaciones (copy) =====
def _standardize(X):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def fit_ols(X, y):
    Xz, mu, sd = _standardize(X)
    y_mu, y_c = y.mean(), y - y.mean()
    try: beta_z = np.linalg.solve(Xz.T @ Xz, Xz.T @ y_c)
    except np.linalg.LinAlgError: return None, None
    coefs = beta_z / sd
    return float(y_mu - mu @ coefs), coefs


def fit_ridge(X, y, lam):
    Xz, mu, sd = _standardize(X)
    y_mu, y_c = y.mean(), y - y.mean()
    p = X.shape[1]
    try: beta_z = np.linalg.solve(Xz.T @ Xz + lam * np.eye(p), Xz.T @ y_c)
    except np.linalg.LinAlgError: return None, None
    coefs = beta_z / sd
    return float(y_mu - mu @ coefs), coefs


def fit_nnls(X, y, max_iter=2000):
    Xz, mu, sd = _standardize(X)
    y_mu, y_c = y.mean(), y - y.mean()
    n, p = Xz.shape
    b = np.zeros(p)
    L = float(np.linalg.norm(Xz, ord=2)) ** 2 / n
    step = 1.0 / max(L, 1e-6)
    for _ in range(max_iter):
        grad = Xz.T @ (Xz @ b - y_c) / n
        b_new = np.maximum(0.0, b - step * grad)
        if np.max(np.abs(b_new - b)) < 1e-7: break
        b = b_new
    coefs = b / sd
    return float(y_mu - mu @ coefs), coefs


def _soft_threshold(z, gamma):
    return np.sign(z) * np.maximum(np.abs(z) - gamma, 0.0)


def fit_elasticnet(X, y, lam, alpha, max_iter=500, tol=1e-6):
    Xz, mu, sd = _standardize(X)
    y_c = y - y.mean()
    n, p = Xz.shape
    col_norms = np.sum(Xz ** 2, axis=0)
    b = np.zeros(p); Xb = np.zeros(n)
    for _ in range(max_iter):
        b_old = b.copy()
        for j in range(p):
            if col_norms[j] == 0: continue
            r = y_c - Xb + Xz[:, j] * b[j]
            num = _soft_threshold(Xz[:, j] @ r / n, lam * alpha)
            den = col_norms[j] / n + lam * (1 - alpha)
            new_j = num / den if den > 0 else 0.0
            Xb += Xz[:, j] * (new_j - b[j])
            b[j] = new_j
        if np.max(np.abs(b - b_old)) < tol: break
    coefs = b / sd
    return float(y.mean() - mu @ coefs), coefs


def cv_ridge(X, y, lambdas, n_folds=N_FOLDS_CV, seed=42):
    n = len(X)
    if n < n_folds * 2: return lambdas[len(lambdas) // 2]
    rng = np.random.default_rng(seed); idx = np.arange(n); rng.shuffle(idx)
    folds = np.array_split(idx, n_folds)
    best_lam, best_mse = lambdas[0], np.inf
    for lam in lambdas:
        mses = []
        for k in range(n_folds):
            tr = np.concatenate([folds[j] for j in range(n_folds) if j != k])
            te = folds[k]
            ic, cf = fit_ridge(X[tr], y[tr], lam)
            if ic is None: continue
            mses.append(float(np.mean((X[te] @ cf + ic - y[te]) ** 2)))
        if mses:
            avg = float(np.mean(mses))
            if avg < best_mse: best_mse, best_lam = avg, lam
    return best_lam


def cv_elasticnet(X, y, lambdas, alphas, n_folds=N_FOLDS_CV, seed=42):
    n = len(X)
    if n < n_folds * 2: return lambdas[1], alphas[len(alphas) // 2]
    rng = np.random.default_rng(seed); idx = np.arange(n); rng.shuffle(idx)
    folds = np.array_split(idx, n_folds)
    best_lam, best_alpha, best_mse = lambdas[0], alphas[0], np.inf
    for lam in lambdas:
        for a in alphas:
            mses = []
            for k in range(n_folds):
                tr = np.concatenate([folds[j] for j in range(n_folds) if j != k])
                te = folds[k]
                ic, cf = fit_elasticnet(X[tr], y[tr], lam, a, max_iter=300)
                if ic is None: continue
                mses.append(float(np.mean((X[te] @ cf + ic - y[te]) ** 2)))
            if mses:
                avg = float(np.mean(mses))
                if avg < best_mse: best_mse, best_lam, best_alpha = avg, lam, a
    return best_lam, best_alpha


# ===== Probs DC + audit =====
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
    profit = stake * (cuota - 1) if label == outcome else -stake
    return {"stake": stake, "profit": profit, "gano": label == outcome}


def brier_3way(p1, px, p2, outcome):
    t = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(outcome)
    if t is None: return None
    return (p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2


def yield_metrics(picks):
    n = sum(1 for p in picks if p)
    g = sum(1 for p in picks if p and p["gano"])
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    pares = [(p["stake"], p["profit"]) for p in picks if p]
    yld = pl / s * 100 if s > 0 else 0
    hit = g / n * 100 if n > 0 else 0
    if pares:
        rng = np.random.default_rng(42)
        sk = np.array([x[0] for x in pares]); pr = np.array([x[1] for x in pares])
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


# ===== Sweep =====
def evaluar_variante(rows_liga, feature_set, reg, target_local=True):
    train = [r for r in rows_liga if r["temp"] in (2022, 2023)]
    test = [r for r in rows_liga if r["temp"] == 2024]
    if len(train) < MIN_N_LIGA or len(test) < 30:
        return None
    X_tr_list = [construir_features(r, feature_set, target_local) for r in train]
    if any(x is None for x in X_tr_list): return None
    X_te_list = [construir_features(r, feature_set, target_local) for r in test]
    if any(x is None for x in X_te_list): return None
    X_tr = np.array(X_tr_list); y_tr = np.array([r["hg"] if target_local else r["ag"] for r in train], float)
    X_te = np.array(X_te_list); y_te = np.array([r["hg"] if target_local else r["ag"] for r in test], float)

    if reg == "OLS":
        ic, cf = fit_ols(X_tr, y_tr); meta = {"reg": "OLS"}
    elif reg == "NNLS":
        ic, cf = fit_nnls(X_tr, y_tr); meta = {"reg": "NNLS"}
    elif reg == "RIDGE":
        lam = cv_ridge(X_tr, y_tr, LAMBDAS_RIDGE)
        ic, cf = fit_ridge(X_tr, y_tr, lam); meta = {"reg": "RIDGE", "lambda": lam}
    elif reg == "ENET":
        lam, alpha = cv_elasticnet(X_tr, y_tr, [0.001, 0.01, 0.1, 1.0], [0.1, 0.3, 0.5, 0.7, 0.9])
        ic, cf = fit_elasticnet(X_tr, y_tr, lam, alpha, max_iter=500)
        meta = {"reg": "ENET", "lambda": lam, "alpha": alpha}
    else: return None

    if ic is None or cf is None: return None
    preds = X_te @ cf + ic
    mse = float(np.mean((preds - y_te) ** 2))
    naive = float(np.mean((y_tr.mean() - y_te) ** 2))
    ss_res = float(np.sum((preds - y_te) ** 2))
    ss_tot = float(np.sum((y_te - y_te.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    return {**meta, "n_train": len(train), "n_test": len(test),
            "intercept": float(ic), "coefs": [float(c) for c in cf],
            "feature_aliases": list(feature_set),
            "mse_test": round(mse, 4), "naive_mse": round(naive, 4),
            "mse_gain": round(naive - mse, 4),
            "r2_oos": round(r2, 4) if r2 is not None else None,
            "mean_pred": round(float(preds.mean()), 3)}


def evaluar_yield_brier_oos(rows_liga, cal_l, cal_v, feature_set):
    if not cal_l or not cal_v: return None
    test = [r for r in rows_liga if r["temp"] == 2024 and r.get("oos")]
    if not test: return None
    cf_l = np.array(cal_l["coefs"]); cf_v = np.array(cal_v["coefs"])
    ic_l = cal_l["intercept"]; ic_v = cal_v["intercept"]
    briers = []; picks = []
    for r in test:
        feats_l = construir_features(r, feature_set, True)
        feats_v = construir_features(r, feature_set, False)
        if feats_l is None or feats_v is None: continue
        xg_l = max(0.10, float(feats_l @ cf_l + ic_l))
        xg_v = max(0.10, float(feats_v @ cf_v + ic_v))
        p1, px, p2 = probs_dc(xg_l, xg_v)
        b = brier_3way(p1, px, p2, r["oos"]["outcome"])
        if b is not None: briers.append(b)
        picks.append(evaluar_pick(p1, px, p2, r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"], r["oos"]["outcome"]))
    return {"brier": round(float(np.mean(briers)), 4) if briers else None,
            "n_oos": len(test), **yield_metrics(picks)}


def main():
    con = sqlite3.connect(DB)
    print("Cargando dataset extended (con disciplina + shots)...")
    rows = cargar_dataset(con)
    print(f"  N partidos full features: {len(rows):,}")
    by_liga = defaultdict(list)
    for r in rows: by_liga[r["liga"]].append(r)

    print(f"\n=== Grid Search V13 EXTENDED (4 reg x 6 feat x 8 ligas x 2 targets) ===")
    payload = {
        "fecha": datetime.now().isoformat(),
        "feature_sets": FEATURE_SETS,
        "regs": ["OLS", "NNLS", "RIDGE", "ENET"],
        "n_total": len(rows),
        "resultados": defaultdict(dict),
    }

    for liga in sorted(by_liga.keys()):
        rows_liga = by_liga[liga]
        if len(rows_liga) < MIN_N_LIGA: continue
        print(f"\n--- {liga} (N={len(rows_liga)}) ---")
        for fname, fset in FEATURE_SETS.items():
            payload["resultados"][liga][fname] = {}
            for reg in ["OLS", "NNLS", "RIDGE", "ENET"]:
                cl = evaluar_variante(rows_liga, fset, reg, True)
                cv = evaluar_variante(rows_liga, fset, reg, False)
                payload["resultados"][liga][fname][reg] = {"local": cl, "visita": cv}
                yb = evaluar_yield_brier_oos(rows_liga, cl, cv, fset)
                payload["resultados"][liga][fname][reg]["audit_oos"] = yb
                if yb and yb["yield_pct"] is not None:
                    ci = f"[{yb['ci95_lo']:>+5.1f},{yb['ci95_hi']:>+5.1f}]" if yb['ci95_lo'] is not None else "n/a"
                    r2_l = cl["r2_oos"] if cl else None
                    print(f"  {fname:<9s} {reg:<5s} N={yb['n_apost']:>3} Hit={yb['hit_pct']:>5.1f}% "
                          f"Yield={yb['yield_pct']:>+6.1f}% {ci:>22} Brier={yb['brier']} R²_l={r2_l}")

    # Resumen TOP yield
    print("\n=== TOP-15 yield OOS (N>=10) ===")
    flat = []
    for liga, sets in payload["resultados"].items():
        for fset, regs in sets.items():
            for reg, vals in regs.items():
                yb = vals.get("audit_oos")
                if yb and yb.get("yield_pct") is not None and yb.get("n_apost", 0) >= 10:
                    flat.append({
                        "liga": liga, "feat": fset, "reg": reg, **yb,
                        "r2_l": vals["local"]["r2_oos"] if vals.get("local") else None,
                    })
    flat.sort(key=lambda x: -x["yield_pct"])
    for t in flat[:15]:
        ci = f"[{t['ci95_lo']:>+5.1f},{t['ci95_hi']:>+5.1f}]"
        print(f"  {t['liga']:<14} {t['feat']:<9} {t['reg']:<5} N={t['n_apost']:>3} "
              f"Hit={t['hit_pct']:>5.1f}% Yield={t['yield_pct']:>+6.1f}% {ci} Brier={t['brier']} R²={t['r2_l']}")

    # BEST por liga (yield > 0, N >= 10, prefer NNLS > RIDGE > ENET > OLS)
    print("\n=== BEST por liga (yield>0, N>=10) ===")
    REG_PRI = {"NNLS": 0, "RIDGE": 1, "ENET": 2, "OLS": 3}
    payload["best_by_liga"] = {}
    for liga in sorted(payload["resultados"].keys()):
        cands = [f for f in flat if f["liga"] == liga and f["yield_pct"] > 0]
        if not cands:
            print(f"  {liga:<14} (sin variant con yield>0 y N>=10)")
            continue
        cands.sort(key=lambda x: (-x["yield_pct"], REG_PRI.get(x["reg"], 99)))
        b = cands[0]
        ci = f"[{b['ci95_lo']:>+5.1f},{b['ci95_hi']:>+5.1f}]"
        print(f"  {liga:<14} {b['feat']:<9} {b['reg']:<5} N={b['n_apost']:>3} "
              f"Yield={b['yield_pct']:>+6.1f}% {ci} Brier={b['brier']}")
        payload["best_by_liga"][liga] = b

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

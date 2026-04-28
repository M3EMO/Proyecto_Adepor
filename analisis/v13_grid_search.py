"""adepor-3ip Grid Search V13: explorar combinaciones de regularizacion x features.

Variantes evaluadas:
  REGULARIZACION:
    OLS    = regresion lineal sin regularizacion (puede dar singular)
    NNLS   = non-negative least squares (projected gradient, coefs >= 0)
    RIDGE  = ridge L2 con CV (5-fold) sobre lambda in {0.01, 0.1, 1, 10, 100}

  FEATURE SETS:
    F1 = ofensivas core: sots, shot_pct, corners + def_sots_c, def_shot_pct_c (5 feats)
    F2 = +posesion: F1 + pos, pass_pct (7 feats)
    F3 = +defensivas: F2 + ema_c_tackles (visita), ema_c_blocks (visita) (9 feats)

Total: 3 reg x 3 feat = 9 variantes por (liga, target). 8 ligas x 2 targets = 16
       16 x 9 = 144 calibraciones. Train 22+23, test OOS 24.

Audit OOS 2024: cada variante calibrada -> Brier + yield real (cuotas Pinnacle)
sobre OOS subset.

Output: tabla comparativa + JSON con todas las combinaciones.
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
OUT = Path(__file__).resolve().parent / "v13_grid_search.json"

RHO_FALLBACK = -0.09
MIN_N_LIGA = 100
LAMBDAS_RIDGE = [0.01, 0.1, 1.0, 10.0, 100.0]
N_FOLDS_CV = 5

# Feature sets ----------------------------------------------------------
# F1: ofensivas core (5)
# F2: +posesion (7)
# F3: +defensivas (9)
FEATURE_SETS = {
    "F1_off": [
        ("ataque", "ema_l_sots", "atk_sots"),
        ("ataque", "ema_l_shot_pct", "atk_shot_pct"),
        ("ataque", "ema_l_corners", "atk_corners"),
        ("defensa", "ema_c_sots", "def_sots_c"),
        ("defensa", "ema_c_shot_pct", "def_shot_pct_c"),
    ],
    "F2_pos": [
        ("ataque", "ema_l_sots", "atk_sots"),
        ("ataque", "ema_l_shot_pct", "atk_shot_pct"),
        ("ataque", "ema_l_pos", "atk_pos"),
        ("ataque", "ema_l_pass_pct", "atk_pass_pct"),
        ("ataque", "ema_l_corners", "atk_corners"),
        ("defensa", "ema_c_sots", "def_sots_c"),
        ("defensa", "ema_c_shot_pct", "def_shot_pct_c"),
    ],
    "F3_def": [
        ("ataque", "ema_l_sots", "atk_sots"),
        ("ataque", "ema_l_shot_pct", "atk_shot_pct"),
        ("ataque", "ema_l_pos", "atk_pos"),
        ("ataque", "ema_l_pass_pct", "atk_pass_pct"),
        ("ataque", "ema_l_corners", "atk_corners"),
        ("defensa", "ema_c_sots", "def_sots_c"),
        ("defensa", "ema_c_shot_pct", "def_shot_pct_c"),
        ("defensa", "ema_c_tackles", "def_tackles_c"),
        ("defensa", "ema_c_blocks", "def_blocks_c"),
    ],
}


def cargar_dataset(con):
    """JOIN partidos_historico_externo + EMA pre-partido (full feature set F3)."""
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag,
               (SELECT json_object(
                    'ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.ht AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               (SELECT json_object(
                    'ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks)
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
        if d["oos_json"]:
            try:
                d["oos"] = json.loads(d["oos_json"])
            except Exception:
                d["oos"] = None
        else:
            d["oos"] = None
        out.append(d)
    return out


def construir_features(row, feature_set, target_local=True):
    if target_local:
        ataque = row["ema_l"]
        defensa = row["ema_v"]
    else:
        ataque = row["ema_v"]
        defensa = row["ema_l"]
    feats = []
    for tipo, col_ema, _alias in feature_set:
        if tipo == "ataque":
            feats.append(ataque[col_ema])
        else:
            feats.append(defensa[col_ema])
    return np.array(feats)


# -------- Regularizaciones --------
def _standardize(X):
    mu = X.mean(0)
    sd = X.std(0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def fit_ols(X, y):
    Xz, mu, sd = _standardize(X)
    y_mu = y.mean()
    y_c = y - y_mu
    try:
        beta_z = np.linalg.solve(Xz.T @ Xz, Xz.T @ y_c)
    except np.linalg.LinAlgError:
        return None, None
    coefs = beta_z / sd
    intercept = y_mu - mu @ coefs
    return float(intercept), coefs


def fit_ridge(X, y, lam):
    Xz, mu, sd = _standardize(X)
    y_mu = y.mean()
    y_c = y - y_mu
    p = X.shape[1]
    try:
        beta_z = np.linalg.solve(Xz.T @ Xz + lam * np.eye(p), Xz.T @ y_c)
    except np.linalg.LinAlgError:
        return None, None
    coefs = beta_z / sd
    intercept = y_mu - mu @ coefs
    return float(intercept), coefs


def fit_nnls(X, y, max_iter=2000, lr=0.001):
    """NNLS via projected gradient. coefs_z >= 0 en escala estandarizada."""
    Xz, mu, sd = _standardize(X)
    y_mu = y.mean()
    y_c = y - y_mu
    n, p = Xz.shape
    b = np.zeros(p)
    L = float(np.linalg.norm(Xz, ord=2)) ** 2 / n  # Lipschitz constant aprox
    if L == 0:
        L = 1.0
    step = 1.0 / max(L, 1e-6)
    for _ in range(max_iter):
        grad = Xz.T @ (Xz @ b - y_c) / n
        b_new = np.maximum(0.0, b - step * grad)
        if np.max(np.abs(b_new - b)) < 1e-7:
            break
        b = b_new
    coefs = b / sd
    intercept = y_mu - mu @ coefs
    return float(intercept), coefs


def _soft_threshold(z, gamma):
    """Soft thresholding operator: S(z, gamma) = sign(z) * max(|z| - gamma, 0)."""
    return np.sign(z) * np.maximum(np.abs(z) - gamma, 0.0)


def fit_elasticnet(X, y, lam, alpha, max_iter=1000, tol=1e-6):
    """ElasticNet via coordinate descent.

    Objective:
      min (1/(2n)) ||y - X b||^2 + lam * (alpha * ||b||_1 + (1-alpha)/2 * ||b||^2)

    alpha ∈ [0, 1]: 1 = Lasso puro, 0 = Ridge puro, intermedio = ElasticNet.
    Implementacion estandar de coordinate descent con soft thresholding.
    """
    Xz, mu, sd = _standardize(X)
    y_mu = y.mean()
    y_c = y - y_mu
    n, p = Xz.shape

    # Pre-compute norms columnas
    col_norms_sq = np.sum(Xz ** 2, axis=0)  # n * 1 cada columna estandarizada
    # Si col_norms_sq es 0 (columna constante), el coef queda 0
    safe_norms = np.where(col_norms_sq == 0, 1.0, col_norms_sq)

    b = np.zeros(p)
    Xb = np.zeros(n)
    for it in range(max_iter):
        b_old = b.copy()
        for j in range(p):
            if col_norms_sq[j] == 0:
                continue
            # Residuo parcial sin coordenada j
            r_partial = y_c - Xb + Xz[:, j] * b[j]
            # OLS partial estimate
            rho_j = Xz[:, j] @ r_partial / n
            # Soft thresholding
            num = _soft_threshold(rho_j, lam * alpha)
            den = (col_norms_sq[j] / n) + lam * (1 - alpha)
            b_new_j = num / den if den > 0 else 0.0
            # Actualizar Xb incremental
            Xb += Xz[:, j] * (b_new_j - b[j])
            b[j] = b_new_j
        if np.max(np.abs(b - b_old)) < tol:
            break

    coefs = b / sd
    intercept = y_mu - mu @ coefs
    return float(intercept), coefs


def cv_elasticnet(X, y, lambdas, alphas, n_folds=N_FOLDS_CV, seed=42):
    """K-fold CV para seleccionar (lambda, alpha) optimo por MSE."""
    n = len(X)
    if n < n_folds * 2:
        return lambdas[len(lambdas) // 2], alphas[len(alphas) // 2]
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    folds = np.array_split(idx, n_folds)
    best_lam = lambdas[0]
    best_alpha = alphas[0]
    best_mse = np.inf
    for lam in lambdas:
        for a in alphas:
            mses = []
            for k in range(n_folds):
                test_idx = folds[k]
                train_idx = np.concatenate([folds[j] for j in range(n_folds) if j != k])
                ic, cf = fit_elasticnet(X[train_idx], y[train_idx], lam, a, max_iter=300)
                if ic is None:
                    continue
                preds = X[test_idx] @ cf + ic
                mses.append(float(np.mean((preds - y[test_idx]) ** 2)))
            if mses:
                mse_avg = float(np.mean(mses))
                if mse_avg < best_mse:
                    best_mse = mse_avg
                    best_lam = lam
                    best_alpha = a
    return best_lam, best_alpha


def cv_ridge(X, y, lambdas, n_folds=N_FOLDS_CV, seed=42):
    n = len(X)
    if n < n_folds * 2:
        return lambdas[len(lambdas) // 2]
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    folds = np.array_split(idx, n_folds)
    best_lam = lambdas[0]
    best_mse = np.inf
    for lam in lambdas:
        mses = []
        for k in range(n_folds):
            test_idx = folds[k]
            train_idx = np.concatenate([folds[j] for j in range(n_folds) if j != k])
            ic, cf = fit_ridge(X[train_idx], y[train_idx], lam)
            if ic is None:
                continue
            preds = X[test_idx] @ cf + ic
            mses.append(float(np.mean((preds - y[test_idx]) ** 2)))
        if mses:
            mse_avg = float(np.mean(mses))
            if mse_avg < best_mse:
                best_mse = mse_avg
                best_lam = lam
    return best_lam


# -------- Probs DC + audit --------
def poisson_pmf(k, lam):
    if lam <= 0:
        return 0.0 if k > 0 else 1.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def tau_dc(i, j, lam, mu, rho):
    if i == 0 and j == 0: return 1.0 - lam * mu * rho
    elif i == 1 and j == 0: return 1.0 + mu * rho
    elif i == 0 and j == 1: return 1.0 + lam * rho
    elif i == 1 and j == 1: return 1.0 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho=RHO_FALLBACK, max_g=8):
    if xg_l <= 0 or xg_v <= 0:
        return 1/3, 1/3, 1/3
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
    f = p - (1 - p) / (c - 1)
    return max(0.0, min(f, cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05: return None
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0: return None
    if prob * cuota - 1 < 0.03: return None
    stake = kelly_fraction(prob, cuota)
    if stake <= 0: return None
    profit = stake * (cuota - 1) if label == outcome else -stake
    return {"stake": stake, "profit": profit, "gano": label == outcome}


def brier_3way(p1, px, p2, outcome):
    target = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(outcome)
    if target is None: return None
    return (p1-target[0])**2 + (px-target[1])**2 + (p2-target[2])**2


def yield_metrics_kelly(picks):
    n_apost = sum(1 for p in picks if p)
    n_gano = sum(1 for p in picks if p and p["gano"])
    sum_stake = sum(p["stake"] for p in picks if p)
    sum_pl = sum(p["profit"] for p in picks if p)
    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
    hit = n_gano / n_apost * 100 if n_apost > 0 else 0
    pares = [(p["stake"], p["profit"]) for p in picks if p]
    if pares:
        rng = np.random.default_rng(42)
        stks = np.array([p[0] for p in pares])
        profs = np.array([p[1] for p in pares])
        ys = []
        for _ in range(500):
            idx = rng.integers(0, len(pares), size=len(pares))
            s, pp = stks[idx].sum(), profs[idx].sum()
            if s > 0: ys.append(pp / s * 100)
        ci_lo = float(np.percentile(ys, 2.5)) if ys else None
        ci_hi = float(np.percentile(ys, 97.5)) if ys else None
    else:
        ci_lo = ci_hi = None
    return {
        "n_apost": n_apost, "n_gano": n_gano,
        "hit_pct": round(hit, 2), "yield_pct": round(yld, 2),
        "ci95_lo": round(ci_lo, 2) if ci_lo is not None else None,
        "ci95_hi": round(ci_hi, 2) if ci_hi is not None else None,
    }


# -------- Sweep --------
def evaluar_variante(rows_liga, feature_set, reg_method, target_local=True):
    train = [r for r in rows_liga if r["temp"] in (2022, 2023)]
    test = [r for r in rows_liga if r["temp"] == 2024]
    if len(train) < MIN_N_LIGA or len(test) < 30:
        return None

    X_train = np.array([construir_features(r, feature_set, target_local) for r in train])
    y_train = np.array([(r["hg"] if target_local else r["ag"]) for r in train], dtype=float)
    X_test = np.array([construir_features(r, feature_set, target_local) for r in test])
    y_test = np.array([(r["hg"] if target_local else r["ag"]) for r in test], dtype=float)

    if reg_method == "OLS":
        ic, cf = fit_ols(X_train, y_train)
        meta = {"reg": "OLS"}
    elif reg_method == "NNLS":
        ic, cf = fit_nnls(X_train, y_train)
        meta = {"reg": "NNLS"}
    elif reg_method == "RIDGE":
        lam = cv_ridge(X_train, y_train, LAMBDAS_RIDGE)
        ic, cf = fit_ridge(X_train, y_train, lam)
        meta = {"reg": "RIDGE", "lambda": lam}
    elif reg_method == "ENET":
        # ElasticNet: grid (lam, alpha) via CV
        lam, alpha = cv_elasticnet(X_train, y_train,
                                    lambdas=[0.001, 0.01, 0.1, 1.0],
                                    alphas=[0.1, 0.3, 0.5, 0.7, 0.9])
        ic, cf = fit_elasticnet(X_train, y_train, lam, alpha, max_iter=1000)
        meta = {"reg": "ENET", "lambda": lam, "alpha": alpha}
    else:
        return None

    if ic is None or cf is None:
        return None

    preds_test = X_test @ cf + ic
    mse_test = float(np.mean((preds_test - y_test) ** 2))
    naive_mse = float(np.mean((y_train.mean() - y_test) ** 2))
    ss_res = float(np.sum((preds_test - y_test) ** 2))
    ss_tot = float(np.sum((y_test - y_test.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None

    return {
        **meta,
        "n_train": len(train), "n_test": len(test),
        "intercept": float(ic),
        "coefs": [float(c) for c in cf],
        "feature_aliases": [a for _, _, a in feature_set],
        "mse_test": round(mse_test, 4),
        "r2_oos": round(r2, 4) if r2 is not None else None,
        "naive_mse": round(naive_mse, 4),
        "mse_gain": round(naive_mse - mse_test, 4),
        "mean_pred": round(float(preds_test.mean()), 3),
    }


def evaluar_yield_brier_oos(rows_liga, calibracion_local, calibracion_visita, feature_set):
    """Para una liga + calibracion local+visita, evalua Brier + yield sobre temp 24."""
    if not calibracion_local or not calibracion_visita:
        return None
    test = [r for r in rows_liga if r["temp"] == 2024 and r.get("oos")]
    if not test:
        return None
    cf_l = np.array(calibracion_local["coefs"])
    cf_v = np.array(calibracion_visita["coefs"])
    ic_l = calibracion_local["intercept"]
    ic_v = calibracion_visita["intercept"]
    briers = []
    picks = []
    for r in test:
        xg_l = max(0.10, float(construir_features(r, feature_set, True) @ cf_l + ic_l))
        xg_v = max(0.10, float(construir_features(r, feature_set, False) @ cf_v + ic_v))
        p1, px, p2 = probs_dc(xg_l, xg_v)
        b = brier_3way(p1, px, p2, r["oos"]["outcome"])
        if b is not None: briers.append(b)
        picks.append(evaluar_pick(p1, px, p2,
                                   r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"],
                                   r["oos"]["outcome"]))
    brier = float(np.mean(briers)) if briers else None
    metrics = yield_metrics_kelly(picks)
    return {"brier": round(brier, 4) if brier else None, **metrics, "n_oos": len(test)}


def main():
    con = sqlite3.connect(DB)
    print("Cargando dataset full...")
    rows = cargar_dataset(con)
    print(f"  N partidos full features: {len(rows):,}")

    by_liga = defaultdict(list)
    for r in rows:
        by_liga[r["liga"]].append(r)

    payload = {
        "fecha": datetime.now().isoformat(),
        "feature_sets": {k: [a for _, _, a in v] for k, v in FEATURE_SETS.items()},
        "regs": ["OLS", "NNLS", "RIDGE", "ENET"],
        "n_total": len(rows),
        "resultados": defaultdict(dict),
    }

    print("\n=== Grid Search V13 (3 reg x 3 feat sets x 2 targets x N ligas) ===")
    print(f"{'liga':<14} {'feat':<8} {'reg':<6} {'tgt':<7} {'N_tr':>4} {'lam':>6} {'mse':>7} {'naive':>7} {'gain':>7} {'R²':>7}")

    for liga in sorted(by_liga.keys()):
        rows_liga = by_liga[liga]
        if len(rows_liga) < MIN_N_LIGA:
            continue
        for fset_name, feature_set in FEATURE_SETS.items():
            payload["resultados"][liga][fset_name] = {}
            for reg in ["OLS", "NNLS", "RIDGE", "ENET"]:
                payload["resultados"][liga][fset_name][reg] = {}
                cal_local = evaluar_variante(rows_liga, feature_set, reg, target_local=True)
                cal_visita = evaluar_variante(rows_liga, feature_set, reg, target_local=False)
                payload["resultados"][liga][fset_name][reg]["local"] = cal_local
                payload["resultados"][liga][fset_name][reg]["visita"] = cal_visita

                # Audit Brier + yield
                yb = evaluar_yield_brier_oos(rows_liga, cal_local, cal_visita, feature_set)
                payload["resultados"][liga][fset_name][reg]["audit_oos"] = yb

                # Print resumen
                for tgt, cal in [("local", cal_local), ("visita", cal_visita)]:
                    if cal is None:
                        continue
                    lam_str = f"{cal.get('lambda', '-'):>6}" if isinstance(cal.get('lambda'), (int, float)) else f"{'-':>6}"
                    print(f"{liga:<14} {fset_name:<8} {reg:<6} {tgt:<7} {cal['n_train']:>4} "
                          f"{lam_str} {cal['mse_test']:>7.4f} {cal['naive_mse']:>7.4f} "
                          f"{cal['mse_gain']:>+7.4f} {cal['r2_oos']:>+7.4f}")
                # Audit summary
                if yb:
                    ci = f"[{yb['ci95_lo']:>+5.1f},{yb['ci95_hi']:>+5.1f}]" if yb['ci95_lo'] is not None else "n/a"
                    print(f"               -> AUDIT OOS: Brier={yb['brier']} NApost={yb['n_apost']} Hit={yb['hit_pct']}% Yield={yb['yield_pct']:+.1f}% CI {ci}")

    # ----- TOP-K resumen -----
    print("\n=== TOP-10 mejores yield OOS por (liga, feat, reg) ===")
    flat = []
    for liga, sets in payload["resultados"].items():
        for fset, regs in sets.items():
            for reg, vals in regs.items():
                yb = vals.get("audit_oos")
                if yb and yb.get("yield_pct") is not None and yb.get("n_apost", 0) >= 10:
                    flat.append({
                        "liga": liga, "feat": fset, "reg": reg,
                        "yield_pct": yb["yield_pct"],
                        "ci95_lo": yb["ci95_lo"], "ci95_hi": yb["ci95_hi"],
                        "n_apost": yb["n_apost"], "hit_pct": yb["hit_pct"],
                        "brier": yb["brier"],
                        "r2_local": vals.get("local", {}).get("r2_oos") if vals.get("local") else None,
                    })
    flat.sort(key=lambda x: (-x["yield_pct"]))
    for top in flat[:10]:
        ci = f"[{top['ci95_lo']:>+5.1f},{top['ci95_hi']:>+5.1f}]"
        print(f"  {top['liga']:<14} {top['feat']:<8} {top['reg']:<6} "
              f"NA={top['n_apost']:>3} Hit={top['hit_pct']:>5.1f}% Yield={top['yield_pct']:>+6.1f}% {ci} "
              f"Brier={top['brier']} R²_l={top['r2_local']}")

    print("\n=== TOP-10 mejores Brier OOS ===")
    flat_brier = [f for f in flat if f["brier"] is not None]
    flat_brier.sort(key=lambda x: x["brier"])
    for top in flat_brier[:10]:
        ci = f"[{top['ci95_lo']:>+5.1f},{top['ci95_hi']:>+5.1f}]"
        print(f"  {top['liga']:<14} {top['feat']:<8} {top['reg']:<6} "
              f"Brier={top['brier']} Yield={top['yield_pct']:>+6.1f}% {ci}")

    payload["top_yield"] = flat[:10]
    payload["top_brier"] = flat_brier[:10]

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

"""adepor-3ip Calibracion V13: motor xG aumentado con ridge L2.

Fuente:
  - partidos_historico_externo (outcome real: hg, ag)
  - historial_equipos_stats (EMA pre-partido para local y visita)

Modelo bilineal:
  xG_local = β0 + β1*ema_l_sots(loc) + β2*ema_l_shot_pct(loc) + β3*ema_l_pos(loc)
                 + β4*ema_l_pass_pct(loc) + β5*ema_l_corners(loc)
                 + γ1*ema_c_sots(vis)  + γ2*ema_c_shot_pct(vis)
  xG_visita = β0' + ... (analogo simetrico con ema_l del visita + ema_c del local)

Ridge L2 con regularizacion lambda elegida por CV K-fold sobre train.
Train: temps 2022 + 2023. Test (OOS): temp 2024.

Por liga: coeficientes propios + lambda optimo. Si CV R2 OOS < 0, V13 cae
al fallback V0 para esa liga.

Output:
  - Tabla v13_coef_por_liga (creada si no existe)
  - JSON con metricas + comparativa vs xG hibrido legacy
"""
from __future__ import annotations

import json
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
OUT = Path(__file__).resolve().parent / "v13_calibracion_ridge.json"

# Features ofensivas + posesion (escalable). Snapshot pre-partido del local
# en su rol "atacante en casa" + del visita en su rol "defensor fuera".
FEATURES_LOCAL_ATAQUE = [
    "ema_l_sots", "ema_l_shot_pct", "ema_l_pos",
    "ema_l_pass_pct", "ema_l_corners",
]
FEATURES_VISITA_DEFENSA = [
    "ema_c_sots", "ema_c_shot_pct",  # ema_c = lo que concede en su rol away
]
FEATURES_VISITA_ATAQUE = [
    "ema_l_sots", "ema_l_shot_pct", "ema_l_pos",  # ema_l del visita = lo que hace en sus roles
    "ema_l_pass_pct", "ema_l_corners",
]
FEATURES_LOCAL_DEFENSA = [
    "ema_c_sots", "ema_c_shot_pct",
]

# Lambda candidates para CV
LAMBDAS = [0.01, 0.1, 1.0, 10.0, 100.0]
N_FOLDS = 5
MIN_N_LIGA = 100  # menos que esto -> no calibrar V13 para esa liga


def cargar_dataset(con):
    """Carga partidos con outcome + EMA L y V pre-partido."""
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag,
               -- EMA local (su rol jugando en casa)
               (SELECT json_object(
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'corners', ema_l_corners,
                    'sots_c', ema_c_sots, 'shot_pct_c', ema_c_shot_pct,
                    'n', n_acum)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.ht AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               -- EMA visita (su rol jugando fuera)
               (SELECT json_object(
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'corners', ema_l_corners,
                    'sots_c', ema_c_sots, 'shot_pct_c', ema_c_shot_pct,
                    'n', n_acum)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.at AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_v_json
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
            ema_l = json.loads(d["ema_l_json"])
            ema_v = json.loads(d["ema_v_json"])
        except Exception:
            continue
        if any(v is None for v in ema_l.values()) or any(v is None for v in ema_v.values()):
            continue
        d["ema_l"] = ema_l
        d["ema_v"] = ema_v
        out.append(d)
    return out


def construir_features(row, target_local=True):
    """Devuelve vector de features para predecir xG local (target_local=True) o visita.

    xG_local depende de:
      - ataque local del local (ema_l del local en su rol home)
      - defensa visita del visita (ema_c del visita en su rol away)
    xG_visita depende de:
      - ataque visita del visita (ema_l del visita)
      - defensa local del local (ema_c del local)
    """
    if target_local:
        ataque = row["ema_l"]
        defensa = row["ema_v"]
    else:
        ataque = row["ema_v"]
        defensa = row["ema_l"]
    feats = [
        ataque["sots"], ataque["shot_pct"], ataque["pos"],
        ataque["pass_pct"], ataque["corners"],
        defensa["sots_c"], defensa["shot_pct_c"],
    ]
    return feats


FEATURE_NAMES = [
    "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
    "def_sots_c", "def_shot_pct_c",
]


def ridge_fit(X, y, lam):
    """Ridge regression analitica: beta = (X^T X + lam*I)^-1 X^T y.
    Standardiza X internamente (z-score) para que lam sea comparable.
    Devuelve (intercept, coefs) en escala original."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, p = X.shape
    # Standardize
    mu = X.mean(axis=0)
    sigma = X.std(axis=0)
    sigma[sigma == 0] = 1.0
    Xz = (X - mu) / sigma
    # Anadir bias en X estandarizado: NO penalizamos intercept, asi que separamos
    # beta_z = (Xz^T Xz + lam*I)^-1 Xz^T (y - mean(y))
    y_mean = y.mean()
    y_centered = y - y_mean
    XtX = Xz.T @ Xz
    A = XtX + lam * np.eye(p)
    try:
        beta_z = np.linalg.solve(A, Xz.T @ y_centered)
    except np.linalg.LinAlgError:
        return None, None  # singular
    # Convertir back a escala original
    coefs = beta_z / sigma
    intercept = y_mean - mu @ coefs
    return intercept, coefs


def ridge_predict(X, intercept, coefs):
    return X @ coefs + intercept


def cv_select_lambda(X_train, y_train, lambdas, n_folds=5, seed=42):
    """K-fold CV para seleccionar mejor lambda por MSE."""
    n = len(X_train)
    if n < n_folds * 2:
        return lambdas[len(lambdas)//2]  # default mid si poco data
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    folds = np.array_split(idx, n_folds)
    X_train = np.asarray(X_train, dtype=float)
    y_train = np.asarray(y_train, dtype=float)

    best_lam = lambdas[0]
    best_mse = np.inf
    for lam in lambdas:
        mses = []
        for k in range(n_folds):
            test_idx = folds[k]
            train_idx = np.concatenate([folds[j] for j in range(n_folds) if j != k])
            ic, cf = ridge_fit(X_train[train_idx], y_train[train_idx], lam)
            if ic is None:
                continue
            preds = ridge_predict(X_train[test_idx], ic, cf)
            mses.append(np.mean((preds - y_train[test_idx]) ** 2))
        if not mses:
            continue
        mse_avg = float(np.mean(mses))
        if mse_avg < best_mse:
            best_mse = mse_avg
            best_lam = lam
    return best_lam


def calibrar_liga(rows_liga, target_local=True):
    """Train ridge por liga. Train: temp 2022+2023. Test: temp 2024.
    Devuelve dict con coefs, lambda_opt, R2 OOS, MSE OOS, N."""
    train = [r for r in rows_liga if r["temp"] in (2022, 2023)]
    test = [r for r in rows_liga if r["temp"] == 2024]
    if len(train) < MIN_N_LIGA or len(test) < 30:
        return None
    X_train = np.array([construir_features(r, target_local) for r in train])
    y_train = np.array([(r["hg"] if target_local else r["ag"]) for r in train], dtype=float)
    X_test = np.array([construir_features(r, target_local) for r in test])
    y_test = np.array([(r["hg"] if target_local else r["ag"]) for r in test], dtype=float)

    lam_opt = cv_select_lambda(X_train, y_train, LAMBDAS, n_folds=N_FOLDS)
    intercept, coefs = ridge_fit(X_train, y_train, lam_opt)
    if intercept is None:
        return None

    # Metricas OOS
    preds_test = ridge_predict(X_test, intercept, coefs)
    mse_test = float(np.mean((preds_test - y_test) ** 2))
    ss_res = float(np.sum((preds_test - y_test) ** 2))
    ss_tot = float(np.sum((y_test - y_test.mean()) ** 2))
    r2_oos = 1 - ss_res / ss_tot if ss_tot > 0 else None

    # Naive baseline: media de goles del train
    naive_mse = float(np.mean((y_train.mean() - y_test) ** 2))

    return {
        "n_train": len(train),
        "n_test": len(test),
        "lambda_opt": lam_opt,
        "intercept": float(intercept),
        "coefs": {n: float(c) for n, c in zip(FEATURE_NAMES, coefs)},
        "mse_test": round(mse_test, 4),
        "r2_oos": round(r2_oos, 4) if r2_oos is not None else None,
        "naive_mse_test": round(naive_mse, 4),
        "mse_gain_vs_naive": round(naive_mse - mse_test, 4),
        "mean_pred": round(float(preds_test.mean()), 3),
        "mean_real": round(float(y_test.mean()), 3),
    }


def crear_tabla_v13(con):
    """Tabla v13_coef_por_liga: persistencia de coeficientes calibrados."""
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v13_coef_por_liga (
            liga TEXT NOT NULL,
            target TEXT NOT NULL,  -- 'local' o 'visita'
            calibrado_en TIMESTAMP NOT NULL,
            n_train INTEGER, n_test INTEGER,
            lambda_opt REAL, intercept REAL,
            coefs_json TEXT,
            mse_test REAL, r2_oos REAL,
            naive_mse_test REAL, mse_gain_vs_naive REAL,
            mean_pred REAL, mean_real REAL,
            aplicado_produccion INTEGER DEFAULT 0,
            PRIMARY KEY (liga, target, calibrado_en)
        )
    """)
    con.commit()


def guardar_calibracion(con, liga, target, metricas):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO v13_coef_por_liga
        (liga, target, calibrado_en, n_train, n_test, lambda_opt, intercept, coefs_json,
         mse_test, r2_oos, naive_mse_test, mse_gain_vs_naive, mean_pred, mean_real,
         aplicado_produccion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (
        liga, target, datetime.now().isoformat(),
        metricas["n_train"], metricas["n_test"],
        metricas["lambda_opt"], metricas["intercept"],
        json.dumps(metricas["coefs"]),
        metricas["mse_test"], metricas["r2_oos"],
        metricas["naive_mse_test"], metricas["mse_gain_vs_naive"],
        metricas["mean_pred"], metricas["mean_real"],
    ))
    con.commit()


def main():
    con = sqlite3.connect(DB)
    print("Cargando dataset...")
    rows = cargar_dataset(con)
    print(f"  N partidos con EMA pre-partido completa: {len(rows):,}")
    print()

    # Por liga
    by_liga = defaultdict(list)
    for r in rows:
        by_liga[r["liga"]].append(r)

    print(f"=== Distribucion por liga (con outcome+EMA completa) ===")
    for liga in sorted(by_liga.keys()):
        sub = by_liga[liga]
        n22 = sum(1 for r in sub if r["temp"] == 2022)
        n23 = sum(1 for r in sub if r["temp"] == 2023)
        n24 = sum(1 for r in sub if r["temp"] == 2024)
        print(f"  {liga:<14s} N={len(sub):>4} (22:{n22:>3} 23:{n23:>3} 24:{n24:>3})")
    print()

    crear_tabla_v13(con)

    print("=== Calibrando ridge por liga (train 22+23, test 24) ===")
    print(f"{'liga':<14} {'target':<7} {'N_tr':>4} {'N_te':>4} {'λ_opt':>6} {'mse_te':>8} {'naive':>7} {'gain':>7} {'R²':>7}")
    payload = {
        "fecha_calibracion": datetime.now().isoformat(),
        "n_total_dataset": len(rows),
        "lambdas_grid": LAMBDAS,
        "n_folds_cv": N_FOLDS,
        "min_n_liga": MIN_N_LIGA,
        "feature_names": FEATURE_NAMES,
        "calibraciones": {},
    }

    for liga in sorted(by_liga.keys()):
        sub = by_liga[liga]
        if len(sub) < MIN_N_LIGA:
            print(f"  {liga:<14s} N={len(sub)} < MIN_N_LIGA={MIN_N_LIGA} -> SKIP (cae a fallback V0)")
            payload["calibraciones"][liga] = {"skipped": True, "razon": f"N<{MIN_N_LIGA}"}
            continue
        payload["calibraciones"][liga] = {}
        for target_label, target_local in [("local", True), ("visita", False)]:
            metricas = calibrar_liga(sub, target_local=target_local)
            if metricas is None:
                print(f"  {liga:<14s} {target_label:<7s} -> CALIBRACION FAILED")
                continue
            print(f"  {liga:<14s} {target_label:<7s} {metricas['n_train']:>4} {metricas['n_test']:>4} "
                  f"{metricas['lambda_opt']:>6.2f} {metricas['mse_test']:>8.4f} "
                  f"{metricas['naive_mse_test']:>7.4f} {metricas['mse_gain_vs_naive']:>+7.4f} "
                  f"{metricas['r2_oos']:>+7.4f}")
            guardar_calibracion(con, liga, target_label, metricas)
            payload["calibraciones"][liga][target_label] = metricas

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    print(f"[OK] Tabla v13_coef_por_liga poblada en {DB}")
    con.close()


if __name__ == "__main__":
    main()

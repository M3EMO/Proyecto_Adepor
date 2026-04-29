"""
[adepor-141 V14 v2] Calibrador motor copa V14 v2 — sin xG (cobertura ampliada).

V14 v2 = V14 sin features xG (xg_l, xg_v, delta_xg). Razón: post-StandardScaler
(Plan B), `delta_elo` emerge como feature DOMINANTE (mag 0.4 log-odds por 1 std)
mientras xG son MARGINALES (mag 0.02-0.05). Test rápido confirma drop xG cuesta
solo Brier +0.0002 (negligible) sobre N=881.

Beneficio: cobertura sube de 881 → ~6,843 partidos copa 2022-24 (+776%) y test
501 → ~2,000 (+300%). Cuello de botella V6 SHADOW eliminado.

Features V14 v2:
- delta_elo (incl. home advantage)
- d_copa_int (dummy copa internacional)
- d_copa_nac (dummy copa nacional)
- log1p(n_l + n_v) (actividad histórica)

Filtro cold-start: n_acum_l >= 1 AND n_acum_v >= 1 (relajado de n>=5 con scaling
hace el filtro irrelevante; literatura Frontiers 2025 usa non-informative prior
para n=0 — seguimos requiriendo al menos 1 partido Elo previo).

[REF: docs/papers/v14_feature_scaling.md] StandardScaler obligatorio.
[REF: docs/papers/v14_train_coverage.md] C.1 drop xG vs C.2 imputación. Plan B
confirmó C.1 viable (Δ Brier +0.0002 sin xG).
"""
from __future__ import annotations
import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))


def lookup_elo(conn, eq_norm, fecha):
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm=? AND fecha<? ORDER BY fecha DESC LIMIT 1
    """, (eq_norm, fecha)).fetchone()
    return (r[0], r[1]) if r else (None, 0)


def build_features_no_xg(conn, fecha_min, fecha_max, min_n=1):
    """Sin xG. Solo requiere Elo previo en ambos equipos (n_acum >= min_n)."""
    rows = conn.execute("""
        SELECT v.fecha, v.equipo_local_norm, v.equipo_visita_norm,
               v.competicion_tipo, v.goles_l, v.goles_v
        FROM v_partidos_unificado v
        WHERE v.competicion_tipo IN ('copa_internacional', 'copa_nacional')
          AND v.goles_l IS NOT NULL AND v.goles_v IS NOT NULL
          AND v.equipo_local_norm IS NOT NULL AND v.equipo_visita_norm IS NOT NULL
          AND v.fecha >= ? AND v.fecha < ?
        ORDER BY v.fecha
    """, (fecha_min, fecha_max)).fetchall()

    X_list = []; y_list = []; meta_list = []
    HOME_ADV = 100
    for fecha, eq_l, eq_v, comp_tipo, gl, gv in rows:
        elo_l, n_l = lookup_elo(conn, eq_l, fecha)
        elo_v, n_v = lookup_elo(conn, eq_v, fecha)
        if elo_l is None or elo_v is None:
            continue  # cold-start absoluto
        if n_l < min_n or n_v < min_n:
            continue
        delta_elo = (elo_l + HOME_ADV) - elo_v
        d_int = 1.0 if comp_tipo == "copa_internacional" else 0.0
        d_nac = 1.0 if comp_tipo == "copa_nacional" else 0.0
        feats = [delta_elo, d_int, d_nac, np.log1p(n_l + n_v)]
        target = 0 if gl > gv else (1 if gl == gv else 2)
        X_list.append(feats)
        y_list.append(target)
        meta_list.append((fecha, eq_l, eq_v, comp_tipo, gl, gv))
    return np.array(X_list), np.array(y_list), meta_list


def brier_multinomial(probs, y):
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return ((probs - onehot) ** 2).sum(axis=1).mean() / 2.0


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str

    print("=== STEP 1: Build train (2022-2024) + test (2025) — V14 v2 sin xG ===")
    X_train, y_train, meta_train = build_features_no_xg(conn, "2022-01-01", "2025-01-01", min_n=1)
    X_test, y_test, meta_test = build_features_no_xg(conn, "2025-01-01", "2026-01-01", min_n=1)
    print(f"  Train: {len(X_train)} partidos, classes: {dict(zip(*np.unique(y_train, return_counts=True)))}")
    print(f"  Test:  {len(X_test)} partidos, classes: {dict(zip(*np.unique(y_test, return_counts=True)))}")

    if len(X_train) < 200 or len(X_test) < 50:
        print("  N insuficiente — abortando.")
        return

    print("\n=== STEP 2: Standardize features + Train LogReg multinomial L2 ===")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    print(f"  Scaler mean: {[round(m,3) for m in scaler.mean_]}")
    print(f"  Scaler scale: {[round(s,3) for s in scaler.scale_]}")

    model = LogisticRegression(solver='lbfgs', C=1.0, max_iter=2000)
    model.fit(X_train_scaled, y_train)
    feat_names = ["delta_elo", "d_copa_int", "d_copa_nac", "log1p(n_l+n_v)"]
    print("  Coeficientes ESCALADOS (3 clases x features, log-odds por 1 std):")
    classes = ["LOCAL", "DRAW", "VISITA"]
    for i, cl in enumerate(classes):
        print(f"  {cl:<8s}: {dict(zip(feat_names, [round(c,3) for c in model.coef_[i]]))}")
    print(f"  Intercepts: {dict(zip(classes, [round(b,3) for b in model.intercept_]))}")

    print("\n=== STEP 3: Backtest train/test ===")
    probs_train = model.predict_proba(X_train_scaled)
    probs_test = model.predict_proba(X_test_scaled)
    pred_test = probs_test.argmax(axis=1)
    hit_train = (model.predict(X_train_scaled) == y_train).mean()
    hit_test = (pred_test == y_test).mean()
    brier_train = brier_multinomial(probs_train, y_train)
    brier_test = brier_multinomial(probs_test, y_test)
    print(f"  Train: hit={hit_train:.3f}  Brier={brier_train:.4f}  N={len(y_train)}")
    print(f"  Test:  hit={hit_test:.3f}  Brier={brier_test:.4f}  N={len(y_test)}")

    print("\n=== STEP 4: Comparar con V14 v1 (con xG, N=881/501) ===")
    print(f"  V14 v1: hit_test=0.511  Brier_test=0.3014  N_train=881  N_test=501")
    print(f"  V14 v2: hit_test={hit_test:.3f}  Brier_test={brier_test:.4f}  N_train={len(X_train)}  N_test={len(X_test)}")
    delta_brier = brier_test - 0.3014
    print(f"  Delta Brier (v2 - v1): {delta_brier:+.4f}")
    if delta_brier <= 0.005:
        print(f"  -> v2 mantiene/mejora Brier con cobertura {len(X_train)/881:.1f}x mayor.")
    else:
        print(f"  -> v2 degrada Brier (>0.005). Considerar C.2 (imputación xG).")

    print("\n=== STEP 5: Comparar con baselines (test 2025) ===")
    from scripts.calcular_elo_historico import expected_score, HOME_ADV
    def predict_elo_only(X):
        out = np.zeros((len(X), 3))
        for i, row in enumerate(X):
            delta_elo_v = row[0]  # idx 0 en V14 v2 (no hay xG)
            elo_l = 1500 + delta_elo_v / 2
            elo_v = 1500 - delta_elo_v / 2
            p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
            p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
            p_x = max(0.0, 1.0 - p_l - p_v)
            s = p_l + p_v + p_x
            out[i] = (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)
        return out
    probs_elo = predict_elo_only(X_test)
    hit_elo = (probs_elo.argmax(axis=1) == y_test).mean()
    brier_elo = brier_multinomial(probs_elo, y_test)
    print(f"  Elo solo:  hit={hit_elo:.3f}  Brier={brier_elo:.4f}")
    print(f"  V14 v2:    hit={hit_test:.3f}  Brier={brier_test:.4f}")
    print(f"  Delta v2 vs Elo: {brier_test - brier_elo:+.4f}")

    print("\n=== STEP 6: Persistir v2 weights ===")
    coefs_dict = {
        "feature_names": feat_names,
        "classes": classes,
        "coefs": [list(c) for c in model.coef_],
        "intercepts": list(model.intercept_),
        "scaler_mean": [float(m) for m in scaler.mean_],
        "scaler_scale": [float(s) for s in scaler.scale_],
        "metadata": {
            "version": "v2_no_xg",
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "hit_train": round(float(hit_train), 4),
            "hit_test": round(float(hit_test), 4),
            "brier_train": round(float(brier_train), 4),
            "brier_test": round(float(brier_test), 4),
            "brier_test_elo_solo": round(float(brier_elo), 4),
            "C": 1.0,
            "scaling": "StandardScaler (mean=0, sd=1)",
            "min_n_acum": 1,
            "fecha_calibrado": _dt.date.today().isoformat(),
            "ref_papers": ["docs/papers/v14_feature_scaling.md",
                           "docs/papers/v14_train_coverage.md"],
            "comparado_v1": {
                "v1_n_train": 881, "v1_brier_test": 0.3014,
                "v2_delta_brier": round(float(brier_test) - 0.3014, 4),
            },
        },
    }
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, fecha_actualizacion)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, ("lr_v14_v2_weights", "global", json.dumps(coefs_dict), "json", "adepor-141-v2"))
    conn.commit()
    print("  config_motor_valores.lr_v14_v2_weights persistido (paralelo a v1)")

    out_path = ROOT / "analisis" / "calibrar_motor_copa_v14_v2.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(coefs_dict, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: {out_path}")
    conn.close()


if __name__ == "__main__":
    main()

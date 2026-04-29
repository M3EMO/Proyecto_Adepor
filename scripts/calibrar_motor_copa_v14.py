"""
[adepor-141] Calibrador motor copa V14 — Logistic Regression multinomial 1X2
con features Elo + xG + competicion_formato.

Train: partidos copa liquidados 2022-2024 (in v_partidos_unificado con
       competicion_tipo IN ('copa_internacional','copa_nacional')).
Test:  copa partidos 2025.

[REF: docs/papers/motor_copa_v14_proposal.md]
[REF: docs/papers/elo_calibracion.md Q1+Q2 — fundamentación Elo dynamic]
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))

from src.nucleo.motor_calculadora import _get_xg_v6_para_partido  # noqa


def lookup_elo(conn, eq_norm, fecha):
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm=? AND fecha<? ORDER BY fecha DESC LIMIT 1
    """, (eq_norm, fecha)).fetchone()
    return (r[0], r[1]) if r else (1500.0, 0)


def build_features(conn, fecha_min, fecha_max):
    """Construye matriz de features X + vector de targets y."""
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
        # xG via V6 SHADOW
        xg_l, xg_v = _get_xg_v6_para_partido(eq_l, eq_v, conn)
        if xg_l is None or xg_v is None:
            continue
        # Elo pre
        elo_l, n_l = lookup_elo(conn, eq_l, fecha)
        elo_v, n_v = lookup_elo(conn, eq_v, fecha)
        if n_l < 5 or n_v < 5:
            continue  # cold-start
        # Features
        delta_elo = (elo_l + HOME_ADV) - elo_v
        delta_xg = xg_l - xg_v
        # Dummies competicion_tipo
        d_int = 1.0 if comp_tipo == "copa_internacional" else 0.0
        d_nac = 1.0 if comp_tipo == "copa_nacional" else 0.0

        feats = [xg_l, xg_v, delta_xg, delta_elo, d_int, d_nac, np.log1p(n_l + n_v)]
        target = 0 if gl > gv else (1 if gl == gv else 2)  # 0=local, 1=draw, 2=visita
        X_list.append(feats)
        y_list.append(target)
        meta_list.append((fecha, eq_l, eq_v, comp_tipo, gl, gv))
    return np.array(X_list), np.array(y_list), meta_list


def brier_multinomial(probs, y):
    """Brier 1X2 multinomial. probs (N,3), y (N,) en {0,1,2}."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return ((probs - onehot) ** 2).sum(axis=1).mean() / 2.0  # divide by 2 = sum/3


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str

    print("=== STEP 1: Build train (2022-2024) + test (2025) ===")
    X_train, y_train, meta_train = build_features(conn, "2022-01-01", "2025-01-01")
    X_test, y_test, meta_test = build_features(conn, "2025-01-01", "2026-01-01")
    print(f"  Train: {len(X_train)} partidos ({y_train.shape}, classes: {dict(zip(*np.unique(y_train, return_counts=True)))})")
    print(f"  Test:  {len(X_test)} partidos ({y_test.shape}, classes: {dict(zip(*np.unique(y_test, return_counts=True)))})")

    if len(X_train) < 200 or len(X_test) < 50:
        print("  N insuficiente — abortando.")
        return

    print("\n=== STEP 2: Train LogisticRegression multinomial L2 ===")
    # sklearn>=1.5 detecta multinomial automáticamente para targets >2 clases
    model = LogisticRegression(solver='lbfgs', C=1.0, max_iter=2000)
    model.fit(X_train, y_train)
    feat_names = ["xg_l", "xg_v", "delta_xg", "delta_elo", "d_copa_int", "d_copa_nac", "log1p(n_l+n_v)"]
    print("  Coeficientes (3 clases × features):")
    classes = ["LOCAL", "DRAW", "VISITA"]
    for i, cl in enumerate(classes):
        print(f"  {cl:<8s}: {dict(zip(feat_names, [round(c,3) for c in model.coef_[i]]))}")
    print(f"  Intercepts: {dict(zip(classes, [round(b,3) for b in model.intercept_]))}")

    print("\n=== STEP 3: Backtest train/test ===")
    probs_train = model.predict_proba(X_train)
    probs_test = model.predict_proba(X_test)
    pred_test = probs_test.argmax(axis=1)
    hit_train = (model.predict(X_train) == y_train).mean()
    hit_test = (pred_test == y_test).mean()
    brier_train = brier_multinomial(probs_train, y_train)
    brier_test = brier_multinomial(probs_test, y_test)
    print(f"  Train: hit={hit_train:.3f}  Brier={brier_train:.4f}  N={len(y_train)}")
    print(f"  Test:  hit={hit_test:.3f}  Brier={brier_test:.4f}  N={len(y_test)}")

    print("\n=== STEP 4: Comparar con baselines ===")
    # Baseline 1: Elo standalone (delta_elo + sigmoid 1X2)
    from scripts.calcular_elo_historico import expected_score, HOME_ADV
    def predict_elo_only(X):
        out = np.zeros((len(X), 3))
        for i, row in enumerate(X):
            elo_l = 1500 + row[3]/2  # delta_elo proxy
            elo_v = 1500 - row[3]/2
            p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
            p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
            p_x = max(0.0, 1.0 - p_l - p_v)
            s = p_l + p_v + p_x
            out[i] = (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)
        return out
    probs_elo = predict_elo_only(X_test)
    hit_elo = (probs_elo.argmax(axis=1) == y_test).mean()
    brier_elo = brier_multinomial(probs_elo, y_test)
    print(f"  Elo solo (test): hit={hit_elo:.3f}  Brier={brier_elo:.4f}")

    # Baseline 2: V0 (xG simple via Poisson 1X2 — aprox)
    # Aproximación rápida: P(local) = expected_score basado en xG ratio
    def predict_xg_only(X):
        out = np.zeros((len(X), 3))
        for i, row in enumerate(X):
            xg_l, xg_v = row[0], row[1]
            # Heurística sin Poisson DC completo: usar diff xG como rating
            r_l = 1500 + (xg_l - xg_v) * 200
            r_v = 1500 - (xg_l - xg_v) * 200
            p_l = expected_score(r_l, r_v, home_adv=HOME_ADV)
            p_v = expected_score(r_v, r_l, home_adv=-HOME_ADV)
            p_x = max(0.0, 1.0 - p_l - p_v)
            s = p_l + p_v + p_x
            out[i] = (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)
        return out
    probs_xg = predict_xg_only(X_test)
    hit_xg = (probs_xg.argmax(axis=1) == y_test).mean()
    brier_xg = brier_multinomial(probs_xg, y_test)
    print(f"  xG solo (test): hit={hit_xg:.3f}  Brier={brier_xg:.4f}")

    print("\n=== STEP 5: Persistir model coefs ===")
    coefs_dict = {
        "feature_names": feat_names,
        "classes": classes,
        "coefs": [list(c) for c in model.coef_],
        "intercepts": list(model.intercept_),
        "metadata": {
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "hit_train": round(hit_train, 4),
            "hit_test": round(hit_test, 4),
            "brier_train": round(brier_train, 4),
            "brier_test": round(brier_test, 4),
            "brier_test_elo_solo": round(brier_elo, 4),
            "brier_test_xg_solo": round(brier_xg, 4),
            "C": 1.0,
            "fecha_calibrado": "2026-04-28",
        },
    }
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, fecha_actualizacion)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, ("lr_v14_weights", "global", json.dumps(coefs_dict), "json", "adepor-141"))
    conn.commit()
    print("  config_motor_valores.lr_v14_weights persistido")

    # Save full report
    with open("analisis/calibrar_motor_copa_v14.json", "w", encoding="utf-8") as f:
        json.dump(coefs_dict, f, indent=2, ensure_ascii=False)
    print("\nReporte: analisis/calibrar_motor_copa_v14.json")
    conn.close()


if __name__ == "__main__":
    main()

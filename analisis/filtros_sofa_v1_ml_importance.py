"""
Fase 1.2 - ML feature importance sobre yield.

Para cada target (yield_local, yield_visita, yield_empate, yield_o25, yield_u25):
- RandomForest regressor con max_depth=4, n_estimators=200, min_samples_leaf=20
- Permutation importance (10 repeats sobre val split)
- Mutual information con hit (binary)
- Top-N features ranked

Output: JSON `filtros_sofa_v1_ml_importance.json`
"""
from __future__ import annotations
import sqlite3
import json
import math
import re
import numpy as np
from pathlib import Path
from collections import defaultdict
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.feature_selection import mutual_info_regression, mutual_info_classif
from sklearn.model_selection import KFold

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)


def cargar_universo_enriquecido():
    """Carga universo + lag-1 features + computa cards_per_game derivados."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_sofa_v1")]

    # O25/U25 yields
    for e in rows:
        gl, gv = e.get("hg"), e.get("ag")
        if gl is not None and gv is not None and e.get("cuota_o25"):
            total = gl + gv
            e["hit_o25"] = 1 if total > 2 else 0
            e["yield_o25"] = (e["cuota_o25"] - 1) if e["hit_o25"] else -1
        if gl is not None and gv is not None and e.get("cuota_u25"):
            total = gl + gv
            e["hit_u25"] = 1 if total <= 2 else 0
            e["yield_u25"] = (e["cuota_u25"] - 1) if e["hit_u25"] else -1

    # Lag-1 features (mismo equipo, partido anterior cualquier rol)
    sofa_all = cur.execute(
        """SELECT sofa_event_id, liga, fecha, ht, at,
                  big_chances_l, big_chances_v,
                  big_chances_missed_l, big_chances_missed_v,
                  shots_total_l, shots_total_v,
                  shots_on_target_l, shots_on_target_v,
                  shots_inside_box_l, shots_inside_box_v,
                  touches_penalty_area_l, touches_penalty_area_v,
                  errors_lead_to_shot_l, errors_lead_to_shot_v,
                  recoveries_l, recoveries_v,
                  ball_possession_l, ball_possession_v,
                  avg_rating_l, avg_rating_v,
                  max_rating_l, max_rating_v,
                  keeper_save_value_l, keeper_save_value_v,
                  xg_shotmap_l, xg_shotmap_v,
                  corners_l, corners_v, fouls_l, fouls_v,
                  saves_l, saves_v, offsides_l, offsides_v,
                  duels_pct_l, duels_pct_v,
                  hg, ag
           FROM sofascore_match_features WHERE error IS NULL"""
    ).fetchall()

    sofa_by_team = defaultdict(list)
    for r in sofa_all:
        d = dict(r)
        for side in ("l", "v"):
            equipo = d["ht"] if side == "l" else d["at"]
            sofa_by_team[(d["liga"], equipo)].append((d["fecha"][:10], side, d))

    for k in sofa_by_team:
        sofa_by_team[k].sort(key=lambda x: x[0])

    LAG_FIELDS = [
        "big_chances", "big_chances_missed", "shots_total", "shots_on_target",
        "shots_inside_box", "touches_penalty_area", "errors_lead_to_shot",
        "recoveries", "ball_possession", "avg_rating", "max_rating",
        "keeper_save_value", "xg_shotmap", "corners", "fouls", "saves",
        "offsides", "duels_pct",
    ]

    for e in rows:
        for side in ("l", "v"):
            equipo = e["ht"] if side == "l" else e["at"]
            history = sofa_by_team.get((e["liga"], equipo), [])
            prev = None
            for h in history:
                if h[0] < e["fecha"]:
                    prev = h
                else:
                    break
            for f in LAG_FIELDS:
                if prev is None:
                    e[f"{f}_lag1_{side}"] = None
                else:
                    pside = prev[1]
                    e[f"{f}_lag1_{side}"] = prev[2].get(f"{f}_{pside}")
            # Lag-1 outcome (won/draw/lost)
            if prev is None:
                e[f"won_lag1_{side}"] = None
                e[f"drew_lag1_{side}"] = None
            else:
                p_hg, p_ag = prev[2]["hg"], prev[2]["ag"]
                pside = prev[1]
                if p_hg is not None and p_ag is not None:
                    if pside == "l":
                        e[f"won_lag1_{side}"] = 1 if p_hg > p_ag else 0
                        e[f"drew_lag1_{side}"] = 1 if p_hg == p_ag else 0
                    else:
                        e[f"won_lag1_{side}"] = 1 if p_ag > p_hg else 0
                        e[f"drew_lag1_{side}"] = 1 if p_ag == p_hg else 0
                else:
                    e[f"won_lag1_{side}"] = None
                    e[f"drew_lag1_{side}"] = None

    return rows


def features_numericos(e: dict) -> dict:
    """Construye dict de features numericos PRE-match (no leakage).
    Pre-match = referee, formation (parsed), manager (count), n_players, lag-1 stats.
    NO usar stats actuales del partido en curso."""
    f = {}
    # Referee features (pre-match: asignados antes del partido)
    f["ref_yellows"] = e.get("referee_yellows")
    f["ref_reds"] = e.get("referee_reds")
    f["ref_games"] = e.get("referee_games")
    if f["ref_games"] and f["ref_games"] > 0:
        f["ref_cards_per_game"] = ((f["ref_yellows"] or 0) + (f["ref_reds"] or 0)) / f["ref_games"]
        f["ref_red_per_game"] = (f["ref_reds"] or 0) / f["ref_games"]
    else:
        f["ref_cards_per_game"] = None
        f["ref_red_per_game"] = None
    f["ref_novel"] = 1 if (f["ref_games"] is not None and f["ref_games"] < 30) else 0

    # Formation parsed (back, mid, fwd)
    def parse_form(s):
        if not s:
            return (None, None, None)
        try:
            parts = [int(x) for x in s.split("-")]
            return (parts[0] if parts else None,
                    sum(parts[1:-1]) if len(parts) > 2 else None,
                    parts[-1] if parts else None)
        except Exception:
            return (None, None, None)

    bl, ml, fl = parse_form(e.get("formation_l"))
    bv, mv, fv = parse_form(e.get("formation_v"))
    f["form_back_l"] = bl
    f["form_back_v"] = bv
    f["form_back_diff"] = (bl - bv) if (bl is not None and bv is not None) else None
    f["form_back_l_3"] = 1 if bl == 3 else 0
    f["form_back_l_4"] = 1 if bl == 4 else 0
    f["form_back_l_5"] = 1 if bl == 5 else 0
    f["form_back_v_3"] = 1 if bv == 3 else 0
    f["form_back_v_4"] = 1 if bv == 4 else 0
    f["form_back_v_5"] = 1 if bv == 5 else 0

    # Cuotas como features
    f["cuota_1"] = e.get("cuota_1")
    f["cuota_x"] = e.get("cuota_x")
    f["cuota_2"] = e.get("cuota_2")
    if f["cuota_1"] and f["cuota_2"]:
        f["cuota_ratio_2_1"] = f["cuota_2"] / f["cuota_1"]
        f["log_cuota_diff"] = math.log(f["cuota_2"]) - math.log(f["cuota_1"])
    else:
        f["cuota_ratio_2_1"] = None
        f["log_cuota_diff"] = None

    # Lag-1 features (PRE-match: del partido anterior)
    LAG_FIELDS = [
        "big_chances", "big_chances_missed", "shots_total", "shots_on_target",
        "shots_inside_box", "touches_penalty_area", "errors_lead_to_shot",
        "recoveries", "ball_possession", "avg_rating", "max_rating",
        "keeper_save_value", "xg_shotmap", "corners", "fouls", "saves",
        "offsides", "duels_pct",
    ]
    for fld in LAG_FIELDS:
        for side in ("l", "v"):
            f[f"{fld}_lag1_{side}"] = e.get(f"{fld}_lag1_{side}")
        # Diff l-v
        vl = e.get(f"{fld}_lag1_l")
        vv = e.get(f"{fld}_lag1_v")
        if vl is not None and vv is not None:
            f[f"{fld}_lag1_diff"] = vl - vv
        else:
            f[f"{fld}_lag1_diff"] = None

    # Lag-1 outcomes
    f["won_lag1_l"] = e.get("won_lag1_l")
    f["won_lag1_v"] = e.get("won_lag1_v")
    f["drew_lag1_l"] = e.get("drew_lag1_l")
    f["drew_lag1_v"] = e.get("drew_lag1_v")

    # Liga categorica (one-hot)
    LIGAS = ["Argentina","Brasil","Inglaterra","Italia","Espana","Francia","Alemania","Turquia",
             "Noruega","Uruguay","Peru","Bolivia","Ecuador","Venezuela"]
    for liga in LIGAS:
        f[f"liga_{liga}"] = 1 if e.get("liga") == liga else 0

    return f


def fit_eval(X: np.ndarray, y: np.ndarray, feat_names: list[str], target_name: str,
             classification: bool = False) -> dict:
    """Fit RF + permutation importance via 5-fold KFold (NO temporal porque solo 2026)."""
    if classification:
        model = RandomForestClassifier(
            n_estimators=200, max_depth=4, min_samples_leaf=20,
            random_state=42, n_jobs=-1
        )
    else:
        model = RandomForestRegressor(
            n_estimators=200, max_depth=4, min_samples_leaf=20,
            random_state=42, n_jobs=-1
        )

    model.fit(X, y)

    perm = permutation_importance(model, X, y, n_repeats=10, random_state=42, n_jobs=-1)
    rf_imp = model.feature_importances_

    if classification:
        mi = mutual_info_classif(X, y, random_state=42)
    else:
        mi = mutual_info_regression(X, y, random_state=42)

    importance = []
    for i, name in enumerate(feat_names):
        importance.append({
            "feature": name,
            "rf_importance": float(rf_imp[i]),
            "perm_importance_mean": float(perm.importances_mean[i]),
            "perm_importance_std": float(perm.importances_std[i]),
            "mutual_info": float(mi[i]),
        })
    importance.sort(key=lambda x: x["perm_importance_mean"], reverse=True)
    return {"target": target_name, "n_samples": len(y), "n_features": X.shape[1],
            "importance": importance[:30]}


def main():
    universo = cargar_universo_enriquecido()
    print(f"Universo: {len(universo)} eventos")

    # Construir matriz
    feats_list = []
    for e in universo:
        feats_list.append(features_numericos(e))

    feat_names = sorted({k for f in feats_list for k in f.keys()})
    X_raw = np.array([[(f.get(n) if f.get(n) is not None else np.nan) for n in feat_names]
                       for f in feats_list], dtype=float)

    # Imputar median per columna
    col_medians = np.nanmedian(X_raw, axis=0)
    inds = np.where(np.isnan(X_raw))
    X = X_raw.copy()
    X[inds] = np.take(col_medians, inds[1])

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]
    targets_class = {"yield_local": "hit_local", "yield_visita": "hit_visita",
                     "yield_empate": "hit_empate", "yield_o25": "hit_o25", "yield_u25": "hit_u25"}

    resultados = {"feat_count": len(feat_names), "n_samples": X.shape[0], "targets": []}
    for tg in targets:
        y_vals = np.array([(e.get(tg) if e.get(tg) is not None else np.nan) for e in universo])
        mask = ~np.isnan(y_vals)
        Xs = X[mask]
        ys = y_vals[mask]
        if len(ys) < 50:
            continue
        result_reg = fit_eval(Xs, ys, feat_names, tg, classification=False)

        # Classification target (hit)
        hit_field = targets_class[tg]
        h_vals = np.array([(e.get(hit_field) if e.get(hit_field) is not None else np.nan) for e in universo])
        mask_h = ~np.isnan(h_vals)
        Xh = X[mask_h]
        yh = h_vals[mask_h].astype(int)
        result_clf = fit_eval(Xh, yh, feat_names, hit_field, classification=True)

        resultados["targets"].append({
            "target": tg,
            "regression": result_reg,
            "classification": result_clf,
        })

    out = ROOT / "analisis" / "filtros_sofa_v1_ml_importance.json"
    out.write_text(json.dumps(resultados, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    print(f"Features: {len(feat_names)}")
    print()
    for tg in resultados["targets"]:
        print(f"=== Target: {tg['target']} ({tg['regression']['n_samples']} samples) ===")
        print("TOP 10 features (permutation importance):")
        for rec in tg["regression"]["importance"][:10]:
            print(f"  {rec['feature']:<35s} perm={rec['perm_importance_mean']:+.4f} ± {rec['perm_importance_std']:.4f}  MI={rec['mutual_info']:.4f}  RF={rec['rf_importance']:.4f}")
        print()


if __name__ == "__main__":
    main()

"""
FASE 2 (Tarea 2) — NNLS extended con interacciones.

Pool global (no per-liga, para evitar overfit con interacciones).

Features (k=11 base + interacciones):
  base:   sot, shots_off, corners, pos, pass_pct, saves_rival, blocks_rival
  inter:  sot_x_pos, sot_x_pass_pct, ratio_xg_l_v, lag_goles_3, residuo_xg_lag

Donde:
  - sot_x_pos = sot * (pos/100)              (interacc dominio territorial × precisión)
  - sot_x_pass_pct = sot * (pass_pct/100)    (calidad ataque)
  - ratio_xg_l_v = xg_calc_simple_local / xg_calc_simple_visita del partido (proxy de
                   superioridad ofensiva — usa β_sot productivo solo para crear el ratio,
                   NO leakage de targets futuros)
  - lag_goles_3 = avg(goles ULTIMOS 3 partidos del equipo) — forward-strict
  - residuo_xg_lag = xg_calc_simple_evento_anterior - goles_evento_anterior

Pipeline:
  - NNLS desde scipy.optimize.nnls — coefs >= 0, intercept >= 0 implícito (lo modelamos
    como columna constante adicional para forzarlo no-negativo).
  - θ-grid {0.05..0.30}.
  - Validacion 5-fold temporal CV intra-año + LOYO inter-año.
  - HOLDOUT 2026: NO usar para training ni hyperparam selection.
  - Reporte coefs aprendidos (sparsity check).

Output: analisis/motor_xg_v2_02_nnls_extended.json
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from math import sqrt
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

DB = "fondo_quant.db"
WARMUP = 5
OUT_JSON = "analisis/motor_xg_v2_02_nnls_extended.json"

HOLDOUT_YEARS = ("2026",)
TRAIN_YEARS = ("2022", "2023", "2024", "2025")
COTA_POISSON = 1.18
THETA_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)

BASE_FEATS = [
    "sot", "shots_off", "corners",
    "pos", "pass_pct", "saves_rival", "blocks_rival",
]
INTER_FEATS = [
    "sot_x_pos", "sot_x_pass_pct",
    "ratio_xg_l_v", "lag_goles_3", "residuo_xg_lag",
]
ALL_FEATS = BASE_FEATS + INTER_FEATS  # 12 features

BETA_PRODUCTIVO_GLOBAL = 0.352  # solo para construir ratio_xg_l_v como proxy


# ---------------------------------------------------------------------------
# Carga (idéntica a Tarea 1)
# ---------------------------------------------------------------------------

def cargar_partidos_extendido() -> list[dict]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag,
               hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct,
               h_saves, a_saves, h_blocks, a_blocks,
               h_longballs_acc, a_longballs_acc
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
        ORDER BY fecha ASC, ht ASC
    """).fetchall()
    con.close()

    out = []
    for r in rows:
        (liga, fecha, ht, at, hg, ag,
         hst, ast, hs, as_v, hc, ac,
         h_pos, a_pos, h_pass_pct, a_pass_pct,
         h_saves, a_saves, h_blocks, a_blocks,
         h_long_acc, a_long_acc) = r
        out.append({
            "liga": liga, "fecha": fecha, "ht": ht, "at": at,
            "hg": hg, "ag": ag,
            "hst": hst, "ast": ast,
            "hs": hs or 0, "as_v": as_v or 0,
            "hc": hc or 0, "ac": ac or 0,
            "h_pos": h_pos, "a_pos": a_pos,
            "h_pass_pct": h_pass_pct, "a_pass_pct": a_pass_pct,
            "h_saves": h_saves, "a_saves": a_saves,
            "h_blocks": h_blocks, "a_blocks": a_blocks,
            "h_long_acc": h_long_acc, "a_long_acc": a_long_acc,
        })
    return out


def cargar_alfa_ema() -> tuple[dict, float]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    alfa = {}
    for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores "
        "WHERE clave='alfa_ema' AND tipo='float'"
    ):
        alfa[r[0]] = float(r[1])
    con.close()
    DEFAULT = 0.10
    alfa.pop("global", None)
    return alfa, DEFAULT


# ---------------------------------------------------------------------------
# Construccion de eventos con features extendidos forward-strict
# ---------------------------------------------------------------------------

def construir_eventos_extendido(partidos: list[dict]) -> list[dict]:
    """Genera eventos con features base + interacciones forward-strict.

    lag_goles_3 y residuo_xg_lag se computan SOLO con info pasada (forward-strict).
    """
    eventos_raw: list[dict] = []
    for p in partidos:
        # ratio xg_l_v: usa β productivo SOLO para tener una señal de fuerza ofensiva
        # del partido. NO usa goles. (es función simétrica de SOT, shots_off, corners.)
        h_xg_simple = (
            BETA_PRODUCTIVO_GLOBAL * p["hst"]
            + 0.010 * max(0, p["hs"] - p["hst"])
            + 0.030 * p["hc"]
        )
        a_xg_simple = (
            BETA_PRODUCTIVO_GLOBAL * p["ast"]
            + 0.010 * max(0, p["as_v"] - p["ast"])
            + 0.030 * p["ac"]
        )
        ratio_l = h_xg_simple / max(a_xg_simple, 0.1)  # local
        ratio_v = a_xg_simple / max(h_xg_simple, 0.1)  # visita

        ev_l = {
            "fecha": p["fecha"], "liga": p["liga"], "equipo": p["ht"],
            "rival": p["at"], "goles": p["hg"],
            "sot": p["hst"], "shots_off": max(0, p["hs"] - p["hst"]),
            "corners": p["hc"],
            "pos": p["h_pos"], "pass_pct": p["h_pass_pct"],
            "saves_rival": p["a_saves"], "blocks_rival": p["a_blocks"],
            "ratio_xg_l_v": ratio_l,
            "_xg_simple_self": h_xg_simple,
        }
        ev_v = {
            "fecha": p["fecha"], "liga": p["liga"], "equipo": p["at"],
            "rival": p["ht"], "goles": p["ag"],
            "sot": p["ast"], "shots_off": max(0, p["as_v"] - p["ast"]),
            "corners": p["ac"],
            "pos": p["a_pos"], "pass_pct": p["a_pass_pct"],
            "saves_rival": p["h_saves"], "blocks_rival": p["h_blocks"],
            "ratio_xg_l_v": ratio_v,
            "_xg_simple_self": a_xg_simple,
        }
        eventos_raw.append(ev_l)
        eventos_raw.append(ev_v)

    # Ordenar por fecha y construir lag por equipo
    eventos_raw.sort(key=lambda e: e["fecha"])
    state_lag: dict[str, deque] = defaultdict(lambda: deque(maxlen=3))
    state_residuo_prev: dict[str, float | None] = defaultdict(lambda: None)

    for ev in eventos_raw:
        eq = ev["equipo"]
        # lag_goles_3: promedio de los hasta-3 ultimos goles previos
        lq = state_lag[eq]
        if len(lq) >= 1:
            ev["lag_goles_3"] = sum(lq) / len(lq)
        else:
            ev["lag_goles_3"] = None

        # residuo_xg_lag: del partido inmediatamente anterior del equipo
        ev["residuo_xg_lag"] = state_residuo_prev[eq]

        # Interacciones: necesitan pos/pass_pct presentes
        if ev["pos"] is not None:
            ev["sot_x_pos"] = ev["sot"] * (ev["pos"] / 100.0)
        else:
            ev["sot_x_pos"] = None
        if ev["pass_pct"] is not None:
            ev["sot_x_pass_pct"] = ev["sot"] * (ev["pass_pct"] / 100.0)
        else:
            ev["sot_x_pass_pct"] = None

        # Update state DESPUES de capturar (forward-strict)
        state_lag[eq].append(ev["goles"])
        state_residuo_prev[eq] = ev["_xg_simple_self"] - ev["goles"]

    return eventos_raw


def evento_es_completo(ev: dict, features: list[str]) -> bool:
    for f in features:
        if ev.get(f) is None:
            return False
    return True


def evento_year(ev: dict) -> str:
    return ev["fecha"][:4]


# ---------------------------------------------------------------------------
# NNLS pool global
# ---------------------------------------------------------------------------

def fit_nnls_pool(eventos_train: list[dict], features: list[str]) -> dict:
    """Ajusta NNLS pool global con intercept como columna de unos.

    Devuelve dict(intercept, coefs={feat: w}, residual_norm, n_train).
    """
    completos = [ev for ev in eventos_train if evento_es_completo(ev, features)]
    if len(completos) < 100:
        return None
    X = np.array(
        [[1.0] + [ev[f] for f in features] for ev in completos],
        dtype=float,
    )
    y = np.array([ev["goles"] for ev in completos], dtype=float)
    w, residual = nnls(X, y)
    intercept = float(w[0])
    coefs = {f: float(c) for f, c in zip(features, w[1:])}
    return {
        "intercept": intercept,
        "coefs": coefs,
        "residual_norm": float(residual),
        "n_train": len(completos),
    }


def predecir_xg_calc_nnls(ev: dict, features: list[str], modelo: dict) -> float | None:
    if modelo is None:
        return None
    s = modelo["intercept"]
    for f in features:
        v = ev.get(f)
        if v is None:
            return None
        s += modelo["coefs"][f] * v
    return max(0.0, s)


# ---------------------------------------------------------------------------
# RMSE forward-EMA
# ---------------------------------------------------------------------------

def rmse_forward_ema(
    eventos: list[dict],
    theta: float,
    features: list[str],
    modelo: dict,
    alfa_ema: dict, def_alfa: float,
) -> dict:
    state = defaultdict(lambda: {"ema": None, "n": 0})
    errs_by_year: dict[str, list[float]] = defaultdict(list)
    n_used = 0
    n_skipped = 0

    for ev in sorted(eventos, key=lambda e: e["fecha"]):
        liga = ev["liga"]
        alfa = alfa_ema.get(liga, def_alfa)
        xg_calc = predecir_xg_calc_nnls(ev, features, modelo)
        if xg_calc is None:
            n_skipped += 1
            continue
        n_used += 1
        goles = ev["goles"]
        xg_final = theta * xg_calc + (1.0 - theta) * goles

        s = state[ev["equipo"]]
        if s["ema"] is not None and s["n"] >= WARMUP:
            errs_by_year[evento_year(ev)].append(s["ema"] - goles)
        if s["ema"] is None:
            s["ema"] = xg_final
        else:
            s["ema"] = alfa * xg_final + (1.0 - alfa) * s["ema"]
        s["n"] += 1

    return _resumir(errs_by_year, n_used, n_skipped)


def _resumir(errs_by_year, n_used=None, n_skipped=None) -> dict:
    def rmse(errs):
        if not errs:
            return None
        return sqrt(sum(e * e for e in errs) / len(errs))

    out = {}
    for y in sorted(errs_by_year.keys()):
        out[y] = {"rmse": rmse(errs_by_year[y]), "n": len(errs_by_year[y])}
    pool = []
    for y in TRAIN_YEARS:
        pool.extend(errs_by_year.get(y, []))
    out["OOS_pool"] = {"rmse": rmse(pool), "n": len(pool)}
    holdout = []
    for y in HOLDOUT_YEARS:
        holdout.extend(errs_by_year.get(y, []))
    out["IS_2026"] = {"rmse": rmse(holdout), "n": len(holdout)}
    if n_used is not None:
        out["_n_eventos_usados"] = n_used
    if n_skipped is not None:
        out["_n_eventos_skipped"] = n_skipped
    return out


# ---------------------------------------------------------------------------
# Validacion CV
# ---------------------------------------------------------------------------

def cv_5fold_temporal(
    eventos_all: list[dict],
    features: list[str],
    theta: float,
) -> dict:
    eventos_train_universe = [ev for ev in eventos_all
                              if evento_year(ev) in TRAIN_YEARS]
    eventos_train_universe.sort(key=lambda e: e["fecha"])
    n = len(eventos_train_universe)
    fold_size = n // 5
    rmses = []
    for k in range(5):
        i_start = k * fold_size
        i_end = (k + 1) * fold_size if k < 4 else n
        test_evs = eventos_train_universe[i_start:i_end]
        train_evs = eventos_train_universe[:i_start] + eventos_train_universe[i_end:]
        modelo = fit_nnls_pool(train_evs, features)
        if modelo is None:
            continue
        errs = []
        for ev in test_evs:
            xg = predecir_xg_calc_nnls(ev, features, modelo)
            if xg is None:
                continue
            errs.append(xg - ev["goles"])
        if errs:
            rmses.append(sqrt(sum(e * e for e in errs) / len(errs)))
    return {
        "rmse_mean": (sum(rmses) / len(rmses)) if rmses else None,
        "rmse_per_fold": rmses,
        "n_folds": len(rmses),
    }


def loyo_inter_year(
    eventos_all: list[dict],
    features: list[str],
    theta: float,
    alfa_ema, def_alfa,
) -> dict:
    eventos_train_uni = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    out = {}
    for test_year in TRAIN_YEARS:
        train_evs = [ev for ev in eventos_train_uni if evento_year(ev) != test_year]
        modelo = fit_nnls_pool(train_evs, features)
        if modelo is None:
            out[test_year] = {"rmse_test_year": None, "n_test_year": 0}
            continue
        resumen = rmse_forward_ema(
            eventos_train_uni, theta, features, modelo, alfa_ema, def_alfa,
        )
        out[test_year] = {
            "rmse_test_year": resumen.get(test_year, {}).get("rmse"),
            "n_test_year": resumen.get(test_year, {}).get("n"),
        }
    rmses = [v["rmse_test_year"] for v in out.values() if v["rmse_test_year"] is not None]
    out["_loyo_mean_rmse"] = sum(rmses) / len(rmses) if rmses else None
    return out


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def evaluar_combo(eventos_all, features, theta, alfa_ema, def_alfa) -> dict:
    eventos_train = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    n_train = sum(1 for ev in eventos_train if evento_es_completo(ev, features))
    dof_ratio = len(features) / max(n_train, 1)
    abort = dof_ratio > 0.10
    modelo = fit_nnls_pool(eventos_train, features)
    if modelo is None:
        return {"rmse_resumen": None, "modelo": None, "dof_abort": abort}
    resumen = rmse_forward_ema(
        eventos_all, theta, features, modelo, alfa_ema, def_alfa,
    )
    return {
        "config": {"features": features, "theta": theta},
        "n_train_completos": n_train,
        "dof_ratio": dof_ratio,
        "dof_abort": abort,
        "rmse_resumen": resumen,
        "modelo": modelo,
    }


def main():
    print("=" * 72)
    print("FASE 2 Tarea 2 — NNLS pool global con interacciones")
    print("=" * 72)
    partidos = cargar_partidos_extendido()
    print(f"Partidos cargados: {len(partidos)}")
    alfa_ema, def_alfa = cargar_alfa_ema()
    print(f"alfa_ema scopes liga: {len(alfa_ema)} | default: {def_alfa}")

    eventos_all = construir_eventos_extendido(partidos)
    print(f"Eventos construidos: {len(eventos_all)}")

    # Diagnostico de completos por feature set:
    n_total = sum(1 for ev in eventos_all if evento_year(ev) in TRAIN_YEARS)
    n_base = sum(1 for ev in eventos_all
                 if evento_year(ev) in TRAIN_YEARS and evento_es_completo(ev, BASE_FEATS))
    n_all = sum(1 for ev in eventos_all
                if evento_year(ev) in TRAIN_YEARS and evento_es_completo(ev, ALL_FEATS))
    print(f"  N train total: {n_total}")
    print(f"  N completos BASE_FEATS:  {n_base}")
    print(f"  N completos ALL_FEATS:   {n_all}")

    resultados = {"_meta": {
        "N_partidos": len(partidos),
        "WARMUP": WARMUP,
        "THETA_GRID": list(THETA_GRID),
        "TRAIN_YEARS": list(TRAIN_YEARS),
        "HOLDOUT_YEARS": list(HOLDOUT_YEARS),
        "COTA_POISSON": COTA_POISSON,
        "BASE_FEATS": BASE_FEATS,
        "INTER_FEATS": INTER_FEATS,
        "ALL_FEATS": ALL_FEATS,
        "n_eventos_completos_train_all": n_all,
        "n_eventos_completos_train_base": n_base,
        "n_eventos_total_train": n_total,
    }}

    # Probamos 3 configs:
    #   1) BASE solo (7 features)
    #   2) BASE + lag_goles_3 + residuo_xg_lag (no requieren pos/pass_pct)  -> 9 feats
    #   3) ALL (12 feats)
    BASE_PLUS_LAGS = BASE_FEATS + ["lag_goles_3", "residuo_xg_lag"]
    feature_sets = {
        "BASE": BASE_FEATS,
        "BASE_plus_lags": BASE_PLUS_LAGS,
        "ALL": ALL_FEATS,
    }

    for fset_name, fset in feature_sets.items():
        print(f"\n--- Feature set: {fset_name} ({len(fset)} features) ---")
        grid = {}
        best = None
        best_modelo = None
        for theta in THETA_GRID:
            r = evaluar_combo(eventos_all, fset, theta, alfa_ema, def_alfa)
            modelo = r.pop("modelo")
            if r["rmse_resumen"] is None:
                continue
            grid[f"theta={theta:.2f}"] = {
                "rmse_oos": r["rmse_resumen"]["OOS_pool"]["rmse"],
                "rmse_is_2026": r["rmse_resumen"]["IS_2026"]["rmse"],
                "n_train_completos": r["n_train_completos"],
                "dof_abort": r["dof_abort"],
            }
            oos = r["rmse_resumen"]["OOS_pool"]["rmse"]
            if oos is not None and (best is None or oos < best[0]):
                best = (oos, theta, r)
                best_modelo = modelo

        if best is None:
            print(f"  [{fset_name}] NO converge.")
            continue

        oos_b, t_b, r_b = best
        is2026_b = r_b["rmse_resumen"]["IS_2026"]["rmse"]
        print(f"  BEST: theta={t_b:.2f} -> OOS={oos_b:.4f} IS_2026={is2026_b:.4f}")
        print(f"  Coefs (sparsity check):")
        for f, c in best_modelo["coefs"].items():
            star = " <- ZERO (pruned)" if abs(c) < 1e-6 else ""
            print(f"    {f:<20s} = {c:+.5f}{star}")
        print(f"    intercept            = {best_modelo['intercept']:+.5f}")

        breaks_floor = oos_b < COTA_POISSON

        # CV 5-fold y LOYO sobre best theta
        print(f"  Corriendo 5-fold temporal CV...")
        cv5 = cv_5fold_temporal(eventos_all, fset, t_b)
        print(f"    CV5 RMSE mean (xg_calc puntual): {cv5['rmse_mean']}")

        print(f"  Corriendo LOYO inter-año...")
        loyo = loyo_inter_year(eventos_all, fset, t_b, alfa_ema, def_alfa)
        print(f"    LOYO mean RMSE: {loyo.get('_loyo_mean_rmse')}")
        for y in TRAIN_YEARS:
            v = loyo.get(y, {})
            if v.get("rmse_test_year") is not None:
                print(f"      {y}: RMSE={v['rmse_test_year']:.4f} N={v['n_test_year']}")

        resultados[fset_name] = {
            "theta_best": t_b,
            "rmse_oos_pool": oos_b,
            "rmse_is_2026": is2026_b,
            "n_eventos_usados_full": r_b["rmse_resumen"].get("_n_eventos_usados"),
            "n_eventos_skipped_full": r_b["rmse_resumen"].get("_n_eventos_skipped"),
            "rmse_per_year": {y: r_b["rmse_resumen"].get(y, {}) for y in TRAIN_YEARS + HOLDOUT_YEARS},
            "modelo": {
                "intercept": best_modelo["intercept"],
                "coefs": best_modelo["coefs"],
                "n_train": best_modelo["n_train"],
                "residual_norm": best_modelo["residual_norm"],
            },
            "cv5_temporal": cv5,
            "loyo_per_year": loyo,
            "breaks_poisson_floor": bool(breaks_floor),
            "grid_full": grid,
        }

    # Comparacion final vs V5 baseline
    V5_BASELINE = 1.1963
    print(f"\n=== Comparacion vs V5 NNLS baseline ({V5_BASELINE:.4f}) ===")
    if resultados.get("BASE") and resultados.get("ALL"):
        for k in feature_sets:
            r = resultados.get(k)
            if r:
                d = r["rmse_oos_pool"] - V5_BASELINE
                print(f"  {k:<20s} OOS: {r['rmse_oos_pool']:.4f}  delta={d:+.4f}")
        # best of best
        best_name = min(
            (k for k in feature_sets if resultados.get(k)),
            key=lambda k: resultados[k]["rmse_oos_pool"],
        )
        rmse_b = resultados[best_name]["rmse_oos_pool"]
        resultados["best_config"] = best_name
        resultados["comparison_vs_baseline_v5"] = {
            "v5_baseline_rmse": V5_BASELINE,
            "best_config": best_name,
            "best_rmse": rmse_b,
            "delta_rmse_oos": rmse_b - V5_BASELINE,
            "ratio": rmse_b / V5_BASELINE,
        }
        print(f"  best_config: {best_name}")

    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(resultados, f, indent=2, default=str)
    print(f"\nGuardado {OUT_JSON}")


if __name__ == "__main__":
    main()

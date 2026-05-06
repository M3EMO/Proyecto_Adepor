"""
FASE 2 (Tarea 1) — Ridge regression per-liga con θ-grid + α_ridge-grid.

Metodologia:
  1. Por cada liga, ajustar Ridge(positive=True) que mapea features de un partido
     {SOT, shots_off, corners, [pos, pass_pct, saves_rival, blocks_rival,
      longballs_acc]} -> goles del equipo en ese partido.
  2. Pipeline: feature_vec -> xg_calc -> xg_final = θ·xg_calc + (1−θ)·goles.
  3. EMA forward-strict por equipo, RMSE pooled.
  4. Validacion 5-fold temporal CV (intra-año) + LOYO inter-año {2022..2025}.
  5. NO usar 2026 para training ni hyperparam selection (HOLDOUT).

Output: analisis/motor_xg_v2_01_ridge_per_liga.json

REF: docs/definiciones/rmse_forward_ema.md
REF: analisis/motor_xg_v2_00_baseline.py
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from math import sqrt
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

DB = "fondo_quant.db"
WARMUP = 5
OUT_JSON = "analisis/motor_xg_v2_01_ridge_per_liga.json"

# Holdout estricto: NO usar 2026 jamas para training ni para seleccionar hyperparams.
HOLDOUT_YEARS = ("2026",)
TRAIN_YEARS = ("2022", "2023", "2024", "2025")
COTA_POISSON = 1.18

ALPHA_GRID = (0.001, 0.01, 0.1, 1.0, 10.0)
THETA_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)

F_SIMPLE = ("sot", "shots_off", "corners")
F_EXTENDED = (
    "sot", "shots_off", "corners",
    "pos", "pass_pct", "saves_rival", "blocks_rival", "longballs_acc",
)


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def cargar_partidos_extendido() -> list[dict]:
    """Carga partidos con TODAS las stats relevantes; mantiene NULLs.

    Devuelve filas como dicts (mas claro que tuplas con 30 cols).
    """
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
    DEFAULT = 0.10  # baseline empirico, no el global de DB (0.15)
    alfa.pop("global", None)
    return alfa, DEFAULT


# ---------------------------------------------------------------------------
# Construccion de eventos (un evento por equipo por partido)
# ---------------------------------------------------------------------------

def construir_eventos(partidos: list[dict], features: tuple[str, ...]) -> list[dict]:
    """Cada partido -> 2 eventos (local + visita).

    Cada evento contiene los features pedidos. Los faltantes vienen como None.
    """
    eventos = []
    for p in partidos:
        # local
        ev_l = {
            "fecha": p["fecha"], "liga": p["liga"], "equipo": p["ht"],
            "rival": p["at"], "goles": p["hg"],
            "sot": p["hst"], "shots_off": max(0, p["hs"] - p["hst"]),
            "corners": p["hc"],
            "pos": p["h_pos"], "pass_pct": p["h_pass_pct"],
            "saves_rival": p["a_saves"], "blocks_rival": p["a_blocks"],
            "longballs_acc": p["h_long_acc"],
        }
        # visita
        ev_v = {
            "fecha": p["fecha"], "liga": p["liga"], "equipo": p["at"],
            "rival": p["ht"], "goles": p["ag"],
            "sot": p["ast"], "shots_off": max(0, p["as_v"] - p["ast"]),
            "corners": p["ac"],
            "pos": p["a_pos"], "pass_pct": p["a_pass_pct"],
            "saves_rival": p["h_saves"], "blocks_rival": p["h_blocks"],
            "longballs_acc": p["a_long_acc"],
        }
        eventos.append(ev_l)
        eventos.append(ev_v)
    return eventos


def evento_es_completo(ev: dict, features: tuple[str, ...]) -> bool:
    for f in features:
        if ev.get(f) is None:
            return False
    return True


def evento_year(ev: dict) -> str:
    return ev["fecha"][:4]


# ---------------------------------------------------------------------------
# Ajuste Ridge per liga
# ---------------------------------------------------------------------------

def fit_ridge_per_liga(
    eventos_train: list[dict],
    features: tuple[str, ...],
    alpha: float,
) -> dict[str, np.ndarray]:
    """Ajusta Ridge(positive=True, fit_intercept=True) por liga.

    Devuelve {liga: dict(intercept=float, coefs=ndarray)}.
    Solo entrena con eventos COMPLETOS para ese feature set.
    """
    by_liga: dict[str, list[dict]] = defaultdict(list)
    for ev in eventos_train:
        if evento_es_completo(ev, features):
            by_liga[ev["liga"]].append(ev)

    out = {}
    for liga, evs in by_liga.items():
        if len(evs) < max(50, 3 * len(features)):
            # liga con pocos datos: skip, fallback al global later
            continue
        X = np.array([[ev[f] for f in features] for ev in evs], dtype=float)
        y = np.array([ev["goles"] for ev in evs], dtype=float)
        m = Ridge(alpha=alpha, positive=True, fit_intercept=True)
        m.fit(X, y)
        out[liga] = {
            "intercept": float(m.intercept_),
            "coefs": m.coef_.astype(float).tolist(),
            "n_train": int(len(evs)),
        }

    # Modelo global de fallback (todas las ligas mezcladas)
    evs_global = [ev for evs in by_liga.values() for ev in evs]
    if evs_global:
        X = np.array([[ev[f] for f in features] for ev in evs_global], dtype=float)
        y = np.array([ev["goles"] for ev in evs_global], dtype=float)
        m = Ridge(alpha=alpha, positive=True, fit_intercept=True)
        m.fit(X, y)
        out["__global__"] = {
            "intercept": float(m.intercept_),
            "coefs": m.coef_.astype(float).tolist(),
            "n_train": int(len(evs_global)),
        }
    return out


def predecir_xg_calc(ev: dict, features: tuple[str, ...], modelo_liga: dict) -> float:
    """Aplica modelo Ridge per-liga (con fallback global) sobre el evento.

    Si el evento NO tiene features completos, usa imputacion (media de feature) =
    aqui lo simplificamos: si falta algun feature, devolvemos None y el caller
    decide si descartar o usar fallback de baseline.
    """
    coefs = modelo_liga["coefs"]
    intercept = modelo_liga["intercept"]
    s = intercept
    for f, c in zip(features, coefs):
        v = ev.get(f)
        if v is None:
            return None
        s += c * v
    return max(0.0, s)


# ---------------------------------------------------------------------------
# RMSE forward-EMA con xg_calc venido de un modelo
# ---------------------------------------------------------------------------

def rmse_forward_ema(
    eventos: list[dict],
    theta: float,
    features: tuple[str, ...],
    modelos_per_liga: dict[str, dict],
    alfa_ema: dict[str, float],
    def_alfa: float,
) -> dict:
    """Recorre eventos cronologicamente, calcula EMA forward-strict, RMSE por año.

    Si un evento no tiene features completos para su liga, se SALTA para training
    pero NO se usa para EMA tampoco -> mantenemos consistencia. Alternativamente,
    podemos re-introducirlo via fallback global. Aqui usamos fallback global: si
    el evento no tiene features completos para su liga, intentamos modelo
    global.
    """
    state = defaultdict(lambda: {"ema": None, "n": 0})
    errs_by_year: dict[str, list[float]] = defaultdict(list)
    n_eventos_usados = 0
    n_eventos_skipped_no_modelo = 0

    eventos_sorted = sorted(eventos, key=lambda e: e["fecha"])

    for ev in eventos_sorted:
        liga = ev["liga"]
        alfa = alfa_ema.get(liga, def_alfa)

        modelo = modelos_per_liga.get(liga) or modelos_per_liga.get("__global__")
        if modelo is None:
            n_eventos_skipped_no_modelo += 1
            continue

        xg_calc = predecir_xg_calc(ev, features, modelo)
        if xg_calc is None:
            # features incompletos: skip
            n_eventos_skipped_no_modelo += 1
            continue

        n_eventos_usados += 1
        goles = ev["goles"]
        xg_final = theta * xg_calc + (1.0 - theta) * goles

        s = state[ev["equipo"]]
        if s["ema"] is not None and s["n"] >= WARMUP:
            year = evento_year(ev)
            errs_by_year[year].append(s["ema"] - goles)

        if s["ema"] is None:
            s["ema"] = xg_final
        else:
            s["ema"] = alfa * xg_final + (1.0 - alfa) * s["ema"]
        s["n"] += 1

    return _resumir(errs_by_year, n_eventos_usados, n_eventos_skipped_no_modelo)


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
# Validacion 5-fold temporal intra-año + LOYO inter-año
# ---------------------------------------------------------------------------

def cv_5fold_temporal_intra_year(
    partidos: list[dict],
    features: tuple[str, ...],
    alpha: float,
    theta: float,
    alfa_ema: dict, def_alfa: float,
) -> dict:
    """5 folds temporales sobre TRAIN_YEARS unidos (2022-2025).

    Cada fold: ajustar Ridge en 4/5 cronologicos, evaluar RMSE sobre 1/5.
    El EMA se computa forward-strict sobre el universo completo, pero los errores
    se acumulan SOLO sobre el fold de test.

    Devuelve rmse promedio sobre 5 folds.
    """
    eventos_all = construir_eventos(partidos, features)
    # Filtrar al universo TRAIN_YEARS (excluir 2026)
    eventos_train_universe = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]
    eventos_train_universe.sort(key=lambda e: e["fecha"])

    n = len(eventos_train_universe)
    if n < 100:
        return {"rmse_mean": None, "rmse_per_fold": [], "n_folds": 0}

    fold_size = n // 5
    rmses = []

    for k in range(5):
        i_start = k * fold_size
        i_end = (k + 1) * fold_size if k < 4 else n
        test_evs = eventos_train_universe[i_start:i_end]
        train_evs = eventos_train_universe[:i_start] + eventos_train_universe[i_end:]

        modelos = fit_ridge_per_liga(train_evs, features, alpha)

        # Evaluar RMSE sobre test_evs (sin EMA -- regresion pura sobre xg_calc vs goles)
        # Nota: aqui evaluamos calidad PUNTUAL del Ridge per-liga, no el RMSE
        # forward-EMA. Es un proxy mas barato y sirve para hyperparam selection.
        errs = []
        for ev in test_evs:
            modelo = modelos.get(ev["liga"]) or modelos.get("__global__")
            if modelo is None:
                continue
            xg = predecir_xg_calc(ev, features, modelo)
            if xg is None:
                continue
            # En CV tomamos el error del xg_calc puntual (no EMA forward)
            errs.append(xg - ev["goles"])
        if errs:
            rmses.append(sqrt(sum(e * e for e in errs) / len(errs)))

    if not rmses:
        return {"rmse_mean": None, "rmse_per_fold": [], "n_folds": 0}
    return {
        "rmse_mean": sum(rmses) / len(rmses),
        "rmse_per_fold": rmses,
        "n_folds": len(rmses),
    }


def loyo_inter_year(
    partidos: list[dict],
    features: tuple[str, ...],
    alpha: float,
    theta: float,
    alfa_ema: dict, def_alfa: float,
) -> dict:
    """Leave-one-year-out sobre TRAIN_YEARS.

    Para cada año test ∈ {2022,23,24,25}: entrenar con los 3 restantes, evaluar
    RMSE forward-EMA sobre el año test usando el modelo. EMA se computa
    cronologicamente sobre el universo completo (incluyendo el año test) pero
    los xg_calc del año test se predicen con un modelo que NO vio ese año.

    En la practica simplificamos: separamos el año test y usamos el modelo
    entrenado en 3 años para predecir xg_calc en TODO el universo, y luego
    extraemos errores del año test.
    """
    eventos_all = construir_eventos(partidos, features)
    eventos_all_train_uni = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]

    out = {}
    for test_year in TRAIN_YEARS:
        train_evs = [ev for ev in eventos_all_train_uni
                     if evento_year(ev) != test_year]
        modelos = fit_ridge_per_liga(train_evs, features, alpha)

        # RMSE forward-EMA sobre TODO el universo (no solo el test_year), pero
        # para reportar usaremos el bucket del test_year. EMA se inicializa
        # desde el principio de los datos para no tener cold-start sesgado.
        resumen = rmse_forward_ema(
            eventos_all_train_uni, theta, features, modelos,
            alfa_ema, def_alfa,
        )
        out[test_year] = {
            "rmse_test_year": resumen.get(test_year, {}).get("rmse"),
            "n_test_year": resumen.get(test_year, {}).get("n"),
        }

    # Promedio simple de los 4 RMSEs LOYO
    rmses = [v["rmse_test_year"] for v in out.values() if v["rmse_test_year"] is not None]
    out["_loyo_mean_rmse"] = sum(rmses) / len(rmses) if rmses else None
    return out


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def evaluar_config(
    partidos: list[dict],
    features: tuple[str, ...],
    alpha: float,
    theta: float,
    alfa_ema: dict, def_alfa: float,
) -> dict:
    """Evalua una config (alpha, theta) sobre todo el dataset.

    Pipeline:
      1) Entrenar Ridge per-liga sobre TRAIN_YEARS (2022-2025) — eventos completos.
      2) Computar RMSE forward-EMA sobre TODO el universo (incl 2026).
      3) Reportar OOS_pool, IS_2026, per year, n_efectivo.
    """
    eventos_all = construir_eventos(partidos, features)
    eventos_train = [ev for ev in eventos_all if evento_year(ev) in TRAIN_YEARS]

    # DOF check
    n_features = len(features)
    n_train = sum(1 for ev in eventos_train if evento_es_completo(ev, features))
    dof_ratio = (n_features * 16) / max(n_train, 1)  # 16 ligas
    abort = dof_ratio > 0.10

    modelos = fit_ridge_per_liga(eventos_train, features, alpha)
    resumen = rmse_forward_ema(
        eventos_all, theta, features, modelos, alfa_ema, def_alfa,
    )
    return {
        "config": {"features": list(features), "alpha": alpha, "theta": theta},
        "n_train_completos": n_train,
        "dof_ratio": dof_ratio,
        "dof_abort": abort,
        "rmse_resumen": resumen,
        "modelos": modelos,
    }


def main():
    print("=" * 72)
    print("FASE 2 Tarea 1 — Ridge per liga (alpha-grid x theta-grid x F_simple/extended)")
    print("=" * 72)

    partidos = cargar_partidos_extendido()
    print(f"Partidos cargados: {len(partidos)}")
    alfa_ema, def_alfa = cargar_alfa_ema()
    print(f"alfa_ema scopes liga: {len(alfa_ema)} | default: {def_alfa}")

    resultados = {"_meta": {
        "N_partidos": len(partidos),
        "WARMUP": WARMUP,
        "ALPHA_GRID": list(ALPHA_GRID),
        "THETA_GRID": list(THETA_GRID),
        "TRAIN_YEARS": list(TRAIN_YEARS),
        "HOLDOUT_YEARS": list(HOLDOUT_YEARS),
        "COTA_POISSON": COTA_POISSON,
    }}

    for fset_name, fset in (("F_simple", F_SIMPLE), ("F_extended", F_EXTENDED)):
        print(f"\n--- Feature set: {fset_name} = {fset}")

        # Verificar N efectivo
        eventos_all = construir_eventos(partidos, fset)
        n_completos_train = sum(
            1 for ev in eventos_all
            if evento_year(ev) in TRAIN_YEARS and evento_es_completo(ev, fset)
        )
        n_total_train = sum(1 for ev in eventos_all if evento_year(ev) in TRAIN_YEARS)
        print(f"  Eventos train completos: {n_completos_train}/{n_total_train}")

        # Filtros NULLs descartados:
        if fset_name == "F_extended":
            n_drop = n_total_train - n_completos_train
            print(f"  Filtro NULL pos/pass_pct/saves/blocks/longballs descarto: {n_drop}")

        grid_results = {}
        best = None  # (oos_pool, alpha, theta, full_dict)

        for alpha in ALPHA_GRID:
            for theta in THETA_GRID:
                r = evaluar_config(partidos, fset, alpha, theta, alfa_ema, def_alfa)
                key = f"alpha={alpha:g}|theta={theta:.2f}"
                # Limpiar modelos del JSON expandido (los guardamos solo para el best)
                models_full = r.pop("modelos")
                grid_results[key] = r
                oos = r["rmse_resumen"]["OOS_pool"]["rmse"]
                if oos is not None and (best is None or oos < best[0]):
                    best = (oos, alpha, theta, r, models_full)

        if best is None:
            print(f"  [{fset_name}] no hubo combos con OOS_pool valido.")
            continue

        oos_best, a_best, t_best, r_best, mods_best = best
        is2026_best = r_best["rmse_resumen"]["IS_2026"]["rmse"]
        print(f"  BEST: alpha={a_best:g} theta={t_best:.2f} -> OOS={oos_best:.4f} IS_2026={is2026_best:.4f}")

        # Romper cota Poisson?
        breaks_floor = oos_best < COTA_POISSON

        # CV 5-fold temporal sobre el best
        print(f"  Corriendo 5-fold temporal CV sobre best...")
        cv5 = cv_5fold_temporal_intra_year(partidos, fset, a_best, t_best, alfa_ema, def_alfa)
        print(f"    CV5 RMSE mean (xg_calc puntual): {cv5['rmse_mean']:.4f}" if cv5["rmse_mean"] else "    CV5 fail")

        # LOYO inter-año
        print(f"  Corriendo LOYO inter-año sobre best...")
        loyo = loyo_inter_year(partidos, fset, a_best, t_best, alfa_ema, def_alfa)
        print(f"    LOYO mean RMSE: {loyo.get('_loyo_mean_rmse'):.4f}" if loyo.get('_loyo_mean_rmse') else "    LOYO fail")
        for y in TRAIN_YEARS:
            v = loyo.get(y, {})
            if v.get("rmse_test_year") is not None:
                print(f"      {y}: RMSE={v['rmse_test_year']:.4f} N={v['n_test_year']}")

        # Coefs aprendidos del best
        coefs_per_liga = {}
        for liga, m in mods_best.items():
            coefs_per_liga[liga] = {
                "intercept": m["intercept"],
                "coefs": dict(zip(fset, m["coefs"])),
                "n_train": m["n_train"],
            }

        resultados[fset_name] = {
            "alpha_best": a_best,
            "theta_best": t_best,
            "rmse_oos_pool": oos_best,
            "rmse_is_2026": is2026_best,
            "n_eventos_usados_full": r_best["rmse_resumen"].get("_n_eventos_usados"),
            "n_eventos_skipped_full": r_best["rmse_resumen"].get("_n_eventos_skipped"),
            "rmse_per_year": {y: r_best["rmse_resumen"].get(y, {}) for y in TRAIN_YEARS + HOLDOUT_YEARS},
            "cv5_temporal": cv5,
            "loyo_per_year": loyo,
            "coefs_per_liga": coefs_per_liga,
            "breaks_poisson_floor": bool(breaks_floor),
            "grid_full": {k: {
                "rmse_oos": v["rmse_resumen"]["OOS_pool"]["rmse"],
                "rmse_is_2026": v["rmse_resumen"]["IS_2026"]["rmse"],
                "dof_abort": v["dof_abort"],
            } for k, v in grid_results.items()},
        }

    # Compare best of best vs V5 baseline (RMSE OOS pool 1.1963 según baseline)
    V5_BASELINE = 1.1963
    if "F_simple" in resultados and "F_extended" in resultados:
        rmse_simple = resultados["F_simple"]["rmse_oos_pool"]
        rmse_extended = resultados["F_extended"]["rmse_oos_pool"]
        if rmse_simple <= rmse_extended:
            best_name = "F_simple"
            rmse_best_global = rmse_simple
        else:
            best_name = "F_extended"
            rmse_best_global = rmse_extended
        resultados["best_config"] = best_name
        resultados["comparison_vs_baseline_v5"] = {
            "v5_baseline_rmse": V5_BASELINE,
            "best_config": best_name,
            "best_rmse": rmse_best_global,
            "delta_rmse_oos": rmse_best_global - V5_BASELINE,
            "ratio": rmse_best_global / V5_BASELINE,
        }
        print(f"\n=== Comparacion vs V5 NNLS baseline ({V5_BASELINE:.4f}) ===")
        print(f"  F_simple   OOS: {rmse_simple:.4f}  delta={rmse_simple - V5_BASELINE:+.4f}")
        print(f"  F_extended OOS: {rmse_extended:.4f}  delta={rmse_extended - V5_BASELINE:+.4f}")
        print(f"  best_config: {best_name}")

    # Persistir
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(resultados, f, indent=2, default=str)
    print(f"\nGuardado {OUT_JSON}")


if __name__ == "__main__":
    main()

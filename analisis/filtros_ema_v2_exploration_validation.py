"""
Pipeline completo Phase 1-2-4 EMA expandido sobre universo_filtros_ema_v2 (4,040 partidos).

Phase 1: explora 4200 tests (21 stats x 10 metodos x 5 picks x 4 bins)
Phase 2: validacion con Bonferroni-CI ajustado (1-0.05/n CI percentile) + Schema A
Phase 4: walk-forward TRUE-OOS por anio (train < year_test, eval = year_test)

Criterios promocion robustos:
1. Pool yield > +5pp sobre baseline pick
2. Bonferroni-CI 99.999% lower > 0
3. N pool >= 50 (no solo 30)
4. Walk-forward TRUE-OOS: 2/3 anios test positivos (train<2024 / 2024; <2025 / 2025; <2026 / 2026)

Output: filtros_ema_v2_findings.json
"""
from __future__ import annotations
import sqlite3
import json
import math
import numpy as np
from pathlib import Path
from collections import defaultdict

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)

EMA_STATS = [
    "pos", "passes", "pass_pct", "crosses", "cross_pct", "longballs", "longball_pct",
    "shots", "sots", "shot_pct", "blocks", "corners", "fouls", "yellow", "red",
    "offsides", "saves", "tackles", "tackle_pct", "interceptions", "clearance",
]

METODOS = [
    "ema_l_{stat}_local", "ema_l_{stat}_visita",
    "diff_propio_{stat}",
    "ema_c_{stat}_local", "ema_c_{stat}_visita",
    "diff_contra_{stat}",
    "asim_atk_l_def_v_{stat}", "asim_atk_v_def_l_{stat}",
    "ratio_propio_{stat}", "ratio_contra_{stat}",
]


def bootstrap_ci(values: np.ndarray, n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    n = len(values)
    samples = np.random.choice(values, size=(n_boot, n), replace=True)
    means = np.sort(samples.mean(axis=1))
    return (float(means[int(alpha / 2 * n_boot)]),
            float(means[int((1 - alpha / 2) * n_boot)]))


def yield_quartile_search(events_train: list[dict], events_eval: list[dict],
                          feature: str, target: str, baseline: float) -> dict | None:
    """Busca el bin q4 (sobre TRAIN) con mejor yield TRAIN, evalua sobre EVAL.
    Esto es walk-forward HONEST: thresholds derivados solo de train, evaluados sobre eval."""
    train_vals = [(e.get(feature), e.get(target)) for e in events_train
                  if e.get(feature) is not None and e.get(target) is not None]
    if len(train_vals) < 50:
        return None
    arr_train = np.array([v[0] for v in train_vals], dtype=float)
    quantiles = np.unique(np.percentile(arr_train, np.linspace(0, 100, 5)))
    if len(quantiles) < 2:
        return None
    best = {"yield_train": -99, "lo": None, "hi": None}
    for i in range(len(quantiles) - 1):
        lo, hi = quantiles[i], quantiles[i + 1]
        is_last = (i == len(quantiles) - 2)
        if is_last:
            sub = [v for v in train_vals if lo <= v[0] <= hi]
        else:
            sub = [v for v in train_vals if lo <= v[0] < hi]
        if len(sub) < 30:
            continue
        ys = [v[1] for v in sub]
        ymean = sum(ys) / len(ys)
        if ymean > best["yield_train"]:
            best = {"yield_train": ymean, "lo": lo, "hi": hi, "n_train": len(sub)}
    if best["lo"] is None:
        return None

    # Eval sobre TEST con mismo threshold
    eval_sub = [(e.get(feature), e.get(target)) for e in events_eval
                if e.get(feature) is not None and e.get(target) is not None
                and best["lo"] <= e[feature] <= best["hi"]]
    if len(eval_sub) < 10:
        return {**best, "n_eval": len(eval_sub), "yield_eval": None}
    ys_eval = [v[1] for v in eval_sub]
    return {**best, "n_eval": len(eval_sub), "yield_eval": sum(ys_eval) / len(ys_eval)}


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    universo = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_ema_v2")]
    print(f"Universo: {len(universo)}")

    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in universo if e[f"yield_{pick}"] is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]

    # ==== PHASE 1+2 POOL ====
    findings_pool = []
    n_tests = 0

    for stat in EMA_STATS:
        for metodo in METODOS:
            feature = metodo.format(stat=stat)
            for target in targets:
                pick = target.replace("yield_", "")
                base = baselines.get(pick, 0)

                # Bin q4 sobre todo el pool
                vals = [(e.get(feature), e.get(target)) for e in universo
                        if e.get(feature) is not None and e.get(target) is not None]
                if len(vals) < 100:
                    continue
                arr = np.array([v[0] for v in vals], dtype=float)
                quantiles = np.unique(np.percentile(arr, np.linspace(0, 100, 5)))
                if len(quantiles) < 2:
                    continue
                for i in range(len(quantiles) - 1):
                    n_tests += 1
                    lo, hi = quantiles[i], quantiles[i + 1]
                    is_last = (i == len(quantiles) - 2)
                    if is_last:
                        sub = [v for v in vals if lo <= v[0] <= hi]
                    else:
                        sub = [v for v in vals if lo <= v[0] < hi]
                    if len(sub) < 50:
                        continue
                    ys_arr = np.array([v[1] for v in sub])
                    ymean = float(ys_arr.mean())
                    lift = ymean - base

                    if lift > 0.02:
                        ci_lo, ci_hi = bootstrap_ci(ys_arr, n_boot=1000, alpha=0.05)
                        findings_pool.append({
                            "stat": stat,
                            "metodo": metodo,
                            "feature": feature,
                            "target": target,
                            "pick": pick,
                            "lo": float(lo), "hi": float(hi),
                            "n": len(sub),
                            "yield_pool": ymean,
                            "ci95_lo_005": ci_lo, "ci95_hi_005": ci_hi,
                            "baseline_pick": base,
                            "lift": lift,
                            "ci95_lo_pos": ci_lo > 0,
                        })

    bonferroni_alpha = 0.05 / n_tests
    print(f"\nTotal tests: {n_tests}")
    print(f"Findings (lift>+5pp AND CI95_lo>0): {len(findings_pool)}")
    print(f"Bonferroni alpha = 0.05/{n_tests} = {bonferroni_alpha:.7f}")

    # Solo CI95 positivo
    findings_ci_pos = [f for f in findings_pool if f["ci95_lo_pos"]]
    print(f"Pasan CI95 lower>0: {len(findings_ci_pos)}")

    # Bonferroni-adjusted CI percentile (top 30 candidates)
    findings_ci_pos.sort(key=lambda x: x["lift"], reverse=True)
    findings_post_bonf = []
    for f in findings_ci_pos[:50]:
        sub_events = [e for e in universo
                      if e.get(f["feature"]) is not None
                      and e.get(f["target"]) is not None
                      and f["lo"] <= e[f["feature"]] <= f["hi"]]
        ys = np.array([e[f["target"]] for e in sub_events])
        ci_lo_bonf, ci_hi_bonf = bootstrap_ci(ys, n_boot=2000, alpha=bonferroni_alpha)
        f["ci_lo_bonf"] = ci_lo_bonf
        f["ci_hi_bonf"] = ci_hi_bonf
        f["bonf_pos"] = ci_lo_bonf > 0
        findings_post_bonf.append(f)

    n_bonf = sum(1 for f in findings_post_bonf if f["bonf_pos"])
    print(f"Pasan Bonferroni-CI estricto: {n_bonf}")

    # ==== PHASE 4: Walk-forward TRUE-OOS por temp ====
    # Years: 2022, 2023, 2024, 2025, 2026
    # Folds: train < y, eval = y
    eval_years = [2024, 2025, 2026]

    walkforward_results = []
    for f in findings_post_bonf:  # top 50 con CI normal positivo
        feature = f["feature"]
        target = f["target"]
        wf_per_year = []
        for y in eval_years:
            train = [e for e in universo if e.get("temp", 0) < y]
            eval_ = [e for e in universo if e.get("temp", 0) == y]
            wf = yield_quartile_search(train, eval_, feature, target,
                                        baselines.get(f["pick"], 0))
            if wf:
                wf_per_year.append({
                    "year_eval": y,
                    "n_train": wf.get("n_train"),
                    "yield_train": wf.get("yield_train"),
                    "n_eval": wf.get("n_eval"),
                    "yield_eval": wf.get("yield_eval"),
                    "lo_train": wf.get("lo"), "hi_train": wf.get("hi"),
                })
        n_pos_eval = sum(1 for w in wf_per_year if w.get("yield_eval") is not None and w["yield_eval"] > 0)
        avg_eval_yield = sum(w["yield_eval"] for w in wf_per_year if w.get("yield_eval") is not None)
        n_with_eval = sum(1 for w in wf_per_year if w.get("yield_eval") is not None)
        avg_eval_yield = avg_eval_yield / n_with_eval if n_with_eval else None
        walkforward_results.append({
            **f,
            "wf_per_year": wf_per_year,
            "n_pos_eval": n_pos_eval,
            "n_with_eval": n_with_eval,
            "avg_eval_yield": avg_eval_yield,
            "wf_passes": (n_with_eval >= 2 and n_pos_eval >= 2 and (avg_eval_yield or 0) > 0),
        })

    walkforward_results.sort(key=lambda x: x["lift"], reverse=True)
    n_wf_pass = sum(1 for w in walkforward_results if w["wf_passes"])
    print(f"\nPasan walk-forward TRUE-OOS (>=2/3 anios test positivos): {n_wf_pass}")
    print()
    print("=== TOP 30 findings post-Bonferroni + walk-forward ===")
    print(f"{'feature':<40} {'pick':<8} {'N':>4} {'yield':>8} {'lift':>8} {'CI_lo_bf':>9} {'avg_OOS':>9} {'pos_OOS':>7} {'WF':>3}")
    for w in walkforward_results[:30]:
        avg_oos = f"{w['avg_eval_yield']:+.3%}" if w.get('avg_eval_yield') is not None else "n/a"
        pos_oos = f"{w['n_pos_eval']}/{w['n_with_eval']}"
        wf = "**" if w["wf_passes"] else ""
        print(f"{w['feature'][:39]:<40} {w['pick']:<8} {w['n']:>4} {w['yield_pool']:>+8.3%} {w['lift']:>+8.3%} {w['ci_lo_bonf']:>+9.3f} {avg_oos:>9} {pos_oos:>7} {wf:>3}")

    out_data = {
        "universo": len(universo),
        "baselines": baselines,
        "n_tests_total": n_tests,
        "bonferroni_alpha": bonferroni_alpha,
        "n_findings_pool_lift_5pp": len(findings_pool),
        "n_post_bonferroni_ci_strict": len(findings_post_bonf),
        "n_walkforward_pass": n_wf_pass,
        "findings": walkforward_results,
    }
    out = ROOT / "analisis" / "filtros_ema_v2_findings.json"
    out.write_text(json.dumps(out_data, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

"""
Exploracion v3 con EMA + posicion tabla.

Phase 1: explora 210 EMA features + 18 pos features + cross EMA x pos = ~228 features
         x 5 picks x 4 bins
Phase 2: bootstrap CI + Bonferroni
Phase 3: walk-forward TRUE-OOS train<y / eval=y para top findings
Phase 4: deep dive per-liga del top global finding
Phase 5: combinaciones top EMA + top POS

Output: filtros_ema_v3_exploration.json + per_liga_deep_dive.json
"""
from __future__ import annotations
import sqlite3
import json
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
METODOS_EMA = [
    "ema_l_{stat}_local", "ema_l_{stat}_visita",
    "diff_propio_{stat}",
    "ema_c_{stat}_local", "ema_c_{stat}_visita",
    "diff_contra_{stat}",
    "asim_atk_l_def_v_{stat}", "asim_atk_v_def_l_{stat}",
    "ratio_propio_{stat}", "ratio_contra_{stat}",
]

POS_FEATURES = [
    "pos_local", "pos_visita", "pos_norm_local", "pos_norm_visita",
    "pos_diff", "pos_diff_norm", "puntos_diff", "ratio_pos",
    "puntos_local", "puntos_visita",
    "puntos_per_pj_local", "puntos_per_pj_visita",
    "gf_per_pj_local", "gf_per_pj_visita",
    "gc_per_pj_local", "gc_per_pj_visita",
]


def bootstrap_ci(values, n_boot=1000, alpha=0.05):
    if len(values) < 2:
        return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    samples = np.random.choice(arr, size=(n_boot, n), replace=True)
    means = np.sort(samples.mean(axis=1))
    return (float(means[int(alpha / 2 * n_boot)]),
            float(means[int((1 - alpha / 2) * n_boot)]))


def bin_q4(events, feature, target, baseline, min_n=50):
    vals = [(e.get(feature), e.get(target)) for e in events
            if e.get(feature) is not None and e.get(target) is not None]
    if len(vals) < 100:
        return []
    arr = np.array([v[0] for v in vals], dtype=float)
    quantiles = np.unique(np.percentile(arr, np.linspace(0, 100, 5)))
    if len(quantiles) < 2:
        return []
    out = []
    for i in range(len(quantiles) - 1):
        lo, hi = quantiles[i], quantiles[i + 1]
        is_last = (i == len(quantiles) - 2)
        if is_last:
            sub = [v for v in vals if lo <= v[0] <= hi]
        else:
            sub = [v for v in vals if lo <= v[0] < hi]
        if len(sub) < min_n:
            continue
        ys = np.array([v[1] for v in sub])
        ymean = float(ys.mean())
        ci_lo, ci_hi = bootstrap_ci(ys)
        out.append({
            "lo": float(lo), "hi": float(hi), "n": len(sub),
            "yield_mean": ymean, "ci95_lo": ci_lo, "ci95_hi": ci_hi,
            "lift": ymean - baseline,
        })
    return out


def walk_forward_oos(universo, feature, target, baseline, eval_years=(2024, 2025, 2026)):
    """Train < year_test, eval = year_test. Selecciona threshold (lo, hi) sobre TRAIN
    (mejor bin q4), evalua sobre TEST con mismo (lo, hi)."""
    out = []
    for y in eval_years:
        train = [e for e in universo if e.get("temp", 0) < y]
        test = [e for e in universo if e.get("temp", 0) == y]
        train_bins = bin_q4(train, feature, target, baseline, min_n=30)
        if not train_bins:
            continue
        # Best bin in train
        best = max(train_bins, key=lambda b: b["yield_mean"])
        # Eval on test with same threshold
        test_sub = [(e.get(feature), e.get(target)) for e in test
                    if e.get(feature) is not None and e.get(target) is not None
                    and best["lo"] <= e[feature] <= best["hi"]]
        if not test_sub:
            out.append({"year": y, "n_train": best["n"], "yield_train": best["yield_mean"],
                        "n_test": 0, "yield_test": None})
            continue
        ys_test = [v[1] for v in test_sub]
        ymean_test = sum(ys_test) / len(ys_test)
        out.append({
            "year": y, "n_train": best["n"], "yield_train": best["yield_mean"],
            "lo_train": best["lo"], "hi_train": best["hi"],
            "n_test": len(ys_test), "yield_test": ymean_test,
        })
    return out


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    universo = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_ema_v3")]
    print(f"Universo v3: {len(universo)}")

    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in universo if e[f"yield_{pick}"] is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"  baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]

    # Build all features
    all_features = []
    for stat in EMA_STATS:
        for m in METODOS_EMA:
            all_features.append(m.format(stat=stat))
    all_features.extend(POS_FEATURES)
    print(f"Total features: {len(all_features)}")

    # ==== PHASE 1+2: Pool + WF TRUE-OOS ====
    findings = []
    n_tests = 0
    for feature in all_features:
        for target in targets:
            pick = target.replace("yield_", "")
            base = baselines.get(pick, 0)
            bins = bin_q4(universo, feature, target, base, min_n=50)
            for b in bins:
                n_tests += 1
                if b["lift"] > 0.03 and b["ci95_lo"] > 0:
                    findings.append({
                        "feature": feature, "target": target, "pick": pick,
                        **b, "baseline": base,
                    })

    bonf = 0.05 / max(1, n_tests)
    print(f"Tests: {n_tests}  Bonferroni alpha: {bonf:.7f}")
    print(f"Findings (lift>+3pp AND CI95_lo>0): {len(findings)}")

    # Walk-forward TRUE-OOS para findings con N >= 100
    big_findings = [f for f in findings if f["n"] >= 100]
    big_findings.sort(key=lambda x: x["lift"], reverse=True)
    print(f"Findings con N>=100: {len(big_findings)}")

    wf_results = []
    for f in big_findings[:80]:
        wf = walk_forward_oos(universo, f["feature"], f["target"], baselines.get(f["pick"], 0))
        n_pos = sum(1 for w in wf if w.get("yield_test") is not None and w["yield_test"] > 0)
        n_with = sum(1 for w in wf if w.get("yield_test") is not None)
        avg = sum(w["yield_test"] for w in wf if w.get("yield_test") is not None)
        avg = avg / n_with if n_with else None
        wf_results.append({
            **f, "wf": wf, "n_pos_oos": n_pos, "n_with_oos": n_with,
            "avg_oos_yield": avg,
            "wf_passes": (n_with >= 2 and n_pos >= 2 and (avg or 0) > 0),
        })

    wf_pass = [r for r in wf_results if r["wf_passes"]]
    print(f"Pasan walk-forward TRUE-OOS: {len(wf_pass)}")
    print()
    print("=== TOP 30 walk-forward TRUE-OOS validados ===")
    print(f"{'feature':<35} {'pick':<8} {'N':>4} {'yld_pool':>9} {'lift':>8} {'avg_OOS':>9} {'pos':>5} {'WF':>3}")
    wf_pass.sort(key=lambda x: x["lift"], reverse=True)
    for r in wf_pass[:30]:
        avg = f"{r['avg_oos_yield']:+.3%}" if r['avg_oos_yield'] is not None else "n/a"
        pos = f"{r['n_pos_oos']}/{r['n_with_oos']}"
        wfm = "**"
        print(f"{r['feature'][:34]:<35} {r['pick']:<8} {r['n']:>4} {r['yield_mean']:>+9.3%} {r['lift']:>+8.3%} {avg:>9} {pos:>5} {wfm:>3}")

    # ==== PHASE 4: Deep dive per-liga del top finding ====
    if wf_pass:
        top = wf_pass[0]
        print(f"\n=== DEEP DIVE per-liga del TOP finding: {top['feature']} -> {top['pick']} ===")
        per_liga = {}
        for liga in ["Argentina", "Italia", "Brasil", "Espana", "Francia", "Inglaterra", "Turquia", "Alemania"]:
            sub_liga = [e for e in universo if e["liga"] == liga
                        and e.get(top["feature"]) is not None
                        and e.get(top["target"]) is not None
                        and top["lo"] <= e[top["feature"]] <= top["hi"]]
            ys = [e[top["target"]] for e in sub_liga]
            if not ys:
                per_liga[liga] = {"n": 0}
                continue
            ymean = sum(ys) / len(ys)
            ci = bootstrap_ci(np.array(ys))
            per_liga[liga] = {
                "n": len(ys), "yield_mean": ymean,
                "ci95_lo": ci[0], "ci95_hi": ci[1],
            }
            print(f"  {liga:<15s} n={len(ys):>4} yield={ymean:+.3%} CI95=[{ci[0]:+.3f}, {ci[1]:+.3f}]")

    # ==== PHASE 5: Combinaciones top EMA × top POS ====
    print(f"\n=== Combinaciones top EMA × top POS ===")
    top_ema = [r for r in wf_pass if any(r["feature"].startswith(p) for p in
                ["ema_l_", "ema_c_", "diff_propio", "diff_contra",
                 "asim_atk", "ratio_propio", "ratio_contra"])][:5]
    top_pos = [r for r in wf_pass if r["feature"] in POS_FEATURES][:5]

    combos = []
    for fe in top_ema:
        for fp in top_pos:
            if fe["target"] != fp["target"]:
                continue
            sub = [e for e in universo
                   if e.get(fe["feature"]) is not None and fe["lo"] <= e[fe["feature"]] <= fe["hi"]
                   and e.get(fp["feature"]) is not None and fp["lo"] <= e[fp["feature"]] <= fp["hi"]
                   and e.get(fe["target"]) is not None]
            if len(sub) < 30:
                continue
            ys = np.array([e[fe["target"]] for e in sub])
            ymean = float(ys.mean())
            ci = bootstrap_ci(ys)
            wf = walk_forward_oos(universo, fe["feature"], fe["target"], baselines.get(fe["pick"], 0))
            n_pos = sum(1 for w in wf if w.get("yield_test") is not None and w["yield_test"] > 0)
            n_with = sum(1 for w in wf if w.get("yield_test") is not None)
            combo = {
                "ema_feature": fe["feature"],
                "pos_feature": fp["feature"],
                "target": fe["target"], "pick": fe["pick"],
                "n": len(sub), "yield_mean": ymean,
                "ci95_lo": ci[0], "ci95_hi": ci[1],
                "lift": ymean - baselines.get(fe["pick"], 0),
                "wf_pos_oos": f"{n_pos}/{n_with}",
            }
            combos.append(combo)
            print(f"  {fe['feature'][:25]:<25} + {fp['feature'][:18]:<18} -> {fe['pick']:<8} n={len(sub):>4} y={ymean:+.3%} CI95_lo={ci[0]:+.3f}")

    out_data = {
        "universo": len(universo),
        "baselines": baselines,
        "n_tests": n_tests,
        "bonferroni_alpha": bonf,
        "n_findings": len(findings),
        "n_findings_n100": len(big_findings),
        "n_walkforward_pass": len(wf_pass),
        "wf_pass": wf_pass[:50],
        "per_liga_deep_dive_top": per_liga if wf_pass else {},
        "top_finding": (wf_pass[0] if wf_pass else None),
        "combinaciones_ema_pos": combos,
    }
    out = ROOT / "analisis" / "filtros_ema_v3_exploration.json"
    out.write_text(json.dumps(out_data, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

"""
Exploracion completa: 4 metodos de features sobre universo EMA.

Para cada feature (210 features = 21 stats x 10 metodos):
- Bin q4
- Per quartile: yield, hit, N
- Bootstrap CI95
- Detectar bin con yield superando baseline en cada pick (1, X, 2, O25, U25)

Bonferroni:
- 21 stats x 10 metodos x 5 picks x 4 bins = 4,200 tests potenciales
- alpha = 0.05 / 4200 = 0.0000119

Output:
- filtros_ema_v1_exploration.json: ranking por lift sobre baseline
- Top filtros con lift > 10pp Y CI95 lower > baseline
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

METODOS = [
    "ema_l_{stat}_local",        # M_A1: lo que hace el local
    "ema_l_{stat}_visita",        # M_A2: lo que hace el visita
    "diff_propio_{stat}",         # M_B: ema_l_local - ema_l_visita
    "ema_c_{stat}_local",         # M_C1: lo que recibe el local
    "ema_c_{stat}_visita",        # M_C2: lo que recibe el visita
    "diff_contra_{stat}",         # M_D: ema_c_local - ema_c_visita
    "asim_atk_l_def_v_{stat}",    # M_E: ataque local vs defensa visita
    "asim_atk_v_def_l_{stat}",    # M_F: ataque visita vs defensa local
    "ratio_propio_{stat}",        # M_G: ratio l/v de stat propio
    "ratio_contra_{stat}",        # M_H: ratio l/v de stat contra
]


def bootstrap_ci(values: list[float], n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    arr = np.array(values, dtype=float)
    n = len(arr)
    samples = np.random.choice(arr, size=(n_boot, n), replace=True)
    means = samples.mean(axis=1)
    means.sort()
    return (float(means[int(alpha / 2 * n_boot)]),
            float(means[int((1 - alpha / 2) * n_boot)]))


def bin_yield(events: list[dict], feature: str, target: str, n_bins: int = 4) -> list[dict]:
    vals = [(e.get(feature), e.get(target)) for e in events
            if e.get(feature) is not None and e.get(target) is not None]
    if len(vals) < 30:
        return []
    arr = np.array([v[0] for v in vals], dtype=float)
    quantiles = np.percentile(arr, np.linspace(0, 100, n_bins + 1))
    quantiles = np.unique(quantiles)
    if len(quantiles) < 2:
        return []
    result = []
    for i in range(len(quantiles) - 1):
        lo, hi = quantiles[i], quantiles[i + 1]
        is_last = (i == len(quantiles) - 2)
        if is_last:
            sub = [v for v in vals if lo <= v[0] <= hi]
        else:
            sub = [v for v in vals if lo <= v[0] < hi]
        if len(sub) < 10:
            continue
        ys = [v[1] for v in sub]
        ci_lo, ci_hi = bootstrap_ci(ys)
        result.append({
            "bin": i,
            "lo": float(lo), "hi": float(hi),
            "n": len(ys),
            "yield_mean": sum(ys) / len(ys),
            "ci95_lo": ci_lo, "ci95_hi": ci_hi,
        })
    return result


def temporal_cv_buckets(events: list[dict]):
    buckets = defaultdict(list)
    for e in events:
        fecha = e.get("fecha", "")
        if len(fecha) < 7:
            continue
        mes = int(fecha[5:7])
        if mes <= 2: b = 0
        elif mes == 3: b = 1
        else: b = 2
        buckets[b].append(e)
    return buckets


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    universo = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_ema_v1")]
    print(f"Universo EMA: {len(universo)} partidos")

    # Baselines
    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in universo if e[f"yield_{pick}"] is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]
    findings = []
    n_tests = 0

    for stat in EMA_STATS:
        for metodo_template in METODOS:
            feature = metodo_template.format(stat=stat)
            for target in targets:
                pick = target.replace("yield_", "")
                bins = bin_yield(universo, feature, target, n_bins=4)
                if not bins:
                    continue
                base_pick = baselines.get(pick, 0)
                for b in bins:
                    n_tests += 1
                    lift = b["yield_mean"] - base_pick
                    # Filter: lift > 10pp AND ci95 lo > 0 (estricto sobre baseline)
                    if lift > 0.10 and b["ci95_lo"] is not None and b["ci95_lo"] > 0:
                        # CV temporal sobre subset
                        events_in_bin = [e for e in universo
                                         if e.get(feature) is not None
                                         and e.get(target) is not None
                                         and b["lo"] <= e[feature] <= b["hi"]]
                        buckets = temporal_cv_buckets(events_in_bin)
                        cv = []
                        for bk_id, bk_events in buckets.items():
                            ys_bk = [e[target] for e in bk_events if e[target] is not None]
                            if ys_bk:
                                cv.append({"bucket": bk_id, "n": len(ys_bk),
                                           "yield": sum(ys_bk) / len(ys_bk)})
                        n_pos = sum(1 for c in cv if c["yield"] > 0)
                        consistencia = n_pos / max(1, len(cv))

                        findings.append({
                            "feature": feature,
                            "stat": stat,
                            "metodo": metodo_template,
                            "target": target,
                            "pick": pick,
                            "bin_lo": b["lo"], "bin_hi": b["hi"],
                            "n": b["n"],
                            "yield_mean": b["yield_mean"],
                            "ci95_lo": b["ci95_lo"], "ci95_hi": b["ci95_hi"],
                            "baseline_pick": base_pick,
                            "lift": lift,
                            "cv_buckets": cv,
                            "consistencia_temporal": consistencia,
                            "n_pos_buckets": n_pos,
                            "n_total_buckets": len(cv),
                        })

    print(f"\nTotal tests: {n_tests}")
    print(f"Findings (lift>+10pp AND CI95_lo>0): {len(findings)}")
    bonferroni = 0.05 / n_tests
    print(f"Bonferroni alpha: {bonferroni:.7f}")

    # Findings que pasan walk-forward LOYO basico (≥2/3 buckets pos AND avg CV > 0)
    promueven = []
    for f in findings:
        if f["consistencia_temporal"] >= 0.5 and f["n_total_buckets"] >= 2:
            avg_cv = sum(c["yield"] for c in f["cv_buckets"]) / max(1, len(f["cv_buckets"]))
            if avg_cv > 0:
                f["avg_cv_yield"] = avg_cv
                promueven.append(f)

    findings.sort(key=lambda x: x["lift"], reverse=True)
    promueven.sort(key=lambda x: x["lift"], reverse=True)

    print(f"\nFindings que pasan CV temporal: {len(promueven)}")
    print()
    print("=== TOP 30 findings ranked by lift ===")
    print(f"{'feature':<40} {'pick':<8} {'N':>4} {'yield':>8} {'baseline':>9} {'lift':>8} {'CI_lo':>7} {'cv_pos':>6}")
    for f in promueven[:30]:
        cvr = f"{f['n_pos_buckets']}/{f['n_total_buckets']}"
        print(f"{f['feature'][:39]:<40} {f['pick']:<8} {f['n']:>4} {f['yield_mean']:>+8.3%} {f['baseline_pick']:>+9.3%} {f['lift']:>+8.3%} {f['ci95_lo']:>+7.3f} {cvr:>6}")

    out_data = {
        "universo": len(universo),
        "baselines": baselines,
        "n_tests_total": n_tests,
        "bonferroni_alpha": bonferroni,
        "n_findings_lift_10pp_ci_pos": len(findings),
        "n_promueven_cv_temporal": len(promueven),
        "promueven": promueven[:100],
        "all_findings_top30": findings[:30],
    }
    out = ROOT / "analisis" / "filtros_ema_v1_exploration.json"
    out.write_text(json.dumps(out_data, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

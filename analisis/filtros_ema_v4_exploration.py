"""
Exploracion v4 sobre universo_filtros_ema_v4 (4,262 partidos, 11 ligas).

Reusa logica v3 pero amplia:
- Per-liga incluye COL, NOR, CHL (suma 3 ligas vs v3)
- Walk-forward TRUE-OOS train<y / eval=y
- Desglose top findings con TODAS las 11 ligas
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
LIGAS = ["Argentina", "Italia", "Brasil", "Espana", "Francia", "Inglaterra",
         "Turquia", "Alemania", "Colombia", "Noruega", "Chile"]
TEMPS = [2022, 2023, 2024, 2025, 2026]


def bootstrap_ci(values, n_boot=1000, alpha=0.05):
    if len(values) < 2: return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    samples = np.random.choice(arr, size=(n_boot, len(arr)), replace=True)
    means = np.sort(samples.mean(axis=1))
    return (float(means[int(alpha/2*n_boot)]), float(means[int((1-alpha/2)*n_boot)]))


def bin_q4(events, feature, target, baseline, min_n=50):
    vals = [(e.get(feature), e.get(target)) for e in events
            if e.get(feature) is not None and e.get(target) is not None]
    if len(vals) < 100: return []
    arr = np.array([v[0] for v in vals], dtype=float)
    quantiles = np.unique(np.percentile(arr, np.linspace(0, 100, 5)))
    if len(quantiles) < 2: return []
    out = []
    for i in range(len(quantiles)-1):
        lo, hi = quantiles[i], quantiles[i+1]
        is_last = (i == len(quantiles)-2)
        if is_last:
            sub = [v for v in vals if lo <= v[0] <= hi]
        else:
            sub = [v for v in vals if lo <= v[0] < hi]
        if len(sub) < min_n: continue
        ys = np.array([v[1] for v in sub])
        ymean = float(ys.mean())
        ci_lo, ci_hi = bootstrap_ci(ys)
        out.append({"lo": float(lo), "hi": float(hi), "n": len(sub),
                    "yield_mean": ymean, "ci95_lo": ci_lo, "ci95_hi": ci_hi,
                    "lift": ymean - baseline})
    return out


def walk_forward_oos(universo, feature, target, baseline, eval_years=(2024, 2025, 2026)):
    out = []
    for y in eval_years:
        train = [e for e in universo if e.get("temp", 0) < y]
        test = [e for e in universo if e.get("temp", 0) == y]
        bins = bin_q4(train, feature, target, baseline, min_n=30)
        if not bins:
            continue
        best = max(bins, key=lambda b: b["yield_mean"])
        sub = [(e.get(feature), e.get(target)) for e in test
               if e.get(feature) is not None and e.get(target) is not None
               and best["lo"] <= e[feature] <= best["hi"]]
        if not sub:
            out.append({"year": y, "n_train": best["n"], "yield_train": best["yield_mean"],
                        "n_test": 0, "yield_test": None})
            continue
        ys = [v[1] for v in sub]
        out.append({
            "year": y, "n_train": best["n"], "yield_train": best["yield_mean"],
            "lo_train": best["lo"], "hi_train": best["hi"],
            "n_test": len(ys), "yield_test": sum(ys)/len(ys),
        })
    return out


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    universo = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_ema_v4")]
    print(f"Universo v4: {len(universo)}")

    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in universo if e[f"yield_{pick}"] is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"  baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]

    all_features = []
    for stat in EMA_STATS:
        for m in METODOS_EMA:
            all_features.append(m.format(stat=stat))
    all_features.extend(POS_FEATURES)
    print(f"Features: {len(all_features)}")

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
                    findings.append({"feature": feature, "target": target, "pick": pick,
                                     **b, "baseline": base})

    bonf = 0.05 / max(1, n_tests)
    print(f"Tests: {n_tests} Bonferroni alpha: {bonf:.7f}")
    print(f"Findings: {len(findings)}")

    big_findings = [f for f in findings if f["n"] >= 100]
    big_findings.sort(key=lambda x: x["lift"], reverse=True)

    wf_results = []
    for f in big_findings[:80]:
        wf = walk_forward_oos(universo, f["feature"], f["target"], baselines.get(f["pick"], 0))
        n_pos = sum(1 for w in wf if w.get("yield_test") is not None and w["yield_test"] > 0)
        n_with = sum(1 for w in wf if w.get("yield_test") is not None)
        avg = (sum(w["yield_test"] for w in wf if w.get("yield_test") is not None) / n_with) if n_with else None
        wf_results.append({**f, "wf": wf, "n_pos_oos": n_pos, "n_with_oos": n_with,
                           "avg_oos_yield": avg,
                           "wf_passes": (n_with >= 2 and n_pos >= 2 and (avg or 0) > 0)})

    wf_pass = [r for r in wf_results if r["wf_passes"]]
    print(f"Pasan walk-forward TRUE-OOS: {len(wf_pass)}")
    print()
    print("=== TOP findings post walk-forward ===")
    print(f"{'feature':<35} {'pick':<8} {'N':>4} {'yield':>9} {'lift':>8} {'avg_OOS':>9} {'pos_OOS':>7}")
    for r in wf_pass[:30]:
        avg = f"{r['avg_oos_yield']:+.3%}" if r['avg_oos_yield'] is not None else "n/a"
        pos = f"{r['n_pos_oos']}/{r['n_with_oos']}"
        print(f"{r['feature'][:34]:<35} {r['pick']:<8} {r['n']:>4} {r['yield_mean']:>+9.3%} {r['lift']:>+8.3%} {avg:>9} {pos:>7}")

    # Desglose 11 ligas x 5 temps para top 6 wf_pass
    desglose = {}
    for f in wf_pass[:8]:
        feature = f["feature"]; target = f["target"]; lo, hi = f["lo"], f["hi"]
        finding_id = f"{feature}_{f['pick']}"
        matriz = {}
        for liga in LIGAS:
            row = {}
            for temp in TEMPS:
                sub = [e for e in universo
                       if e["liga"] == liga and e["temp"] == temp
                       and e.get(feature) is not None and e.get(target) is not None
                       and lo <= e[feature] <= hi]
                if sub:
                    ys = [e[target] for e in sub]
                    row[temp] = {"n": len(ys), "yield": sum(ys)/len(ys)}
                else:
                    row[temp] = {"n": 0, "yield": None}
            matriz[liga] = row

        total_per_liga = {}
        for liga in LIGAS:
            sub = [e for e in universo
                   if e["liga"] == liga and e.get(feature) is not None
                   and e.get(target) is not None and lo <= e[feature] <= hi]
            if sub:
                ys = [e[target] for e in sub]
                total_per_liga[liga] = {"n": len(ys), "yield": sum(ys)/len(ys)}
            else:
                total_per_liga[liga] = {"n": 0, "yield": None}

        total_per_temp = {}
        for temp in TEMPS:
            sub = [e for e in universo
                   if e["temp"] == temp and e.get(feature) is not None
                   and e.get(target) is not None and lo <= e[feature] <= hi]
            if sub:
                ys = [e[target] for e in sub]
                total_per_temp[temp] = {"n": len(ys), "yield": sum(ys)/len(ys)}
            else:
                total_per_temp[temp] = {"n": 0, "yield": None}

        desglose[finding_id] = {
            "feature": feature, "target": target, "pick": f["pick"],
            "lo": lo, "hi": hi, "n_pool": f["n"], "yield_pool": f["yield_mean"],
            "matriz": matriz, "total_per_liga": total_per_liga, "total_per_temp": total_per_temp,
        }

        print(f"\n=== DESGLOSE 11 LIGAS x 5 AÑOS: {finding_id} ===")
        print(f"Pool: yield {f['yield_mean']:+.3%} N={f['n']}")
        header = f"{'liga':<13}"
        for t in TEMPS:
            header += f"  {t:>4}"
        header += f"  {'Total':>9}"
        print(header)
        for liga in LIGAS:
            line = f"{liga:<13}"
            for t in TEMPS:
                cell = matriz[liga][t]
                if cell["n"] == 0:
                    line += f"  {'.':>4}"
                elif cell["n"] < 5:
                    line += f"  {'~' + str(cell['n']):>4}"
                else:
                    line += f"  {cell['yield']:+.0%}({cell['n']:>2})"
            tot = total_per_liga[liga]
            if tot["n"] == 0:
                line += f"  {'.':>9}"
            else:
                line += f"  {tot['yield']:+.0%}({tot['n']:>4})"
            print(line)
        line = f"{'Total':<13}"
        for t in TEMPS:
            cell = total_per_temp[t]
            if cell["n"] == 0:
                line += f"  {'.':>4}"
            else:
                line += f"  {cell['yield']:+.0%}({cell['n']:>2})"
        print(line)

    out = ROOT / "analisis" / "filtros_ema_v4_findings.json"
    out.write_text(json.dumps({
        "universo": len(universo),
        "baselines": baselines,
        "n_tests": n_tests,
        "bonferroni_alpha": bonf,
        "n_findings": len(findings),
        "n_walkforward_pass": len(wf_pass),
        "wf_pass": wf_pass[:30],
        "desglose_11ligas_5anios": desglose,
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

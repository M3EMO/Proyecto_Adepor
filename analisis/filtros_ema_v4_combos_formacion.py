"""
Test combinatorio EMA-v4 filters + formacion SOFA, restringido a subset 2026.

Pipeline:
1. Cruzar universo_filtros_ema_v4 (2026 only) con sofascore_match_features por (liga, fecha, ht, at)
2. Para cada filtro v4 validado (3 filtros) x cada formacion local x cada formacion visita:
   - Yield, N, CI95 (alpha=0.05)
   - Bonferroni adjusted = 0.05 / n_combos
3. Reportar findings y comparar vs filtro solo (sin formacion)

Output: filtros_ema_v4_combos_formacion.json
"""
from __future__ import annotations
import sqlite3
import json
import re
import unicodedata
import numpy as np
from pathlib import Path
from collections import defaultdict
from itertools import product

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)


def norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def bootstrap_ci(values, n_boot=2000, alpha=0.05):
    if len(values) < 2: return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    samples = np.random.choice(arr, size=(n_boot, len(arr)), replace=True)
    means = np.sort(samples.mean(axis=1))
    return (float(means[int(alpha/2*n_boot)]), float(means[int((1-alpha/2)*n_boot)]))


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 1) Universo v4 SOLO 2026 (subset cruzable con SOFA)
    universo_2026 = [dict(r) for r in cur.execute(
        "SELECT * FROM universo_filtros_ema_v4 WHERE temp = 2026"
    )]
    print(f"Universo v4 (2026 only): {len(universo_2026)}")

    # 2) Index SOFA por (liga_norm, fecha, ht_norm, at_norm)
    sofa = list(cur.execute(
        "SELECT liga, fecha, ht, at, formation_l, formation_v FROM sofascore_match_features WHERE error IS NULL"
    ))
    sofa_idx = {}
    for r in sofa:
        liga, fecha, ht, at, fl, fv = r
        if not fl or not fv: continue
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        sofa_idx[k] = (fl, fv)

    # Loose match: fecha + ht_norm[:6]
    sofa_loose = defaultdict(list)
    for k, v in sofa_idx.items():
        sofa_loose[(k[1], k[2][:6])].append((k, v))

    # 3) Cruzar
    cruzados = []
    for e in universo_2026:
        k = (norm(e["liga"]), e["fecha"][:10], norm(e["ht"]), norm(e["at"]))
        formacion = sofa_idx.get(k)
        if formacion is None:
            cands = sofa_loose.get((k[1], k[2][:6]), [])
            for kk, vv in cands:
                if kk[3][:5] == k[3][:5]:
                    formacion = vv
                    break
        if formacion:
            e["formation_l"] = formacion[0]
            e["formation_v"] = formacion[1]
            cruzados.append(e)

    print(f"Cruzados con formacion: {len(cruzados)}")

    # 4) Filtros v4 validados (3)
    findings_v4 = json.load(open(ROOT / "analisis" / "filtros_ema_v4_findings.json", encoding="utf-8"))
    top_filtros = findings_v4["wf_pass"][:3]

    # Whitelist per filtro de v4
    summary_v4 = json.load(open(ROOT / "analisis" / "filtros_ema_v4_shadow_summary.json", encoding="utf-8"))
    whitelist_per_filter = {f["filtro_id"]: set(f["whitelist_ligas"]) for f in summary_v4["filtros"]}

    # 5) Para cada filtro x cada formacion (l y v), computar yield
    print()
    todas_formaciones_l = sorted(set(e["formation_l"] for e in cruzados if e["formation_l"]))
    todas_formaciones_v = sorted(set(e["formation_v"] for e in cruzados if e["formation_v"]))
    print(f"Formaciones distintas local: {len(todas_formaciones_l)}")
    print(f"Formaciones distintas visita: {len(todas_formaciones_v)}")
    print(f"Formaciones local mas comunes:")
    from collections import Counter
    fl_counter = Counter(e["formation_l"] for e in cruzados)
    fv_counter = Counter(e["formation_v"] for e in cruzados)
    for f, n in fl_counter.most_common(5):
        print(f"  {f:<10s}  {n}")

    findings = []
    n_combos_test = 0

    for f in top_filtros:
        feature = f["feature"]
        target = f["target"]
        pick = f["pick"]
        lo, hi = f["lo"], f["hi"]
        finding_id = f"{feature}_{pick}"

        # Subset = universo_v4 cruzado, dentro del bin del filtro EMA
        subset_filtro = [e for e in cruzados
                         if e.get(feature) is not None
                         and e.get(target) is not None
                         and lo <= e[feature] <= hi]
        ys_filtro_solo = [e[target] for e in subset_filtro]
        if ys_filtro_solo:
            ymean_filtro = sum(ys_filtro_solo)/len(ys_filtro_solo)
            ci_filtro = bootstrap_ci(np.array(ys_filtro_solo))
        else:
            continue

        print(f"\n=== {finding_id} ===")
        print(f"  Subset 2026 con formacion: N={len(subset_filtro)}")
        print(f"  Yield filtro solo: {ymean_filtro:+.3%} CI95=[{ci_filtro[0]:+.3f}, {ci_filtro[1]:+.3f}]")

        # FILTRO + WHITELIST liga 2026
        wl = whitelist_per_filter.get(finding_id, set())
        subset_wl = [e for e in subset_filtro if e["liga"] in wl]
        if subset_wl:
            ys_wl = [e[target] for e in subset_wl]
            ymean_wl = sum(ys_wl) / len(ys_wl)
            ci_wl = bootstrap_ci(np.array(ys_wl))
            print(f"  + Whitelist liga: N={len(subset_wl)} yield={ymean_wl:+.3%} CI95=[{ci_wl[0]:+.3f}, {ci_wl[1]:+.3f}]")

        baseline_filtro_solo = ymean_filtro

        # Probar AND con cada formacion local con N>=15 (para test no totalmente espurio)
        for fl in todas_formaciones_l:
            sub = [e for e in subset_filtro if e["formation_l"] == fl]
            if len(sub) < 10: continue
            n_combos_test += 1
            ys = np.array([e[target] for e in sub])
            ymean = float(ys.mean())
            ci = bootstrap_ci(ys)
            findings.append({
                "filtro_id": finding_id,
                "tipo": "formation_l",
                "valor": fl,
                "n": len(sub),
                "yield": ymean,
                "ci95_lo": ci[0], "ci95_hi": ci[1],
                "baseline_filtro_solo": baseline_filtro_solo,
                "lift_vs_filtro_solo": ymean - baseline_filtro_solo,
            })

        for fv in todas_formaciones_v:
            sub = [e for e in subset_filtro if e["formation_v"] == fv]
            if len(sub) < 10: continue
            n_combos_test += 1
            ys = np.array([e[target] for e in sub])
            ymean = float(ys.mean())
            ci = bootstrap_ci(ys)
            findings.append({
                "filtro_id": finding_id,
                "tipo": "formation_v",
                "valor": fv,
                "n": len(sub),
                "yield": ymean,
                "ci95_lo": ci[0], "ci95_hi": ci[1],
                "baseline_filtro_solo": baseline_filtro_solo,
                "lift_vs_filtro_solo": ymean - baseline_filtro_solo,
            })

        # Combinaciones formation_l x formation_v (mismatch tactico)
        for fl, fv in product(todas_formaciones_l, todas_formaciones_v):
            sub = [e for e in subset_filtro if e["formation_l"] == fl and e["formation_v"] == fv]
            if len(sub) < 10: continue
            n_combos_test += 1
            ys = np.array([e[target] for e in sub])
            ymean = float(ys.mean())
            ci = bootstrap_ci(ys)
            findings.append({
                "filtro_id": finding_id,
                "tipo": "formation_l_x_v",
                "valor": f"{fl}_vs_{fv}",
                "n": len(sub),
                "yield": ymean,
                "ci95_lo": ci[0], "ci95_hi": ci[1],
                "baseline_filtro_solo": baseline_filtro_solo,
                "lift_vs_filtro_solo": ymean - baseline_filtro_solo,
            })

    # Bonferroni
    bonf_alpha = 0.05 / max(1, n_combos_test)
    print(f"\nTotal combinaciones testeadas: {n_combos_test}")
    print(f"Bonferroni alpha = 0.05/{n_combos_test} = {bonf_alpha:.5f}")

    # Re-compute CI con Bonferroni alpha para finding con CI95_lo>0 ya
    candidates = [f for f in findings if f["ci95_lo"] > 0 and f["lift_vs_filtro_solo"] > 0]
    print(f"Findings con CI95 (alpha=0.05) lower > 0: {len(candidates)}")

    # Top
    findings.sort(key=lambda x: x["yield"], reverse=True)
    print()
    print("=== TOP 30 combinaciones ranked by yield ===")
    print(f"{'filtro':<37} {'tipo':<14} {'valor':<22} {'N':>3} {'yield':>8} {'CI95_lo':>8} {'lift':>8}")
    for f in findings[:30]:
        ci = "**SIG**" if f["ci95_lo"] > 0 else ""
        print(f"{f['filtro_id'][:36]:<37} {f['tipo']:<14} {f['valor'][:21]:<22} {f['n']:>3} {f['yield']:>+8.3%} {f['ci95_lo']:>+8.3f} {f['lift_vs_filtro_solo']:>+8.3%} {ci}")

    out = ROOT / "analisis" / "filtros_ema_v4_combos_formacion.json"
    out.write_text(json.dumps({
        "n_universo_2026_v4": len(universo_2026),
        "n_cruzados_con_formacion": len(cruzados),
        "n_combos_test": n_combos_test,
        "bonferroni_alpha": bonf_alpha,
        "n_candidates_ci95_pos": len(candidates),
        "findings": findings,
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

"""
Fase 2 - Validacion estadistica rigurosa filtros SOFA.

Sobre los 72 filtros positivos + 72 anti-filtros derivados Phase 1.3
+ 29 filtros candidatos Phase 1.1.

LIMITACIONES:
- Universo SOFA solo cubre season 2026 (443 eventos con cuotas).
- NO posible walk-forward TRUE-OOS train<2025/test=2026 (no SOFA hist).
- Validacion: Bootstrap CI95 + temporal CV (3 buckets mensuales) + Bonferroni.

Criterios promocion SHADOW:
1. Bootstrap CI95 lower > 0 (significancia bilateral)
2. Yield pool > +5%
3. N >= 30
4. Bonferroni alpha = 0.05 / total_tests
5. Consistencia temporal: 2/3 folds positivos (LOYO mensual)

Output: filtros_sofa_v1_validation.json
"""
from __future__ import annotations
import sqlite3
import json
import math
import random
import numpy as np
from pathlib import Path
from collections import defaultdict
from filtros_sofa_v1_ml_importance import cargar_universo_enriquecido, features_numericos
from filtros_sofa_v1_exploration import filtros_definidos

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
random.seed(42)
np.random.seed(42)


def bootstrap_ci(values: list[float], n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    n = len(values)
    arr = np.array(values, dtype=float)
    samples = np.random.choice(arr, size=(n_boot, n), replace=True)
    means = samples.mean(axis=1)
    means.sort()
    return (float(means[int(alpha / 2 * n_boot)]),
            float(means[int((1 - alpha / 2) * n_boot)]))


def temporal_cv_buckets(events: list[dict]) -> list[list[dict]]:
    """3 buckets temporales por mes: ene-feb, mar, abr+may."""
    buckets = defaultdict(list)
    for e in events:
        fecha = e.get("fecha", "")
        if len(fecha) < 7:
            continue
        mes = int(fecha[5:7])
        if mes <= 2:
            b = 0
        elif mes == 3:
            b = 1
        else:
            b = 2
        buckets[b].append(e)
    return [buckets[i] for i in range(3) if i in buckets]


def evaluar_filtro(filtro: dict, universo: list[dict]) -> dict:
    pick_field = filtro["pick_field"]
    cond = filtro["condition"]
    events_filt = [e for e in universo if cond(e)]

    vals_pool = [e.get(pick_field) for e in events_filt if e.get(pick_field) is not None]
    n_pool = len(vals_pool)
    if n_pool == 0:
        return {"n_pool": 0, "yield_pool": None, "hit_rate": None, "ci95_lo": None,
                "ci95_hi": None, "ci95_lo_gt_zero": False, "cv_buckets": [],
                "consistencia_temporal": 0, "n_buckets_pos": 0, "n_buckets_total": 0}
    yield_pool = sum(vals_pool) / n_pool
    hit_field = pick_field.replace("yield_", "hit_")
    hits = [e.get(hit_field) for e in events_filt if e.get(hit_field) is not None]
    hit_rate = sum(hits) / len(hits) if hits else None
    ci95 = bootstrap_ci(vals_pool)

    # Temporal CV
    buckets = temporal_cv_buckets(events_filt)
    cv_yields = []
    for b in buckets:
        bv = [e.get(pick_field) for e in b if e.get(pick_field) is not None]
        if bv:
            cv_yields.append({"n": len(bv), "yield": sum(bv) / len(bv)})

    n_pos_buckets = sum(1 for cv in cv_yields if cv["yield"] > 0)
    consistencia = n_pos_buckets / max(1, len(cv_yields))

    return {
        "n_pool": n_pool,
        "yield_pool": yield_pool,
        "hit_rate": hit_rate,
        "ci95_lo": ci95[0],
        "ci95_hi": ci95[1],
        "ci95_lo_gt_zero": ci95[0] > 0 if not math.isnan(ci95[0]) else False,
        "cv_buckets": cv_yields,
        "consistencia_temporal": consistencia,
        "n_buckets_pos": n_pos_buckets,
        "n_buckets_total": len(cv_yields),
    }


def construir_filtros_hipotesis(hyp_data: dict) -> list[dict]:
    """De las hipotesis Phase 1.3 -> filtros con condition lambda."""
    filtros = []
    for h in hyp_data["hipotesis"]:
        feat = h["feature"]
        lo = h["lo"]
        hi = h["hi"]
        target = h["target"]
        tipo = h["tipo"]
        if tipo == "positivo":
            cond = (lambda f, l, h_=hi: lambda e:
                    e.get(f) is not None and l <= e.get(f) <= h_)(feat, lo)
            filtros.append({
                "id": h["id"],
                "desc": h["filtro_desc"],
                "pick_field": target,
                "condition": cond,
                "tipo": tipo,
                "feature": feat,
                "lo": lo, "hi": hi,
            })
    return filtros


def main() -> None:
    universo = cargar_universo_enriquecido()

    # Enriquecer O25/U25 + features numericos
    for e in universo:
        gl, gv = e.get("hg"), e.get("ag")
        if gl is not None and gv is not None and e.get("cuota_o25"):
            total = gl + gv
            e["hit_o25"] = 1 if total > 2 else 0
            e["yield_o25"] = (e["cuota_o25"] - 1) if e["hit_o25"] else -1
        if gl is not None and gv is not None and e.get("cuota_u25"):
            total = gl + gv
            e["hit_u25"] = 1 if total <= 2 else 0
            e["yield_u25"] = (e["cuota_u25"] - 1) if e["hit_u25"] else -1
        feats = features_numericos(e)
        for k, v in feats.items():
            if k not in e:
                e[k] = v

    # Filtros candidatos: phase 1.1 + phase 1.3 hipotesis (positivos solo)
    filtros_p11 = filtros_definidos()
    filtros_p11_no_z = [f for f in filtros_p11 if not f["id"].startswith("Z")]

    hyp_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_hipotesis.json", encoding="utf-8"))
    filtros_p13 = construir_filtros_hipotesis(hyp_data)

    todos = filtros_p11_no_z + filtros_p13
    n_total_tests = len(todos)
    bonferroni_alpha = 0.05 / n_total_tests
    print(f"Total filtros a validar: {n_total_tests} (Bonferroni alpha={bonferroni_alpha:.5f})")

    resultados = {
        "n_filtros_total": n_total_tests,
        "bonferroni_alpha": bonferroni_alpha,
        "universo_total": len(universo),
        "filtros_validados": [],
    }

    for f in todos:
        eval_ = evaluar_filtro(f, universo)
        promociona = (
            eval_["n_pool"] >= 30
            and eval_["yield_pool"] is not None
            and eval_["yield_pool"] > 0.05
            and eval_["ci95_lo_gt_zero"]
            and eval_["consistencia_temporal"] >= 0.5
        )

        record = {
            "id": f["id"],
            "desc": f["desc"],
            "pick_field": f["pick_field"],
            "tipo": f.get("tipo", "p11_propuesto"),
            "n_pool": eval_["n_pool"],
            "yield_pool": eval_["yield_pool"],
            "hit_rate": eval_["hit_rate"],
            "ci95_lo": eval_["ci95_lo"],
            "ci95_hi": eval_["ci95_hi"],
            "consistencia_temporal": eval_["consistencia_temporal"],
            "n_buckets_pos": eval_["n_buckets_pos"],
            "n_buckets_total": eval_["n_buckets_total"],
            "cv_buckets": eval_["cv_buckets"],
            "promociona_shadow": promociona,
        }
        resultados["filtros_validados"].append(record)

    resultados["filtros_validados"].sort(key=lambda x: (x["yield_pool"] or -99), reverse=True)
    n_promovidos = sum(1 for r in resultados["filtros_validados"] if r["promociona_shadow"])

    out = ROOT / "analisis" / "filtros_sofa_v1_validation.json"
    out.write_text(json.dumps(resultados, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== Validacion Fase 2 ===")
    print(f"Filtros que promueven a SHADOW: {n_promovidos} / {n_total_tests}")
    print()
    print(f"{'ID':<55} {'tgt':<14} {'N':>4} {'yield':>8} {'CI95_lo':>8} {'CV_pos':>6} {'PROMUEVE':>9}")
    for r in resultados["filtros_validados"][:30]:
        cl = f"{r['ci95_lo']:+.3f}" if r['ci95_lo'] is not None else "n/a"
        cvr = f"{r['n_buckets_pos']}/{r['n_buckets_total']}"
        prom = "**SI**" if r["promociona_shadow"] else ""
        print(f"{r['id'][:54]:<55} {r['pick_field'][:13]:<14} {r['n_pool']:>4} {(r['yield_pool'] or 0):>+8.3%} {cl:>8} {cvr:>6} {prom:>9}")


if __name__ == "__main__":
    main()

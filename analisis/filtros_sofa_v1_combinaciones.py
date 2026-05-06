"""
Fase 3 - Combinaciones top filtros + anti-filtros.

Estrategia:
- Top 10 filtros con yield_pool > +10% AND N>=50 (de Phase 2)
- Combinar AND, OR
- Combinar con anti-filtros estructurales (gap14, lunes, mes10/11, hora<14) — pero
  estos requieren feature gap_l/dow/hora que NO esta en SOFA. Skip.
- Test combinaciones contra subset apostado_v0 (121 picks).

Output: filtros_sofa_v1_combinaciones.json
"""
from __future__ import annotations
import json
import math
import numpy as np
from pathlib import Path
from itertools import combinations

from filtros_sofa_v1_ml_importance import cargar_universo_enriquecido, features_numericos
from filtros_sofa_v1_validation import construir_filtros_hipotesis, evaluar_filtro
from filtros_sofa_v1_exploration import filtros_definidos

ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)


def main() -> None:
    universo = cargar_universo_enriquecido()
    for e in universo:
        gl, gv = e.get("hg"), e.get("ag")
        if gl is not None and gv is not None and e.get("cuota_o25"):
            e["hit_o25"] = 1 if gl + gv > 2 else 0
            e["yield_o25"] = (e["cuota_o25"] - 1) if e["hit_o25"] else -1
        if gl is not None and gv is not None and e.get("cuota_u25"):
            e["hit_u25"] = 1 if gl + gv <= 2 else 0
            e["yield_u25"] = (e["cuota_u25"] - 1) if e["hit_u25"] else -1
        feats = features_numericos(e)
        for k, v in feats.items():
            if k not in e:
                e[k] = v

    val_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_validation.json", encoding="utf-8"))

    # Tomar top 10 filtros con yield_pool>+10% Y N>=50
    top_filtros = [r for r in val_data["filtros_validados"]
                   if r["yield_pool"] is not None and r["yield_pool"] > 0.10
                   and r["n_pool"] >= 50]
    top_filtros = top_filtros[:10]
    print(f"Top filtros candidatos a combinar: {len(top_filtros)}")

    hyp_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_hipotesis.json", encoding="utf-8"))
    filtros_p13 = construir_filtros_hipotesis(hyp_data)
    by_id = {f["id"]: f for f in filtros_p13}

    top_filtros_full = []
    for r in top_filtros:
        if r["id"] in by_id:
            top_filtros_full.append(by_id[r["id"]])

    # Solo combinar filtros del MISMO target (sumar AND no tiene sentido cross-target)
    by_target = {}
    for f in top_filtros_full:
        by_target.setdefault(f["pick_field"], []).append(f)

    combinaciones = []

    for target, filtros_t in by_target.items():
        if len(filtros_t) < 2:
            continue
        for f1, f2 in combinations(filtros_t, 2):
            # AND
            cond_and = (lambda c1, c2: lambda e: c1(e) and c2(e))(f1["condition"], f2["condition"])
            f_and = {
                "id": f"AND_{f1['id']}__{f2['id']}",
                "desc": f"({f1['desc']}) AND ({f2['desc']})",
                "pick_field": target,
                "condition": cond_and,
            }
            ev_and = evaluar_filtro(f_and, universo)

            # OR
            cond_or = (lambda c1, c2: lambda e: c1(e) or c2(e))(f1["condition"], f2["condition"])
            f_or = {
                "id": f"OR_{f1['id']}__{f2['id']}",
                "desc": f"({f1['desc']}) OR ({f2['desc']})",
                "pick_field": target,
                "condition": cond_or,
            }
            ev_or = evaluar_filtro(f_or, universo)

            combinaciones.append({
                "id": f_and["id"],
                "tipo": "AND",
                "desc": f_and["desc"],
                "pick_field": target,
                "n_pool": ev_and["n_pool"],
                "yield_pool": ev_and["yield_pool"],
                "ci95_lo": ev_and["ci95_lo"],
                "ci95_hi": ev_and["ci95_hi"],
                "consistencia_temporal": ev_and["consistencia_temporal"],
                "n_buckets_pos": ev_and["n_buckets_pos"],
                "n_buckets_total": ev_and["n_buckets_total"],
                "yield_f1": next((r["yield_pool"] for r in top_filtros if r["id"] == f1["id"]), None),
                "yield_f2": next((r["yield_pool"] for r in top_filtros if r["id"] == f2["id"]), None),
            })
            combinaciones.append({
                "id": f_or["id"],
                "tipo": "OR",
                "desc": f_or["desc"],
                "pick_field": target,
                "n_pool": ev_or["n_pool"],
                "yield_pool": ev_or["yield_pool"],
                "ci95_lo": ev_or["ci95_lo"],
                "ci95_hi": ev_or["ci95_hi"],
                "consistencia_temporal": ev_or["consistencia_temporal"],
                "n_buckets_pos": ev_or["n_buckets_pos"],
                "n_buckets_total": ev_or["n_buckets_total"],
                "yield_f1": next((r["yield_pool"] for r in top_filtros if r["id"] == f1["id"]), None),
                "yield_f2": next((r["yield_pool"] for r in top_filtros if r["id"] == f2["id"]), None),
            })

    combinaciones.sort(key=lambda x: x["yield_pool"] or -99, reverse=True)

    bonferroni_alpha = 0.05 / max(1, len(combinaciones))
    print(f"Combinaciones generadas: {len(combinaciones)}")
    print(f"Bonferroni alpha (combos): {bonferroni_alpha:.5f}")
    print()

    promueven = [c for c in combinaciones
                 if c["yield_pool"] is not None
                 and c["yield_pool"] > 0.10
                 and c["n_pool"] >= 30
                 and c["ci95_lo"] is not None and c["ci95_lo"] > 0
                 and c["consistencia_temporal"] >= 0.5]

    out = ROOT / "analisis" / "filtros_sofa_v1_combinaciones.json"
    payload = {
        "n_filtros_top": len(top_filtros),
        "n_combinaciones": len(combinaciones),
        "bonferroni_alpha": bonferroni_alpha,
        "promueven_a_shadow": len(promueven),
        "combinaciones": combinaciones[:50],
    }
    out.write_text(json.dumps(payload, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    print(f"Combinaciones que promueven: {len(promueven)} / {len(combinaciones)}")
    print()
    print("=== TOP 20 COMBINACIONES (yield_pool ranking) ===")
    print(f"{'tipo':<5} {'tgt':<13} {'N':>4} {'yield':>8} {'CI95_lo':>8} {'CV':>6} {'lift_f1':>8} {'lift_f2':>8} desc")
    for c in combinaciones[:20]:
        cl = f"{c['ci95_lo']:+.3f}" if c['ci95_lo'] is not None else "n/a"
        cvr = f"{c['n_buckets_pos']}/{c['n_buckets_total']}"
        lift1 = c["yield_f1"] or 0
        lift2 = c["yield_f2"] or 0
        print(f"{c['tipo']:<5} {c['pick_field']:<13} {c['n_pool']:>4} {(c['yield_pool'] or 0):>+8.3%} {cl:>8} {cvr:>6} {lift1:>+8.3%} {lift2:>+8.3%} {c['desc'][:80]}")


if __name__ == "__main__":
    main()

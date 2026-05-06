"""
Fase 4 - Walk-forward LOYO sobre buckets temporales.

LIMITACION CRITICA: solo season 2026 disponible. Buckets temporales:
- B0: ene-feb (~150 obs)
- B1: marzo (~150 obs)
- B2: abril+mayo (~150 obs)

Walk-forward LOYO con 3 buckets:
- Train B0+B1, test B2
- Train B0+B2, test B1
- Train B1+B2, test B0

Para cada combinacion top de Phase 3:
- Computar yield en cada bucket
- Avg yield walk-forward = media de los 3 yields test
- Reportar consistencia + bonferroni adicional

NOTA: 'Train' aqui no se usa para fit (los filtros estan ya definidos). LOYO mide
estabilidad temporal: ¿el yield del filtro en el bucket excluido se mantiene cuando
hubieramos elegido el filtro mirando solo a los otros 2 buckets?
"""
from __future__ import annotations
import json
import math
import numpy as np
from pathlib import Path
from collections import defaultdict

from filtros_sofa_v1_ml_importance import cargar_universo_enriquecido, features_numericos
from filtros_sofa_v1_validation import construir_filtros_hipotesis, evaluar_filtro
from filtros_sofa_v1_exploration import filtros_definidos

ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)


def bucket_idx(fecha: str) -> int | None:
    if len(fecha) < 7:
        return None
    mes = int(fecha[5:7])
    if mes <= 2:
        return 0
    if mes == 3:
        return 1
    return 2


def yield_pool(events: list[dict], pick_field: str) -> tuple[int, float | None]:
    vals = [e.get(pick_field) for e in events if e.get(pick_field) is not None]
    if not vals:
        return (0, None)
    return (len(vals), sum(vals) / len(vals))


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
        e["_bucket"] = bucket_idx(e.get("fecha", ""))

    # Cargar combinaciones top de Phase 3
    combos_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_combinaciones.json", encoding="utf-8"))
    combos = combos_data["combinaciones"]
    top_combos = [c for c in combos if c["yield_pool"] is not None
                  and c["yield_pool"] > 0.20 and c["n_pool"] >= 30][:15]

    # Cargar combos as filtros con condition
    hyp_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_hipotesis.json", encoding="utf-8"))
    filtros_p13 = construir_filtros_hipotesis(hyp_data)
    by_id = {f["id"]: f for f in filtros_p13}

    # Reconstruir condition de combinaciones (parse id)
    def reconstruir_combo(c):
        m_id = c["id"]
        tipo = c["tipo"]
        # Format: AND_F1__F2 or OR_F1__F2
        rest = m_id[len(tipo) + 1:]
        f1_id, f2_id = rest.split("__", 1)
        if f1_id not in by_id or f2_id not in by_id:
            return None
        f1, f2 = by_id[f1_id], by_id[f2_id]
        if tipo == "AND":
            cond = (lambda c1, c2: lambda e: c1(e) and c2(e))(f1["condition"], f2["condition"])
        else:
            cond = (lambda c1, c2: lambda e: c1(e) or c2(e))(f1["condition"], f2["condition"])
        return {"id": m_id, "desc": c["desc"], "pick_field": c["pick_field"],
                "condition": cond, "tipo": tipo}

    combos_full = [reconstruir_combo(c) for c in top_combos]
    combos_full = [c for c in combos_full if c is not None]

    resultados = {"combos_evaluados": []}

    for c in combos_full:
        events_filt = [e for e in universo if c["condition"](e)]

        # Por bucket
        per_bucket = defaultdict(list)
        for e in events_filt:
            b = e.get("_bucket")
            if b is None:
                continue
            v = e.get(c["pick_field"])
            if v is not None:
                per_bucket[b].append(v)

        bucket_metrics = {}
        for b, vs in per_bucket.items():
            bucket_metrics[b] = {"n": len(vs), "yield": sum(vs) / len(vs)}

        # LOYO: para cada bucket k = test, train = otros 2
        loyo = []
        all_buckets = sorted(per_bucket.keys())
        for k in all_buckets:
            train_buckets = [b for b in all_buckets if b != k]
            train_vals = []
            for b in train_buckets:
                train_vals.extend(per_bucket[b])
            test_vals = per_bucket[k]
            if not train_vals or not test_vals:
                continue
            train_yield = sum(train_vals) / len(train_vals)
            test_yield = sum(test_vals) / len(test_vals)
            loyo.append({
                "bucket_test": k,
                "n_train": len(train_vals),
                "n_test": len(test_vals),
                "yield_train": train_yield,
                "yield_test": test_yield,
            })

        avg_test_yield = sum(l["yield_test"] for l in loyo) / max(1, len(loyo))
        n_pos_test = sum(1 for l in loyo if l["yield_test"] > 0)

        resultados["combos_evaluados"].append({
            "id": c["id"],
            "desc": c["desc"],
            "pick_field": c["pick_field"],
            "tipo": c["tipo"],
            "n_pool": len(events_filt),
            "yield_pool": sum(e.get(c["pick_field"], 0) or 0 for e in events_filt
                              if e.get(c["pick_field"]) is not None) / max(1, sum(1 for e in events_filt
                                  if e.get(c["pick_field"]) is not None)),
            "buckets": bucket_metrics,
            "loyo": loyo,
            "avg_test_yield_loyo": avg_test_yield,
            "n_pos_test_loyo": n_pos_test,
            "n_total_loyo": len(loyo),
        })

    resultados["combos_evaluados"].sort(key=lambda x: x["avg_test_yield_loyo"], reverse=True)

    # Promueven walk-forward
    promueven_wf = [c for c in resultados["combos_evaluados"]
                    if c["avg_test_yield_loyo"] > 0.05
                    and c["n_total_loyo"] >= 2
                    and c["n_pos_test_loyo"] >= 2]
    resultados["promueven_walkforward"] = len(promueven_wf)
    resultados["promueven_walkforward_ids"] = [c["id"] for c in promueven_wf]

    out = ROOT / "analisis" / "filtros_sofa_v1_walkforward.json"
    out.write_text(json.dumps(resultados, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    print(f"=== Fase 4 — Walk-forward LOYO buckets temporales ===")
    print(f"Combos evaluados: {len(resultados['combos_evaluados'])}")
    print(f"Promueven walk-forward (avg yield_test > 5% AND >=2/3 buckets pos): {len(promueven_wf)}")
    print()
    print(f"{'ID':<70} {'tgt':<13} {'N':>4} {'Y_pool':>8} {'avg_LOYO':>9} {'pos':>6}")
    for c in resultados["combos_evaluados"]:
        cvr = f"{c['n_pos_test_loyo']}/{c['n_total_loyo']}"
        prom = " **WF**" if c in promueven_wf else ""
        print(f"{c['id'][:69]:<70} {c['pick_field'][:13]:<13} {c['n_pool']:>4} {c['yield_pool']:>+8.3%} {c['avg_test_yield_loyo']:>+9.3%} {cvr:>6}{prom}")


if __name__ == "__main__":
    main()

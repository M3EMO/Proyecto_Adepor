"""
Fase 1.3 - Derivar hipotesis testeables top-30 features.

Para cada feature top de Fase 1.2 (ML importance):
- Bin en quartiles (q1, q2, q3, q4)
- Computar yield_pool por bin
- Identificar threshold optimo (donde yield bin >> baseline)
- Derivar filtro testeable: "feature >= threshold AND pick = X -> yield positivo"

Output:
- JSON `filtros_sofa_v1_hipotesis.json` con filtros derivados
- Lista de filtros para Fase 2 validacion
"""
from __future__ import annotations
import sqlite3
import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from filtros_sofa_v1_ml_importance import cargar_universo_enriquecido, features_numericos

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def yield_per_bin(events: list[dict], feature: str, target: str, n_bins: int = 4) -> list[dict]:
    vals = [(e.get(feature), e.get(target)) for e in events
            if e.get(feature) is not None and e.get(target) is not None]
    if len(vals) < 20:
        return []
    arr = np.array([v[0] for v in vals], dtype=float)
    quantiles = np.percentile(arr, np.linspace(0, 100, n_bins + 1))
    quantiles = np.unique(quantiles)
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
        result.append({
            "bin": i,
            "lo": float(lo),
            "hi": float(hi),
            "n": len(ys),
            "yield_mean": sum(ys) / len(ys),
            "hit_rate": sum(1 for s in sub if s[1] > 0) / len(sub),
        })
    return result


def main() -> None:
    universo = cargar_universo_enriquecido()
    print(f"Universo: {len(universo)} eventos")

    # O25/U25 yields ya enriquecidos en cargar_universo_enriquecido (a través del cargar_o25)
    # Wait, no: cargar_universo_enriquecido NO los agrega. Verificar.
    # Veo que solo cargar_o25_yields lo hace. Lo replico.
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

    # Cargar features numericos en cada event (para acceder a feats derivados)
    for e in universo:
        feats = features_numericos(e)
        for k, v in feats.items():
            if k not in e:
                e[k] = v

    # Cargar ranking ML
    ml = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_ml_importance.json", encoding="utf-8"))

    resultados = {"hipotesis": []}

    for tgr in ml["targets"]:
        target = tgr["target"]
        baseline = sum(e.get(target, 0) or 0 for e in universo if e.get(target) is not None)
        baseline /= max(1, sum(1 for e in universo if e.get(target) is not None))

        feats_top = [f["feature"] for f in tgr["regression"]["importance"][:15]]
        for feat in feats_top:
            bins = yield_per_bin(universo, feat, target, n_bins=4)
            if not bins:
                continue
            best_bin = max(bins, key=lambda x: x["yield_mean"])
            worst_bin = min(bins, key=lambda x: x["yield_mean"])

            if best_bin["yield_mean"] > baseline + 0.05 and best_bin["n"] >= 30:
                # Hipotesis filtro positivo
                lo = best_bin["lo"]
                hi = best_bin["hi"]
                hyp_id = f"H_{target}_{feat}_pos"
                desc_filt = f"{feat} in [{lo:.3f}, {hi:.3f}] -> {target.replace('yield_','')}"
                resultados["hipotesis"].append({
                    "id": hyp_id,
                    "target": target,
                    "feature": feat,
                    "filtro_desc": desc_filt,
                    "lo": lo, "hi": hi,
                    "n_in_bin": best_bin["n"],
                    "yield_in_bin": best_bin["yield_mean"],
                    "hit_in_bin": best_bin["hit_rate"],
                    "baseline_target": baseline,
                    "lift": best_bin["yield_mean"] - baseline,
                    "tipo": "positivo",
                })
            if worst_bin["yield_mean"] < baseline - 0.05 and worst_bin["n"] >= 30:
                lo = worst_bin["lo"]
                hi = worst_bin["hi"]
                hyp_id = f"H_{target}_{feat}_neg"
                desc_filt = f"NOT ({feat} in [{lo:.3f}, {hi:.3f}]) -> evita {target.replace('yield_','')}"
                resultados["hipotesis"].append({
                    "id": hyp_id,
                    "target": target,
                    "feature": feat,
                    "filtro_desc": desc_filt,
                    "lo": lo, "hi": hi,
                    "n_in_bin": worst_bin["n"],
                    "yield_in_bin": worst_bin["yield_mean"],
                    "hit_in_bin": worst_bin["hit_rate"],
                    "baseline_target": baseline,
                    "lift": worst_bin["yield_mean"] - baseline,
                    "tipo": "anti",
                })

    # Sort: positivos por lift, antis por -lift
    resultados["hipotesis"].sort(key=lambda x: x["lift"], reverse=True)
    n_pos = sum(1 for h in resultados["hipotesis"] if h["tipo"] == "positivo")
    n_neg = sum(1 for h in resultados["hipotesis"] if h["tipo"] == "anti")

    out = ROOT / "analisis" / "filtros_sofa_v1_hipotesis.json"
    out.write_text(json.dumps(resultados, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    print(f"Hipotesis derivadas: {n_pos} positivos, {n_neg} anti-filtros")
    print()
    print("=== TOP 15 HIPOTESIS POSITIVAS (lift sobre baseline) ===")
    pos = [h for h in resultados["hipotesis"] if h["tipo"] == "positivo"]
    print(f"{'ID':<55} {'tgt':<14} {'N':>4} {'yield':>8} {'baseline':>9} {'lift':>8}")
    for h in pos[:15]:
        print(f"{h['id'][:54]:<55} {h['target'][:13]:<14} {h['n_in_bin']:>4} {h['yield_in_bin']:>+8.3%} {h['baseline_target']:>+9.3%} {h['lift']:>+8.3%}")
    print()
    print("=== TOP 15 ANTI-FILTROS (mas negativos) ===")
    neg = [h for h in resultados["hipotesis"] if h["tipo"] == "anti"]
    neg.sort(key=lambda x: x["lift"])
    print(f"{'ID':<55} {'tgt':<14} {'N':>4} {'yield':>8} {'baseline':>9} {'lift':>8}")
    for h in neg[:15]:
        print(f"{h['id'][:54]:<55} {h['target'][:13]:<14} {h['n_in_bin']:>4} {h['yield_in_bin']:>+8.3%} {h['baseline_target']:>+9.3%} {h['lift']:>+8.3%}")


if __name__ == "__main__":
    main()

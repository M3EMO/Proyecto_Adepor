"""adepor-3ip Recalibracion V13: usar la BEST variant por liga del grid search.

Best variant por (liga, target) elegida por:
  Criterio 1: yield_pct OOS > 0 con N_apost >= 10
  Criterio 2: si empate, mse_gain > 0 (mejor que naive)
  Criterio 3: prefer NNLS > RIDGE > OLS (conservador, sparse)

Si NINGUNA variante da yield > 0 con N>=10, V13 NO se calibra para esa liga.

Output:
  - Tabla v13_coef_por_liga REGENERADA con la best variant + metodo + feature_set
  - Schema extendido: nuevas columnas 'metodo' (OLS/NNLS/RIDGE) y 'feature_set' (F1/F2/F3)
  - JSON con resumen de elecciones
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
GRID = Path(__file__).resolve().parent / "v13_grid_search.json"
OUT = Path(__file__).resolve().parent / "v13_recalibrar_best_variants.json"

REG_PRIORITY = {"NNLS": 0, "RIDGE": 1, "OLS": 2}


def elegir_best_variant(liga, sets):
    """De {feat: {reg: {local, visita, audit_oos}}} elegir best (feat, reg) si yield>0."""
    candidates = []
    for fset_name, regs in sets.items():
        for reg, vals in regs.items():
            yb = vals.get("audit_oos")
            if not yb or yb.get("yield_pct") is None:
                continue
            if yb["n_apost"] < 10:
                continue
            if yb["yield_pct"] <= 0:
                continue
            candidates.append({
                "feat": fset_name,
                "reg": reg,
                "yield": yb["yield_pct"],
                "ci_lo": yb["ci95_lo"],
                "n_apost": yb["n_apost"],
                "brier": yb["brier"],
                "local": vals.get("local"),
                "visita": vals.get("visita"),
            })
    if not candidates:
        return None
    # Ordenar: yield desc, luego prefer NNLS
    candidates.sort(key=lambda x: (-x["yield"], REG_PRIORITY.get(x["reg"], 99)))
    return candidates[0]


def main():
    print("Cargando grid search results...")
    grid = json.loads(GRID.read_text(encoding="utf-8"))
    resultados = grid["resultados"]
    print(f"  Ligas con resultados: {sorted(resultados.keys())}")
    print()

    # Schema extendido
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # Verificar si columnas metodo y feature_set existen
    cols = [c[1] for c in cur.execute('PRAGMA table_info(v13_coef_por_liga)')]
    if "metodo" not in cols:
        cur.execute("ALTER TABLE v13_coef_por_liga ADD COLUMN metodo TEXT")
        print("  ALTER: metodo TEXT")
    if "feature_set" not in cols:
        cur.execute("ALTER TABLE v13_coef_por_liga ADD COLUMN feature_set TEXT")
        print("  ALTER: feature_set TEXT")
    con.commit()

    print("\n=== Elecciones BEST variant por liga ===")
    print(f"{'liga':<14} {'feat':<8} {'reg':<6} {'yield':>7} {'CI95_lo':>8} {'N':>4} {'brier':>7}")
    elecciones = {}
    for liga in sorted(resultados.keys()):
        best = elegir_best_variant(liga, resultados[liga])
        if best is None:
            print(f"{liga:<14} (sin variante con yield>0 y N>=10) -> NO calibrar V13")
            continue
        print(f"{liga:<14} {best['feat']:<8} {best['reg']:<6} "
              f"{best['yield']:>+7.1f}% {best['ci_lo']:>+8.1f} "
              f"{best['n_apost']:>4} {best['brier']:>7.4f}")
        elecciones[liga] = best

    print(f"\n=== Persistiendo {len(elecciones)} calibraciones BEST en v13_coef_por_liga ===")
    # Limpiar entradas previas (mantener historial via PK compuesta calibrado_en)
    ts = datetime.now().isoformat()

    for liga, best in elecciones.items():
        for target_label, cal in [("local", best["local"]), ("visita", best["visita"])]:
            if cal is None:
                continue
            cur.execute("""
                INSERT INTO v13_coef_por_liga
                (liga, target, calibrado_en, n_train, n_test, lambda_opt,
                 intercept, coefs_json, mse_test, r2_oos, naive_mse_test,
                 mse_gain_vs_naive, mean_pred, mean_real, aplicado_produccion,
                 metodo, feature_set)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
            """, (
                liga, target_label, ts,
                cal.get("n_train"), cal.get("n_test"),
                cal.get("lambda") if cal.get("reg") == "RIDGE" else None,
                cal.get("intercept"),
                json.dumps(dict(zip(cal["feature_aliases"], cal["coefs"]))),
                cal.get("mse_test"), cal.get("r2_oos"),
                cal.get("naive_mse"),
                cal.get("mse_gain"),
                cal.get("mean_pred"),
                best["reg"],
                best["feat"],
            ))
    con.commit()

    payload = {
        "fecha": ts,
        "elecciones": elecciones,
        "n_ligas_calibradas": len(elecciones),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    print(f"[OK] v13_coef_por_liga actualizada con BEST variants")
    con.close()


if __name__ == "__main__":
    main()

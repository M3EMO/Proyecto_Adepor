"""adepor-3ip Recalibracion V13 (post grid extended): BEST con F4/F5/F6.

Lee v13_grid_search_extended.json y persiste BEST por liga en v13_coef_por_liga.
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
GRID = Path(__file__).resolve().parent / "v13_grid_search_extended.json"
OUT = Path(__file__).resolve().parent / "v13_recalibrar_best_extended.json"


def main():
    grid = json.loads(GRID.read_text(encoding="utf-8"))
    best_by_liga = grid["best_by_liga"]
    print(f"BEST por liga (post extended grid):")
    for liga, b in best_by_liga.items():
        print(f"  {liga:<14} {b['feat']:<9} {b['reg']:<5} N={b['n_apost']:>3} "
              f"Yield={b['yield_pct']:>+6.1f}% Brier={b['brier']}")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    ts = datetime.now().isoformat()

    print(f"\nPersistiendo BEST en v13_coef_por_liga (timestamp {ts})...")
    for liga, b in best_by_liga.items():
        # Pull full calibration data del grid
        liga_data = grid["resultados"][liga][b["feat"]][b["reg"]]
        cal_l = liga_data.get("local")
        cal_v = liga_data.get("visita")
        for tgt, cal in [("local", cal_l), ("visita", cal_v)]:
            if not cal:
                continue
            coefs_dict = dict(zip(cal["feature_aliases"], cal["coefs"]))
            cur.execute("""
                INSERT INTO v13_coef_por_liga
                (liga, target, calibrado_en, n_train, n_test, lambda_opt,
                 intercept, coefs_json, mse_test, r2_oos, naive_mse_test,
                 mse_gain_vs_naive, mean_pred, mean_real, aplicado_produccion,
                 metodo, feature_set)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
            """, (
                liga, tgt, ts,
                cal.get("n_train"), cal.get("n_test"),
                cal.get("lambda") if b["reg"] == "RIDGE" else None,
                cal.get("intercept"),
                json.dumps(coefs_dict),
                cal.get("mse_test"), cal.get("r2_oos"),
                cal.get("naive_mse"),
                cal.get("mse_gain"),
                cal.get("mean_pred"),
                b["reg"],
                b["feat"],
            ))
            print(f"  {liga} {tgt}: {b['reg']} {b['feat']} R²={cal.get('r2_oos')}")
    con.commit()
    con.close()

    payload = {"fecha": ts, "best_by_liga": best_by_liga}
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

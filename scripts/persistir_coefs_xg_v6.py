"""Persiste coeficientes OLS xG V6 (SHADOW) en config_motor_valores.

Lee analisis/calibracion_xg_ols_por_liga.json (output de calibrar_xg_por_liga_ols.py)
e inserta 4 claves por scope (10 ligas + global pool):
    - beta_sot_v6_shadow
    - beta_off_v6_shadow
    - coef_corner_v6_shadow
    - intercept_v6_shadow

Estos coefs alimentan calcular_xg_v6() en motor_data.py para el SHADOW V6+V7.
NO afectan producción — uso exclusivo de la fórmula recalibrada en shadow.

Idempotente: usa INSERT OR REPLACE.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
JSON_OLS = ROOT / "analisis" / "calibracion_xg_ols_por_liga.json"
FUENTE = "OLS_2026-04-26_adepor-d7h"

KEYS = {
    "beta_sot": "beta_sot_v6_shadow",
    "beta_shots_off": "beta_off_v6_shadow",
    "coef_corner": "coef_corner_v6_shadow",
    "intercept": "intercept_v6_shadow",
}


def main():
    if not JSON_OLS.exists():
        sys.exit(f"[FATAL] No existe {JSON_OLS}. Correr analisis/calibrar_xg_por_liga_ols.py primero.")

    data = json.loads(JSON_OLS.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    cur = con.cursor()

    inserted = 0
    for liga, coefs in data.items():
        if "skip" in coefs:
            print(f"[SKIP] {liga}: {coefs.get('skip')}")
            continue
        scope = "global" if liga == "__pool__" else liga
        for json_key, db_key in KEYS.items():
            valor = float(coefs[json_key])
            cur.execute("""
                INSERT OR REPLACE INTO config_motor_valores
                    (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
                VALUES (?, ?, ?, NULL, 'real', ?, 0)
            """, (db_key, scope, valor, FUENTE))
            inserted += 1
            print(f"  [OK] {db_key:<25s} scope={scope:<13s} valor={valor:+.4f}")

    con.commit()
    con.close()
    print(f"\n[DONE] {inserted} filas insertadas/reemplazadas en config_motor_valores.")
    print(f"[FUENTE] {FUENTE}")


if __name__ == "__main__":
    main()

"""Inspecciona configuracion actual de margen_predictivo_1x2 por liga."""
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
con = sqlite3.connect(DB)
cur = con.cursor()

print("=== Tablas con 'config' ===")
for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%config%'"):
    print(f"  {r[0]}")

print()
print("=== Valores margen_predictivo_1x2 por scope (todas tablas config) ===")
for tabla in ["config_motor", "config_motor_valores", "configuracion"]:
    try:
        cur.execute(f"SELECT * FROM {tabla} WHERE clave LIKE 'margen_pred%' OR clave = 'margen_predictivo_1x2'")
        rows = cur.fetchall()
        if rows:
            cols = [d[0] for d in cur.description]
            print(f"\n--- {tabla} ---")
            print(f"  cols: {cols}")
            for r in rows:
                print(f"    {r}")
    except sqlite3.OperationalError:
        pass

print()
print("=== Get_param simulation: que scope retorna que valor ===")
ligas_test = ["Argentina", "Brasil", "Bolivia", "Chile", "Colombia", "Ecuador", "Peru",
              "Uruguay", "Venezuela", "Inglaterra", "Espana", "Italia", "Francia",
              "Alemania", "Turquia", "Noruega"]
for liga in ligas_test:
    valor = None
    for tabla in ["config_motor", "config_motor_valores"]:
        try:
            r = cur.execute(
                f"SELECT valor FROM {tabla} WHERE clave='margen_predictivo_1x2' AND scope=?",
                (liga,)
            ).fetchone()
            if r:
                valor = (tabla, float(r[0]))
                break
        except sqlite3.OperationalError:
            continue
    if valor:
        print(f"  {liga:<12} {valor[1]:.4f}  ({valor[0]})")
    else:
        # Fallback global
        for tabla in ["config_motor", "config_motor_valores"]:
            try:
                r = cur.execute(
                    f"SELECT valor FROM {tabla} WHERE clave='margen_predictivo_1x2' AND (scope IS NULL OR scope='')"
                ).fetchone()
                if r:
                    print(f"  {liga:<12} {float(r[0]):.4f}  ({tabla} GLOBAL fallback)")
                    break
            except sqlite3.OperationalError:
                continue
        else:
            print(f"  {liga:<12} (no value, hardcoded default 0.03)")

con.close()

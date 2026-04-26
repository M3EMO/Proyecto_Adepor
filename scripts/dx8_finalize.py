"""Finaliza PROPOSAL adepor-dx8: actualiza manifesto_sha256 + motor_filtros_activos."""
import hashlib
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
MANIFESTO = ROOT / "Reglas_IA.txt"

# 1. SHA256 nuevo
new_hash = hashlib.sha256(MANIFESTO.read_bytes()).hexdigest()
print(f"Nuevo manifesto_sha256: {new_hash}")

con = sqlite3.connect(DB)
cur = con.cursor()

# Old hash
old_row = cur.execute("SELECT valor FROM configuracion WHERE clave='manifesto_sha256'").fetchone()
old_hash = old_row[0] if old_row else None
print(f"Old hash:               {old_hash}")

# Update or insert
if old_hash:
    cur.execute(
        "UPDATE configuracion SET valor = ? WHERE clave = 'manifesto_sha256'",
        (new_hash,)
    )
else:
    cur.execute(
        "INSERT INTO configuracion (clave, valor) VALUES ('manifesto_sha256', ?)",
        (new_hash,)
    )
con.commit()
print(f"manifesto_sha256 actualizado.")

# 2. Update motor_filtros_activos
nueva_desc = (
    "Diferencia minima entre prob_top1 y prob_top2. Si margen < threshold, "
    "[PASAR]. V4.5 (2026-04-26 dx8): subido de 0.03 a 0.05 (FLOOR universal) "
    "con evidencia walk-forward N=4938. SHADOW MODE Opcion B activo: "
    "picks_shadow_margen_log loguea threshold_optimo_per_liga."
)
cur.execute(
    """UPDATE motor_filtros_activos
       SET default_global = 0.05, descripcion = ?, referencia_manifesto = 'II.E + IV.A V4.5'
       WHERE filtro = 'MARGEN_PREDICTIVO_1X2'""",
    (nueva_desc,)
)
print(f"motor_filtros_activos updated: {cur.rowcount} row")
con.commit()

# Verify
print("\n=== VERIFICACION ===")
r = cur.execute(
    "SELECT filtro, default_global, referencia_manifesto FROM motor_filtros_activos WHERE filtro='MARGEN_PREDICTIVO_1X2'"
).fetchone()
print(f"  Filtro: {r[0]}")
print(f"  Default: {r[1]}")
print(f"  Manifesto ref: {r[2]}")

r2 = cur.execute("SELECT valor FROM configuracion WHERE clave='manifesto_sha256'").fetchone()
print(f"  DB manifesto_sha256: {r2[0]}")
print(f"  Match? {r2[0] == new_hash}")

con.close()

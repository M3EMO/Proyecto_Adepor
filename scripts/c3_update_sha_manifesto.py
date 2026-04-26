"""C3 PROPOSAL adepor-u4z: actualiza manifesto_sha256 + motor_filtros_activos HG."""
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
new_hash = hashlib.sha256((ROOT / "Reglas_IA.txt").read_bytes()).hexdigest()

con = sqlite3.connect(ROOT / "fondo_quant.db")
cur = con.cursor()

old = cur.execute("SELECT valor FROM configuracion WHERE clave = 'manifesto_sha256'").fetchone()
print(f"Old hash: {old[0] if old else None}")
print(f"New hash: {new_hash}")
cur.execute("UPDATE configuracion SET valor = ? WHERE clave = 'manifesto_sha256'", (new_hash,))
con.commit()

# Update motor_filtros_activos HALLAZGO_G description con estado actualizado
nueva_desc_hg = (
    "Boost local cuando freq_local_real_liga > 0.5 con N>=50 (50% del gap). "
    "Estado 2026-04-26: ACTIVO en Argentina (N=79, freq=0.494) y Brasil (N=65, "
    "freq=0.539). Resto INACTIVO. §IV.H corregido en V4.6 (era 'INACTIVO para "
    "todas' pre-corrección por bead adepor-0ll)."
)
cur.execute(
    "UPDATE motor_filtros_activos SET descripcion = ?, referencia_manifesto = ? WHERE filtro = 'HALLAZGO_G'",
    (nueva_desc_hg, "II.E + IV.H V4.6")
)
con.commit()

# Verify
print()
r = cur.execute("SELECT valor FROM configuracion WHERE clave='manifesto_sha256'").fetchone()
print(f"DB hash post: {r[0]}")
print(f"Match? {r[0] == new_hash}")

r2 = cur.execute("SELECT filtro, descripcion FROM motor_filtros_activos WHERE filtro='HALLAZGO_G'").fetchone()
print()
print(f"motor_filtros_activos.{r2[0]} desc:")
print(f"  {r2[1]}")
con.close()

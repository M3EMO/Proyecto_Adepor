"""Aplica Opcion C de PROPOSAL adepor-dx8: FLOOR margen_predictivo_1x2 = 0.05.

CONDICIONES PRE-EJECUCION:
1. Tag MANIFESTO-CHANGE-APPROVED:bd-dx8 en task que invoca este script
2. Snapshot DB pre-cambio creado
3. Audit critico CONDICIONAL resuelto en COND-1 (este script ES la resolucion)
4. Documentado en bead adepor-dx8 (notes con SQL ejecutado)

USO:
  py scripts/proposal_dx8_aplicar_opcion_c.py --dry-run   # solo muestra
  py scripts/proposal_dx8_aplicar_opcion_c.py --apply     # ejecuta
"""
import argparse
import datetime
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
SNAPSHOTS = ROOT / "snapshots"
SNAPSHOTS.mkdir(exist_ok=True)

NUEVO_FLOOR = 0.05
FUENTE = f"adepor-dx8_walkforward_N4938_2026-04-26"


def snapshot_db():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = SNAPSHOTS / f"fondo_quant_{ts}_pre_dx8_opcion_c.db"
    src = sqlite3.connect(DB)
    dst_con = sqlite3.connect(dst)
    src.backup(dst_con)
    src.close()
    dst_con.close()
    h = hashlib.sha256(dst.read_bytes()).hexdigest()
    return dst, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("PROPOSAL adepor-dx8 — Opcion C: FLOOR margen_predictivo_1x2 = 0.05")
    print("=" * 70)

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Estado pre
    print("\n=== ESTADO PRE-CAMBIO ===")
    for r in cur.execute("""
        SELECT scope, valor_real, fuente FROM config_motor_valores
        WHERE clave='margen_predictivo_1x2' ORDER BY valor_real, scope
    """):
        print(f"  {r[0]:<14} = {r[1]:.4f}  ({r[2]})")

    # Filas que se modificarian
    rows_changes = cur.execute("""
        SELECT scope, valor_real FROM config_motor_valores
        WHERE clave='margen_predictivo_1x2' AND valor_real < ?
    """, (NUEVO_FLOOR,)).fetchall()
    n_changes = len(rows_changes)

    print(f"\n=== CAMBIOS A APLICAR ({n_changes} filas) ===")
    for scope, val in rows_changes:
        print(f"  {scope:<14}  {val:.3f} -> {NUEVO_FLOOR:.3f}")

    if not args.apply:
        print(f"\n[DRY RUN] Re-ejecutar con --apply para escribir cambios.")
        print(f"  REQUIERE: tag MANIFESTO-CHANGE-APPROVED:bd-dx8 en task previa")
        con.close()
        return

    # Snapshot
    print("\n=== CREANDO SNAPSHOT PRE-CAMBIO ===")
    snap_path, snap_hash = snapshot_db()
    print(f"  Snapshot: {snap_path}")
    print(f"  SHA256:   {snap_hash}")

    # Aplicar
    print("\n=== APLICANDO ===")
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_updated = 0
    for scope, val in rows_changes:
        cur.execute("""
            UPDATE config_motor_valores
            SET valor_real = ?, fuente = ?, fecha_actualizacion = ?
            WHERE clave = 'margen_predictivo_1x2' AND scope = ?
        """, (NUEVO_FLOOR, FUENTE, fecha, scope))
        n_updated += cur.rowcount
    con.commit()
    print(f"  {n_updated} filas actualizadas.")

    # Verificacion
    print("\n=== ESTADO POST-CAMBIO ===")
    for r in cur.execute("""
        SELECT scope, valor_real, fuente FROM config_motor_valores
        WHERE clave='margen_predictivo_1x2' ORDER BY valor_real, scope
    """):
        print(f"  {r[0]:<14} = {r[1]:.4f}  ({r[2]})")

    print(f"\n[OK] PROPOSAL adepor-dx8 Opcion C aplicada.")
    print(f"  Snapshot rollback: {snap_path}")
    print(f"  Para rollback: copiar snapshot sobre fondo_quant.db")
    con.close()


if __name__ == "__main__":
    main()

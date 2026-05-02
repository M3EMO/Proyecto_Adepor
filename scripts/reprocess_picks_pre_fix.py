"""
Reprocess partidos creados PRE-fix Layer 3 helpers (2026-04-28 19:00).

Estos partidos quedaron con probs V0 viejas y nunca pasaron por Layer 3 fixed.
Para forzar recálculo:
1. Snapshot DB.
2. UPDATE estado='Pendiente' para los partidos afectados.
3. Usuario ejecuta py ejecutar_proyecto.py → motor recalcula desde cero.

USO:
    py scripts/reprocess_picks_pre_fix.py            # dry-run
    py scripts/reprocess_picks_pre_fix.py --apply    # SNAPSHOT + UPDATE
"""
from __future__ import annotations
import sqlite3
import sys
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
APPLY = "--apply" in sys.argv
FECHA_FIX_LAYER3 = "2026-04-28 19:00"  # cuando se aplicó fix helpers


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # Identificar partidos afectados
    rows = cur.execute("""
        SELECT id_partido, fecha, pais, local, visita, estado, fecha_creacion,
               apuesta_1x2, prob_x
        FROM partidos_backtest
        WHERE fecha >= date('now')
          AND fecha_creacion < ?
          AND estado IN ('Pendiente', 'Calculado')
          AND pais IN ('Argentina', 'Italia', 'Inglaterra', 'Alemania')
    """, (FECHA_FIX_LAYER3,)).fetchall()
    print(f"Partidos pre-fix Layer 3 a reprocesar: {len(rows)}\n")

    print("Detalle:")
    print(f"  {'fecha':<17s} {'pais':<11s} {'local':<22s} {'visita':<22s} estado  P_V0(X)  pick")
    n_target = 0
    for r in rows:
        idp, fecha, pais, local, visita, estado, fc, ap, px = r
        pick = (ap or "").split(']')[1].strip().split()[0] if ap and ']' in ap else 'NONE'
        try:
            print(f"  {fecha:<17s} {pais:<11s} {local:<22s} {visita:<22s} {estado:<8s} {px:.3f}  {pick}")
        except UnicodeEncodeError:
            print(f"  {fecha} {pais} ?? est={estado} px={px}")
        n_target += 1

    if not APPLY:
        print(f"\nDRY-RUN. Para aplicar: --apply")
        print(f"Acción APPLY: UPDATE {n_target} partidos a estado='Pendiente'")
        return

    # SNAPSHOT
    ts = time.strftime("%Y%m%d_%H%M%S")
    snap = f"snapshots/fondo_quant_{ts}_pre_reprocess_pre_fix.db"
    Path(snap).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(DB, snap)
    print(f"\n[SNAPSHOT] {snap}")

    # UPDATE
    n = cur.execute("""
        UPDATE partidos_backtest
        SET estado = 'Pendiente'
        WHERE fecha >= date('now')
          AND fecha_creacion < ?
          AND estado IN ('Pendiente', 'Calculado')
          AND pais IN ('Argentina', 'Italia', 'Inglaterra', 'Alemania')
    """, (FECHA_FIX_LAYER3,)).rowcount
    conn.commit()
    print(f"[UPDATE] {n} partidos -> estado='Pendiente'")
    print(f"\nAhora ejecutar: py ejecutar_proyecto.py")
    print(f"Verificar después: SELECT COUNT(*) FROM picks_shadow_layer3_log WHERE fecha_partido >= date('now')")
    conn.close()


if __name__ == "__main__":
    main()

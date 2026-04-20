# ============================================================
# adepor_guard.py — Protección del backtest y entorno sombra
# ============================================================
# Comandos:
#   python adepor_guard.py snapshot          — Copia DB + métricas JSON
#   python adepor_guard.py compare           — Compara estado actual vs último snapshot
#   python adepor_guard.py compare <archivo> — Compara vs snapshot específico
#   python adepor_guard.py shadow            — Crea DB sombra para testear cambios
#   python adepor_guard.py restore <archivo> — Restaura DB desde snapshot
#   python adepor_guard.py status            — Lista todos los snapshots disponibles
#
# Filosofía:
#   Antes de cualquier cambio estructural (refactor, calibración, nuevo motor):
#     1. Correr "snapshot"  -> guarda el estado actual como baseline
#     2. Correr "shadow"    -> crea fondo_quant_shadow.db para probar en paralelo
#     3. Hacer los cambios sobre la shadow DB
#     4. Correr "compare"   -> verifica que el estado de producción no se rompió
#     5. Si todo OK -> los cambios se integran a la DB principal
# ============================================================

import sqlite3
import shutil
import json
import os
import sys
import glob
from datetime import datetime
from config_sistema import DB_NAME

SNAPSHOTS_DIR = "snapshots"
SHADOW_DB     = "fondo_quant_shadow.db"


# ============================================================
# Extractor de métricas
# ============================================================

def extraer_metricas(conn):
    """
    Extrae las métricas clave del estado actual de la DB.
    Estas métricas se guardan en el snapshot JSON y se usan
    para comparar antes/después de cualquier cambio.
    """
    c = conn.cursor()
    metricas = {}

    # --- 1. Estados del pipeline ---
    c.execute("SELECT estado, COUNT(*) FROM partidos_backtest GROUP BY estado")
    metricas["estados"] = dict(c.fetchall())

    # --- 2. Partidos liquidados por liga ---
    c.execute("""
        SELECT pais, COUNT(*) as n,
               SUM(CASE WHEN apuesta_1x2 != '' AND apuesta_1x2 IS NOT NULL
                        THEN stake_1x2 ELSE 0 END) as total_stake,
               SUM(CASE WHEN apuesta_1x2 != '' AND apuesta_1x2 IS NOT NULL
                        THEN 1 ELSE 0 END) as con_apuesta
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
        GROUP BY pais
    """)
    metricas["liquidados_por_liga"] = {
        r[0]: {"n": r[1], "total_stake": round(r[2] or 0, 2), "con_apuesta": r[3]}
        for r in c.fetchall()
    }

    # --- 3. rho por liga ---
    try:
        c.execute("SELECT liga, rho_calculado, total_partidos FROM ligas_stats")
        metricas["rho_por_liga"] = {
            r[0]: {"rho": r[1], "n_partidos": r[2]} for r in c.fetchall()
        }
    except Exception:
        metricas["rho_por_liga"] = {}

    # --- 4. EMA promedio por liga ---
    try:
        c.execute("""
            SELECT liga,
                   ROUND(AVG(ema_xg_favor_home), 4) as avg_fav_h,
                   ROUND(AVG(ema_xg_contra_home), 4) as avg_con_h,
                   ROUND(AVG(ema_xg_favor_away), 4) as avg_fav_a,
                   ROUND(AVG(ema_xg_contra_away), 4) as avg_con_a,
                   COUNT(*) as n_equipos
            FROM historial_equipos
            GROUP BY liga
        """)
        metricas["ema_por_liga"] = {
            r[0]: {"avg_fav_h": r[1], "avg_con_h": r[2],
                   "avg_fav_a": r[3], "avg_con_a": r[4], "n_equipos": r[5]}
            for r in c.fetchall()
        }
    except Exception:
        metricas["ema_por_liga"] = {}

    # --- 5. Últimas 10 apuestas con resultado ---
    c.execute("""
        SELECT fecha, pais, local, visita, apuesta_1x2, stake_1x2,
               goles_l, goles_v, apuesta_ou, stake_ou
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
        ORDER BY fecha DESC
        LIMIT 10
    """)
    metricas["ultimas_apuestas"] = [
        {"fecha": r[0], "pais": r[1], "partido": f"{r[2]} vs {r[3]}",
         "apuesta_1x2": r[4], "stake_1x2": r[5],
         "goles": f"{r[6]}-{r[7]}", "apuesta_ou": r[8], "stake_ou": r[9]}
        for r in c.fetchall()
    ]

    # --- 6. Totales globales ---
    total_liq = sum(v["n"] for v in metricas["liquidados_por_liga"].values())
    total_stake = sum(v["total_stake"] for v in metricas["liquidados_por_liga"].values())
    metricas["totales"] = {
        "total_liquidados": total_liq,
        "total_stake_apostado": round(total_stake, 2),
        "total_equipos_con_ema": sum(
            v["n_equipos"] for v in metricas["ema_por_liga"].values()
        ),
        "total_partidos_ema": metricas["estados"].get("Liquidado", 0)
                              + metricas["estados"].get("Calculado", 0)
                              + metricas["estados"].get("Finalizado", 0),
    }

    # --- 7. Integridad de datos ---
    c.execute("SELECT COUNT(*) FROM ema_procesados")
    metricas["integridad"] = {
        "ema_procesados": c.fetchone()[0],
        "estados_validos": all(
            k in ["Pendiente", "Calculado", "Finalizado", "Liquidado"]
            for k in metricas["estados"].keys()
        ),
    }

    return metricas


# ============================================================
# Comandos
# ============================================================

def cmd_snapshot():
    """Crea snapshot: backup de la DB + JSON de métricas."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Backup de la DB
    db_backup = os.path.join(SNAPSHOTS_DIR, f"fondo_quant_{ts}.db")
    shutil.copy2(DB_NAME, db_backup)

    # JSON de métricas
    conn = sqlite3.connect(DB_NAME)
    metricas = extraer_metricas(conn)
    conn.close()

    metricas["_meta"] = {
        "timestamp": ts,
        "db_backup": db_backup,
        "db_size_kb": round(os.path.getsize(db_backup) / 1024, 1),
    }

    json_path = os.path.join(SNAPSHOTS_DIR, f"metricas_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2, ensure_ascii=False)

    print(f"[SNAPSHOT OK]")
    print(f"  DB backup : {db_backup}  ({metricas['_meta']['db_size_kb']} KB)")
    print(f"  Métricas  : {json_path}")
    print(f"\n  Resumen estado actual:")
    for estado, n in metricas["estados"].items():
        print(f"    {estado:15s}: {n}")
    print(f"  Total liquidados    : {metricas['totales']['total_liquidados']}")
    print(f"  Total stake apostado: {metricas['totales']['total_stake_apostado']}")
    print(f"  Equipos con EMA     : {metricas['totales']['total_equipos_con_ema']}")
    return json_path


def cmd_compare(snapshot_path=None):
    """Compara estado actual vs un snapshot JSON."""
    if snapshot_path is None:
        # Último snapshot disponible
        jsons = sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, "metricas_*.json")))
        if not jsons:
            print("[ERROR] No hay snapshots. Corre 'snapshot' primero.")
            return
        snapshot_path = jsons[-1]

    print(f"[COMPARE] Comparando vs: {snapshot_path}\n")

    with open(snapshot_path, encoding="utf-8") as f:
        baseline = json.load(f)

    conn = sqlite3.connect(DB_NAME)
    actual = extraer_metricas(conn)
    conn.close()

    cambios = []

    # --- Comparar estados ---
    print("ESTADOS DEL PIPELINE:")
    for estado in ["Pendiente", "Calculado", "Finalizado", "Liquidado"]:
        b = baseline["estados"].get(estado, 0)
        a = actual["estados"].get(estado, 0)
        delta = a - b
        signo = f"+{delta}" if delta >= 0 else str(delta)
        marca = " [!]" if abs(delta) > 50 else ""
        print(f"  {estado:15s}: {b:4d} -> {a:4d}  ({signo}){marca}")
        if delta != 0:
            cambios.append(f"{estado}: {b}->{a}")

    # --- Comparar rho ---
    print("\nRHO POR LIGA:")
    b_rho = baseline.get("rho_por_liga", {})
    a_rho = actual.get("rho_por_liga", {})
    for liga in sorted(set(list(b_rho.keys()) + list(a_rho.keys()))):
        b_val = b_rho.get(liga, {}).get("rho", "—")
        a_val = a_rho.get(liga, {}).get("rho", "—")
        marca = " <- CAMBIÓ" if b_val != a_val else ""
        print(f"  {liga:15s}: {str(b_val):8s} -> {str(a_val):8s}{marca}")

    # --- Comparar EMA promedio ---
    print("\nEMA PROMEDIO FAV HOME POR LIGA:")
    b_ema = baseline.get("ema_por_liga", {})
    a_ema = actual.get("ema_por_liga", {})
    for liga in sorted(set(list(b_ema.keys()) + list(a_ema.keys()))):
        b_val = b_ema.get(liga, {}).get("avg_fav_h", "—")
        a_val = a_ema.get(liga, {}).get("avg_fav_h", "—")
        try:
            diff = abs(float(a_val) - float(b_val))
            marca = " [!] DRIFT > 0.05" if diff > 0.05 else ""
        except Exception:
            diff, marca = 0, ""
        print(f"  {liga:15s}: {str(b_val):8s} -> {str(a_val):8s}{marca}")

    # --- Resumen ---
    print("\n" + "="*50)
    if not cambios:
        print("[OK] Estado de producción INTACTO respecto al snapshot.")
    else:
        print(f"[INFO] Cambios detectados (esperados si el sistema corrió):")
        for c in cambios:
            print(f"  • {c}")
    print(f"\nSnapshot baseline: {baseline.get('_meta', {}).get('timestamp', '?')}")


def cmd_shadow():
    """
    Crea fondo_quant_shadow.db como copia exacta de la DB actual.
    Los motores pueden apuntar a esta DB para testear cambios
    sin tocar los datos de producción.
    """
    if os.path.exists(SHADOW_DB):
        ts_mod = datetime.fromtimestamp(os.path.getmtime(SHADOW_DB)).strftime("%Y-%m-%d %H:%M")
        resp = input(f"Ya existe {SHADOW_DB} (modificado {ts_mod}). ¿Sobreescribir? [s/N]: ")
        if resp.lower() != "s":
            print("Cancelado.")
            return

    shutil.copy2(DB_NAME, SHADOW_DB)
    size_kb = round(os.path.getsize(SHADOW_DB) / 1024, 1)

    print(f"[SHADOW OK] {SHADOW_DB} creada ({size_kb} KB)")
    print(f"\nPara testear cambios en los motores, cambia DB_NAME temporalmente:")
    print(f"  En config_sistema.py:  DB_NAME = '{SHADOW_DB}'")
    print(f"  O en cada motor:       conn = sqlite3.connect('{SHADOW_DB}')")
    print(f"\nCuando termines de validar, corre:")
    print(f"  python adepor_guard.py compare   # verifica que producción está intacta")


def cmd_restore(snapshot_path):
    """Restaura la DB desde un backup de snapshot."""
    if not os.path.exists(snapshot_path):
        print(f"[ERROR] No se encontró: {snapshot_path}")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Primero hacemos backup de la DB actual antes de restaurar
    safety = os.path.join(SNAPSHOTS_DIR, f"pre_restore_{ts}.db")
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    shutil.copy2(DB_NAME, safety)

    print(f"[SAFETY] DB actual guardada en: {safety}")

    resp = input(f"¿Restaurar {DB_NAME} desde {snapshot_path}? [s/N]: ")
    if resp.lower() != "s":
        print("Cancelado.")
        return

    shutil.copy2(snapshot_path, DB_NAME)
    size_kb = round(os.path.getsize(DB_NAME) / 1024, 1)
    print(f"[RESTORE OK] {DB_NAME} restaurada desde {snapshot_path} ({size_kb} KB)")


def cmd_status():
    """Lista todos los snapshots disponibles."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    jsons = sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, "metricas_*.json")), reverse=True)
    dbs   = sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, "fondo_quant_*.db")), reverse=True)

    if not jsons:
        print("[INFO] No hay snapshots. Corre 'snapshot' primero.")
        return

    print(f"{'TIMESTAMP':<20} {'DB BACKUP':<35} {'LIQUIDADOS':>10} {'STAKE':>12}")
    print("-" * 80)
    for jpath in jsons:
        try:
            with open(jpath, encoding="utf-8") as f:
                m = json.load(f)
            ts    = m.get("_meta", {}).get("timestamp", "?")
            db_bk = os.path.basename(m.get("_meta", {}).get("db_backup", "—"))
            liq   = m.get("totales", {}).get("total_liquidados", "?")
            stake = m.get("totales", {}).get("total_stake_apostado", "?")
            print(f"{ts:<20} {db_bk:<35} {str(liq):>10} {str(stake):>12}")
        except Exception:
            print(f"  {jpath} (no legible)")

    # DB sombra
    if os.path.exists(SHADOW_DB):
        ts_mod = datetime.fromtimestamp(os.path.getmtime(SHADOW_DB)).strftime("%Y-%m-%d %H:%M")
        size   = round(os.path.getsize(SHADOW_DB) / 1024, 1)
        print(f"\n[SHADOW] {SHADOW_DB}  ({size} KB, modificado: {ts_mod})")


# ============================================================
# Entry point
# ============================================================

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("\nUso: python adepor_guard.py <comando> [args]")
        print("Comandos: snapshot | compare [archivo] | shadow | restore <archivo> | status")
        return

    cmd = args[0].lower()

    if cmd == "snapshot":
        cmd_snapshot()
    elif cmd == "compare":
        path = args[1] if len(args) > 1 else None
        cmd_compare(path)
    elif cmd == "shadow":
        cmd_shadow()
    elif cmd == "restore":
        if len(args) < 2:
            print("[ERROR] Especificá el archivo de backup. Ej: restore snapshots/fondo_quant_20260409_120000.db")
        else:
            cmd_restore(args[1])
    elif cmd == "status":
        cmd_status()
    else:
        print(f"[ERROR] Comando desconocido: '{cmd}'")
        print("Comandos válidos: snapshot | compare | shadow | restore | status")


if __name__ == "__main__":
    main()

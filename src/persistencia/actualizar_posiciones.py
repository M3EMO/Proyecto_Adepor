"""src/persistencia/actualizar_posiciones.py — actualizador de posiciones_tabla_snapshot.

Hook llamado desde el pipeline (post-motor_data) para mantener la tabla
posiciones_tabla_snapshot al dia con los partidos liquidados nuevos.

Estrategia INCREMENTAL:
  1. Detectar grupos (liga, temp) que tienen partidos liquidados POSTERIORES al
     ultimo snapshot persistido (o que no tienen snapshots).
  2. Para cada grupo afectado, regenerar todos sus snapshots desde el primer
     partido pendiente hasta hoy (cronologico, sin look-ahead).
  3. Si no hay grupos afectados, skip (idempotente).

Argentina tiene 3 formatos paralelos (anual, apertura, clausura). Si un grupo
(liga=Argentina, temp=2026) tiene pendientes, regenera los 3 formatos.

Uso:
  from src.persistencia.actualizar_posiciones import actualizar_si_hay_nuevos
  resumen = actualizar_si_hay_nuevos()
  print(resumen)  # {'grupos_actualizados': 2, 'snapshots_persistidos': 234, ...}

Tambien ejecutable como script:
  py -m src.persistencia.actualizar_posiciones
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# [adepor-qqb fix 2026-04-28] Importar limpiar_texto para popular equipo_norm
# en cada INSERT — sin esto los snapshots nuevos no son lookable por helpers
# Layer 3 (_get_pos_local_forward usa WHERE equipo_norm = ?).
from src.comun.gestor_nombres import limpiar_texto

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB_DEFAULT = ROOT / "fondo_quant.db"

# Calendario de splits por liga (Argentina con 3 formatos paralelos)
ARGENTINA_SPLIT = {
    2022: {"apertura": ("2022-02-04", "2022-05-22"), "clausura": ("2022-06-05", "2022-10-25")},
    2023: {"apertura": ("2023-01-27", "2023-07-30"), "clausura": ("2023-08-04", "2023-12-04")},
    2024: {"apertura": ("2024-02-23", "2024-06-08"), "clausura": ("2024-07-19", "2024-12-08")},
    2025: {"apertura": ("2025-01-23", "2025-06-28"), "clausura": ("2025-07-12", "2025-12-14")},
    2026: {"apertura": ("2026-01-23", "2026-06-22"), "clausura": None},
}

LIGAS_FORMATOS = {
    "Argentina":  ["anual", "apertura", "clausura"],
    "Brasil":     ["anual"],
    "Noruega":    ["anual"],
    "Chile":      ["anual"],
    "Peru":       ["anual"],
    "Bolivia":    ["anual"],
    "Uruguay":    ["anual"],
    "Venezuela":  ["anual"],
    "Ecuador":    ["anual"],
    "Colombia":   ["apertura"],
    "Inglaterra": ["liga"],
    "Italia":     ["liga"],
    "Espana":     ["liga"],
    "Francia":    ["liga"],
    "Alemania":   ["liga"],
    "Turquia":    ["liga"],
}


def fecha_dentro_de(fecha_str, rango):
    if rango is None: return False
    return rango[0] <= fecha_str <= rango[1]


def determinar_formatos_partido(liga, temp, fecha_str):
    """Retorna lista de formatos en los que aplica este partido."""
    if liga == "Argentina":
        split = ARGENTINA_SPLIT.get(temp)
        if not split:
            return ["anual"]
        out = ["anual"]
        if fecha_dentro_de(fecha_str, split.get("apertura")):
            out.append("apertura")
        if fecha_dentro_de(fecha_str, split.get("clausura")):
            out.append("clausura")
        return out
    return LIGAS_FORMATOS.get(liga, ["anual"])


def crear_tabla_si_no_existe(con):
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS posiciones_tabla_snapshot (
            liga TEXT NOT NULL,
            temp INTEGER NOT NULL,
            formato TEXT NOT NULL,
            fecha_snapshot TEXT NOT NULL,
            equipo TEXT NOT NULL,
            posicion INTEGER,
            pj INTEGER,
            pg INTEGER,
            pe INTEGER,
            pp INTEGER,
            gf INTEGER,
            gc INTEGER,
            dif_gol INTEGER,
            puntos INTEGER,
            PRIMARY KEY (liga, temp, formato, fecha_snapshot, equipo)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pos_snapshot_lookup
        ON posiciones_tabla_snapshot(liga, temp, formato, equipo, fecha_snapshot DESC)
    """)
    con.commit()


def detectar_grupos_pendientes(con):
    """Identifica (liga, temp) con partidos liquidados POSTERIORES al MAX
    fecha_snapshot del grupo (o sin snapshots).

    Lee de DOS fuentes (UNION):
      - partidos_historico_externo (history 2022-2024)
      - partidos_backtest          (productivo 2026+)

    Retorna lista de tuples (liga, temp, fecha_min_pendiente).
    """
    cur = con.cursor()
    rows = cur.execute("""
        WITH partidos_unidos AS (
            SELECT phe.liga AS liga, phe.temp AS temp,
                   substr(phe.fecha, 1, 10) AS fecha
            FROM partidos_historico_externo phe
            WHERE phe.hg IS NOT NULL AND phe.ag IS NOT NULL
            UNION ALL
            SELECT pb.pais AS liga,
                   CAST(substr(pb.fecha, 1, 4) AS INTEGER) AS temp,
                   substr(pb.fecha, 1, 10) AS fecha
            FROM partidos_backtest pb
            WHERE pb.estado = 'Liquidado'
              AND pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
        )
        SELECT liga, temp, MIN(fecha) AS fecha_min_pendiente
        FROM partidos_unidos pu
        WHERE fecha > COALESCE(
                (SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
                 WHERE liga = pu.liga AND temp = pu.temp),
                '0000-00-00')
        GROUP BY liga, temp
    """).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def regenerar_grupo(con, liga, temp, fecha_inicio):
    """Regenerar TODOS los formatos del grupo (liga, temp) desde fecha_inicio
    hasta el ultimo partido. Borra snapshots existentes posteriores a
    fecha_inicio (exclusivo) y recalcula.
    """
    cur = con.cursor()
    formatos_grupo = LIGAS_FORMATOS.get(liga, ["anual"])
    if liga == "Argentina":
        formatos_grupo = ["anual", "apertura", "clausura"]

    # Borrar snapshots posteriores a fecha_inicio (NO inclusivo) para todos los formatos del grupo
    # Usamos < para preservar snapshot anterior al primer partido pendiente.
    placeholders = ",".join("?" * len(formatos_grupo))
    cur.execute(f"""
        DELETE FROM posiciones_tabla_snapshot
        WHERE liga = ? AND temp = ? AND formato IN ({placeholders})
          AND fecha_snapshot >= ?
    """, [liga, temp] + formatos_grupo + [fecha_inicio])

    # Cargar todos los partidos del grupo desde AMBAS fuentes (cronologico)
    partidos = cur.execute("""
        WITH partidos_unidos AS (
            SELECT phe.id AS id, substr(phe.fecha, 1, 10) AS fecha,
                   phe.ht AS ht, phe.at AS at, phe.hg AS hg, phe.ag AS ag
            FROM partidos_historico_externo phe
            WHERE phe.liga = ? AND phe.temp = ?
              AND phe.hg IS NOT NULL AND phe.ag IS NOT NULL
            UNION ALL
            SELECT pb.id_partido AS id, substr(pb.fecha, 1, 10) AS fecha,
                   pb.local AS ht, pb.visita AS at,
                   pb.goles_l AS hg, pb.goles_v AS ag
            FROM partidos_backtest pb
            WHERE pb.pais = ? AND CAST(substr(pb.fecha, 1, 4) AS INTEGER) = ?
              AND pb.estado = 'Liquidado'
              AND pb.goles_l IS NOT NULL AND pb.goles_v IS NOT NULL
        )
        SELECT id, fecha, ht, at, hg, ag FROM partidos_unidos
        ORDER BY fecha, id
    """, (liga, temp, liga, temp)).fetchall()
    if not partidos:
        return 0

    # Reconstruir estado acumulado por (formato, equipo) hasta JUSTO ANTES de fecha_inicio.
    # Para eso, leer partidos con fecha < fecha_inicio y acumular.
    estado = {fm: defaultdict(lambda: {"pj": 0, "pg": 0, "pe": 0, "pp": 0,
                                          "gf": 0, "gc": 0, "puntos": 0})
              for fm in formatos_grupo}
    partidos_pre = [p for p in partidos if p[1] < fecha_inicio]
    partidos_post = [p for p in partidos if p[1] >= fecha_inicio]

    for pid, fecha, ht, at, hg, ag in partidos_pre:
        formatos_p = determinar_formatos_partido(liga, temp, fecha)
        for fm in formatos_p:
            if fm not in estado: continue
            estado[fm][ht]["pj"] += 1; estado[fm][at]["pj"] += 1
            estado[fm][ht]["gf"] += hg; estado[fm][ht]["gc"] += ag
            estado[fm][at]["gf"] += ag; estado[fm][at]["gc"] += hg
            if hg > ag:
                estado[fm][ht]["pg"] += 1; estado[fm][ht]["puntos"] += 3
                estado[fm][at]["pp"] += 1
            elif hg == ag:
                estado[fm][ht]["pe"] += 1; estado[fm][ht]["puntos"] += 1
                estado[fm][at]["pe"] += 1; estado[fm][at]["puntos"] += 1
            else:
                estado[fm][at]["pg"] += 1; estado[fm][at]["puntos"] += 3
                estado[fm][ht]["pp"] += 1

    # Procesar partidos_post: snapshot ANTES de cada partido + actualizar estado
    snapshots_a_persistir = []  # (liga, temp, formato, fecha, equipo, stats)
    for pid, fecha, ht, at, hg, ag in partidos_post:
        formatos_p = determinar_formatos_partido(liga, temp, fecha)
        for fm in formatos_p:
            if fm not in estado: continue
            for eq in [ht, at]:
                s = estado[fm][eq]
                snapshots_a_persistir.append((
                    liga, temp, fm, fecha, eq,
                    s["pj"], s["pg"], s["pe"], s["pp"],
                    s["gf"], s["gc"], s["gf"] - s["gc"], s["puntos"],
                ))
            # Update estado
            estado[fm][ht]["pj"] += 1; estado[fm][at]["pj"] += 1
            estado[fm][ht]["gf"] += hg; estado[fm][ht]["gc"] += ag
            estado[fm][at]["gf"] += ag; estado[fm][at]["gc"] += hg
            if hg > ag:
                estado[fm][ht]["pg"] += 1; estado[fm][ht]["puntos"] += 3
                estado[fm][at]["pp"] += 1
            elif hg == ag:
                estado[fm][ht]["pe"] += 1; estado[fm][ht]["puntos"] += 1
                estado[fm][at]["pe"] += 1; estado[fm][at]["puntos"] += 1
            else:
                estado[fm][at]["pg"] += 1; estado[fm][at]["puntos"] += 3
                estado[fm][ht]["pp"] += 1

    # Asignar posicion: agrupar snapshots por (liga, temp, formato, fecha) y rankear
    by_lookup = defaultdict(list)
    for snap in snapshots_a_persistir:
        liga_s, temp_s, fm_s, fecha_s, eq_s, pj, pg, pe, pp, gf, gc, dif, pts = snap
        by_lookup[(liga_s, temp_s, fm_s, fecha_s)].append((eq_s, pj, pg, pe, pp, gf, gc, dif, pts))

    rows_final = []
    for (liga_s, temp_s, fm_s, fecha_s), eq_stats in by_lookup.items():
        ord_ = sorted(eq_stats, key=lambda x: (-x[8], -x[7], -x[5], x[0]))
        for posicion, (eq_s, pj, pg, pe, pp, gf, gc, dif, pts) in enumerate(ord_, 1):
            # [adepor-qqb fix] Popular equipo_norm para que helpers Layer 3 lookeen.
            equipo_norm = limpiar_texto(eq_s)
            rows_final.append((liga_s, temp_s, fm_s, fecha_s, eq_s, equipo_norm, posicion,
                                pj, pg, pe, pp, gf, gc, dif, pts))

    # Insert batch
    cur.executemany("""
        INSERT OR REPLACE INTO posiciones_tabla_snapshot
        (liga, temp, formato, fecha_snapshot, equipo, equipo_norm, posicion,
         pj, pg, pe, pp, gf, gc, dif_gol, puntos)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_final)
    con.commit()
    return len(rows_final)


def actualizar_si_hay_nuevos(db_path=None, verbose=True):
    """Hook principal. Detecta grupos con liquidados nuevos y regenera incremental.

    Returns dict con resumen: {n_grupos, n_snapshots_persistidos, fecha_run}.
    """
    db_path = db_path or DB_DEFAULT
    con = sqlite3.connect(db_path)
    crear_tabla_si_no_existe(con)
    pendientes = detectar_grupos_pendientes(con)
    if not pendientes:
        if verbose:
            print("[posiciones] sin liquidados nuevos, skip")
        con.close()
        return {"n_grupos": 0, "n_snapshots_persistidos": 0,
                "fecha_run": datetime.now().isoformat()}

    if verbose:
        print(f"[posiciones] detectados {len(pendientes)} grupos (liga, temp) con liquidados nuevos")
    total = 0
    for liga, temp, fecha_min in pendientes:
        n = regenerar_grupo(con, liga, temp, fecha_min)
        total += n
        if verbose:
            print(f"  {liga}/{temp} desde {fecha_min}: {n:,} snapshots")
    con.close()
    return {"n_grupos": len(pendientes), "n_snapshots_persistidos": total,
            "fecha_run": datetime.now().isoformat()}


def main():
    """Entry point para ejecucion como modulo: py -m src.persistencia.actualizar_posiciones."""
    print("=" * 60)
    print("Actualizador posiciones_tabla_snapshot (incremental)")
    print("=" * 60)
    res = actualizar_si_hay_nuevos(verbose=True)
    print(f"\nResumen: {res}")


if __name__ == "__main__":
    main()

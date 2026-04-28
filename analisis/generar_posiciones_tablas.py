"""adepor-3ip: Recrear tablas de posiciones por (liga, temp, formato).

Argentina TIENE DOS formatos paralelos:
  - 'anual': acumulando todos los partidos del ano (jan-dec).
  - 'apertura' + 'clausura': dos torneos semestrales separados.

Otras ligas: formato unico segun calendario tipico.
  - EUR top: 'liga' (ago-may, una sola tabla).
  - LATAM: 'anual' default. Algunas tienen 'apertura'/'clausura' tambien.

OUTPUT TABLA: posiciones_tabla_snapshot
  (liga, temp, formato, fecha_snapshot, equipo, posicion, pj, pg, pe, pp,
   gf, gc, dif_gol, puntos)

Snapshot por equipo en cada fecha de partido (sin look-ahead). El snapshot
'al inicio del dia del partido' acumula resultados ANTES de esa fecha.

Para Argentina, generamos 3 vistas paralelas:
  - posicion_anual: ranking acumulado anual.
  - posicion_apertura: ranking solo Apertura (primer semestre).
  - posicion_clausura: ranking solo Clausura (segundo semestre).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# Para Argentina: cuando empieza/termina cada torneo (Apertura/Clausura) en cada ano.
# Si no hay split (ej. liga anual sin distincion): apertura = todo el ano, clausura = None.
# Datos investigados de calendarios oficiales LPF.
ARGENTINA_SPLIT = {
    2022: {  # Liga 1 / Copa LPF anual
        "apertura": ("2022-02-04", "2022-05-22"),  # Copa LPF 1ra mitad
        "clausura": ("2022-06-05", "2022-10-25"),  # Liga Profesional segunda mitad
    },
    2023: {  # Liga Profesional anual
        "apertura": ("2023-01-27", "2023-07-30"),
        "clausura": ("2023-08-04", "2023-12-04"),
    },
    2024: {  # Copa LPF + Liga
        "apertura": ("2024-02-23", "2024-06-08"),
        "clausura": ("2024-07-19", "2024-12-08"),
    },
    2025: {  # LPF nuevo formato Apertura/Clausura
        "apertura": ("2025-01-23", "2025-06-28"),
        "clausura": ("2025-07-12", "2025-12-14"),
    },
    2026: {  # Apertura 2026 actual (Clausura aun no empezo)
        "apertura": ("2026-01-23", "2026-06-22"),
        "clausura": None,  # se llenara cuando empiece (~jul 2026)
    },
}

# LIGAS_FORMATOS: por liga, que formato(s) tiene esa liga
LIGAS_FORMATOS = {
    "Argentina":  ["anual", "apertura", "clausura"],  # los 3 paralelos
    "Brasil":     ["anual"],
    "Noruega":    ["anual"],
    "Chile":      ["anual"],
    "Peru":       ["anual"],
    "Bolivia":    ["anual"],
    "Uruguay":    ["anual"],
    "Venezuela":  ["anual"],
    "Ecuador":    ["anual"],
    "Colombia":   ["apertura"],  # Colombia hace solo Apertura ene-jun en este sample
    # EUR top: una sola liga ago-may (call it "liga" formato)
    "Inglaterra": ["liga"],
    "Italia":     ["liga"],
    "Espana":     ["liga"],
    "Francia":    ["liga"],
    "Alemania":   ["liga"],
    "Turquia":    ["liga"],
}


def fecha_dentro_de(fecha_str, rango):
    """rango = (start, end). Retorna True si fecha_str esta dentro."""
    if rango is None:
        return False
    return rango[0] <= fecha_str <= rango[1]


def cargar_partidos(con):
    """Cargar partidos liquidados con outcome."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT id, liga, temp, fecha, ht, at, hg, ag
        FROM partidos_historico_externo
        WHERE hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY liga, temp, fecha, id
    """).fetchall()
    return [{"id": r[0], "liga": r[1], "temp": r[2], "fecha": r[3][:10],
             "ht": r[4], "at": r[5], "hg": r[6], "ag": r[7]} for r in rows]


def determinar_formato_partido(liga, temp, fecha):
    """Para un partido, retorna lista de formatos que aplican.
    Argentina partido en Apertura -> ['anual', 'apertura']
    Argentina partido en Clausura -> ['anual', 'clausura']
    Otras ligas -> formato unico
    """
    formatos = LIGAS_FORMATOS.get(liga, ["anual"])
    if liga == "Argentina":
        split = ARGENTINA_SPLIT.get(temp)
        if not split:
            return ["anual"]
        if fecha_dentro_de(fecha, split.get("apertura")):
            return ["anual", "apertura"]
        if fecha_dentro_de(fecha, split.get("clausura")):
            return ["anual", "clausura"]
        return ["anual"]
    return formatos


def crear_tabla_posiciones(con):
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
    # Index para queries rapidas por (liga, temp, formato, equipo, fecha)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pos_snapshot_lookup
        ON posiciones_tabla_snapshot(liga, temp, formato, equipo, fecha_snapshot DESC)
    """)
    con.commit()


def calcular_snapshots(partidos):
    """Para cada (liga, temp, formato), iterar partidos en orden cronologico
    y persistir snapshot ANTES de cada partido (con stats acumuladas hasta
    el dia anterior).

    Retorna dict {(liga, temp, formato, fecha, equipo): stats_dict}
    """
    snapshots = {}
    # Agrupar partidos por (liga, temp, formato)
    by_grupo = defaultdict(list)
    for p in partidos:
        formatos = determinar_formato_partido(p["liga"], p["temp"], p["fecha"])
        for fm in formatos:
            by_grupo[(p["liga"], p["temp"], fm)].append(p)

    # Para cada grupo, iterar cronologico
    for (liga, temp, fm), part_grupo in by_grupo.items():
        part_grupo.sort(key=lambda x: (x["fecha"], x["id"]))
        # estado acumulativo por equipo
        stats = defaultdict(lambda: {"pj": 0, "pg": 0, "pe": 0, "pp": 0,
                                       "gf": 0, "gc": 0, "puntos": 0})
        # Para cada partido, ANTES de procesarlo, snapshot ambos equipos
        for p in part_grupo:
            for eq in [p["ht"], p["at"]]:
                s = stats[eq]
                snap_key = (liga, temp, fm, p["fecha"], eq)
                snapshots[snap_key] = {
                    "pj": s["pj"], "pg": s["pg"], "pe": s["pe"], "pp": s["pp"],
                    "gf": s["gf"], "gc": s["gc"],
                    "dif_gol": s["gf"] - s["gc"], "puntos": s["puntos"],
                }
            # Despues del snapshot, actualizar estado por este partido
            stats[p["ht"]]["pj"] += 1
            stats[p["at"]]["pj"] += 1
            stats[p["ht"]]["gf"] += p["hg"]
            stats[p["ht"]]["gc"] += p["ag"]
            stats[p["at"]]["gf"] += p["ag"]
            stats[p["at"]]["gc"] += p["hg"]
            if p["hg"] > p["ag"]:
                stats[p["ht"]]["pg"] += 1; stats[p["ht"]]["puntos"] += 3
                stats[p["at"]]["pp"] += 1
            elif p["hg"] == p["ag"]:
                stats[p["ht"]]["pe"] += 1; stats[p["ht"]]["puntos"] += 1
                stats[p["at"]]["pe"] += 1; stats[p["at"]]["puntos"] += 1
            else:
                stats[p["at"]]["pg"] += 1; stats[p["at"]]["puntos"] += 3
                stats[p["ht"]]["pp"] += 1
    return snapshots


def calcular_posiciones(snapshots):
    """Dado snapshots dict, asignar posicion por (liga, temp, formato, fecha).
    Ordenar equipos por puntos DESC, dif_gol DESC, gf DESC.
    """
    # Agrupar snapshots por (liga, temp, formato, fecha)
    by_fecha = defaultdict(list)
    for (liga, temp, fm, fecha, eq), stats in snapshots.items():
        by_fecha[(liga, temp, fm, fecha)].append((eq, stats))
    # Para cada (liga, temp, formato, fecha), rankear
    for (liga, temp, fm, fecha), eq_stats in by_fecha.items():
        # Ordenar
        ordenado = sorted(eq_stats, key=lambda x: (-x[1]["puntos"], -x[1]["dif_gol"], -x[1]["gf"], x[0]))
        for pos, (eq, stats) in enumerate(ordenado, 1):
            stats["posicion"] = pos
    return snapshots


def main():
    con = sqlite3.connect(DB)
    print("Cargando partidos historicos...")
    partidos = cargar_partidos(con)
    print(f"  N partidos: {len(partidos):,}")
    crear_tabla_posiciones(con)
    print("\nCalculando snapshots cronologicos sin look-ahead...")
    snapshots = calcular_snapshots(partidos)
    print(f"  N snapshots (liga,temp,formato,fecha,equipo): {len(snapshots):,}")
    snapshots = calcular_posiciones(snapshots)
    print("Persistiendo en posiciones_tabla_snapshot...")
    cur = con.cursor()
    cur.execute("DELETE FROM posiciones_tabla_snapshot")
    inserted = 0
    batch = []
    for (liga, temp, fm, fecha, eq), s in snapshots.items():
        batch.append((liga, temp, fm, fecha, eq, s.get("posicion"),
                       s["pj"], s["pg"], s["pe"], s["pp"],
                       s["gf"], s["gc"], s["dif_gol"], s["puntos"]))
        if len(batch) >= 5000:
            cur.executemany("""
                INSERT OR REPLACE INTO posiciones_tabla_snapshot
                (liga, temp, formato, fecha_snapshot, equipo, posicion,
                 pj, pg, pe, pp, gf, gc, dif_gol, puntos)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            inserted += len(batch)
            batch = []
    if batch:
        cur.executemany("""
            INSERT OR REPLACE INTO posiciones_tabla_snapshot
            (liga, temp, formato, fecha_snapshot, equipo, posicion,
             pj, pg, pe, pp, gf, gc, dif_gol, puntos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        inserted += len(batch)
    con.commit()
    print(f"  Insertadas {inserted:,} filas")

    # Audit: cuantas combinaciones (liga, temp, formato) hay?
    print("\n=== Resumen por (liga, temp, formato) ===")
    for r in cur.execute("""
        SELECT liga, temp, formato, COUNT(DISTINCT equipo) as N_eqs,
               COUNT(DISTINCT fecha_snapshot) as N_fechas,
               COUNT(*) as N_filas
        FROM posiciones_tabla_snapshot
        GROUP BY liga, temp, formato
        ORDER BY liga, temp, formato
    """):
        print(f"  {r[0]:<14} {r[1]} {r[2]:<10} {r[3]:>3} eqs  {r[4]:>3} fechas  {r[5]:>5} filas")

    # Validacion: ultima posicion Argentina Apertura 2024 vs anual 2024
    print("\n=== Validacion: top-5 Argentina 2024 ===")
    print("  ANUAL (al final temp):")
    for r in cur.execute("""
        SELECT equipo, posicion, pj, puntos FROM posiciones_tabla_snapshot
        WHERE liga='Argentina' AND temp=2024 AND formato='anual'
          AND fecha_snapshot = (SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
                                 WHERE liga='Argentina' AND temp=2024 AND formato='anual')
        ORDER BY posicion LIMIT 5
    """):
        print(f"    {r[1]:>2}. {r[0]:<25} pj={r[2]:>2} pts={r[3]}")

    print("  APERTURA (al final temp):")
    for r in cur.execute("""
        SELECT equipo, posicion, pj, puntos FROM posiciones_tabla_snapshot
        WHERE liga='Argentina' AND temp=2024 AND formato='apertura'
          AND fecha_snapshot = (SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
                                 WHERE liga='Argentina' AND temp=2024 AND formato='apertura')
        ORDER BY posicion LIMIT 5
    """):
        print(f"    {r[1]:>2}. {r[0]:<25} pj={r[2]:>2} pts={r[3]}")

    print("  CLAUSURA (al final temp):")
    for r in cur.execute("""
        SELECT equipo, posicion, pj, puntos FROM posiciones_tabla_snapshot
        WHERE liga='Argentina' AND temp=2024 AND formato='clausura'
          AND fecha_snapshot = (SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
                                 WHERE liga='Argentina' AND temp=2024 AND formato='clausura')
        ORDER BY posicion LIMIT 5
    """):
        print(f"    {r[1]:>2}. {r[0]:<25} pj={r[2]:>2} pts={r[3]}")

    con.close()


if __name__ == "__main__":
    main()

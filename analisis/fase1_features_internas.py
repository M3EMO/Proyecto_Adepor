"""adepor-6kw Fase 1 — backbone interno features sin scraping.

Genera 2 tablas determinísticas + 1 view:
  - momento_temporada(liga, temp, fecha, pct_temp, bin_4, bin_8)
  - posicion_tabla(liga, temp, fecha_snapshot, equipo, pj/pg/pe/pp/gf/gc/dg/pts/posicion)
  - partidos_con_features (VIEW que joinea partidos_backtest con features)

Fuentes de resultados:
  - partidos_historico_externo (2021-2025, temps cerradas)
  - partidos_backtest (2026, temp en curso)

Walk-forward correcto: posición al inicio del día del partido = acumulado
de partidos PREVIOS al día del partido (sin look-ahead).
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS momento_temporada (
    liga TEXT NOT NULL,
    temp INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    fecha_min_temp TEXT NOT NULL,
    fecha_max_temp TEXT NOT NULL,
    pct_temp REAL NOT NULL,
    bin_4 INTEGER NOT NULL,
    bin_8 INTEGER NOT NULL,
    bin_12 INTEGER,
    PRIMARY KEY (liga, temp, fecha)
);

CREATE TABLE IF NOT EXISTS posicion_tabla (
    liga TEXT NOT NULL,
    temp INTEGER NOT NULL,
    fecha_snapshot TEXT NOT NULL,
    equipo TEXT NOT NULL,
    pj INTEGER NOT NULL,
    pg INTEGER NOT NULL,
    pe INTEGER NOT NULL,
    pp INTEGER NOT NULL,
    gf INTEGER NOT NULL,
    gc INTEGER NOT NULL,
    dg INTEGER NOT NULL,
    puntos INTEGER NOT NULL,
    posicion INTEGER NOT NULL,
    PRIMARY KEY (liga, temp, fecha_snapshot, equipo)
);

CREATE INDEX IF NOT EXISTS idx_pos_tabla_lookup
    ON posicion_tabla(liga, fecha_snapshot, equipo);

CREATE INDEX IF NOT EXISTS idx_momento_lookup
    ON momento_temporada(liga, fecha);
"""


def derivar_temp_de_fecha(fecha_str: str, liga: str) -> int:
    """Deriva temp aproximada del año de la fecha.
    Para LATAM y Argentina (calendario): año exacto.
    Para EUR (agosto-mayo): si mes>=8, temp=year; si mes<8, temp=year-1.
    """
    y = int(fecha_str[:4])
    m = int(fecha_str[5:7])
    ligas_eur = {"Alemania", "Espana", "Francia", "Inglaterra", "Italia", "Turquia"}
    if liga in ligas_eur:
        return y if m >= 7 else y - 1
    return y


def setup_schema(con):
    cur = con.cursor()
    for stmt in SCHEMA.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)
    # Agregar columna bin_12 si la tabla ya existe sin ella
    cols = [r[1] for r in cur.execute("PRAGMA table_info(momento_temporada)")]
    if "bin_12" not in cols:
        cur.execute("ALTER TABLE momento_temporada ADD COLUMN bin_12 INTEGER")
    con.commit()


def cargar_resultados(con):
    """Devuelve list de dicts: liga, temp, fecha, local, visita, gl, gv."""
    cur = con.cursor()
    rows = []
    # partidos_historico_externo
    for r in cur.execute("""
        SELECT liga, temp, substr(fecha, 1, 10) as f, ht, at, hg, ag
        FROM partidos_historico_externo
        WHERE hg IS NOT NULL AND ag IS NOT NULL AND ht IS NOT NULL AND at IS NOT NULL
    """):
        rows.append({
            "liga": r[0], "temp": r[1], "fecha": r[2],
            "local": r[3], "visita": r[4], "gl": r[5], "gv": r[6],
            "fuente": "historico_externo",
        })
    # partidos_backtest (Liquidado con goles)
    for r in cur.execute("""
        SELECT pais, substr(fecha, 1, 10) as f, local, visita, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """):
        liga, fecha, local, visita, gl, gv = r
        if not (liga and fecha and local and visita):
            continue
        temp = derivar_temp_de_fecha(fecha, liga)
        rows.append({
            "liga": liga, "temp": temp, "fecha": fecha,
            "local": local, "visita": visita, "gl": gl, "gv": gv,
            "fuente": "backtest",
        })
    print(f"Resultados cargados: {len(rows)} partidos")
    print(f"  desde historico_externo: {sum(1 for r in rows if r['fuente']=='historico_externo')}")
    print(f"  desde backtest:          {sum(1 for r in rows if r['fuente']=='backtest')}")
    return rows


def cargar_fechas_a_snapshot(con):
    """Devuelve set de (liga, fecha_str) donde necesitamos posicion_tabla.
    Incluye:
      - partidos_backtest (in-sample 2026)
      - predicciones_walkforward x cuotas_externas_historico (OOS 2022-2024)
    """
    cur = con.cursor()
    out = set()
    # In-sample (motor real)
    for r in cur.execute("""
        SELECT DISTINCT pais, substr(fecha,1,10) FROM partidos_backtest
    """):
        if r[0] and r[1]:
            out.add((r[0], r[1]))
    # OOS walk-forward con cuotas
    for r in cur.execute("""
        SELECT DISTINCT p.liga, substr(p.fecha_partido,1,10)
        FROM predicciones_walkforward p
        JOIN cuotas_externas_historico q
          ON p.liga = q.liga AND substr(p.fecha_partido,1,10) = q.fecha
         AND p.ht = q.ht AND p.at = q.at
        WHERE p.fuente='walk_forward_sistema_real' AND q.psch IS NOT NULL
    """):
        if r[0] and r[1]:
            out.add((r[0], r[1]))
    return out


def poblar_momento_temporada(con, resultados, fechas_backtest):
    """Computa pct_temp para cada (liga, temp, fecha) y lo persiste."""
    cur = con.cursor()
    cur.execute("DELETE FROM momento_temporada")

    # Agrupar por (liga, temp)
    por_lt = defaultdict(list)
    for r in resultados:
        por_lt[(r["liga"], r["temp"])].append(r["fecha"])

    # Fechas adicionales del backtest (incluso si no hay resultado todavia)
    fechas_backtest_lt = defaultdict(set)
    for liga, fecha in fechas_backtest:
        temp = derivar_temp_de_fecha(fecha, liga)
        fechas_backtest_lt[(liga, temp)].add(fecha)

    # Combinar: para cada (liga, temp), todas las fechas conocidas
    todas_lt = defaultdict(set)
    for k, fs in por_lt.items():
        todas_lt[k].update(fs)
    for k, fs in fechas_backtest_lt.items():
        todas_lt[k].update(fs)

    n_filas = 0
    for (liga, temp), fechas in todas_lt.items():
        if not fechas:
            continue
        f_min = min(fechas)
        f_max = max(fechas)
        # Si solo hay 1 fecha, pct=0
        from datetime import datetime
        d_min = datetime.strptime(f_min, "%Y-%m-%d")
        d_max = datetime.strptime(f_max, "%Y-%m-%d")
        delta_total = (d_max - d_min).days
        for f in fechas:
            d = datetime.strptime(f, "%Y-%m-%d")
            delta = (d - d_min).days
            pct = delta / delta_total if delta_total > 0 else 0.0
            pct = max(0.0, min(0.999, pct))
            bin_4 = min(int(pct * 4), 3)
            bin_8 = min(int(pct * 8), 7)
            bin_12 = min(int(pct * 12), 11)
            cur.execute("""
                INSERT OR REPLACE INTO momento_temporada
                (liga, temp, fecha, fecha_min_temp, fecha_max_temp, pct_temp, bin_4, bin_8, bin_12)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (liga, temp, f, f_min, f_max, pct, bin_4, bin_8, bin_12))
            n_filas += 1
    con.commit()
    print(f"momento_temporada: {n_filas} filas insertadas ({len(todas_lt)} (liga,temp) procesadas)")


def poblar_posicion_tabla(con, resultados, fechas_backtest):
    """Calcula posicion ranking por liga+temp cumulativamente sin look-ahead."""
    cur = con.cursor()
    cur.execute("DELETE FROM posicion_tabla")

    # Agrupar resultados por (liga, temp), ordenar por fecha
    por_lt = defaultdict(list)
    for r in resultados:
        por_lt[(r["liga"], r["temp"])].append(r)

    # Identificar fechas a snapshot (las que aparecen en partidos_backtest)
    fechas_snapshot = defaultdict(set)
    for liga, fecha in fechas_backtest:
        temp = derivar_temp_de_fecha(fecha, liga)
        fechas_snapshot[(liga, temp)].add(fecha)

    n_filas = 0
    for (liga, temp), partidos in por_lt.items():
        partidos_ord = sorted(partidos, key=lambda p: p["fecha"])
        # Acumuladores por equipo
        acum = defaultdict(lambda: {"pj": 0, "pg": 0, "pe": 0, "pp": 0,
                                       "gf": 0, "gc": 0})
        # Snapshot fechas ordenadas
        fechas_snap = sorted(fechas_snapshot.get((liga, temp), set()))
        idx_part = 0
        for fecha_snap in fechas_snap:
            # Avanzar acumuladores con partidos previos a fecha_snap
            while idx_part < len(partidos_ord) and partidos_ord[idx_part]["fecha"] < fecha_snap:
                p = partidos_ord[idx_part]
                gl, gv = p["gl"], p["gv"]
                if gl is None or gv is None:
                    idx_part += 1
                    continue
                # Local
                aL = acum[p["local"]]
                aL["pj"] += 1
                aL["gf"] += gl
                aL["gc"] += gv
                if gl > gv:
                    aL["pg"] += 1
                elif gl == gv:
                    aL["pe"] += 1
                else:
                    aL["pp"] += 1
                # Visita
                aV = acum[p["visita"]]
                aV["pj"] += 1
                aV["gf"] += gv
                aV["gc"] += gl
                if gv > gl:
                    aV["pg"] += 1
                elif gv == gl:
                    aV["pe"] += 1
                else:
                    aV["pp"] += 1
                idx_part += 1
            # Snapshot ranking
            equipos_lista = [(eq, a) for eq, a in acum.items()]
            equipos_lista.sort(key=lambda x: (
                -(x[1]["pg"]*3 + x[1]["pe"]),
                -(x[1]["gf"] - x[1]["gc"]),
                -x[1]["gf"],
            ))
            for pos_idx, (eq, a) in enumerate(equipos_lista, start=1):
                pts = a["pg"]*3 + a["pe"]
                cur.execute("""
                    INSERT OR REPLACE INTO posicion_tabla
                    (liga, temp, fecha_snapshot, equipo, pj, pg, pe, pp, gf, gc, dg, puntos, posicion)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (liga, temp, fecha_snap, eq,
                       a["pj"], a["pg"], a["pe"], a["pp"],
                       a["gf"], a["gc"], a["gf"]-a["gc"], pts, pos_idx))
                n_filas += 1
    con.commit()
    print(f"posicion_tabla: {n_filas} filas insertadas")


def crear_view_features(con):
    cur = con.cursor()
    # In-sample view
    cur.execute("DROP VIEW IF EXISTS partidos_con_features")
    cur.execute("""
        CREATE VIEW partidos_con_features AS
        SELECT
            p.id_partido,
            substr(p.fecha, 1, 10) AS fecha,
            p.pais AS liga,
            p.local,
            p.visita,
            mt.pct_temp,
            mt.bin_4 AS momento_bin_4,
            mt.bin_8 AS momento_octavo,
            mt.bin_12 AS momento_bin_12,
            pt_l.posicion AS pos_local,
            pt_l.puntos AS pts_local,
            pt_l.pj AS pj_local,
            pt_l.dg AS dg_local,
            pt_v.posicion AS pos_visita,
            pt_v.puntos AS pts_visita,
            pt_v.pj AS pj_visita,
            pt_v.dg AS dg_visita,
            CASE
                WHEN pt_l.posicion IS NULL OR pt_v.posicion IS NULL THEN NULL
                ELSE pt_v.posicion - pt_l.posicion
            END AS diff_pos
        FROM partidos_backtest p
        LEFT JOIN momento_temporada mt
          ON p.pais = mt.liga AND substr(p.fecha,1,10) = mt.fecha
        LEFT JOIN posicion_tabla pt_l
          ON p.pais = pt_l.liga
         AND substr(p.fecha,1,10) = pt_l.fecha_snapshot
         AND p.local = pt_l.equipo
        LEFT JOIN posicion_tabla pt_v
          ON p.pais = pt_v.liga
         AND substr(p.fecha,1,10) = pt_v.fecha_snapshot
         AND p.visita = pt_v.equipo
    """)
    # OOS view: predicciones walk-forward con cuotas reales + features
    cur.execute("DROP VIEW IF EXISTS predicciones_oos_con_features")
    cur.execute("""
        CREATE VIEW predicciones_oos_con_features AS
        SELECT
            p.id AS pred_id,
            substr(p.fecha_partido, 1, 10) AS fecha,
            p.liga,
            p.temp,
            p.ht AS local,
            p.at AS visita,
            p.outcome,
            p.prob_1, p.prob_x, p.prob_2,
            q.psch, q.pscd, q.psca,
            mt.pct_temp,
            mt.bin_4 AS momento_bin_4,
            mt.bin_8 AS momento_octavo,
            mt.bin_12 AS momento_bin_12,
            pt_l.posicion AS pos_local,
            pt_l.puntos AS pts_local,
            pt_l.pj AS pj_local,
            pt_v.posicion AS pos_visita,
            pt_v.puntos AS pts_visita,
            pt_v.pj AS pj_visita,
            CASE
                WHEN pt_l.posicion IS NULL OR pt_v.posicion IS NULL THEN NULL
                ELSE pt_v.posicion - pt_l.posicion
            END AS diff_pos
        FROM predicciones_walkforward p
        JOIN cuotas_externas_historico q
          ON p.liga = q.liga AND substr(p.fecha_partido,1,10) = q.fecha
         AND p.ht = q.ht AND p.at = q.at
        LEFT JOIN momento_temporada mt
          ON p.liga = mt.liga AND substr(p.fecha_partido,1,10) = mt.fecha
        LEFT JOIN posicion_tabla pt_l
          ON p.liga = pt_l.liga
         AND substr(p.fecha_partido,1,10) = pt_l.fecha_snapshot
         AND p.ht = pt_l.equipo
        LEFT JOIN posicion_tabla pt_v
          ON p.liga = pt_v.liga
         AND substr(p.fecha_partido,1,10) = pt_v.fecha_snapshot
         AND p.at = pt_v.equipo
        WHERE p.fuente='walk_forward_sistema_real'
          AND q.psch IS NOT NULL AND q.pscd IS NOT NULL AND q.psca IS NOT NULL
          AND p.prob_1 IS NOT NULL
    """)
    con.commit()
    print("VIEW partidos_con_features creada")
    print("VIEW predicciones_oos_con_features creada")


def smoke_tests(con):
    """Smoke tests sobre partidos_backtest in-sample (donde hay snapshots)."""
    cur = con.cursor()
    print()
    print("=== SMOKE TESTS ===")

    # 1. Cobertura
    n_pf = cur.execute("SELECT COUNT(*) FROM partidos_con_features").fetchone()[0]
    n_with_pos = cur.execute("""
        SELECT COUNT(*) FROM partidos_con_features
        WHERE pos_local IS NOT NULL AND pos_visita IS NOT NULL
    """).fetchone()[0]
    n_with_momento = cur.execute("""
        SELECT COUNT(*) FROM partidos_con_features WHERE pct_temp IS NOT NULL
    """).fetchone()[0]
    print(f"1. Cobertura: {n_pf} partidos in-sample")
    print(f"   con momento_temp:  {n_with_momento} ({n_with_momento*100/n_pf:.1f}%)")
    print(f"   con posicion_tabla: {n_with_pos} ({n_with_pos*100/n_pf:.1f}%)")

    # 2. Hit rate por bucket de posicion local (Liquidados in-sample)
    print()
    print("2. In-sample: hit_local por posicion_local (Liquidados, motor decide LOCAL)")
    print(f"   {'pos_local_bucket':<20} {'N':>5} {'GANA_local%':>12} {'EMPATE%':>9} {'PIERDE%':>9}")
    for r in cur.execute("""
        WITH joined AS (
            SELECT
                CASE
                    WHEN pf.pos_local <= 4 THEN 'top_4'
                    WHEN pf.pos_local <= 8 THEN 'top_5_8'
                    WHEN pf.pos_local <= 12 THEN 'mid_9_12'
                    WHEN pf.pos_local <= 16 THEN 'mid_13_16'
                    ELSE 'bottom_17plus'
                END AS bucket,
                CASE WHEN p.goles_l > p.goles_v THEN 1 ELSE 0 END AS gl,
                CASE WHEN p.goles_l = p.goles_v THEN 1 ELSE 0 END AS e,
                CASE WHEN p.goles_l < p.goles_v THEN 1 ELSE 0 END AS pl
            FROM partidos_backtest p
            JOIN partidos_con_features pf ON pf.id_partido = p.id_partido
            WHERE p.estado='Liquidado' AND p.goles_l IS NOT NULL
              AND pf.pos_local IS NOT NULL AND pf.pj_local >= 3
        )
        SELECT bucket, COUNT(*) n,
               AVG(gl)*100, AVG(e)*100, AVG(pl)*100
        FROM joined GROUP BY bucket ORDER BY MIN(CASE bucket
            WHEN 'top_4' THEN 1 WHEN 'top_5_8' THEN 2 WHEN 'mid_9_12' THEN 3
            WHEN 'mid_13_16' THEN 4 ELSE 5 END)
    """):
        print(f"   {r[0]:<20} {r[1]:>5} {r[2]:>12.1f} {r[3]:>9.1f} {r[4]:>9.1f}")

    # 3. Distribucion de pct_temp
    print()
    print("3. Distribucion partidos_backtest por momento_bin_4 y octavo:")
    print(f"   bin_4: 0=arranque 1=inicio 2=mitad 3=cierre")
    for r in cur.execute("""
        SELECT momento_bin_4, COUNT(*)
        FROM partidos_con_features
        WHERE momento_bin_4 IS NOT NULL
        GROUP BY momento_bin_4 ORDER BY momento_bin_4
    """):
        print(f"   bin_4={r[0]} (pct {r[0]*25}-{(r[0]+1)*25}%): N={r[1]}")
    print()
    for r in cur.execute("""
        SELECT momento_octavo, COUNT(*)
        FROM partidos_con_features
        WHERE momento_octavo IS NOT NULL
        GROUP BY momento_octavo ORDER BY momento_octavo
    """):
        print(f"   octavo O{r[0]+1} (pct {r[0]*12.5}-{(r[0]+1)*12.5}%): N={r[1]}")

    # 4. Sample partidos_con_features
    print()
    print("4. Sample partidos_con_features in-sample (10 mas recientes):")
    print(f"   {'Fecha':<12} {'Liga':<12} {'Local vs Visita':<46} {'pct':>5} {'b4':>3} {'O':>2} {'PL':>3} {'PV':>3} {'dPos':>5}")
    for r in cur.execute("""
        SELECT fecha, liga, local || ' vs ' || visita, pct_temp, momento_bin_4, momento_octavo,
               pos_local, pos_visita, diff_pos
        FROM partidos_con_features
        WHERE pos_local IS NOT NULL AND pos_visita IS NOT NULL
        ORDER BY fecha DESC LIMIT 10
    """):
        partido = r[2][:44]
        pct = r[3] if r[3] is not None else 0
        b4 = r[4] if r[4] is not None else "-"
        oct = (r[5] + 1) if r[5] is not None else "-"
        pl = r[6] if r[6] is not None else "-"
        pv = r[7] if r[7] is not None else "-"
        dp = r[8] if r[8] is not None else "-"
        print(f"   {r[0]:<12} {r[1]:<12} {partido:<46} {pct:>5.2f} {b4:>3} {oct:>2} {pl:>3} {pv:>3} {dp:>+5}" if isinstance(dp, int)
              else f"   {r[0]:<12} {r[1]:<12} {partido:<46} {pct:>5.2f} {b4:>3} {oct:>2} {pl:>3} {pv:>3} {dp:>5}")

    # 5. Correlacion diff_pos con resultado in-sample (Liquidados)
    print()
    print("5. In-sample: hit_local por diff_pos bucket (Liquidados con goles)")
    print(f"   diff_pos = pos_visita - pos_local. >0 = local mejor ranking.")
    print(f"   {'diff_pos_bucket':<20} {'N':>5} {'GANA_local%':>12} {'EMPATE%':>9} {'GANA_vis%':>9}")
    for r in cur.execute("""
        WITH joined AS (
            SELECT
                CASE
                    WHEN pf.diff_pos <= -5 THEN '-5+ (vis mejor)'
                    WHEN pf.diff_pos BETWEEN -4 AND -1 THEN '-1 a -4'
                    WHEN pf.diff_pos = 0 THEN '0 (igual)'
                    WHEN pf.diff_pos BETWEEN 1 AND 4 THEN '+1 a +4'
                    ELSE '+5+ (loc mejor)'
                END AS bucket,
                CASE WHEN p.goles_l > p.goles_v THEN 1 ELSE 0 END AS gl,
                CASE WHEN p.goles_l = p.goles_v THEN 1 ELSE 0 END AS e,
                CASE WHEN p.goles_l < p.goles_v THEN 1 ELSE 0 END AS gv,
                CASE pf.diff_pos <= -5 WHEN 1 THEN 1
                     ELSE CASE WHEN pf.diff_pos BETWEEN -4 AND -1 THEN 2
                          ELSE CASE WHEN pf.diff_pos = 0 THEN 3
                               ELSE CASE WHEN pf.diff_pos BETWEEN 1 AND 4 THEN 4
                                    ELSE 5 END END END END AS ord
            FROM partidos_backtest p
            JOIN partidos_con_features pf ON pf.id_partido = p.id_partido
            WHERE p.estado='Liquidado' AND p.goles_l IS NOT NULL
              AND pf.diff_pos IS NOT NULL AND pf.pj_local >= 3 AND pf.pj_visita >= 3
        )
        SELECT bucket, COUNT(*) n,
               AVG(gl)*100, AVG(e)*100, AVG(gv)*100,
               MIN(ord)
        FROM joined GROUP BY bucket ORDER BY MIN(ord)
    """):
        print(f"   {r[0]:<20} {r[1]:>5} {r[2]:>12.1f} {r[3]:>9.1f} {r[4]:>9.1f}")


def main():
    con = sqlite3.connect(DB)
    print(f"=== Fase 1 features internas (adepor-6kw) ===")
    setup_schema(con)
    print("Schema verificado/creado")
    print()
    resultados = cargar_resultados(con)
    fechas_a_snapshot = cargar_fechas_a_snapshot(con)
    print(f"Fechas a snapshot (in-sample + OOS): {len(fechas_a_snapshot)} (liga, fecha) únicas")
    print()
    poblar_momento_temporada(con, resultados, fechas_a_snapshot)
    poblar_posicion_tabla(con, resultados, fechas_a_snapshot)
    crear_view_features(con)
    smoke_tests(con)
    con.close()
    print()
    print("[OK] Fase 1 completa")


if __name__ == "__main__":
    main()

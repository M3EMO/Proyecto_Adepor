"""Fase 4 (adepor-6kw): EMA por equipo de stats avanzadas.

Para cada (liga, equipo): mantener EMA dual (corto α=0.40, largo α=0.10) de
cada stat ESPN. Snapshot ANTES de cada partido = predictor pre-partido.

Walk-forward correcto: el snapshot del partido fecha=X solo usa partidos
con fecha < X (sin look-ahead).

Schema:
  historial_equipos_stats(liga, equipo, fecha, n_acum,
    ema_l_*, ema_c_*    # 21 stats x 2 alfas = 42 columnas EMA
  )
  PRIMARY KEY (liga, equipo, fecha)

Inicialización: prior = primer partido del equipo (no usar promedio liga
para no contaminar). Tras 3-4 partidos EMA corto converge.

Smoke test: validar que equipos posesivos clásicos (Manchester City, Boca
Juniors si no domina) tengan ema_pos > 55%.
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

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# Stats con su key local y visita (perspectiva del equipo)
STATS = [
    ("h_pos", "a_pos", "pos"),
    ("h_passes", "a_passes", "passes"),
    ("h_pass_pct", "a_pass_pct", "pass_pct"),
    ("h_crosses", "a_crosses", "crosses"),
    ("h_cross_pct", "a_cross_pct", "cross_pct"),
    ("h_longballs", "a_longballs", "longballs"),
    ("h_longball_pct", "a_longball_pct", "longball_pct"),
    ("hs", "as_v", "shots"),
    ("hst", "ast", "sots"),
    ("h_shot_pct", "a_shot_pct", "shot_pct"),
    ("h_blocks", "a_blocks", "blocks"),
    ("hc", "ac", "corners"),
    ("h_fouls", "a_fouls", "fouls"),
    ("h_yellow", "a_yellow", "yellow"),
    ("h_red", "a_red", "red"),
    ("h_offsides", "a_offsides", "offsides"),
    ("h_saves", "a_saves", "saves"),
    ("h_tackles", "a_tackles", "tackles"),
    ("h_tackle_pct", "a_tackle_pct", "tackle_pct"),
    ("h_interceptions", "a_interceptions", "interceptions"),
    ("h_clearance", "a_clearance", "clearance"),
]

ALFA_CORTO = 0.40   # EMA reactivo: ~3-4 partidos para convergir
ALFA_LARGO = 0.10   # EMA estable: ~10 partidos para convergir


def crear_schema(con):
    cur = con.cursor()
    cols_ema = []
    for _, _, lbl in STATS:
        cols_ema.append(f"ema_l_{lbl} REAL")
        cols_ema.append(f"ema_c_{lbl} REAL")
    schema = f"""
        CREATE TABLE IF NOT EXISTS historial_equipos_stats (
            liga TEXT NOT NULL,
            equipo TEXT NOT NULL,
            fecha TEXT NOT NULL,
            n_acum INTEGER NOT NULL,
            es_local INTEGER NOT NULL,
            rival TEXT,
            outcome TEXT,
            {','.join(cols_ema)},
            PRIMARY KEY (liga, equipo, fecha)
        )
    """
    cur.execute(schema)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hes_liga_eq ON historial_equipos_stats(liga, equipo)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hes_fecha ON historial_equipos_stats(fecha)")
    con.commit()


def cargar_partidos_ordenados(con, liga=None):
    """Devuelve list de partidos ordenados por (liga, fecha) con stats por equipo."""
    cur = con.cursor()
    where = "h_pos IS NOT NULL"
    params = []
    if liga:
        where += " AND liga = ?"
        params.append(liga)
    rows = cur.execute(f"""
        SELECT * FROM stats_partido_espn
        WHERE {where}
        ORDER BY liga, fecha, ht
    """, params).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("hg") is None or d.get("ag") is None:
            continue
        if d["hg"] > d["ag"]:
            out_l, out_v = "G", "P"
        elif d["hg"] == d["ag"]:
            out_l, out_v = "E", "E"
        else:
            out_l, out_v = "P", "G"
        # Local stats (perspectiva del equipo local)
        stats_l = {lbl: d.get(h) for h, _, lbl in STATS}
        # Visita stats
        stats_v = {lbl: d.get(a) for _, a, lbl in STATS}
        out.append({
            "liga": d["liga"], "fecha": d["fecha"],
            "ht": d["ht"], "at": d["at"],
            "outcome_l": out_l, "outcome_v": out_v,
            "stats_l": stats_l, "stats_v": stats_v,
        })
    return out


def actualizar_ema(estado, stats_nuevo, alfa):
    """Actualiza diccionario estado con EMA usando alfa.
    estado dict tipo {label: ema_value}. Si label no existe, init = stats_nuevo."""
    for lbl, val in stats_nuevo.items():
        if val is None:
            continue
        if lbl not in estado:
            estado[lbl] = float(val)
        else:
            estado[lbl] = alfa * float(val) + (1 - alfa) * estado[lbl]


def insertar_snapshot(con, liga, equipo, fecha, es_local, rival, outcome,
                       n_acum, ema_l, ema_c):
    """Inserta o reemplaza snapshot pre-partido del equipo en esa fecha."""
    cur = con.cursor()
    cols = ["liga", "equipo", "fecha", "n_acum", "es_local", "rival", "outcome"]
    vals = [liga, equipo, fecha, n_acum, es_local, rival, outcome]
    for _, _, lbl in STATS:
        cols.append(f"ema_l_{lbl}")
        vals.append(ema_l.get(lbl))
        cols.append(f"ema_c_{lbl}")
        vals.append(ema_c.get(lbl))
    placeholders = ",".join(["?"] * len(cols))
    cur.execute(f"""INSERT OR REPLACE INTO historial_equipos_stats ({','.join(cols)})
                     VALUES ({placeholders})""", vals)


def backfill(con, liga=None):
    """Walk-forward backfill EMAs por equipo. Snapshot ANTES de cada partido."""
    if liga:
        print(f"Backfill {liga}...")
    else:
        print("Backfill todas las ligas...")
    partidos = cargar_partidos_ordenados(con, liga)
    print(f"  {len(partidos)} partidos cargados")
    # Estado por (liga, equipo)
    ema_l_state = defaultdict(dict)  # {(liga, equipo): {lbl: val}}
    ema_c_state = defaultdict(dict)
    n_acum = defaultdict(int)
    n_snapshots = 0
    n_total = len(partidos)
    for i, p in enumerate(partidos):
        liga_p = p["liga"]
        ht = p["ht"]
        at = p["at"]
        # Snapshot ANTES del partido (estado actual de los acumuladores)
        # Local
        key_l = (liga_p, ht)
        if n_acum[key_l] >= 1:  # solo snapshot si hay al menos 1 partido previo
            insertar_snapshot(con, liga_p, ht, p["fecha"], 1, at, p["outcome_l"],
                               n_acum[key_l], ema_l_state[key_l], ema_c_state[key_l])
            n_snapshots += 1
        # Visita
        key_v = (liga_p, at)
        if n_acum[key_v] >= 1:
            insertar_snapshot(con, liga_p, at, p["fecha"], 0, ht, p["outcome_v"],
                               n_acum[key_v], ema_l_state[key_v], ema_c_state[key_v])
            n_snapshots += 1
        # Actualizar EMA con los stats del partido recién jugado (DESPUES)
        actualizar_ema(ema_l_state[key_l], p["stats_l"], ALFA_LARGO)
        actualizar_ema(ema_c_state[key_l], p["stats_l"], ALFA_CORTO)
        actualizar_ema(ema_l_state[key_v], p["stats_v"], ALFA_LARGO)
        actualizar_ema(ema_c_state[key_v], p["stats_v"], ALFA_CORTO)
        n_acum[key_l] += 1
        n_acum[key_v] += 1
        if (i + 1) % 1000 == 0:
            print(f"  ... {i+1}/{n_total} ({n_snapshots} snapshots persistidos)", flush=True)
    con.commit()
    print(f"\n[OK] Backfill completo: {n_snapshots} snapshots persistidos")
    print(f"  Equipos únicos con EMA: {len([k for k, v in n_acum.items() if v >= 1])}")


def smoke_test(con):
    """Verificación: top equipos por EMA pos largo en último snapshot."""
    cur = con.cursor()
    print("\n=== SMOKE TEST: top equipos por ema_l_pos (último snapshot por equipo) ===")
    rows = cur.execute("""
        WITH ultimo AS (
            SELECT liga, equipo, MAX(fecha) AS ult_fecha
            FROM historial_equipos_stats
            WHERE n_acum >= 10
            GROUP BY liga, equipo
        )
        SELECT h.liga, h.equipo, h.fecha, h.n_acum,
               h.ema_l_pos, h.ema_l_passes, h.ema_l_sots, h.ema_l_clearance,
               h.ema_l_crosses
        FROM historial_equipos_stats h
        JOIN ultimo u ON h.liga=u.liga AND h.equipo=u.equipo AND h.fecha=u.ult_fecha
        ORDER BY h.ema_l_pos DESC
        LIMIT 15
    """).fetchall()
    print(f"  {'Liga':<14} {'Equipo':<28} {'N':>4} {'pos':>5} {'pass':>5} {'sots':>5} {'clr':>5} {'crs':>5}")
    for r in rows:
        print(f"  {r[0]:<14} {r[1][:26]:<28} {r[3]:>4} "
              f"{r[4]:>5.1f} {r[5]:>5.0f} {r[6]:>5.1f} {r[7]:>5.1f} {r[8]:>5.1f}")

    print("\n=== Bottom equipos por ema_l_pos (más defensivos) ===")
    rows = cur.execute("""
        WITH ultimo AS (
            SELECT liga, equipo, MAX(fecha) AS ult_fecha
            FROM historial_equipos_stats
            WHERE n_acum >= 10
            GROUP BY liga, equipo
        )
        SELECT h.liga, h.equipo, h.fecha, h.n_acum,
               h.ema_l_pos, h.ema_l_passes, h.ema_l_sots, h.ema_l_clearance, h.ema_l_crosses
        FROM historial_equipos_stats h
        JOIN ultimo u ON h.liga=u.liga AND h.equipo=u.equipo AND h.fecha=u.ult_fecha
        ORDER BY h.ema_l_pos ASC
        LIMIT 15
    """).fetchall()
    print(f"  {'Liga':<14} {'Equipo':<28} {'N':>4} {'pos':>5} {'pass':>5} {'sots':>5} {'clr':>5} {'crs':>5}")
    for r in rows:
        print(f"  {r[0]:<14} {r[1][:26]:<28} {r[3]:>4} "
              f"{r[4]:>5.1f} {r[5]:>5.0f} {r[6]:>5.1f} {r[7]:>5.1f} {r[8]:>5.1f}")

    print("\n=== EMA dual divergence (top 10 con mayor |ema_c - ema_l| posesión) ===")
    rows = cur.execute("""
        WITH ultimo AS (
            SELECT liga, equipo, MAX(fecha) AS ult_fecha
            FROM historial_equipos_stats
            WHERE n_acum >= 10
            GROUP BY liga, equipo
        )
        SELECT h.liga, h.equipo, h.n_acum,
               h.ema_l_pos, h.ema_c_pos,
               h.ema_c_pos - h.ema_l_pos AS divergence
        FROM historial_equipos_stats h
        JOIN ultimo u ON h.liga=u.liga AND h.equipo=u.equipo AND h.fecha=u.ult_fecha
        ORDER BY ABS(h.ema_c_pos - h.ema_l_pos) DESC
        LIMIT 10
    """).fetchall()
    print(f"  {'Liga':<14} {'Equipo':<28} {'N':>4} {'EMA_L':>6} {'EMA_C':>6} {'div':>7}")
    for r in rows:
        print(f"  {r[0]:<14} {r[1][:26]:<28} {r[2]:>4} {r[3]:>6.2f} {r[4]:>6.2f} {r[5]:>+7.2f}")


def predecir_stats_pre_partido(con, liga, equipo, fecha):
    """Devuelve EMA del equipo ANTES de la fecha indicada (sin look-ahead).

    Uso pre-partido en motor: para predecir stats esperadas, llamar:
      stats_l = predecir_stats_pre_partido(con, 'Argentina', 'River Plate', '2026-05-01')
      stats_v = predecir_stats_pre_partido(con, 'Argentina', 'Boca Juniors', '2026-05-01')

    Devuelve dict {stat: ema_largo} (o None si equipo no tiene historial suficiente).
    También incluye 'ema_c_*' si se quiere divergencia corto vs largo.
    """
    cur = con.cursor()
    # Tomar el snapshot inmediatamente antes de la fecha
    row = cur.execute("""
        SELECT * FROM historial_equipos_stats
        WHERE liga=? AND equipo=? AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (liga, equipo, fecha)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def smoke_test_predecir(con):
    """Test de la funcion predecir_stats_pre_partido."""
    print("\n=== SMOKE predecir_stats_pre_partido ===")
    casos = [
        ("Argentina", "River Plate", "2026-04-25"),
        ("Argentina", "Boca Juniors", "2026-04-25"),
        ("Espana", "Barcelona", "2025-01-15"),
        ("Inglaterra", "Liverpool", "2025-01-15"),
        ("Inglaterra", "Crystal Palace", "2025-01-15"),
    ]
    for liga, eq, fecha in casos:
        snap = predecir_stats_pre_partido(con, liga, eq, fecha)
        if snap:
            print(f"\n  {liga} {eq} pre-{fecha} (N_acum={snap['n_acum']}):")
            print(f"    ema_l_pos = {snap['ema_l_pos']:.1f} | ema_c_pos = {snap['ema_c_pos']:.1f}")
            print(f"    ema_l_sots = {snap['ema_l_sots']:.2f} | ema_c_sots = {snap['ema_c_sots']:.2f}")
            print(f"    ema_l_clearance = {snap['ema_l_clearance']:.1f}")
            print(f"    ema_l_crosses = {snap['ema_l_crosses']:.1f}")
        else:
            print(f"  {liga} {eq} pre-{fecha}: sin historial")


def main():
    con = sqlite3.connect(DB)
    crear_schema(con)
    print("Schema creado")
    con.execute("DELETE FROM historial_equipos_stats")
    con.commit()
    backfill(con)
    smoke_test(con)
    smoke_test_predecir(con)
    con.close()


if __name__ == "__main__":
    main()

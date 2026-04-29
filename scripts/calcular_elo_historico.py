"""
[F3 — adepor PROPOSAL motor copa] Elo calculator histórico cross-competition.

Procesa cronologicamente todos los partidos en v_partidos_unificado (UNION
partidos_historico_externo + partidos_no_liga) y calcula Elo rating dinamico
por equipo segun:

- K-factor por competicion_tipo (literatura Eloratings.net + WC 2009 study):
    liga: 20, copa_nacional: 30, copa_internacional_grupo: 40,
    copa_internacional_knockout: 50, final: 60
- Home advantage: +100 puntos al rating del local antes de calcular expected
  (literatura World Football Elo Ratings)
- Goal difference modifier: 1.0/1.5/1.75/...+(N-3)/8 (estandar Eloratings.net)
- Cold-start regularization (Tandfonline 2025 sparse networks): K * 0.5 cuando
  n_partidos_acumulados < 30, para reducir varianza early.
- Rating inicial: 1500 (estandar)

Persiste en tabla equipo_nivel_elo con (equipo_norm, fecha, elo_post, ...).

[REF: docs/papers/elo_calibracion.md Q1+Q2+Q3]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# K-factor por competicion_tipo — calibrado por literatura Eloratings.net
K_FACTOR = {
    "liga": 20,
    "copa_nacional": 30,
    "copa_internacional": 40,           # default copa internacional (fase grupos)
    "copa_internacional_knockout": 50,  # eliminatorias
}
HOME_ADV = 100  # estandar World Football Elo Ratings
ELO_INIT = 1500
COLD_START_N = 30
COLD_START_FACTOR = 0.5
GD_MODIFIERS = {1: 1.0, 2: 1.5, 3: 1.75}  # 4+ usa formula 1.75 + (N-3)/8


def goal_diff_factor(gd_abs):
    """Factor multiplicativo de K segun diferencia de goles. [REF Q1]."""
    if gd_abs <= 1:
        return 1.0
    if gd_abs in GD_MODIFIERS:
        return GD_MODIFIERS[gd_abs]
    return 1.75 + (gd_abs - 3) / 8.0


def expected_score(elo_a, elo_b, home_adv=0):
    """Probabilidad esperada de gano de A vs B con home advantage opcional."""
    return 1.0 / (1.0 + 10 ** ((elo_b - (elo_a + home_adv)) / 400.0))


def k_para_partido(competicion_tipo, n_acum):
    """K-factor con cold-start regularization si pocos partidos acumulados."""
    base = K_FACTOR.get(competicion_tipo or "", 20)
    return base * (COLD_START_FACTOR if n_acum < COLD_START_N else 1.0)


def crear_tabla(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipo_nivel_elo (
            equipo_norm TEXT NOT NULL,
            fecha TEXT NOT NULL,
            elo_post REAL NOT NULL,
            delta_elo REAL,
            competicion TEXT,
            competicion_tipo TEXT,
            n_partidos_acumulados INTEGER,
            timestamp_insertado TEXT,
            PRIMARY KEY (equipo_norm, fecha)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_elo_equipo_fecha
        ON equipo_nivel_elo(equipo_norm, fecha DESC)
    """)
    conn.commit()


def cargar_partidos(conn, fecha_desde=None):
    """Carga partidos cronologicamente con norm names ya poblados."""
    cur = conn.cursor()
    where_extra = ""
    params = []
    if fecha_desde:
        where_extra = "AND fecha >= ?"
        params = [fecha_desde]

    rows = cur.execute(f"""
        SELECT fecha, equipo_local_norm, equipo_visita_norm,
               competicion, competicion_tipo, goles_l, goles_v
        FROM v_partidos_unificado
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND equipo_local_norm IS NOT NULL AND equipo_visita_norm IS NOT NULL
          {where_extra}
        ORDER BY fecha
    """, params).fetchall()
    return rows


def calcular(conn, dry_run=False, limpiar=False):
    cur = conn.cursor()
    if limpiar:
        cur.execute("DELETE FROM equipo_nivel_elo")
        conn.commit()
        print(f"  [LIMPIO] equipo_nivel_elo")

    partidos = cargar_partidos(conn)
    print(f"  Partidos a procesar: {len(partidos)}")

    # Estado actual: dict {equipo_norm: (elo, n_acum)}
    estado = defaultdict(lambda: [ELO_INIT, 0])

    inserts = []
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    n_l = n_v = n_c = 0  # contadores tipo competicion
    for fecha, eq_l, eq_v, comp, comp_tipo, gl, gv in partidos:
        # Mapear competicion_tipo a categoria K-factor
        ct = comp_tipo or "liga"
        if ct == "copa_internacional":
            # Default knockout salvo si fase grupo (sin info aqui — usamos default grupo)
            k_cat = "copa_internacional"
        elif ct == "copa_internacional_knockout":
            k_cat = "copa_internacional_knockout"
        elif "nacional" in ct:
            k_cat = "copa_nacional"
        else:
            k_cat = "liga"

        # Estado pre-partido
        elo_l_pre, n_l_acum = estado[eq_l]
        elo_v_pre, n_v_acum = estado[eq_v]

        # Expected (con home advantage al local)
        expected_l = expected_score(elo_l_pre, elo_v_pre, home_adv=HOME_ADV)

        # Resultado actual desde perspectiva local: 1/0.5/0
        if gl > gv:
            res_l = 1.0
        elif gl == gv:
            res_l = 0.5
        else:
            res_l = 0.0

        # GD modifier
        gd_abs = abs(gl - gv)
        f_gd = goal_diff_factor(gd_abs)

        # K (cold-start aware)
        k_l = k_para_partido(k_cat, n_l_acum)
        k_v = k_para_partido(k_cat, n_v_acum)
        k = (k_l + k_v) / 2.0

        # Update
        delta = k * f_gd * (res_l - expected_l)
        elo_l_post = elo_l_pre + delta
        elo_v_post = elo_v_pre - delta

        # Update estado
        estado[eq_l] = [elo_l_post, n_l_acum + 1]
        estado[eq_v] = [elo_v_post, n_v_acum + 1]

        if k_cat == "liga": n_l += 1
        elif "nacional" in k_cat: n_c += 1
        else: n_v += 1

        if not dry_run:
            inserts.append((eq_l, fecha, elo_l_post, +delta, comp, comp_tipo, n_l_acum + 1, ts))
            inserts.append((eq_v, fecha, elo_v_post, -delta, comp, comp_tipo, n_v_acum + 1, ts))

    if dry_run:
        print(f"\n  DRY-RUN — {n_l} liga, {n_c} copa nacional, {n_v} copa internacional")
        return estado, []

    print(f"  Tipos procesados: liga={n_l}, copa_nacional={n_c}, copa_internacional={n_v}")
    print(f"  Insertando {len(inserts)} filas...")
    cur.executemany("""
        INSERT OR REPLACE INTO equipo_nivel_elo
        (equipo_norm, fecha, elo_post, delta_elo, competicion, competicion_tipo,
         n_partidos_acumulados, timestamp_insertado)
        VALUES (?,?,?,?,?,?,?,?)
    """, inserts)
    conn.commit()

    return estado, inserts


def reporte(conn, estado):
    """Top 25 + bottom 10 + distribucion."""
    print("\n" + "=" * 70)
    print("TOP 25 EQUIPOS POR ELO ACTUAL (post histórico)")
    print("=" * 70)
    sorted_eq = sorted(estado.items(), key=lambda x: -x[1][0])
    for i, (eq, (elo, n)) in enumerate(sorted_eq[:25], 1):
        print(f"  {i:2d}. {eq:<35s} elo={elo:7.1f} n={n}")

    print("\n" + "=" * 70)
    print("BOTTOM 10 (con n>=20)")
    print("=" * 70)
    bottom = [(eq, e, n) for eq, (e, n) in sorted_eq if n >= 20]
    for eq, elo, n in bottom[-10:]:
        print(f"  {eq:<35s} elo={elo:7.1f} n={n}")

    print("\n" + "=" * 70)
    print("DISTRIBUCION elo_actual")
    print("=" * 70)
    elos = [e for e, n in estado.values() if n >= 10]
    if elos:
        elos.sort()
        print(f"  N (n>=10): {len(elos)}")
        print(f"  min: {min(elos):.1f}  max: {max(elos):.1f}")
        print(f"  median: {elos[len(elos)//2]:.1f}")
        print(f"  p10: {elos[len(elos)//10]:.1f}  p90: {elos[len(elos)*9//10]:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limpiar", action="store_true",
                    help="DELETE equipo_nivel_elo antes de recalcular")
    args = ap.parse_args()

    if not DB.exists():
        print(f"DB no existe: {DB}")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    conn.text_factory = str

    print(f"=== STEP 1: Crear tabla ===")
    crear_tabla(conn)

    print(f"\n=== STEP 2: Calcular Elo histórico ({'DRY-RUN' if args.dry_run else 'APPLY'}) ===")
    estado, _ = calcular(conn, dry_run=args.dry_run, limpiar=args.limpiar)

    reporte(conn, estado)
    conn.close()
    print(f"\nCompletado.")


if __name__ == "__main__":
    main()

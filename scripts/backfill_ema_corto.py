"""
Backfill historico de EMA corto (shadow EMA dual).

Pobla las columnas ema_corto_*_home/away y partidos_corto_home/away en
historial_equipos para los 333 equipos con N_largo > 0, replicando la
formula EMA con alfa_corto = min(2 * alfa_largo_liga, 0.50).

Diseno (Lead approved 2026-04-26, Opcion 2):
  - SEED inicial = ema_largo del equipo (no 1.4). Para los 77 equipos sin
    partidos en partidos_backtest, esto significa ema_corto = ema_largo
    exacto al final (fallback con prior informado).
  - SIN Bayesian shrinkage hacia promedio_liga (la Bayesianeidad ya viene
    del seed inicial — no se duplica).
  - Iteracion cronologica ASC sobre Liquidados con stats crudas.

CAVEAT METODOLOGICO:
Seed = ema_largo introduce information leakage retroactivo del estado actual
del EMA largo hacia el inicio de la serie cronologica. Mitigacion: alfa~=0.30
hace que tras 5 partidos el peso del seed sea 17%, y tras 10 sea 3%. El valor
FINAL del ema_corto es lo que importa para baseline (no la trayectoria
historica). Para los 77 equipos sin stats en partidos_backtest, ema_corto =
ema_largo exacto — fallback legitimo con prior informado.

NO TOCA:
  - ema_xg_favor_*/contra_* (largo).
  - ema_var_* (no aplica al corto).
  - ema_procesados (no se recalcula EMA largo).
  - motor_data.py / motor_calculadora.py.

Uso:
    py scripts/backfill_ema_corto.py --dry-run   # Preview, sin escribir.
    py scripts/backfill_ema_corto.py --auto      # Aplica + commit.
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingesta.motor_data import (
    calcular_xg_hibrido, ajustar_xg_por_estado_juego,
    ALFA_EMA, ALFA_EMA_POR_LIGA, get_param,
)
from src.comun.config_sistema import DB_NAME
from src.comun.gestor_nombres import limpiar_texto


def _stats_desde_row(sot, corn, shots):
    return [
        {"name": "shotsOnTarget", "displayValue": sot or 0},
        {"name": "wonCorners",    "displayValue": corn or 0},
        {"name": "totalShots",    "displayValue": shots or 0},
    ]


def _coef_corner_liga(cur, liga):
    cur.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga=?", (liga,))
    r = cur.fetchone()
    return float(r[0]) if r and r[0] is not None else 0.02


def _alfa_corto_liga(liga):
    alfa_largo = get_param("alfa_ema", scope=liga, default=ALFA_EMA_POR_LIGA.get(liga, ALFA_EMA))
    return min(2 * alfa_largo, 0.50), alfa_largo


def descubrir_targets(conn):
    """Todos los equipos en historial_equipos con N_largo > 0 (esperado: 333)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT equipo_real, liga
        FROM historial_equipos
        WHERE (partidos_home + partidos_away) > 0
          AND equipo_real IS NOT NULL
        ORDER BY liga, equipo_real
    """)
    return [(r[0], r[1]) for r in cur.fetchall()]


def _leer_estado_largo(cur, eq_norm, liga):
    cur.execute("""
        SELECT ema_xg_favor_home, ema_xg_contra_home,
               ema_xg_favor_away, ema_xg_contra_away
        FROM historial_equipos WHERE equipo_norm=? AND liga=?
    """, (eq_norm, liga))
    r = cur.fetchone()
    if r is None:
        return None
    return {"fav_home": r[0] or 1.4, "con_home": r[1] or 1.4,
            "fav_away": r[2] or 1.4, "con_away": r[3] or 1.4}


def backfill_ema_corto_uno(conn, equipo_real, liga, dry_run=False):
    cur = conn.cursor()
    eq_norm = limpiar_texto(equipo_real)
    alfa_corto, alfa_largo = _alfa_corto_liga(liga)
    coef_corner = _coef_corner_liga(cur, liga)

    seed = _leer_estado_largo(cur, eq_norm, liga)
    if seed is None:
        return None

    # Estado inicial = SEED desde EMA largo. Sin var_* (no aplica al corto).
    state = {
        "fav_home": seed["fav_home"], "con_home": seed["con_home"], "p_home": 0,
        "fav_away": seed["fav_away"], "con_away": seed["con_away"], "p_away": 0,
    }
    seed_inicial = dict(state)

    cur.execute("""
        SELECT id_partido, fecha, local, visita, goles_l, goles_v,
               sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado'
          AND (local=? OR visita=?)
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
        ORDER BY fecha ASC
    """, (liga, equipo_real, equipo_real))
    partidos = cur.fetchall()

    for p in partidos:
        _, _, local, _, goles_l, goles_v, sot_l, shots_l, corn_l, sot_v, shots_v, corn_v = p
        is_home = (local == equipo_real)

        stats_loc = _stats_desde_row(sot_l, corn_l, shots_l)
        stats_vis = _stats_desde_row(sot_v, corn_v, shots_v)

        xg_loc_crudo = calcular_xg_hibrido(stats_loc, goles_l, coef_corner, pais=liga)
        xg_vis_crudo = calcular_xg_hibrido(stats_vis, goles_v, coef_corner, pais=liga)
        xg_loc = ajustar_xg_por_estado_juego(xg_loc_crudo, goles_l, goles_v)
        xg_vis = ajustar_xg_por_estado_juego(xg_vis_crudo, goles_v, goles_l)

        if is_home:
            xg_f, xg_c = xg_loc, xg_vis
            state["fav_home"] = round((xg_f * alfa_corto) + (state["fav_home"] * (1 - alfa_corto)), 3)
            state["con_home"] = round((xg_c * alfa_corto) + (state["con_home"] * (1 - alfa_corto)), 3)
            state["p_home"] += 1
        else:
            xg_f, xg_c = xg_vis, xg_loc
            state["fav_away"] = round((xg_f * alfa_corto) + (state["fav_away"] * (1 - alfa_corto)), 3)
            state["con_away"] = round((xg_c * alfa_corto) + (state["con_away"] * (1 - alfa_corto)), 3)
            state["p_away"] += 1

    if not dry_run:
        cur.execute("""
            UPDATE historial_equipos SET
                ema_corto_favor_home=?, ema_corto_contra_home=?, partidos_corto_home=?,
                ema_corto_favor_away=?, ema_corto_contra_away=?, partidos_corto_away=?,
                ultima_actualizacion=?
            WHERE equipo_norm=? AND liga=?
        """, (
            state["fav_home"], state["con_home"], state["p_home"],
            state["fav_away"], state["con_away"], state["p_away"],
            date.today().strftime("%Y-%m-%d"),
            eq_norm, liga,
        ))

    return {
        "equipo": equipo_real, "liga": liga,
        "alfa_corto": alfa_corto, "alfa_largo": alfa_largo,
        "n_partidos": len(partidos), "n_home": state["p_home"], "n_away": state["p_away"],
        "seed": seed_inicial, "final": dict(state),
        "es_fallback_puro": (state["p_home"] + state["p_away"]) == 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada; solo imprime resumen.")
    parser.add_argument("--auto", action="store_true", help="Aplica el backfill y commitea.")
    parser.add_argument("--verbose", action="store_true", help="Imprime cada equipo procesado.")
    args = parser.parse_args()

    if not args.dry_run and not args.auto:
        print("[ERROR] Especificá --dry-run o --auto.")
        sys.exit(1)

    conn = sqlite3.connect(DB_NAME)
    targets = descubrir_targets(conn)
    print(f"[BACKFILL EMA-CORTO {'DRY-RUN' if args.dry_run else 'APPLY'}] Targets: {len(targets)}")
    print()

    n_ok, n_fallback, n_skip = 0, 0, 0
    n_modulado = 0
    delta_max_eq = None
    delta_max_val = 0.0
    breakdown_liga = {}

    for nombre, liga in targets:
        result = backfill_ema_corto_uno(conn, nombre, liga, dry_run=args.dry_run)
        if result is None:
            n_skip += 1
            print(f"  SKIP: {nombre} ({liga}) — no existe en historial_equipos")
            continue
        n_ok += 1
        if result["es_fallback_puro"]:
            n_fallback += 1
        else:
            seed_h = result["seed"]["fav_home"]
            final_h = result["final"]["fav_home"]
            delta = abs(final_h - seed_h)
            if delta > 0.001:
                n_modulado += 1
            if delta > delta_max_val:
                delta_max_val = delta
                delta_max_eq = (nombre, liga, seed_h, final_h)
        breakdown_liga[liga] = breakdown_liga.get(liga, 0) + 1
        if args.verbose:
            print(f"  {nombre:<30s} ({liga:<10s}) | alfa_corto={result['alfa_corto']:.2f} | "
                  f"N_h={result['n_home']} N_a={result['n_away']} | "
                  f"seed_fav_h={result['seed']['fav_home']:.3f} -> final={result['final']['fav_home']:.3f}")

    if not args.dry_run:
        conn.commit()
        print(f"[OK] Backfill aplicado + commit.")
    else:
        print(f"[DRY-RUN] Sin commit.")
    print()
    print(f"=== RESUMEN ===")
    print(f"Targets descubiertos       : {len(targets)}")
    print(f"Backfilleados con exito    : {n_ok}")
    print(f"Skip (no en historial)     : {n_skip}")
    print(f"Fallback puro (N=0 partidos usables, ema_corto = ema_largo): {n_fallback}")
    print(f"Modulados (ema_corto != ema_largo, delta_fav_h > 0.001)    : {n_modulado}")
    if delta_max_eq:
        eq, lg, s, f = delta_max_eq
        print(f"Mayor modulacion fav_home  : {eq} ({lg}) seed={s:.3f} -> final={f:.3f} (delta={delta_max_val:.3f})")
    print()
    print(f"Breakdown por liga:")
    for liga in sorted(breakdown_liga):
        print(f"  {liga:<15s} {breakdown_liga[liga]}")
    conn.close()


if __name__ == "__main__":
    main()

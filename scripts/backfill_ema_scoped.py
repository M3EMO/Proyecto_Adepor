"""
Backfill scoped de EMA en historial_equipos.

Reconstruye las 4 entradas faltantes (Everton Inglaterra/Chile,
Liverpool Inglaterra/Uruguay) desde partidos_backtest sin tocar
ema_procesados ni los EMAs de los rivales.

Usa las stats crudas ya persistidas en partidos_backtest
(sot_l/v, shots_l/v, corners_l/v, goles_l/v) + las funciones
calcular_xg_hibrido/ajustar_xg_por_estado_juego importadas de motor_data.

Replica la formula de EMA + ancla Bayesiana de motor_data.actualizar_estado,
pero aplicada solo al equipo target en cada match (el rival queda intacto).

Uso:
    py scripts/backfill_ema_scoped.py --dry-run   # muestra EMA calculada sin escribir
    py scripts/backfill_ema_scoped.py             # aplica y commitea
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
    ALFA_EMA, ALFA_EMA_POR_LIGA, N0_ANCLA, get_param,
)
from src.comun.config_sistema import DB_NAME
from src.comun.gestor_nombres import limpiar_texto


TARGETS = [
    ("Everton",   "Inglaterra"),
    ("Everton",   "Chile"),
    ("Liverpool", "Inglaterra"),
    ("Liverpool", "Uruguay"),
]


def _stats_desde_row(sot, corn, shots):
    """Recontruye el formato lista-de-dicts que calcular_xg_hibrido espera."""
    return [
        {"name": "shotsOnTarget", "displayValue": sot or 0},
        {"name": "wonCorners",    "displayValue": corn or 0},
        {"name": "totalShots",    "displayValue": shots or 0},
    ]


def _promedio_goles_liga(cur, liga):
    cur.execute("""
        SELECT AVG(goles_l + goles_v)
        FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """, (liga,))
    r = cur.fetchone()
    return float(r[0]) if r and r[0] is not None else 1.4


def _coef_corner_liga(cur, liga):
    cur.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga=?", (liga,))
    r = cur.fetchone()
    return float(r[0]) if r and r[0] is not None else 0.02


def backfill_uno(conn, nombre_oficial, liga, dry_run=False):
    cur = conn.cursor()
    eq_norm = limpiar_texto(nombre_oficial)
    alfa = get_param("alfa_ema", scope=liga, default=ALFA_EMA_POR_LIGA.get(liga, ALFA_EMA))
    coef_corner = _coef_corner_liga(cur, liga)
    promedio_liga = _promedio_goles_liga(cur, liga)

    # Estado inicial idéntico a motor_data (1.4 / 0.1).
    state = {
        "fav_home": 1.4, "con_home": 1.4, "p_home": 0,
        "fav_away": 1.4, "con_away": 1.4, "p_away": 0,
        "var_fh": 0.1, "var_ch": 0.1, "var_fa": 0.1, "var_ca": 0.1,
    }

    cur.execute("""
        SELECT id_partido, fecha, local, visita, goles_l, goles_v,
               sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado'
          AND (local=? OR visita=?)
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
        ORDER BY fecha ASC
    """, (liga, nombre_oficial, nombre_oficial))
    partidos = cur.fetchall()

    descartados_sin_stats = cur.execute("""
        SELECT COUNT(*) FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado'
          AND (local=? OR visita=?)
          AND (sot_l IS NULL OR sot_v IS NULL)
    """, (liga, nombre_oficial, nombre_oficial)).fetchone()[0]

    for p in partidos:
        _, _, local, visita, goles_l, goles_v, sot_l, shots_l, corn_l, sot_v, shots_v, corn_v = p
        is_home = (local == nombre_oficial)

        stats_loc = _stats_desde_row(sot_l, corn_l, shots_l)
        stats_vis = _stats_desde_row(sot_v, corn_v, shots_v)

        xg_loc_crudo = calcular_xg_hibrido(stats_loc, goles_l, coef_corner, pais=liga)
        xg_vis_crudo = calcular_xg_hibrido(stats_vis, goles_v, coef_corner, pais=liga)
        xg_loc = ajustar_xg_por_estado_juego(xg_loc_crudo, goles_l, goles_v)
        xg_vis = ajustar_xg_por_estado_juego(xg_vis_crudo, goles_v, goles_l)

        if is_home:
            xg_f, xg_c = xg_loc, xg_vis
            viejo_fav, viejo_con = state["fav_home"], state["con_home"]
            error_fav, error_con = xg_f - viejo_fav, xg_c - viejo_con
            state["var_fh"] = (error_fav ** 2 * alfa) + (state["var_fh"] * (1 - alfa))
            state["var_ch"] = (error_con ** 2 * alfa) + (state["var_ch"] * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N = state["p_home"]
            w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
            w_ema = 1.0 - w_liga
            state["fav_home"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            state["con_home"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            state["p_home"] += 1
        else:
            xg_f, xg_c = xg_vis, xg_loc
            viejo_fav, viejo_con = state["fav_away"], state["con_away"]
            error_fav, error_con = xg_f - viejo_fav, xg_c - viejo_con
            state["var_fa"] = (error_fav ** 2 * alfa) + (state["var_fa"] * (1 - alfa))
            state["var_ca"] = (error_con ** 2 * alfa) + (state["var_ca"] * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N = state["p_away"]
            w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
            w_ema = 1.0 - w_liga
            state["fav_away"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            state["con_away"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            state["p_away"] += 1

    print(f"  {nombre_oficial:<15s}/{liga:<12s}  alfa={alfa}  prom_liga={promedio_liga:.3f}  coef_corner={coef_corner:.4f}")
    print(f"    partidos usados: N_home={state['p_home']}  N_away={state['p_away']}  "
          f"(descartados sin stats: {descartados_sin_stats})")
    print(f"    EMA home:  fav={state['fav_home']}  con={state['con_home']}  var_fh={round(state['var_fh'],4)}  var_ch={round(state['var_ch'],4)}")
    print(f"    EMA away:  fav={state['fav_away']}  con={state['con_away']}  var_fa={round(state['var_fa'],4)}  var_ca={round(state['var_ca'],4)}")

    if dry_run:
        return state

    if state["p_home"] + state["p_away"] == 0:
        print(f"    SKIP: 0 partidos usables, no se inserta row.")
        return state

    cur.execute("""
        INSERT INTO historial_equipos (
            equipo_norm, equipo_real, liga, ultima_actualizacion,
            ema_xg_favor_home, ema_xg_contra_home, partidos_home,
            ema_xg_favor_away, ema_xg_contra_away, partidos_away,
            ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(equipo_norm, liga) DO UPDATE SET
            equipo_real=excluded.equipo_real, ultima_actualizacion=excluded.ultima_actualizacion,
            ema_xg_favor_home=excluded.ema_xg_favor_home,
            ema_xg_contra_home=excluded.ema_xg_contra_home,
            partidos_home=excluded.partidos_home,
            ema_xg_favor_away=excluded.ema_xg_favor_away,
            ema_xg_contra_away=excluded.ema_xg_contra_away,
            partidos_away=excluded.partidos_away,
            ema_var_favor_home=excluded.ema_var_favor_home,
            ema_var_contra_home=excluded.ema_var_contra_home,
            ema_var_favor_away=excluded.ema_var_favor_away,
            ema_var_contra_away=excluded.ema_var_contra_away
    """, (
        eq_norm, nombre_oficial, liga, date.today().strftime("%Y-%m-%d"),
        state["fav_home"], state["con_home"], state["p_home"],
        state["fav_away"], state["con_away"], state["p_away"],
        state["var_fh"], state["var_ch"], state["var_fa"], state["var_ca"],
    ))
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada; solo imprime.")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_NAME)
    print(f"[BACKFILL {'DRY-RUN' if args.dry_run else 'APPLY'}] Targets: {len(TARGETS)}")
    print()
    for nombre, liga in TARGETS:
        backfill_uno(conn, nombre, liga, dry_run=args.dry_run)
        print()
    if not args.dry_run:
        conn.commit()
        print("[OK] Backfill aplicado + commit.")
    conn.close()


if __name__ == "__main__":
    main()

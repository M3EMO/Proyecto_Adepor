"""
Backfill scoped de EMA en historial_equipos.

Reconstruye entradas con N bajo (defaults o casi) desde partidos_backtest
sin tocar ema_procesados ni los EMAs de los rivales.

Usa las stats crudas ya persistidas en partidos_backtest
(sot_l/v, shots_l/v, corners_l/v, goles_l/v) + las funciones
calcular_xg_hibrido/ajustar_xg_por_estado_juego importadas de motor_data.

Replica la formula de EMA + ancla Bayesiana de motor_data.actualizar_estado,
pero aplicada solo al equipo target en cada match (el rival queda intacto).

ARQUITECTURA --auto (dual mode):
- ESTRICTO (produccion): rows con default real — partidos_home==0 AND fav_home==1.4,
  o lo mismo en away. Solo aqui se escribe a historial_equipos. Cambio quirurgico.
- LAXO (shadow): rows con N<5 + >=3 partidos con stats. PRE/POST se loggea a
  backfill_ema_shadow_log con flag aplicado_produccion=0 y razon. NO escribe a
  historial_equipos. Util para auditoria longitudinal y eventual recalibracion.

Uso:
    py scripts/backfill_ema_scoped.py --dry-run   # TARGETS hardcoded, sin escribir
    py scripts/backfill_ema_scoped.py             # TARGETS hardcoded, aplica y commitea
    py scripts/backfill_ema_scoped.py --auto --dry-run  # auto-discover dual, sin escribir
    py scripts/backfill_ema_scoped.py --auto      # auto-discover dual: estricto a prod, laxo a shadow
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


def descubrir_targets_estricto(conn):
    """Auto-discovery ESTRICTO (produccion): rows con default real en home o away.

    Default real = (partidos_home==0 AND fav_home==1.4 AND con_home==1.4) o lo mismo
    en away. Estos son los rows que verdaderamente nunca recibieron datos del motor.
    Tambien exigimos >=3 partidos con stats en partidos_backtest para reconstruir
    la EMA con minima fiabilidad.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT he.equipo_real, he.liga
        FROM historial_equipos he
        WHERE he.equipo_real IS NOT NULL
          AND (
            (he.partidos_home = 0 AND he.ema_xg_favor_home = 1.4 AND he.ema_xg_contra_home = 1.4)
            OR
            (he.partidos_away = 0 AND he.ema_xg_favor_away = 1.4 AND he.ema_xg_contra_away = 1.4)
          )
          AND (
            SELECT COUNT(*) FROM partidos_backtest pb
            WHERE pb.pais = he.liga AND pb.estado = 'Liquidado'
              AND (pb.local = he.equipo_real OR pb.visita = he.equipo_real)
              AND pb.sot_l IS NOT NULL AND pb.sot_v IS NOT NULL
          ) >= 3
        ORDER BY he.liga, he.equipo_real
    """)
    return [(r[0], r[1]) for r in cur.fetchall()]


def descubrir_targets_laxo(conn):
    """Auto-discovery LAXO (shadow): pares (equipo_real, liga) con N<5 y >=3 partidos con stats.

    Set ampliado para auditoria. Incluye rows con N bajo pero sin defaults puros
    (cambios marginales o no-ops). Nunca se aplica a produccion; solo se loggea.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT he.equipo_real, he.liga
        FROM historial_equipos he
        WHERE (he.partidos_home + he.partidos_away) < 5
          AND he.equipo_real IS NOT NULL
          AND (
            SELECT COUNT(*) FROM partidos_backtest pb
            WHERE pb.pais = he.liga AND pb.estado = 'Liquidado'
              AND (pb.local = he.equipo_real OR pb.visita = he.equipo_real)
              AND pb.sot_l IS NOT NULL AND pb.sot_v IS NOT NULL
          ) >= 3
        ORDER BY he.liga, he.equipo_real
    """)
    return [(r[0], r[1]) for r in cur.fetchall()]


def loggear_shadow(conn, modo, equipo_real, liga, aplicado, razon, pre, state, descartados):
    """Inserta una fila en backfill_ema_shadow_log con PRE/POST + deltas."""
    from datetime import datetime
    cur = conn.cursor()
    fav_h_pre = pre["fav_h"] if pre else None
    con_h_pre = pre["con_h"] if pre else None
    fav_a_pre = pre["fav_a"] if pre else None
    con_a_pre = pre["con_a"] if pre else None
    n_h_pre   = pre["N_h"]   if pre else None
    n_a_pre   = pre["N_a"]   if pre else None
    delta_fav_h = round(state["fav_home"] - fav_h_pre, 4) if fav_h_pre is not None else None
    delta_con_h = round(state["con_home"] - con_h_pre, 4) if con_h_pre is not None else None
    delta_fav_a = round(state["fav_away"] - fav_a_pre, 4) if fav_a_pre is not None else None
    delta_con_a = round(state["con_away"] - con_a_pre, 4) if con_a_pre is not None else None
    cur.execute("""
        INSERT INTO backfill_ema_shadow_log (
            timestamp, modo, equipo_real, liga, aplicado_produccion, razon_no_aplicado,
            n_h_pre, n_a_pre, n_h_post, n_a_post,
            fav_h_pre, con_h_pre, fav_a_pre, con_a_pre,
            fav_h_post, con_h_post, fav_a_post, con_a_post,
            delta_fav_h, delta_con_h, delta_fav_a, delta_con_a,
            descartados_sin_stats
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(timespec="seconds"), modo, equipo_real, liga, aplicado, razon,
        n_h_pre, n_a_pre, state["p_home"], state["p_away"],
        fav_h_pre, con_h_pre, fav_a_pre, con_a_pre,
        state["fav_home"], state["con_home"], state["fav_away"], state["con_away"],
        delta_fav_h, delta_con_h, delta_fav_a, delta_con_a,
        descartados,
    ))


def _snapshot_row(cur, eq_norm, liga):
    cur.execute("""
        SELECT ema_xg_favor_home, ema_xg_contra_home, partidos_home,
               ema_xg_favor_away, ema_xg_contra_away, partidos_away
        FROM historial_equipos WHERE equipo_norm=? AND liga=?
    """, (eq_norm, liga))
    r = cur.fetchone()
    if r is None:
        return None
    return {"fav_h": r[0], "con_h": r[1], "N_h": r[2],
            "fav_a": r[3], "con_a": r[4], "N_a": r[5]}


def backfill_uno(conn, nombre_oficial, liga, dry_run=False):
    cur = conn.cursor()
    eq_norm = limpiar_texto(nombre_oficial)
    alfa = get_param("alfa_ema", scope=liga, default=ALFA_EMA_POR_LIGA.get(liga, ALFA_EMA))
    coef_corner = _coef_corner_liga(cur, liga)
    promedio_liga = _promedio_goles_liga(cur, liga)
    pre = _snapshot_row(cur, eq_norm, liga)

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

    print(f"  {nombre_oficial:<25s}/{liga:<12s}  alfa={alfa}  prom_liga={promedio_liga:.3f}  coef_corner={coef_corner:.4f}")
    print(f"    partidos usados: N_home={state['p_home']}  N_away={state['p_away']}  "
          f"(descartados sin stats: {descartados_sin_stats})")
    if pre is not None:
        print(f"    PRE   home: fav={pre['fav_h']} con={pre['con_h']} N={pre['N_h']}  "
              f"away: fav={pre['fav_a']} con={pre['con_a']} N={pre['N_a']}")
    else:
        print(f"    PRE   (row no existe en historial_equipos, se INSERTara)")
    print(f"    POST  home: fav={state['fav_home']} con={state['con_home']} N={state['p_home']}  "
          f"away: fav={state['fav_away']} con={state['con_away']} N={state['p_away']}")

    return state, pre, descartados_sin_stats


def escribir_historial(conn, eq_norm, nombre_oficial, liga, state):
    """UPSERT a historial_equipos. Llamar solo cuando esta decidido aplicar."""
    cur = conn.cursor()
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada; solo imprime.")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-discover dual: estricto a produccion + laxo a shadow.")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_NAME)

    # ---------- MODO HARDCODED (legacy) ----------
    if not args.auto:
        targets = TARGETS
        print(f"[BACKFILL HARDCODED {'DRY-RUN' if args.dry_run else 'APPLY'}] Targets: {len(targets)}")
        print()
        n_skip = 0
        for nombre, liga in targets:
            state, pre, descartados = backfill_uno(conn, nombre, liga, dry_run=args.dry_run)
            if state["p_home"] + state["p_away"] == 0:
                n_skip += 1
                print(f"    SKIP: 0 partidos usables, no se inserta row.")
            elif not args.dry_run:
                eq_norm = limpiar_texto(nombre)
                escribir_historial(conn, eq_norm, nombre, liga, state)
            print()
        if not args.dry_run:
            conn.commit()
            print(f"[OK] HARDCODED aplicado + commit. Targets: {len(targets)}  Skip: {n_skip}")
        else:
            print(f"[DRY-RUN] HARDCODED: {len(targets)}  Skip: {n_skip}")
        conn.close()
        return

    # ---------- MODO AUTO DUAL (estricto a prod + laxo a shadow) ----------
    targets_estrictos = descubrir_targets_estricto(conn)
    targets_laxos = descubrir_targets_laxo(conn)
    set_estrictos = set(targets_estrictos)
    targets_solo_shadow = [t for t in targets_laxos if t not in set_estrictos]

    print(f"[BACKFILL AUTO {'DRY-RUN' if args.dry_run else 'APPLY'}]")
    print(f"  ESTRICTO (a produccion):  {len(targets_estrictos)} targets — rows con default real")
    print(f"  LAXO     (solo a shadow): {len(targets_solo_shadow)} targets — N<5 sin defaults puros")
    print(f"  TOTAL                   : {len(targets_laxos)} targets descubiertos")

    if targets_laxos:
        breakdown = {}
        for _, liga in targets_laxos:
            breakdown[liga] = breakdown.get(liga, 0) + 1
        print(f"  Breakdown por liga (total):")
        for liga in sorted(breakdown):
            print(f"    {liga:<20s} {breakdown[liga]}")
    print()

    n_aplicados = 0
    n_skip_estricto = 0
    n_loggeados_shadow = 0

    # 1) ESTRICTOS: calcular, escribir a produccion, loggear a shadow con flag=1
    if targets_estrictos:
        print("=" * 70)
        print("[ESTRICTO] Aplicando a historial_equipos:")
        print("=" * 70)
        for nombre, liga in targets_estrictos:
            state, pre, descartados = backfill_uno(conn, nombre, liga, dry_run=args.dry_run)
            if state["p_home"] + state["p_away"] == 0:
                n_skip_estricto += 1
                print(f"    SKIP: 0 partidos usables, no se inserta.")
                if not args.dry_run:
                    loggear_shadow(conn, "auto", nombre, liga, 0,
                                   "skip_zero_partidos", pre, state, descartados)
                    n_loggeados_shadow += 1
            else:
                if not args.dry_run:
                    eq_norm = limpiar_texto(nombre)
                    escribir_historial(conn, eq_norm, nombre, liga, state)
                    loggear_shadow(conn, "auto", nombre, liga, 1, None, pre, state, descartados)
                    n_aplicados += 1
                    n_loggeados_shadow += 1
            print()

    # 2) LAXOS-no-estrictos: calcular, NO escribir a produccion, loggear a shadow con flag=0
    if targets_solo_shadow:
        print("=" * 70)
        print("[LAXO -> SHADOW] Solo se loggea (no escribe a produccion):")
        print("=" * 70)
        for nombre, liga in targets_solo_shadow:
            state, pre, descartados = backfill_uno(conn, nombre, liga, dry_run=args.dry_run)
            if not args.dry_run:
                # Razon: por que no se aplica? Si pre==post, no_op; si tiene N>0, no_default
                if (pre is not None
                    and pre["fav_h"] == state["fav_home"] and pre["con_h"] == state["con_home"]
                    and pre["fav_a"] == state["fav_away"] and pre["con_a"] == state["con_away"]):
                    razon = "no_op_pre_eq_post"
                else:
                    razon = "no_default_residual"
                loggear_shadow(conn, "auto", nombre, liga, 0, razon, pre, state, descartados)
                n_loggeados_shadow += 1
            print()

    if not args.dry_run:
        conn.commit()
        print("=" * 70)
        print(f"[OK] AUTO aplicado + commit.")
        print(f"     Aplicados a produccion: {n_aplicados} / {len(targets_estrictos)} (estrictos, skip={n_skip_estricto})")
        print(f"     Loggeados a shadow    : {n_loggeados_shadow} (estrictos + laxos)")
    else:
        print("=" * 70)
        print(f"[DRY-RUN] AUTO. Estrictos: {len(targets_estrictos)} (skip={n_skip_estricto}) | Solo-shadow: {len(targets_solo_shadow)}")
    conn.close()


if __name__ == "__main__":
    main()

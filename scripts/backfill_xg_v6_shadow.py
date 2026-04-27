"""[SHADOW V6 — adepor-d7h] Backfill EMA xG_v6 (recalibrado OLS) en historial_equipos_v6_shadow.

Pipeline:
  1. Leer partidos cronológicamente (partidos_historico_externo + partidos_backtest)
  2. Para cada partido con stats raw:
     - Construir stats al estilo ESPN
     - Calcular xg_v6 local/visita usando coefs OLS (calcular_xg_v6)
     - Aplicar ajuste por estado de juego (ajustar_xg_por_estado_juego)
     - Actualizar EMA home/away (favor + contra) en tabla shadow
  3. Persistir.

NO afecta producción: solo escribe a historial_equipos_v6_shadow.
Idempotente: borra contenido al inicio (REBUILD_YES=1 implícito por ser shadow).
"""
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingesta.motor_data import calcular_xg_v6, ajustar_xg_por_estado_juego
from src.comun.gestor_nombres import limpiar_texto

DB = ROOT / "fondo_quant.db"
ALFA_FALLBACK = 0.15


def get_alfa(cur, liga):
    """ALFA por liga desde config; fallback 0.15."""
    row = cur.execute(
        "SELECT valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND scope=?",
        (liga,)
    ).fetchone()
    if row and row[0] is not None:
        return float(row[0])
    row = cur.execute(
        "SELECT valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND scope='global'"
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else ALFA_FALLBACK


def stats_obj(sot, shots, corners):
    return [
        {'name': 'shotsOnTarget', 'displayValue': str(sot or 0)},
        {'name': 'totalShots', 'displayValue': str(shots or 0)},
        {'name': 'wonCorners', 'displayValue': str(corners or 0)},
    ]


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    print("=" * 95)
    print("BACKFILL xG V6 SHADOW — adepor-d7h")
    print("=" * 95)

    # Wipe shadow table (full rebuild every run — coherente con shadow)
    cur.execute("DELETE FROM historial_equipos_v6_shadow")
    print("[WIPE] historial_equipos_v6_shadow vaciada.")

    # Cargar partidos cronológicamente desde ambas fuentes
    rows = []

    # Fuente 1: partidos_historico_externo (10 ligas EUR + LATAM full_stats)
    cur.execute("""
        SELECT liga, ht, at, hst, hs, hc, ast, as_, ac, hg, ag, fecha
        FROM partidos_historico_externo
        WHERE has_full_stats = 1
          AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
        ORDER BY fecha ASC
    """)
    n_hist = 0
    for r in cur.fetchall():
        rows.append(('historico_ext', *r))
        n_hist += 1
    print(f"[FUENTE 1] partidos_historico_externo: {n_hist:>5d} partidos")

    # Fuente 2: partidos_backtest (motor real reciente, stats raw)
    cur.execute("""
        SELECT pais, local, visita, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v, goles_l, goles_v, fecha
        FROM partidos_backtest
        WHERE sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        ORDER BY fecha ASC
    """)
    n_back = 0
    for r in cur.fetchall():
        rows.append(('backtest', *r))
        n_back += 1
    print(f"[FUENTE 2] partidos_backtest:           {n_back:>5d} partidos")

    # Re-ordenar global por fecha
    rows.sort(key=lambda x: x[12])  # x[12] = fecha (índice tras el tag fuente)
    print(f"[TOTAL]   {len(rows)} partidos cronológicos\n")

    # Cache ALFA por liga + estado equipos en memoria (evita roundtrips)
    alfa_cache = {}
    estado = defaultdict(lambda: {
        'equipo_real': None, 'liga': None,
        'ema_fav_home': None, 'ema_con_home': None, 'n_home': 0,
        'ema_fav_away': None, 'ema_con_away': None, 'n_away': 0,
        'ult_partido': None,
    })

    n_proc = 0
    n_skip = 0

    for fuente, liga, ht, at, hst, hs, hc, ast, as_, ac, hg, ag, fecha in rows:
        if liga not in alfa_cache:
            alfa_cache[liga] = get_alfa(cur, liga)
        alfa = alfa_cache[liga]

        # Limpieza de nombres (encoding raro en historico_externo se neutraliza)
        ht_norm = limpiar_texto(ht)
        at_norm = limpiar_texto(at)
        if not ht_norm or not at_norm:
            n_skip += 1
            continue

        # Calcular xG_v6 ambos equipos
        stats_l = stats_obj(hst, hs, hc)
        stats_v = stats_obj(ast, as_, ac)
        xg_v6_l = calcular_xg_v6(stats_l, hg, liga=liga, conn=conn)
        xg_v6_v = calcular_xg_v6(stats_v, ag, liga=liga, conn=conn)

        # Score effects
        xg_v6_l_aj = ajustar_xg_por_estado_juego(xg_v6_l, hg, ag)
        xg_v6_v_aj = ajustar_xg_por_estado_juego(xg_v6_v, ag, hg)

        # Update EMAs HOME (local) y AWAY (visita)
        e_l = estado[ht_norm]
        if e_l['equipo_real'] is None:
            e_l['equipo_real'] = ht
            e_l['liga'] = liga
        # Local juega home: actualiza fav_home con xg_v6_l, contra_home con xg_v6_v
        if e_l['ema_fav_home'] is None:
            e_l['ema_fav_home'] = xg_v6_l_aj
            e_l['ema_con_home'] = xg_v6_v_aj
        else:
            e_l['ema_fav_home'] = alfa * xg_v6_l_aj + (1 - alfa) * e_l['ema_fav_home']
            e_l['ema_con_home'] = alfa * xg_v6_v_aj + (1 - alfa) * e_l['ema_con_home']
        e_l['n_home'] += 1
        e_l['ult_partido'] = fecha

        e_v = estado[at_norm]
        if e_v['equipo_real'] is None:
            e_v['equipo_real'] = at
            e_v['liga'] = liga
        # Visita juega away: actualiza fav_away con xg_v6_v, contra_away con xg_v6_l
        if e_v['ema_fav_away'] is None:
            e_v['ema_fav_away'] = xg_v6_v_aj
            e_v['ema_con_away'] = xg_v6_l_aj
        else:
            e_v['ema_fav_away'] = alfa * xg_v6_v_aj + (1 - alfa) * e_v['ema_fav_away']
            e_v['ema_con_away'] = alfa * xg_v6_l_aj + (1 - alfa) * e_v['ema_con_away']
        e_v['n_away'] += 1
        e_v['ult_partido'] = fecha

        n_proc += 1
        if n_proc % 2000 == 0:
            print(f"  [{n_proc:>5d}/{len(rows)}] procesados...")

    print(f"\n[PROC] {n_proc} partidos procesados, {n_skip} skip (nombre vacío)")
    print(f"[EQUIPOS] {len(estado)} equipos únicos en EMA shadow")

    # Persistir
    ts = datetime.now().isoformat()
    n_insert = 0
    for equipo_norm, e in estado.items():
        if e['n_home'] == 0 and e['n_away'] == 0:
            continue
        cur.execute("""
            INSERT OR REPLACE INTO historial_equipos_v6_shadow
            (equipo_norm, equipo_real, liga,
             ema_xg_v6_favor_home, ema_xg_v6_contra_home, partidos_v6_home,
             ema_xg_v6_favor_away, ema_xg_v6_contra_away, partidos_v6_away,
             ultima_actualizacion, ultimo_partido_procesado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (equipo_norm, e['equipo_real'], e['liga'],
              e['ema_fav_home'], e['ema_con_home'], e['n_home'],
              e['ema_fav_away'], e['ema_con_away'], e['n_away'],
              ts, e['ult_partido']))
        n_insert += 1

    conn.commit()
    print(f"\n[INSERT] {n_insert} filas en historial_equipos_v6_shadow")

    # Sanity check: distribución por liga
    print("\n=== Distribución por liga ===")
    print(f"{'liga':<13s} {'equipos':>8s} {'avg_n_home':>10s} {'avg_xg_fav_home':>16s}")
    for liga, n_eq, avg_h, avg_xg in cur.execute("""
        SELECT liga, COUNT(*),
               ROUND(AVG(partidos_v6_home), 1),
               ROUND(AVG(ema_xg_v6_favor_home), 3)
        FROM historial_equipos_v6_shadow
        WHERE liga IS NOT NULL
        GROUP BY liga
        ORDER BY liga
    """):
        print(f"{liga:<13s} {n_eq:>8d} {avg_h:>10.1f} {avg_xg:>16.3f}")

    conn.close()
    print("\n[DONE] Backfill xG V6 shadow completo.")


if __name__ == "__main__":
    main()

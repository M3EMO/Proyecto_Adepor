"""
Rebuild COMPLETO de historial_equipos con V2 hybrid SOFA.

Procesa cronológicamente TODOS los partidos liquidados con xG V2 (cuando SOFA
disponible) o V0 (fallback automático). Reconstruye EMAs desde cero.

Idempotente respecto a otros scripts (no toca tablas paralelas como
historial_equipos_v6_shadow). Solo reconstruye historial_equipos.

NO consume API SOFA — usa data persistida en sofascore_match_features.

Modo:
  --dry-run         no escribe, solo print stats
  --backup          crea snapshot DB pre-rebuild
  --liga X          restringir a una liga
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.config_sistema import DB_NAME
from src.comun.config_motor import get_param
from src.comun.tipos import safe_int
from src.comun import gestor_nombres

DB = ROOT / DB_NAME

ALFA_EMA_POR_LIGA = {
    "Brasil": 0.20, "Turquia": 0.20, "Noruega": 0.18,
    "Argentina": 0.15, "Inglaterra": 0.12,
}
N0_ANCLA = 5


def _stats_desde_row(sot, corn, shots):
    return [
        {"name": "shotsOnTarget", "displayValue": str(sot or 0)},
        {"name": "wonCorners", "displayValue": str(corn or 0)},
        {"name": "totalShots", "displayValue": str(shots or 0)},
    ]


def _ajustar_xg_por_estado(xg, goles_propio, goles_rival):
    """Réplica motor_data.ajustar_xg_por_estado_juego — score effects ajuste."""
    if goles_propio > goles_rival:
        return xg * 0.95   # ganando: leve descuento
    elif goles_propio < goles_rival:
        return xg * 1.05   # perdiendo: leve aumento
    return xg


def _coef_corner_liga(cur, liga):
    r = cur.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga=?", (liga,)).fetchone()
    return r[0] if r and r[0] is not None else 0.03


def _promedio_goles_liga(cur, liga):
    r = cur.execute("""
        SELECT AVG(goles_l + goles_v) FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """, (liga,)).fetchone()
    return r[0] if r and r[0] else 2.6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--backup', action='store_true')
    parser.add_argument('--liga', type=str, default=None)
    args = parser.parse_args()

    # Snapshot
    if args.backup and not args.dry_run:
        import shutil
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = ROOT / 'snapshots' / f'fondo_quant_{ts}_pre_rebuild_ema_v2.db'
        shutil.copy2(str(DB), str(backup_path))
        print(f'Snapshot: {backup_path.name}')

    conn = sqlite3.connect(str(DB))

    # Importar V2 después de tener conn
    from src.ingesta.motor_data import calcular_xg_v2_hibrido_sofa, calcular_xg_hibrido

    cur = conn.cursor()

    # Verificar modo
    modo = cur.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='xg_v2_hibrido_modo'").fetchone()
    if modo:
        print(f'Modo xg_v2_hibrido: {modo[0]}')

    # Cargar partidos liquidados cronológicamente, optionally filtrar liga
    where_liga = ''
    params = []
    if args.liga:
        where_liga = ' AND pais = ?'
        params.append(args.liga)

    partidos = cur.execute(f'''
        SELECT id_partido, fecha, pais, local, visita, goles_l, goles_v,
               sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
          {where_liga}
        ORDER BY fecha ASC
    ''', params).fetchall()
    print(f'Partidos liquidados a procesar: {len(partidos)}')

    # Estado por equipo (FRESH START)
    state = defaultdict(lambda: {
        'fav_h': 1.4, 'con_h': 1.4, 'p_h': 0,
        'fav_a': 1.4, 'con_a': 1.4, 'p_a': 0,
        'var_fh': 0.1, 'var_ch': 0.1, 'var_fa': 0.1, 'var_ca': 0.1,
    })

    # Promedio liga (cache)
    prom_liga_cache = {}
    coef_corner_cache = {}

    # Process
    n_v2_used = 0
    n_v0_fallback = 0
    by_liga = defaultdict(int)

    for p in partidos:
        id_p, fecha, liga, local, visita, gol_l, gol_v, sot_l, shots_l, corn_l, sot_v, shots_v, corn_v = p

        if liga not in prom_liga_cache:
            prom_liga_cache[liga] = _promedio_goles_liga(cur, liga)
        if liga not in coef_corner_cache:
            coef_corner_cache[liga] = _coef_corner_liga(cur, liga)

        prom_liga = prom_liga_cache[liga]
        coef_corner = coef_corner_cache[liga]
        alfa = ALFA_EMA_POR_LIGA.get(liga, 0.15)

        stats_loc = _stats_desde_row(sot_l, corn_l, shots_l)
        stats_vis = _stats_desde_row(sot_v, corn_v, shots_v)

        # V2 hybrid (con fallback automático V0)
        xg_loc_crudo = calcular_xg_v2_hibrido_sofa(
            stats_loc, gol_l, liga=liga, coef_corner_liga=coef_corner,
            conn=conn, fecha=fecha, ht=local, at=visita, es_local=True
        )
        xg_vis_crudo = calcular_xg_v2_hibrido_sofa(
            stats_vis, gol_v, liga=liga, coef_corner_liga=coef_corner,
            conn=conn, fecha=fecha, ht=local, at=visita, es_local=False
        )

        # Detectar si SOFA fue usado (heurística: si V2 != V0 entonces SOFA aplicó)
        v0_l = calcular_xg_hibrido(stats_loc, gol_l, coef_corner, pais=liga)
        if abs(xg_loc_crudo - v0_l) > 0.001:
            n_v2_used += 1
            by_liga[liga] += 1
        else:
            n_v0_fallback += 1

        # Score effects
        xg_loc = _ajustar_xg_por_estado(xg_loc_crudo, gol_l, gol_v)
        xg_vis = _ajustar_xg_por_estado(xg_vis_crudo, gol_v, gol_l)

        # Update LOCAL state (home perspective)
        eq_l = gestor_nombres.limpiar_texto(local)
        s = state[(eq_l, liga)]
        viejo_fav, viejo_con = s['fav_h'], s['con_h']
        err_f, err_c = xg_loc - viejo_fav, xg_vis - viejo_con
        s['var_fh'] = (err_f ** 2 * alfa) + (s['var_fh'] * (1 - alfa))
        s['var_ch'] = (err_c ** 2 * alfa) + (s['var_ch'] * (1 - alfa))
        nuevo_fav = xg_loc * alfa + viejo_fav * (1 - alfa)
        nuevo_con = xg_vis * alfa + viejo_con * (1 - alfa)
        N = s['p_h']
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        s['fav_h'] = round(w_ema * nuevo_fav + w_liga * prom_liga, 3)
        s['con_h'] = round(w_ema * nuevo_con + w_liga * prom_liga, 3)
        s['p_h'] += 1

        # Update VISITA state (away perspective)
        eq_v = gestor_nombres.limpiar_texto(visita)
        s = state[(eq_v, liga)]
        viejo_fav, viejo_con = s['fav_a'], s['con_a']
        err_f, err_c = xg_vis - viejo_fav, xg_loc - viejo_con
        s['var_fa'] = (err_f ** 2 * alfa) + (s['var_fa'] * (1 - alfa))
        s['var_ca'] = (err_c ** 2 * alfa) + (s['var_ca'] * (1 - alfa))
        nuevo_fav = xg_vis * alfa + viejo_fav * (1 - alfa)
        nuevo_con = xg_loc * alfa + viejo_con * (1 - alfa)
        N = s['p_a']
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        s['fav_a'] = round(w_ema * nuevo_fav + w_liga * prom_liga, 3)
        s['con_a'] = round(w_ema * nuevo_con + w_liga * prom_liga, 3)
        s['p_a'] += 1

    print(f'\n=== RESULTADOS ===')
    print(f'Partidos procesados: {len(partidos)}')
    print(f'Eventos con V2 (SOFA matched): {n_v2_used}')
    print(f'Eventos con V0 fallback: {n_v0_fallback}')
    print(f'Equipos con state nuevo: {len(state)}')
    print(f'\nPor liga (V2 used events):')
    for liga, n in sorted(by_liga.items(), key=lambda x: -x[1]):
        print(f'  {liga:<14s} {n:>5d}')

    # Persistir
    if args.dry_run:
        print('\n[DRY-RUN] No escribiendo a DB')
        # Sample para inspección
        print('\nSample state final (5 equipos):')
        for k, s in list(state.items())[:5]:
            print(f'  {k}: fav_h={s["fav_h"]} con_h={s["con_h"]} N_h={s["p_h"]} | fav_a={s["fav_a"]} con_a={s["con_a"]} N_a={s["p_a"]}')
    else:
        n_upd = 0
        for (eq_norm, liga), s in state.items():
            cur.execute('''
                UPDATE historial_equipos
                SET ema_xg_favor_home=?, ema_xg_contra_home=?, partidos_home=?,
                    ema_xg_favor_away=?, ema_xg_contra_away=?, partidos_away=?,
                    ema_var_favor_home=?, ema_var_contra_home=?,
                    ema_var_favor_away=?, ema_var_contra_away=?,
                    ultima_actualizacion=?
                WHERE equipo_norm=? AND liga=?
            ''', (s['fav_h'], s['con_h'], s['p_h'],
                  s['fav_a'], s['con_a'], s['p_a'],
                  s['var_fh'], s['var_ch'], s['var_fa'], s['var_ca'],
                  datetime.now().isoformat(), eq_norm, liga))
            n_upd += cur.rowcount
        conn.commit()
        print(f'\nUpdated {n_upd} rows en historial_equipos')

    conn.close()


if __name__ == '__main__':
    main()

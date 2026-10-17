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


def _promedio_goles_liga(cur, liga, por_equipo=False):
    """Prior de las EMAs. por_equipo=True divide por 2: las EMAs son xG de UN equipo
    y AVG(goles_l + goles_v) es por partido (ver motor_data.prior_liga_por_equipo)."""
    r = cur.execute("""
        SELECT AVG(goles_l + goles_v) FROM partidos_backtest
        WHERE pais=? AND estado='Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """, (liga,)).fetchone()
    por_partido = r[0] if r and r[0] else 2.6
    return por_partido / 2.0 if por_equipo else por_partido


def _prior_por_equipo_activo():
    return str(get_param('ema_prior_por_equipo', default='FALSE')).upper() in ('TRUE', '1')


def cargar_partidos(cur, liga=None):
    where_liga, params = ('', [])
    if liga:
        where_liga, params = (' AND pais = ?', [liga])
    return cur.execute(f'''
        SELECT id_partido, fecha, pais, local, visita, goles_l, goles_v,
               sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
          {where_liga}
        ORDER BY fecha ASC
    ''', params).fetchall()


def _actualizar_lado(s, sufijo, xg_f, xg_c, alfa, prom_liga):
    """EMA + varianza + ancla bayesiana para un lado ('h' local, 'a' visita)."""
    var_f, var_c = ('var_fh', 'var_ch') if sufijo == 'h' else ('var_fa', 'var_ca')
    fav, con, n = f'fav_{sufijo}', f'con_{sufijo}', f'p_{sufijo}'
    viejo_fav, viejo_con = s[fav], s[con]
    s[var_f] = ((xg_f - viejo_fav) ** 2 * alfa) + (s[var_f] * (1 - alfa))
    s[var_c] = ((xg_c - viejo_con) ** 2 * alfa) + (s[var_c] * (1 - alfa))
    nuevo_fav = xg_f * alfa + viejo_fav * (1 - alfa)
    nuevo_con = xg_c * alfa + viejo_con * (1 - alfa)
    w_liga = N0_ANCLA / (N0_ANCLA + s[n])
    s[fav] = round((1.0 - w_liga) * nuevo_fav + w_liga * prom_liga, 3)
    s[con] = round((1.0 - w_liga) * nuevo_con + w_liga * prom_liga, 3)
    s[n] += 1


def reconstruir(conn, partidos, prior_por_equipo, antes_de_actualizar=None):
    """Replay cronologico de EMAs desde cero. Devuelve (state, stats).

    antes_de_actualizar(partido, st_local, st_visita) se llama con el estado AS-OF
    (antes de absorber el partido): permite evaluar walk-forward sin look-ahead.
    """
    from src.ingesta.motor_data import calcular_xg_v2_hibrido_sofa, calcular_xg_hibrido
    cur = conn.cursor()
    state = defaultdict(lambda: {
        'fav_h': 1.4, 'con_h': 1.4, 'p_h': 0,
        'fav_a': 1.4, 'con_a': 1.4, 'p_a': 0,
        'var_fh': 0.1, 'var_ch': 0.1, 'var_fa': 0.1, 'var_ca': 0.1,
    })
    prom_liga_cache, coef_corner_cache = {}, {}
    stats = {'v2': 0, 'v0': 0, 'by_liga': defaultdict(int)}
    for p in partidos:
        id_p, fecha, liga, local, visita, gol_l, gol_v, sot_l, shots_l, corn_l, sot_v, shots_v, corn_v = p
        if liga not in prom_liga_cache:
            prom_liga_cache[liga] = _promedio_goles_liga(cur, liga, prior_por_equipo)
            coef_corner_cache[liga] = _coef_corner_liga(cur, liga)
        prom_liga, coef_corner = prom_liga_cache[liga], coef_corner_cache[liga]
        alfa = ALFA_EMA_POR_LIGA.get(liga, 0.15)

        stats_loc = _stats_desde_row(sot_l, corn_l, shots_l)
        stats_vis = _stats_desde_row(sot_v, corn_v, shots_v)
        xg_loc_crudo = calcular_xg_v2_hibrido_sofa(
            stats_loc, gol_l, liga=liga, coef_corner_liga=coef_corner,
            conn=conn, fecha=fecha, ht=local, at=visita, es_local=True)
        xg_vis_crudo = calcular_xg_v2_hibrido_sofa(
            stats_vis, gol_v, liga=liga, coef_corner_liga=coef_corner,
            conn=conn, fecha=fecha, ht=local, at=visita, es_local=False)
        # Heuristica: si V2 != V0 entonces SOFA aplico
        if abs(xg_loc_crudo - calcular_xg_hibrido(stats_loc, gol_l, coef_corner, pais=liga)) > 0.001:
            stats['v2'] += 1
            stats['by_liga'][liga] += 1
        else:
            stats['v0'] += 1
        xg_loc = _ajustar_xg_por_estado(xg_loc_crudo, gol_l, gol_v)
        xg_vis = _ajustar_xg_por_estado(xg_vis_crudo, gol_v, gol_l)

        st_l = state[(gestor_nombres.limpiar_texto(local), liga)]
        st_v = state[(gestor_nombres.limpiar_texto(visita), liga)]
        if antes_de_actualizar is not None:
            antes_de_actualizar(p, st_l, st_v)
        _actualizar_lado(st_l, 'h', xg_loc, xg_vis, alfa, prom_liga)
        _actualizar_lado(st_v, 'a', xg_vis, xg_loc, alfa, prom_liga)
    return state, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--backup', action='store_true')
    parser.add_argument('--liga', type=str, default=None)
    args = parser.parse_args()

    # Snapshot
    if args.backup and not args.dry_run:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = ROOT / 'snapshots' / f'fondo_quant_{ts}_pre_rebuild_ema_v2.db'
        backup_path.parent.mkdir(exist_ok=True)
        # API de backup: copy2 pierde las paginas que siguen en el -wal.
        with sqlite3.connect(str(DB)) as _src, sqlite3.connect(str(backup_path)) as _dst:
            _src.backup(_dst)
        print(f'Snapshot: {backup_path.name}')

    conn = sqlite3.connect(str(DB))

    cur = conn.cursor()

    # Verificar modo
    modo = cur.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='xg_v2_hibrido_modo'").fetchone()
    if modo:
        print(f'Modo xg_v2_hibrido: {modo[0]}')
    # Sin xG SOFA activo el rebuild solo reproduce V0 sobre partidos_backtest y pisa EMAs que
    # motor_data construyo con mas historia (en una DB nueva, el backfill ESPN no esta en
    # partidos_backtest): se perderia historia todos los dias.
    if not args.dry_run and (not modo or modo[0] != 'active'):
        print('[SKIP] xg_v2_hibrido_modo != active: EMAs de motor_data quedan intactas.')
        conn.close()
        return

    partidos = cargar_partidos(cur, args.liga)
    print(f'Partidos liquidados a procesar: {len(partidos)}')
    state, st = reconstruir(conn, partidos, _prior_por_equipo_activo())
    n_v2_used, n_v0_fallback, by_liga = st['v2'], st['v0'], st['by_liga']

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

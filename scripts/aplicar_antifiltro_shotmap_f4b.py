"""
Hook SHADOW — anti-filtro F4b shotmap.

F4b = "ema_sp_dep_v > 0.5 → NO apostar X" (visita set-piece dependent → empate destructivo)

Modo SHADOW (default): NO afecta producción. Solo loguea en
picks_shadow_antifiltro_f4b_runtime cuando el motor productivo genera pick='X'
en partidos donde la visita tiene set-piece dependency alta.

Modo ACTIVE (futuro, post N≥80 SHADOW válido): suprime pick='X' en partidos_backtest
y loguea con habria_sido_suprimido=1.

Trigger: tras motor_calculadora (FASE 3.7 sugerida).
Idempotente: skip si ya logueado.

Bead: shotmap_v1_F4b_anti (NO promoted to Manifesto, SHADOW only).

Validación POC original (sesión 2026-05-04 shotmap_v1):
  - N=13, yield=-77.2%, hit=8%, CI95=[-100%, -32%] (CI hi NEGATIVO sig al 5%)
  - ÚNICO filtro shotmap con CI95 hi < 0
  - LIMITACIÓN: N pequeño + walk-forward inter-año imposible (SOFA solo 2026)

Uso:
  py scripts/aplicar_antifiltro_shotmap_f4b.py             # auto: partidos_backtest sin liquidar
  py scripts/aplicar_antifiltro_shotmap_f4b.py --liquidados # post-liquidación: actualizar yield_real
  py scripts/aplicar_antifiltro_shotmap_f4b.py --dry-run
"""
import argparse
import sqlite3
import sys
import unicodedata
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analisis.aliases_sofa_espn import norm_team_name

DB = str(ROOT / 'fondo_quant.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--liquidados', action='store_true',
                       help='Actualizar yield_real para picks ya liquidados')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Leer config
    modo = cur.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='antifiltro_shotmap_f4b_modo'").fetchone()
    modo = modo[0] if modo else 'shadow'
    thr_row = cur.execute("SELECT valor_real FROM config_motor_valores WHERE clave='antifiltro_shotmap_f4b_threshold'").fetchone()
    threshold = thr_row[0] if thr_row else 0.5

    print(f'Modo: {modo} | Threshold: ema_sp_dep_v > {threshold}')

    if args.liquidados:
        # Path 2: actualizar yield_real para SHADOW logs ya escritos
        actualizar_liquidados(con, args.dry_run)
        return

    # Path 1: detectar picks=X que el filtro habría suprimido
    # 1. Cargar EMAs shotmap pre-partido (visitante con sp_dep > threshold)
    sp_dep_visitas = {}  # (liga, equipo_norm, fecha_anterior) -> ema_sp_dep_v + n_acum
    for r in cur.execute('''
        SELECT liga, equipo_norm, fecha, ema_sp_dep, n_acum
        FROM historial_equipos_shotmap_ema
        WHERE n_acum >= 3 AND ema_sp_dep IS NOT NULL AND es_local = 0
    '''):
        liga, eq_n, fecha, sp_dep, n_acum = r
        sp_dep_visitas[(liga, eq_n, fecha)] = (sp_dep, n_acum)
    print(f'Snapshots ema_sp_dep visita disponibles: {len(sp_dep_visitas)}')

    # 2. Cargar picks=X de partidos_backtest (estado en cualquier estado)
    picks_x = cur.execute('''
        SELECT id_partido, fecha, pais, local, visita, apuesta_1x2,
               cuota_x, prob_x, ev_empate, estado, goles_l, goles_v
        FROM partidos_backtest
        WHERE apuesta_1x2='X' OR (cuota_x IS NOT NULL AND prob_x IS NOT NULL)
    ''').fetchall()
    print(f'Partidos con info pick=X: {len(picks_x)}')

    # 3. Idempotencia: skip ya logueados
    existing = set()
    for r in cur.execute('SELECT liga, fecha, ht, at FROM picks_shadow_antifiltro_f4b_runtime'):
        existing.add(tuple(r))

    n_logged = 0
    n_skipped = 0
    n_no_match = 0
    ts_now = datetime.now().isoformat()

    for r in picks_x:
        id_p, fecha, liga, local, visita, apuesta, c_x, p_x, ev_x, estado, gl, gv = r
        equipo_n_visita = norm_team_name(visita, liga)
        if not equipo_n_visita:
            continue

        # Buscar EMA sp_dep visita (con tolerancia ±2 días para fechas)
        sp_dep_v = None
        n_acum_v = None
        sofa_eid = None
        try:
            d0 = datetime.fromisoformat(fecha).date()
            for delta in (0, -1, 1, -2, 2):
                fecha_alt = (d0 + timedelta(days=delta)).isoformat()
                key = (liga, equipo_n_visita, fecha_alt)
                if key in sp_dep_visitas:
                    sp_dep_v, n_acum_v = sp_dep_visitas[key]
                    break
        except (ValueError, TypeError):
            pass

        if sp_dep_v is None:
            n_no_match += 1
            continue

        # Aplicar filtro: ema_sp_dep_v > threshold
        if sp_dep_v <= threshold:
            continue

        # Idempotencia
        key_log = (liga, fecha, local, visita)
        if key_log in existing:
            n_skipped += 1
            continue

        # Determinar pick_original real (apuesta_1x2 si existe, sino N/A)
        pick_orig = apuesta if apuesta else 'X_potencial'

        # hit_real / yield_real si está liquidado
        hit_real = None
        yield_real = None
        if estado == 'Liquidado' and gl is not None and gv is not None:
            hit_real = 1 if gl == gv else 0
            yield_real = (c_x - 1.0) if hit_real else -1.0

        if not args.dry_run:
            cur.execute('''
                INSERT INTO picks_shadow_antifiltro_f4b_runtime
                (ts_log, liga, fecha, ht, at, equipo_visita_norm,
                 ema_sp_dep_v, n_acum_v, pick_original, cuota_original,
                 prob_modelo_x, ev_x, habria_sido_suprimido, modo_actual,
                 hit_real, yield_real, fecha_liquidacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ts_now, liga, fecha, local, visita, equipo_n_visita,
                  sp_dep_v, n_acum_v, pick_orig, c_x,
                  p_x, ev_x, 1, modo,
                  hit_real, yield_real, fecha if hit_real is not None else None))
        n_logged += 1

    if not args.dry_run:
        con.commit()

    print(f'\n=== RESULTADOS ===')
    print(f'Picks logueados (habría suprimido): {n_logged}')
    print(f'Skipped (idempotente): {n_skipped}')
    print(f'Sin EMA shotmap match: {n_no_match}')

    # Stats
    if not args.dry_run:
        n_total = cur.execute('SELECT COUNT(*) FROM picks_shadow_antifiltro_f4b_runtime').fetchone()[0]
        n_liquidados = cur.execute('SELECT COUNT(*) FROM picks_shadow_antifiltro_f4b_runtime WHERE hit_real IS NOT NULL').fetchone()[0]
        print(f'\nTotal en SHADOW table: {n_total}')
        print(f'Liquidados con yield: {n_liquidados}')
        if n_liquidados > 0:
            avg_y = cur.execute('SELECT AVG(yield_real) FROM picks_shadow_antifiltro_f4b_runtime WHERE yield_real IS NOT NULL').fetchone()[0]
            hit_pct = cur.execute('SELECT AVG(hit_real)*100 FROM picks_shadow_antifiltro_f4b_runtime WHERE hit_real IS NOT NULL').fetchone()[0]
            print(f'Yield SHADOW (de picks=X que habrían sido suprimidos): {avg_y*100:+.1f}%')
            print(f'Hit rate empate: {hit_pct:.1f}%')
            print(f'(yield NEGATIVO = anti-filtro funciona; suprimirlos en producción daría lift)')

    con.close()


def actualizar_liquidados(con, dry_run=False):
    """Path 2: para SHADOW logs sin yield_real, actualizar tras liquidación."""
    cur = con.cursor()
    pendientes = cur.execute('''
        SELECT psf.id, psf.liga, psf.fecha, psf.ht, psf.at, psf.cuota_original
        FROM picks_shadow_antifiltro_f4b_runtime psf
        WHERE psf.hit_real IS NULL
    ''').fetchall()
    print(f'SHADOW logs sin yield_real: {len(pendientes)}')

    n_updated = 0
    for r in pendientes:
        log_id, liga, fecha, ht, at, cuota_x = r
        # Buscar resultado en partidos_backtest (estado='Liquidado')
        try:
            d0 = datetime.fromisoformat(fecha).date()
            res = None
            for delta in (0, -1, 1):
                fecha_alt = (d0 + timedelta(days=delta)).isoformat()
                row = cur.execute('''
                    SELECT goles_l, goles_v FROM partidos_backtest
                    WHERE pais=? AND fecha=? AND local=? AND visita=? AND estado='Liquidado'
                ''', (liga, fecha_alt, ht, at)).fetchone()
                if row and row[0] is not None and row[1] is not None:
                    res = row
                    break
            if not res:
                continue
            gl, gv = res
            hit = 1 if gl == gv else 0
            yld = (cuota_x - 1.0) if hit else -1.0

            if not dry_run:
                cur.execute('''
                    UPDATE picks_shadow_antifiltro_f4b_runtime
                    SET hit_real=?, yield_real=?, fecha_liquidacion=?
                    WHERE id=?
                ''', (hit, yld, datetime.now().isoformat(), log_id))
            n_updated += 1
        except (ValueError, TypeError):
            continue

    if not dry_run:
        con.commit()
    print(f'Actualizados: {n_updated}')


if __name__ == '__main__':
    main()

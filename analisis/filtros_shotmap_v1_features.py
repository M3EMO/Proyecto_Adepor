"""
Fase 1 — Construir features shotmap-derived + tabla historial_equipos_shotmap_ema.

Para cada partido SOFA, extraer del shotmap_json para cada equipo:
  F1. xg_perf_match = goles_real - xg_shotmap_team
  F2. bcc_match = goles_BC / total_BC (BC = xg > 0.45)
  F3. pct_danger_match = shots con dist < 12m / total_shots
  F4. sp_dep_match = goles_setpiece / max(1, total_goles)
  F5. late_pct_match = shots min > 80 / total_shots
  F6. shooter_gini_match = Gini sobre shots por playerId

Cronológico per (equipo, liga): EMA span=5, warmup ≥ 3.
Snapshot pre-partido (forward-strict, NO leak del partido en curso).

Output: tabla historial_equipos_shotmap_ema con (liga, equipo_norm, fecha, sofa_event_id, ema_*, n_acum).
Idempotente: drop+recreate.
"""

import sqlite3
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = str(ROOT / 'fondo_quant.db')
WARMUP = 3
EMA_SPAN = 5
EMA_ALPHA = 2.0 / (EMA_SPAN + 1)  # ~0.333
DANGER_DIST_M = 12.0
LATE_GAME_MIN = 80
BC_XG_THRESHOLD = 0.45  # big chance threshold

# Cancha real metros
CANCHA_W_M = 105.0
CANCHA_H_M = 68.0


def normalize_team(name):
    """Normalizar para identificar equipo cross-tabla."""
    if not name:
        return ''
    import unicodedata, re
    s = unicodedata.normalize('NFKD', name).encode('ascii', errors='ignore').decode().lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def shot_distance_m(player_coords):
    """Distancia al arco contrario en metros desde playerCoordinates SOFA (0-100)."""
    px = player_coords.get('x', 50)
    py = player_coords.get('y', 50)
    if px is None or py is None:
        return 50.0
    x_m = (px / 100.0) * CANCHA_W_M
    y_m = ((py - 50) / 100.0) * CANCHA_H_M
    return math.sqrt(x_m ** 2 + y_m ** 2)


def gini(values):
    """Gini coefficient (0=todos iguales, 1=uno acapara)."""
    if not values or sum(values) == 0:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    cum = sum((i + 1) * v for i, v in enumerate(sorted_v))
    return (2 * cum) / (n * sum(sorted_v)) - (n + 1) / n


def features_partido_equipo(shots_team, goles_team, xg_team_total):
    """Calcular features de un partido para un equipo (subset shots)."""
    n_total = len(shots_team)
    if n_total == 0:
        return {
            'xg_perf': None, 'bcc': None, 'pct_danger': None,
            'sp_dep': None, 'late_pct': None, 'shooter_gini': None,
            'n_shots': 0, 'goles': goles_team, 'xg_team': xg_team_total,
        }

    # F1: xg_perf
    xg_perf = goles_team - (xg_team_total or 0)

    # F2: BCC (big-chance conversion rate)
    bc_shots = [s for s in shots_team if (s.get('xg') or 0) >= BC_XG_THRESHOLD]
    bc_total = len(bc_shots)
    bc_goals = sum(1 for s in bc_shots if s.get('shotType') == 'goal')
    bcc = (bc_goals / bc_total) if bc_total > 0 else None

    # F3: % shots danger zone
    danger_shots = sum(1 for s in shots_team
                       if shot_distance_m(s.get('playerCoordinates') or {}) < DANGER_DIST_M)
    pct_danger = danger_shots / n_total

    # F4: set-piece dependency
    sp_situations = ('corner', 'free-kick', 'set-piece', 'throw-in-set-piece', 'penalty')
    goals_team = [s for s in shots_team if s.get('shotType') == 'goal']
    n_goals_total = len(goals_team)
    n_goals_sp = sum(1 for s in goals_team if (s.get('situation') or '') in sp_situations)
    sp_dep = (n_goals_sp / n_goals_total) if n_goals_total > 0 else None

    # F5: late game shots
    late = sum(1 for s in shots_team if (s.get('time') or 0) > LATE_GAME_MIN)
    late_pct = late / n_total

    # F6: shooter Gini
    shots_per_player = defaultdict(int)
    for s in shots_team:
        pid = (s.get('player') or {}).get('id')
        if pid:
            shots_per_player[pid] += 1
    shooter_gini = gini(list(shots_per_player.values())) if shots_per_player else 0.0

    return {
        'xg_perf': xg_perf,
        'bcc': bcc,
        'pct_danger': pct_danger,
        'sp_dep': sp_dep,
        'late_pct': late_pct,
        'shooter_gini': shooter_gini,
        'n_shots': n_total,
        'goles': goles_team,
        'xg_team': xg_team_total,
        'bc_total': bc_total,
        'bc_goals': bc_goals,
    }


def crear_schema(con):
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS historial_equipos_shotmap_ema')
    cur.execute('''
        CREATE TABLE historial_equipos_shotmap_ema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            liga TEXT NOT NULL,
            equipo_norm TEXT NOT NULL,
            equipo_real TEXT,
            fecha TEXT NOT NULL,
            sofa_event_id INTEGER,
            es_local INTEGER,
            -- per-match raw
            xg_perf_match REAL,
            bcc_match REAL,
            pct_danger_match REAL,
            sp_dep_match REAL,
            late_pct_match REAL,
            shooter_gini_match REAL,
            n_shots_match INTEGER,
            goles_match INTEGER,
            xg_team_match REAL,
            -- EMA pre-partido (forward-strict, snapshot ANTES de incorporar partido actual)
            ema_xg_perf REAL,
            ema_bcc REAL,
            ema_pct_danger REAL,
            ema_sp_dep REAL,
            ema_late_pct REAL,
            ema_shooter_gini REAL,
            n_acum INTEGER NOT NULL DEFAULT 0,
            ts_log TEXT
        )
    ''')
    cur.execute('CREATE INDEX idx_ema_shotmap_eq ON historial_equipos_shotmap_ema(equipo_norm, liga, fecha)')
    cur.execute('CREATE INDEX idx_ema_shotmap_evt ON historial_equipos_shotmap_ema(sofa_event_id)')
    con.commit()


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    crear_schema(con)

    # Cargar partidos cronológicamente
    rows = cur.execute('''
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               xg_shotmap_l, xg_shotmap_v, shotmap_json
        FROM sofascore_match_features
        WHERE error IS NULL AND shotmap_json IS NOT NULL
        ORDER BY fecha ASC, sofa_event_id ASC
    ''').fetchall()
    print(f'Partidos a procesar: {len(rows)}')

    # Estado per (equipo_norm, liga)
    state = defaultdict(lambda: {
        'ema_xg_perf': None, 'ema_bcc': None, 'ema_pct_danger': None,
        'ema_sp_dep': None, 'ema_late_pct': None, 'ema_shooter_gini': None,
        'n': 0,
    })

    n_inserted = 0
    n_match_no_shotmap = 0
    from datetime import datetime
    ts_now = datetime.now().isoformat()

    for r in rows:
        sofa_id, liga, fecha, ht, at, hg, ag, xg_l, xg_v, sm_json = r
        try:
            sm = json.loads(sm_json)
        except (TypeError, json.JSONDecodeError):
            n_match_no_shotmap += 1
            continue
        shots_all = sm.get('shotmap', [])
        if not shots_all:
            n_match_no_shotmap += 1
            continue

        # Split por equipo
        shots_l = [s for s in shots_all if s.get('isHome')]
        shots_v = [s for s in shots_all if not s.get('isHome')]

        # Procesar local + visita
        for shots, equipo_real, goles, xg_team, es_local in [
            (shots_l, ht, hg, xg_l, 1),
            (shots_v, at, ag, xg_v, 0),
        ]:
            if goles is None:
                continue
            equipo_norm = normalize_team(equipo_real)
            if not equipo_norm:
                continue

            # Features partido actual
            f = features_partido_equipo(shots, goles, xg_team)

            # SNAPSHOT pre-partido (forward-strict): tomar state ANTES de update
            s = state[(equipo_norm, liga)]
            n_pre = s['n']
            ema_pre = {
                'xg_perf': s['ema_xg_perf'] if n_pre >= WARMUP else None,
                'bcc': s['ema_bcc'] if n_pre >= WARMUP else None,
                'pct_danger': s['ema_pct_danger'] if n_pre >= WARMUP else None,
                'sp_dep': s['ema_sp_dep'] if n_pre >= WARMUP else None,
                'late_pct': s['ema_late_pct'] if n_pre >= WARMUP else None,
                'shooter_gini': s['ema_shooter_gini'] if n_pre >= WARMUP else None,
            }

            # Persistir snapshot pre-partido + features partido actual
            cur.execute('''
                INSERT INTO historial_equipos_shotmap_ema
                (liga, equipo_norm, equipo_real, fecha, sofa_event_id, es_local,
                 xg_perf_match, bcc_match, pct_danger_match, sp_dep_match,
                 late_pct_match, shooter_gini_match, n_shots_match, goles_match, xg_team_match,
                 ema_xg_perf, ema_bcc, ema_pct_danger, ema_sp_dep, ema_late_pct, ema_shooter_gini,
                 n_acum, ts_log)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (liga, equipo_norm, equipo_real, fecha, sofa_id, es_local,
                  f['xg_perf'], f['bcc'], f['pct_danger'], f['sp_dep'],
                  f['late_pct'], f['shooter_gini'], f['n_shots'], f['goles'], f['xg_team'],
                  ema_pre['xg_perf'], ema_pre['bcc'], ema_pre['pct_danger'],
                  ema_pre['sp_dep'], ema_pre['late_pct'], ema_pre['shooter_gini'],
                  n_pre, ts_now))
            n_inserted += 1

            # UPDATE EMA con partido actual (post-snapshot)
            for fld_match, fld_ema in [
                ('xg_perf', 'ema_xg_perf'),
                ('bcc', 'ema_bcc'),
                ('pct_danger', 'ema_pct_danger'),
                ('sp_dep', 'ema_sp_dep'),
                ('late_pct', 'ema_late_pct'),
                ('shooter_gini', 'ema_shooter_gini'),
            ]:
                v = f[fld_match]
                if v is None:
                    continue  # no actualizar EMA si feature no disponible
                if s[fld_ema] is None:
                    s[fld_ema] = v  # primera observación
                else:
                    s[fld_ema] = EMA_ALPHA * v + (1 - EMA_ALPHA) * s[fld_ema]
            s['n'] += 1

        if n_inserted % 200 == 0:
            con.commit()
            print(f'  Insertados {n_inserted}...')

    con.commit()
    print(f'\nTotal insertados: {n_inserted}')
    print(f'Sin shotmap: {n_match_no_shotmap}')

    # Stats
    n_post_warmup = cur.execute('SELECT COUNT(*) FROM historial_equipos_shotmap_ema WHERE n_acum >= ?', (WARMUP,)).fetchone()[0]
    print(f'Eventos post-WARMUP (>=3 partidos previos): {n_post_warmup}')

    # Cobertura per liga
    print('\nCobertura per liga (eventos post-warmup):')
    for r in cur.execute('SELECT liga, COUNT(*) FROM historial_equipos_shotmap_ema WHERE n_acum >= ? GROUP BY liga ORDER BY 2 DESC', (WARMUP,)):
        print(f'  {r[0]:<14s} {r[1]:>5d}')

    # Sample EMA features
    print('\nSample features EMA (5 eventos post-warmup):')
    print(f'{"liga":<11} {"equipo":<22} {"fecha":<10} {"n":>3} {"xg_perf":>8} {"bcc":>6} {"danger":>7} {"sp_dep":>7} {"late":>6} {"gini":>5}')
    for r in cur.execute('''SELECT liga, equipo_real, fecha, n_acum,
                                    ema_xg_perf, ema_bcc, ema_pct_danger,
                                    ema_sp_dep, ema_late_pct, ema_shooter_gini
                              FROM historial_equipos_shotmap_ema
                              WHERE n_acum >= ?
                              ORDER BY fecha DESC LIMIT 5''', (WARMUP,)):
        liga, eq, fecha, n, xp, bc, pd, sp, lp, gi = r
        fmt = lambda v: f'{v:>+7.3f}' if v is not None else '   N/A'
        fmt2 = lambda v: f'{v:>5.3f}' if v is not None else '  N/A'
        print(f'{liga:<11} {eq[:22]:<22} {fecha:<10} {n:>3} {fmt(xp):>8} {fmt2(bc):>6} {fmt2(pd):>7} {fmt2(sp):>7} {fmt2(lp):>6} {fmt2(gi):>5}')

    con.close()


if __name__ == '__main__':
    main()

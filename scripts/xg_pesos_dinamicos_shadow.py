"""
SHADOW: pesos xG proxy dinamicos por liga (bead adepor-thv.21). No afecta picks.

Replay walk-forward sobre partidos liquidados con stats y log por liga en
xg_pesos_dinamicos_shadow: coeficientes actuales y log-lik por observacion
(estatico vs dinamico). OJO: mejor ajuste de goles NO implica mejor pronostico.
Validacion Pinnacle 2024-25 (analisis/validacion_fdco_walkforward.py): LL goles +0.035 (z=7.7)
pero Brier 1X2 empeora (0.6393 vs 0.6366). Promover solo si mejora la log-loss 1X2 walk-forward.

Uso:  python scripts/xg_pesos_dinamicos_shadow.py [--dry-run]
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.config_motor import get_param  # noqa: E402
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.nucleo.xg_pesos_dinamicos import replay_liga  # noqa: E402

SQL_TABLA = """CREATE TABLE IF NOT EXISTS xg_pesos_dinamicos_shadow (
    liga TEXT NOT NULL, fecha_calculo TEXT NOT NULL, n_obs INTEGER,
    b_sot REAL, b_off REAL, b_corner REAL,
    b_sot_estatico REAL, b_off_estatico REAL, b_corner_estatico REAL,
    ll_estatico REAL, ll_dinamico REAL, aplicado_produccion INTEGER DEFAULT 0,
    PRIMARY KEY (liga, fecha_calculo))"""


def cargar_observaciones(conn):
    """{liga: [(x, goles), ...]} cronologico; dos observaciones por partido (local y visita)."""
    filas = conn.execute("""
        SELECT pais, goles_l, goles_v, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado' AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND sot_l IS NOT NULL AND sot_v IS NOT NULL
        ORDER BY fecha, id_partido
    """).fetchall()
    obs = defaultdict(list)
    for liga, gl, gv, sl, shl, cl, sv, shv, cv in filas:
        for sot, shots, corners, goles in ((sl, shl, cl, gl), (sv, shv, cv, gv)):
            off = max(0, (shots or 0) - (sot or 0))
            obs[liga].append(((sot or 0, off, corners or 0), goles))
    return obs


def theta_estatico(conn, liga):
    """Coeficientes vigentes del xG proxy (motor_data.calcular_xg_hibrido)."""
    fila = conn.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga=?", (liga,)).fetchone()
    corner = fila[0] if fila and fila[0] is not None else 0.02
    return (get_param('beta_sot', scope=liga, default=0.352),
            get_param('beta_shots_off', default=0.010), corner)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = sqlite3.connect(DB_NAME)
    obs = cargar_observaciones(conn)
    if not obs:
        print('[SKIP] Sin partidos liquidados con stats.')
        return
    ahora = datetime.now().isoformat(timespec='seconds')
    if not args.dry_run:
        conn.execute(SQL_TABLA)
    print(f'{"liga":<16}{"n":>6}{"b_sot":>8}{"b_off":>8}{"b_corn":>8}{"LL est":>9}{"LL din":>9}')
    for liga, observaciones in sorted(obs.items()):
        t0 = theta_estatico(conn, liga)
        r = replay_liga(observaciones, t0)
        b = r['theta']
        print(f'{liga:<16}{r["n"]:>6}{b[0]:>8.3f}{b[1]:>8.3f}{b[2]:>8.3f}'
              f'{r["ll_estatico"]:>9.4f}{r["ll_dinamico"]:>9.4f}')
        if not args.dry_run:
            conn.execute("""INSERT OR REPLACE INTO xg_pesos_dinamicos_shadow
                (liga, fecha_calculo, n_obs, b_sot, b_off, b_corner,
                 b_sot_estatico, b_off_estatico, b_corner_estatico, ll_estatico, ll_dinamico)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (liga, ahora, r['n'], *b, *t0, r['ll_estatico'], r['ll_dinamico']))
    conn.commit()
    conn.close()
    print('LL = log-verosimilitud Poisson media por observacion (mayor = mejor), walk-forward.')


if __name__ == '__main__':
    main()

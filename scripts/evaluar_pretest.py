"""
EVALUAR_PRETEST — monitor del pretest mode por liga.

Decision del usuario (fase 3, 2026-04-20):
- Las apuestas arrancan en modo PRETEST (stake = 0, pick se registra pero no hay plata real).
- Cada liga sube a LIVE automaticamente cuando acumula >= N partidos liquidados con hit >= 55%.
- Parametros en config_motor_valores:
    apuestas_live (scope=<liga>)      -> 'TRUE' / 'FALSE'
    pretest_hit_threshold (global)    -> 0.55
    pretest_n_minimo (global)         -> 20

Uso:
    py scripts/evaluar_pretest.py              # report + auto-flip si corresponde
    py scripts/evaluar_pretest.py --dry-run    # solo report, no cambia DB
"""

import sqlite3
import sys
from pathlib import Path

# Imports del repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402
from src.comun.config_sistema import DB_NAME  # noqa: E402


def _is_true(val):
    if isinstance(val, bool):
        return val
    return str(val).upper() in ('TRUE', '1', 'T', 'YES')


def evaluar(dry_run=False):
    umbral = get_param('pretest_hit_threshold', default=0.55) or 0.55
    n_min = int(get_param('pretest_n_minimo', default=20) or 20)

    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()

    # Hit rate por liga sobre apuestas 1X2 liquidadas (ganadas/perdidas)
    rows = cur.execute("""
        SELECT pais,
               COUNT(*) AS n,
               SUM(CASE WHEN apuesta_1x2 LIKE '[GANADA]%' THEN 1 ELSE 0 END) AS ganadas
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')
        GROUP BY pais
        ORDER BY pais
    """).fetchall()

    print(f"\nPretest monitor — umbral={umbral:.0%}, N_min={n_min}")
    print(f"{'Liga':<12s} {'N':>4s} {'Ganadas':>8s} {'Hit%':>7s} {'apuestas_live actual':>22s} {'Decision':>15s}")
    print('-' * 80)

    flips = []
    for pais, n, ganadas in rows:
        hit = ganadas / n if n else 0.0
        live_actual = _is_true(get_param('apuestas_live', scope=pais, default='FALSE'))

        if n < n_min:
            decision = f'wait (faltan {n_min - n})'
            marca = ''
        elif hit >= umbral and not live_actual:
            decision = 'FLIP -> LIVE'
            flips.append((pais, hit, n, 'TRUE'))
            marca = ' [+]'
        elif hit < umbral and live_actual:
            decision = 'FLIP -> PRETEST'
            flips.append((pais, hit, n, 'FALSE'))
            marca = ' [-]'
        else:
            decision = 'mantener'
            marca = ''

        print(f"{pais:<12s} {n:>4d} {ganadas:>8d} {100*hit:>6.1f}% {str(live_actual):>22s} {decision:>15s}{marca}")

    if not flips:
        print("\nSin cambios de estado.")
        con.close()
        return 0

    print(f"\nCambios propuestos: {len(flips)}")
    for pais, hit, n, nuevo_estado in flips:
        print(f"  {pais}: apuestas_live -> {nuevo_estado} (hit={100*hit:.1f}%, N={n})")

    if dry_run:
        print("\n--dry-run: no se aplicaron cambios en DB.")
        con.close()
        return 0

    # Aplicar flips
    for pais, hit, n, nuevo_estado in flips:
        cur.execute(
            "UPDATE config_motor_valores SET valor_texto=?, fuente=? "
            "WHERE clave='apuestas_live' AND scope=?",
            (nuevo_estado, f'pretest_autoflip_hit={100*hit:.1f}%_N={n}', pais)
        )
    con.commit()
    con.close()

    # Nota: motor_calculadora leera los nuevos valores en el proximo run
    # (get_param no cachea, lee de DB cada llamada).

    print(f"\n{len(flips)} cambio(s) aplicado(s) en config_motor_valores.")
    return len(flips)


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    evaluar(dry_run=dry)

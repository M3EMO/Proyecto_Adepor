"""
EVALUAR_PRETEST — monitor del pretest mode por liga.

Decision del usuario (fase 3, 2026-04-20 -> actualizada 2026-04-21):
- Las apuestas arrancan en modo PRETEST (stake = 0, pick se registra pero no hay plata real).
- Cada liga sube a LIVE automaticamente cuando cumple:
    N partidos liquidados >= pretest_n_minimo
    hit >= pretest_hit_threshold
    p-valor <= pretest_p_max (binomial exacto test vs p=0.5)
- Parametros en config_motor_valores:
    apuestas_live (scope=<liga>)      -> 'TRUE' / 'FALSE'
    pretest_hit_threshold (global)    -> 0.55
    pretest_n_minimo (global)         -> 15 (era 20 hasta fase 3.3.3)
    pretest_p_max (global)            -> 0.30 (NUEVO fase 3.3.3)

Uso:
    py scripts/evaluar_pretest.py              # report + auto-flip si corresponde
    py scripts/evaluar_pretest.py --dry-run    # solo report, no cambia DB
"""

import sqlite3
import sys
from math import comb
from pathlib import Path

# Imports del repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402
from src.comun.config_sistema import DB_NAME  # noqa: E402


def _is_true(val):
    if isinstance(val, bool):
        return val
    return str(val).upper() in ('TRUE', '1', 'T', 'YES')


def _p_valor_binomial(n, k, p0=0.5):
    """P(X >= k | n, p0) - calculo exacto binomial.
    Test one-sided: prob de ver >=k aciertos si el hit rate real fuera p0.
    p < 0.30 significa: solo 30% de chance de que el hit observado sea por azar."""
    if n == 0 or k == 0:
        return 1.0
    return sum(comb(n, i) * (p0**i) * ((1-p0)**(n-i)) for i in range(k, n+1))


def evaluar(dry_run=False):
    umbral = get_param('pretest_hit_threshold', default=0.55) or 0.55
    n_min = int(get_param('pretest_n_minimo', default=15) or 15)
    p_max = get_param('pretest_p_max', default=0.30) or 0.30

    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()

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

    print(f"\nPretest monitor — hit>={umbral:.0%}, N>={n_min}, p<={p_max}")
    print(f"{'Liga':<12s} {'N':>4s} {'Gan':>4s} {'Hit%':>6s} {'p-val':>7s} {'live':>6s} {'Decision':>18s}")
    print('-' * 75)

    flips = []
    for pais, n, ganadas in rows:
        hit = ganadas / n if n else 0.0
        pval = _p_valor_binomial(n, ganadas, 0.5)
        live_actual = _is_true(get_param('apuestas_live', scope=pais, default='FALSE'))

        # Razones de wait
        if n < n_min:
            decision = f'wait N (+{n_min - n})'
        elif hit < umbral:
            decision = f'wait hit ({100*hit:.0f}<{100*umbral:.0f})'
        elif pval > p_max:
            decision = f'wait p ({pval:.2f}>{p_max:.2f})'
        elif not live_actual:
            decision = 'FLIP -> LIVE'
            flips.append((pais, hit, n, pval, 'TRUE'))
        else:
            decision = 'mantener LIVE'

        # Flip inverso: si esta LIVE y hit bajo, volver a PRETEST
        if live_actual and n >= n_min and hit < umbral:
            decision = 'FLIP -> PRETEST'
            flips.append((pais, hit, n, pval, 'FALSE'))

        print(f"{pais:<12s} {n:>4d} {ganadas:>4d} {100*hit:>5.1f}% {pval:>7.3f} {str(live_actual):>6s} {decision:>18s}")

    if not flips:
        print("\nSin cambios de estado.")
        con.close()
        return 0

    print(f"\nCambios propuestos: {len(flips)}")
    for pais, hit, n, pval, nuevo_estado in flips:
        print(f"  {pais}: apuestas_live -> {nuevo_estado} (hit={100*hit:.1f}%, N={n}, p={pval:.3f})")

    if dry_run:
        print("\n--dry-run: no se aplicaron cambios en DB.")
        con.close()
        return 0

    for pais, hit, n, pval, nuevo_estado in flips:
        cur.execute(
            "UPDATE config_motor_valores SET valor_texto=?, fuente=? "
            "WHERE clave='apuestas_live' AND scope=?",
            (nuevo_estado, f'pretest_autoflip_hit={100*hit:.1f}%_N={n}_p={pval:.3f}', pais)
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

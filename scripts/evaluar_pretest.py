"""
EVALUAR_PRETEST — monitor del pretest mode por liga, para mercados 1X2 y O/U 2.5.

Decision del usuario (fase 3, 2026-04-20 -> actualizada 2026-04-22):
- Picks arrancan en modo PRETEST (stake = 0, pick se registra pero no hay plata real).
- Cada (liga, mercado) sube a LIVE automaticamente cuando cumple:
    N partidos liquidados >= N_minimo
    hit >= hit_threshold
    p-valor <= p_max (binomial exacto one-sided vs p=0.5)
- Auto-revert a PRETEST si, estando LIVE, hit cae <threshold con N>=N_min.

Parametros en config_motor_valores (scope='global'):
    Mercado 1X2
        apuestas_live             -> 'TRUE'/'FALSE' scope=<liga>
        pretest_hit_threshold     -> 0.55
        pretest_n_minimo          -> 15
        pretest_p_max             -> 0.30
    Mercado O/U 2.5
        apuesta_ou_live           -> 'TRUE'/'FALSE' scope=<liga>  (fallback global)
        pretest_ou_hit_threshold  -> 0.55   (default)
        pretest_ou_n_minimo       -> 5      (default, menor que 1X2 porque hay menos volumen)
        pretest_ou_p_max          -> 0.30   (default)

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
    """P(X >= k | n, p0) - calculo exacto binomial one-sided."""
    if n == 0 or k == 0:
        return 1.0
    return sum(comb(n, i) * (p0**i) * ((1-p0)**(n-i)) for i in range(k, n+1))


def _evaluar_mercado(cur, etiqueta, apuesta_col, flag_clave, n_min, hit_thr, p_max, fuente_prefix):
    """Evalua un mercado (1X2 o O/U) sobre partidos_backtest y calcula auto-flips.

    Returns: lista de tuplas (pais, hit, n, pval, nuevo_estado) a aplicar.
    """
    rows = cur.execute(f"""
        SELECT pais,
               COUNT(*) AS n,
               SUM(CASE WHEN {apuesta_col} LIKE '[GANADA]%' THEN 1 ELSE 0 END) AS ganadas
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND ({apuesta_col} LIKE '[GANADA]%' OR {apuesta_col} LIKE '[PERDIDA]%')
        GROUP BY pais
        ORDER BY pais
    """).fetchall()

    print(f"\n=== Mercado {etiqueta} — hit>={hit_thr:.0%}, N>={n_min}, p<={p_max} (flag={flag_clave}) ===")
    print(f"{'Liga':<12s} {'N':>4s} {'Gan':>4s} {'Hit%':>6s} {'p-val':>7s} {'live':>6s} {'Decision':>18s}")
    print('-' * 75)

    flips = []
    for pais, n, ganadas in rows:
        if n == 0:
            continue
        hit = ganadas / n
        pval = _p_valor_binomial(n, ganadas, 0.5)
        live_actual = _is_true(get_param(flag_clave, scope=pais, default='FALSE'))

        if n < n_min:
            decision = f'wait N (+{n_min - n})'
        elif hit < hit_thr:
            decision = f'wait hit ({100*hit:.0f}<{100*hit_thr:.0f})'
        elif pval > p_max:
            decision = f'wait p ({pval:.2f}>{p_max:.2f})'
        elif not live_actual:
            decision = 'FLIP -> LIVE'
            flips.append((pais, hit, n, pval, 'TRUE'))
        else:
            decision = 'mantener LIVE'

        # Auto-revert si esta LIVE y hit cayo bajo el umbral
        if live_actual and n >= n_min and hit < hit_thr:
            decision = 'FLIP -> PRETEST'
            flips.append((pais, hit, n, pval, 'FALSE'))

        print(f"{pais:<12s} {n:>4d} {ganadas:>4d} {100*hit:>5.1f}% {pval:>7.3f} {str(live_actual):>6s} {decision:>18s}")

    return flips


def _aplicar_flips(cur, flips, flag_clave, fuente_prefix):
    """Aplica auto-flips al config_motor_valores usando UPSERT."""
    for pais, hit, n, pval, nuevo_estado in flips:
        fuente = f'{fuente_prefix}_hit={100*hit:.1f}%_N={n}_p={pval:.3f}'
        cur.execute(
            """INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
               VALUES (?, ?, ?, 'bool', ?, 0, datetime('now'))
               ON CONFLICT(clave, scope) DO UPDATE SET
                   valor_texto=excluded.valor_texto,
                   fuente=excluded.fuente,
                   fecha_actualizacion=excluded.fecha_actualizacion""",
            (flag_clave, pais, nuevo_estado, fuente)
        )


def evaluar(dry_run=False):
    # Parametros 1X2
    hit_1x2 = float(get_param('pretest_hit_threshold', default=0.55) or 0.55)
    n_1x2   = int(get_param('pretest_n_minimo',       default=15) or 15)
    p_1x2   = float(get_param('pretest_p_max',        default=0.30) or 0.30)

    # Parametros O/U (defaults mas laxos en N porque hay menos volumen O/U)
    hit_ou = float(get_param('pretest_ou_hit_threshold', default=0.55) or 0.55)
    n_ou   = int(get_param('pretest_ou_n_minimo',        default=5)    or 5)
    p_ou   = float(get_param('pretest_ou_p_max',         default=0.30) or 0.30)

    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()

    # Mercado 1X2
    flips_1x2 = _evaluar_mercado(
        cur, '1X2', 'apuesta_1x2', 'apuestas_live',
        n_1x2, hit_1x2, p_1x2, 'pretest_autoflip_1x2'
    )
    # Mercado O/U
    flips_ou = _evaluar_mercado(
        cur, 'O/U 2.5', 'apuesta_ou', 'apuesta_ou_live',
        n_ou, hit_ou, p_ou, 'pretest_autoflip_ou'
    )

    total = len(flips_1x2) + len(flips_ou)
    if total == 0:
        print("\nSin cambios de estado.")
        con.close()
        return 0

    print(f"\nCambios propuestos: {total}")
    for pais, hit, n, pval, nuevo in flips_1x2:
        print(f"  [1X2]   {pais}: apuestas_live    -> {nuevo} (hit={100*hit:.1f}%, N={n}, p={pval:.3f})")
    for pais, hit, n, pval, nuevo in flips_ou:
        print(f"  [O/U]   {pais}: apuesta_ou_live  -> {nuevo} (hit={100*hit:.1f}%, N={n}, p={pval:.3f})")

    if dry_run:
        print("\n--dry-run: no se aplicaron cambios en DB.")
        con.close()
        return 0

    # Aplicar. apuestas_live usa UPDATE (ya existen filas), apuesta_ou_live usa UPSERT.
    for pais, hit, n, pval, nuevo in flips_1x2:
        cur.execute(
            "UPDATE config_motor_valores SET valor_texto=?, fuente=?, fecha_actualizacion=datetime('now') "
            "WHERE clave='apuestas_live' AND scope=?",
            (nuevo, f'pretest_autoflip_1x2_hit={100*hit:.1f}%_N={n}_p={pval:.3f}', pais)
        )
    _aplicar_flips(cur, flips_ou, 'apuesta_ou_live', 'pretest_autoflip_ou')
    con.commit()
    con.close()

    print(f"\n{total} cambio(s) aplicado(s) en config_motor_valores.")
    return total


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    evaluar(dry_run=dry)

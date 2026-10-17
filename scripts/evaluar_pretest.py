"""
EVALUAR_PRETEST — monitor del pretest mode por liga, para mercados 1X2 y O/U 2.5.

Decision del usuario (fase 3, 2026-04-20 -> actualizada 2026-04-22):
- Picks arrancan en modo PRETEST (stake = 0, pick se registra pero no hay plata real).
- Cada (liga, mercado) sube a LIVE automaticamente cuando cumple:
    N partidos liquidados (con cuota valida) >= N_minimo
    yield plano (stake 1) > 0
    p-valor <= p_max (binomial exacto one-sided vs p0 = break-even = media de 1/cuota)
- Auto-revert a PRETEST si, estando LIVE, el yield plano es <= 0 con N>=N_min.

Auditoria 2026-10: antes el criterio era hit >= 55% vs p0=0.5, sin cuotas. Con cuota
media 1.80 el break-even es 55.6%: un hit de 55% pierde plata y aun asi flipeaba a LIVE.
pretest_*_hit_threshold queda solo como columna informativa.

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
    py scripts/evaluar_pretest.py --aprobar-live  # aplica tambien los flips a LIVE (dinero real)

El pipeline diario corre sin --aprobar-live: solo aplica reversiones a PRETEST.
"""

import sqlite3
import sys
from math import comb
from pathlib import Path

# Imports del repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.comun.config_motor import get_param  # noqa: E402
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.comun.picks import cuota_para_pick  # noqa: E402


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
    crudas = cur.execute(f"""
        SELECT pais, {apuesta_col}, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND ({apuesta_col} LIKE '[GANADA]%' OR {apuesta_col} LIKE '[PERDIDA]%')
    """).fetchall()
    por_pais = {}
    for pais, ap, c1, cx, c2, co, cu in crudas:
        cuota = cuota_para_pick(ap, c1, cx, c2, co, cu)
        if not cuota or cuota <= 1:
            continue  # sin cuota no hay yield ni break-even
        a = por_pais.setdefault(pais, [0, 0, 0.0, 0.0])  # n, ganadas, profit, sum(1/cuota)
        gano = ap.startswith('[GANADA]')
        a[0] += 1
        a[1] += gano
        a[2] += (cuota - 1) if gano else -1.0
        a[3] += 1 / cuota
    rows = [(p, *v) for p, v in sorted(por_pais.items())]

    print(f"\n=== Mercado {etiqueta} — yield>0, N>={n_min}, p<={p_max} vs break-even (flag={flag_clave}) ===")
    print(f"{'Liga':<12s} {'N':>4s} {'Gan':>4s} {'Hit%':>6s} {'BE%':>6s} {'Yield':>7s} {'p-val':>7s} {'live':>6s} {'Decision':>18s}")
    print('-' * 90)

    flips = []
    for pais, n, ganadas, profit, inv_cuotas in rows:
        if n == 0:
            continue
        hit = ganadas / n
        break_even = inv_cuotas / n
        yld = profit / n
        pval = _p_valor_binomial(n, ganadas, break_even)
        live_actual = _is_true(get_param(flag_clave, scope=pais, default='FALSE'))

        if n < n_min:
            decision = f'wait N (+{n_min - n})'
        elif yld <= 0:
            decision = f'wait yield ({100*yld:+.0f}%)'
        elif pval > p_max:
            decision = f'wait p ({pval:.2f}>{p_max:.2f})'
        elif not live_actual:
            decision = 'FLIP -> LIVE'
            flips.append((pais, hit, n, pval, 'TRUE'))
        else:
            decision = 'mantener LIVE'

        # Auto-revert si esta LIVE y el yield plano dejo de ser positivo
        if live_actual and n >= n_min and yld <= 0:
            decision = 'FLIP -> PRETEST'
            flips.append((pais, hit, n, pval, 'FALSE'))

        print(f"{pais:<12s} {n:>4d} {ganadas:>4d} {100*hit:>5.1f}% {100*break_even:>5.1f}% "
              f"{100*yld:>+6.1f}% {pval:>7.3f} {str(live_actual):>6s} {decision:>18s}")

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


def evaluar(dry_run=False, aprobar_live=False):
    # Parametros 1X2
    hit_1x2 = float(get_param('pretest_hit_threshold', default=0.55) or 0.55)
    n_1x2   = int(get_param('pretest_n_minimo',       default=15) or 15)
    p_1x2   = float(get_param('pretest_p_max',        default=0.30) or 0.30)

    # Parametros O/U (defaults mas laxos en N porque hay menos volumen O/U)
    hit_ou = float(get_param('pretest_ou_hit_threshold', default=0.55) or 0.55)
    # Piso 15 para O/U tambien: con N=5 y p<=0.30 una liga sin edge flipea ~19% de las veces.
    n_ou   = max(15, int(get_param('pretest_ou_n_minimo',        default=15)   or 15))
    n_1x2  = max(15, n_1x2)
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

    # Pasar a LIVE mueve dinero real: requiere --aprobar-live (humano). Volver a
    # PRETEST es la direccion segura y se aplica sola.
    if not aprobar_live:
        pendientes = [f for f in flips_1x2 + flips_ou if f[4] == 'TRUE']
        for pais, hit, n, pval, _ in pendientes:
            print(f"  [PENDIENTE APROBACION] {pais} -> LIVE (N={n}, p={pval:.3f}). "
                  f"Correr con --aprobar-live para aplicarlo.")
        flips_1x2 = [f for f in flips_1x2 if f[4] != 'TRUE']
        flips_ou = [f for f in flips_ou if f[4] != 'TRUE']

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
    evaluar(dry_run='--dry-run' in sys.argv, aprobar_live='--aprobar-live' in sys.argv)

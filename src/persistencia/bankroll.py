"""Bankroll operativo: base fija o base + aportes + P/L liquidado (modo dinamico)."""
import sqlite3


def obtener_bankroll_operativo(cursor):
    """Devuelve el bankroll a usar por Kelly.

    Modo 'fijo'    -> configuracion.bankroll
    Modo 'dinamico'-> bankroll_base
                    + SUM(aportes_capital con fecha >= bankroll_fecha_corte)
                    + SUM(P/L liquidado desde bankroll_fecha_corte),
                      clampeado a [bankroll_piso, bankroll_techo].

    Los aportes_capital son inyecciones/retiros manuales (positivo=aporte,
    negativo=retiro). Permiten subir el bankroll sin reescribir stakes ya
    liquidados (los registros viejos en partidos_backtest quedan intactos).
    """
    def _get(clave, default):
        cursor.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,))
        r = cursor.fetchone()
        return r[0] if r else default

    try:
        bankroll_base = float(_get('bankroll', 100000.0))
    except (TypeError, ValueError):
        bankroll_base = 100000.0

    modo = str(_get('bankroll_modo', 'fijo')).lower().strip()
    if modo != 'dinamico':
        return bankroll_base

    fecha_corte = str(_get('bankroll_fecha_corte', '1970-01-01'))
    try:
        piso  = float(_get('bankroll_piso',  100000.0))
        techo = float(_get('bankroll_techo', 1000000.0))
    except (TypeError, ValueError):
        piso, techo = 100000.0, 1000000.0

    # Aportes de capital desde fecha_corte (tabla puede no existir si no se migro)
    aportes = 0.0
    try:
        cursor.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM aportes_capital WHERE fecha >= ?",
            (fecha_corte,)
        )
        aportes = float(cursor.fetchone()[0] or 0)
    except sqlite3.OperationalError:
        pass  # tabla no existe; ignorar (compat pre-migracion)

    cursor.execute("""
        SELECT apuesta_1x2, apuesta_ou, stake_1x2, stake_ou,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM partidos_backtest
        WHERE estado = 'Liquidado' AND fecha >= ?
              AND (stake_1x2 > 0 OR stake_ou > 0)
    """, (fecha_corte,))

    pnl = 0.0
    for ap12, apou, st12, stou, c1, cx, c2, co, cu in cursor.fetchall():
        ap12 = str(ap12 or '')
        apou = str(apou or '')
        if st12 and st12 > 0:
            if ap12.startswith('[GANADA]'):
                u = ap12.upper()
                cuota = c1 if 'LOCAL' in u else (cx if 'EMPATE' in u else (c2 if 'VISITA' in u else 0))
                if cuota: pnl += st12 * (cuota - 1)
            elif ap12.startswith('[PERDIDA]'):
                pnl -= st12
        if stou and stou > 0:
            if apou.startswith('[GANADA]'):
                u = apou.upper()
                cuota = co if ('OVER' in u or '+2.5' in u or 'MAS' in u) else (cu if ('UNDER' in u or '-2.5' in u or 'MENOS' in u) else 0)
                if cuota: pnl += stou * (cuota - 1)
            elif apou.startswith('[PERDIDA]'):
                pnl -= stou

    bankroll = bankroll_base + aportes + pnl
    if bankroll < piso:
        # Antes se clampeaba al piso: Kelly dimensionaba con capital que ya no existe.
        print(f"[ALERTA] Bankroll real {bankroll:,.2f} bajo el piso {piso:,.2f}: se usa el real.")
        return max(0.0, bankroll)
    return min(techo, bankroll)

import sqlite3
from src.comun.resolucion import determinar_resultado_token

# ==========================================
# MOTOR LIQUIDADOR V1.1
# Responsabilidad: Auditoria y liquidacion de resultados de apuestas.
# V1.1 (2026-04-25, bead adepor-dl6): calculo CLV en columnas separadas
#       clv_pct_1x2 y clv_pct_ou cuando hay stake>0 + cuota_cierre>0.
#       Convencion: clv_pct = (cuota_apostada / cuota_cierre - 1) * 100
#       Positivo = apostaste a cuota mejor que cierre = capturaste valor.
#       Cambio aditivo: NO altera la logica de liquidacion existente.
# ==========================================

DB_NAME = 'fondo_quant.db'


# adepor-6ph: helper unificado en src/comun/picks.cuota_para_pick
from src.comun.picks import cuota_para_pick as _cuota_apostada_para_pick


def _calcular_clv_pct(cuota_apostada, cuota_cierre):
    """
    CLV convencion fractional (industria): positivo = capturaste valor.
        clv_pct = (cuota_apostada / cuota_cierre - 1) * 100
    Retorna None si cualquier insumo invalido (no se persiste).
    """
    if not cuota_apostada or cuota_apostada <= 0:
        return None
    if not cuota_cierre or cuota_cierre <= 0:
        return None
    return (cuota_apostada / cuota_cierre - 1.0) * 100.0

def main():
    """
    Ejecuta el proceso de liquidación de apuestas para partidos calculados
    cuyos resultados ya han sido registrados.
    """
    print("Iniciando Motor Liquidador V1.1...")
    conn = None
    partidos_liquidados = 0
    clv_calculados = 0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # --- FASE 1: EXTRACCIÓN DE CANDIDATOS ---
        # V1.1: traemos cuotas + stakes + cuotas_cierre para soporte CLV.
        cursor.execute("""
            SELECT id_partido, apuesta_1x2, apuesta_ou, goles_l, goles_v,
                   cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
                   stake_1x2, stake_ou,
                   cuota_cierre_1x2, cuota_cierre_ou
            FROM partidos_backtest
            WHERE estado = 'Finalizado'
        """)
        partidos_a_liquidar = cursor.fetchall()

        if not partidos_a_liquidar:
            print("No se encontraron partidos calculados con resultados para liquidar.")
            return

        updates_a_realizar = []

        # --- FASE 2: AUDITORÍA Y PROCESAMIENTO ---
        for row in partidos_a_liquidar:
            (id_partido, ap_1x2, ap_ou, gl, gv,
             c1, cx, c2, co, cu,
             stk_1x2, stk_ou,
             cc_1x2, cc_ou) = row

            # FIX DE ROBUSTEZ: Si el partido se marcó como finalizado pero no tiene goles, lo omitimos.
            if gl is None or gv is None:
                continue

            nuevo_ap_1x2 = ap_1x2
            token_1x2 = determinar_resultado_token(ap_1x2, gl, gv)
            if token_1x2 is not None:
                nuevo_ap_1x2 = ap_1x2.replace("[APOSTAR]", token_1x2)

            nuevo_ap_ou = ap_ou
            token_ou = determinar_resultado_token(ap_ou, gl, gv)
            if token_ou is not None:
                nuevo_ap_ou = ap_ou.replace("[APOSTAR]", token_ou)

            # --- V1.1: calculo CLV (columnas separadas 1x2 y OU) ---
            clv_1x2 = None
            clv_ou  = None
            if stk_1x2 and stk_1x2 > 0:
                cuota_apostada_1x2 = _cuota_apostada_para_pick(ap_1x2, c1, cx, c2, co, cu)
                clv_1x2 = _calcular_clv_pct(cuota_apostada_1x2, cc_1x2)
            if stk_ou and stk_ou > 0:
                cuota_apostada_ou = _cuota_apostada_para_pick(ap_ou, c1, cx, c2, co, cu)
                clv_ou = _calcular_clv_pct(cuota_apostada_ou, cc_ou)
            if clv_1x2 is not None or clv_ou is not None:
                clv_calculados += 1

            updates_a_realizar.append((
                nuevo_ap_1x2, nuevo_ap_ou, 'Liquidado',
                clv_1x2, clv_ou,
                id_partido,
            ))

        # --- FASE 3: EJECUCIÓN Y SELLADO ---
        if updates_a_realizar:
            cursor.executemany("""
                UPDATE partidos_backtest
                SET apuesta_1x2 = ?, apuesta_ou = ?, estado = ?,
                    clv_pct_1x2 = COALESCE(?, clv_pct_1x2),
                    clv_pct_ou  = COALESCE(?, clv_pct_ou)
                WHERE id_partido = ?
            """, updates_a_realizar)

            partidos_liquidados = cursor.rowcount
            conn.commit()

        print(f"Proceso de liquidacion completado. Total de partidos liquidados: {partidos_liquidados}.")
        print(f"   CLV calculado para {clv_calculados} picks (con stake>0 y cuota_cierre poblada).")

    except sqlite3.Error as e:
        print(f"ERROR CRÍTICO: La operación de liquidación falló: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()

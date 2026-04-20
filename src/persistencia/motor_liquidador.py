import sqlite3
from src.comun.resolucion import determinar_resultado_token

# ==========================================
# MOTOR LIQUIDADOR V1.0
# Responsabilidad: Auditoría y liquidación de resultados de apuestas.
# ==========================================

DB_NAME = 'fondo_quant.db'

def main():
    """
    Ejecuta el proceso de liquidación de apuestas para partidos calculados
    cuyos resultados ya han sido registrados.
    """
    print("Iniciando Motor Liquidador V1.0...")
    conn = None
    partidos_liquidados = 0
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # --- FASE 1: EXTRACCIÓN DE CANDIDATOS ---
        cursor.execute("""
            SELECT id_partido, apuesta_1x2, apuesta_ou, goles_l, goles_v 
            FROM partidos_backtest 
            WHERE estado = 'Finalizado'
        """)
        partidos_a_liquidar = cursor.fetchall()

        if not partidos_a_liquidar:
            print("No se encontraron partidos calculados con resultados para liquidar.")
            return

        updates_a_realizar = []

        # --- FASE 2: AUDITORÍA Y PROCESAMIENTO ---
        for id_partido, ap_1x2, ap_ou, gl, gv in partidos_a_liquidar:
            
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

            # El estado ahora se actualiza aquí, junto con las apuestas.
            updates_a_realizar.append((nuevo_ap_1x2, nuevo_ap_ou, 'Liquidado', id_partido))

        # --- FASE 3: EJECUCIÓN Y SELLADO ---
        if updates_a_realizar:
            cursor.executemany("""
                UPDATE partidos_backtest 
                SET apuesta_1x2 = ?, apuesta_ou = ?, estado = ?
                WHERE id_partido = ?
            """, updates_a_realizar)
            
            partidos_liquidados = cursor.rowcount
            conn.commit()

        print(f"Proceso de liquidación completado. Total de partidos liquidados: {partidos_liquidados}.")

    except sqlite3.Error as e:
        print(f"ERROR CRÍTICO: La operación de liquidación falló: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()

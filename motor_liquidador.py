import sqlite3

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
            if isinstance(ap_1x2, str) and "[APOSTAR]" in ap_1x2:
                if "LOCAL" in ap_1x2: resultado = "[GANADA]" if gl > gv else "[PERDIDA]"
                elif "EMPATE" in ap_1x2: resultado = "[GANADA]" if gl == gv else "[PERDIDA]"
                elif "VISITA" in ap_1x2: resultado = "[GANADA]" if gl < gv else "[PERDIDA]"
                else: resultado = "[APOSTAR]"
                nuevo_ap_1x2 = ap_1x2.replace("[APOSTAR]", resultado)

            nuevo_ap_ou = ap_ou
            if isinstance(ap_ou, str) and "[APOSTAR]" in ap_ou:
                if "OVER 2.5" in ap_ou: resultado = "[GANADA]" if (gl + gv) > 2.5 else "[PERDIDA]"
                elif "UNDER 2.5" in ap_ou: resultado = "[GANADA]" if (gl + gv) < 2.5 else "[PERDIDA]"
                else: resultado = "[APOSTAR]"
                nuevo_ap_ou = ap_ou.replace("[APOSTAR]", resultado)

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

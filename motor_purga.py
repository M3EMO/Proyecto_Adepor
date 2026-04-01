import sqlite3
from datetime import datetime, timedelta

# ==========================================
# MOTOR DE PURGA V1.0 (RECOLECTOR DE BASURA)
# Responsabilidad: Eliminar equipos obsoletos para optimizar la memoria y el cálculo.
# ==========================================

DB_NAME = 'fondo_quant.db'
INACTIVITY_MONTHS = 6

def main():
    print("[SISTEMA] Iniciando Motor de Purga de Historial Obsoleto...")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Calcular la fecha de corte (hace 6 meses)
        cutoff_date = datetime.now() - timedelta(days=INACTIVITY_MONTHS * 30)
        cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")

        print(f"[INFO] Límite de inactividad establecido en: {cutoff_date_str}")

        # Encontrar equipos obsoletos en la tabla principal de historial
        cursor.execute("""
            SELECT equipo_norm, equipo_real, ultima_actualizacion
            FROM historial_equipos
            WHERE ultima_actualizacion < ?
        """, (cutoff_date_str,))
        equipos_a_purgar = cursor.fetchall()

        if not equipos_a_purgar:
            print("[EXITO] No se encontraron equipos obsoletos. La base de datos está optimizada.")
            return

        print(f"[ALERTA] Se purgarán {len(equipos_a_purgar)} equipos por inactividad (+{INACTIVITY_MONTHS} meses):")
        ids_a_purgar = [(eq[0],) for eq in equipos_a_purgar]
        for _, eq_real, fecha in equipos_a_purgar:
            print(f"  - {eq_real} (Última vez visto: {fecha})")

        # Ejecutar la purga en las tablas relevantes
        cursor.executemany("DELETE FROM historial_equipos WHERE equipo_norm = ?", ids_a_purgar)
        print(f"[PURGA] {cursor.rowcount} registros eliminados de 'historial_equipos'.")

        conn.commit()
        print("\n[EXITO] Purga completada. La base de datos ha sido optimizada.")

    except sqlite3.Error as e:
        print(f"[ERROR CRITICO] Falló la operación de purga: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
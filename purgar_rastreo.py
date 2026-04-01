import sqlite3

# ==========================================
# SCRIPT DE PURGA DE RASTREO
# Responsabilidad: Vaciar la tabla de rastreo 'ema_procesados'
# para forzar una re-descarga de datos en arquitecturas que la utilicen.
# ==========================================

DB_NAME = 'fondo_quant.db'

def main():
    """
    Conecta a la base de datos y ejecuta un DELETE sobre la tabla
    de rastreo 'ema_procesados'.
    """
    print("Iniciando protocolo de purga de la tabla de rastreo API.")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        print("Ejecutando purga sobre 'ema_procesados'...")
        cursor.execute("DELETE FROM ema_procesados")
        
        conn.commit()
        
        print("Confirmación institucional: La tabla de rastreo 'ema_procesados' ha sido vaciada exitosamente.")

    except sqlite3.Error as e:
        print(f"Error durante la operación de purga: {e}")
        print("La operación no pudo ser completada. Verifique si la tabla 'ema_procesados' existe en el esquema actual de la base de datos.")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
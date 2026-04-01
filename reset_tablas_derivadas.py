import sqlite3

# ==========================================
# SCRIPT DE PURGA DE TABLAS DERIVADAS
# Responsabilidad: Vaciar las tablas que contienen datos calculados
# para forzar una reconstrucción completa del modelo.
# ==========================================

DB_NAME = 'fondo_quant.db'
TABLAS_A_PURGAR = [
    'historial_equipos',
    'arbitros_stats',
    'ligas_stats',
    'ema_procesados'
]

def main():
    print("Iniciando protocolo de purga de tablas de datos derivados.")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        for tabla in TABLAS_A_PURGAR:
            try:
                print(f"Ejecutando purga sobre '{tabla}'...")
                cursor.execute(f"DELETE FROM {tabla}")
                print(f"   -> Tabla '{tabla}' vaciada.")
            except sqlite3.OperationalError:
                print(f"   -> [ADVERTENCIA] La tabla '{tabla}' no existe. Omitiendo.")
        
        conn.commit()
        print("\nConfirmación institucional: Todas las tablas de datos derivados han sido purgadas.")

    except sqlite3.Error as e:
        print(f"Error crítico durante la operación de purga: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()
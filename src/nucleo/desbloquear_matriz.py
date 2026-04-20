import sqlite3

# ==========================================
# SCRIPT DE DESBLOQUEO DE MATRIZ
# Responsabilidad: Reabrir el estado de todos los partidos a 'Pendiente'
# para forzar un recálculo completo por parte de los motores subsiguientes.
# ==========================================

from src.comun.config_sistema import DB_NAME

def main():
    """
    Conecta a la base de datos y ejecuta un UPDATE masivo para
    restablecer el estado de todos los partidos a 'Pendiente'.
    """
    print("Iniciando protocolo de desbloqueo de matriz de partidos.")
    print("ADVERTENCIA: esto resetea el estado de TODOS los partidos a 'Pendiente'.")
    print("Se perdera el progreso de liquidacion (estados 'Liquidado'/'Finalizado'/'Calculado').")
    confirmacion = input("Escribir RESET para confirmar: ")
    if confirmacion != "RESET":
        print("Operacion abortada por el usuario.")
        return
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        print("Ejecutando UPDATE sobre 'partidos_backtest' para establecer estado a 'Pendiente'...")
        cursor.execute("UPDATE partidos_backtest SET estado = 'Pendiente'")
        
        filas_afectadas = cursor.rowcount
        
        conn.commit()
        
        print(f"Confirmación institucional: La matriz ha sido desbloqueada. {filas_afectadas} filas han sido actualizadas al estado 'Pendiente'.")

    except sqlite3.Error as e:
        print(f"Error crítico durante la operación de desbloqueo: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
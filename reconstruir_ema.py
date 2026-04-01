import sqlite3
import sys

# ==========================================
# SCRIPT DE RECONSTRUCCIÓN DE EMA (MODO SEGURO)
# Responsabilidad: Guiar al usuario para ejecutar el protocolo de reconstrucción
# correcto a través del orquestador principal.
# ==========================================

def main():
    """
    Informa al usuario sobre el procedimiento correcto para reconstruir la memoria EMA
    y aborta la ejecución para prevenir el uso de lógica obsoleta.
    """
    print("="*80)
    print("⛔ [AVISO] ESTE SCRIPT (reconstruir_ema.py) ESTÁ OBSOLETO. ⛔")
    print("   La reconstrucción de EMA ahora se gestiona a través del orquestador principal.")
    print("\n   Para forzar una reconstrucción completa y segura del historial de equipos (EMA):")
    print("   1. Ejecute el orquestador con el flag '--purge-history'.")
    print("   2. Esto limpiará las tablas de datos calculados y luego ejecutará el pipeline")
    print("      completo, forzando a 'motor_data.py' a reconstruir todo desde cero.")
    print("\n   COMANDO A EJECUTAR:")
    print("   python ejecutar_proyecto.py --purge-history")
    print("="*80)
    sys.exit(0)

if __name__ == "__main__":
    main()
import sqlite3
import csv
import os

# ==========================================
# SCRIPT DE IMPORTACIÓN GOLD STANDARD
# Responsabilidad: Reconstruir la tabla 'partidos_backtest' desde
# una fuente de datos maestra (CSV) para garantizar la integridad.
# ==========================================

DB_NAME = 'fondo_quant.db'
CSV_GOLD_STANDARD = 'modelo_estable.csv'

def safe_float_from_csv(val_str):
    """Convierte un string con coma decimal a float."""
    if not val_str: return None
    try:
        return float(val_str.replace(',', '.'))
    except (ValueError, TypeError):
        return None

def safe_int_from_csv(val_str):
    """Convierte un string a int, manejando vacíos."""
    if not val_str: return None
    try:
        return int(val_str)
    except (ValueError, TypeError):
        return None

def main():
    if not os.path.exists(CSV_GOLD_STANDARD):
        print(f"[ERROR CRITICO] El archivo Gold Standard '{CSV_GOLD_STANDARD}' no fue encontrado. Proceso abortado.")
        return

    print("Iniciando protocolo de reconstrucción desde Gold Standard CSV.")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        print(f"Purgando la tabla 'partidos_backtest' para la reconstrucción...")
        cursor.execute("DELETE FROM partidos_backtest")

        partidos_insertados = 0
        with open(CSV_GOLD_STANDARD, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                id_partido = row.get('ID Partido')
                if not id_partido:
                    continue

                goles_l = safe_int_from_csv(row.get('Goles L'))
                goles_v = safe_int_from_csv(row.get('Goles V'))
                
                estado = 'Liquidado' if goles_l is not None and goles_v is not None and str(goles_l).strip() != '' and str(goles_v).strip() != '' else 'Pendiente'

                cursor.execute("""
                    INSERT INTO partidos_backtest (id_partido, fecha, local, visita, pais, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, goles_l, goles_v, formacion_l, formacion_v, estado) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id_partido, row.get('Fecha'), row.get('Local'), row.get('Visita'), row.get('Liga'),
                    safe_float_from_csv(row.get('Cuota 1')), safe_float_from_csv(row.get('Cuota X')), safe_float_from_csv(row.get('Cuota 2')),
                    safe_float_from_csv(row.get('Cuota +2.5')), safe_float_from_csv(row.get('Cuota -2.5')),
                    goles_l, goles_v, row.get('Formacion L'), row.get('Formacion V'), estado
                ))
                partidos_insertados += 1
        
        conn.commit()
        print(f"Reconstrucción de 'partidos_backtest' completada. Se insertaron {partidos_insertados} registros desde el Gold Standard.")

    except Exception as e:
        print(f"Error crítico durante la operación: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()
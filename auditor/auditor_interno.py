import sqlite3
import csv
import os
import difflib
import itertools
import unicodedata

# ==========================================
# AUDITOR INTERNO V1.0 (HIGIENE DE BASE DE DATOS)
# Responsabilidad: Detectar duplicados, errores tipográficos o inconsistencias en tu propia data.
# ==========================================

CSV_DATA = 'Apuestas deportivas _ Calculadora - Data.csv'
DB_NAME = 'fondo_quant.db'

def normalizar(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')

def extraer_equipos_propios():
    """Extrae todos los nombres de tu CSV y tu base SQLite"""
    equipos = set()
    
    # 1. Escanear el CSV (Data)
    if os.path.exists(CSV_DATA):
        try:
            with open(CSV_DATA, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if 'Equipo' in row: equipos.add(row['Equipo'].strip())
        except Exception as e:
            print(f"[!] Error leyendo {CSV_DATA}: {e}")

    # 2. Escanear SQLite (Partidos Históricos)
    if os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            # Leemos la tabla de stats y la de backtest
            try:
                cursor.execute("SELECT local, visita FROM partidos_backtest")
                for loc, vis in cursor.fetchall():
                    equipos.add(loc.strip())
                    equipos.add(vis.strip())
            except: pass
            conn.close()
        except: pass

    return sorted(list(equipos))

def main():
    print("[AUDIT] Iniciando Auditoría de Higiene Interna (Buscando inconsistencias en tu DATA)...")
    
    equipos = extraer_equipos_propios()
    if not equipos:
        print("[X] No se encontraron equipos en tu base de datos o CSV.")
        return
        
    print(f"   [v] Se detectaron {len(equipos)} nombres únicos de equipos en tu sistema.")
    print("\n[ATQ] Ejecutando análisis de colisión lingüística...\n")
    
    alertas = 0
    # Comparamos cada equipo contra todos los demás
    for eq1, eq2 in itertools.combinations(equipos, 2):
        n1 = normalizar(eq1)
        n2 = normalizar(eq2)
        
        # Filtro de similitud: Si se parecen más de un 85% pero no son idénticos
        similitud = difflib.SequenceMatcher(None, n1, n2).ratio()
        
        if similitud > 0.85:
            # Descartamos falsos positivos comunes que sí son equipos distintos
            falsos_positivos = ["manchester", "madrid", "milan", "racing"]
            if any(fp in n1 and fp in n2 for fp in falsos_positivos) and similitud < 0.95:
                continue
                
            print(f"   [ALERTA] POSIBLE DUPLICADO (Similitud {round(similitud*100)}%):")
            print(f"      -> '{eq1}'  vs  '{eq2}'")
            alertas += 1

    if alertas == 0:
        print("[OK] Tu base de datos está impecable. No hay equipos duplicados ni mal escritos.")
    else:
        print(f"\n[!] Se encontraron {alertas} posibles conflictos internos.")
        print("[TIP] Acción requerida: Elige un único nombre oficial para estos equipos, búscalo en tu Excel (Pestaña DATA o Backtest) y unifícalos.")

if __name__ == "__main__":
    main()
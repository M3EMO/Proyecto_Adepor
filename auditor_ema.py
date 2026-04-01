import sqlite3
import pandas as pd
import difflib

# ==========================================
# AUDITOR CUANTITATIVO V2.0 (DETECTOR DE HUECOS)
# Responsabilidad: Detectar equipos sin memoria EMA y auditar la salud del modelo.
# ==========================================

DB_NAME = 'fondo_quant.db'

def main():
    print("🔬 INICIANDO AUDITORÍA DEL MODELO BAYESIANO (EMA)...\n")

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # --- FASE 1: DETECCIÓN DE HUECOS DE MEMORIA ---
        print("1. Buscando equipos 'fantasma' (partidos jugados pero sin EMA guardado)...")

        # Obtener todos los equipos que han jugado un partido
        cursor.execute("SELECT DISTINCT local FROM partidos_backtest")
        equipos_partidos_loc = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT DISTINCT visita FROM partidos_backtest")
        equipos_partidos_vis = {row[0] for row in cursor.fetchall()}
        todos_los_equipos_jugados = sorted(list(equipos_partidos_loc.union(equipos_partidos_vis)))

        # Obtener todos los equipos que tienen un EMA calculado
        cursor.execute("SELECT equipo_real FROM historial_equipos")
        equipos_con_ema = {row[0] for row in cursor.fetchall()}

        equipos_fantasma = [eq for eq in todos_los_equipos_jugados if eq not in equipos_con_ema]

        if not equipos_fantasma:
            print("   ✅ ¡Excelente! Todos los equipos que han jugado tienen su memoria EMA correspondiente.\n")
        else:
            print(f"   🚨 ¡ALERTA! Se encontraron {len(equipos_fantasma)} equipos sin memoria EMA. Esto suele ser un problema de diccionario ('gestor_nombres').")
            for fantasma in equipos_fantasma:
                # Intentar encontrar una sugerencia para el usuario
                sugerencia = difflib.get_close_matches(fantasma, equipos_con_ema, n=1, cutoff=0.7)
                if sugerencia:
                    print(f"      - '{fantasma}' (Posiblemente debería ser '{sugerencia[0]}')")
                else:
                    print(f"      - '{fantasma}' (No se encontró un nombre similar en el historial)")
            print("\n")

        # --- FASE 2: MÉTRICAS GENERALES ---
        cursor.execute("SELECT COUNT(*) FROM historial_equipos")
        total_equipos = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM ema_procesados")
        total_partidos = cursor.fetchone()[0]

        print("2. Métricas de Memoria Global:")
        print(f"   • Equipos bajo radar (con EMA): {total_equipos}")
        print(f"   • Partidos históricos absorbidos: {total_partidos}\n")

        # --- FASE 3: RANKINGS DE PODERÍO ---
        print("3. Rankings de Poder (Top 10):")

        print("   ⚔️ TOP ATAQUES (Mayor xG Esperado a Favor - Home):")
        query_ataque = """
            SELECT equipo_real AS Equipo, liga AS Liga,
                   ema_xg_favor_home AS xG_Favor_H, (partidos_home + partidos_away) AS Partidos
            FROM historial_equipos 
            ORDER BY ema_xg_favor_home DESC
            LIMIT 10
        """
        df_ataque = pd.read_sql_query(query_ataque, conn)
        print(df_ataque.to_string(index=False))
        print("\n" + "-"*80 + "\n")

        print("   🛡️ TOP DEFENSAS (Menor xG Esperado en Contra - Home):")
        query_defensa = """
            SELECT equipo_real AS Equipo, liga AS Liga,
                   ema_xg_contra_home AS xG_Contra_H, (partidos_home + partidos_away) AS Partidos
            FROM historial_equipos 
            WHERE (partidos_home + partidos_away) > 3
            ORDER BY ema_xg_contra_home ASC
            LIMIT 10
        """
        df_defensa = pd.read_sql_query(query_defensa, conn)
        print(df_defensa.to_string(index=False))
        print("\n")
        
        conn.close()

    except sqlite3.OperationalError as e:
        print(f"⚠️ Error: La base de datos o sus tablas no existen. Ejecuta 'motor_data.py' primero. ({e})")

if __name__ == "__main__":
    main()
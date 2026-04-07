import sqlite3
from datetime import datetime
import pandas as pd

# ==========================================
# VISUALIZADOR DE MOMENTUM V1.0
# Responsabilidad: Mostrar el factor de momentum actual de los equipos de una liga.
# ==========================================

DB_NAME = 'fondo_quant.db'

def obtener_factor_momentum(cursor, equipo_real, fecha_actual_str):
    """
    Analiza los últimos 5 resultados de un equipo para generar un factor de momentum.
    Una racha de victorias aumenta el xG esperado, una de derrotas lo disminuye.
    """
    try:
        f_act = str(fecha_actual_str).split(" ")[0]
        d_act = datetime.strptime(f_act, "%d/%m/%Y")
        
        cursor.execute("""
            SELECT local, visita, goles_l, goles_v FROM partidos_backtest 
            WHERE (local = ? OR visita = ?) AND estado = 'Liquidado' AND fecha < ?
            ORDER BY fecha DESC LIMIT 5
        """, (equipo_real, equipo_real, d_act.strftime("%Y-%m-%d")))
        
        ultimos_partidos = cursor.fetchall()
        if not ultimos_partidos: return 1.0, 0

        score = 0
        for loc, vis, gl, gv in ultimos_partidos:
            if (loc == equipo_real and gl > gv) or (vis == equipo_real and gv > gl): score += 2 # Victoria
            elif gl == gv: score += 1 # Empate
        
        max_score_posible = len(ultimos_partidos) * 2
        factor = 0.90 + (0.20 * (score / max_score_posible))
        return round(factor, 4), len(ultimos_partidos)
    except Exception as e:
        print(f"Error calculando momentum para {equipo_real}: {e}")
        return 1.0, 0

def main():
    liga_seleccionada = input("Ingrese el nombre de la liga para analizar (ej: Argentina, Brasil, Inglaterra): ").strip().title()

    print(f"\n📈 Analizando Momentum para la liga: {liga_seleccionada}...")
    
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT local FROM partidos_backtest WHERE pais = ?", (liga_seleccionada,))
        equipos_loc = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT DISTINCT visita FROM partidos_backtest WHERE pais = ?", (liga_seleccionada,))
        equipos_vis = {row[0] for row in cursor.fetchall()}
        equipos_unicos = sorted(list(equipos_loc.union(equipos_vis)))

        if not equipos_unicos:
            print(f"No se encontraron equipos para la liga '{liga_seleccionada}'. Verifique el nombre.")
            return

        fecha_hoy = datetime.now().strftime("%d/%m/%Y")
        datos_momentum = [{"Equipo": eq, "Factor Momentum": obtener_factor_momentum(cursor, eq, fecha_hoy)[0], "Partidos Analizados": obtener_factor_momentum(cursor, eq, fecha_hoy)[1]} for eq in equipos_unicos]

        df = pd.DataFrame(datos_momentum).sort_values(by="Factor Momentum", ascending=False)
        print("\n" + "="*60 + f"\n  Factor de Momentum Actual - {liga_seleccionada}\n  (> 1.0 = Racha Positiva, < 1.0 = Racha Negativa)\n" + "="*60)
        print(df.to_string(index=False))
        print("="*60)
    except sqlite3.Error as e: print(f"Error de base de datos: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()
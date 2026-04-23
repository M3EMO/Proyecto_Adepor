import sqlite3
import pandas as pd
import math
import difflib
import unicodedata

# ==========================================
# MOTOR CALCULADORA V9.5 (POISSON & FUZZY MATCH)
# Responsabilidad: Cruzar memoria EMA con el Backtest y asignar Probabilidades.
# ==========================================

DB_NAME = 'fondo_quant.db'
CSV_FILE = 'Apuestas deportivas _ Calculadora - Backtest.csv'

def normalizar_extremo(texto):
    if not isinstance(texto, str): return ""
    crudo = ''.join(c for c in unicodedata.normalize('NFD', texto.lower().strip()) if unicodedata.category(c) != 'Mn')
    return crudo.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")

def obtener_ema(equipo_norm, historial_ema):
    """
    Algoritmo de IA de Emparejamiento.
    Busca la fuerza matemática de un equipo usando 3 capas de tolerancia.
    """
    default_ema = {'fav_h': 1.4, 'con_h': 1.4, 'fav_a': 1.4, 'con_a': 1.4}
    
    if not equipo_norm:
        return default_ema

    # 1. Coincidencia Exacta
    if equipo_norm in historial_ema:
        data = historial_ema[equipo_norm]
        return data

    # 2. Coincidencia por Subcadena Inteligente
    for eq_db, data in historial_ema.items():
        if eq_db in equipo_norm or equipo_norm in eq_db:
            return data

    # 3. Coincidencia Difusa (Fuzzy Match - Tolerancia 45%)
    matches = difflib.get_close_matches(equipo_norm, historial_ema.keys(), n=1, cutoff=0.45)
    if matches:
        data = historial_ema[matches[0]]
        return data
        
    return default_ema

def poisson(k, lmbda):
    try:
        return (lmbda**k * math.exp(-lmbda)) / math.factorial(k)
    except:
        return 0.0

def calcular_distribucion_poisson(xg_local, xg_visita):
    """
    Ejecuta una matriz de colisiones de Poisson (hasta 8x8 goles)
    para derivar las probabilidades reales de 1X2 y Over/Under.
    """
    prob_1 = prob_x = prob_2 = 0.0
    prob_over = prob_under = 0.0
    
    for goles_l in range(8):
        for goles_v in range(8):
            probabilidad_resultado = poisson(goles_l, xg_local) * poisson(goles_v, xg_visita)
            
            if goles_l > goles_v:
                prob_1 += probabilidad_resultado
            elif goles_l == goles_v:
                prob_x += probabilidad_resultado
            else:
                prob_2 += probabilidad_resultado
                
            if (goles_l + goles_v) > 2.5:
                prob_over += probabilidad_resultado
            else:
                prob_under += probabilidad_resultado
                
    # Normalización para forzar que sumen exactamente 1.0 (100%)
    total_1x2 = prob_1 + prob_x + prob_2
    if total_1x2 > 0:
        prob_1 /= total_1x2
        prob_x /= total_1x2
        prob_2 /= total_1x2
        
    total_ou = prob_over + prob_under
    if total_ou > 0:
        prob_over /= total_ou
        prob_under /= total_ou

    return prob_1, prob_x, prob_2, prob_over, prob_under

def main():
    print("[SISTEMA] Iniciando Cerebro Predictivo (Motor Calculadora V9.5)...")
    
    # 1. Cargar Memoria Cuantitativa (EMA)
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Key compuesta (equipo_norm, liga): historial_equipos admite mismo equipo_norm en varias ligas.
        cursor.execute("SELECT equipo_norm, liga, ema_xg_favor_home, ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away FROM historial_equipos")
        historial_ema = {}
        for row in cursor.fetchall():
            historial_ema[(row[0], row[1])] = {
                'fav_h': row[2] or 1.4, 'con_h': row[3] or 1.4,
                'fav_a': row[4] or 1.4, 'con_a': row[5] or 1.4
            }
        conn.close()
        print(f"[PROCESO] Memoria cargada: {len(historial_ema)} equipos identificados.")
    except Exception as e:
        print(f"[ERROR CRÍTICO] No se pudo leer la base de datos: {e}")
        return

    # 2. Cargar Matriz (Backtest)
    try:
        df = pd.read_csv(CSV_FILE)
    except FileNotFoundError:
        print(f"[ERROR CRÍTICO] Archivo CSV no encontrado: {CSV_FILE}")
        return

    actualizaciones = 0

    # 3. Cruzar Datos y Calcular (Ignorando partidos ya liquidados)
    print("[PROCESO] Calculando matrices de probabilidad...")
    for index, row in df.iterrows():
        estado_apuesta = str(row.get('Apuesta 1X2', '')).upper()
        
        # Saltamos si el liquidador ya cerró este partido
        if '[GANADA]' in estado_apuesta or '[PERDIDA]' in estado_apuesta:
            continue

        local_raw = row.get('Local', '')
        visita_raw = row.get('Visita', '')
        
        if pd.isna(local_raw) or pd.isna(visita_raw):
            continue

        loc_norm = normalizar_extremo(str(local_raw))
        vis_norm = normalizar_extremo(str(visita_raw))

        ema_loc = obtener_ema(loc_norm, historial_ema)
        ema_vis = obtener_ema(vis_norm, historial_ema)

        # Fusión Híbrida de Fuerza: Ataque del Local vs Defensa de la Visita y viceversa
        xg_esperado_local = (ema_loc['fav_h'] + ema_vis['con_a']) / 2.0
        xg_esperado_visita = (ema_vis['fav_a'] + ema_loc['con_h']) / 2.0

        # Cálculo Estadístico
        p1, px, p2, po, pu = calcular_distribucion_poisson(xg_esperado_local, xg_esperado_visita)

        # Inyección en la Matriz
        df.at[index, 'Prob 1'] = f"{p1:.2%}".replace('.', ',')
        df.at[index, 'Prob X'] = f"{px:.2%}".replace('.', ',')
        df.at[index, 'Prob 2'] = f"{p2:.2%}".replace('.', ',')
        df.at[index, 'Prob +2.5'] = f"{po:.2%}".replace('.', ',')
        df.at[index, 'Prob -2.5'] = f"{pu:.2%}".replace('.', ',')
        
        actualizaciones += 1

    # 4. Volcado Final
    if actualizaciones > 0:
        df.to_csv(CSV_FILE, index=False, encoding='utf-8')
        print(f"[EXITO] {actualizaciones} colisiones predictivas calculadas y guardadas.")
    else:
        print("[INFO] No hay partidos pendientes para calcular.")

if __name__ == "__main__":
    main()
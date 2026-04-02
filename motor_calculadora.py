import sqlite3
import math
import unicodedata
import difflib
from datetime import datetime
from collections import defaultdict

# ==========================================
# MOTOR CALCULADORA V3.0 (MODELO DIXON-COLES)
# Responsabilidad: Calcular probabilidades usando un modelo de Poisson Bivariado (Dixon-Coles)
# basado en el EMA histórico y el factor de correlación (rho).
# ==========================================

# --- Constantes de Configuración ---
DB_NAME = 'fondo_quant.db'
MAX_KELLY_PCT_NORMAL = 0.025
MAX_KELLY_PCT_DRAWDOWN = 0.010
DRAWDOWN_THRESHOLD = 5


# --- Funciones de Riesgo y Liquidación (Tomadas de calc_repuesto) ---

def determinar_resultado_apuesta(apuesta, gl, gv):
    """Determina si una apuesta fue GANADA o PERDIDA basado en el resultado."""
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"

    if "LOCAL" in apuesta: return "GANADA" if gl > gv else "PERDIDA"
    if "EMPATE" in apuesta: return "GANADA" if gl == gv else "PERDIDA"
    if "VISITA" in apuesta: return "GANADA" if gl < gv else "PERDIDA"
    if "OVER 2.5" in apuesta: return "GANADA" if (gl + gv) > 2.5 else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl + gv) < 2.5 else "PERDIDA"

    return "INDETERMINADO"

def detectar_drawdown(cursor, umbral_perdidas=DRAWDOWN_THRESHOLD):
    """
    Detecta si el sistema está en una racha de N pérdidas consecutivas
    para activar el modo de protección de capital (drawdown).
    """
    cursor.execute("""
        SELECT apuesta_1x2, apuesta_ou, goles_l, goles_v FROM partidos_backtest
        WHERE estado = 'Liquidado' AND (stake_1x2 > 0 OR stake_ou > 0)
        ORDER BY fecha DESC LIMIT 20
    """)
    ultimas_apuestas = cursor.fetchall()
    perdidas_consecutivas = 0
    for ap_1x2, ap_ou, gl, gv in ultimas_apuestas:
        # Determinar cuál fue la apuesta real (1X2 o O/U)
        apuesta_real = ap_1x2 if "[APOSTAR]" in str(ap_1x2) else ap_ou
        resultado = determinar_resultado_apuesta(apuesta_real, gl, gv)
        
        if resultado == "PERDIDA":
            perdidas_consecutivas += 1
        elif resultado == "GANADA":
            # Una victoria rompe la racha de pérdidas
            return False
        
        if perdidas_consecutivas >= umbral_perdidas:
            return True
            
    return perdidas_consecutivas >= umbral_perdidas

# --- Funciones de Utilidad y Normalización ---

def normalizar_extremo(texto):
    """Limpia y normaliza un nombre de equipo para facilitar el matching."""
    if not texto: return ""
    # Elimina tildes, convierte a minúsculas y quita caracteres no alfanuméricos
    crudo = ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')
    return crudo.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")

def safe_float(val):
    """Convierte un valor a float de forma segura, devolviendo 0.0 en caso de error."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

# --- Funciones de Lógica de Modelo ---

def obtener_ema(equipo_norm, historial_ema):
    """
    Busca los datos de EMA (xG y Varianza) de un equipo.
    Usa un fuzzy match simple como fallback si no encuentra una coincidencia exacta.
    """
    # Valores por defecto si un equipo es completamente nuevo
    default_ema = {'fav_home': 1.4, 'con_home': 1.4, 'fav_away': 1.4, 'con_away': 1.4, 'var_fh': 0.1, 'var_ch': 0.1, 'var_fa': 0.1, 'var_ca': 0.1}
    
    if equipo_norm in historial_ema:
        data = historial_ema[equipo_norm]
        # Aseguramos que no haya valores nulos que rompan el cálculo
        return {
            'fav_home': data.get('fav_home') or 1.4, 'con_home': data.get('con_home') or 1.4,
            'fav_away': data.get('fav_away') or 1.4, 'con_away': data.get('con_away') or 1.4,
            'var_fh': data.get('var_fh') or 0.1, 'var_ch': data.get('var_ch') or 0.1,
            'var_fa': data.get('var_fa') or 0.1, 'var_ca': data.get('var_ca') or 0.1,
        }

    # Fallback: buscar el nombre más parecido con una similitud > 70%
    matches = difflib.get_close_matches(equipo_norm, historial_ema.keys(), n=1, cutoff=0.7)
    if matches:
        data = historial_ema[matches[0]]
        return {
            'fav_home': data.get('fav_home') or 1.4, 'con_home': data.get('con_home') or 1.4,
            'fav_away': data.get('fav_away') or 1.4, 'con_away': data.get('con_away') or 1.4,
            'var_fh': data.get('var_fh') or 0.1, 'var_ch': data.get('var_ch') or 0.1,
            'var_fa': data.get('var_fa') or 0.1, 'var_ca': data.get('var_ca') or 0.1,
        }
        
    return default_ema

def poisson(k, lmbda):
    """Calcula la probabilidad de k eventos para una media lmbda."""
    if lmbda <= 0: return 0.0
    try:
        # (e^-lmbda * lmbda^k) / k!
        return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)
    except (ValueError, OverflowError):
        # Previene errores con números muy grandes, aunque k<8 es seguro.
        return 0.0

# --- Funciones de Decisión y Sizing (Capa de Apuesta) ---

def evaluar_mercado_1x2(p1, px, p2, c1, cx, c2):
    """
    Evalúa el mercado 1X2 para encontrar apuestas con valor esperado positivo (EV+).
    Aplica reglas de negocio como margen predictivo y techos de cuota.
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return "[PASAR] Sin Cuotas", -100, 0

    # Regla: Si el modelo no tiene una convicción mínima, no se apuesta.
    probs_ordenadas = sorted([p1, px, p2])
    margen_predictivo = probs_ordenadas[2] - probs_ordenadas[1]
    if margen_predictivo < 0.05: # Requiere al menos un 5% de diferencia entre el 1ro y 2do más probables
        return "[PASAR] Margen Predictivo Insuficiente (<5%)", -100, 0

    probs = {"LOCAL": p1, "EMPATE": px, "VISITA": p2}
    cuotas = {"LOCAL": c1, "EMPATE": cx, "VISITA": c2}
    
    # Identificar la opción favorita del modelo para aplicar un sesgo
    pick_favorito = max(probs, key=probs.get)

    # Búsqueda de la mejor apuesta por EV, con un umbral más estricto para las no-favoritas
    max_ev = -100
    best_pick = None
    
    for pick, prob in probs.items():
        cuota = cuotas[pick]
        if cuota <= 1.0: continue
        
        ev = (prob * cuota) - 1
        
        # Umbral de EV base, dinámico basado en la probabilidad
        umbral_ev_base = (0.03 * (0.5 / prob)) if prob > 0 else 999
        
        # Aplicar un umbral más estricto si la apuesta no es la favorita del modelo
        # Esto hace que el sistema prefiera al favorito, pero no descarta un underdog con mucho valor.
        factor_penalizacion = 1.5 if pick != pick_favorito else 1.0
        umbral_ev_ajustado = umbral_ev_base * factor_penalizacion
        
        # Criterios de apuesta
        if ev > umbral_ev_ajustado and cuota <= 5.0:
            if ev > max_ev:
                max_ev = ev
                best_pick = (f"[APOSTAR] {pick}", ev, cuota)

    if best_pick:
        return best_pick

    return "[PASAR] Sin Valor", -100, 0

def evaluar_mercado_ou(po, pu, co, cu, p1, px, p2):
    """
    Evalúa el mercado Over/Under 2.5. Es más estricto que el 1X2.
    Solo apuesta a favor de la tendencia más probable.
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [co, cu]):
        return "[PASAR] Sin Cuotas", -100, 0

    # Regla: Si el modelo no tiene una convicción mínima en el mercado de goles, no se apuesta.
    margen_predictivo_ou = abs(po - pu)
    if margen_predictivo_ou < 0.05: # Requiere una diferencia de al menos 15% entre Over y Under
        return "[PASAR] Margen Predictivo O/U Insuficiente (<5%)", -100, 0

    probs = {"OVER 2.5": po, "UNDER 2.5": pu}
    cuotas = {"OVER 2.5": co, "UNDER 2.5": cu}
    
    # Identificar la opción favorita del modelo
    pick_favorito = max(probs, key=probs.get)
    prob_fav = probs[pick_favorito]
    cuota_fav = cuotas[pick_favorito]

    if cuota_fav <= 1.0:
        return "[PASAR] Cuota Inválida", -100, 0

    ev_fav = (prob_fav * cuota_fav) - 1
    umbral_ev = (0.025 * (0.5 / prob_fav)) if prob_fav > 0 else 999

    # Criterios de apuesta para O/U
    if ev_fav > umbral_ev and cuota_fav <= 6.0:
        return f"[APOSTAR] {pick_favorito}", ev_fav, cuota_fav

    return "[PASAR] Sin Valor", ev_fav, cuota_fav

def calcular_stake_independiente(pick, ev, cuota, bankroll, max_kelly_pct):
    """Calcula el tamaño de la apuesta usando el Criterio de Kelly fraccional."""
    if "[APOSTAR]" not in pick or ev <= 0 or cuota <= 1:
        return 0.0
    try:
        # k = (p*c - 1) / (c - 1), donde p es la probabilidad real
        prob_real = (1 / cuota) * (1 + ev)
        kelly_full = (prob_real * cuota - 1) / (cuota - 1)
        
        # Aplicamos una fracción del Kelly para ser conservadores y limitamos al máximo configurado
        fraccion_kelly = min(kelly_full, max_kelly_pct)
        
        return round(bankroll * fraccion_kelly, 2)
    except (ZeroDivisionError, TypeError):
        return 0.0

def ajustar_stakes_por_covarianza(lista_apuestas_potenciales):
    """
    Ajusta los stakes de apuestas en la misma liga y día para reducir el riesgo
    de correlación. Penaliza el stake usando la raíz cuadrada del número de apuestas.
    """
    apuestas_agrupadas = defaultdict(list)
    for apuesta in lista_apuestas_potenciales:
        # Agrupamos por (país, día)
        fecha_dia = str(apuesta.get('fecha', '')).split(" ")[0]
        pais = apuesta.get('pais', 'Desconocido')
        clave_agrupacion = (pais, fecha_dia)
        apuestas_agrupadas[clave_agrupacion].append(apuesta)

    for _, apuestas_en_grupo in apuestas_agrupadas.items():
        n = len(apuestas_en_grupo)
        if n > 1:
            # Factor de penalización: 1 / sqrt(N)
            factor = 1 / (n ** 0.5)
            for apuesta in apuestas_en_grupo:
                apuesta['stk_1x2'] *= factor
                apuesta['stk_ou'] *= factor

# --- Función Principal ---

def main():
    """
    Orquesta todo el proceso de cálculo:
    1. Carga datos.
    2. Itera sobre partidos pendientes.
    3. Calcula xG y probabilidades.
    4. Evalúa mercados y calcula stakes.
    5. Ajusta riesgo y actualiza la base de datos.
    """
    print("[SISTEMA] Iniciando Motor Calculadora V3.0 (Modelo Dixon-Coles)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- FASE 0: GESTIÓN DE RIESGO GLOBAL ---
    MAX_KELLY_PCT = MAX_KELLY_PCT_NORMAL
    if detectar_drawdown(cursor):
        MAX_KELLY_PCT = MAX_KELLY_PCT_DRAWDOWN
        print(f"[ALERTA] Drawdown detectado. MAX_KELLY_PCT reducido a {MAX_KELLY_PCT_DRAWDOWN * 100}%.")
    else:
        print(f"[INFO] Nivel de riesgo normal. MAX_KELLY_PCT en {MAX_KELLY_PCT_NORMAL * 100}%.")

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        BANKROLL = float(cursor.fetchone()[0])
    except (TypeError, IndexError):
        BANKROLL = 100000.00 # Bankroll por defecto si no está en la DB
    print(f"[INFO] Bankroll operativo: ${BANKROLL:,.2f}")

    # --- FASE 1: CARGA DE DATOS ESENCIALES ---
    cursor.execute("""
        SELECT equipo_norm, ema_xg_favor_home, ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away,
               ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away
        FROM historial_equipos
    """)
    historial_ema = {row[0]: {'fav_home': row[1], 'con_home': row[2], 'fav_away': row[3], 'con_away': row[4], 
                              'var_fh': row[5], 'var_ch': row[6], 'var_fa': row[7], 'var_ca': row[8]} for row in cursor.fetchall()}

    cursor.execute("SELECT liga, rho_calculado FROM ligas_stats")
    rho_por_liga = {row[0]: row[1] for row in cursor.fetchall()}
    RHO_ESTATICO_FALLBACK = -0.03 # Valor de respaldo si una liga no tiene rho

    cursor.execute("""
        SELECT p.id_partido, p.local, p.visita, p.pais, p.fecha,
               p.cuota_1, p.cuota_x, p.cuota_2, p.cuota_o25, p.cuota_u25
        FROM partidos_backtest p
        WHERE p.estado = 'Pendiente' OR p.estado = 'Calculado'
    """)
    partidos_pendientes = cursor.fetchall()
    
    if not partidos_pendientes:
        print("[INFO] No hay partidos nuevos para calcular.")
        conn.close()
        return

    partidos_a_actualizar = []

    # --- FASE 2: CÁLCULO Y DECISIÓN POR PARTIDO ---
    for partido in partidos_pendientes:
        id_partido, local, visita, pais, fecha_str, c1, cx, c2, co, cu = partido
        
        loc_norm, vis_norm = normalizar_extremo(local), normalizar_extremo(visita)

        ema_l = obtener_ema(loc_norm, historial_ema)
        ema_v = obtener_ema(vis_norm, historial_ema)
        
        # MODELO ESTABLE (POISSON PURO): xG basado en la media del ataque de un equipo y la defensa del otro.
        # Se eliminan todos los factores contextuales (momentum, descanso, altitud, etc.)
        xg_local = (ema_l['fav_home'] + ema_v['con_away']) / 2.0
        xg_visita = (ema_v['fav_away'] + ema_l['con_home']) / 2.0

        # Modelo de Goles: Distribución de Poisson Bivariada (Dixon-Coles)
        p1, px, p2, po, pu = 0.0, 0.0, 0.0, 0.0, 0.0
        rho = rho_por_liga.get(pais, RHO_ESTATICO_FALLBACK)
        
        for i in range(8): # Goles Local
            for j in range(8): # Goles Visita
                # Probabilidad base de un resultado i-j
                pb = poisson(i, xg_local) * poisson(j, xg_visita)

                # Ajuste Bivariado (Dixon-Coles con factor Rho)
                if i == 0 and j == 0: pb *= (1 - xg_local * xg_visita * rho)
                elif i == 0 and j == 1: pb *= (1 + xg_local * rho)
                elif i == 1 and j == 0: pb *= (1 + xg_visita * rho)
                elif i == 1 and j == 1: pb *= (1 - rho)
                pb = max(0.0, pb) # Asegurar que la probabilidad no sea negativa

                if i > j: p1 += pb
                elif i == j: px += pb
                else: p2 += pb
                
                if (i + j) > 2.5: po += pb
                else: pu += pb

        # Normalización de probabilidades para que sumen 100%
        suma_1x2 = p1 + px + p2
        if suma_1x2 > 0: p1, px, p2 = p1/suma_1x2, px/suma_1x2, p2/suma_1x2
        suma_ou = po + pu
        if suma_ou > 0: po, pu = po/suma_ou, pu/suma_ou

        # --- CAPA DE DECISIÓN ---
        c1_val, cx_val, c2_val = safe_float(c1), safe_float(cx), safe_float(c2)
        co_val, cu_val = safe_float(co), safe_float(cu)
        
        pick_1x2, ev_1x2, cu_1x2 = evaluar_mercado_1x2(p1, px, p2, c1_val, cx_val, c2_val)
        pick_ou, ev_ou, cu_ou = evaluar_mercado_ou(po, pu, co_val, cu_val, p1, px, p2)
        
        stk_1x2 = calcular_stake_independiente(pick_1x2, ev_1x2, cu_1x2, BANKROLL, MAX_KELLY_PCT)
        stk_ou = calcular_stake_independiente(pick_ou, ev_ou, cu_ou, BANKROLL, MAX_KELLY_PCT)

        # Lógica de Overlap: si hay valor en 1X2 y O/U, priorizar la de mayor EV.
        if stk_1x2 > 0 and stk_ou > 0:
            if ev_1x2 >= ev_ou:
                stk_ou = 0.0
                pick_ou = "[PASAR] Overlap Riesgo (1X2 Priorizado)"
            else:
                stk_1x2 = 0.0
                pick_1x2 = "[PASAR] Overlap Riesgo (O/U Priorizado)"

        partidos_a_actualizar.append({
            'id_partido': id_partido, 'pais': pais, 'fecha': fecha_str,
            'p1': p1, 'px': px, 'p2': p2, 'po': po, 'pu': pu,
            'pick_1x2': pick_1x2, 'ev_1x2': ev_1x2, 'cu_1x2': cu_1x2, 'stk_1x2': stk_1x2,
            'pick_ou': pick_ou, 'ev_ou': ev_ou, 'cu_ou': cu_ou, 'stk_ou': stk_ou
        })

    # --- FASE 3: AJUSTE DE RIESGO POR COVARIANZA ---
    apuestas_potenciales = [p for p in partidos_a_actualizar if p['stk_1x2'] > 0 or p['stk_ou'] > 0]
    if apuestas_potenciales:
        print(f"[INFO] {len(apuestas_potenciales)} apuestas potenciales. Aplicando ajuste de covarianza...")
        ajustar_stakes_por_covarianza(apuestas_potenciales)

    # --- FASE 4: ACTUALIZACIÓN EN BASE DE DATOS ---
    calculados = 0
    for p in partidos_a_actualizar:
        cursor.execute("""
            UPDATE partidos_backtest 
            SET prob_1=?, prob_x=?, prob_2=?, prob_o25=?, prob_u25=?, 
                apuesta_1x2=?, apuesta_ou=?, stake_1x2=?, stake_ou=?, 
                estado='Calculado'
            WHERE id_partido=?
        """, (
            p['p1'], p['px'], p['p2'], p['po'], p['pu'], 
            p['pick_1x2'], p['pick_ou'], 
            round(p['stk_1x2'], 2), round(p['stk_ou'], 2),
            p['id_partido']
        ))
        calculados += 1

    conn.commit()
    conn.close()
    print(f"[EXITO] {calculados} partidos calculados y/o actualizados.")
    print("[SISTEMA] Motor Calculadora (Dixon-Coles) ha finalizado su ejecución.")

if __name__ == "__main__":
    main()
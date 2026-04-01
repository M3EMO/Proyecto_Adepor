import sqlite3
import math
import unicodedata
import difflib
from datetime import datetime
from collections import defaultdict

# ==========================================
# MOTOR CALCULADORA V12.7 (AJUSTE DE COVARIANZA KELLY)
# ==========================================

DB_NAME = 'fondo_quant.db'
MAX_KELLY_PCT_NORMAL = 0.025
MAX_KELLY_PCT_DRAWDOWN = 0.010
DRAWDOWN_THRESHOLD = 5

GRUPO_OFENSIVO = ["4-3-3", "4-2-3-1", "3-4-3", "3-4-2-1", "4-1-2-1-2"]
GRUPO_EQUILIBRIO = ["4-4-2", "4-1-4-1", "4-4-1-1", "4-5-1"]
GRUPO_DEFENSIVO = ["5-3-2", "5-4-1", "3-5-2", "5-2-3"]

# Base de datos de partidos de alta tensión (Clásicos/Derbies)
DERBIES = {
    frozenset({'bocajuniors', 'riverplate'}),
    frozenset({'racingclub', 'independiente'}),
    frozenset({'sanlorenzo', 'huracan'}),
    frozenset({'rosariocentral', 'newellsoldboys'}),
    frozenset({'estudiantesdelaplata', 'gimnasialaplata'})
}

def determinar_resultado_apuesta(apuesta, gl, gv):
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"

    if "LOCAL" in apuesta: return "GANADA" if gl > gv else "PERDIDA"
    if "EMPATE" in apuesta: return "GANADA" if gl == gv else "PERDIDA"
    if "VISITA" in apuesta: return "GANADA" if gl < gv else "PERDIDA"
    if "OVER 2.5" in apuesta: return "GANADA" if (gl + gv) > 2.5 else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl + gv) < 2.5 else "PERDIDA"

    return "INDETERMINADO"

def detectar_drawdown(cursor, umbral_perdidas=DRAWDOWN_THRESHOLD):
    cursor.execute("""
        SELECT apuesta_1x2, apuesta_ou, goles_l, goles_v FROM partidos_backtest
        WHERE estado = 'Liquidado' AND (stake_1x2 > 0 OR stake_ou > 0)
        ORDER BY fecha DESC LIMIT 20
    """)
    ultimas_apuestas = cursor.fetchall()
    perdidas_consecutivas = 0
    for ap_1x2, ap_ou, gl, gv in ultimas_apuestas:
        apuesta_real = ap_1x2 if "[APOSTAR]" in str(ap_1x2) else ap_ou
        resultado = determinar_resultado_apuesta(apuesta_real, gl, gv)
        if resultado == "PERDIDA": perdidas_consecutivas += 1
        elif resultado == "GANADA": return False
        if perdidas_consecutivas >= umbral_perdidas: return True
    return perdidas_consecutivas >= umbral_perdidas

def normalizar_extremo(texto):
    if not texto: return ""
    crudo = ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')
    return crudo.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")

def obtener_ema(equipo_norm, historial_ema):
    default_ema = {'fav_home': 1.4, 'con_home': 1.4, 'fav_away': 1.4, 'con_away': 1.4, 'var_fh': 0.1, 'var_ch': 0.1, 'var_fa': 0.1, 'var_ca': 0.1}
    if equipo_norm in historial_ema:
        data = historial_ema[equipo_norm]
        return {
            'fav_home': data.get('fav_home') or 1.4, 'con_home': data.get('con_home') or 1.4,
            'fav_away': data.get('fav_away') or 1.4, 'con_away': data.get('con_away') or 1.4,
            'var_fh': data.get('var_fh') or 0.1, 'var_ch': data.get('var_ch') or 0.1,
            'var_fa': data.get('var_fa') or 0.1, 'var_ca': data.get('var_ca') or 0.1,
        }
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

def obtener_dias_descanso(cursor, equipo_real, fecha_actual_str):
    try:
        f_act = str(fecha_actual_str).split(" ")[0]
        d_act = datetime.strptime(f_act, "%d/%m/%Y")
        cursor.execute("""
            SELECT fecha FROM partidos_backtest 
            WHERE (local = ? OR visita = ?) AND estado = 'Liquidado'
            ORDER BY rowid DESC LIMIT 1
        """, (equipo_real, equipo_real))
        row = cursor.fetchone()
        if row and row[0]:
            f_ant = str(row[0]).split(" ")[0]
            d_ant = datetime.strptime(f_ant, "%d/%m/%Y")
            return (d_act - d_ant).days
    except: pass
    return 7 

def obtener_factor_momentum(cursor, equipo_real, fecha_actual_str, is_derby=False):
    """
    Analiza los últimos 5 resultados de un equipo para generar un factor de momentum.
    Una racha de victorias aumenta el xG esperado, una de derrotas lo disminuye.
    El efecto es más pronunciado en partidos de alta tensión (derbies).
    """
    try:
        f_act = str(fecha_actual_str).split(" ")[0]
        d_act = datetime.strptime(f_act, "%d/%m/%Y")
        
        cursor.execute("""
            SELECT local, visita, goles_l, goles_v FROM partidos_backtest 
            WHERE (local = ? OR visita = ?) AND estado = 'Liquidado' AND fecha < ?
            ORDER BY fecha DESC LIMIT 5
        """, (equipo_real, equipo_real, d_act.strftime("%Y-%m-%d"))) # Se usa formato ISO para la comparación
        
        ultimos_partidos = cursor.fetchall()
        if not ultimos_partidos: return 1.0

        score = 0
        for loc, vis, gl, gv in ultimos_partidos:
            if (loc == equipo_real and gl > gv) or (vis == equipo_real and gv > gl): score += 2 # Victoria
            elif gl == gv: score += 1 # Empate
        
        max_score_posible = len(ultimos_partidos) * 2
        
        base, rango = (0.85, 0.30) if is_derby else (0.90, 0.20)
        return base + (rango * (score / max_score_posible)) # Derby: [0.85, 1.15], Normal: [0.90, 1.10]
    except: return 1.0

def colision_tactica(form_l, form_v):
    if not form_l or not form_v: return 1.0, 1.0
    def clasificar(f):
        if f in GRUPO_OFENSIVO: return "OFE"
        if f in GRUPO_DEFENSIVO: return "DEF"
        return "EQU"
    cat_l, cat_v = clasificar(form_l), clasificar(form_v)
    matriz = {
        ("OFE", "EQU"): (1.04, 0.98), ("OFE", "DEF"): (0.94, 1.05), ("OFE", "OFE"): (1.0, 1.0),
        ("EQU", "OFE"): (0.98, 1.04), ("EQU", "DEF"): (1.02, 0.96), ("EQU", "EQU"): (1.0, 1.0),
        ("DEF", "OFE"): (1.05, 0.94), ("DEF", "EQU"): (0.96, 1.02), ("DEF", "DEF"): (1.0, 1.0)
    }
    return matriz.get((cat_l, cat_v), (1.0, 1.0))
def ajustar_stakes_por_covarianza(lista_apuestas_potenciales):
    """
    Penaliza los stakes de apuestas simultáneas en la misma liga y EL MISMO DÍA
    para mitigar el riesgo de correlación temporal.
    """
    stakes_originales = {}
    try:
        # 1. Backup estricto de los valores originales
        stakes_originales = {
            apuesta['id_partido']: (apuesta['stk_1x2'], apuesta['stk_ou'])
            for apuesta in lista_apuestas_potenciales
        }
        
        # 2. Nueva clusterización por (País, Día)
        apuestas_agrupadas = defaultdict(list)
        for apuesta in lista_apuestas_potenciales:
            # Cortamos la hora si existe, quedándonos solo con 'DD/MM/YYYY'
            fecha_exacta = str(apuesta.get('fecha', '')).split(" ")[0]
            pais = apuesta.get('pais', 'Desconocido')
            
            # La llave del diccionario ahora es una tupla doble
            clave_agrupacion = (pais, fecha_exacta)
            apuestas_agrupadas[clave_agrupacion].append(apuesta)

        # 3. Aplicación de la penalización matemática
        for clave, apuestas_en_grupo in apuestas_agrupadas.items():
            n_apuestas_correlacionadas = len(apuestas_en_grupo)
            if n_apuestas_correlacionadas > 1:
                factor_penalizacion = 1 / (n_apuestas_correlacionadas ** 0.5)
                for apuesta in apuestas_en_grupo:
                    apuesta['stk_1x2'] *= factor_penalizacion
                    apuesta['stk_ou'] *= factor_penalizacion

    except Exception as e:
        print(f"[ADVERTENCIA] Fallo en el ajuste de covarianza: {e}. Revertiendo a stakes originales de contingencia.")
        for apuesta in lista_apuestas_potenciales:
            if apuesta['id_partido'] in stakes_originales:
                apuesta['stk_1x2'], apuesta['stk_ou'] = stakes_originales[apuesta['id_partido']]

def calcular_stake_independiente(pick, ev, cuota, BANKROLL, max_kelly_pct):
    if "[PASAR]" in pick or ev <= 0 or cuota <= 1: return 0.0
    prob_real = (1 / cuota) * (1 + ev)
    kelly = (prob_real * cuota - 1) / (cuota - 1)
    fraccion_kelly = max(0, min(kelly, max_kelly_pct))
    return round(BANKROLL * fraccion_kelly, 2)

def evaluar_mercado_1x2(p1, px, p2, c1, cx, c2, incertidumbre=0.0):
    if c1 <= 0 or cx <= 0 or c2 <= 0: return "[PASAR] Sin Cuotas", -100, 0

    # 🧠 REGLA DE ORO PREDICTIVA: Si el modelo duda, no operamos.
    probs_ordenadas = sorted([p1, px, p2])
    margen_predictivo = probs_ordenadas[2] - probs_ordenadas[1]  # Diferencia entre el 1ro y 2do más probables
    if margen_predictivo < 0.05:  # Requerimos al menos un 5% de 'aire' o convicción.
        return "[PASAR] Margen Predictivo Insuficiente (<5%)", -100, 0

    probs = {"LOCAL": p1, "EMPATE": px, "VISITA": p2}
    cuotas = {"LOCAL": c1, "EMPATE": cx, "VISITA": c2}
    max_prob_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[max_prob_key], cuotas[max_prob_key]
    ev_fav = (p_fav * c_fav) - 1
    # El umbral de EV ahora es más exigente si el partido es impredecible
    mod_incertidumbre = 1.0 + incertidumbre
    umb_fav = (0.015 * (0.5 / p_fav)) * mod_incertidumbre if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)

    if c_fav <= 5.5 and ev_fav >= umb_fav and div_fav <= 0.1:  # Aumentado de 0.2 a 0.4 para permitir mayor divergencia en el favorito del modelo
        return f"[APOSTAR] {max_prob_key}", ev_fav, c_fav

    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    max_ev_key = max(evs, key=evs.get)
    m_ev, p_ev, c_ev = evs[max_ev_key], probs[max_ev_key], cuotas[max_ev_key]
    umb_ev = (0.015 * (0.5 / p_ev)) * mod_incertidumbre if p_ev > 0 else 999
    div_ev = p_ev - (1 / c_ev)

    if c_ev <= 5.5 and m_ev >= umb_ev and div_ev <= 0.2:  # Aumentado de 0.3 a 0.4 para consistencia con el camino del favorito
        return f"[APOSTAR] {max_ev_key}", m_ev, c_ev

    if c_fav > 5.5: return "[PASAR] Techo Cuota", ev_fav, c_fav
    if ev_fav < umb_fav: return "[PASAR] Riesgo/Beneficio", ev_fav, c_fav
    if div_fav > 0.4: return "[PASAR] Info Oculta", ev_fav, c_fav  # Aumentado de 0.3 a 0.4
    return "[PASAR] Sin Valor", ev_fav, c_fav

def evaluar_mercado_ou(po, pu, co, cu, p1, px, p2, incertidumbre=0.0):
    if co <= 0 or cu <= 0: return "[PASAR] Sin Cuotas", -100, 0

    # 🧠 REGLA DE ORO PREDICTIVA (O/U): Si el modelo duda sobre el 1X2, no operamos en goles.
    probs_1x2_ordenadas = sorted([p1, px, p2])
    margen_predictivo_1x2 = probs_1x2_ordenadas[2] - probs_1x2_ordenadas[1]
    if margen_predictivo_1x2 < 0.15:
        return "[PASAR] Margen Predictivo 1X2 Insuficiente (<15%)", -100, 0 # CORREGIDO: De 0.5 a 0.05

    probs = {"OVER 2.5": po, "UNDER 2.5": pu}
    cuotas = {"OVER 2.5": co, "UNDER 2.5": cu}
    max_prob_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[max_prob_key], cuotas[max_prob_key]
    ev_fav = (p_fav * c_fav) - 1
    mod_incertidumbre = 1.0 + incertidumbre
    umb_fav = (0.025 * (0.5 / p_fav)) * mod_incertidumbre if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)

    if c_fav > 6.0: return "[PASAR] Techo Cuota", ev_fav, c_fav
    if ev_fav < umb_fav: return "[PASAR] Riesgo/Beneficio", ev_fav, c_fav
    if div_fav > 0.55: return "[PASAR] Info Oculta", ev_fav, c_fav
    return f"[APOSTAR] {max_prob_key}", ev_fav, c_fav

def poisson(k, lmbda):
    if lmbda <= 0: return 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)

def safe_float(val):
    try: return float(val)
    except: return 0.0

def main():
    print("[SISTEMA] Iniciando Cerebro Cuantitativo V12.7 (Ajuste de Covarianza Kelly)...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- FASE -1: GESTIÓN DE RIESGO DINÁMICA (STOP-LOSS) ---
    MAX_KELLY_PCT = MAX_KELLY_PCT_NORMAL
    if detectar_drawdown(cursor):
        MAX_KELLY_PCT = MAX_KELLY_PCT_DRAWDOWN
        print(f"[ALERTA] Drawdown detectado ({DRAWDOWN_THRESHOLD}+ pérdidas consecutivas). MAX_KELLY_PCT reducido a {MAX_KELLY_PCT_DRAWDOWN * 100}%.")
    else:
        print(f"[INFO] Nivel de riesgo operativo normal. MAX_KELLY_PCT establecido en {MAX_KELLY_PCT_NORMAL * 100}%.")

    # --- FASE 0: CARGA DE BANKROLL DINÁMICO ---
    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        bankroll_row = cursor.fetchone()
        BANKROLL = float(bankroll_row[0]) if bankroll_row else 100000.00
    except:
        BANKROLL = 100000.00 # Fallback en caso de error de DB
    
    print(f"[INFO] Bankroll operativo para esta sesion: ${BANKROLL:,.2f}")

    cursor.execute("""
        SELECT equipo_norm, ema_xg_favor_home, ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away,
               ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away
        FROM historial_equipos
    """)
    historial_ema = {row[0]: {'fav_home': row[1], 'con_home': row[2], 'fav_away': row[3], 'con_away': row[4], 
                              'var_fh': row[5], 'var_ch': row[6], 'var_fa': row[7], 'var_ca': row[8]} for row in cursor.fetchall()}

    cursor.execute("SELECT equipo_norm, altitud FROM equipos_altitud")
    altitudes = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT liga, rho_calculado FROM ligas_stats")
    rho_por_liga = {row[0]: row[1] for row in cursor.fetchall()}
    RHO_ESTATICO_FALLBACK = -0.03


    cursor.execute("""
        SELECT p.id_partido, p.local, p.visita, p.pais, p.cuota_1, p.cuota_x, p.cuota_2, 
               p.cuota_o25, p.cuota_u25, p.formacion_l, p.formacion_v, a.ema_faltas, p.fecha
        FROM partidos_backtest p
        LEFT JOIN arbitros_stats a ON p.id_arbitro = a.id_arbitro
    """)
    partidos = cursor.fetchall()
    
    if not partidos: return

    partidos_a_actualizar = []

    for p in partidos:
        id_partido, local, visita, pais, c1, cx, c2, co, cu, form_l, form_v, ema_faltas, fecha_str = p
        loc_norm, vis_norm = normalizar_extremo(local), normalizar_extremo(visita)

        ema_l = obtener_ema(loc_norm, historial_ema)
        ema_v = obtener_ema(vis_norm, historial_ema)
        
        # Cálculo del score de incertidumbre del partido
        incertidumbre_partido = math.sqrt((ema_l['var_fh'] + ema_v['var_ca'] + ema_v['var_fa'] + ema_l['var_ch']) / 4)

        xg_local = (ema_l['fav_home'] + ema_v['con_away']) / 2.0
        xg_visita = (ema_v['fav_away'] + ema_l['con_home']) / 2.0
        
        # =================================================================
        # FACTOR DE LOCALÍA ESTÁTICO (REQUERIMIENTO DE USUARIO)
        # Se aplica un multiplicador para acentuar la ventaja del equipo local.
        xg_local *= 1.05 # Bonus del 10% al xG del local (AJUSTE SIMÉTRICO)
        xg_visita *= 0.95 # Penalización del 10% al xG del visitante (AJUSTE SIMÉTRICO)
        # =================================================================

        mod_l, mod_v = colision_tactica(form_l, form_v)
        xg_local *= mod_l
        xg_visita *= mod_v

        # El factor momentum ahora considera si el partido es un clásico
        es_derby = frozenset({loc_norm, vis_norm}) in DERBIES
        factor_momento_l = obtener_factor_momentum(cursor, local, fecha_str, is_derby=es_derby)
        factor_momento_v = obtener_factor_momentum(cursor, visita, fecha_str, is_derby=es_derby)
        xg_local *= factor_momento_l
        xg_visita *= factor_momento_v

        descanso_l = obtener_dias_descanso(cursor, local, fecha_str)
        descanso_v = obtener_dias_descanso(cursor, visita, fecha_str)
        if descanso_l <= 3: xg_local *= 0.85 
        if descanso_v <= 3: xg_visita *= 0.85
        
        if ema_faltas:
            if ema_faltas >= 26.0: xg_local *= 0.93; xg_visita *= 0.93
            elif ema_faltas <= 21.0: xg_local *= 1.05; xg_visita *= 1.05

        altitud_local = altitudes.get(loc_norm, 0)
        if altitud_local > 1500:
            if altitud_local >= 3601: xg_visita *= 0.75; xg_local *= 1.35
            elif altitud_local >= 3001: xg_visita *= 0.80; xg_local *= 1.25
            elif altitud_local >= 2501: xg_visita *= 0.85; xg_local *= 1.15
            else: xg_visita *= 0.90; xg_local *= 1.10

        p1, px, p2, po, pu = 0.0, 0.0, 0.0, 0.0, 0.0
        rho = rho_por_liga.get(pais, RHO_ESTATICO_FALLBACK)
        
        for i in range(8):
            for j in range(8):
                pb = poisson(i, xg_local) * poisson(j, xg_visita)
                if i == 0 and j == 0: pb *= (1 - xg_local * xg_visita * rho)
                elif i == 0 and j == 1: pb *= (1 + xg_local * rho)
                elif i == 1 and j == 0: pb *= (1 + xg_visita * rho)
                elif i == 1 and j == 1: pb *= (1 - rho)
                pb = max(0.0, pb)
                
                if i > j: p1 += pb
                elif i == j: px += pb
                else: p2 += pb
                
                if (i + j) > 2.5: po += pb
                else: pu += pb

        suma_1x2 = p1 + px + p2
        if suma_1x2 > 0: p1, px, p2 = p1/suma_1x2, px/suma_1x2, p2/suma_1x2
        suma_ou = po + pu
        if suma_ou > 0: po, pu = po/suma_ou, pu/suma_ou

        c1_val, cx_val, c2_val = safe_float(c1), safe_float(cx), safe_float(c2)
        co_val, cu_val = safe_float(co), safe_float(cu)
        
        pick_1x2, ev_1x2, cu_1x2 = evaluar_mercado_1x2(p1, px, p2, c1_val, cx_val, c2_val, incertidumbre_partido)
        pick_ou, ev_ou, cu_ou = evaluar_mercado_ou(po, pu, co_val, cu_val, p1, px, p2, incertidumbre_partido)
        
        stk_1x2 = calcular_stake_independiente(pick_1x2, ev_1x2, cu_1x2, BANKROLL, MAX_KELLY_PCT)
        stk_ou = calcular_stake_independiente(pick_ou, ev_ou, cu_ou, BANKROLL, MAX_KELLY_PCT)

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
            'pick_1x2': pick_1x2, 'pick_ou': pick_ou,
            'stk_1x2': stk_1x2, 'stk_ou': stk_ou
        })

    # --- FASE DE AJUSTE DE RIESGO POR COVARIANZA ---
    apuestas_potenciales = [p for p in partidos_a_actualizar if p['stk_1x2'] > 0 or p['stk_ou'] > 0]
    
    if apuestas_potenciales:
        print(f"[INFO] {len(apuestas_potenciales)} apuestas potenciales identificadas. Aplicando ajuste de covarianza...")
        ajustar_stakes_por_covarianza(apuestas_potenciales)
    
    # --- FASE FINAL: ACTUALIZACIÓN EN BBDD ---
    calculados = 0
    for p_actualizado in partidos_a_actualizar:
        cursor.execute("""
            UPDATE partidos_backtest 
            SET prob_1=?, prob_x=?, prob_2=?, prob_o25=?, prob_u25=?, 
                apuesta_1x2=?, apuesta_ou=?, stake_1x2=?, stake_ou=?, 
                estado=CASE WHEN estado IN ('Liquidado', 'Finalizado') THEN estado ELSE 'Calculado' END 
            WHERE id_partido=?
        """, (p_actualizado['p1'], p_actualizado['px'], p_actualizado['p2'], p_actualizado['po'], p_actualizado['pu'], 
              p_actualizado['pick_1x2'], p_actualizado['pick_ou'], 
              round(p_actualizado['stk_1x2'], 2), round(p_actualizado['stk_ou'], 2),
              p_actualizado['id_partido']))
        calculados += 1

    conn.commit()
    conn.close()
    print(f"[EXITO] {calculados} partidos recalculados. Varianza predictiva al mando.")

if __name__ == "__main__":
    main()
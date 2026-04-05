import sqlite3
import math
import unicodedata
import difflib
import re
from datetime import datetime
from collections import defaultdict

# ==========================================
# MOTOR CALCULADORA V4.0 (DIXON-COLES + GESTION DE RIESGO CALIBRADA)
# Cambios respecto a V3.0:
#   - Umbral EV: 0.03 * (0.5 / prob) [Manifiesto II.E]
#   - Divergencia restaurada: max 0.2 para 1X2, 0.55 para O/U [Manifiesto II.E]
#   - Techo cuota 1X2: 5.0 [Manifiesto II.E]
#   - Medio Kelly: fraccion 0.50 [Thorp 2006]
#   - Poisson: range(10) -> 0 a 9 goles [Manifiesto II.C]
#   - Shadow mode: incertidumbre y altitud (calcula y almacena, no decide)
# ==========================================

DB_NAME = 'fondo_quant.db'

# --- Constantes de Riesgo ---
MAX_KELLY_PCT_NORMAL = 0.025
MAX_KELLY_PCT_DRAWDOWN = 0.010
DRAWDOWN_THRESHOLD = 5
FRACCION_KELLY = 0.50  # Medio Kelly (Thorp 2006, Ziemba 2005)

# --- Constantes de Decision ---
UMBRAL_EV_BASE = 0.03          # Manifiesto II.E (era 0.015 en V3.0)
TECHO_CUOTA_1X2 = 5.0          # Manifiesto II.E (era 5.5 en V3.0)
TECHO_CUOTA_OU = 6.0           # Manifiesto II.E
DIVERGENCIA_MAX_1X2 = 0.15      # Manifiesto II.E (no existia en V3.0)
DIVERGENCIA_MAX_OU = 0.05      # Manifiesto II.E
MARGEN_PREDICTIVO_1X2 = 0.05   # Manifiesto (minimo 5% de separacion)
MARGEN_PREDICTIVO_OU = 0.05    # Manifiesto (minimo 5% de separacion)

# --- Filtros Opcion 1 (estrategia activa desde V4.1) ---
# Backtest de 25 apuestas: floor 33% + EV escalado => 14 bets, 71% hit, +124% yield
# vs sistema sin filtros: 25 bets, 52% hit, +72% yield
FLOOR_PROB_MIN = 0.33          # Probabilidad minima para apostar cualquier outcome

def min_ev_escalado(prob):
    """EV minimo requerido segun nivel de confianza del modelo (Opcion 1)."""
    if prob >= 0.50: return 0.03   # alta confianza: umbral base
    if prob >= 0.40: return 0.08   # media: doble umbral
    if prob >= FLOOR_PROB_MIN: return 0.12  # baja-media: triple umbral
    return 999.0                   # < 33%: rechazar siempre

# --- Constantes de Modelo ---
RHO_FALLBACK = -0.03  # NOTA: Manifiesto dice -0.09. Pendiente calibracion con backtest.
RANGO_POISSON = 10    # 0 a 9 goles (era 8 en V3.0, Manifiesto dice 0-9)

# --- Altitud: Modificadores del Manifiesto II.G (solo para shadow) ---
ALTITUD_NIVELES = [
    (3601, 99999, 0.75, 1.35, "Zona de la Muerte"),
    (3001, 3600, 0.80, 1.25, "Extremo"),
    (2501, 3000, 0.85, 1.15, "Alto"),
    (1501, 2500, 0.90, 1.10, "Medio"),
]


# ==========================================================================
# FUNCIONES DE RIESGO Y DRAWDOWN
# ==========================================================================

def determinar_resultado_apuesta(apuesta, gl, gv):
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"
    if "LOCAL" in apuesta: return "GANADA" if gl > gv else "PERDIDA"
    if "EMPATE" in apuesta: return "GANADA" if gl == gv else "PERDIDA"
    if "VISITA" in apuesta: return "GANADA" if gl < gv else "PERDIDA"
    if "OVER 2.5" in apuesta: return "GANADA" if (gl + gv) > 2.5 else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl + gv) < 2.5 else "PERDIDA"
    return "INDETERMINADO"

def detectar_drawdown(cursor, umbral=DRAWDOWN_THRESHOLD):
    cursor.execute("""
        SELECT apuesta_1x2, apuesta_ou, goles_l, goles_v FROM partidos_backtest
        WHERE estado = 'Liquidado' AND (stake_1x2 > 0 OR stake_ou > 0)
        ORDER BY fecha DESC LIMIT 20
    """)
    perdidas = 0
    for ap_1x2, ap_ou, gl, gv in cursor.fetchall():
        apuesta = ap_1x2 if "[APOSTAR]" in str(ap_1x2) else ap_ou
        resultado = determinar_resultado_apuesta(apuesta, gl, gv)
        if resultado == "PERDIDA":
            perdidas += 1
        elif resultado == "GANADA":
            return False
        if perdidas >= umbral:
            return True
    return perdidas >= umbral


# ==========================================================================
# FUNCIONES DE UTILIDAD
# ==========================================================================

def normalizar_extremo(texto):
    # Identica a gestor_nombres.limpiar_texto: elimina todo lo que no sea letra o numero.
    # Esto garantiza que la clave de busqueda en historial_equipos coincida exactamente
    # con la clave generada por motor_data al guardar (ej: "belgrano(cordoba)" -> "belgranocordoba").
    if not texto: return ""
    sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', sin_tildes)

def safe_float(val):
    try: return float(val)
    except (ValueError, TypeError): return 0.0

def obtener_ema(equipo_norm, historial_ema):
    default = {'fav_home': 1.4, 'con_home': 1.4, 'fav_away': 1.4, 'con_away': 1.4,
               'var_fh': 0.1, 'var_ch': 0.1, 'var_fa': 0.1, 'var_ca': 0.1}
    data = historial_ema.get(equipo_norm)
    if not data:
        matches = difflib.get_close_matches(equipo_norm, historial_ema.keys(), n=1, cutoff=0.7)
        data = historial_ema.get(matches[0]) if matches else None
    if not data:
        return default
    return {k: (data.get(k) or default[k]) for k in default}

def poisson(k, lmbda):
    if lmbda <= 0: return 0.0
    try: return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)
    except (ValueError, OverflowError): return 0.0


# ==========================================================================
# SHADOW MODE: ALTITUD (Calcula xG modificado, no lo usa en decision)
# ==========================================================================

def calcular_shadow_altitud(xg_local, xg_visita, loc_norm, altitudes):
    altitud = altitudes.get(loc_norm, 0)
    if altitud <= 1500:
        return xg_local, xg_visita, 0, ""
    for alt_min, alt_max, mod_vis, mod_loc, nivel in ALTITUD_NIVELES:
        if alt_min <= altitud <= alt_max:
            return (xg_local * mod_loc, xg_visita * mod_vis, altitud, nivel)
    return xg_local, xg_visita, altitud, ""


# ==========================================================================
# CAPA DE DECISION (Evaluadores de Mercado)
# ==========================================================================

def evaluar_mercado_1x2(p1, px, p2, c1, cx, c2):
    """
    Evalua mercado 1X2 con dos caminos (Manifiesto II.E):
    1. Favorito del modelo: umbral estandar, divergencia <= 0.2
    2. Value Hunting: busca maximo EV si favorito no cumple, misma divergencia
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return "[PASAR] Sin Cuotas", -100, 0

    probs_ord = sorted([p1, px, p2])
    if (probs_ord[2] - probs_ord[1]) < MARGEN_PREDICTIVO_1X2:
        return "[PASAR] Margen Predictivo Insuficiente (<5%)", -100, 0

    probs = {"LOCAL": p1, "EMPATE": px, "VISITA": p2}
    cuotas = {"LOCAL": c1, "EMPATE": cx, "VISITA": c2}

    # --- CAMINO 1: Evaluar al favorito del modelo ---
    fav_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[fav_key], cuotas[fav_key]
    ev_fav = (p_fav * c_fav) - 1
    umb_fav = (UMBRAL_EV_BASE * (0.5 / p_fav)) if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)  # Positiva = modelo ve mas prob que el mercado

    if c_fav <= TECHO_CUOTA_1X2 and ev_fav >= umb_fav and div_fav <= DIVERGENCIA_MAX_1X2:
        return f"[APOSTAR] {fav_key}", ev_fav, c_fav

    # --- CAMINO 2: Value Hunting (underdog con maximo EV) ---
    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    ev_key = max(evs, key=evs.get)
    p_ev, c_ev, m_ev = probs[ev_key], cuotas[ev_key], evs[ev_key]
    umb_ev = (UMBRAL_EV_BASE * (0.5 / p_ev)) if p_ev > 0 else 999
    div_ev = p_ev - (1 / c_ev)

    if c_ev <= TECHO_CUOTA_1X2 and m_ev >= umb_ev and div_ev <= DIVERGENCIA_MAX_1X2:
        return f"[APOSTAR] {ev_key}", m_ev, c_ev

    # --- DIAGNOSTICO ---
    if c_fav > TECHO_CUOTA_1X2: return "[PASAR] Techo Cuota", ev_fav, c_fav
    if ev_fav < umb_fav: return "[PASAR] Riesgo/Beneficio", ev_fav, c_fav
    if div_fav > DIVERGENCIA_MAX_1X2: return "[PASAR] Info Oculta", ev_fav, c_fav
    return "[PASAR] Sin Valor", ev_fav, c_fav

def evaluar_mercado_ou(po, pu, co, cu, p1, px, p2):
    """
    Evalua mercado O/U 2.5 (Manifiesto II.E - Francotirador):
    SOLO evalua la opcion matematicamente favorita. Prohibido cazar valor.
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [co, cu]):
        return "[PASAR] Sin Cuotas", -100, 0

    if abs(po - pu) < MARGEN_PREDICTIVO_OU:
        return "[PASAR] Margen Predictivo O/U Insuficiente (<15%)", -100, 0

    probs = {"OVER 2.5": po, "UNDER 2.5": pu}
    cuotas = {"OVER 2.5": co, "UNDER 2.5": cu}

    pick = max(probs, key=probs.get)
    p_fav, c_fav = probs[pick], cuotas[pick]

    if c_fav <= 1.0:
        return "[PASAR] Cuota Invalida", -100, 0

    ev = (p_fav * c_fav) - 1
    umbral = (UMBRAL_EV_BASE * (0.5 / p_fav)) if p_fav > 0 else 999
    div = p_fav - (1 / c_fav)

    if ev > umbral and c_fav <= TECHO_CUOTA_OU and div <= DIVERGENCIA_MAX_OU:
        return f"[APOSTAR] {pick}", ev, c_fav

    return "[PASAR] Sin Valor", ev, c_fav


# ==========================================================================
# SIZING (Kelly Fraccional)
# ==========================================================================

def mejor_outcome_fallback(p1, px, p2, c1, cx, c2):
    """
    Opcion 4 (shadow): si el outcome elegido tiene prob < FLOOR_PROB_MIN,
    buscar el mejor outcome alternativo con prob >= FLOOR_PROB_MIN, ordenado por EV.
    Retorna (nombre, prob, cuota, ev) o None si no hay ninguno valido.
    """
    candidatos = [('LOCAL', p1, c1), ('EMPATE', px, cx), ('VISITA', p2, c2)]
    validos = []
    for nombre, prob, cuota in candidatos:
        if prob >= FLOOR_PROB_MIN and cuota and cuota > 1:
            ev_val = (prob * cuota) - 1
            if ev_val > 0:
                validos.append((nombre, prob, cuota, ev_val))
    if not validos:
        return None
    return max(validos, key=lambda x: x[3])  # mayor EV

def calcular_stake_independiente(pick, ev, cuota, bankroll, max_kelly_pct):
    """
    Medio Kelly: k_fraccion = kelly_full * 0.50, capado a max_kelly_pct.
    Justificacion: el modelo estima probabilidades con incertidumbre inherente,
    lo que sobreestima el Kelly optimo. Medio Kelly reduce varianza ~50%
    sacrificando ~25% de crecimiento geometrico (Kelly 1956, Thorp 2006).
    """
    if "[APOSTAR]" not in pick or ev <= 0 or cuota <= 1:
        return 0.0
    try:
        prob_real = (1 / cuota) * (1 + ev)
        kelly_full = (prob_real * cuota - 1) / (cuota - 1)
        fraccion = min(kelly_full * FRACCION_KELLY, max_kelly_pct)
        return round(bankroll * max(0, fraccion), 2)
    except (ZeroDivisionError, TypeError):
        return 0.0

def ajustar_stakes_por_covarianza(lista_apuestas):
    """Penaliza stakes correlacionados por (pais, dia). Factor: 1/sqrt(N)."""
    agrupadas = defaultdict(list)
    for ap in lista_apuestas:
        clave = (ap.get('pais', '?'), str(ap.get('fecha', '')).split(" ")[0])
        agrupadas[clave].append(ap)
    for _, grupo in agrupadas.items():
        n = len(grupo)
        if n > 1:
            factor = 1 / (n ** 0.5)
            for ap in grupo:
                ap['stk_1x2'] *= factor
                ap['stk_ou'] *= factor


# ==========================================================================
# FUNCION PRINCIPAL
# ==========================================================================

def main():
    print("[SISTEMA] Iniciando Motor Calculadora V4.0 (Dixon-Coles + Riesgo Calibrado)...")
    print(f"[CONFIG] Umbral EV: {UMBRAL_EV_BASE} | Techo 1X2: {TECHO_CUOTA_1X2} | Kelly: {FRACCION_KELLY} | Poisson: 0-{RANGO_POISSON-1}")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- Columnas shadow (crear si no existen) ---
    for col in ['incertidumbre REAL', 'shadow_xg_local REAL', 'shadow_xg_visita REAL',
                'apuesta_shadow_1x2 TEXT', 'stake_shadow_1x2 REAL']:
        try: cursor.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col}")
        except sqlite3.OperationalError: pass

    # --- FASE 0: GESTION DE RIESGO GLOBAL ---
    MAX_KELLY_PCT = MAX_KELLY_PCT_NORMAL
    if detectar_drawdown(cursor):
        MAX_KELLY_PCT = MAX_KELLY_PCT_DRAWDOWN
        print(f"[ALERTA] Drawdown detectado. MAX_KELLY_PCT reducido a {MAX_KELLY_PCT_DRAWDOWN * 100}%.")
    else:
        print(f"[INFO] Riesgo normal. MAX_KELLY_PCT en {MAX_KELLY_PCT_NORMAL * 100}%.")

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        BANKROLL = float(cursor.fetchone()[0])
    except (TypeError, IndexError):
        BANKROLL = 100000.00
    print(f"[INFO] Bankroll operativo: ${BANKROLL:,.2f}")

    # --- FASE 1: CARGA DE DATOS ---
    cursor.execute("""
        SELECT equipo_norm, ema_xg_favor_home, ema_xg_contra_home, ema_xg_favor_away, ema_xg_contra_away,
               ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away
        FROM historial_equipos
    """)
    historial_ema = {r[0]: {'fav_home': r[1], 'con_home': r[2], 'fav_away': r[3], 'con_away': r[4],
                            'var_fh': r[5], 'var_ch': r[6], 'var_fa': r[7], 'var_ca': r[8]} for r in cursor.fetchall()}

    cursor.execute("SELECT liga, rho_calculado FROM ligas_stats")
    rho_por_liga = {r[0]: r[1] for r in cursor.fetchall()}

    # Altitudes para shadow mode
    cursor.execute("SELECT equipo_norm, altitud FROM equipos_altitud")
    altitudes = {r[0]: r[1] for r in cursor.fetchall()}

    cursor.execute("""
        SELECT p.id_partido, p.local, p.visita, p.pais, p.fecha,
               p.cuota_1, p.cuota_x, p.cuota_2, p.cuota_o25, p.cuota_u25
        FROM partidos_backtest p
        WHERE p.estado = 'Pendiente' OR p.estado = 'Calculado'
    """)
    partidos = cursor.fetchall()

    if not partidos:
        print("[INFO] No hay partidos nuevos para calcular.")
        conn.close()
        return

    partidos_a_actualizar = []
    shadow_log_alt = 0
    shadow_log_incert = 0

    # --- FASE 2: CALCULO Y DECISION POR PARTIDO ---
    for partido in partidos:
        id_partido, local, visita, pais, fecha_str, c1, cx, c2, co, cu = partido
        loc_norm = normalizar_extremo(local)
        vis_norm = normalizar_extremo(visita)

        ema_l = obtener_ema(loc_norm, historial_ema)
        ema_v = obtener_ema(vis_norm, historial_ema)

        # xG base (Poisson puro, sin factores contextuales)
        xg_local = (ema_l['fav_home'] + ema_v['con_away']) / 2.0
        xg_visita = (ema_v['fav_away'] + ema_l['con_home']) / 2.0

        # --- SHADOW: Incertidumbre ---
        incertidumbre = math.sqrt(
            (ema_l['var_fh'] + ema_v['var_ca'] + ema_v['var_fa'] + ema_l['var_ch']) / 4
        )

        # --- SHADOW: Altitud ---
        sh_xg_l, sh_xg_v, alt_msnm, alt_nivel = calcular_shadow_altitud(
            xg_local, xg_visita, loc_norm, altitudes
        )
        if alt_msnm > 1500:
            shadow_log_alt += 1
            print(f"   [SHADOW-ALT] {local} ({alt_msnm}m, {alt_nivel}) vs {visita} | "
                  f"xG_L: {xg_local:.2f}->{sh_xg_l:.2f} | xG_V: {xg_visita:.2f}->{sh_xg_v:.2f}")

        # --- Poisson Bivariado (Dixon-Coles) ---
        p1, px, p2, po, pu = 0.0, 0.0, 0.0, 0.0, 0.0
        rho = rho_por_liga.get(pais, RHO_FALLBACK)

        for i in range(RANGO_POISSON):
            for j in range(RANGO_POISSON):
                pb = poisson(i, xg_local) * poisson(j, xg_visita)
                # Ajuste Dixon-Coles (correlacion en marcadores bajos)
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

        # Normalizacion
        s1 = p1 + px + p2
        if s1 > 0: p1, px, p2 = p1/s1, px/s1, p2/s1
        so = po + pu
        if so > 0: po, pu = po/so, pu/so

        # --- SHADOW: Log de incertidumbre ---
        prob_max = max(p1, px, p2)
        umb_activo = (UMBRAL_EV_BASE * (0.5 / prob_max)) if prob_max > 0 else 999
        umb_con_incert = umb_activo * (1 + incertidumbre)
        if incertidumbre > 0.15:
            shadow_log_incert += 1
            print(f"   [SHADOW-INC] {local} vs {visita} | Incert: {incertidumbre:.3f} | "
                  f"Umbral activo: {umb_activo:.4f} | Umbral+incert: {umb_con_incert:.4f}")

        # --- CAPA DE DECISION ---
        c1_v, cx_v, c2_v = safe_float(c1), safe_float(cx), safe_float(c2)
        co_v, cu_v = safe_float(co), safe_float(cu)

        # Evaluacion raw (sin filtros adicionales)
        pick_1x2_raw, ev_1x2, cu_1x2 = evaluar_mercado_1x2(p1, px, p2, c1_v, cx_v, c2_v)

        # Extraer prob del outcome elegido en raw
        prob_raw_1x2 = 0.0
        if "[APOSTAR]" in pick_1x2_raw:
            if   "LOCAL"  in pick_1x2_raw: prob_raw_1x2 = p1
            elif "EMPATE" in pick_1x2_raw: prob_raw_1x2 = px
            else:                          prob_raw_1x2 = p2

        # --- OPCION 1 (ACTIVA): floor 33% + EV escalado ---
        pick_1x2 = pick_1x2_raw
        if "[APOSTAR]" in pick_1x2_raw:
            if prob_raw_1x2 < FLOOR_PROB_MIN:
                pick_1x2 = f"[PASAR] Floor Prob ({prob_raw_1x2:.0%}<{FLOOR_PROB_MIN:.0%})"
            elif ev_1x2 < min_ev_escalado(prob_raw_1x2):
                pick_1x2 = f"[PASAR] EV Insuf ({ev_1x2:.3f}<{min_ev_escalado(prob_raw_1x2):.3f})"

        # --- OPCION 4 (SHADOW): floor 33%, EV libre para originales, fallback si prob baja ---
        pick_shadow_1x2 = pick_1x2_raw  # hereda el raw (EV libre)
        if "[APOSTAR]" in pick_1x2_raw and prob_raw_1x2 < FLOOR_PROB_MIN:
            # prob demasiado baja: intentar fallback al mejor outcome con prob >= 33%
            fb = mejor_outcome_fallback(p1, px, p2, c1_v, cx_v, c2_v)
            if fb:
                nombre_fb, prob_fb, cuota_fb, ev_fb = fb
                pick_shadow_1x2 = f"[APOSTAR] {nombre_fb}"
                cu_1x2_shadow   = cuota_fb
                ev_1x2_shadow   = ev_fb
            else:
                pick_shadow_1x2 = "[PASAR] Sin Fallback Opcion4"
                cu_1x2_shadow   = 0.0
                ev_1x2_shadow   = 0.0
        else:
            cu_1x2_shadow = cu_1x2
            ev_1x2_shadow = ev_1x2

        pick_ou, ev_ou, cu_ou = evaluar_mercado_ou(po, pu, co_v, cu_v, p1, px, p2)

        stk_1x2 = calcular_stake_independiente(pick_1x2, ev_1x2, cu_1x2, BANKROLL, MAX_KELLY_PCT)
        stk_ou  = calcular_stake_independiente(pick_ou,  ev_ou,  cu_ou,  BANKROLL, MAX_KELLY_PCT)
        stk_shadow_1x2 = calcular_stake_independiente(
            pick_shadow_1x2, ev_1x2_shadow, cu_1x2_shadow, BANKROLL, MAX_KELLY_PCT)

        # Overlap: si hay apuesta en ambos mercados, priorizar la de mayor EV
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
            'pick_ou': pick_ou, 'ev_ou': ev_ou, 'cu_ou': cu_ou, 'stk_ou': stk_ou,
            'pick_shadow_1x2': pick_shadow_1x2, 'stk_shadow_1x2': stk_shadow_1x2,
            'incertidumbre': round(incertidumbre, 4),
            'shadow_xg_l': round(sh_xg_l, 3), 'shadow_xg_v': round(sh_xg_v, 3)
        })

    # --- FASE 3: AJUSTE DE COVARIANZA ---
    apuestas_vivas = [p for p in partidos_a_actualizar if p['stk_1x2'] > 0 or p['stk_ou'] > 0]
    if apuestas_vivas:
        print(f"[INFO] {len(apuestas_vivas)} apuestas potenciales. Aplicando covarianza...")
        ajustar_stakes_por_covarianza(apuestas_vivas)

    # --- FASE 4: ACTUALIZACION EN DB ---
    calculados = 0
    for p in partidos_a_actualizar:
        cursor.execute("""
            UPDATE partidos_backtest
            SET prob_1=?, prob_x=?, prob_2=?, prob_o25=?, prob_u25=?,
                apuesta_1x2=?, apuesta_ou=?, stake_1x2=?, stake_ou=?,
                apuesta_shadow_1x2=?, stake_shadow_1x2=?,
                incertidumbre=?, shadow_xg_local=?, shadow_xg_visita=?,
                estado='Calculado'
            WHERE id_partido=?
        """, (
            p['p1'], p['px'], p['p2'], p['po'], p['pu'],
            p['pick_1x2'], p['pick_ou'],
            round(p['stk_1x2'], 2), round(p['stk_ou'], 2),
            p['pick_shadow_1x2'], round(p['stk_shadow_1x2'], 2),
            p['incertidumbre'], p['shadow_xg_l'], p['shadow_xg_v'],
            p['id_partido']
        ))
        calculados += 1

    conn.commit()
    conn.close()

    # Estadisticas de filtrado Opcion 1 vs Opcion 4
    n_op1  = sum(1 for p in partidos_a_actualizar if "[APOSTAR]" in p['pick_1x2'])
    n_op4  = sum(1 for p in partidos_a_actualizar if "[APOSTAR]" in p['pick_shadow_1x2'])
    n_diff = sum(1 for p in partidos_a_actualizar
                 if "[APOSTAR]" in p['pick_shadow_1x2'] and "[APOSTAR]" not in p['pick_1x2'])
    print(f"\n[EXITO] {calculados} partidos calculados.")
    print(f"[OP1-ACTIVA]  Apuestas generadas: {n_op1} (floor {FLOOR_PROB_MIN:.0%} + EV escalado)")
    print(f"[OP4-SHADOW]  Apuestas shadow:    {n_op4} ({n_diff} adicionales vs Op1, guardadas para auditoria)")
    print(f"[SHADOW] Altitud activa: {shadow_log_alt} | Incertidumbre alta (>0.15): {shadow_log_incert}")
    print("[SISTEMA] Motor Calculadora V4.1 ha finalizado su ejecucion.")

if __name__ == "__main__":
    main()

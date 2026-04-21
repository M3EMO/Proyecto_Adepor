import sqlite3
import math
import unicodedata
import difflib
import re
from datetime import datetime
from collections import defaultdict
from src.comun.config_sistema import DB_NAME
from src.comun.config_motor import get_param
from src.comun.tipos import safe_float
from src.comun.resolucion import determinar_resultado_string as determinar_resultado_apuesta

# ==========================================
# MOTOR CALCULADORA V4.8 (DIXON-COLES + GESTION DE RIESGO CALIBRADA)
# Cambios respecto a V4.7:
#   - Hallazgo G: prior dinámico de ventaja local por liga.
#     Se activa SOLO cuando N_liquidados_por_liga >= N_MIN_HALLAZGO_G (50).
#     Aplica un boost conservador (50% de la diferencia observada) a p1 (LOCAL).
#     Mientras N < 50: completamente inactivo, sin efecto en las decisiones.
#   - Shadow redefinido: Opcion 1 SIN Fix #5 (calibración) NI Hallazgo C (delta stake).
#     Sirve como grupo de control para validar que esos dos fixes agregan valor real
#     a largo plazo. Si Op1 > Shadow acumulado -> los fixes están funcionando.
# Cambios respecto a V4.6:
#   - Hallazgo C: multiplicador de stake por dominancia xG.
#     delta >= 0.50: x1.30 (100% hit en backtest, n=5).
#     delta [0.30-0.50): x1.15 (0% sorpresas en backtest, n=8).
#     NO abre apuestas nuevas; solo escala stakes de apuestas ya aprobadas.
#     Cap MAX_KELLY_PCT se aplica después — límite absoluto de riesgo intacto.
# Cambios respecto a V4.5:
#   - Fix B: Margen xG O/U asimetrico. OVER requiere xG>2.80 (era 2.75).
#     Backtest: xG [2.5-2.8) -> goles_prom=0.60, UNDER=100%. Zona bloqueada para OVER.
#   - Fix A REVERTIDO: corregir_ventaja_local() fue implementado pero revertido.
#     Razon: bajar xG_visita en calculadora cambia p1/p2 y flipa picks VISITA->LOCAL
#     correctos (yield -35.9pp en backtest de 32 partidos). El sesgo de xG_visita
#     debe corregirse en motor_data.py (EMA), no en la capa de prediccion.
# Cambios respecto a V4.4:
#   - Fix #5: Corrección de sesgo de compresión de calibración.
#     Bucket 40-50%: frecuencia real = 53.4% vs modelo = 45% promedio => +8.4pp sesgo.
#     Corrección conservadora: +0.042 (50% del sesgo; el otro 50% es margen N=92).
#     Solo se corrige LOCAL/VISITA en ese bucket. Se renormaliza p1+px+p2=1.
# Cambios respecto a V4.3:
#   - Regimen Desacuerdo Modelo-Mercado (Camino 2B):
#     Cuando modelo y mercado difieren sobre el favorito, prob >= 40%,
#     div entre 0.15 y 0.30: hit rate 80-100% en backtest de 92 partidos.
#     Umbral critico: prob < 40% en desacuerdo da hit=33% (ruido, excluido).
# Cambios respecto a V4.1:
#   - Regimen Alta Conviccion (Camino 3): cuando modelo favorito y mercado errado
#     Condicion: EV >= 1.0 + prob >= FLOOR_PROB + cuota <= TECHO_ALTA_CONV (8.0)
#     Razon: div alta + EV extremo = mercado equivocado, no info oculta
# Cambios respecto a V4.0:
#   - Floor 33% + EV escalado (Opcion 1 activa) [backtest 25 apuestas]
#   - Shadow mode Opcion 4: floor 33% sin EV escalado + fallback
# Cambios respecto a V3.0:
#   - Umbral EV: 0.03 * (0.5 / prob) [Manifiesto II.E]
#   - Divergencia restaurada: max 0.15 para 1X2 [Manifiesto II.E]
#   - Techo cuota 1X2: 5.0 [Manifiesto II.E]
#   - Medio Kelly: fraccion 0.50 [Thorp 2006]
# ==========================================

# DB_NAME importado desde config_sistema

# --- Constantes de Riesgo ---
MAX_KELLY_PCT_NORMAL = get_param('max_kelly_pct_normal', default=0.025)
MAX_KELLY_PCT_DRAWDOWN = get_param('max_kelly_pct_drawdown', default=0.010)
DRAWDOWN_THRESHOLD = get_param('drawdown_threshold', default=5)
FRACCION_KELLY = get_param('fraccion_kelly', default=0.50)  # Medio Kelly (Thorp 2006, Ziemba 2005)

# --- Constantes de Decision ---
UMBRAL_EV_BASE = get_param('umbral_ev_base', default=0.03)          # Manifiesto II.E (era 0.015 en V3.0)
TECHO_CUOTA_1X2 = get_param('techo_cuota_1x2', default=5.0)          # Manifiesto II.E (era 5.5 en V3.0)
TECHO_CUOTA_OU = get_param('techo_cuota_ou', default=6.0)           # Manifiesto II.E
DIVERGENCIA_MAX_1X2 = get_param('divergencia_max_1x2', default=0.15)      # Manifiesto II.E — fallback global
# DIVERGENCIA_MAX_OU eliminada (V4.9): el filtro div<=0.05 bloqueaba el 100% de las apuestas OU.
# El modelo Poisson/xG diverge estructuralmente del mercado en 0.27-0.61 — eso es esperado,
# no una señal de error. El guard correcto es EV > umbral + Fix B (xG margen asimetrico).

# Factor de calibración xG para O/U (V4.9) — OLS histórico: goles = factor × xG_ema
# El xG sobreestima goles en diferente magnitud por liga. Para O/U el valor absoluto
# importa (umbral fijo en 2.5), así que se calibra lambda POR LIGA.
# 1X2 no se toca: el ratio local/visita sigue siendo correcto con xG inflado.
# Derivado de: AVG(goles_real / xG_ema) por liga sobre liquidados históricos.
# Backtest factor por liga: n=7, 100% hit, +126.1% yield (vs global 0.627: n=5, +140.6%)
FACTOR_CORR_XG_OU_POR_LIGA = {
    "Noruega":    0.524,   # Liga más sobreestimada — reducir más agresivamente
    "Brasil":     0.603,   # Sobreestimación moderada-alta
    "Argentina":  0.642,   # Sobreestimación moderada (pero Fix B bloquea la mayoría)
    "Turquia":    0.648,   # Sobreestimación moderada
    "Inglaterra": 0.627,   # Sin muestra suficiente — usar promedio global
    # Ligas sudamericanas 2026-04-11: sin backtest propio -> fallback global 0.627
    "Bolivia":   0.627,   # Sin datos propios; fallback global
    "Chile":     0.627,   # Sin datos propios; fallback global
    "Uruguay":   0.627,   # Sin datos propios; fallback global
    "Peru":      0.627,   # Sin datos propios; fallback global
    "Ecuador":   0.627,   # Sin datos propios; fallback global
    "Colombia":  0.627,   # Sin datos propios; fallback global
    "Venezuela": 0.627,   # Sin datos propios; fallback global
    # Piloto europeo 2026-04-21:
    #   Espana (LaLiga) -> liga mas defensiva que EPL/Bundesliga (muchos 1-0/2-1,
    #   goles totales tipicamente ~2.5 vs Bundesliga ~3.0). xG tiende a sobreestimar
    #   un poco mas en ligas defensivas. Sin backtest propio -> fallback global 0.627;
    #   se recalibrara cuando N_liquidados_Espana >= 30.
    "Espana":    0.627,   # Sin datos propios; fallback global (recalibrar con N>=30)
}
FACTOR_CORR_XG_OU = get_param('factor_corr_xg_ou', default=0.627)  # Fallback global para ligas nuevas

# Fix #4 (V4.4): Divergencia 1X2 diferenciada por eficiencia de mercado por liga.
# Razonamiento:
#   - Mercado eficiente (Inglaterra): cuotas muy calibradas; divergencia > 10% casi siempre
#     indica que el modelo está equivocado, no el mercado. Tolerancia baja.
#   - Mercado poco eficiente (Noruega, Turquía): bookmakers tienen menos información;
#     nuestro modelo puede explotar desviaciones mayores. Tolerancia alta.
# Valores derivados de eficiencia de mercado relativa en fútbol europeo/sudamericano:
DIVERGENCIA_MAX_POR_LIGA = {
    "Inglaterra": 0.10,   # Premier League: el mercado más eficiente del mundo
    "Argentina":  0.15,   # Cobertura alta, mercado calibrado (BASE)
    "Brasil":     0.18,   # Menos cobertura que PL, algo de ineficiencia explotable
    "Noruega":    0.20,   # Liga pequeña, bookmakers con menos datos
    "Turquia":    0.20,   # Alta volatilidad + menor eficiencia de mercado
    # Ligas sudamericanas 2026-04-11: mercados poco eficientes -> tolerancia alta
    # Solo Chile tiene cobertura en Odds-API; el resto operara sin cuotas de referencia
    # hasta que se incorporen fuentes adicionales. Divergencia conservadora 0.18 (=Brasil)
    # como punto de partida; se ajustara con backtest propio.
    "Bolivia":   0.20,   # Mercado muy ineficiente, baja cobertura bookmakers
    "Chile":     0.18,   # Unica con Odds-API; mercado sudamericano mediano (=Brasil)
    "Uruguay":   0.18,   # Mercado mediano; ajustar con datos propios
    "Peru":      0.20,   # Mercado poco eficiente, baja cobertura bookmakers
    "Ecuador":   0.20,   # Mercado poco eficiente, baja cobertura bookmakers
    "Colombia":  0.18,   # Mercado algo mas liquido que Bolivia/Venezuela (=Brasil)
    "Venezuela": 0.20,   # Mercado muy ineficiente; alta volatilidad
    # Piloto europeo 2026-04-21:
    #   Espana (LaLiga) -> mercado top-tier europeo, eficiencia altisima,
    #   cobertura Pinnacle/Bet365 plena. Perfil equivalente a Premier League.
    #   Divergencia > 10% vs mercado casi siempre indica que el modelo esta
    #   equivocado, no una oportunidad real.
    "Espana":    0.10,   # Perfil Premier League: mercado muy eficiente, tolerancia baja
}
MARGEN_PREDICTIVO_1X2 = get_param('margen_predictivo_1x2', default=0.03)   # V4.3: bajado de 0.05 a 0.03 — backtest 8 nuevas bets, 62.5% hit (F9 scope=liga via get_param en evaluar_mercado_1x2)
MARGEN_PREDICTIVO_OU = get_param('margen_predictivo_ou', default=0.05)    # Manifiesto (minimo 5% de separacion)

# --- Filtros Opcion 1 (estrategia activa desde V4.1) ---
# Backtest de 25 apuestas: floor 33% + EV escalado => 14 bets, 71% hit, +124% yield
# vs sistema sin filtros: 25 bets, 52% hit, +72% yield
FLOOR_PROB_MIN = get_param('floor_prob_min', default=0.33)          # Probabilidad minima para apostar cualquier outcome

# --- Regimen Alta Conviccion (V4.2) ---
# Cuando el modelo ve al equipo como favorito (prob >= FLOOR) pero el mercado
# lo pone como gran underdog (cuota > TECHO normal), la divergencia sube mucho.
# Con EV >= 1.0, no es "info oculta" — es desacuerdo genuino modelo vs mercado.
# Techo relajado a 8.0 para evitar cuotas absurdas pero capturar los casos reales.
CONVICCION_EV_MIN = get_param('conviccion_ev_min', default=1.0)        # EV > 100%: retorno esperado enorme
TECHO_CUOTA_ALTA_CONV = get_param('techo_cuota_alta_conv', default=8.0)   # Techo relajado para este regimen

# --- Regimen Desacuerdo Modelo-Mercado (V4.3) ---
# Backtest 92 partidos: cuando modelo y mercado discrepan sobre el favorito
# y prob_modelo >= 40%:
#   div 15-25% -> hit 80%  (5 casos)
#   div 25-35% -> hit 100% (6 casos, mayoria cubiertos por Alta Conviccion)
# Con prob 33-40% el desacuerdo NO ayuda (hit 33%, ruido). Umbral duro en 40%.
# Zona operativa: div entre DIVERGENCIA_MAX_1X2 (0.15) y DIVERGENCIA_DESACUERDO_MAX (0.30)
# Los casos con div > 0.30 y EV >= 1.0 ya los cubre Alta Conviccion.
DESACUERDO_PROB_MIN = get_param('desacuerdo_prob_min', default=0.40)     # Umbral critico: por debajo el desacuerdo es ruido
DIVERGENCIA_DESACUERDO_MAX = get_param('divergencia_desacuerdo_max', default=0.30)  # Techo de divergencia para este regimen

# --- Regimen Consenso con el Mercado — CAMINO 4 (V4.7 fase3 / 2026-04-20) ---
# Hallazgo fase3: bucket PASAR "Riesgo/Beneficio" (n=27) tenia 88.9% hit y +36.6%
# yield. Clave: fav_modelo == fav_mercado pero cuota baja => EV negativo => rechazo.
# Cuando modelo y mercado acuerdan, el filtro EV sobra.
#
# Actualizacion fase 3.3.4 (2026-04-21): tras train/test split 60/40 cronologico
# sobre 223 partidos liquidados, threshold test -20%/+20% sobre cada filtro:
#   C4 prob 0.45 -> 0.36 fue GANADOR NETO: +3 picks, hit +3.2pp, yield +5.1pp en TEST.
# Interpretacion: cuando mercado y modelo coinciden en favorito con prob 36-44%
# y cuota 1.80-2.50, el edge es solido. Floor 0.45 dejaba ~60 picks/año en la mesa.
CONSENSO_PROB_MIN = get_param('consenso_prob_min', default=0.36)         # Prob modelo minima (fase 3.3.4: 0.45->0.36)
CONSENSO_CUOTA_MIN = get_param('consenso_cuota_min', default=1.12)       # Cuota minima (fase 3.3.5: 1.40->1.12 COMBO +5 picks)
CONSENSO_CUOTA_MAX = get_param('consenso_cuota_max', default=2.00)       # Cuota maxima: mas arriba C1/C2/C2B/C3 ya cubren

# --- Bloqueo de Empates (V4.3) ---
# Backtest 92 partidos: frecuencia real empates=17.9%, modelo asigna 25.7% (+7.9% sesgo).
# El mercado sobreestima aun mas (30.1%). Apostar empate sistematicamente destruye EV.
# Ningun camino puede seleccionar EMPATE como pick final.
APUESTA_EMPATE_PERMITIDA = get_param('apuesta_empate_permitida', default=False)

# Mercado O/U 2.5 (complementario — opera solo cuando no hay señal 1X2)
# True  = activo  (backtest post-fix: 5 bets, 100% hit, +140.6% yield)
# False = shadow  (registra pick_ou en DB pero stake_ou = 0, sin dinero real)
# Cambiar a False si se quiere observar sin apostar hasta acumular n >= 30
APUESTA_OU_ACTIVA = get_param('apuesta_ou_live', default=True)

# --- Filtro xG Margen O/U — ASIMETRICO (Fix B, V4.6) ---
# Backtest 32 partidos: xG en [2.5-2.8) -> goles_prom=0.60, UNDER=100%.
# El modelo dice "levemente OVER" pero la realidad es dramaticamente UNDER.
# Causa: xG_visita inflado empuja el total hacia 2.5-2.8 en juegos que son UNDER reales.
# Fix B: margen OVER mas estricto (0.30) que UNDER (0.25).
# OVER solo si xG > 2.80 | UNDER solo si xG < 2.25 | Zona [2.25-2.80] = PASAR.
MARGEN_XG_OU_OVER  = get_param('margen_xg_ou_over', default=0.30)  # Fix B (V4.6): era 0.25 simetrico; zona [2.5-2.8) = trampa UNDER
MARGEN_XG_OU_UNDER = get_param('margen_xg_ou_under', default=0.25)  # sin cambio — UNDER con xG < 2.25 sigue siendo valido
MARGEN_XG_OU = MARGEN_XG_OU_UNDER  # alias de compatibilidad (no usar en logica nueva)

# --- Fix A (V4.6): Corrección de ventaja local (xG_visita sobreestimado) ---
# Backtest 32 partidos: xG_visita bias = +0.491 global (Brasil +0.494, Turquia +0.631, Argentina +0.398).
# El modelo EMA no captura el efecto real de jugar de visitante: menos posesion,
# mayor presion defensiva, mayor tendencia a acumular tiros sin convertir.
# La correccion es DELTA-DEPENDIENTE: cuando el local ya domina (delta_xG >= 1.0),
# el modelo lo refleja y no se necesita ajuste. Cuando estan equilibrados (delta=0),
# se aplica la correccion completa.
# Conservador: 50% del sesgo observado para evitar sobreajuste con N=32.
CORR_VISITA_POR_LIGA = {
    "Brasil":     0.25,   # bias observado +0.494 -> corr 50% = 0.25
    "Turquia":    0.30,   # bias observado +0.631 -> corr 50% = 0.30 (aprox)
    "Argentina":  0.20,   # bias observado +0.398 -> corr 50% = 0.20
    "Noruega":    0.20,   # sin datos propios, usar referencia global
    "Inglaterra": 0.20,   # sin datos propios, usar referencia global
}
CORR_VISITA_FALLBACK   = 0.20   # fallback para ligas sin calibracion propia
CORR_VISITA_ESCALA_DELTA = 1.0  # delta en xG a partir del cual la correccion llega a 0

def min_ev_escalado(prob):
    """EV minimo requerido segun nivel de confianza del modelo (Opcion 1)."""
    if prob >= 0.50: return 0.03   # alta confianza: umbral base
    if prob >= 0.40: return 0.08   # media: doble umbral
    if prob >= FLOOR_PROB_MIN: return 0.12  # baja-media: triple umbral
    return 999.0                   # < 33%: rechazar siempre

# --- Calibración de compresión (Fix #5, V4.5) ---
# Backtest 92 partidos: cuando el modelo asigna 40-50% a LOCAL o VISITA,
# la frecuencia real de ese outcome es 53.4% (+8.4pp de sesgo).
# Causa: Dixon-Coles comprime probabilidades hacia 0.5 con xG moderados.
# Corrección conservadora: 50% del sesgo (0.042) para evitar sobreajuste con N=92.
# CALIBRACION_ACTIVA = False desactiva la corrección sin tocar el código.
CALIBRACION_ACTIVA        = get_param('calibracion_activa', default=True)
CALIBRACION_BUCKET_MIN    = get_param('calibracion_bucket_min', default=0.40)   # bucket donde se observó el sesgo
CALIBRACION_BUCKET_MAX    = get_param('calibracion_bucket_max', default=0.50)   # (exclusive: 0.50+ asumido bien calibrado)
CALIBRACION_CORRECCION    = get_param('calibracion_delta', default=0.042)  # +50% del sesgo observado (+8.4pp / 2)

# --- Hallazgo C (V4.7): Multiplicador de stake por dominancia xG ---
# Backtest 32 partidos: cuando delta_xG (|xG_local - xG_visita|) >= 0.5,
# el favorito del modelo ganó el 100% de los partidos (5/5).
# En rango [0.2-0.5): 57% hit pero 0% sorpresas con delta > 0.3 (fav nunca pierde,
# solo empata). En [0.0-0.2): 62% hit, 19% sorpresas — señal débil.
# MECANISMO: no abre apuestas nuevas (EV negativo sigue siendo PASAR), sino que
# multiplica el stake Kelly en apuestas que ya pasaron todos los filtros.
# Conservador: N=5 en bucket alto — multiplicador máximo 1.30 (no 2x).
# DELTA_STAKE_ACTIVO = False desactiva sin tocar lógica.
DELTA_STAKE_ACTIVO    = get_param('delta_stake_activo', default=True)
DELTA_STAKE_UMBRAL    = get_param('delta_stake_umbral', default=0.50)   # a partir de aquí: 100% hit en backtest
DELTA_STAKE_MULT_ALTO = get_param('delta_stake_mult_alto', default=1.30)   # delta >= 0.50: x1.30 del stake Kelly
DELTA_STAKE_MULT_MED  = get_param('delta_stake_mult_med', default=1.15)   # delta [0.30-0.50): x1.15 (0% sorpresas pero empates)
DELTA_STAKE_UMBRAL_MED= get_param('delta_stake_umbral_med', default=0.30)   # umbral del bucket medio

# --- Hallazgo G (V4.8): Prior dinámico de ventaja local por liga ---
# Problema: el modelo Dixon-Coles ignora el prior histórico de ventaja de local
# de ESTA liga. Si en Brasil el LOCAL gana el 52% de los partidos pero el modelo
# predice solo 44% promedio, hay un sesgo sistemático explotable.
# Solución: cuando acumulamos N_MIN liquidados por liga, calculamos la frecuencia
# real de victorias locales y aplicamos un boost conservador (50% del gap) a p1.
# Conservador: 50% del sesgo observado para evitar sobreajuste (igual que Fix #5).
# INACTIVO hasta N >= N_MIN. Seguro: nunca actúa con datos insuficientes.
N_MIN_HALLAZGO_G  = get_param('n_min_hallazgo_g', default=50)     # mínimo de partidos liquidados para activar por liga
BOOST_G_FRACCION  = get_param('boost_g_fraccion', default=0.50)   # conservador: 50% del gap observado (mismo criterio que Fix #5)
HALLAZGO_G_ACTIVO = get_param('hallazgo_g_activo', default=True)   # False = desactivar sin tocar lógica

def multiplicador_delta_stake(delta_xg):
    """
    Hallazgo C (V4.7): escala el stake Kelly segun la dominancia xG del partido.

    La dominancia xG es una señal INDEPENDIENTE del EV y la divergencia de cuotas.
    Cuando el modelo ve una diferencia clara de expectativa de goles, el partido
    tiene menos incertidumbre estructural — el favorito convierte esa ventaja
    con mucha más frecuencia de lo que el modelo de probabilidades captura.

    NO abre apuestas nuevas. Solo multiplica el stake de apuestas que ya
    pasaron todos los filtros (el EV negativo sigue siendo PASAR siempre).

    El cap de Kelly (MAX_KELLY_PCT) se aplica DESPUÉS del multiplicador,
    garantizando que nunca se supere el límite de riesgo absoluto.
    """
    if not DELTA_STAKE_ACTIVO:
        return 1.0
    if delta_xg >= DELTA_STAKE_UMBRAL:
        return DELTA_STAKE_MULT_ALTO   # 100% hit en backtest (n=5)
    if delta_xg >= DELTA_STAKE_UMBRAL_MED:
        return DELTA_STAKE_MULT_MED    # 0% sorpresas pero con empates (n=8)
    return 1.0


def aplicar_hallazgo_g(p1, px, p2, pais, hallazgo_g_data):
    """
    Hallazgo G (V4.8): ajusta p1 (LOCAL) según la frecuencia real de victorias locales
    observada en partidos liquidados de esa liga.

    Solo se activa cuando N_liquidados >= N_MIN_HALLAZGO_G.
    El boost es conservador: 50% del gap entre frecuencia real y probabilidad del modelo.
    Se renormaliza el vector para que p1 + px + p2 = 1.

    Ejemplo (Brasil, freq_real=0.52, p1_modelo=0.44):
      gap = 0.52 - 0.44 = 0.08
      boost = 0.08 * 0.50 = 0.04
      p1_nuevo = 0.44 + 0.04 = 0.48 -> renormalizar -> px y p2 se achican proporcionalmente.
    """
    if not HALLAZGO_G_ACTIVO or pais not in hallazgo_g_data:
        return p1, px, p2

    freq_real = hallazgo_g_data[pais]['freq_local']
    gap = freq_real - p1

    # Solo aplicar si el modelo subestima LOCAL (gap positivo) y la diferencia es >1pp
    if gap < 0.01:
        return p1, px, p2

    boost = gap * BOOST_G_FRACCION
    p1_nuevo = min(p1 + boost, 0.95)  # cap: nunca por encima de 95%
    delta = p1_nuevo - p1

    # Reducir px y p2 proporcionalmente al peso relativo de cada uno
    peso_px = px / (px + p2) if (px + p2) > 0 else 0.5
    peso_p2 = 1.0 - peso_px
    px_nuevo = max(0.01, px - delta * peso_px)
    p2_nuevo = max(0.01, p2 - delta * peso_p2)

    # Renormalizar para garantizar suma exacta = 1
    total = p1_nuevo + px_nuevo + p2_nuevo
    return round(p1_nuevo / total, 6), round(px_nuevo / total, 6), round(p2_nuevo / total, 6)


def corregir_calibracion(p1, px, p2):
    """
    Fix #5 (V4.5): corrige el sesgo de compresión del modelo Poisson-Dixon-Coles.
    Si LOCAL o VISITA caen en el bucket [40%, 50%), les suma CALIBRACION_CORRECCION
    y renormaliza el vector de probabilidades para que sumen 1.
    El empate nunca se corrige (ya está bloqueado y su sesgo es distinto).
    """
    if not CALIBRACION_ACTIVA:
        return p1, px, p2

    p1_cal, p2_cal = p1, p2
    if CALIBRACION_BUCKET_MIN <= p1 < CALIBRACION_BUCKET_MAX:
        p1_cal = p1 + CALIBRACION_CORRECCION
    if CALIBRACION_BUCKET_MIN <= p2 < CALIBRACION_BUCKET_MAX:
        p2_cal = p2 + CALIBRACION_CORRECCION

    # Sin cambio: nada estaba en el bucket
    if p1_cal == p1 and p2_cal == p2:
        return p1, px, p2

    # Renormalizar manteniendo px proporcional al delta
    total = p1_cal + px + p2_cal
    if total <= 0:
        return p1, px, p2
    return round(p1_cal / total, 6), round(px / total, 6), round(p2_cal / total, 6)


def corregir_ventaja_local(xg_local, xg_visita, liga=None):
    """
    Fix A (V4.6): corrige el sesgo sistematico de sobreestimacion de xG visitante.

    El modelo EMA no diferencia entre rendir como local y como visitante: toma el
    promedio historico de xG visitante del equipo, pero en la realidad los equipos
    visitantes generan mas tiros sin convertir (mayor presion defensiva rival,
    menos posesion, efectos psicologicos). Esto infla xG_visita en DB.

    La correccion es delta-dependiente:
      - Partidos equilibrados (delta_xG = 0): correccion completa = CORR_BASE_LIGA
      - Local dominante (delta_xG = ESCALA): correccion = 0 (modelo ya lo refleja)
      - Lineal entre ambos extremos

    Ejemplo (Brasil, CORR_BASE=0.25, ESCALA=1.0):
      delta=0.0 -> resta 0.25 a xg_visita
      delta=0.5 -> resta 0.125
      delta=1.0 -> resta 0.00 (sin cambio)
    """
    base   = CORR_VISITA_POR_LIGA.get(liga, CORR_VISITA_FALLBACK)
    delta  = max(0.0, xg_local - xg_visita)
    escala = max(0.0, 1.0 - delta / CORR_VISITA_ESCALA_DELTA)
    correccion = base * escala
    return xg_local, max(0.10, xg_visita - correccion)

# --- Constantes de Modelo ---
RHO_FALLBACK = get_param('rho_fallback', default=-0.09)  # Fix #2 (V4.4): corregido de -0.03 a -0.09 segun Manifiesto II.C.
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


def tau(i, j, lam, mu, rho):
    """
    Factor de corrección Dixon-Coles para marcadores bajos (i+j <= 1).
    Ajusta la correlación entre goles del local (i) y visitante (j)
    que el modelo Poisson independiente ignora.

    Parámetros:
        i   — goles del local
        j   — goles del visitante
        lam — lambda esperada del local (xG local)
        mu  — lambda esperada del visitante (xG visitante)
        rho — coeficiente de correlación de la liga (negativo, ∈ [-0.30, -0.03])

    Retorna un multiplicador ≥ 0 que se aplica sobre p(i)*p(j).
    Para i+j > 1 devuelve 1.0 (sin corrección).
    """
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    elif i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    elif i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    elif i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


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

def evaluar_mercado_1x2(p1, px, p2, c1, cx, c2, liga=None):
    """
    Evalua mercado 1X2 con cuatro caminos (Manifiesto II.E + V4.3/V4.4):
    1. Favorito del modelo: umbral estandar, divergencia <= div_max (por liga)
    2. Value Hunting: busca maximo EV si favorito no cumple, misma divergencia
    2B. Desacuerdo Modelo-Mercado: prob >= 40%, div entre div_max y 0.30
    3. Alta Conviccion: EV >= 1.0, cuota <= 8.0 (mercado claramente equivocado)
    Fix #4 (V4.4): div_max es especifico por liga segun eficiencia de mercado.
    """
    # Resolver divergencia maxima segun eficiencia de mercado de la liga (F4 via DB)
    if liga:
        div_max = get_param('divergencia_max_1x2', scope=liga,
                            default=DIVERGENCIA_MAX_POR_LIGA.get(liga, DIVERGENCIA_MAX_1X2))
        # F9: margen predictivo por liga con auto-fill al global
        margen_pred = get_param('margen_predictivo_1x2', scope=liga, default=MARGEN_PREDICTIVO_1X2)
    else:
        div_max = DIVERGENCIA_MAX_1X2
        margen_pred = MARGEN_PREDICTIVO_1X2

    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return "[PASAR] Sin Cuotas", -100, 0

    probs_ord = sorted([p1, px, p2])
    if (probs_ord[2] - probs_ord[1]) < margen_pred:
        return "[PASAR] Margen Predictivo Insuficiente (<5%)", -100, 0

    probs  = {"LOCAL": p1, "VISITA": p2}
    cuotas = {"LOCAL": c1, "VISITA": c2}
    if APUESTA_EMPATE_PERMITIDA:
        probs["EMPATE"]  = px
        cuotas["EMPATE"] = cx

    # --- CAMINO 1: Evaluar al favorito del modelo ---
    fav_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[fav_key], cuotas[fav_key]
    ev_fav = (p_fav * c_fav) - 1
    umb_fav = (UMBRAL_EV_BASE * (0.5 / p_fav)) if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)  # Positiva = modelo ve mas prob que el mercado

    if c_fav <= TECHO_CUOTA_1X2 and ev_fav >= umb_fav and div_fav <= div_max:
        return f"[APOSTAR] {fav_key}", ev_fav, c_fav

    # --- CAMINO 2B: Regimen Desacuerdo Modelo-Mercado ---
    # El modelo favorece X pero el mercado favorece Y (distinto outcome).
    # Con prob_modelo >= 40% y divergencia moderada (div_max a 0.30), el modelo
    # gana al mercado con 80-100% de hit rate en backtest (92 partidos).
    # Con prob 33-40% el desacuerdo NO es señal confiable (hit=33%): no aplica.
    # NOTA: el umbral inferior del desacuerdo es div_max (por liga), no fijo 0.15.
    fav_mkt_key = min(cuotas, key=cuotas.get)  # favorito del mercado = cuota minima
    if (fav_key != fav_mkt_key
            and p_fav >= DESACUERDO_PROB_MIN
            and div_max < div_fav <= DIVERGENCIA_DESACUERDO_MAX
            and ev_fav >= min_ev_escalado(p_fav)
            and c_fav <= TECHO_CUOTA_ALTA_CONV):
        return f"[APOSTAR] {fav_key}", ev_fav, c_fav

    # --- CAMINO 3: Regimen Alta Conviccion ---
    # Modelo dice favorito (prob >= FLOOR) pero mercado lo pone como gran underdog
    # (cuota > TECHO normal => divergencia alta). Con EV >= 1.0 no es info oculta,
    # es el mercado equivocado. Se permite hasta TECHO_CUOTA_ALTA_CONV = 8.0.
    if (p_fav >= FLOOR_PROB_MIN
            and ev_fav >= CONVICCION_EV_MIN
            and c_fav <= TECHO_CUOTA_ALTA_CONV):
        return f"[APOSTAR] {fav_key}", ev_fav, c_fav

    # --- CAMINO 4: Consenso con el Mercado (V4.7, 2026-04-20) ---
    # Cuando el favorito del modelo coincide con el favorito del mercado y ambos
    # estan de acuerdo fuertemente (prob >= 0.45, cuota 1.40-2.00), ignorar EV.
    # Hallazgo fase3: bucket PASAR Riesgo/Beneficio n=27 => hit 88.9% yield +36.6%.
    # Filtrado c >= 1.40: n=21 hit 90.5% yield +46.3%.
    # Requisito: fav_modelo == fav_mercado (sin desacuerdo).
    fav_mkt_key_c4 = min(cuotas, key=cuotas.get)
    if (fav_key == fav_mkt_key_c4
            and p_fav >= CONSENSO_PROB_MIN
            and CONSENSO_CUOTA_MIN <= c_fav <= CONSENSO_CUOTA_MAX
            and div_fav <= div_max):
        return f"[APOSTAR] {fav_key}", ev_fav, c_fav

    # --- CAMINO 2: Value Hunting (underdog con maximo EV) — BAJA PRIORIDAD ---
    # F2b (usuario 2026-04-18): Camino 2 se evalua ULTIMO. Si C1/C2B/C3 ya
    # dispararon pick, C2 no corre. Ademas, SE RECHAZA cuando:
    #   - pick = VISITA (no LOCAL)  AND
    #   - prob en [0.33, 0.40)  AND
    #   - liga con sesgo xG_visita inflado: {Brasil, Inglaterra, Noruega, Turquia}
    # Razon: el xG_visita esta +1.07 inflado globalmente (experto-deportivo fase2),
    # el EV positivo del visitante en esa zona es falso positivo estructural.
    # Backtest fase2: C2 bucket destructor n=24 hit 29% yield +10%. Cortando el
    # subset destructor, yield 1X2 sube ~+120% y hit ~60%.
    LIGAS_SESGO_VISITA = ("Brasil", "Inglaterra", "Noruega", "Turquia")
    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    ev_key = max(evs, key=evs.get)
    p_ev, c_ev, m_ev = probs[ev_key], cuotas[ev_key], evs[ev_key]
    umb_ev = (UMBRAL_EV_BASE * (0.5 / p_ev)) if p_ev > 0 else 999
    div_ev = p_ev - (1 / c_ev)

    # Filtro F2b: subset destructor VISITA/33-40/liga-sesgo
    if (ev_key == "VISITA"
            and 0.33 <= p_ev < 0.40
            and liga in LIGAS_SESGO_VISITA):
        return "[PASAR] C2 restringido F2b (VISITA 33-40 liga sesgo)", m_ev, c_ev

    if c_ev <= TECHO_CUOTA_1X2 and m_ev >= umb_ev and div_ev <= div_max:
        return f"[APOSTAR] {ev_key}", m_ev, c_ev

    # --- DIAGNOSTICO ---
    if c_fav > TECHO_CUOTA_1X2: return "[PASAR] Techo Cuota", ev_fav, c_fav
    if ev_fav < umb_fav: return "[PASAR] Riesgo/Beneficio", ev_fav, c_fav
    if div_fav > div_max: return "[PASAR] Info Oculta", ev_fav, c_fav
    return "[PASAR] Sin Valor", ev_fav, c_fav

def evaluar_mercado_ou(po, pu, co, cu, p1, px, p2, xg_local=None, xg_visita=None):
    """
    Evalua mercado O/U 2.5 (Manifiesto II.E - Francotirador):
    SOLO evalua la opcion matematicamente favorita. Prohibido cazar valor.
    Filtro xG: el total esperado debe alejarse del umbral 2.5 en al menos
    MARGEN_XG_OU (0.4) goles. Evita apostar cuando la señal es marginal.
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [co, cu]):
        return "[PASAR] Sin Cuotas", -100, 0

    # Filtro xG: margen asimetrico OVER/UNDER (Fix B, V4.6)
    # xG [2.5-2.80) = trampa UNDER (backtest: goles_prom=0.60, UNDER=100%)
    # OVER solo si xG > 2.80 | UNDER solo si xG < 2.25
    if xg_local is not None and xg_visita is not None:
        xg_total = xg_local + xg_visita
        margen = MARGEN_XG_OU_OVER if xg_total >= 2.5 else MARGEN_XG_OU_UNDER
        if abs(xg_total - 2.5) < margen:
            return f"[PASAR] xG Margen Insuf ({xg_total:.2f}, delta={abs(xg_total-2.5):.2f}<{margen:.2f})", -100, 0

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

    if ev > umbral and c_fav <= TECHO_CUOTA_OU:
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
    print(f"[CONFIG] Umbral EV: {UMBRAL_EV_BASE} | Techo 1X2: {TECHO_CUOTA_1X2} (AltaConv/Desac: {TECHO_CUOTA_ALTA_CONV}) | Kelly: {FRACCION_KELLY} | Poisson: 0-{RANGO_POISSON-1}")
    print(f"[CONFIG] Floor prob: {FLOOR_PROB_MIN} | Div normal: {DIVERGENCIA_MAX_1X2} | Desacuerdo: prob>={DESACUERDO_PROB_MIN} div<={DIVERGENCIA_DESACUERDO_MAX} | AltaConv EV>={CONVICCION_EV_MIN}")
    print(f"[CONFIG] Consenso C4: prob>={CONSENSO_PROB_MIN} cuota {CONSENSO_CUOTA_MIN}-{CONSENSO_CUOTA_MAX}")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- Columnas shadow (crear si no existen) ---
    for col in ['incertidumbre REAL', 'shadow_xg_local REAL', 'shadow_xg_visita REAL',
                'apuesta_shadow_1x2 TEXT', 'stake_shadow_1x2 REAL',
                'xg_local REAL', 'xg_visita REAL']:
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
        BANKROLL = get_param('bankroll_fallback', default=100000.00)
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

    # --- HALLAZGO G: cargar frecuencias reales de victoria local por liga ---
    hallazgo_g_data = {}
    if HALLAZGO_G_ACTIVO:
        cursor.execute("""
            SELECT pais,
                   COUNT(*) as n,
                   AVG(CASE WHEN goles_l > goles_v THEN 1.0 ELSE 0.0 END) as freq_local
            FROM partidos_backtest
            WHERE estado = 'Liquidado'
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
            GROUP BY pais
        """)
        print("[HALLAZGO-G] Estado del prior de ventaja local por liga:")
        for pais_g, n_g, freq_local_g in cursor.fetchall():
            if n_g >= N_MIN_HALLAZGO_G:
                hallazgo_g_data[pais_g] = {'n': n_g, 'freq_local': freq_local_g}
                print(f"   [{pais_g}] N={n_g} >= {N_MIN_HALLAZGO_G} -> ACTIVO | freq_local_real={freq_local_g:.3f}")
            else:
                print(f"   [{pais_g}] N={n_g} < {N_MIN_HALLAZGO_G} -> INACTIVO (faltan {N_MIN_HALLAZGO_G - n_g} partidos)")
        if not hallazgo_g_data:
            print(f"   [HALLAZGO-G] Ninguna liga tiene N>={N_MIN_HALLAZGO_G} liquidados. Prior inactivo para todas.")
    else:
        print("[HALLAZGO-G] Desactivado globalmente (HALLAZGO_G_ACTIVO=False).")

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
        # FIX A REVERTIDO: la corrección de xG_visita debe hacerse en motor_data.py
        # (en el EMA), no aquí. Aplicarla en predicción flipa picks VISITA->LOCAL
        # correctos (Vasco vs Botafogo, Tigre vs Independiente). Ver análisis V4.6.

        # --- P5D fase3 (2026-04-20): GAMMA DE DISPLAY (no entra al Poisson) ---
        # Opcion D elegida: el xG crudo sigue entrando a Dixon-Coles para preservar
        # capacidad predictiva (probs con "filo"). Pero el xG que se PERSISTE en DB
        # y se muestra al usuario se comprime por gamma empirica (goles_real/xG_modelo).
        # Asi el usuario ve xG realistas sin deteriorar el Brier ni el volumen de picks.
        gamma_display = get_param('gamma_1x2', scope=pais, default=0.59)
        xg_local_display = xg_local * gamma_display
        xg_visita_display = xg_visita * gamma_display
        # xg_local y xg_visita siguen crudos para el Poisson (abajo)

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
                pb *= tau(i, j, xg_local, xg_visita, rho)  # Ajuste Dixon-Coles

                if i > j: p1 += pb
                elif i == j: px += pb
                else: p2 += pb
                if (i + j) > 2.5: po += pb
                else: pu += pb

        # Normalizacion 1X2
        s1 = p1 + px + p2
        if s1 > 0: p1, px, p2 = p1/s1, px/s1, p2/s1
        so = po + pu
        if so > 0: po, pu = po/so, pu/so

        # O/U calibrado: segundo loop con xG corregido por factor por liga (no afecta 1X2)
        factor_ou = get_param('factor_corr_xg_ou', scope=pais,
                              default=FACTOR_CORR_XG_OU_POR_LIGA.get(pais, FACTOR_CORR_XG_OU))
        xg_l_ou = xg_local  * factor_ou
        xg_v_ou = xg_visita * factor_ou
        po_ou, pu_ou = 0.0, 0.0
        for i in range(RANGO_POISSON):
            for j in range(RANGO_POISSON):
                pb = poisson(i, xg_l_ou) * poisson(j, xg_v_ou)
                pb *= tau(i, j, xg_l_ou, xg_v_ou, rho)
                if (i + j) > 2.5: po_ou += pb
                else:              pu_ou += pb
        so_ou = po_ou + pu_ou
        if so_ou > 0: po_ou, pu_ou = po_ou/so_ou, pu_ou/so_ou

        # Guardar probabilidades RAW (sin Fix #5 ni Hallazgo G) para el Shadow
        p1_raw, px_raw, p2_raw = p1, px, p2

        # Hallazgo G (V4.8): boost de ventaja local observada en esta liga (solo si N >= 50)
        p1, px, p2 = aplicar_hallazgo_g(p1, px, p2, pais, hallazgo_g_data)
        if pais in hallazgo_g_data:
            g_info = hallazgo_g_data[pais]
            boost_aplicado = round(p1 - p1_raw, 4)
            if abs(boost_aplicado) > 0.0005:
                print(f"   [HALLAZGO-G] {local} vs {visita} ({pais}) | "
                      f"freq_real={g_info['freq_local']:.3f} p1: {p1_raw:.3f}->{p1:.3f} (boost={boost_aplicado:+.4f})")

        # Fix #5 (V4.5): corrección de sesgo de compresión de calibración
        p1, px, p2 = corregir_calibracion(p1, px, p2)

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

        # Evaluacion raw (sin filtros adicionales) — Fix #4: pasa pais para div_max por liga
        pick_1x2_raw, ev_1x2, cu_1x2 = evaluar_mercado_1x2(p1, px, p2, c1_v, cx_v, c2_v, liga=pais)

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

        # --- SHADOW (V4.8): Grupo de control — Opcion 1 SIN Fix #5 NI Hallazgo G NI Hallazgo C ---
        # Proposito: validar a largo plazo que Fix #5 (calibracion) + Hallazgo G (prior local)
        # + Hallazgo C (delta stake) agregan valor real sobre el sistema base.
        # Si en 200+ partidos acumulados Op1 > Shadow en yield -> los fixes funcionan.
        # Metodologia: usa p1_raw/px_raw/p2_raw (antes de Hallazgo G y Fix #5),
        # aplica los mismos filtros de Opcion 1 (floor 33% + EV escalado),
        # pero SIN multiplicador de stake por delta xG.
        pick_shadow_raw, ev_shadow_raw, cu_shadow_raw = evaluar_mercado_1x2(
            p1_raw, px_raw, p2_raw, c1_v, cx_v, c2_v, liga=pais)
        prob_shadow_raw = 0.0
        if "[APOSTAR]" in pick_shadow_raw:
            if   "LOCAL"  in pick_shadow_raw: prob_shadow_raw = p1_raw
            elif "EMPATE" in pick_shadow_raw: prob_shadow_raw = px_raw
            else:                             prob_shadow_raw = p2_raw

        pick_shadow_1x2 = pick_shadow_raw
        if "[APOSTAR]" in pick_shadow_raw:
            if prob_shadow_raw < FLOOR_PROB_MIN:
                pick_shadow_1x2 = f"[PASAR] Shadow-Floor ({prob_shadow_raw:.0%}<{FLOOR_PROB_MIN:.0%})"
            elif ev_shadow_raw < min_ev_escalado(prob_shadow_raw):
                pick_shadow_1x2 = f"[PASAR] Shadow-EV ({ev_shadow_raw:.3f}<{min_ev_escalado(prob_shadow_raw):.3f})"

        cu_1x2_shadow = cu_shadow_raw if "[APOSTAR]" in pick_shadow_1x2 else 0.0
        ev_1x2_shadow = ev_shadow_raw if "[APOSTAR]" in pick_shadow_1x2 else 0.0

        pick_ou, ev_ou, cu_ou = evaluar_mercado_ou(po_ou, pu_ou, co_v, cu_v, p1, px, p2, xg_l_ou, xg_v_ou)

        # PRETEST MODE (fase3 decision usuario 2026-04-20):
        # apuestas_live por liga. Si False: picks se calculan y persisten (para medir hit%)
        # pero stake=0 (sin plata real). Se activa a True automaticamente cuando
        # scripts/evaluar_pretest.py detecta hit >= 55% con N >= 20 en la liga.
        _live_val = get_param('apuestas_live', scope=pais, default='FALSE')
        _live = str(_live_val).upper() in ('TRUE', '1', 'T') if not isinstance(_live_val, bool) else _live_val
        stk_1x2 = calcular_stake_independiente(pick_1x2, ev_1x2, cu_1x2, BANKROLL, MAX_KELLY_PCT) if _live else 0.0
        # Si APUESTA_OU_ACTIVA=False: pick queda en DB (shadow) pero stake=0 (sin dinero real)
        stk_ou  = calcular_stake_independiente(pick_ou, ev_ou, cu_ou, BANKROLL, MAX_KELLY_PCT) if (APUESTA_OU_ACTIVA and _live) else 0.0
        stk_shadow_1x2 = calcular_stake_independiente(
            pick_shadow_1x2, ev_1x2_shadow, cu_1x2_shadow, BANKROLL, MAX_KELLY_PCT) if _live else 0.0

        # Hallazgo C (V4.7): multiplicador de stake por dominancia xG
        # Solo escala apuestas que ya pasaron todos los filtros. El cap MAX_KELLY_PCT
        # garantiza que no se supere el límite absoluto de riesgo.
        delta_xg = abs(xg_local - xg_visita)
        mult_delta = multiplicador_delta_stake(delta_xg)
        if mult_delta > 1.0:
            if stk_1x2 > 0:
                stk_1x2 = min(round(stk_1x2 * mult_delta, 2), BANKROLL * MAX_KELLY_PCT)
                print(f"   [DELTA-xG] {local} vs {visita} | delta={delta_xg:.2f} mult=x{mult_delta} -> stk_1x2={stk_1x2:.2f}")
            if stk_ou > 0:
                stk_ou  = min(round(stk_ou  * mult_delta, 2), BANKROLL * MAX_KELLY_PCT)

        # Overlap: 1X2 siempre tiene prioridad sobre O/U (V4.9)
        # Razon: backtest muestra 1X2 yield=165% vs O/U yield=55% cuando compiten.
        # O/U opera como mercado COMPLEMENTARIO — solo cuando no hay señal 1X2.
        # Backtest O/U "solo sin 1X2": 10 bets, 80% hit, +77.6% yield.
        if stk_1x2 > 0 and stk_ou > 0:
            stk_ou = 0.0
            pick_ou = "[PASAR] Overlap 1X2 Prioritario"

        partidos_a_actualizar.append({
            'id_partido': id_partido, 'pais': pais, 'fecha': fecha_str,
            'p1': p1, 'px': px, 'p2': p2, 'po': po_ou, 'pu': pu_ou,
            'pick_1x2': pick_1x2, 'ev_1x2': ev_1x2, 'cu_1x2': cu_1x2, 'stk_1x2': stk_1x2,
            'pick_ou': pick_ou, 'ev_ou': ev_ou, 'cu_ou': cu_ou, 'stk_ou': stk_ou,
            'pick_shadow_1x2': pick_shadow_1x2, 'stk_shadow_1x2': stk_shadow_1x2,
            'incertidumbre': round(incertidumbre, 4),
            'xg_local': round(xg_local_display, 3), 'xg_visita': round(xg_visita_display, 3),  # P5D: gamma applied
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
                incertidumbre=?, xg_local=?, xg_visita=?,
                shadow_xg_local=?, shadow_xg_visita=?,
                estado='Calculado'
            WHERE id_partido=?
        """, (
            p['p1'], p['px'], p['p2'], p['po'], p['pu'],
            p['pick_1x2'], p['pick_ou'],
            round(p['stk_1x2'], 2), round(p['stk_ou'], 2),
            p['pick_shadow_1x2'], round(p['stk_shadow_1x2'], 2),
            p['incertidumbre'], p['xg_local'], p['xg_visita'],
            p['shadow_xg_l'], p['shadow_xg_v'],
            p['id_partido']
        ))
        calculados += 1

    conn.commit()
    conn.close()

    # Estadisticas de filtrado Op1 vs Shadow (grupo de control)
    n_op1         = sum(1 for p in partidos_a_actualizar if "[APOSTAR]" in p['pick_1x2'])
    n_op4         = sum(1 for p in partidos_a_actualizar if "[APOSTAR]" in p['pick_shadow_1x2'])
    n_solo_shadow = sum(1 for p in partidos_a_actualizar
                        if "[APOSTAR]" in p['pick_shadow_1x2'] and "[APOSTAR]" not in p['pick_1x2'])
    n_solo_op1    = sum(1 for p in partidos_a_actualizar
                        if "[APOSTAR]" in p['pick_1x2'] and "[APOSTAR]" not in p['pick_shadow_1x2'])
    print(f"\n[EXITO] {calculados} partidos calculados.")
    print(f"[OP1-ACTIVA]  Apuestas generadas: {n_op1} (Hallazgo G + Fix #5 + Hallazgo C + EV escalado)")
    print(f"[SHADOW]      Apuestas control:   {n_op4} (sin Hallazgo G, sin Fix #5, sin Hallazgo C)")
    print(f"[DIVERGENCIA] Op1 exclusivo: {n_solo_op1} | Shadow exclusivo: {n_solo_shadow} | Coincidentes: {n_op1 - n_solo_op1}")
    print(f"[SHADOW] Altitud activa: {shadow_log_alt} | Incertidumbre alta (>0.15): {shadow_log_incert}")
    g_activas = len(hallazgo_g_data)
    print(f"[HALLAZGO-G]  Ligas con prior activo: {g_activas}/{len(DIVERGENCIA_MAX_POR_LIGA)}")
    print("[SISTEMA] Motor Calculadora V4.8 ha finalizado su ejecucion.")

if __name__ == "__main__":
    main()

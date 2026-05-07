import sqlite3
import requests
import concurrent.futures
from src.comun import gestor_nombres
import math
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta
from src.comun.config_sistema import LIGAS_ESPN, DB_NAME, LIGAS_SOFA_PRIMARY
from src.comun.constantes_espn import ESTADOS_ESPN_FINALIZADO
from src.comun.tipos import safe_int, safe_float
from src.comun.tiempo import fecha_a_espn
from src.comun.config_motor import get_param


def _fetch_espn_json(session, url, pais, fecha_api):
    """Thread-safe fetch de ESPN scoreboard. Retorna dict JSON o None.
    Usado en ThreadPoolExecutor para paralelizar requests dentro de cada fecha.
    """
    try:
        resp = session.get(url, timeout=(3, 8))
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.exceptions.ReadTimeout:
        # Retry una vez
        try:
            resp = session.get(url, timeout=(3, 8))
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            print(f"      [SKIP] {pais} {fecha_api} colgado 2 veces, saltado.")
            return None
    except Exception:
        return None

# ==========================================
# MOTOR DATA V9.2 (REGRESIÓN BAYESIANA INTEGRADA + --rebuild)
# Responsabilidad: Ajuste de xG, cálculo de EMA y anclaje a la media.
# V9.2: LIGAS_ESPN y DB_NAME importados desde config_sistema.
# ==========================================

ALFA_EMA  = get_param('alfa_ema', default=0.15)  # Fallback global si la liga no tiene ALFA propio
N0_ANCLA  = get_param('n0_ancla', default=5)    # Fix #1 (V4.4): ancla Bayesiana N-dependiente. N=0 -> 100% liga; N=5 -> 50/50; N=20 -> 80/20.

# Fix #3 (V4.4): ALFA por liga según volatilidad observada en backtest.
# Razonamiento:
#   - ALFA alto  => el modelo olvida rápido, reacciona a tendencias recientes  (ligas volátiles)
#   - ALFA bajo  => el modelo es más conservador, confía en la media histórica  (ligas estables)
# Valores derivados de varianza xG observada en backtest de 92 partidos:
#   Brasil  -> xG inflados, alta dispersión entre equipos          -> ALFA 0.20
#   Turquia -> resultados impredecibles, alta varianza de marcador -> ALFA 0.20
#   Noruega -> liga corta/estacional, equipos con pocos datos      -> ALFA 0.18
#   Argentina-> volatilidad media, liga competitiva                -> ALFA 0.15 (base)
#   Inglaterra-> mercado eficiente, equipos estables               -> ALFA 0.12
ALFA_EMA_POR_LIGA = {
    "Brasil":     0.20,
    "Turquia":    0.20,
    "Noruega":    0.18,
    "Argentina":  0.15,
    "Inglaterra": 0.12,
    # Ligas sudamericanas incorporadas 2026-04-11:
    #   Sin backtest propio -> valores conservadores basados en perfil de liga.
    #   Bolivia  -> liga corta (2 ruedas), poca cobertura de datos; fallback seguro 0.15
    #   Chile    -> liga estable con Apertura/Clausura, mercado mediano; similar a Argentina 0.15
    #   Uruguay  -> liga dividida (Apertura/Clausura), volatilidad media; similar a Argentina 0.15
    #   Peru     -> competencia irregular, equipos muy dispares en nivel; algo mas volatil 0.18
    #   Ecuador  -> resultados variables, equipos con disparidad alta; similar a Peru 0.18
    #   Colombia -> liga de medio-alto nivel sudamericano, competitiva; similar a Argentina 0.15
    #   Venezuela -> liga con menor nivel, resultados impredecibles, baja cobertura; 0.20
    "Bolivia":   0.15,   # Pocos datos disponibles; fallback seguro = Argentina base
    "Chile":     0.15,   # Liga estable, perfil similar a Argentina
    "Uruguay":   0.15,   # Liga dividida pero competitiva, perfil Argentina
    "Peru":      0.18,   # Equipos dispares, mayor volatilidad; perfil Noruega
    "Ecuador":   0.18,   # Resultados variables; perfil Noruega
    "Colombia":  0.15,   # Liga competitiva, similar a Argentina
    "Venezuela": 0.20,   # Alta impredictibilidad, baja cobertura; perfil Brasil/Turquia
    # Piloto europeo 2026-04-21:
    #   Espana (LaLiga) -> mercado muy eficiente (top-5 UEFA), equipos estables,
    #                      cobertura total de datos. Perfil equivalente a Inglaterra:
    #                      ALFA bajo para que el modelo confie en la media historica.
    "Espana":    0.12,   # Perfil Premier League: mercado eficiente + plantillas estables
    # Big 5 europeo completado 2026-04-21:
    #   Italia (Serie A)      -> liga defensiva, equipos estables, mercado eficiente top-5 UEFA.
    #                            Perfil Inglaterra/Espana: ALFA bajo (0.12) — confiar en media.
    #   Alemania (Bundesliga) -> liga ofensiva (~3.0-3.2 goles/partido), mercado eficiente pero
    #                            con varianza mayor por goles altos. Ligeramente mas reactivo: 0.13.
    #   Francia (Ligue 1)     -> mercado algo menos eficiente (dominio historico PSG -> dispersion
    #                            de niveles), equipos mas variables. Mas reactivo al cambio: 0.14.
    "Italia":    0.12,   # Perfil Premier League: liga defensiva, mercado eficiente
    "Alemania":  0.13,   # Ofensiva con varianza alta -> levemente mas reactivo que EPL
    "Francia":   0.14,   # Dispersion de niveles (PSG) -> ALFA intermedio
}

# LIGAS_ESPN importado desde config_sistema — no definir aqui
# safe_int / safe_float importados desde src.comun.tipos


def extraer_stats_raw(estadisticas):
    """
    Extrae tiros al arco, tiros totales y corners desde la lista de estadísticas ESPN.
    Devuelve (sot, total_shots, corners) como enteros.
    Separado de calcular_xg_hibrido para permitir calibración OLS futura sin acoplar lógica.
    """
    sot, corners, total_shots = 0, 0, 0
    for stat in (estadisticas or []):
        nombre = stat.get('name', '')
        valor = safe_float(stat.get('displayValue', 0))
        if nombre == 'shotsOnTarget':
            sot = int(valor)
        elif nombre == 'wonCorners':     # B2 fase3: ESPN real es 'wonCorners' (antes: 'cornerKicks')
            corners = int(valor)
        elif nombre == 'totalShots':     # B2 fase3: ESPN real es 'totalShots' (antes: 'shots')
            total_shots = int(valor)
    return sot, total_shots, corners


def lookup_stats_sofa_primario(conn, liga, fecha, ht, at):
    """[SOFA-PRIMARY scaffolding 2026-05-07]

    Busca stats post-partido en sofascore_match_features para ligas listadas
    en LIGAS_SOFA_PRIMARY. Si encuentra row con error IS NULL, devuelve dict
    con sot/shots/corners para local y visita. Caller lo usa como fuente
    PRIMARIA de stats; cae a extraer_stats_raw(ESPN) cuando esta función
    devuelve None (o cuando liga NO está en LIGAS_SOFA_PRIMARY).

    Diseñado para ligas EU expansión (Holanda/Portugal/Escocia/Dinamarca/
    Belgica/Grecia/Suecia) donde:
      - ESPN scoreboard devuelve fixture pero statistics[] vacío (DEN/BEL/GRE)
      - O ESPN tiene stats pero SOFA es estrictamente mejor por xgot 100% (NED/POR/SCO)
      - O xg/xgot NULL en SOFA pero stats sí (SWE → fallback custom)

    NOTA temporal: scrape_sofa_post_liquidacion corre en FASE 3.1 (después de
    motor_data en FASE 3). Día 1 fresh events: SOFA aún no scrapeado → MISS →
    fallback ESPN. Día 2+: SOFA ya cargado → HIT. Aceptable para scaffolding;
    para ligas SOFA-only sin stats ESPN (DEN/BEL/GRE) eventualmente requerirá
    reorden de pipeline o re-pass de motor_data tras FASE 3.1.

    Args:
      conn: sqlite3 connection
      liga: nombre interno (e.g., "Holanda")
      fecha: 'YYYY-MM-DD'
      ht, at: equipos local/visita ya canonicalizados via gestor_nombres

    Returns:
      dict con keys (sot_l, shots_l, corners_l, sot_v, shots_v, corners_v)
      o None si no hay match SOFA disponible.
    """
    if liga not in LIGAS_SOFA_PRIMARY:
        return None
    if conn is None or not fecha or not ht or not at:
        return None
    try:
        from analisis.aliases_sofa_espn import norm_team_name
        from datetime import datetime, timedelta
        cur = conn.cursor()
        ht_n = norm_team_name(ht, liga)
        at_n = norm_team_name(at, liga)

        try:
            d0 = datetime.fromisoformat(fecha).date()
            fechas_alt = [(d0 + timedelta(days=delta)).isoformat() for delta in (0, -1, 1, -2, 2)]
        except (ValueError, TypeError):
            fechas_alt = [fecha]

        for f in fechas_alt:
            rows = cur.execute('''
                SELECT ht, at,
                       shots_on_target_l, shots_on_target_v,
                       shots_total_l, shots_total_v,
                       corners_l, corners_v
                FROM sofascore_match_features
                WHERE liga=? AND fecha=? AND error IS NULL
            ''', (liga, f)).fetchall()
            for sofa_ht, sofa_at, sot_l, sot_v, sh_l, sh_v, c_l, c_v in rows:
                if norm_team_name(sofa_ht, liga) == ht_n and norm_team_name(sofa_at, liga) == at_n:
                    return {
                        'sot_l': int(sot_l) if sot_l is not None else 0,
                        'shots_l': int(sh_l) if sh_l is not None else 0,
                        'corners_l': int(c_l) if c_l is not None else 0,
                        'sot_v': int(sot_v) if sot_v is not None else 0,
                        'shots_v': int(sh_v) if sh_v is not None else 0,
                        'corners_v': int(c_v) if c_v is not None else 0,
                    }
    except Exception:
        return None
    return None

def calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga=0.03, pais=None):
    """
    Calcula los Goles Esperados (xG) a partir de estadísticas a nivel de partido.

    P4 fase3 (2026-04-20): coeficientes calibrados via OLS por liga.
      beta_sot: por liga (desde config_motor_valores, scope=<pais>).
                Ligas con N>=30 tienen β específico. Resto fallback global=0.352.
                Valores del manifiesto anterior (0.30 global) eran sub-óptimos.
      beta_shots_off: global 0.010 (era 0.040). OLS midió -0.008: reducido a 0.010 conservador.
                      Shots_off no correlaciona con goles en la muestra.
      coef_corner_liga: se mantiene como viene del caller (ligas_stats.coef_corner_calculado).
    """
    goles_reales = safe_float(goles_reales)
    if not estadisticas:
        return goles_reales

    sot, corners, total_shots = 0, 0, 0
    for stat in estadisticas:
        nombre = stat.get('name', '')
        valor = safe_float(stat.get('displayValue', 0))
        if nombre == 'shotsOnTarget':
            sot = valor
        elif nombre == 'wonCorners':     # B2 fase3: ESPN real es 'wonCorners' (antes: 'cornerKicks')
            corners = valor
        elif nombre == 'totalShots':     # B2 fase3: ESPN real es 'totalShots' (antes: 'shots')
            total_shots = valor

    shots_off_target_or_blocked = max(0, total_shots - sot)

    # Coeficientes P4 recalibrados
    beta_sot = get_param('beta_sot', scope=pais, default=0.352)
    beta_shots_off = get_param('beta_shots_off', default=0.010)

    xg_calc = (sot * beta_sot) + (shots_off_target_or_blocked * beta_shots_off) + (corners * coef_corner_liga)
    if xg_calc == 0 and goles_reales > 0:
        return goles_reales

    xg_final = (xg_calc * 0.70) + (goles_reales * 0.30)
    return round(xg_final, 3)


def calcular_xg_v2_hibrido_sofa(estadisticas, goles_reales, liga=None,
                                 coef_corner_liga=0.03, conn=None,
                                 fecha=None, ht=None, at=None, es_local=None):
    """
    [V2 hybrid SOFA - POC 2026-05-04]
    xG calculator híbrido per-liga: blend xg_shotmap (SofaScore) + xg_calc V0 legacy.

    Rationale (POC validado, ablation v2 N=465 eventos, RMSE forward-EMA):
      LATAM exóticas (BOL/VEN/URU/ECU): ESPN devuelve stats=0 → xG_V0=0 (motor falla).
        SOFA xg_shotmap basado en coordenadas + situation reduce RMSE -7.8% a -11.4%.
      LATAM mainstream (ARG/BRA): SOFA -2% RMSE marginal.
      EUR mainstream (ENG/ESP/ITA/ALE/FRA/TUR/NOR): SOFA ≈ ruido vs V0 (V0 ya calibrado).

    Fórmula:
      xg_calc_v2 = α(liga) · xg_shotmap_sofa + (1 − α(liga)) · xg_calc_v0_legacy
      α(liga) ∈ config_motor_valores.alpha_xg_v2_hibrido_sofa
        Default α(BOL/VEN/URU)=1.0, α(ECU)=0.95, α(PER)=0.85, α(ARG/BRA)=0.50,
                α(EUR)=0.25-0.40, α(global fallback)=0.30

    Si SOFA NO disponible (no hay row en sofascore_match_features para liga/fecha/ht/at):
      → fallback a calcular_xg_hibrido (V0 legacy)

    Modo SHADOW (default) vs ACTIVO:
      config_motor_valores.xg_v2_hibrido_modo IN ('shadow','active'):
        shadow: NO afecta producción. Usar para SHADOW logging.
        active: aplica al motor productivo.

    Manifesto change autorizado por usuario 2026-05-04 (sesión motor_xg_v2_sofa_poc).

    Args:
      estadisticas: list de stats ESPN (mismo formato que calcular_xg_hibrido)
      goles_reales: int goles del equipo en este partido
      liga: str (e.g., 'Argentina')
      coef_corner_liga: float coef corner para fallback V0
      conn: sqlite3 connection (para lookup SOFA)
      fecha: str 'YYYY-MM-DD' del partido
      ht: str equipo local
      at: str equipo visita
      es_local: bool — True si el equipo del cálculo es local

    Returns:
      float xG ajustado, o resultado de V0 si SOFA no disponible.
    """
    # Fallback V0 si modo shadow o falta info para lookup SOFA
    modo = get_param('xg_v2_hibrido_modo', default='shadow')
    if modo == 'shadow':
        # SHADOW: NO aplicar v2, devolver V0 legacy
        return calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga, pais=liga)

    if conn is None or fecha is None or ht is None or at is None or es_local is None:
        return calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga, pais=liga)

    # Lookup SOFA xg_shotmap usando matching robusto (norm_team_name + fechas ±2 + fuzzy)
    sofa_xg = None
    try:
        # Importar lazily para evitar circular imports
        from analisis.aliases_sofa_espn import norm_team_name
        from datetime import datetime, timedelta
        cur = conn.cursor()
        ht_n = norm_team_name(ht, liga)
        at_n = norm_team_name(at, liga)

        # Buscar SOFA partidos del mismo liga + fecha ±2 días
        try:
            d0 = datetime.fromisoformat(fecha).date()
            fechas_alt = [(d0 + timedelta(days=delta)).isoformat() for delta in (0, -1, 1, -2, 2)]
        except (ValueError, TypeError):
            fechas_alt = [fecha]

        # V3 (2026-05-04): preferir xg_v3 (xgot SOFA + custom fallback) sobre xg_shotmap (custom puro)
        # Mejora -16% RMSE global validated empirically (8 WIN / 5 TIE / 1 LOSS)
        for f in fechas_alt:
            rows = cur.execute('''
                SELECT ht, at, xg_v3_l, xg_v3_v, xg_shotmap_l, xg_shotmap_v
                FROM sofascore_match_features
                WHERE liga=? AND fecha=? AND error IS NULL
                  AND (xg_v3_l IS NOT NULL OR xg_shotmap_l IS NOT NULL)
            ''', (liga, f)).fetchall()
            for sofa_ht, sofa_at, xg_v3_l, xg_v3_v, xg_sh_l, xg_sh_v in rows:
                if norm_team_name(sofa_ht, liga) == ht_n and norm_team_name(sofa_at, liga) == at_n:
                    if es_local:
                        sofa_xg = xg_v3_l if xg_v3_l is not None else xg_sh_l
                    else:
                        sofa_xg = xg_v3_v if xg_v3_v is not None else xg_sh_v
                    break
            if sofa_xg is not None:
                break

        # Fuzzy fallback si no match estricto
        if sofa_xg is None:
            from difflib import SequenceMatcher
            for f in fechas_alt:
                rows = cur.execute('''
                    SELECT ht, at, xg_v3_l, xg_v3_v, xg_shotmap_l, xg_shotmap_v
                    FROM sofascore_match_features
                    WHERE liga=? AND fecha=? AND error IS NULL
                      AND (xg_v3_l IS NOT NULL OR xg_shotmap_l IS NOT NULL)
                ''', (liga, f)).fetchall()
                best, best_sim = None, 0
                for sofa_ht, sofa_at, xg_v3_l, xg_v3_v, xg_sh_l, xg_sh_v in rows:
                    sim = (SequenceMatcher(None, ht_n, norm_team_name(sofa_ht, liga)).ratio()
                           + SequenceMatcher(None, at_n, norm_team_name(sofa_at, liga)).ratio()) / 2
                    if sim > best_sim:
                        best_sim = sim
                        if es_local:
                            best = xg_v3_l if xg_v3_l is not None else xg_sh_l
                        else:
                            best = xg_v3_v if xg_v3_v is not None else xg_sh_v
                if best is not None and best_sim >= 0.75:
                    sofa_xg = best
                    break
    except Exception:
        sofa_xg = None

    # V0 legacy
    xg_v0 = calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga, pais=liga)

    if sofa_xg is None:
        # SOFA no disponible → fallback V0
        return xg_v0

    # Aplicar α blend per liga
    alpha = get_param('alpha_xg_v2_hibrido_sofa', scope=liga, default=0.30)
    # SOFA es xg_calc puro (sin híbrido goles_reales). V0 ya tiene 0.70/0.30 incorporado.
    # Para coherencia, aplicar mismo blend 0.70/0.30 al sofa también:
    sofa_final = (sofa_xg * 0.70) + (goles_reales * 0.30)
    xg_v2 = alpha * sofa_final + (1.0 - alpha) * xg_v0
    return round(xg_v2, 3)


def calcular_xg_v6(estadisticas, goles_reales, liga=None, conn=None):
    """[SHADOW V6 — adepor-d7h] xG recalibrado con coeficientes OLS empíricos.

    Audit 2026-04-26 detectó 3 errores estructurales en la fórmula original:
      1. β_shots_off positivo en código (+0.010) vs negativo empírico (~-0.027)
      2. coef_corner positivo en código (+0.02) vs negativo empírico (~-0.055)
      3. Intercept ausente (asume 0) vs OLS estima ~+0.46 goles baseline

    Coefs leídos desde config_motor_valores con clave *_v6_shadow.
    Lookup: scope=liga primero, fallback scope=global (pool 10 ligas).
    Fuente: OLS_2026-04-26_adepor-d7h sobre N=24,164 obs partidos_historico_externo.

    Híbrido 0.70/0.30 se mantiene por consistencia con V0..V5 (re-EMA dual).
    NO afecta producción — uso exclusivo en backfill_xg_v6_shadow + motor_calculadora SHADOW.
    """
    goles_reales = safe_float(goles_reales)
    if not estadisticas:
        return goles_reales

    sot, corners, total_shots = 0, 0, 0
    for stat in estadisticas:
        nombre = stat.get('name', '')
        valor = safe_int(stat.get('displayValue'))
        if nombre == 'shotsOnTarget':
            sot = valor
        elif nombre == 'wonCorners':
            corners = valor
        elif nombre == 'totalShots':
            total_shots = valor

    shots_off = max(0, total_shots - sot)

    # Lookup de coeficientes: liga > global
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    def _coef(clave, scope_liga):
        # Intenta scope=liga, fallback scope=global
        row = cur.execute(
            "SELECT valor_real FROM config_motor_valores WHERE clave=? AND scope=?",
            (clave, scope_liga or '__none__')
        ).fetchone()
        if row is not None and row[0] is not None:
            return float(row[0])
        row = cur.execute(
            "SELECT valor_real FROM config_motor_valores WHERE clave=? AND scope='global'",
            (clave,)
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    beta_sot = _coef('beta_sot_v6_shadow', liga)
    beta_off = _coef('beta_off_v6_shadow', liga)
    coef_corner = _coef('coef_corner_v6_shadow', liga)
    intercept = _coef('intercept_v6_shadow', liga)

    if own_conn:
        conn.close()

    if any(v is None for v in (beta_sot, beta_off, coef_corner, intercept)):
        # Coefs no persistidos -> caer al híbrido legacy
        return calcular_xg_hibrido(estadisticas, goles_reales, pais=liga)

    xg_calc = (sot * beta_sot) + (shots_off * beta_off) + (corners * coef_corner) + intercept
    # Floor: OLS puede dar negativo si stats=0 e intercept bajo. Forzamos >=0 para Poisson.
    xg_calc = max(0.0, xg_calc)

    if xg_calc == 0 and goles_reales > 0:
        return goles_reales

    xg_final = (xg_calc * 0.70) + (goles_reales * 0.30)
    return round(xg_final, 3)


def ajustar_xg_por_estado_juego(xg_crudo, goles_a_favor, goles_en_contra):
    """
    Aplica un ajuste heurístico al xG basado en el resultado final para simular
    el impacto de los 'score effects' en un modelo sin datos intra-partido.
    """
    try:
        g_favor = int(goles_a_favor)
        g_contra = int(goles_en_contra)
    except (ValueError, TypeError):
        return xg_crudo

    diferencia_goles = g_favor - g_contra
    
    if diferencia_goles > 0:
        # El equipo ganó. Se asume que jugó de forma más conservadora.
        factor_ajuste = 1.0 + 0.08 * math.log(1 + diferencia_goles)
        return xg_crudo * min(factor_ajuste, 1.20)
    elif diferencia_goles < 0:
        # El equipo perdió. Se asume que tomó más riesgos de los habituales.
        factor_ajuste = 1.0 - 0.05 * math.log(1 + abs(diferencia_goles))
        return xg_crudo * max(factor_ajuste, 0.80)
    else:
        # Empate, se asume estado neutral.
        return xg_crudo

def main():
    # --- FLAG --rebuild ---
    # Uso: py motor_data.py --rebuild
    # Efecto: borra el historial EMA (ema_procesados, historial_equipos, ligas_stats)
    # y re-procesa desde PROFUNDIDAD_INICIAL. Util cuando se cambia el modelo de xG
    # o la logica EMA y se quiere recalibrar desde cero.
    # ADVERTENCIA: operacion destructiva e irreversible. Requiere confirmacion manual.
    modo_rebuild = '--rebuild' in sys.argv
    if modo_rebuild:
        print("[REBUILD] *** MODO RECONSTRUCCION SOLICITADO ***")
        print("[REBUILD] Se borrarán TODAS las tablas EMA:")
        print("          - ema_procesados  (historial de partidos procesados)")
        print("          - historial_equipos (EMA de todos los equipos)")
        print("          - ligas_stats       (estadísticas de liga: RHO, coef_corner, etc.)")
        print("[REBUILD] El sistema re-procesará desde PROFUNDIDAD_INICIAL (210 dias).")
        # Bypass para ejecucion no interactiva (fase3 rebuild shadow): env var REBUILD_YES=1
        if os.environ.get('REBUILD_YES') == '1':
            print("[REBUILD] REBUILD_YES=1 detectado — auto-confirmado (no interactivo).")
            confirmacion = "CONFIRMAR"
        else:
            confirmacion = input("[REBUILD] Escribe CONFIRMAR para continuar, o cualquier otra cosa para cancelar: ").strip()
        if confirmacion != "CONFIRMAR":
            print("[REBUILD] Cancelado. No se ha modificado ningún dato.")
            return
        print("[REBUILD] Confirmado. Iniciando limpieza...")

    print("[SISTEMA] Iniciando Motor Data V9.1 (Regresión Bayesiana Integrada)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_equipos (
            equipo_norm TEXT NOT NULL, equipo_real TEXT, liga TEXT NOT NULL, ultima_actualizacion TEXT,
            ema_xg_favor_home REAL DEFAULT 1.4, ema_xg_contra_home REAL DEFAULT 1.4,
            ema_xg_favor_away REAL DEFAULT 1.4, ema_xg_contra_away REAL DEFAULT 1.4,
            partidos_home INTEGER DEFAULT 0, partidos_away INTEGER DEFAULT 0,
            ema_var_favor_home REAL DEFAULT 0.1, ema_var_contra_home REAL DEFAULT 0.1,
            ema_var_favor_away REAL DEFAULT 0.1, ema_var_contra_away REAL DEFAULT 0.1,
            PRIMARY KEY (equipo_norm, liga)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ligas_stats (
            liga TEXT PRIMARY KEY,
            total_partidos INTEGER DEFAULT 0,
            empates INTEGER DEFAULT 0,
            rho_calculado REAL DEFAULT -0.04,
            total_goles INTEGER DEFAULT 0,
            total_corners INTEGER DEFAULT 0,
            coef_corner_calculado REAL DEFAULT 0.02
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ema_procesados (id_partido TEXT PRIMARY KEY)
    """)

    # Migración: columnas de estadísticas brutas en partidos_backtest para calibración OLS futura de xG
    # Estas columnas permiten calibrar los coeficientes de calcular_xg_hibrido por regresión directa
    for col_def in ['sot_l INTEGER', 'shots_l INTEGER', 'corners_l INTEGER',
                    'sot_v INTEGER', 'shots_v INTEGER', 'corners_v INTEGER']:
        try:
            cursor.execute(f"ALTER TABLE partidos_backtest ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # La columna ya existe — operación idempotente

    # Ejecucion del REBUILD: borrar datos EMA para forzar re-procesamiento completo
    if modo_rebuild:
        cursor.execute("DELETE FROM ema_procesados")
        cursor.execute("DELETE FROM historial_equipos")
        cursor.execute("DELETE FROM ligas_stats")
        conn.commit()
        n_proc = cursor.rowcount  # rowcount del ultimo DELETE
        print(f"[REBUILD] Tablas vaciadas. El sistema reclasificara todas las ligas a PROFUNDIDAD_INICIAL.")

    cursor.execute("""SELECT equipo_norm, equipo_real, liga,
                              ema_xg_favor_home, ema_xg_contra_home, partidos_home,
                              ema_xg_favor_away, ema_xg_contra_away, partidos_away,
                              ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away,
                              ema_corto_favor_home, ema_corto_contra_home, partidos_corto_home,
                              ema_corto_favor_away, ema_corto_contra_away, partidos_corto_away
                       FROM historial_equipos""")
    # Key: (equipo_norm, liga) — permite que el mismo equipo_norm coexista en varias ligas (Everton Chile/Inglaterra, etc.).
    # SHADOW EMA dual (2026-04-26): columnas ema_corto_* persisten EMA con alfa=2*alfa_largo (capped 0.50), sin Bayesian shrinkage.
    estado_equipos = {(row[0], row[2]): {
        "nombre": row[1], "liga": row[2],
        "fav_home": row[3], "con_home": row[4], "p_home": row[5],
        "fav_away": row[6], "con_away": row[7], "p_away": row[8],
        "var_fh": row[9] or 0.1, "var_ch": row[10] or 0.1, "var_fa": row[11] or 0.1, "var_ca": row[12] or 0.1,
        "fav_corto_home": row[13] if row[13] is not None else 1.4,
        "con_corto_home": row[14] if row[14] is not None else 1.4,
        "p_corto_home":   row[15] if row[15] is not None else 0,
        "fav_corto_away": row[16] if row[16] is not None else 1.4,
        "con_corto_away": row[17] if row[17] is not None else 1.4,
        "p_corto_away":   row[18] if row[18] is not None else 0,
    } for row in cursor.fetchall()}
    
    cursor.execute("SELECT liga, total_partidos, empates, rho_calculado, total_goles, total_corners, coef_corner_calculado FROM ligas_stats")
    estado_ligas = {row[0]: {"total": row[1], "empates": row[2], "rho": row[3], "goles": row[4], "corners": row[5], "coef_c": row[6]} for row in cursor.fetchall()}
    
    cursor.execute("SELECT id_partido FROM ema_procesados")
    procesados = {row[0] for row in cursor.fetchall()}
    
    hoy = datetime.now()
    partidos_procesados_sesion = 0
    nuevos_partidos_procesados = []
    equipos_actualizados = set()
    equipos_nuevos_sesion = set()

    def actualizar_estado(eq_oficial, pais, xg_f, xg_c, is_home, promedio_liga, equipos_nuevos):
        """Aplica EMA y Regresión Bayesiana para actualizar el poderío del equipo.
        Clave compuesta (eq_norm, pais): el mismo equipo_norm puede existir en distintas ligas."""
        alfa = get_param('alfa_ema', scope=pais, default=ALFA_EMA_POR_LIGA.get(pais, ALFA_EMA))  # Fix #3 (V4.4): ALFA específico por liga
        eq_norm = gestor_nombres.limpiar_texto(eq_oficial)
        key = (eq_norm, pais)
        if key not in estado_equipos:
            equipos_nuevos.add(eq_oficial)
            estado_equipos[key] = {
                "nombre": eq_oficial, "liga": pais,
                "fav_home": 1.4, "con_home": 1.4, "p_home": 0,
                "fav_away": 1.4, "con_away": 1.4, "p_away": 0,
                "var_fh": 0.1, "var_ch": 0.1, "var_fa": 0.1, "var_ca": 0.1,
                "fav_corto_home": 1.4, "con_corto_home": 1.4, "p_corto_home": 0,
                "fav_corto_away": 1.4, "con_corto_away": 1.4, "p_corto_away": 0,
            }
        if is_home:
            viejo_fav = estado_equipos[key]["fav_home"]
            viejo_con = estado_equipos[key]["con_home"]
            error_fav = xg_f - viejo_fav
            error_con = xg_c - viejo_con
            vieja_var_fav = estado_equipos[key]["var_fh"]
            vieja_var_con = estado_equipos[key]["var_ch"]
            estado_equipos[key]["var_fh"] = (error_fav**2 * alfa) + (vieja_var_fav * (1 - alfa))
            estado_equipos[key]["var_ch"] = (error_con**2 * alfa) + (vieja_var_con * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N_home  = estado_equipos[key]["p_home"]
            w_liga  = N0_ANCLA / (N0_ANCLA + N_home) if (N0_ANCLA + N_home) > 0 else 1.0
            w_ema   = 1.0 - w_liga
            estado_equipos[key]["fav_home"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            estado_equipos[key]["con_home"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            estado_equipos[key]["p_home"] += 1
        else:
            viejo_fav = estado_equipos[key]["fav_away"]
            viejo_con = estado_equipos[key]["con_away"]
            error_fav = xg_f - viejo_fav
            error_con = xg_c - viejo_con
            vieja_var_fav = estado_equipos[key]["var_fa"]
            vieja_var_con = estado_equipos[key]["var_ca"]
            estado_equipos[key]["var_fa"] = (error_fav**2 * alfa) + (vieja_var_fav * (1 - alfa))
            estado_equipos[key]["var_ca"] = (error_con**2 * alfa) + (vieja_var_con * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N_away  = estado_equipos[key]["p_away"]
            w_liga  = N0_ANCLA / (N0_ANCLA + N_away) if (N0_ANCLA + N_away) > 0 else 1.0
            w_ema   = 1.0 - w_liga
            estado_equipos[key]["fav_away"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            estado_equipos[key]["con_away"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            estado_equipos[key]["p_away"] += 1

        # --- SHADOW EMA dual (2026-04-26) ---
        # Calcula EMA corto en paralelo con alfa = min(2 * alfa_largo, 0.50).
        # SIN Bayesian shrinkage hacia promedio_liga: el corto refleja form crudo (decision Lead).
        # Shadow puro: NO afecta xG predicho, picks, stakes, ni constantes Manifiesto.
        alfa_corto = min(2 * alfa, 0.50)
        if is_home:
            viejo_fav_c = estado_equipos[key]["fav_corto_home"]
            viejo_con_c = estado_equipos[key]["con_corto_home"]
            estado_equipos[key]["fav_corto_home"] = round((xg_f * alfa_corto) + (viejo_fav_c * (1 - alfa_corto)), 3)
            estado_equipos[key]["con_corto_home"] = round((xg_c * alfa_corto) + (viejo_con_c * (1 - alfa_corto)), 3)
            estado_equipos[key]["p_corto_home"] += 1
        else:
            viejo_fav_c = estado_equipos[key]["fav_corto_away"]
            viejo_con_c = estado_equipos[key]["con_corto_away"]
            estado_equipos[key]["fav_corto_away"] = round((xg_f * alfa_corto) + (viejo_fav_c * (1 - alfa_corto)), 3)
            estado_equipos[key]["con_corto_away"] = round((xg_c * alfa_corto) + (viejo_con_c * (1 - alfa_corto)), 3)
            estado_equipos[key]["p_corto_away"] += 1
        equipos_actualizados.add(key)

    # --- FASE DE ANÁLISIS: AGRUPAR LIGAS POR NECESIDAD DE ESCANEO ---
    print("[ANALISIS] Agrupando ligas por profundidad de escaneo requerida...")
    UMBRAL_PARTIDOS_MINIMOS = 15   # V9.1: bajado de 20. Con 15 partidos el EMA ya es fiable
                                   # (w_ema=75% con N=15 y N0=5). Evita que Brasil quede en
                                   # PROFUNDA por equipos con 17-18 partidos bien calibrados.
    UMBRAL_RECIEN_ASCENDIDO = 10   # Equipos con <= este total se excluyen del cálculo de modo
    PROFUNDIDAD_INICIAL     = get_param('profundidad_inicial', default=365)  # Primera vez que aparece la liga en DB (F4: override por liga en loop)
    PROFUNDIDAD_PROFUNDA    = get_param('profundidad_profunda', default=210)  # Liga con muchos equipos por bajo umbral
    PROFUNDIDAD_MANTENIMIENTO = get_param('profundidad_mantenimiento', default=7)  # Liga consolidada: solo nuevos datos

    # Profundidad PROFUNDA por liga para ligas estacionales.
    # Noruega (Eliteserien): temporada Abril-Noviembre. Al comenzar el año siguiente,
    # la temporada anterior tiene >210 días de antigüedad y escapa al radar.
    # 365 días garantiza que el escaneo profundo capture el año completo anterior.
    PROFUNDIDAD_PROFUNDA_POR_LIGA = {
        "Noruega": 365,
    }

    # grupos_de_escaneo: clave = dias, valor = [(codigo_liga, pais)]
    # Usamos defaultdict para soportar profundidades variables por liga (ej. Noruega=365)
    grupos_de_escaneo = defaultdict(list)

    for codigo_liga, pais in LIGAS_ESPN.items():
        equipos_de_la_liga = {k: v for k, v in estado_equipos.items() if k[1] == pais}
        prof_profunda_liga = PROFUNDIDAD_PROFUNDA_POR_LIGA.get(pais, PROFUNDIDAD_PROFUNDA)

        if not equipos_de_la_liga:
            # F4 (D4): PROFUNDIDAD_INICIAL por liga via DB (fallback global)
            dias_a_escanear = get_param('profundidad_inicial', scope=pais, default=PROFUNDIDAD_INICIAL)
            print(f"   [GRUPO INICIAL] Liga '{pais}' necesita historial base ({dias_a_escanear} días).")
            grupos_de_escaneo[dias_a_escanear].append((codigo_liga, pais))
        else:
            # Excluir equipos recien ascendidos del calculo: si tienen muy pocos partidos
            # es porque no habia datos ESPN de la division anterior. No deben arrastrar
            # a toda la liga al modo profundo cuando el resto ya esta consolidado.
            equipos_establecidos = {k: v for k, v in equipos_de_la_liga.items()
                                    if (v.get('p_home', 0) + v.get('p_away', 0)) > UMBRAL_RECIEN_ASCENDIDO}
            recien_ascendidos = len(equipos_de_la_liga) - len(equipos_establecidos)

            if not equipos_establecidos:
                dias_a_escanear = prof_profunda_liga
                print(f"   [GRUPO PROFUNDO] Liga '{pais}' sin equipos establecidos ({dias_a_escanear} días).")
                grupos_de_escaneo[dias_a_escanear].append((codigo_liga, pais))
            else:
                equipos_con_pocos_datos = [v for v in equipos_establecidos.values()
                                           if (v.get('p_home', 0) + v.get('p_away', 0)) < UMBRAL_PARTIDOS_MINIMOS]
                porcentaje_pocos_datos = len(equipos_con_pocos_datos) / len(equipos_establecidos)

                if porcentaje_pocos_datos > 0.15:
                    dias_a_escanear = prof_profunda_liga
                    print(f"   [GRUPO PROFUNDO] Liga '{pais}' necesita re-calibración ({dias_a_escanear} días) "
                          f"({porcentaje_pocos_datos:.0%} establecidos con pocos datos, {recien_ascendidos} ascendidos excluidos).")
                    grupos_de_escaneo[dias_a_escanear].append((codigo_liga, pais))
                else:
                    dias_a_escanear = PROFUNDIDAD_MANTENIMIENTO
                    print(f"   [GRUPO MANTENIMIENTO] Liga '{pais}' está consolidada ({dias_a_escanear} días)"
                          f"{f', {recien_ascendidos} ascendidos excluidos del calculo' if recien_ascendidos else ''}.")
                    grupos_de_escaneo[dias_a_escanear].append((codigo_liga, pais))

    # --- FASE DE EJECUCIÓN: PROCESAR CADA GRUPO DE ESCANEO ---
    # OPTIMIZACION (fase3, 2026-04-20): Session HTTP + ThreadPoolExecutor(max_workers=6)
    # Reutiliza conexion TCP/TLS (gana ~30-50%) + paralela ligas dentro de cada fecha (gana ~5x).
    # Ganancia total esperada: ~6-8x vs loop secuencial con requests.get() individual.
    session = requests.Session()
    session.headers.update({'User-Agent': 'adepor/1.0', 'Accept': 'application/json'})

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for dias_a_escanear, ligas_en_grupo in grupos_de_escaneo.items():
            if not ligas_en_grupo:
                continue

            nombres_ligas = [pais for _, pais in ligas_en_grupo]
            print(f"\n[PROCESO] Iniciando escaneo de {dias_a_escanear} días para el grupo: {nombres_ligas}.")

            # --- BUCLE DE DÍAS ---
            for i in range(dias_a_escanear, -1, -1):
                fecha_obj = hoy - timedelta(days=i)
                fecha_api = fecha_a_espn(fecha_obj)

                # FASE 1: Lanzar requests de las 12 ligas en paralelo (pool=6)
                futures = {}
                for codigo_liga, pais in ligas_en_grupo:
                    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
                    fut = executor.submit(_fetch_espn_json, session, url, pais, fecha_api)
                    futures[fut] = (codigo_liga, pais)

                # FASE 2: Procesar respuestas SECUENCIAL en main thread (DB-safe)
                for fut in concurrent.futures.as_completed(futures):
                    codigo_liga, pais = futures[fut]
                    data = fut.result()
                    if data is None:
                        continue
                    print(f"   [PROCESO] {pais} para la fecha {fecha_api} ({len(data.get('events', []))} eventos)")

                    for evento in data.get('events', []):
                        try:
                            tipo_estado = evento.get('status', {}).get('type', {})
                            if not tipo_estado.get('completed', False) and tipo_estado.get('name', '') not in ESTADOS_ESPN_FINALIZADO: continue
                            
                            competidores = evento['competitions'][0]['competitors']
                        
                            loc = next(c for c in competidores if c['homeAway'] == 'home')
                            vis = next(c for c in competidores if c['homeAway'] == 'away')
                        
                            loc_crudo = loc['team']['displayName']
                            vis_crudo = vis['team']['displayName']
                        
                            loc_oficial = gestor_nombres.obtener_nombre_estandar(loc_crudo, liga=pais, modo_interactivo=False)
                            vis_oficial = gestor_nombres.obtener_nombre_estandar(vis_crudo, liga=pais, modo_interactivo=False)
                        
                            fecha_iso = fecha_obj.strftime('%Y-%m-%d')
                            id_unico = f"{fecha_iso}{gestor_nombres.limpiar_texto(loc_oficial)}{gestor_nombres.limpiar_texto(vis_oficial)}"

                            if id_unico in procesados: continue

                            goles_loc = safe_int(loc.get('score', 0))
                            goles_vis = safe_int(vis.get('score', 0))

                            if pais not in estado_ligas:
                                estado_ligas[pais] = {"total": 0, "empates": 0, "rho": -0.04, "goles": 0, "corners": 0, "coef_c": 0.02}

                            coef_corner_actual = estado_ligas[pais].get('coef_c', 0.02)
                            stats_loc = loc.get('statistics', [])
                            stats_vis = vis.get('statistics', [])

                            # P4 fase3: pasar pais para que lea beta_sot por liga
                            # V2 hybrid SOFA (bead adepor-atn, MANIFESTO-CHANGE-APPROVED:adepor-atn)
                            # Si modo='active' y SOFA disponible -> V2 hybrid; sino fallback V0.
                            xg_loc_crudo = calcular_xg_v2_hibrido_sofa(
                                stats_loc, goles_loc, liga=pais,
                                coef_corner_liga=coef_corner_actual, conn=conn,
                                fecha=fecha_iso, ht=loc_oficial, at=vis_oficial, es_local=True
                            )
                            xg_vis_crudo = calcular_xg_v2_hibrido_sofa(
                                stats_vis, goles_vis, liga=pais,
                                coef_corner_liga=coef_corner_actual, conn=conn,
                                fecha=fecha_iso, ht=loc_oficial, at=vis_oficial, es_local=False
                            )

                            xg_loc = ajustar_xg_por_estado_juego(xg_loc_crudo, goles_loc, goles_vis)
                            xg_vis = ajustar_xg_por_estado_juego(xg_vis_crudo, goles_vis, goles_loc)
                        
                            promedio_goles_liga = (estado_ligas[pais]["goles"] / estado_ligas[pais]["total"]) if estado_ligas[pais]["total"] > 0 else 1.4

                            actualizar_estado(loc_oficial, pais, xg_loc, xg_vis, is_home=True, promedio_liga=promedio_goles_liga, equipos_nuevos=equipos_nuevos_sesion)
                            actualizar_estado(vis_oficial, pais, xg_vis, xg_loc, is_home=False, promedio_liga=promedio_goles_liga, equipos_nuevos=equipos_nuevos_sesion)

                            nuevos_partidos_procesados.append((id_unico,))
                            partidos_procesados_sesion += 1

                            estado_ligas[pais]["total"] += 1
                            estado_ligas[pais]["goles"] += goles_loc + goles_vis
                            if goles_loc == goles_vis:
                                estado_ligas[pais]["empates"] += 1

                            corners_loc = next((safe_int(s.get('displayValue')) for s in stats_loc if s.get('name') == 'wonCorners'), 0)  # B2 fase3
                            corners_vis = next((safe_int(s.get('displayValue')) for s in stats_vis if s.get('name') == 'wonCorners'), 0)  # B2 fase3
                            estado_ligas[pais]["corners"] += corners_loc + corners_vis

                            # Persistir estadísticas brutas para calibración OLS futura de xG
                            sot_loc, shots_loc, _ = extraer_stats_raw(stats_loc)
                            sot_vis, shots_vis, _ = extraer_stats_raw(stats_vis)

                            # SOFA-primary override: para ligas en LIGAS_SOFA_PRIMARY
                            # (e.g. DEN/BEL/GRE sin statistics[] ESPN) preferir stats SOFA.
                            # Fresh same-day events: MISS (SOFA aún no scrapeado), fallback ESPN.
                            # Día 2+: HIT. Scaffolding inactivo hasta onboarding (LIGAS_ESPN
                            # no contiene aún las 7 ligas EU expansión).
                            stats_sofa = lookup_stats_sofa_primario(conn, pais, fecha_iso, loc_oficial, vis_oficial)
                            if stats_sofa is not None:
                                sot_loc, shots_loc, corners_loc = stats_sofa['sot_l'], stats_sofa['shots_l'], stats_sofa['corners_l']
                                sot_vis, shots_vis, corners_vis = stats_sofa['sot_v'], stats_sofa['shots_v'], stats_sofa['corners_v']

                            cursor.execute(
                                "UPDATE partidos_backtest SET sot_l=?, shots_l=?, corners_l=?, sot_v=?, shots_v=?, corners_v=? WHERE id_partido=?",
                                (sot_loc, shots_loc, corners_loc, sot_vis, shots_vis, corners_vis, id_unico)
                            )

                            stats_liga_actual = estado_ligas[pais]
                            if stats_liga_actual["total"] > 20:
                                draw_ratio = stats_liga_actual["empates"] / stats_liga_actual["total"]
                                stats_liga_actual['rho'] = round(-0.04 + (draw_ratio - 0.25) * -0.2, 4)

                            ESQUINAS_POR_GOL_GLOBAL = 4.0
                            if stats_liga_actual["goles"] > 50 and stats_liga_actual["corners"] > 0:
                                esquinas_por_gol_liga = stats_liga_actual["corners"] / stats_liga_actual["goles"]
                                ajuste = ESQUINAS_POR_GOL_GLOBAL / esquinas_por_gol_liga
                                stats_liga_actual['coef_c'] = round(0.02 * ajuste, 4)
                        except Exception as e:
                            loc_desc = evento.get('competitions', [{}])[0].get('competitors', [{}])[0].get('team', {}).get('displayName', '?')
                            vis_desc = evento.get('competitions', [{}])[0].get('competitors', [{}])[-1].get('team', {}).get('displayName', '?') if len(evento.get('competitions', [{}])[0].get('competitors', [])) > 1 else '?'
                            print(f"   [ERROR] {pais} {fecha_api} | {loc_desc} vs {vis_desc} | {type(e).__name__}: {e}")
                            continue

    if equipos_actualizados:
        for key in equipos_actualizados:
            eq_norm, liga_key = key
            dt = estado_equipos[key]
            cursor.execute("""
                INSERT INTO historial_equipos (equipo_norm, equipo_real, liga, ultima_actualizacion,
                                             ema_xg_favor_home, ema_xg_contra_home, partidos_home,
                                             ema_xg_favor_away, ema_xg_contra_away, partidos_away,
                                             ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away,
                                             ema_corto_favor_home, ema_corto_contra_home, partidos_corto_home,
                                             ema_corto_favor_away, ema_corto_contra_away, partidos_corto_away)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(equipo_norm, liga) DO UPDATE SET
                    equipo_real=excluded.equipo_real, ultima_actualizacion=excluded.ultima_actualizacion,
                    ema_xg_favor_home=excluded.ema_xg_favor_home,
                    ema_xg_contra_home=excluded.ema_xg_contra_home,
                    partidos_home=excluded.partidos_home,
                    ema_xg_favor_away=excluded.ema_xg_favor_away,
                    ema_xg_contra_away=excluded.ema_xg_contra_away,
                    partidos_away=excluded.partidos_away,
                    ema_var_favor_home=excluded.ema_var_favor_home,
                    ema_var_contra_home=excluded.ema_var_contra_home,
                    ema_var_favor_away=excluded.ema_var_favor_away,
                    ema_var_contra_away=excluded.ema_var_contra_away,
                    ema_corto_favor_home=excluded.ema_corto_favor_home,
                    ema_corto_contra_home=excluded.ema_corto_contra_home,
                    partidos_corto_home=excluded.partidos_corto_home,
                    ema_corto_favor_away=excluded.ema_corto_favor_away,
                    ema_corto_contra_away=excluded.ema_corto_contra_away,
                    partidos_corto_away=excluded.partidos_corto_away
            """, (eq_norm, dt["nombre"], dt["liga"], hoy.strftime("%Y-%m-%d"),
                  dt["fav_home"], dt["con_home"], dt["p_home"],
                  dt["fav_away"], dt["con_away"], dt["p_away"],
                  dt["var_fh"], dt["var_ch"], dt["var_fa"], dt["var_ca"],
                  dt["fav_corto_home"], dt["con_corto_home"], dt["p_corto_home"],
                  dt["fav_corto_away"], dt["con_corto_away"], dt["p_corto_away"]))
        
        for liga, stats in estado_ligas.items():
            # FIX: Se leen los valores ya calculados en memoria, en lugar de recalcularlos.
            total = stats.get("total", 0)
            empates = stats.get("empates", 0)
            total_goles = stats.get("goles", 0)
            total_corners = stats.get("corners", 0)
            rho = stats.get("rho", -0.04)
            coef_corner = stats.get("coef_c", 0.02)

            cursor.execute("""
                INSERT INTO ligas_stats (liga, total_partidos, empates, rho_calculado, total_goles, total_corners, coef_corner_calculado) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(liga) DO UPDATE SET total_partidos=excluded.total_partidos, empates=excluded.empates, rho_calculado=excluded.rho_calculado,
                                                total_goles=excluded.total_goles, total_corners=excluded.total_corners, coef_corner_calculado=excluded.coef_corner_calculado
            """, (liga, total, empates, rho, total_goles, total_corners, coef_corner))

        if nuevos_partidos_procesados:
            cursor.executemany("INSERT OR IGNORE INTO ema_procesados (id_partido) VALUES (?)", nuevos_partidos_procesados)

        conn.commit()
        print(f"[EXITO] Proceso finalizado. {partidos_procesados_sesion} partidos nuevos han sido asimilados en la memoria de los equipos.")

    if equipos_nuevos_sesion:
        print("\n[INFO] Se ha calculado el EMA por primera vez para los siguientes equipos:")
        for equipo in sorted(list(equipos_nuevos_sesion)):
            print(f"   - {equipo}")

    conn.close()

if __name__ == "__main__":
    main()
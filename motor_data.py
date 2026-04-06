import sqlite3
import requests
import gestor_nombres
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# ==========================================
# MOTOR DATA V9.1 (REGRESIÓN BAYESIANA INTEGRADA + --rebuild)
# Responsabilidad: Ajuste de xG, cálculo de EMA y anclaje a la media.
# ==========================================

DB_NAME = 'fondo_quant.db'
ALFA_EMA  = 0.15  # Fallback global si la liga no tiene ALFA propio
N0_ANCLA  = 5    # Fix #1 (V4.4): ancla Bayesiana N-dependiente. N=0 -> 100% liga; N=5 -> 50/50; N=20 -> 80/20.

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
}

LIGAS_ESPN = {
    "arg.1": "Argentina", "eng.1": "Inglaterra", 
    "bra.1": "Brasil", "nor.1": "Noruega", "tur.1": "Turquia"
}

def safe_int(val):
    try: return int(val)
    except: return 0

def safe_float(val):
    try: return float(val)
    except: return 0.0

def calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga=0.03):
    """
    Calcula los Goles Esperados (xG) a partir de estadísticas a nivel de partido.
    Este modelo descompone los tiros en 'en el arco' y 'fuera/bloqueado' para una
    valoración más precisa, y se basa en coeficientes derivados de la literatura
    pública de análisis de fútbol.
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
        elif nombre == 'cornerKicks':
            corners = valor
        elif nombre == 'shots':
            total_shots = valor

    shots_off_target_or_blocked = max(0, total_shots - sot)
    xg_calc = (sot * 0.30) + (shots_off_target_or_blocked * 0.04) + (corners * coef_corner_liga)
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
            equipo_norm TEXT PRIMARY KEY, equipo_real TEXT, liga TEXT, ultima_actualizacion TEXT,
            ema_xg_favor_home REAL DEFAULT 1.4, ema_xg_contra_home REAL DEFAULT 1.4,
            ema_xg_favor_away REAL DEFAULT 1.4, ema_xg_contra_away REAL DEFAULT 1.4,
            partidos_home INTEGER DEFAULT 0, partidos_away INTEGER DEFAULT 0,
            ema_var_favor_home REAL DEFAULT 0.1, ema_var_contra_home REAL DEFAULT 0.1,
            ema_var_favor_away REAL DEFAULT 0.1, ema_var_contra_away REAL DEFAULT 0.1
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

    # Ejecucion del REBUILD: borrar datos EMA para forzar re-procesamiento completo
    if modo_rebuild:
        cursor.execute("DELETE FROM ema_procesados")
        cursor.execute("DELETE FROM historial_equipos")
        cursor.execute("DELETE FROM ligas_stats")
        conn.commit()
        n_proc = cursor.rowcount  # rowcount del ultimo DELETE
        print(f"[REBUILD] Tablas vaciadas. El sistema reclasificara todas las ligas a PROFUNDIDAD_INICIAL.")

    cursor.execute("SELECT equipo_norm, equipo_real, liga, ema_xg_favor_home, ema_xg_contra_home, partidos_home, ema_xg_favor_away, ema_xg_contra_away, partidos_away, ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away FROM historial_equipos")
    estado_equipos = {row[0]: {"nombre": row[1], "liga": row[2], "fav_home": row[3], "con_home": row[4], "p_home": row[5], "fav_away": row[6], "con_away": row[7], "p_away": row[8], "var_fh": row[9] or 0.1, "var_ch": row[10] or 0.1, "var_fa": row[11] or 0.1, "var_ca": row[12] or 0.1} for row in cursor.fetchall()}
    
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
        """Aplica EMA y Regresión Bayesiana para actualizar el poderío del equipo."""
        alfa = ALFA_EMA_POR_LIGA.get(pais, ALFA_EMA)  # Fix #3 (V4.4): ALFA específico por liga
        eq_norm = gestor_nombres.limpiar_texto(eq_oficial)
        if eq_norm not in estado_equipos:
            equipos_nuevos.add(eq_oficial)
            estado_equipos[eq_norm] = {
                "nombre": eq_oficial, "liga": pais,
                "fav_home": 1.4, "con_home": 1.4, "p_home": 0,
                "fav_away": 1.4, "con_away": 1.4, "p_away": 0,
                "var_fh": 0.1, "var_ch": 0.1, "var_fa": 0.1, "var_ca": 0.1
            }
        if is_home:
            viejo_fav = estado_equipos[eq_norm]["fav_home"]
            viejo_con = estado_equipos[eq_norm]["con_home"]
            error_fav = xg_f - viejo_fav
            error_con = xg_c - viejo_con
            vieja_var_fav = estado_equipos[eq_norm]["var_fh"]
            vieja_var_con = estado_equipos[eq_norm]["var_ch"]
            estado_equipos[eq_norm]["var_fh"] = (error_fav**2 * alfa) + (vieja_var_fav * (1 - alfa))
            estado_equipos[eq_norm]["var_ch"] = (error_con**2 * alfa) + (vieja_var_con * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N_home  = estado_equipos[eq_norm]["p_home"]
            w_liga  = N0_ANCLA / (N0_ANCLA + N_home) if (N0_ANCLA + N_home) > 0 else 1.0
            w_ema   = 1.0 - w_liga
            estado_equipos[eq_norm]["fav_home"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            estado_equipos[eq_norm]["con_home"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            estado_equipos[eq_norm]["p_home"] += 1
        else:
            viejo_fav = estado_equipos[eq_norm]["fav_away"]
            viejo_con = estado_equipos[eq_norm]["con_away"]
            error_fav = xg_f - viejo_fav
            error_con = xg_c - viejo_con
            vieja_var_fav = estado_equipos[eq_norm]["var_fa"]
            vieja_var_con = estado_equipos[eq_norm]["var_ca"]
            estado_equipos[eq_norm]["var_fa"] = (error_fav**2 * alfa) + (vieja_var_fav * (1 - alfa))
            estado_equipos[eq_norm]["var_ca"] = (error_con**2 * alfa) + (vieja_var_con * (1 - alfa))
            nuevo_ema_fav = (xg_f * alfa) + (viejo_fav * (1 - alfa))
            nuevo_ema_con = (xg_c * alfa) + (viejo_con * (1 - alfa))
            N_away  = estado_equipos[eq_norm]["p_away"]
            w_liga  = N0_ANCLA / (N0_ANCLA + N_away) if (N0_ANCLA + N_away) > 0 else 1.0
            w_ema   = 1.0 - w_liga
            estado_equipos[eq_norm]["fav_away"] = round((w_ema * nuevo_ema_fav) + (w_liga * promedio_liga), 3)
            estado_equipos[eq_norm]["con_away"] = round((w_ema * nuevo_ema_con) + (w_liga * promedio_liga), 3)
            estado_equipos[eq_norm]["p_away"] += 1
        equipos_actualizados.add(eq_norm)

    # --- FASE DE ANÁLISIS: AGRUPAR LIGAS POR NECESIDAD DE ESCANEO ---
    print("[ANALISIS] Agrupando ligas por profundidad de escaneo requerida...")
    UMBRAL_PARTIDOS_MINIMOS = 15   # V9.1: bajado de 20. Con 15 partidos el EMA ya es fiable
                                   # (w_ema=75% con N=15 y N0=5). Evita que Brasil quede en
                                   # PROFUNDA por equipos con 17-18 partidos bien calibrados.
    UMBRAL_RECIEN_ASCENDIDO = 10   # Equipos con <= este total se excluyen del cálculo de modo
    PROFUNDIDAD_INICIAL     = 365  # Primera vez que aparece la liga en DB
    PROFUNDIDAD_PROFUNDA    = 140  # Liga con muchos equipos por bajo umbral
    PROFUNDIDAD_MANTENIMIENTO = 7  # Liga consolidada: solo nuevos datos

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
        equipos_de_la_liga = {k: v for k, v in estado_equipos.items() if v.get('liga') == pais}
        prof_profunda_liga = PROFUNDIDAD_PROFUNDA_POR_LIGA.get(pais, PROFUNDIDAD_PROFUNDA)

        if not equipos_de_la_liga:
            dias_a_escanear = PROFUNDIDAD_INICIAL
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
    for dias_a_escanear, ligas_en_grupo in grupos_de_escaneo.items():
        if not ligas_en_grupo:
            continue

        nombres_ligas = [pais for _, pais in ligas_en_grupo]
        print(f"\n[PROCESO] Iniciando escaneo de {dias_a_escanear} días para el grupo: {nombres_ligas}.")
        
        # --- BUCLE DE DÍAS ---
        for i in range(dias_a_escanear, -1, -1):
            fecha_obj = hoy - timedelta(days=i)
            fecha_api = fecha_obj.strftime('%Y%m%d')
            
            # --- BUCLE DE LIGAS (DENTRO DEL GRUPO) ---
            for codigo_liga, pais in ligas_en_grupo:
                print(f"   [PROCESO] Escaneando {pais} para la fecha {fecha_api}...")
                url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code != 200: continue
                
                    for evento in resp.json().get('events', []):
                        try:
                            tipo_estado = evento.get('status', {}).get('type', {})
                            if not tipo_estado.get('completed', False) and tipo_estado.get('name', '') not in ['STATUS_FINAL', 'STATUS_FULL_TIME']: continue 
                            
                            competidores = evento['competitions'][0]['competitors']
                        
                            loc = next(c for c in competidores if c['homeAway'] == 'home')
                            vis = next(c for c in competidores if c['homeAway'] == 'away')
                        
                            loc_crudo = loc['team']['displayName']
                            vis_crudo = vis['team']['displayName']
                        
                            loc_oficial = gestor_nombres.obtener_nombre_estandar(loc_crudo, modo_interactivo=False)
                            vis_oficial = gestor_nombres.obtener_nombre_estandar(vis_crudo, modo_interactivo=False)
                        
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

                            xg_loc_crudo = calcular_xg_hibrido(stats_loc, goles_loc, coef_corner_actual)
                            xg_vis_crudo = calcular_xg_hibrido(stats_vis, goles_vis, coef_corner_actual)

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

                            corners_loc = next((safe_int(s.get('displayValue')) for s in stats_loc if s.get('name') == 'cornerKicks'), 0)
                            corners_vis = next((safe_int(s.get('displayValue')) for s in stats_vis if s.get('name') == 'cornerKicks'), 0)
                            estado_ligas[pais]["corners"] += corners_loc + corners_vis

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
                except requests.exceptions.RequestException as e:
                    print(f"   [RED] Fallo de red en {pais} {fecha_api}: {e}")

    if equipos_actualizados:
        for eq_norm in equipos_actualizados:
            dt = estado_equipos[eq_norm]
            cursor.execute("""
                INSERT INTO historial_equipos (equipo_norm, equipo_real, liga, ultima_actualizacion,
                                             ema_xg_favor_home, ema_xg_contra_home, partidos_home,
                                             ema_xg_favor_away, ema_xg_contra_away, partidos_away,
                                             ema_var_favor_home, ema_var_contra_home, ema_var_favor_away, ema_var_contra_away)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(equipo_norm) DO UPDATE SET
                    equipo_real=excluded.equipo_real, liga=excluded.liga, ultima_actualizacion=excluded.ultima_actualizacion,
                    ema_xg_favor_home=excluded.ema_xg_favor_home,
                    ema_xg_contra_home=excluded.ema_xg_contra_home,
                    partidos_home=excluded.partidos_home,
                    ema_xg_favor_away=excluded.ema_xg_favor_away,
                    ema_xg_contra_away=excluded.ema_xg_contra_away,
                    partidos_away=excluded.partidos_away,
                    ema_var_favor_home=excluded.ema_var_favor_home,
                    ema_var_contra_home=excluded.ema_var_contra_home,
                    ema_var_favor_away=excluded.ema_var_favor_away,
                    ema_var_contra_away=excluded.ema_var_contra_away
            """, (eq_norm, dt["nombre"], dt["liga"], hoy.strftime("%Y-%m-%d"), dt["fav_home"], dt["con_home"], dt["p_home"], dt["fav_away"], dt["con_away"], dt["p_away"], dt["var_fh"], dt["var_ch"], dt["var_fa"], dt["var_ca"]))
        
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
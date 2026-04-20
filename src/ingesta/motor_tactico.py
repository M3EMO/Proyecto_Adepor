import sqlite3
import requests
from datetime import datetime, timedelta
from src.comun import gestor_nombres
from src.comun.config_sistema import DB_NAME, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL

# ==========================================
# MOTOR TÁCTICO V3.1 (EL ANALISTA INTEGRADO)
# Responsabilidad: Extracción de Formaciones, Fusión con Motor DTs y Upsert SQLite.
# V3.1: API key movida a config.json. MAPA_LIGAS_API centralizado en config_sistema.
# ==========================================

BASE_URL = "https://v3.football.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY_FOOTBALL}

# Alias local para compatibilidad con el resto del archivo
MAPA_LIGAS_API = MAPA_LIGAS_API_FOOTBALL

def preparar_base_datos(cursor):
    """Crea las columnas tácticas y de DT si no existen en la bóveda"""
    try: cursor.execute("ALTER TABLE partidos_backtest ADD COLUMN formacion_l TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE partidos_backtest ADD COLUMN formacion_v TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE equipos_stats ADD COLUMN dt_nombre TEXT DEFAULT 'Desconocido'")
    except: pass

def _get_current_season(pais):
    """
    Calcula la temporada activa según el país y la fecha actual.
    - Ligas europeas y Turquía: temporada dividida (jul-jun) -> año de inicio
    - Argentina, Brasil: temporada de año calendario -> año actual
    - Noruega: temporada de año calendario -> año actual
    """
    year  = datetime.now().year
    month = datetime.now().month
    ligas_temporada_dividida = {"Inglaterra", "Turquia"}
    if pais in ligas_temporada_dividida:
        return year - 1 if month < 7 else year
    return year  # Argentina, Brasil, Noruega -> año calendario


def procesar_tactica():
    print("[TACTICO] Iniciando Motor Táctico V3.1 (Extracción de Formaciones y Control de DTs)...")
    conn = sqlite3.connect(DB_NAME, isolation_level=None)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')

    preparar_base_datos(cursor)

    # 1. Buscar partidos de HOY y AYER que no tengan formación cargada
    # FIX: usar DATE() para comparación agnóstica al formato (DB guarda YYYY-MM-DD HH:MM)
    hoy = datetime.now()
    fecha_hoy  = hoy.strftime("%Y-%m-%d")
    fecha_ayer = (hoy - timedelta(days=1)).strftime("%Y-%m-%d")

    query = """
        SELECT id_partido, pais, local, visita, fecha
        FROM partidos_backtest
        WHERE DATE(fecha) IN (?, ?)
        AND (formacion_l = '' OR formacion_l IS NULL)
    """
    cursor.execute(query, (fecha_ayer, fecha_hoy))
    partidos_huerfanos = cursor.fetchall()

    if not partidos_huerfanos:
        print("[INFO] No hay partidos recientes pendientes de análisis táctico.")
        conn.close()
        return

    diccionario_nombres = gestor_nombres.cargar_diccionario()
    # 2. Diccionario de memoria de DTs actuales
    cursor.execute("SELECT nombre, dt_nombre, partidos_dt FROM equipos_stats")
    memoria_dts = {row[0]: {"dt": row[1], "pj": row[2]} for row in cursor.fetchall()}

    actualizados = 0

    # 3. Consultas a la API-Football (Agrupadas por fecha y liga para ahorrar cuota)
    fechas_api = [fecha_ayer, fecha_hoy]

    for fecha_api in fechas_api:
        for pais, lig_id in MAPA_LIGAS_API.items():
            # ¿Tenemos algún partido de este país en estas fechas sin formación?
            # FIX: comparar contra fecha_api directamente (ambas en YYYY-MM-DD)
            huerfanos_liga = [p for p in partidos_huerfanos if p[1] == pais and p[4][:10] == fecha_api]
            if not huerfanos_liga: continue

            # FIX: temporada dinámica en vez de season=2024 hardcodeado
            season = _get_current_season(pais)
            print(f"   [BUSCA] Buscando alineaciones en {pais} ({fecha_api}, season={season})...")

            # Traer el calendario del día
            url_fixtures = f"{BASE_URL}/fixtures?league={lig_id}&season={season}&date={fecha_api}"
            try:
                res_fix = requests.get(url_fixtures, headers=HEADERS, timeout=10).json()
                
                for ev in res_fix.get("response", []):
                    fix_id = ev["fixture"]["id"]
                    loc_api = ev["teams"]["home"]["name"]
                    vis_api = ev["teams"]["away"]["name"]
                    
                    # Cruzar con nuestros huérfanos
                    partido_db = next((p for p in huerfanos_liga if gestor_nombres.son_equivalentes(p[2], loc_api, diccionario_nombres) and gestor_nombres.son_equivalentes(p[3], vis_api, diccionario_nombres)), None)
                    
                    if partido_db:
                        # Extraer Alineaciones
                        url_lineups = f"{BASE_URL}/fixtures/lineups?fixture={fix_id}"
                        res_lineup = requests.get(url_lineups, headers=HEADERS, timeout=10).json()
                        lineups = res_lineup.get("response", [])
                        
                        if not lineups or len(lineups) < 2: continue

                        form_l = lineups[0].get("formation", "")
                        coach_l = lineups[0].get("coach", {}).get("name", "Desconocido")
                        form_v = lineups[1].get("formation", "")
                        coach_v = lineups[1].get("coach", {}).get("name", "Desconocido")

                        if not form_l or not form_v: continue

                        id_p = partido_db[0]
                        
                        loc_canonico = gestor_nombres.obtener_nombre_estandar(loc_api, modo_interactivo=False)
                        vis_canonico = gestor_nombres.obtener_nombre_estandar(vis_api, modo_interactivo=False)
                        # A. Actualizar Táctica del Partido
                        cursor.execute("UPDATE partidos_backtest SET formacion_l=?, formacion_v=? WHERE id_partido=?", (form_l, form_v, id_p))
                        
                        # B. Gestión Autónoma de DTs (Reemplazo del motor_dts.py)
                        for eq, coach_nuevo in [(loc_canonico, coach_l), (vis_canonico, coach_v)]:
                            if eq in memoria_dts:
                                dt_viejo = memoria_dts[eq]["dt"]
                                pj_viejo = memoria_dts[eq]["pj"]
                                
                                if dt_viejo != coach_nuevo and dt_viejo != "Desconocido":
                                    print(f"   [ALERTA] SHOCK: Cambio de DT en {eq.title()} ({dt_viejo} -> {coach_nuevo}). Estabilidad reiniciada a 1.")
                                    cursor.execute("UPDATE equipos_stats SET dt_nombre=?, partidos_dt=1 WHERE nombre=?", (coach_nuevo, eq))
                                else:
                                    # Mismo DT, suma 1 partido de vida
                                    cursor.execute("UPDATE equipos_stats SET dt_nombre=?, partidos_dt=? WHERE nombre=?", (coach_nuevo, pj_viejo + 1, eq))
                            else:
                                # Equipo nuevo
                                cursor.execute("INSERT INTO equipos_stats (nombre, liga, partidos_dt, dt_nombre) VALUES (?, ?, 1, ?)", (eq, pais, coach_nuevo))
                                memoria_dts[eq] = {"dt": coach_nuevo, "pj": 1}

                        actualizados += 1
                        print(f"   [DEF] Táctica inyectada: {loc_canonico} ({form_l}) vs {vis_canonico} ({form_v})")

            except Exception as e:
                print(f"   [X] Error API en {pais}: {e}")

    conn.close()
    print(f"[OK] Análisis completado. {actualizados} partidos actualizados. Motor DTs absorbido con éxito.")

def main():
    procesar_tactica()

if __name__ == "__main__":
    main()
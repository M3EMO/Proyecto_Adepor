import sqlite3
import requests
import unicodedata
from datetime import datetime, timedelta
import gestor_nombres

# ==========================================
# MOTOR TÁCTICO V3.0 (EL ANALISTA INTEGRADO)
# Responsabilidad: Extracción de Formaciones, Fusión con Motor DTs y Upsert SQLite.
# ==========================================

DB_NAME = 'fondo_quant.db'

# 🚨 TU LLAVE DE API-FOOTBALL 🚨
API_FOOTBALL_KEY = "95a21929923fef5aff0e34b64f2b17c9"
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}

MAPA_LIGAS_API = {
    "Argentina": 128, "Inglaterra": 39, "Brasil": 71, 
    "Noruega": 69, "Turquia": 203
}

def preparar_base_datos(cursor):
    """Crea las columnas tácticas y de DT si no existen en la bóveda"""
    try: cursor.execute("ALTER TABLE partidos_backtest ADD COLUMN formacion_l TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE partidos_backtest ADD COLUMN formacion_v TEXT DEFAULT ''")
    except: pass
    try: cursor.execute("ALTER TABLE equipos_stats ADD COLUMN dt_nombre TEXT DEFAULT 'Desconocido'")
    except: pass

def procesar_tactica():
    print("📋 Iniciando Motor Táctico V3.0 (Extracción de Formaciones y Control de DTs)...")
    conn = sqlite3.connect(DB_NAME, isolation_level=None)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    
    preparar_base_datos(cursor)

    # 1. Buscar partidos de HOY y AYER que no tengan formación cargada
    hoy = datetime.now()
    fechas_str = [(hoy - timedelta(days=1)).strftime("%d/%m/%Y"), hoy.strftime("%d/%m/%Y")]
    
    placeholders = ','.join(['?'] * len(fechas_str))
    query = f"""
        SELECT id_partido, pais, local, visita, fecha 
        FROM partidos_backtest 
        WHERE substr(fecha, 1, 10) IN ({placeholders}) 
        AND (formacion_l = '' OR formacion_l IS NULL)
    """
    cursor.execute(query, fechas_str)
    partidos_huerfanos = cursor.fetchall()

    if not partidos_huerfanos:
        print("ℹ️ No hay partidos recientes pendientes de análisis táctico.")
        conn.close()
        return

    diccionario_nombres = gestor_nombres.cargar_diccionario()
    # 2. Diccionario de memoria de DTs actuales
    cursor.execute("SELECT nombre, dt_nombre, partidos_dt FROM equipos_stats")
    memoria_dts = {row[0]: {"dt": row[1], "pj": row[2]} for row in cursor.fetchall()}

    actualizados = 0

    # 3. Consultas a la API-Football (Agrupadas por fecha y liga para ahorrar cuota)
    fechas_api = [(hoy - timedelta(days=1)).strftime("%Y-%m-%d"), hoy.strftime("%Y-%m-%d")]
    
    for fecha_api in fechas_api:
        for pais, lig_id in MAPA_LIGAS_API.items():
            # ¿Tenemos algún partido de este país en estas fechas sin formación?
            huerfanos_liga = [p for p in partidos_huerfanos if p[1] == pais and p[4][:10] == datetime.strptime(fecha_api, "%Y-%m-%d").strftime("%d/%m/%Y")]
            if not huerfanos_liga: continue

            print(f"   🔎 Buscando alineaciones en {pais} ({fecha_api})...")
            
            # Traer el calendario del día
            url_fixtures = f"{BASE_URL}/fixtures?league={lig_id}&season=2024&date={fecha_api}"
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
                                    print(f"   🚨 SHOCK: Cambio de DT en {eq.title()} ({dt_viejo} -> {coach_nuevo}). Estabilidad reiniciada a 1.")
                                    cursor.execute("UPDATE equipos_stats SET dt_nombre=?, partidos_dt=1 WHERE nombre=?", (coach_nuevo, eq))
                                else:
                                    # Mismo DT, suma 1 partido de vida
                                    cursor.execute("UPDATE equipos_stats SET dt_nombre=?, partidos_dt=? WHERE nombre=?", (coach_nuevo, pj_viejo + 1, eq))
                            else:
                                # Equipo nuevo
                                cursor.execute("INSERT INTO equipos_stats (nombre, liga, partidos_dt, dt_nombre) VALUES (?, ?, 1, ?)", (eq, pais, coach_nuevo))
                                memoria_dts[eq] = {"dt": coach_nuevo, "pj": 1}

                        actualizados += 1
                        print(f"   🛡️ Táctica inyectada: {loc_canonico} ({form_l}) vs {vis_canonico} ({form_v})")

            except Exception as e:
                print(f"   ❌ Error API en {pais}: {e}")

    conn.close()
    print(f"✅ Análisis completado. {actualizados} partidos actualizados. Motor DTs absorbido con éxito.")

if __name__ == "__main__":
    procesar_tactica()
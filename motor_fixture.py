import sqlite3
import requests
from datetime import datetime, timedelta
import gestor_nombres
import os
import json

# ==========================================
# MOTOR FIXTURE V6.8 (ESCUDO DE VALIDACIÓN PRE-INSERCIÓN)
# Responsabilidad: Prevención de 'Boundary Overlap' y 'Time-Shift Bugs'.
# ==========================================

DB_NAME = 'fondo_quant.db'

LIGAS_ESPN = {
    "arg.1": "Argentina", "eng.1": "Inglaterra",
    "bra.1": "Brasil", "nor.1": "Noruega", "tur.1": "Turquia"
}

# --- CONFIGURACIÓN DE FAILOVER ---
API_KEYS_ODDS = [
    "4cae986ac10670871e798390fdcb867c", "ac8262657731e6a0d8f3456697969fd0",
    "d5c54a43b0edf957f2455b161121dc68", "9dca75c9208891d279c764cad910111a",
    "f66391a91a19e99bce4666178474bd18", "f0a158af49776d3bc01a9bc983db8ff9"
]
KEY_INDEX = 0

MAPA_LIGAS_ODDS = {
    "Argentina": "soccer_argentina_primera_division", "Inglaterra": "soccer_epl",
    "Brasil": "soccer_brazil_campeonato", "Noruega": "soccer_norway_eliteserien",
    "Turquia": "soccer_turkey_super_league"
}

def normalizar_evento_api_secundaria(evento_api):
    """Convierte un evento de The-Odds-API al formato que espera el sistema."""
    return {
        'date': evento_api['commence_time'],
        'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'displayName': evento_api['home_team']}},
            {'homeAway': 'away', 'team': {'displayName': evento_api['away_team']}}
        ]}]
    }

def main():
    print("[SISTEMA] Iniciando Motor Fixture V6.8 (Escudo de Validacion Pre-Insercion)...")
    
    conn = sqlite3.connect(DB_NAME, isolation_level=None)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS partidos_backtest (
            id_partido TEXT PRIMARY KEY, fecha TEXT, local TEXT, visita TEXT, pais TEXT,
            estado TEXT, prob_1 REAL, prob_x REAL, prob_2 REAL, prob_o25 REAL, prob_u25 REAL,
            apuesta_1x2 TEXT, apuesta_ou TEXT, stake_1x2 REAL, stake_ou REAL,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL, cuota_o25 REAL, cuota_u25 REAL,
            goles_l INTEGER, goles_v INTEGER, formacion_l TEXT, formacion_v TEXT, 
            arbitro TEXT, id_arbitro TEXT, clv_registrado TEXT,
            cuota_cierre_1x2 REAL, cuota_cierre_ou REAL
        )
    """)

    global KEY_INDEX
    hoy = datetime.utcnow()
    fechas_a_buscar = [(hoy + timedelta(days=i)).strftime("%Y%m%d") for i in range(-1, 6)]
    
    partidos_agregados = 0
    partidos_omitidos = 0

    for fecha_api in fechas_a_buscar:
        for codigo_liga, pais in LIGAS_ESPN.items():
            eventos_del_dia = []
            fuente_activa = "ESPN"

            # --- INTENTO 1: FUENTE PRIMARIA (ESPN) ---
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
            try:
                resp = requests.get(url, timeout=5)
                resp.raise_for_status() # Lanza una excepción para códigos de error HTTP
                eventos_del_dia = resp.json().get('events', [])
            except requests.exceptions.RequestException as e:
                print(f"[FAILOVER] ESPN falló ({e}). Conmutando a The-Odds-API para {pais}...")
                fuente_activa = "The-Odds-API"
                
                # --- INTENTO 2: FUENTE SECUNDARIA (THE-ODDS-API) ---
                if pais in MAPA_LIGAS_ODDS and KEY_INDEX < len(API_KEYS_ODDS):
                    codigo_liga_odds = MAPA_LIGAS_ODDS[pais]
                    api_key = API_KEYS_ODDS[KEY_INDEX]
                    # Usamos el endpoint de 'scores' que también sirve para ver partidos futuros
                    url_odds = f"https://api.the-odds-api.com/v4/sports/{codigo_liga_odds}/scores/?apiKey={api_key}&daysFrom=1"
                    try:
                        resp_odds = requests.get(url_odds, timeout=10)
                        if resp_odds.status_code == 401 or resp_odds.status_code == 429:
                            KEY_INDEX += 1 # Rotar la clave si está agotada
                        resp_odds.raise_for_status()
                        
                        # Normalizamos la data para que sea compatible
                        eventos_api_secundaria = resp_odds.json()
                        eventos_del_dia = [normalizar_evento_api_secundaria(ev) for ev in eventos_api_secundaria]
                    except requests.exceptions.RequestException as e_odds:
                        print(f"[FALLO TOTAL] La API secundaria también falló: {e_odds}")

            for evento in eventos_del_dia:
                    try:
                        fecha_utc_str = evento['date']
                        fecha_utc_obj = None
                        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
                            try:
                                fecha_utc_obj = datetime.strptime(fecha_utc_str, fmt)
                                break
                            except ValueError:
                                continue
                        if fecha_utc_obj is None:
                            print(f"[ALERTA] Formato de fecha no reconocido: {fecha_utc_str}")
                            continue
                        
                        # FIX: El ID se genera con la fecha UTC para garantizar unicidad y evitar duplicados por zona horaria.
                        fecha_iso_real = fecha_utc_obj.strftime("%Y-%m-%d")
                        
                        fecha_local_obj = fecha_utc_obj - timedelta(hours=3)
                        fecha_db_real = fecha_local_obj.strftime("%Y-%m-%d %H:%M")  # ISO: ordena correctamente como texto
                        
                        competidores = evento['competitions'][0]['competitors']
                        loc_crudo = next(c['team']['displayName'] for c in competidores if c['homeAway'] == 'home')
                        vis_crudo = next(c['team']['displayName'] for c in competidores if c['homeAway'] == 'away')
                        
                        loc_oficial = gestor_nombres.obtener_nombre_estandar(loc_crudo, modo_interactivo=True)
                        vis_oficial = gestor_nombres.obtener_nombre_estandar(vis_crudo, modo_interactivo=True)
                        
                        # FIX CRITICO: Limpieza forzada de espacios para el ID
                        loc_id = gestor_nombres.limpiar_texto(loc_oficial)
                        vis_id = gestor_nombres.limpiar_texto(vis_oficial)
                        id_partido = f"{fecha_iso_real}{loc_id}{vis_id}"
                        
                        # --- Requerimiento 2: Escudo de Validación Pre-Inserción ---
                        # 1. La validación de fecha de ID es inherente al usar fecha_iso_real (UTC) para el ID.
                        # 2. Prevenir Time-Shift Bugs antes de la inserción.
                        cursor.execute("SELECT fecha FROM partidos_backtest WHERE local = ? AND visita = ?", (loc_oficial, vis_oficial))
                        partidos_existentes = cursor.fetchall()
                        es_duplicado_temporal = False
                        for (fecha_existente_str,) in partidos_existentes:
                            fecha_existente_obj = None
                            for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
                                try:
                                    fecha_existente_obj = datetime.strptime(fecha_existente_str.strip(), fmt)
                                    break
                                except ValueError:
                                    continue
                            if fecha_existente_obj is None:
                                continue
                            if abs((fecha_local_obj - fecha_existente_obj).days) <= 3:
                                es_duplicado_temporal = True
                                print(f"[VALIDACION] Insercion bloqueada. Posible 'Time-Shift Bug' para {loc_oficial} vs {vis_oficial}.")
                                break

                        if es_duplicado_temporal:
                            partidos_omitidos += 1
                            continue
                        
                        cursor.execute("""
                            INSERT INTO partidos_backtest (id_partido, fecha, local, visita, pais, estado)
                            VALUES (?, ?, ?, ?, ?, 'Pendiente')
                            ON CONFLICT(id_partido) DO NOTHING
                        """, (id_partido, fecha_db_real, loc_oficial, vis_oficial, pais))
                        
                        if cursor.rowcount > 0: partidos_agregados += 1
                        else: partidos_omitidos += 1
                    except Exception:
                        continue

    conn.close()
    print(f"\n[EXITO] Fixture completado. {partidos_agregados} inyectados | {partidos_omitidos} omitidos.")

if __name__ == "__main__":
    main()
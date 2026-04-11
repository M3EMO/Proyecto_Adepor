import sqlite3
import requests
import gestor_nombres
from datetime import datetime, timedelta
from config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS

# ==========================================
# MOTOR BACKTEST V7.2 (RESILIENTE CON FAILOVER)
# Responsabilidad: Liquidación de resultados con conmutación a API secundaria.
# V7.2: LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME y API_KEYS_ODDS desde config_sistema.
# ==========================================

# MAPA_LIGAS_ESPN: inverso de LIGAS_ESPN (pais -> codigo ESPN) — derivado en runtime
MAPA_LIGAS_ESPN = {pais: codigo for codigo, pais in LIGAS_ESPN.items()}
KEY_INDEX = 0

def safe_int(val):
    try: return int(val)
    except: return 0

def normalizar_evento_api_secundaria(evento_api):
    """Convierte un evento de The-Odds-API al formato que espera el sistema."""
    if not evento_api.get('completed', False) or not evento_api.get('scores'):
        return None # No es un partido finalizado con resultado

    loc_score = next((s['score'] for s in evento_api['scores'] if s['name'] == evento_api['home_team']), '0')
    vis_score = next((s['score'] for s in evento_api['scores'] if s['name'] == evento_api['away_team']), '0')

    return {
        'completed': True,
        'home_team': evento_api['home_team'], 'away_team': evento_api['away_team'],
        'goles_l': safe_int(loc_score), 'goles_v': safe_int(vis_score)
    }

def main():
    print("[SISTEMA] Iniciando Motor Backtest V7.0 (Resiliente con Failover)...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id_partido, local, visita, fecha FROM partidos_backtest WHERE estado = 'Calculado'")
    pendientes = cursor.fetchall()
    
    if not pendientes:
        print("[INFO] No hay partidos pendientes de resolucion.")
        conn.close()
        return
        
    print(f"[ESCANEO] Buscando resultados para {len(pendientes)} partidos.")
    
    hoy = datetime.now()
    partidos_liquidados = 0
    pendientes_restantes = list(pendientes)
    
    for i in range(7, -1, -1):
        fecha_obj = hoy - timedelta(days=i)
        fecha_api = fecha_obj.strftime("%Y%m%d")
        
        for pais, codigo_liga in MAPA_LIGAS_ESPN.items():
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200: continue
                
                for evento in resp.json().get('events', []):
                    try:
                        tipo_estado = evento.get('status', {}).get('type', {})
                        partido_terminado = tipo_estado.get('completed', False)
                        nombre_estado = tipo_estado.get('name', '')
                        
                        if not partido_terminado and nombre_estado not in ['STATUS_FINAL', 'STATUS_FULL_TIME']: 
                            continue
                            
                        competidores = evento['competitions'][0]['competitors']
                        loc_api = next(c for c in competidores if c['homeAway'] == 'home')
                        vis_api = next(c for c in competidores if c['homeAway'] == 'away')
                        
                        loc_oficial = gestor_nombres.obtener_nombre_estandar(loc_api['team']['displayName'], modo_interactivo=False)
                        vis_oficial = gestor_nombres.obtener_nombre_estandar(vis_api['team']['displayName'], modo_interactivo=False)
                        
                        for p in list(pendientes_restantes):
                            id_partido, loc_db, vis_db, _ = p
                            
                            if gestor_nombres.limpiar_texto(loc_db) == gestor_nombres.limpiar_texto(loc_oficial) and gestor_nombres.limpiar_texto(vis_db) == gestor_nombres.limpiar_texto(vis_oficial):
                                gL = safe_int(loc_api.get('score', 0))
                                gV = safe_int(vis_api.get('score', 0))
                                
                                # FIX: Estado pasa a 'Finalizado', esperando al Sincronizador
                                cursor.execute('''
                                    UPDATE partidos_backtest 
                                    SET goles_l = ?, goles_v = ?, estado = 'Finalizado' 
                                    WHERE id_partido = ?
                                ''', (gL, gV, id_partido))
                                
                                partidos_liquidados += 1
                                print(f"[RESULTADO] {loc_oficial} ({gL}) vs ({gV}) {vis_oficial}")
                                
                                pendientes_restantes.remove(p)
                                break 
                    except Exception: continue
            except requests.exceptions.RequestException: pass

    conn.commit()
    conn.close()
    
    if partidos_liquidados > 0:
        print(f"[EXITO] {partidos_liquidados} partidos marcados como Finalizados. Listos para inyeccion.")

if __name__ == "__main__":
    main()
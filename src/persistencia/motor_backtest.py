import sqlite3
import requests
from src.comun import gestor_nombres
from datetime import datetime, timedelta
from src.comun.config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
from src.comun.constantes_espn import ESTADOS_ESPN_FINALIZADO
from src.comun.mapas import MAPA_LIGAS_ESPN
from src.comun.tipos import safe_int

# ==========================================
# MOTOR BACKTEST V7.3 (RESILIENTE CON FAILOVER, SCOPE POR FECHA REAL)
# Responsabilidad: Liquidación de resultados con conmutación a API secundaria.
# V7.2: LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME y API_KEYS_ODDS desde config_sistema.
# V7.3 (2026-04-17): Escanea SOLO partidos 'Calculado' cuya fecha ya paso (no futuros),
#                    y SOLO consulta ESPN en las fechas unicas donde hay pendientes.
#                    Evita ~N*K llamadas inutiles a la API. No altera la logica de match
#                    ni la actualizacion de goles_l/goles_v/estado.
# ==========================================

KEY_INDEX = 0


def main():
    print("[SISTEMA] Iniciando Motor Backtest V7.3 (Scope por fecha real)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # V7.3: filtrar por fecha <= ahora. Los partidos futuros (estado='Calculado'
    # pero fecha > ahora) aun no se jugaron: no tienen resultado posible en ESPN.
    ahora_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    cursor.execute("""
        SELECT id_partido, local, visita, fecha
        FROM partidos_backtest
        WHERE estado = 'Calculado'
          AND fecha <= ?
    """, (ahora_str,))
    pendientes = cursor.fetchall()

    if not pendientes:
        print("[INFO] No hay partidos con fecha pasada pendientes de resolucion.")
        conn.close()
        return

    print(f"[ESCANEO] Buscando resultados para {len(pendientes)} partidos (fecha <= {ahora_str}).")

    partidos_liquidados = 0
    pendientes_restantes = list(pendientes)

    # V7.3: solo las fechas unicas donde tenemos pendientes. Antes: rango fijo de 8 dias.
    # Formato fecha en DB: 'YYYY-MM-DD HH:MM' -> extraer YYYYMMDD.
    fechas_unicas = sorted({p[3][:10].replace('-', '') for p in pendientes}, reverse=True)

    for fecha_api in fechas_unicas:
        if not pendientes_restantes:
            break
        for pais, codigo_liga in MAPA_LIGAS_ESPN.items():
            if not pendientes_restantes:
                break
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200: continue
                
                for evento in resp.json().get('events', []):
                    try:
                        tipo_estado = evento.get('status', {}).get('type', {})
                        partido_terminado = tipo_estado.get('completed', False)
                        nombre_estado = tipo_estado.get('name', '')
                        
                        if not partido_terminado and nombre_estado not in ESTADOS_ESPN_FINALIZADO:
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
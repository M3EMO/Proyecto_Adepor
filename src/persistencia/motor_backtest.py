import sqlite3
import requests
from src.comun import gestor_nombres
from datetime import datetime, timedelta
from src.comun.config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
from src.comun.constantes_espn import ESTADOS_ESPN_FINALIZADO
from src.comun.mapas import MAPA_LIGAS_ESPN
from src.comun.tiempo import ahora_art
from src.comun.tipos import safe_int

# ==========================================
# MOTOR BACKTEST V7.4 (resultados ESPN; empareja por liga y fecha +-1)
# Responsabilidad: Liquidación de resultados con conmutación a API secundaria.
# V7.2: LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME y API_KEYS_ODDS desde config_sistema.
# V7.3 (2026-04-17): Escanea SOLO partidos 'Calculado' cuya fecha ya paso (no futuros),
#                    y SOLO consulta ESPN en las fechas unicas donde hay pendientes.
#                    Evita ~N*K llamadas inutiles a la API. No altera la logica de match
#                    ni la actualizacion de goles_l/goles_v/estado.
# ==========================================

KEY_INDEX = 0


def _score_entero(valor):
    """Score ESPN -> int. None si falta o no es numerico."""
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _coincide_partido(pendiente, pais_liga, fecha_api, loc_oficial, vis_oficial):
    """True si el evento ESPN corresponde al pendiente: mismos equipos, misma liga y fecha +-1 dia.

    pendiente: (id_partido, local, visita, fecha 'YYYY-MM-DD HH:MM', pais).
    fecha_api: fecha del scoreboard escaneado, 'YYYYMMDD'.
    """
    _id, loc_db, vis_db, fecha_db, pais_db = pendiente
    if pais_db != pais_liga:
        return False
    dias = abs((datetime.strptime(fecha_db[:10], '%Y-%m-%d') - datetime.strptime(fecha_api, '%Y%m%d')).days)
    if dias > 1:
        return False
    return (gestor_nombres.limpiar_texto(loc_db) == gestor_nombres.limpiar_texto(loc_oficial)
            and gestor_nombres.limpiar_texto(vis_db) == gestor_nombres.limpiar_texto(vis_oficial))


def main():
    print("[SISTEMA] Iniciando Motor Backtest V7.4 (Scope por fecha real)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # V7.3: filtrar por fecha <= ahora. Los partidos futuros (estado='Calculado'
    # pero fecha > ahora) aun no se jugaron: no tienen resultado posible en ESPN.
    ahora_str = ahora_art().strftime('%Y-%m-%d %H:%M')
    cursor.execute("""
        SELECT id_partido, local, visita, fecha, pais
        FROM partidos_backtest
        WHERE estado IN ('Pendiente', 'Calculado')  -- Pendiente: el pipeline abortó antes de calcularlo
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
    # V7.4: tambien el dia siguiente, sin pasar de hoy. Un partido postergado un dia queda con la
    # fecha vieja en la DB (motor_fixture bloquea el cambio como Time-Shift) y ESPN lo lista en la nueva.
    hoy = ahora_art().date()
    fechas_unicas = sorted({d.strftime('%Y%m%d') for p in pendientes
                            for d in (datetime.strptime(p[3][:10], '%Y-%m-%d').date() + timedelta(days=k) for k in (0, 1))
                            if d <= hoy}, reverse=True)

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
                        
                        loc_oficial = gestor_nombres.obtener_nombre_estandar(loc_api['team']['displayName'], liga=pais, modo_interactivo=False)
                        vis_oficial = gestor_nombres.obtener_nombre_estandar(vis_api['team']['displayName'], liga=pais, modo_interactivo=False)
                        
                        for p in list(pendientes_restantes):
                            if _coincide_partido(p, pais, fecha_api, loc_oficial, vis_oficial):
                                id_partido = p[0]
                                gL = _score_entero(loc_api.get('score'))
                                gV = _score_entero(vis_api.get('score'))
                                if gL is None or gV is None:
                                    print(f"[WARN] Score no numerico en ESPN, partido sin liquidar: {loc_oficial} vs {vis_oficial}")
                                    break

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
                    except Exception as e:
                        print(f"[WARN] Evento ESPN omitido: {type(e).__name__}: {e}")
                        continue
            except requests.exceptions.RequestException: pass

    print(f"[INFO] Pendientes sin resultado ESPN: {len(pendientes_restantes)}.")
    conn.commit()
    conn.close()
    
    if partidos_liquidados > 0:
        print(f"[EXITO] {partidos_liquidados} partidos marcados como Finalizados. Listos para inyeccion.")

if __name__ == "__main__":
    main()
import sqlite3
import requests
import unicodedata
import json
import os
import difflib
import gestor_nombres

# ==========================================
# MOTOR CUOTAS V9.1 (RADAR SHARP + SUB-STRING MATCH)
# Responsabilidad: Auto-Matching relajado, Linea 2.5 Estricta y Jerarquia Pinnacle.
# ==========================================

DB_NAME = 'fondo_quant.db'
MODO_INTERACTIVO = os.getenv('PROYECTO_MODO_INTERACTIVO') == '1'
DICCIONARIO_FILE = 'diccionario_equipos.json'

API_KEYS = [
    "4cae986ac10670871e798390fdcb867c",  
    "ac8262657731e6a0d8f3456697969fd0",        
    "d5c54a43b0edf957f2455b161121dc68",
    "9dca75c9208891d279c764cad910111a",
    "f66391a91a19e99bce4666178474bd18",
    "f0a158af49776d3bc01a9bc983db8ff9"
]

MAPA_LIGAS_ODDS = {
    "Argentina": "soccer_argentina_primera_division",
    "Inglaterra": "soccer_epl",
    "Brasil": "soccer_brazil_campeonato",
    "Noruega": "soccer_norway_eliteserien",
    "Turquia": "soccer_turkey_super_league"
}

def cargar_diccionario():
    if os.path.exists(DICCIONARIO_FILE):
        with open(DICCIONARIO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def obtener_datos_api(liga_odds, key_index=0):
    if key_index >= len(API_KEYS):
        print("[ERROR] Todas las API Keys se han agotado o estan bloqueadas.")
        return None, key_index
        
    api_key = API_KEYS[key_index]
    url = f"https://api.the-odds-api.com/v4/sports/{liga_odds}/odds/?apiKey={api_key}&regions=eu,us,uk,au&markets=h2h,totals&bookmakers=pinnacle,bet365,1xBet,betfair_ex_eu,draftkings"
    
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json(), key_index
        elif resp.status_code == 429 or resp.status_code == 401:
            print(f"[ALERTA] Key {key_index} agotada. Rotando a la siguiente...")
            return obtener_datos_api(liga_odds, key_index + 1)
        else:
            return None, key_index
    except:
        return None, key_index

def extraer_cuotas_sharp(bookmakers, local_api, visita_api):
    c1, cx, c2 = 0.0, 0.0, 0.0
    co, cu = 0.0, 0.0

    for b in bookmakers:
        if b['key'] in ['pinnacle', 'bet365']:
            for m in b.get('markets', []):
                if m['key'] == 'h2h':
                    for out in m['outcomes']:
                        nombre = out['name']
                        if nombre == 'Draw':
                            cx = out['price']
                        elif nombre == local_api:
                            c1 = out['price']
                        elif nombre == visita_api:
                            c2 = out['price']
            if c1 > 0: break

    for b in bookmakers:
        for m in b.get('markets', []):
            if m['key'] == 'totals':
                for out in m['outcomes']:
                    if out.get('point') == 2.5:
                        if out['name'] == 'Over': co = out['price']
                        if out['name'] == 'Under': cu = out['price']
        if co > 0 and cu > 0: break 

    return c1, cx, c2, co, cu

def main():
    print("[SISTEMA] Iniciando Motor Cuotas V9.1 (Radar Sharp con Contencion)...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Solo partidos sin resultado: goles_l IS NULL descarta partidos ya jugados pero
    # no liquidados aun, evitando consultas inutiles a la API por partidos pasados.
    cursor.execute("""
        SELECT id_partido, local, visita, pais FROM partidos_backtest
        WHERE estado != 'Liquidado' AND goles_l IS NULL AND goles_v IS NULL
    """)
    partidos = cursor.fetchall()
    
    if not partidos:
        print("[INFO] No hay partidos vivos para actualizar cuotas.")
        return

    partidos_por_liga = {}
    for p in partidos:
        pais = p[3]
        if pais in MAPA_LIGAS_ODDS:
            liga_odds = MAPA_LIGAS_ODDS[pais]
            if liga_odds not in partidos_por_liga: partidos_por_liga[liga_odds] = []
            partidos_por_liga[liga_odds].append(p)

    key_actual = 0
    cuotas_actualizadas = 0

    for liga_odds, lista_partidos in partidos_por_liga.items():
        print(f"   [ESCANEO] Buscando mercado para la liga: {liga_odds}...")
        datos_api, key_actual = obtener_datos_api(liga_odds, key_actual)
        
        if not datos_api: continue

        for p in lista_partidos:
            id_p, loc_espn, vis_espn, _ = p
            encontrado = False
            
            for evento in datos_api:
                loc_odds = evento.get("home_team", "")
                vis_odds = evento.get("away_team", "")
                
                # Resolver nombres de la API de cuotas a nuestro estándar
                loc_odds_oficial = gestor_nombres.obtener_nombre_estandar(loc_odds, modo_interactivo=MODO_INTERACTIVO)
                vis_odds_oficial = gestor_nombres.obtener_nombre_estandar(vis_odds, modo_interactivo=MODO_INTERACTIVO)

                if (gestor_nombres.limpiar_texto(loc_espn) == gestor_nombres.limpiar_texto(loc_odds_oficial)
                        and gestor_nombres.limpiar_texto(vis_espn) == gestor_nombres.limpiar_texto(vis_odds_oficial)):
                    c1, cx, c2, co, cu = extraer_cuotas_sharp(evento.get("bookmakers", []), loc_odds, vis_odds)
                    
                    if c1 > 0 or co > 0:
                        cursor.execute("""
                            UPDATE partidos_backtest SET 
                            cuota_1 = CASE WHEN ? > 0 THEN ? ELSE cuota_1 END,
                            cuota_x = CASE WHEN ? > 0 THEN ? ELSE cuota_x END,
                            cuota_2 = CASE WHEN ? > 0 THEN ? ELSE cuota_2 END,
                            cuota_o25 = CASE WHEN ? > 0 THEN ? ELSE cuota_o25 END,
                            cuota_u25 = CASE WHEN ? > 0 THEN ? ELSE cuota_u25 END
                            WHERE id_partido=?
                        """, (c1, c1, cx, cx, c2, c2, co, co, cu, cu, id_p))
                        
                        cuotas_actualizadas += 1
                        print(f"      [MATCH] Cuotas capturadas: {loc_espn} vs {vis_espn}")
                        encontrado = True
                    break
            
            if not encontrado:
                print(f"      [ALERTA] No se hallaron cuotas en mercado para: {loc_espn} vs {vis_espn}")

    conn.commit()
    conn.close()
    print(f"[EXITO] Motor Cuotas completado. {cuotas_actualizadas} partidos inyectados con probabilidades de mercado.")

if __name__ == "__main__":
    main()
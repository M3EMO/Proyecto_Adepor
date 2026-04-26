import sqlite3
import requests
import json
import os
import difflib
from datetime import datetime, timedelta
from src.comun import gestor_nombres
from src.comun.config_sistema import MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS

# ==========================================
# MOTOR CUOTAS V9.3 (RADAR SHARP + CAPTURA CUOTA_CIERRE PARA CLV)
# Responsabilidad: Auto-Matching, Linea 2.5 Estricta y Jerarquia Pinnacle.
# V9.3 (2026-04-25, bead adepor-dl6): captura cuota_cierre_1x2/ou cuando el
#       partido esta dentro de la ventana <2h del kickoff y tiene pick con stake>0.
#       Cambio aditivo: NO altera la logica de UPDATE existente de cuota_1/x/2/o25/u25.
#       Decision Lead: SOBREESCRIBIR dentro de la ventana (siempre tomar el valor
#       mas fresco), NO sobreescribir si el partido ya paso (preserva cierre legitimo).
# V9.2: O/U ahora prioriza Pinnacle igual que 1X2. MAPA_LIGAS_ODDS importado
#       desde config_sistema — agregar ligas en un solo lugar.
# ==========================================

# Ventana CLV: capturar cuota_cierre cuando faltan <= 2h al kickoff
VENTANA_CIERRE = timedelta(hours=2)


def _seleccionar_cuota_cierre(apuesta_str, c1, cx, c2, co, cu):
    """
    Dada la apuesta_1x2 / apuesta_ou (formato "[APOSTAR] 1", "[APOSTAR] X",
    "[APOSTAR] 2", "[APOSTAR] OVER", "[APOSTAR] UNDER"), retorna la cuota
    cierre capturada para ese pick. Retorna 0.0 si no hay match o no aplica.
    """
    if not apuesta_str:
        return 0.0
    s = apuesta_str.strip().upper()
    if not s.startswith("[APOSTAR]"):
        return 0.0
    pick = s.replace("[APOSTAR]", "").strip()
    if pick == "1":     return c1 or 0.0
    if pick == "X":     return cx or 0.0
    if pick == "2":     return c2 or 0.0
    if pick == "OVER":  return co or 0.0
    if pick == "UNDER": return cu or 0.0
    return 0.0


def _en_ventana_cierre(fecha_str):
    """
    True si el partido esta dentro de la ventana de captura: fecha esta entre
    now y now+2h (kickoff inminente). Fuera de eso: skip (NO sobreescribir).
    fecha_str formato esperado: 'YYYY-MM-DD HH:MM'.
    """
    if not fecha_str:
        return False
    try:
        fp = datetime.strptime(fecha_str, '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return False
    delta = fp - datetime.now()
    return timedelta(0) <= delta <= VENTANA_CIERRE

MODO_INTERACTIVO = os.getenv('PROYECTO_MODO_INTERACTIVO') == '1'
DICCIONARIO_FILE = 'diccionario_equipos.json'

# API Keys desde config_sistema (que las lee de config.json)
API_KEYS = API_KEYS_ODDS

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

    # --- 1X2: preferir Pinnacle, luego bet365 ---
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
            if c1 > 0:
                break

    # --- O/U 2.5: jerarquia Pinnacle -> bet365 -> resto (igual que 1X2) ---
    # Primero intentar fuentes sharp; si no tienen 2.5, caer al resto.
    puntos_disponibles = set()
    fuente_ou = None
    ORDEN_OU = ['pinnacle', 'bet365', '1xbet', 'betfair_ex_eu', 'draftkings']
    bookmakers_ordenados = sorted(
        bookmakers,
        key=lambda b: ORDEN_OU.index(b['key']) if b['key'] in ORDEN_OU else len(ORDEN_OU)
    )
    for b in bookmakers_ordenados:
        co_tmp, cu_tmp = 0.0, 0.0
        for m in b.get('markets', []):
            if m['key'] == 'totals':
                for out in m['outcomes']:
                    punto = out.get('point')
                    try:
                        punto_f = float(punto)
                    except (TypeError, ValueError):
                        continue
                    puntos_disponibles.add(punto_f)
                    if abs(punto_f - 2.5) < 0.01:
                        if out['name'] == 'Over':  co_tmp = out['price']
                        if out['name'] == 'Under': cu_tmp = out['price']
        if co_tmp > 0 and cu_tmp > 0:
            co, cu = co_tmp, cu_tmp
            fuente_ou = b['key']
            break  # tenemos ambos lados de una fuente sharp — listo

    if fuente_ou:
        if fuente_ou not in ('pinnacle', 'bet365'):
            print(f"         [AVISO O/U] Fuente blanda: {fuente_ou} (Pinnacle/bet365 no tenian 2.5)")
    elif puntos_disponibles:
        lineas = sorted(puntos_disponibles)
        print(f"         [INFO O/U] Linea 2.5 no disponible. Lineas en mercado: {lineas}")

    return c1, cx, c2, co, cu

def main():
    print("[SISTEMA] Iniciando Motor Cuotas V9.1 (Radar Sharp con Contencion)...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Solo partidos sin resultado: goles_l IS NULL descarta partidos ya jugados pero
    # no liquidados aun, evitando consultas inutiles a la API por partidos pasados.
    # V9.3: traemos fecha + apuestas + stakes para soporte CLV (captura cuota_cierre).
    cursor.execute("""
        SELECT id_partido, local, visita, pais, fecha, apuesta_1x2, apuesta_ou, stake_1x2, stake_ou
        FROM partidos_backtest
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

        # Pais canonico de esta liga_odds (para scope por liga en gestor_nombres).
        # lista_partidos no esta vacia aca: cada row tiene pais en p[3].
        pais_liga = lista_partidos[0][3] if lista_partidos else None

        # Pre-construir índice normalizado de eventos de la API para matching rápido
        eventos_index = []
        for evento in datos_api:
            loc_raw = evento.get("home_team", "")
            vis_raw = evento.get("away_team", "")
            loc_std = gestor_nombres.obtener_nombre_estandar(loc_raw, liga=pais_liga, modo_interactivo=MODO_INTERACTIVO)
            vis_std = gestor_nombres.obtener_nombre_estandar(vis_raw, liga=pais_liga, modo_interactivo=MODO_INTERACTIVO)
            eventos_index.append({
                'evento':   evento,
                'loc_raw':  loc_raw,
                'vis_raw':  vis_raw,
                'loc_norm': gestor_nombres.limpiar_texto(loc_std),
                'vis_norm': gestor_nombres.limpiar_texto(vis_std),
            })

        for p in lista_partidos:
            id_p, loc_espn, vis_espn, _, fecha_p, ap_1x2, ap_ou, stk_1x2, stk_ou = p
            loc_norm = gestor_nombres.limpiar_texto(loc_espn)
            vis_norm = gestor_nombres.limpiar_texto(vis_espn)
            encontrado = False

            # --- Paso 1: match exacto normalizado ---
            match_evento = None
            for ei in eventos_index:
                if ei['loc_norm'] == loc_norm and ei['vis_norm'] == vis_norm:
                    match_evento = ei
                    break

            # --- Paso 2: fallback fuzzy si el exacto falla ---
            if match_evento is None:
                mejor_score = 0.0
                for ei in eventos_index:
                    score_loc = difflib.SequenceMatcher(None, loc_norm, ei['loc_norm']).ratio()
                    score_vis = difflib.SequenceMatcher(None, vis_norm, ei['vis_norm']).ratio()
                    score = (score_loc + score_vis) / 2
                    if score > mejor_score:
                        mejor_score = score
                        mejor_ei = ei
                if mejor_score >= 0.75:
                    match_evento = mejor_ei
                    print(f"      [FUZZY {mejor_score:.0%}] {loc_espn} vs {vis_espn} -> {mejor_ei['loc_raw']} vs {mejor_ei['vis_raw']}")

            if match_evento is not None:
                evento = match_evento['evento']
                c1, cx, c2, co, cu = extraer_cuotas_sharp(
                    evento.get("bookmakers", []),
                    match_evento['loc_raw'],
                    match_evento['vis_raw']
                )
                if c1 > 0 or co > 0:
                    cursor.execute("""
                        UPDATE partidos_backtest SET
                        cuota_1   = CASE WHEN ? > 0 THEN ? ELSE cuota_1   END,
                        cuota_x   = CASE WHEN ? > 0 THEN ? ELSE cuota_x   END,
                        cuota_2   = CASE WHEN ? > 0 THEN ? ELSE cuota_2   END,
                        cuota_o25 = CASE WHEN ? > 0 THEN ? ELSE cuota_o25 END,
                        cuota_u25 = CASE WHEN ? > 0 THEN ? ELSE cuota_u25 END
                        WHERE id_partido=?
                    """, (c1, c1, cx, cx, c2, c2, co, co, cu, cu, id_p))
                    cuotas_actualizadas += 1
                    print(f"      [MATCH] Cuotas capturadas: {loc_espn} vs {vis_espn} | 1={c1} X={cx} 2={c2} O={co} U={cu}")
                    encontrado = True

                    # --- V9.3: captura cuota_cierre para CLV ---
                    # Solo si: (a) en ventana <2h al kickoff, (b) hay pick con stake>0.
                    # SOBREESCRIBIR dentro de la ventana (decision Lead 2026-04-25).
                    # Fuera de la ventana: NO tocar (preserva cierre legitimo o nulo).
                    if _en_ventana_cierre(fecha_p):
                        cierre_1x2_nuevo = 0.0
                        cierre_ou_nuevo  = 0.0
                        if stk_1x2 and stk_1x2 > 0:
                            cierre_1x2_nuevo = _seleccionar_cuota_cierre(ap_1x2, c1, cx, c2, co, cu)
                        if stk_ou and stk_ou > 0:
                            cierre_ou_nuevo  = _seleccionar_cuota_cierre(ap_ou,  c1, cx, c2, co, cu)
                        if cierre_1x2_nuevo > 0 or cierre_ou_nuevo > 0:
                            cursor.execute("""
                                UPDATE partidos_backtest SET
                                cuota_cierre_1x2 = CASE WHEN ? > 0 THEN ? ELSE cuota_cierre_1x2 END,
                                cuota_cierre_ou  = CASE WHEN ? > 0 THEN ? ELSE cuota_cierre_ou  END
                                WHERE id_partido=?
                            """, (cierre_1x2_nuevo, cierre_1x2_nuevo,
                                  cierre_ou_nuevo,  cierre_ou_nuevo, id_p))
                            print(f"         [CLV] cuota_cierre capturada: 1x2={cierre_1x2_nuevo} ou={cierre_ou_nuevo} (kickoff en ventana)")
                else:
                    print(f"      [ALERTA] Partido encontrado pero sin cuotas sharp: {loc_espn} vs {vis_espn}")

            if not encontrado and match_evento is None:
                print(f"      [ALERTA] Sin match en mercado para: {loc_espn} vs {vis_espn}")

    conn.commit()
    conn.close()
    print(f"[EXITO] Motor Cuotas completado. {cuotas_actualizadas} partidos inyectados con probabilidades de mercado.")

if __name__ == "__main__":
    main()
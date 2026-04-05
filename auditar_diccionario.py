"""
AUDITOR DE DICCIONARIO
Consulta la odds API para cada liga, lista todos los nombres que devuelve,
y los compara contra los equipos que tenemos en la DB.
Imprime los que no tienen match exacto y sugiere la entrada a agregar al diccionario.
"""
import sqlite3
import requests
import json
import os
import difflib
import gestor_nombres

DB_NAME          = 'fondo_quant.db'
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
    "Brasil":    "soccer_brazil_campeonato",
    "Noruega":   "soccer_norway_eliteserien",
    "Turquia":   "soccer_turkey_super_league"
}

def obtener_datos_api(liga_odds, key_index=0):
    if key_index >= len(API_KEYS):
        print(f"   [ERROR] Todas las keys agotadas para {liga_odds}")
        return None, key_index
    api_key = API_KEYS[key_index]
    url = (f"https://api.the-odds-api.com/v4/sports/{liga_odds}/odds/"
           f"?apiKey={api_key}&regions=eu,us,uk,au&markets=h2h,totals"
           f"&bookmakers=pinnacle,bet365,1xBet,betfair_ex_eu,draftkings")
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json(), key_index
        elif resp.status_code in (429, 401):
            print(f"   [ALERTA] Key {key_index} agotada. Rotando...")
            return obtener_datos_api(liga_odds, key_index + 1)
        else:
            print(f"   [ERROR] HTTP {resp.status_code} para {liga_odds}")
            return None, key_index
    except Exception as e:
        print(f"   [ERROR] {e}")
        return None, key_index

def limpiar(texto):
    return gestor_nombres.limpiar_texto(texto)

def main():
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    with open(DICCIONARIO_FILE, 'r', encoding='utf-8') as f:
        diccionario = json.load(f)

    # Equipos que tenemos en la DB (futuros y pasados)
    cursor.execute("SELECT DISTINCT local  FROM partidos_backtest")
    equipos_db = {limpiar(r[0]): r[0] for r in cursor.fetchall()}
    cursor.execute("SELECT DISTINCT visita FROM partidos_backtest")
    for r in cursor.fetchall():
        equipos_db[limpiar(r[0])] = r[0]
    conn.close()

    key_actual = 0
    nuevas_entradas = {}   # clave_limpia -> nombre_api_original

    print("=" * 70)
    print("AUDITORIA DE NOMBRES: API DE CUOTAS vs BASE DE DATOS")
    print("=" * 70)

    for pais, liga_odds in MAPA_LIGAS_ODDS.items():
        print(f"\n{'='*70}")
        print(f"  {pais.upper()} ({liga_odds})")
        print(f"{'-'*70}")

        datos_api, key_actual = obtener_datos_api(liga_odds, key_actual)
        if not datos_api:
            print("  [SKIP] Sin datos de API")
            continue

        # Recopilar todos los nombres únicos que devuelve la API para esta liga
        nombres_api = set()
        for evento in datos_api:
            nombres_api.add(evento.get("home_team", ""))
            nombres_api.add(evento.get("away_team", ""))

        print(f"  Nombres en API ({len(nombres_api)}):")
        for nombre_api in sorted(nombres_api):
            clave = limpiar(nombre_api)

            # ¿Está ya en el diccionario?
            if clave in diccionario:
                nombre_std = diccionario[clave]
                print(f"    [OK-DICC ] {nombre_api!r:40} -> {nombre_std}")
                continue

            # ¿Coincide directamente con un equipo de la DB?
            if clave in equipos_db:
                print(f"    [OK-DB   ] {nombre_api!r:40} -> {equipos_db[clave]}")
                continue

            # No hay match — buscar el más parecido en la DB
            candidatos = list(equipos_db.keys())
            matches = difflib.get_close_matches(clave, candidatos, n=1, cutoff=0.6)
            if matches:
                sugerido_clave = matches[0]
                sugerido_nombre = equipos_db[sugerido_clave]
                print(f"    [FUZZY   ] {nombre_api!r:40} -> ¿{sugerido_nombre}?  (agregar: \"{clave}\": \"{sugerido_nombre}\")")
                nuevas_entradas[clave] = (nombre_api, sugerido_nombre)
            else:
                print(f"    [SIN MATCH] {nombre_api!r:40}  (no se encontro equipo similar en DB)")
                nuevas_entradas[clave] = (nombre_api, None)

    # --- Resumen final ---
    print(f"\n{'=' * 70}")
    print("ENTRADAS SUGERIDAS PARA diccionario_equipos.json")
    print(f"{'=' * 70}")
    if not nuevas_entradas:
        print("  Todo OK, no hay entradas nuevas necesarias.")
    else:
        print("  Copia las que sean correctas al diccionario:\n")
        for clave, (nombre_api, sugerido) in sorted(nuevas_entradas.items()):
            if sugerido:
                print(f'    "{clave}": "{sugerido}",   // API usa: {nombre_api!r}')
            else:
                print(f'    "{clave}": "???",           // API usa: {nombre_api!r} — sin match, revisar manualmente')

if __name__ == "__main__":
    main()

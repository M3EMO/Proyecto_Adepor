import sqlite3
import requests
import unicodedata
import json
import os
import csv
import difflib

# ==========================================
# MOTOR AUDITOR V1.0 (EL CARTÓGRAFO)
# Responsabilidad: Escanear ESPN (DATA) y The-Odds-API, cruzar entidades y armar el JSON.
# ==========================================

DICCIONARIO_FILE = 'diccionario_equipos.json'
CSV_DATA = 'Apuestas deportivas _ Calculadora - Data.csv'
DB_NAME = 'fondo_quant.db'

# 🚨 PON TUS LLAVES AQUÍ 🚨
API_KEYS = [
    "f66391a91a19e99bce4666178474bd18"
]

MAPA_LIGAS_ODDS = {

    "Brasil": "soccer_brazil_campeonato",

}

def normalizar(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')

def obtener_vocabulario_espn():
    """Extrae todos los nombres de equipos desde tu pestaña DATA (CSV) y SQLite"""
    equipos_espn = set()
    
    # 1. Intentar leer el CSV "DATA" directamente
    if os.path.exists(CSV_DATA):
        try:
            with open(CSV_DATA, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if 'Equipo' in row: equipos_espn.add(normalizar(row['Equipo']))
        except Exception as e:
            print(f"⚠️ Error leyendo CSV DATA: {e}")

    # 2. Leer desde la Base de Datos (SQLite) como respaldo
    if os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT local, visita FROM partidos_backtest")
            for loc, vis in cursor.fetchall():
                equipos_espn.add(normalizar(loc))
                equipos_espn.add(normalizar(vis))
            conn.close()
        except: pass

    return list(equipos_espn)

def obtener_vocabulario_odds():
    """Descarga todos los equipos activos de The-Odds-API en este momento"""
    equipos_odds = set()
    
    for pais, codigo_api in MAPA_LIGAS_ODDS.items():
        for api_key in API_KEYS:
            if not api_key or "PEGA" in api_key: continue
            url = f"https://api.the-odds-api.com/v4/sports/{codigo_api}/odds/?apiKey={api_key}&regions=eu&markets=h2h"
            
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    for evento in resp.json():
                        equipos_odds.add(evento.get("home_team", ""))
                        equipos_odds.add(evento.get("away_team", ""))
                    break  # Éxito, pasamos al siguiente país
            except:
                continue
                
    return list(equipos_odds)

def main():
    print("🕵️‍♂️ Iniciando Auditoría de Ligas (ESPN vs The-Odds-API)...")
    
    # 1. Cargar diccionario existente
    diccionario = {}
    if os.path.exists(DICCIONARIO_FILE):
        with open(DICCIONARIO_FILE, 'r', encoding='utf-8') as f:
            diccionario = json.load(f)

    # 2. Recolectar Vocabularios
    print("📥 Extrayendo equipos de tu pestaña DATA (ESPN)...")
    vocab_espn = obtener_vocabulario_espn()
    print(f"   ✓ {len(vocab_espn)} equipos encontrados en tu base.")

    print("📥 Descargando catálogo de The-Odds-API...")
    vocab_odds = obtener_vocabulario_odds()
    print(f"   ✓ {len(vocab_odds)} equipos detectados en las casas de apuestas.")

    # 3. Cruzar Entidades (El Cerebro Auditor)
    print("\n⚔️ Cruzando Entidades (Resolución Lingüística)...")
    nuevos_mapeos = 0
    conflictos = []

    for equipo_api in vocab_odds:
        n_api = normalizar(equipo_api)
        
        # Si ya lo conocemos, lo saltamos
        if n_api in diccionario:
            continue
            
        # Búsqueda 1: Coincidencia Exacta
        if n_api in vocab_espn:
            diccionario[n_api] = n_api
            nuevos_mapeos += 1
            print(f"   ✅ [EXACTO] '{equipo_api}' agregado automáticamente.")
            continue
            
        # Búsqueda 2: Lógica Difusa (Fuzzy Matching > 75% similitud)
        matches = difflib.get_close_matches(n_api, vocab_espn, n=1, cutoff=0.75)
        if matches:
            diccionario[n_api] = matches[0]
            nuevos_mapeos += 1
            print(f"   🤖 [IA DIFUSA] '{equipo_api}' emparejado con '{matches[0]}' de tu DATA.")
        else:
            conflictos.append(equipo_api)

    # 4. Guardar resultados
    if nuevos_mapeos > 0:
        with open(DICCIONARIO_FILE, 'w', encoding='utf-8') as f:
            json.dump(diccionario, f, indent=4, ensure_ascii=False)
        print(f"\n💾 Diccionario actualizado: Se agregaron {nuevos_mapeos} equipos nuevos al JSON.")
    else:
        print("\nℹ️ El diccionario está al día. No se detectaron equipos nuevos.")

    # 5. Reporte de Conflictos (Lo que la IA no pudo resolver)
    if conflictos:
        print("\n🚨 REPORTE DE CONFLICTOS (Requieren tu atención manual en el JSON):")
        for c in conflictos:
            print(f"   ❌ No encontré pareja en tu DATA para: '{c}'")
    
    print("\n✅ Auditoría finalizada.")

if __name__ == "__main__":
    main()
import json
import unicodedata
import re
import difflib
import os

# ==========================================
# GESTOR DE NOMBRES V4.0 (MOTOR DE ALIAS Y SUFIJOS HEURÍSTICOS)
# ==========================================

DICCIONARIO_FILE = 'diccionario_equipos.json'

# Sufijos geográficos/comerciales a ser ignorados durante la búsqueda.
SUFIJOS_RUIDO = {"pr", "mg", "rj", "sp", "rs", "go", "ba", "fc", "jrs", "united", "city"}

def cargar_diccionario():
    if os.path.exists(DICCIONARIO_FILE):
        with open(DICCIONARIO_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return {}
    return {}

def guardar_diccionario(dic):
    with open(DICCIONARIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(dic, f, indent=4, ensure_ascii=False)

def limpiar_texto(texto):
    if not texto: return ""
    texto_norm = ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', texto_norm)

def generar_candidatos_raiz(nombre_limpio):
    """
    Genera una lista de candidatos para un nombre, eliminando sufijos comunes.
    Ej: 'athleticopr' -> ['athleticopr', 'athletico']
    """
    candidatos = {nombre_limpio}
    for sufijo in SUFIJOS_RUIDO:
        if nombre_limpio.endswith(sufijo):
            raiz = nombre_limpio[:-len(sufijo)]
            if raiz: # Evitar añadir strings vacíos
                candidatos.add(raiz)
    return list(candidatos)

def son_equivalentes(nombre1, nombre2, diccionario, umbral_similitud=0.85):
    """Función centralizada para comparar dos nombres de fuentes distintas."""
    limpio1 = limpiar_texto(nombre1)
    limpio2 = limpiar_texto(nombre2)

    if not limpio1 or not limpio2: return False

    # 1. Match exacto
    if limpio1 == limpio2: return True

    # 2. Chequeo cruzado en diccionario
    val_dicc_1 = limpiar_texto(diccionario.get(limpio1, ""))
    val_dicc_2 = limpiar_texto(diccionario.get(limpio2, ""))
    if val_dicc_1 and val_dicc_1 == limpio2: return True
    if val_dicc_2 and val_dicc_2 == limpio1: return True

    # 3. Fuzzy Match como último recurso
    return difflib.SequenceMatcher(None, limpio1, limpio2).ratio() > umbral_similitud

def obtener_nombre_estandar(nombre_crudo, modo_interactivo=True):
    """
    Versión 4.0: Proceso de búsqueda y mapeo de nombres de equipo, inmune a variaciones de sufijos.
    """
    dic = cargar_diccionario()
    nombre_limpio = limpiar_texto(nombre_crudo)

    if not nombre_limpio:
        return nombre_crudo

    # --- FASE 1: BÚSQUEDA DIRECTA Y POR RAÍZ ---
    candidatos = generar_candidatos_raiz(nombre_limpio)
    for candidato in candidatos:
        if candidato in dic:
            nombre_oficial = dic[candidato]
            # Auto-aprendizaje: Si encontramos el nombre por su raíz, guardamos el alias completo para futuras búsquedas O(1).
            if nombre_limpio not in dic:
                dic[nombre_limpio] = nombre_oficial
                guardar_diccionario(dic)
            return nombre_oficial

    # --- FASE 2: BÚSQUEDA DE IDENTIDAD (¿ES UN NOMBRE OFICIAL?) ---
    valores_oficiales_unicos = list(set(dic.values()))
    for valor_oficial in valores_oficiales_unicos:
        if nombre_limpio == limpiar_texto(valor_oficial):
            dic[nombre_limpio] = valor_oficial
            guardar_diccionario(dic)
            return valor_oficial

    # --- FASE 3: LÓGICA DIFUSA AUTOMÁTICA (FUZZY MATCHING) ---
    AUTO_LEARN_CUTOFF = 0.80
    matches = difflib.get_close_matches(nombre_limpio, [limpiar_texto(v) for v in valores_oficiales_unicos], n=1, cutoff=AUTO_LEARN_CUTOFF)

    if matches:
        candidato_limpio_match = matches[0]
        candidato_oficial = next((v for v in valores_oficiales_unicos if limpiar_texto(v) == candidato_limpio_match), None)
        if candidato_oficial:
            dic[nombre_limpio] = candidato_oficial
            guardar_diccionario(dic)
            if modo_interactivo:
                 print(f"[APRENDIZAJE AUTOMATICO] Regla guardada por similitud: '{nombre_crudo}' -> '{candidato_oficial}'")
            return candidato_oficial

    # --- FASE 4: INTERVENCIÓN MANUAL (SI TODO FALLA Y EL MODO LO PERMITE) ---
    if not modo_interactivo:
        return nombre_crudo

    print(f"\n[ALERTA SEMANTICA] Nombre desconocido en la API: '{nombre_crudo}'")
    
    sugerencia_matches = difflib.get_close_matches(nombre_limpio, [limpiar_texto(v) for v in valores_oficiales_unicos], n=1, cutoff=0.55)

    if sugerencia_matches:
        candidato_limpio_sugerencia = sugerencia_matches[0]
        candidato_oficial_sugerencia = next(v for v in valores_oficiales_unicos if limpiar_texto(v) == candidato_limpio_sugerencia)
        
        respuesta = input(f"El equipo '{nombre_crudo}' es en realidad '{candidato_oficial_sugerencia}'? (S/N): ").strip().lower()
        if respuesta == 's':
            dic[nombre_limpio] = candidato_oficial_sugerencia
            guardar_diccionario(dic)
            print(f"[APRENDIZAJE] Regla guardada: {nombre_crudo} -> {candidato_oficial_sugerencia}")
            return candidato_oficial_sugerencia
            
    nuevo_oficial = input(f"Ingrese el nombre oficial para '{nombre_crudo}' (o Enter para mantenerlo como está): ").strip()
    
    if nuevo_oficial:
        dic[nombre_limpio] = nuevo_oficial
        guardar_diccionario(dic)
        print(f"[APRENDIZAJE] Nuevo equipo mapeado: {nombre_crudo} -> {nuevo_oficial}")
        return nuevo_oficial
    else:
        dic[nombre_limpio] = nombre_crudo
        guardar_diccionario(dic)
        return nombre_crudo
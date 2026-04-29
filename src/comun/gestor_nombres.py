import json
import unicodedata
import re
import difflib
import os
import warnings

# ==========================================
# GESTOR DE NOMBRES V5.0 — SCOPE POR LIGA
# ==========================================
# Cambio estructural (2026-04-23): diccionario_equipos.json pasa de dict plano a
# dict anidado por liga. El fuzzy matching queda scoped al sub-dict de la liga
# del contexto, eliminando falsos matches cross-liga (ej: "Lens"->"Leones" FRA/ECU,
# "Juventus"->"Juventud" ITA/URU, "Barcelona"->"Barcelona SC" ESP/ECU).
#
# Ademas, soporta COPAS INTERNACIONALES via _meta.ligas_por_copa: una copa como
# "Libertadores" se resuelve iterando sobre las ligas participantes sudamericanas.
# Las stats de cada equipo siguen viviendo en su liga_home (ver obtener_liga_home).
#
# Backwards-compat: si se llama sin `liga`, hace busqueda global (warning + scan
# de todas las sub-ligas). Los callers del pipeline deben migrar a pasar `liga`.

DICCIONARIO_FILE = 'diccionario_equipos.json'

# Sufijos geograficos/comerciales a ser ignorados durante la busqueda.
SUFIJOS_RUIDO = {"pr", "mg", "rj", "sp", "rs", "go", "ba", "fc", "jrs", "united", "city"}

# Cutoff del fuzzy. Con scope por liga ya es seguro bajarlo, pero mantengo 0.92
# para compatibilidad con el comportamiento previo.
AUTO_LEARN_CUTOFF = 0.95  # [bug-critico fuzzy 2026-04-28] subido de 0.92 a 0.95
                          # para evitar Rangers->Angers (sim=0.923) y similares.

# Claves reservadas del JSON (no son ligas).
_CLAVES_META = {"_meta", "_huerfanos"}


def cargar_diccionario():
    """Retorna el JSON completo (anidado v5.0 o plano v4.x legacy)."""
    if os.path.exists(DICCIONARIO_FILE):
        with open(DICCIONARIO_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}


def guardar_diccionario(dic):
    with open(DICCIONARIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(dic, f, indent=2, ensure_ascii=False)


def _es_formato_v5(dic):
    """Heuristica: v5 tiene _meta con equipo_a_liga_home, v4 es dict plano str->str."""
    return isinstance(dic, dict) and isinstance(dic.get('_meta'), dict) and 'equipo_a_liga_home' in dic['_meta']


def limpiar_texto(texto):
    if not texto:
        return ""
    texto_norm = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto).lower().strip())
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'[^a-z0-9]', '', texto_norm)


def generar_candidatos_raiz(nombre_limpio):
    """Genera candidatos para un nombre eliminando sufijos comunes."""
    candidatos = {nombre_limpio}
    for sufijo in SUFIJOS_RUIDO:
        if nombre_limpio.endswith(sufijo):
            raiz = nombre_limpio[:-len(sufijo)]
            if raiz:
                candidatos.add(raiz)
    return list(candidatos)


def _resolver_ligas_contexto(dic, liga):
    """
    Dado `liga` (contexto del partido) retorna las sub-ligas del dict donde buscar.
    - Liga domestica presente en el dict -> [liga]
    - Copa registrada en _meta.ligas_por_copa -> lista de ligas participantes
    - Desconocida o None -> todas las sub-ligas (fallback global).
    """
    if not _es_formato_v5(dic):
        return None  # formato legacy, caller usa el dict plano

    if liga is None:
        # Backwards-compat: sin liga, scan todas
        return [k for k in dic.keys() if k not in _CLAVES_META]

    if liga in dic and liga not in _CLAVES_META:
        return [liga]

    copas = dic.get('_meta', {}).get('ligas_por_copa', {})
    if liga in copas:
        return [l for l in copas[liga] if l in dic]

    # Liga desconocida -> fallback global con warning
    warnings.warn(
        f"gestor_nombres: liga '{liga}' no esta en el diccionario ni en _meta.ligas_por_copa. "
        "Cayendo a busqueda global (todas las sub-ligas).",
        stacklevel=3
    )
    return [k for k in dic.keys() if k not in _CLAVES_META]


def _sub_dict_merge(dic, ligas):
    """Merge de aliases de todas las sub-ligas dadas, preservando fuente."""
    merged = {}
    for liga in ligas:
        sub = dic.get(liga, {})
        if isinstance(sub, dict):
            merged.update(sub)
    return merged


def _obtener_dict_plano_para_uso(dic, liga=None):
    """Compat shim: devuelve un dict plano alias->oficial para el scope dado.
    Permite que `son_equivalentes` opere con el viejo contrato."""
    if not _es_formato_v5(dic):
        # Legacy flat
        return dic if isinstance(dic, dict) else {}
    ligas = _resolver_ligas_contexto(dic, liga)
    return _sub_dict_merge(dic, ligas or [])


def son_equivalentes(nombre1, nombre2, diccionario, liga=None, umbral_similitud=0.85):
    """Compara dos nombres (posiblemente desde fuentes distintas).
    Si el dict es v5, el cruce via diccionario queda scoped a la liga indicada.
    """
    limpio1 = limpiar_texto(nombre1)
    limpio2 = limpiar_texto(nombre2)
    if not limpio1 or not limpio2:
        return False

    # 1. Match exacto limpio
    if limpio1 == limpio2:
        return True

    # 2. Cross-check via diccionario (scoped)
    flat = _obtener_dict_plano_para_uso(diccionario, liga)
    val1 = limpiar_texto(flat.get(limpio1, ""))
    val2 = limpiar_texto(flat.get(limpio2, ""))
    if val1 and val1 == limpio2:
        return True
    if val2 and val2 == limpio1:
        return True

    # 3. Fuzzy final
    return difflib.SequenceMatcher(None, limpio1, limpio2).ratio() > umbral_similitud


def obtener_nombre_estandar(nombre_crudo, liga=None, modo_interactivo=True):
    """
    V5.0: Mapea un nombre crudo a su nombre oficial, opcionalmente scoped a una liga
    (liga domestica o copa internacional).

    Args:
        nombre_crudo: string tal como llega de una fuente externa (API, CSV).
        liga: pais ('Argentina','Italia','Francia',...) o copa ('Libertadores','Champions',...).
              Si None, hace busqueda global (legacy, warning).
        modo_interactivo: si True y todos los matches fallan, pide intervencion manual.
    """
    dic = cargar_diccionario()
    nombre_limpio = limpiar_texto(nombre_crudo)
    if not nombre_limpio:
        return nombre_crudo

    if not _es_formato_v5(dic):
        # Compat con formato v4 plano (caso de migracion incompleta): delega al path legacy
        return _obtener_nombre_estandar_legacy(nombre_crudo, nombre_limpio, dic, modo_interactivo)

    ligas_contexto = _resolver_ligas_contexto(dic, liga)
    if not ligas_contexto:
        ligas_contexto = [k for k in dic.keys() if k not in _CLAVES_META]

    # [SAFETY 2026-04-28 — bug-critico fuzzy] Detectar fallback global cuando liga
    # is None O liga no esta registrada en el diccionario ni en _meta.ligas_por_copa.
    # Sin scope acotado, fuzzy match es demasiado promiscuo (Rangers->Angers, etc).
    copas_meta = dic.get('_meta', {}).get('ligas_por_copa', {})
    es_fallback_global = (
        liga is None or
        (liga not in dic and liga not in copas_meta and liga not in _CLAVES_META)
    )
    scope = _sub_dict_merge(dic, ligas_contexto)

    # FASE 1: busqueda directa + raiz
    candidatos = generar_candidatos_raiz(nombre_limpio)
    for candidato in candidatos:
        if candidato in scope:
            nombre_oficial = scope[candidato]
            # Auto-aprendizaje: guardar alias completo en la liga del match.
            # Si son varias ligas (ambiguo), lo guardamos en la primera que contenga el valor.
            if nombre_limpio not in scope:
                liga_destino = _liga_de_nombre_oficial(dic, nombre_oficial, ligas_contexto)
                if liga_destino:
                    dic.setdefault(liga_destino, {})[nombre_limpio] = nombre_oficial
                    guardar_diccionario(dic)
            return nombre_oficial

    # FASE 2: identidad (el nombre crudo ES el oficial)
    valores_oficiales_unicos = list({v for v in scope.values()})
    for valor_oficial in valores_oficiales_unicos:
        if nombre_limpio == limpiar_texto(valor_oficial):
            liga_destino = _liga_de_nombre_oficial(dic, valor_oficial, ligas_contexto)
            if liga_destino:
                dic.setdefault(liga_destino, {})[nombre_limpio] = valor_oficial
                guardar_diccionario(dic)
            return valor_oficial

    # FASE 3: fuzzy scoped — SOLO si scope esta acotado.
    # En fallback global (liga desconocida o None) saltamos fuzzy para evitar
    # matches cross-country (Rangers->Angers, etc).
    if es_fallback_global:
        matches = []
    else:
        matches = difflib.get_close_matches(
            nombre_limpio,
            [limpiar_texto(v) for v in valores_oficiales_unicos],
            n=1, cutoff=AUTO_LEARN_CUTOFF
        )
    if matches:
        candidato_oficial = next(
            (v for v in valores_oficiales_unicos if limpiar_texto(v) == matches[0]),
            None
        )
        if candidato_oficial:
            # [SAFETY 2026-04-28 — bug-critico fuzzy cross-country] Si el oficial
            # pertenece a una liga distinta a las contexto, RECHAZAR el fuzzy match.
            # Casos historicos envenenados: 'rangers'->Angers, 'hatayspor'->Antalyaspor,
            # 'independientemedellin'->Independiente del Valle (cross Colombia/Ecuador).
            liga_destino = _liga_de_nombre_oficial(dic, candidato_oficial, ligas_contexto)
            if not liga_destino:
                # Cross-country fuzzy match -> NO persistir + caer a modo interactivo/crudo
                if modo_interactivo:
                    print(f"[FUZZY-REJECT] '{nombre_crudo}' fuzzy-matched a '{candidato_oficial}' "
                          f"pero pertenece a otra(s) liga(s) que {ligas_contexto}. Saltando.")
            else:
                dic.setdefault(liga_destino, {})[nombre_limpio] = candidato_oficial
                guardar_diccionario(dic)
                if modo_interactivo:
                    print(f"[APRENDIZAJE AUTOMATICO] ({liga_destino}) "
                          f"'{nombre_crudo}' -> '{candidato_oficial}'")
                return candidato_oficial

    # FASE 4: intervencion manual (solo si modo interactivo)
    if not modo_interactivo:
        return nombre_crudo

    print(f"\n[ALERTA SEMANTICA] Nombre desconocido en liga='{liga}': '{nombre_crudo}'")
    sugerencia = difflib.get_close_matches(
        nombre_limpio,
        [limpiar_texto(v) for v in valores_oficiales_unicos],
        n=1, cutoff=0.55
    )
    if sugerencia:
        cand_oficial = next(v for v in valores_oficiales_unicos if limpiar_texto(v) == sugerencia[0])
        respuesta = input(f"El equipo '{nombre_crudo}' es en realidad '{cand_oficial}'? (S/N): ").strip().lower()
        if respuesta == 's':
            liga_destino = _liga_de_nombre_oficial(dic, cand_oficial, ligas_contexto) or (liga if liga in dic else None)
            if liga_destino:
                dic.setdefault(liga_destino, {})[nombre_limpio] = cand_oficial
                guardar_diccionario(dic)
                print(f"[APRENDIZAJE] ({liga_destino}) {nombre_crudo} -> {cand_oficial}")
            return cand_oficial

    nuevo_oficial = input(f"Ingrese el nombre oficial para '{nombre_crudo}' (o Enter para mantener crudo): ").strip()
    if nuevo_oficial:
        liga_destino = liga if liga in dic else None
        if liga_destino:
            dic.setdefault(liga_destino, {})[nombre_limpio] = nuevo_oficial
            # Si es nombre nuevo, tambien registrar en equipo_a_liga_home
            meta = dic.setdefault('_meta', {}).setdefault('equipo_a_liga_home', {})
            if nuevo_oficial not in meta:
                meta[nuevo_oficial] = liga_destino
            guardar_diccionario(dic)
            print(f"[APRENDIZAJE] ({liga_destino}) {nombre_crudo} -> {nuevo_oficial}")
        return nuevo_oficial

    # Usuario no sabe: devolver crudo sin persistir (evita contaminar el dict)
    return nombre_crudo


def _liga_de_nombre_oficial(dic, nombre_oficial, ligas_contexto=None):
    """Devuelve la liga_home de un nombre oficial consultando _meta.equipo_a_liga_home.
    Si el equipo es ambiguo (lista) y ligas_contexto acota, devuelve la interseccion."""
    meta = dic.get('_meta', {}).get('equipo_a_liga_home', {})
    home = meta.get(nombre_oficial)
    if home is None:
        # Inferir buscando donde aparece como valor en las sub-ligas
        candidatos = [
            liga for liga, sub in dic.items()
            if liga not in _CLAVES_META and isinstance(sub, dict) and nombre_oficial in sub.values()
        ]
        if ligas_contexto:
            candidatos = [l for l in candidatos if l in ligas_contexto]
        return candidatos[0] if candidatos else None
    if isinstance(home, list):
        if ligas_contexto:
            interseccion = [l for l in home if l in ligas_contexto]
            if interseccion:
                return interseccion[0]
        return home[0]
    return home


def obtener_liga_home(nombre_oficial, contexto_liga=None):
    """
    Devuelve la liga domestica de un equipo (donde vive su historial de stats).
    Si el equipo es ambiguo (aparece en varias ligas), retorna:
      - el primer elemento acotado por `contexto_liga` (copa o liga especifica), o
      - el primer elemento de la lista si no hay contexto.

    Necesario para copas internacionales: Boca (Libertadores) -> 'Argentina',
    Flamengo (Libertadores) -> 'Brasil'.
    """
    dic = cargar_diccionario()
    if not _es_formato_v5(dic):
        return None
    ligas_contexto = _resolver_ligas_contexto(dic, contexto_liga) if contexto_liga else None
    return _liga_de_nombre_oficial(dic, nombre_oficial, ligas_contexto)


def _obtener_nombre_estandar_legacy(nombre_crudo, nombre_limpio, dic, modo_interactivo):
    """Path V4 plano — se conserva para transicion. Deprecable cuando toda la base migre."""
    warnings.warn(
        "diccionario_equipos.json no esta en formato v5.0. "
        "Corre scripts/migrar_diccionario_por_liga.py para habilitar scope por liga.",
        stacklevel=3
    )
    candidatos = generar_candidatos_raiz(nombre_limpio)
    for candidato in candidatos:
        if candidato in dic:
            nombre_oficial = dic[candidato]
            if nombre_limpio not in dic:
                dic[nombre_limpio] = nombre_oficial
                guardar_diccionario(dic)
            return nombre_oficial
    valores = list(set(dic.values()))
    for v in valores:
        if nombre_limpio == limpiar_texto(v):
            dic[nombre_limpio] = v
            guardar_diccionario(dic)
            return v
    matches = difflib.get_close_matches(nombre_limpio, [limpiar_texto(v) for v in valores], n=1, cutoff=AUTO_LEARN_CUTOFF)
    if matches:
        cand = next((v for v in valores if limpiar_texto(v) == matches[0]), None)
        if cand:
            dic[nombre_limpio] = cand
            guardar_diccionario(dic)
            if modo_interactivo:
                print(f"[APRENDIZAJE AUTOMATICO legacy] '{nombre_crudo}' -> '{cand}'")
            return cand
    return nombre_crudo

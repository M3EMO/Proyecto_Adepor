# ==========================================
# CONFIG SISTEMA — Constantes centralizadas (V1.0)
# Unica fuente de verdad para DB, ligas y estados del pipeline.
# Todos los motores deben importar desde aqui.
# Al agregar una liga: editar SOLO este archivo.
# ==========================================

import json
import os

# --- Base de datos ---
DB_NAME = 'fondo_quant.db'

# --- Ligas activas (codigo ESPN -> nombre interno) ---
# REGLA: sin tildes en valores ("Turquia" no "Turquía").
# El nombre interno es el usado en historial_equipos.liga, ligas_stats.liga,
# partidos_backtest.pais y en todos los diccionarios por liga del sistema.
LIGAS_ESPN = {
    "arg.1": "Argentina",
    "eng.1": "Inglaterra",
    "bra.1": "Brasil",
    "nor.1": "Noruega",
    "tur.1": "Turquia",
    "bol.1": "Bolivia",
    "chi.1": "Chile",
    "uru.1": "Uruguay",
    "per.1": "Peru",
    "ecu.1": "Ecuador",
    "col.1": "Colombia",
    "ven.1": "Venezuela",
}

# --- Mapeo nombre interno -> sport key de The-Odds-API ---
MAPA_LIGAS_ODDS = {
    "Argentina": "soccer_argentina_primera_division",
    "Inglaterra": "soccer_epl",
    "Brasil":     "soccer_brazil_campeonato",
    "Noruega":    "soccer_norway_eliteserien",
    "Turquia":    "soccer_turkey_super_league",
    "Bolivia":   None,                          # Sin cobertura en The-Odds-API (2026-04)
    "Chile":     "soccer_chile_campeonato",
    "Uruguay":   None,                          # Sin cobertura en The-Odds-API (2026-04)
    "Peru":      None,                          # Sin cobertura en The-Odds-API (2026-04)
    "Ecuador":   None,                          # Sin cobertura en The-Odds-API (2026-04)
    "Colombia":  None,                          # Sin cobertura en The-Odds-API (2026-04)
    "Venezuela": None,                          # Sin cobertura en The-Odds-API (2026-04)
}

# --- Mapeo nombre interno -> ID de liga en API-Football ---
MAPA_LIGAS_API_FOOTBALL = {
    "Argentina": 128,
    "Inglaterra": 39,
    "Brasil":     71,
    "Noruega":    69,
    "Turquia":    203,
    "Bolivia":   344,   # Primera Division Bolivia
    "Chile":     265,   # Primera Division Chile
    "Uruguay":   268,   # Primera Division - Apertura (liga principal activa)
    "Peru":      281,   # Primera Division Peru
    "Ecuador":   242,   # Liga Pro Ecuador
    "Colombia":  239,   # Primera A Colombia
    "Venezuela": 299,   # Primera Division Venezuela
}

# --- Estados del ciclo de vida de un partido ---
# Transicion: PENDIENTE -> CALCULADO -> FINALIZADO -> LIQUIDADO
# Nunca saltar estados ni retroceder.
ESTADO_PENDIENTE  = 'Pendiente'
ESTADO_CALCULADO  = 'Calculado'
ESTADO_FINALIZADO = 'Finalizado'
ESTADO_LIQUIDADO  = 'Liquidado'

# --- Claves API (cargadas desde config.json, nunca hardcodeadas) ---
# AJUSTE OBLIGADO POR REUBICACION (refactor 2026-04-17): este archivo se movio
# de raiz a src/comun/. PROJECT_ROOT compensa el cambio de __file__ para que
# _CONFIG_FILE resuelva al mismo path absoluto que antes. NO es modificacion funcional.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG_FILE = os.path.join(PROJECT_ROOT, 'config.json')
try:
    with open(_CONFIG_FILE, 'r', encoding='utf-8') as _f:
        _cfg = json.load(_f)
    API_KEYS_ODDS    = _cfg.get('api_keys_odds', [])
    API_KEY_FOOTBALL = _cfg.get('api_key_football', '')
    # Soporte multi-key para API-Football (fase 3.3.2): si config.json tiene la
    # lista api_keys_football, se rotan cuando la actual se agota (429 o quota llena).
    # Fallback a lista con solo la key legacy para compatibilidad.
    API_KEYS_FOOTBALL = _cfg.get('api_keys_football', [])
    if not API_KEYS_FOOTBALL and API_KEY_FOOTBALL:
        API_KEYS_FOOTBALL = [API_KEY_FOOTBALL]
except (FileNotFoundError, json.JSONDecodeError) as _e:
    print(f"[ADVERTENCIA config_sistema] No se pudo leer config.json: {_e}")
    API_KEYS_ODDS     = []
    API_KEY_FOOTBALL  = ''
    API_KEYS_FOOTBALL = []

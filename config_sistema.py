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
}

# --- Mapeo nombre interno -> sport key de The-Odds-API ---
MAPA_LIGAS_ODDS = {
    "Argentina": "soccer_argentina_primera_division",
    "Inglaterra": "soccer_epl",
    "Brasil":     "soccer_brazil_campeonato",
    "Noruega":    "soccer_norway_eliteserien",
    "Turquia":    "soccer_turkey_super_league",
}

# --- Mapeo nombre interno -> ID de liga en API-Football ---
MAPA_LIGAS_API_FOOTBALL = {
    "Argentina": 128,
    "Inglaterra": 39,
    "Brasil":     71,
    "Noruega":    69,
    "Turquia":    203,
}

# --- Estados del ciclo de vida de un partido ---
# Transicion: PENDIENTE -> CALCULADO -> FINALIZADO -> LIQUIDADO
# Nunca saltar estados ni retroceder.
ESTADO_PENDIENTE  = 'Pendiente'
ESTADO_CALCULADO  = 'Calculado'
ESTADO_FINALIZADO = 'Finalizado'
ESTADO_LIQUIDADO  = 'Liquidado'

# --- Claves API (cargadas desde config.json, nunca hardcodeadas) ---
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
try:
    with open(_CONFIG_FILE, 'r', encoding='utf-8') as _f:
        _cfg = json.load(_f)
    API_KEYS_ODDS    = _cfg.get('api_keys_odds', [])
    API_KEY_FOOTBALL = _cfg.get('api_key_football', '')
except (FileNotFoundError, json.JSONDecodeError) as _e:
    print(f"[ADVERTENCIA config_sistema] No se pudo leer config.json: {_e}")
    API_KEYS_ODDS    = []
    API_KEY_FOOTBALL = ''

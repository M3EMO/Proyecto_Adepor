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
    "esp.1": "Espana",   # LaLiga (piloto europeo incorporado 2026-04-21)
    # Big 5 europeo — completado 2026-04-21 (Italia/Alemania/Francia):
    "ita.1": "Italia",    # Serie A
    "ger.1": "Alemania",  # Bundesliga
    "fra.1": "Francia",   # Ligue 1
    # COPAS — agregadas 2026-04-28 (F2 sub-15) para integrar pipeline LIVE.
    # Slugs ESPN validados via sports.core.api.espn.com/v2/sports/soccer/leagues.
    # NOMBRE INTERNO debe coincidir con dic._meta.ligas_por_copa[k] para que
    # gestor_nombres resuelva equipos cross-source consistentemente.
    "uefa.champions": "Champions League",        # UCL
    "uefa.europa": "Europa League",               # UEL
    "uefa.europa.conf": "Conference League",      # UECL
    "conmebol.libertadores": "Libertadores",      # Conmebol
    "conmebol.sudamericana": "Sudamericana",
    "eng.fa": "FA Cup",                           # Copa nacional
    "eng.league_cup": "EFL Cup",
    "esp.copa_del_rey": "Copa del Rey",
    "ita.coppa_italia": "Coppa Italia",
    "fra.coupe_de_france": "Coupe de France",
    "ger.dfb_pokal": "DFB Pokal",
    "arg.copa": "Copa Argentina",
    "bra.copa_do_brazil": "Copa do Brasil",
    "conmebol.recopa": "Recopa Sudamericana",
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
    "Espana":    "soccer_spain_la_liga",         # LaLiga — cobertura activa con Pinnacle/Bet365
    # Big 5 europeo — completado 2026-04-21: cobertura plena en The-Odds-API
    "Italia":    "soccer_italy_serie_a",         # Serie A — verified active 2026-04-21
    "Alemania":  "soccer_germany_bundesliga",    # Bundesliga — verified active 2026-04-21
    "Francia":   "soccer_france_ligue_one",      # Ligue 1 — verified active 2026-04-21
    # COPAS — F2 sub-15 (2026-04-28). The-Odds-API tiene cobertura PARCIAL para
    # algunas copas EUR top. Por ahora None para copas; cuotas via API-Football
    # Pro plan (bloqueado adepor-4tb) o scraper alternativo (oddsportal).
    "Champions League":      "soccer_uefa_champs_league",
    "Europa League":         "soccer_uefa_europa_league",
    "Conference League":     "soccer_uefa_europa_conference_league",
    "Libertadores":          None,  # Sin cobertura confiable
    "Sudamericana":          None,
    "FA Cup":                "soccer_fa_cup",
    "EFL Cup":               None,
    "Copa del Rey":          None,
    "Coppa Italia":          None,
    "Coupe de France":       None,
    "DFB Pokal":             None,
    "Copa Argentina":        None,
    "Copa do Brasil":        None,
    "Recopa Sudamericana":   None,
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
    "Espana":    140,   # LaLiga (Primera Division Espana)
    # Big 5 europeo — completado 2026-04-21 (IDs verificados con API-Football 2026-04-21):
    "Italia":    135,   # Serie A (Italy) — temporada actual 2025/26
    "Alemania":  78,    # Bundesliga (Germany) — temporada actual 2025/26
    "Francia":   61,    # Ligue 1 (France) — temporada actual 2025/26
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

"""
MOTOR CUOTAS API-FOOTBALL — Capa secundaria para ligas sin cobertura en The Odds API.

Contexto (fase 3.2, 2026-04-21):
- The Odds API (motor_cuotas.py) cubre Argentina/Brasil/Inglaterra/Noruega/Turquia bien.
- NO cubre practicamente ninguna sudamericana (Ecuador/Peru/Bolivia/Colombia/Uruguay/Venezuela):
  90+ partidos sin cuota => pipeline descarta por PASAR Sin Cuotas.
- API-Football (api-sports.io) SI cubre estas ligas con 13+ bookmakers incluyendo
  Pinnacle, Bet365, William Hill. Free tier: 100 req/dia, ventana +-1 dia.

Este motor se ejecuta DESPUES de motor_cuotas.py y solo trabaja sobre partidos que
quedaron con cuotas nulas o en cero. No reescribe valores ya capturados.

Jerarquia de bookies: Pinnacle > Bet365 > William Hill > 10Bet > resto.
Mercados: Match Winner (id=1) => 1X2; Goals Over/Under (id=5) line 2.5 => O/U 2.5.
"""
import sqlite3
import requests
import difflib
import time
from datetime import datetime, timedelta, timezone

from src.comun import gestor_nombres
from src.comun.config_sistema import (
    DB_NAME, API_KEY_FOOTBALL, API_KEYS_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
)


BASE_URL = "https://v3.football.api-sports.io"

# Soporte multi-key (fase 3.3.2): rotamos si una key se agota.
# api_keys_football en config.json es la lista; fallback a key unica legacy.
_KEYS = list(API_KEYS_FOOTBALL) if API_KEYS_FOOTBALL else ([API_KEY_FOOTBALL] if API_KEY_FOOTBALL else [])
_KEY_IDX = 0


def _headers():
    if not _KEYS:
        return {}
    return {"x-apisports-key": _KEYS[_KEY_IDX]}


def _rotar_key(motivo=""):
    """Avanza al siguiente key. Devuelve True si quedan keys, False si se agotaron todas."""
    global _KEY_IDX
    if _KEY_IDX + 1 >= len(_KEYS):
        return False
    _KEY_IDX += 1
    print(f"      [ROTACION] Key agotada ({motivo}). Cambiando a key {_KEY_IDX + 1}/{len(_KEYS)}.")
    return True

# Ligas a cubrir: las que tradicionalmente quedan sin cuotas via The Odds API.
# Conservador: 6 sudamericanas + Chile (cobertura parcial en Odds API).
LIGAS_OBJETIVO = (
    "Ecuador", "Peru", "Bolivia", "Colombia", "Uruguay", "Venezuela", "Chile"
)

# Orden de preferencia por bookie (id verificados via /odds real 2026-04-21).
# Pinnacle=sharp de referencia; Bet365=mas liquidez; William Hill y 10Bet como fallback;
# Marathonbet y Betfair (exchange) para ligas menores donde las otras a veces no cotizan.
BOOKIES_SHARP = [
    ("Pinnacle", 4),
    ("Bet365", 8),
    ("William Hill", 7),
    ("10Bet", 1),
    ("Marathonbet", 2),
    ("Betfair", 3),
    ("Unibet", 16),
]

FUZZY_UMBRAL = 0.75


def _get(url, max_retries=2):
    """GET con retry y rotacion multi-key. Devuelve None si todas las keys fallan."""
    for intento in range(max_retries + 1):
        try:
            r = requests.get(url, headers=_headers(), timeout=(3, 8))
            if r.status_code == 200:
                data = r.json()
                # La API devuelve 200 incluso cuando la quota esta agotada; el
                # error viene en el body. Ej: {"errors": {"requests": "You have
                # reached the request limit for the day."}}
                errs = data.get("errors") if isinstance(data, dict) else None
                if isinstance(errs, dict) and ("requests" in errs or "plan" in errs):
                    if "requests" in errs:
                        if not _rotar_key("quota diaria agotada"):
                            return None
                        continue
                return data
            if r.status_code == 429:
                # Rate limit: rotar key si hay, si no esperar y reintentar
                if _rotar_key("429 rate limit"):
                    continue
                time.sleep(1.5)
                continue
            if r.status_code in (401, 403):
                # Key invalida o bloqueada
                if not _rotar_key(f"status {r.status_code}"):
                    return None
                continue
            return None
        except requests.exceptions.RequestException:
            if intento == max_retries:
                return None
            time.sleep(1.0)
    return None


def _status():
    """Devuelve requests consumidos/limite hoy (de la key activa)."""
    data = _get(f"{BASE_URL}/status")
    if not data or not data.get("response"):
        return None, None
    req = data["response"].get("requests", {})
    return req.get("current"), req.get("limit_day")


def _buscar_fixtures_dia(fecha_str):
    """Lista TODOS los fixtures del mundo para una fecha (YYYY-MM-DD).
    Free plan exige date+nada-mas: con league+date requiere season, y season>2024 esta
    bloqueada. Estrategia: 1 req por fecha para traer todo, filtrar por liga client-side.
    Es +eficiente: 3 req (hoy/manana/pasado) cubre el universo operativo.
    """
    url = f"{BASE_URL}/fixtures?date={fecha_str}"
    data = _get(url)
    if not data:
        return []
    return data.get("response", [])


def _obtener_odds_fixture(fixture_id):
    """Devuelve cuotas sharp (c1, cx, c2, co, cu) para un fixture.
    0.0 para los que no existan. Recorre bookies por jerarquia."""
    url = f"{BASE_URL}/odds?fixture={fixture_id}"
    data = _get(url)
    if not data or not data.get("response"):
        return 0.0, 0.0, 0.0, 0.0, 0.0
    resp = data["response"][0]
    bookmakers = resp.get("bookmakers", [])

    # Indexar por id de bookie
    bm_by_id = {bm.get("id"): bm for bm in bookmakers}

    c1 = cx = c2 = 0.0
    co = cu = 0.0

    # 1X2 (Match Winner id=1)
    for _, bm_id in BOOKIES_SHARP:
        bm = bm_by_id.get(bm_id)
        if not bm:
            continue
        for bet in bm.get("bets", []):
            if bet.get("id") != 1:
                continue
            for v in bet.get("values", []):
                val = v.get("value")
                try:
                    odd = float(v.get("odd", 0))
                except (TypeError, ValueError):
                    continue
                if val == "Home":
                    c1 = odd
                elif val == "Draw":
                    cx = odd
                elif val == "Away":
                    c2 = odd
            break
        if c1 > 0 and cx > 0 and c2 > 0:
            break

    # O/U 2.5 (Goals Over/Under id=5) - jerarquia igual
    for _, bm_id in BOOKIES_SHARP:
        bm = bm_by_id.get(bm_id)
        if not bm:
            continue
        co_tmp = cu_tmp = 0.0
        for bet in bm.get("bets", []):
            if bet.get("id") != 5:
                continue
            for v in bet.get("values", []):
                val = v.get("value", "")
                try:
                    odd = float(v.get("odd", 0))
                except (TypeError, ValueError):
                    continue
                if val == "Over 2.5":
                    co_tmp = odd
                elif val == "Under 2.5":
                    cu_tmp = odd
            break
        if co_tmp > 0 and cu_tmp > 0:
            co, cu = co_tmp, cu_tmp
            break

    return c1, cx, c2, co, cu


def _matchear_fixture(local_espn, visita_espn, eventos_index):
    """Match por normalizacion (exacto -> fuzzy >=0.75)."""
    loc_norm = gestor_nombres.limpiar_texto(local_espn)
    vis_norm = gestor_nombres.limpiar_texto(visita_espn)

    # Match exacto
    for ei in eventos_index:
        if ei["loc_norm"] == loc_norm and ei["vis_norm"] == vis_norm:
            return ei, 1.0

    # Fuzzy
    mejor_score = 0.0
    mejor_ei = None
    for ei in eventos_index:
        s_l = difflib.SequenceMatcher(None, loc_norm, ei["loc_norm"]).ratio()
        s_v = difflib.SequenceMatcher(None, vis_norm, ei["vis_norm"]).ratio()
        s = (s_l + s_v) / 2
        if s > mejor_score:
            mejor_score = s
            mejor_ei = ei
    if mejor_score >= FUZZY_UMBRAL:
        return mejor_ei, mejor_score
    return None, mejor_score


def main():
    print("[SISTEMA] Iniciando Motor Cuotas API-Football (capa sudamericana).")

    if not _KEYS:
        print("   [ERROR] No hay API key configurada (api_key_football / api_keys_football en config.json).")
        return

    print(f"   Keys disponibles: {len(_KEYS)} | activa: 1/{len(_KEYS)}")
    current, limit = _status()
    if current is not None:
        print(f"   Quota key activa: {current}/{limit} requests hoy")
        if limit and current >= limit - 5 and not _rotar_key("quota cerca del limite en key inicial"):
            print("   [WARN] Todas las keys cerca del limite diario, abortando.")
            return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Partidos vivos (no liquidados, sin cuota 1X2 ni O/U) en ligas objetivo
    cur.execute(f"""
        SELECT id_partido, local, visita, pais, fecha
        FROM partidos_backtest
        WHERE estado != 'Liquidado'
          AND goles_l IS NULL AND goles_v IS NULL
          AND pais IN ({",".join("?" * len(LIGAS_OBJETIVO))})
          AND (cuota_1 IS NULL OR cuota_1 = 0)
    """, LIGAS_OBJETIVO)
    partidos = cur.fetchall()

    if not partidos:
        print("[INFO] Sin partidos vivos faltantes de cuotas en ligas sudamericanas.")
        conn.close()
        return

    # Mapeo inverso: liga_id -> pais (para filtrar fixtures de la API por ligas objetivo)
    ligas_ids = {MAPA_LIGAS_API_FOOTBALL[p]: p for p in LIGAS_OBJETIVO if p in MAPA_LIGAS_API_FOOTBALL}

    # Solo operamos sobre la ventana +-1 dia del free plan (hoy-1, hoy, hoy+1).
    # El resto de fechas no puede consultarse y se ignora sin consumir req.
    hoy = datetime.now().date()
    ventana = {str(hoy - timedelta(days=1)), str(hoy), str(hoy + timedelta(days=1))}

    # Agrupar partidos por fecha (solo dentro de la ventana)
    por_fecha = {}
    fuera_ventana = 0
    for id_p, loc, vis, pais, fecha in partidos:
        dia = str(fecha).split(" ")[0] if fecha else ""
        if dia not in ventana:
            fuera_ventana += 1
            continue
        por_fecha.setdefault(dia, []).append((id_p, loc, vis, pais))

    if fuera_ventana:
        print(f"   [INFO] {fuera_ventana} partidos fuera de ventana +-1 dia (free plan no los cubre)")

    if not por_fecha:
        print("[INFO] Nada para consultar en la ventana permitida.")
        conn.close()
        return

    cuotas_actualizadas = 0
    sin_match = 0

    # --- POOL GLOBAL DE FIXTURES (resuelve time-shift UTC vs local) ---
    # API-Football indexa fixtures por UTC. Partidos nocturnos locales (ej Bolivia 21h)
    # caen al dia UTC siguiente. Solucion: fetch de las 3 fechas de ventana y
    # agrupar todo por liga_id SIN filtrar por dia. Matching agregado.
    por_liga_id = {}
    fetched_days = set()
    for dia in sorted(ventana):
        fixtures_raw = _buscar_fixtures_dia(dia)
        fetched_days.add(dia)
        if not fixtures_raw:
            continue
        for fx in fixtures_raw:
            lid = fx["league"]["id"]
            if lid not in ligas_ids:
                continue
            loc_api = fx["teams"]["home"]["name"]
            vis_api = fx["teams"]["away"]["name"]
            loc_std = gestor_nombres.obtener_nombre_estandar(loc_api, modo_interactivo=False)
            vis_std = gestor_nombres.obtener_nombre_estandar(vis_api, modo_interactivo=False)
            fx_id = fx["fixture"]["id"]
            # Evitar duplicados si la API retorna el mismo fixture en 2 dias distintos
            if any(e["fixture_id"] == fx_id for e in por_liga_id.get(lid, [])):
                continue
            por_liga_id.setdefault(lid, []).append({
                "fixture_id": fx_id,
                "fx_date": fx["fixture"]["date"],
                "loc_raw": loc_api,
                "vis_raw": vis_api,
                "loc_norm": gestor_nombres.limpiar_texto(loc_std),
                "vis_norm": gestor_nombres.limpiar_texto(vis_std),
            })

    print(f"   [POOL] {sum(len(v) for v in por_liga_id.values())} fixtures de {len(por_liga_id)} ligas objetivo en ventana {sorted(fetched_days)}")

    # Iterar partidos DB (ya filtrados por ventana) y matchear contra pool
    for dia, lista_partidos in por_fecha.items():
        for id_p, loc_espn, vis_espn, pais in lista_partidos:
            liga_id = MAPA_LIGAS_API_FOOTBALL.get(pais)
            eventos_liga = por_liga_id.get(liga_id, [])
            if not eventos_liga:
                print(f"   [SIN LIGA] {pais} {dia} {loc_espn} vs {vis_espn} — pool vacio para liga {liga_id}")
                sin_match += 1
                continue

            match, score = _matchear_fixture(loc_espn, vis_espn, eventos_liga)
            if match is None:
                print(f"   [SIN MATCH] {pais} {dia} {loc_espn} vs {vis_espn} (mejor score={score:.0%})")
                sin_match += 1
                continue

            c1, cx, c2, co, cu = _obtener_odds_fixture(match["fixture_id"])
            if c1 <= 0 and co <= 0:
                print(f"   [SIN ODDS] fx={match['fixture_id']} {pais} {loc_espn} vs {vis_espn}")
                continue

            cur.execute("""
                UPDATE partidos_backtest SET
                cuota_1   = CASE WHEN ? > 0 THEN ? ELSE cuota_1   END,
                cuota_x   = CASE WHEN ? > 0 THEN ? ELSE cuota_x   END,
                cuota_2   = CASE WHEN ? > 0 THEN ? ELSE cuota_2   END,
                cuota_o25 = CASE WHEN ? > 0 THEN ? ELSE cuota_o25 END,
                cuota_u25 = CASE WHEN ? > 0 THEN ? ELSE cuota_u25 END
                WHERE id_partido=?
            """, (c1, c1, cx, cx, c2, c2, co, co, cu, cu, id_p))
            cuotas_actualizadas += 1

            tag = f"[MATCH {score:.0%}]" if score < 1.0 else "[MATCH]"
            print(f"   {tag} {pais} {dia} {loc_espn} vs {vis_espn} | 1={c1} X={cx} 2={c2} O={co} U={cu}")

    conn.commit()
    conn.close()

    current2, _ = _status()
    delta = (current2 or 0) - (current or 0)
    print(f"[EXITO] API-Football: {cuotas_actualizadas} partidos con cuotas, {sin_match} sin match. Requests consumidos: {delta}")


if __name__ == "__main__":
    main()

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
    DB_NAME, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
)


BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY_FOOTBALL}

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
    """GET con retry basico. Devuelve None si falla."""
    for intento in range(max_retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(3, 8))
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                # Rate limit: esperar un poco y reintentar
                time.sleep(1.5)
                continue
            return None
        except requests.exceptions.RequestException:
            if intento == max_retries:
                return None
            time.sleep(1.0)
    return None


def _status():
    """Devuelve requests consumidos/limite hoy."""
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

    current, limit = _status()
    if current is not None:
        print(f"   Quota API-Football: {current}/{limit} requests hoy")
        if limit and current >= limit - 5:
            print("   [WARN] Cerca del limite diario, abortando para no bloquear la cuenta.")
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

    # Un request /fixtures por dia (cubre todas las ligas objetivo)
    for dia, lista_partidos in por_fecha.items():
        print(f"   [ESCANEO] Fecha {dia} — {len(lista_partidos)} partidos nuestros (ligas objetivo)")
        fixtures_raw = _buscar_fixtures_dia(dia)
        if not fixtures_raw:
            print(f"      [INFO] API-Football sin fixtures para {dia}")
            continue

        # Indexar fixtures API solo de las ligas objetivo
        por_liga_id = {}
        for fx in fixtures_raw:
            lid = fx["league"]["id"]
            if lid not in ligas_ids:
                continue
            loc_api = fx["teams"]["home"]["name"]
            vis_api = fx["teams"]["away"]["name"]
            loc_std = gestor_nombres.obtener_nombre_estandar(loc_api, modo_interactivo=False)
            vis_std = gestor_nombres.obtener_nombre_estandar(vis_api, modo_interactivo=False)
            por_liga_id.setdefault(lid, []).append({
                "fixture_id": fx["fixture"]["id"],
                "loc_raw": loc_api,
                "vis_raw": vis_api,
                "loc_norm": gestor_nombres.limpiar_texto(loc_std),
                "vis_norm": gestor_nombres.limpiar_texto(vis_std),
            })

        if not por_liga_id:
            print(f"      [INFO] Ninguna liga objetivo con fixtures en {dia}")
            continue

        for id_p, loc_espn, vis_espn, pais in lista_partidos:
            liga_id = MAPA_LIGAS_API_FOOTBALL.get(pais)
            eventos_liga = por_liga_id.get(liga_id, [])
            if not eventos_liga:
                print(f"      [SIN LIGA] {pais} {loc_espn} vs {vis_espn} — API no tiene fixtures de {pais} ese dia")
                sin_match += 1
                continue

            match, score = _matchear_fixture(loc_espn, vis_espn, eventos_liga)
            if match is None:
                print(f"      [SIN MATCH] {pais} {loc_espn} vs {vis_espn} (mejor score={score:.0%})")
                sin_match += 1
                continue

            c1, cx, c2, co, cu = _obtener_odds_fixture(match["fixture_id"])
            if c1 <= 0 and co <= 0:
                print(f"      [SIN ODDS] fx={match['fixture_id']} {pais} {loc_espn} vs {vis_espn}")
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
            print(f"      {tag} {pais} {loc_espn} vs {vis_espn} | 1={c1} X={cx} 2={c2} O={co} U={cu}")

    conn.commit()
    conn.close()

    current2, _ = _status()
    delta = (current2 or 0) - (current or 0)
    print(f"[EXITO] API-Football: {cuotas_actualizadas} partidos con cuotas, {sin_match} sin match. Requests consumidos: {delta}")


if __name__ == "__main__":
    main()

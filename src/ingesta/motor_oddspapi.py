"""
Captura forward de cuotas 1X2 en OddsPapi: Pinnacle contra bet365 AR (adepor-6kk).

Guarda una fila por partido, casa y captura en cuotas_forward. No toca partidos_backtest ni la
decision: es la base del estudio Pinnacle vs bet365 AR.
De las mismas respuestas guarda los totales de goles, corners y tarjetas en cuotas_forward_totales
(adepor-e9u), una fila por linea con over y under activos.
El plan gratis da 250 pedidos por mes, y cada pedido acepta 1 casa y 5 torneos. Con 2 casas y
20 torneos son 8 pedidos; el motor captura una vez por dia (unos 240 pedidos por mes, al limite).
Betano salio el 2026-10-22: su feed en OddsPapi es Betano Rumania (ro.betano.com), no argentino.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.comun.config_sistema import API_KEY_ODDSPAPI, DB_NAME, PROJECT_ROOT

URL = 'https://api.oddspapi.io/v4/odds-by-tournaments'
CASAS = ('pinnacle', 'bet365.bet.ar')  # la API acepta una casa por pedido
# Argentina, Libertadores, Sudamericana, Brasil, las 5 ligas top de Europa, Champions, Europa League,
# Chile, MLS, Liga MX y las segundas de prueba (Championship, Primera Nacional, Primera B de Chile).
# Uruguay, Colombia y Copa Argentina miden CLV contra la ultima captura de Pinnacle (sin The Odds API).
TORNEOS = (155, 384, 480, 325, 17, 8, 23, 35, 34, 7, 679, 27665, 242, 27464, 18, 703, 1240, 278, 27070, 1024)
TORNEOS_POR_PEDIDO = 5  # tope de la API
MERCADO_1X2 = '101'
OUTCOMES_1X2 = ('101', '102', '103')  # local, empate, visita
PAUSA = 1.5  # cooldown del endpoint: 1 s
# Cada linea de un total es un mercado propio; /v4/markets?sportId=10 da su handicap y sus outcomes.
MARKETS_CACHE = Path(PROJECT_ROOT) / 'data' / 'oddspapi' / 'markets_10.json'
TIPOS_TOTALES = {'totals': 'goles', 'totals-corners': 'corners', 'totals-bookings': 'tarjetas'}

SQL_CUOTAS_FORWARD = """
CREATE TABLE IF NOT EXISTS cuotas_forward (
    ts_captura TEXT NOT NULL, fixture_id TEXT NOT NULL, torneo_id INTEGER, inicio_utc TEXT,
    local_id INTEGER, visita_id INTEGER, casa TEXT NOT NULL,
    cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
    PRIMARY KEY (fixture_id, casa, ts_captura));
"""

SQL_CUOTAS_FORWARD_TOTALES = """
CREATE TABLE IF NOT EXISTS cuotas_forward_totales (
    ts_captura TEXT NOT NULL, fixture_id TEXT NOT NULL, casa TEXT NOT NULL,
    tipo TEXT NOT NULL, linea REAL NOT NULL, cuota_over REAL, cuota_under REAL,
    PRIMARY KEY (fixture_id, casa, tipo, linea, ts_captura));
"""


def filas_1x2(fixtures, ts, ahora_iso):
    """Filas (ts, fixture, torneo, inicio, local, visita, casa, c1, cx, c2) de partidos no empezados
    con las tres cuotas del 1X2 activas."""
    out = []
    for f in fixtures:
        if str(f.get('startTime') or '') <= ahora_iso:
            continue
        for casa, datos in (f.get('bookmakerOdds') or {}).items():
            outcomes = ((datos.get('markets') or {}).get(MERCADO_1X2) or {}).get('outcomes') or {}
            precios = []
            for o in OUTCOMES_1X2:
                jugador = ((outcomes.get(o) or {}).get('players') or {}).get('0') or {}
                precios.append(jugador.get('price') if jugador.get('active') else None)
            if all(p and p > 1 for p in precios):
                out.append((ts, f['fixtureId'], f.get('tournamentId'), f.get('startTime'),
                            f.get('participant1Id'), f.get('participant2Id'), casa, *precios))
    return out


def mapa_totales(markets):
    """{marketId: (tipo, linea, outcome over, outcome under)} de los totales de partido completo."""
    out = {}
    for m in markets:
        tipo = TIPOS_TOTALES.get(m.get('marketType'))
        if tipo is None or m.get('period') != 'fulltime' or m.get('playerProp'):
            continue
        oid = {o['outcomeName']: str(o['outcomeId']) for o in m.get('outcomes') or []}
        if 'Over' in oid and 'Under' in oid:
            out[str(m['marketId'])] = (tipo, float(m['handicap']), oid['Over'], oid['Under'])
    return out


def filas_totales(fixtures, ts, ahora_iso, mapa):
    """Filas (ts, fixture, casa, tipo, linea, over, under) de partidos no empezados con las dos cuotas activas."""
    out = []
    for f in fixtures:
        if str(f.get('startTime') or '') <= ahora_iso:
            continue
        for casa, datos in (f.get('bookmakerOdds') or {}).items():
            for mid, mercado in (datos.get('markets') or {}).items():
                if mid not in mapa:
                    continue
                tipo, linea, o_over, o_under = mapa[mid]
                precios = []
                for o in (o_over, o_under):
                    jugador = ((mercado.get('outcomes') or {}).get(o) or {}).get('players', {}).get('0') or {}
                    precios.append(jugador.get('price') if jugador.get('active') else None)
                if all(p and p > 1 for p in precios):
                    out.append((ts, f['fixtureId'], casa, tipo, linea, *precios))
    return out


def main():
    if not API_KEY_ODDSPAPI:
        print('[ERROR] Falta api_key_oddspapi en config.json.')
        raise SystemExit(1)
    ahora = datetime.now(timezone.utc)
    ts, ahora_iso = ahora.strftime('%Y-%m-%dT%H:%M:%SZ'), ahora.strftime('%Y-%m-%dT%H:%M:%S')
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.executescript(SQL_CUOTAS_FORWARD + SQL_CUOTAS_FORWARD_TOTALES)
        # Una captura por dia UTC: la cascada corre dos veces y el cupo no alcanza para dos.
        if conn.execute('SELECT 1 FROM cuotas_forward WHERE ts_captura LIKE ?', (ts[:10] + '%',)).fetchone():
            print(f'[INFO] cuotas_forward ya tiene la captura del {ts[:10]}: no se gasta cupo.')
            return
        # Sin la cache de mercados la captura del 1X2 sigue; los totales quedan vacios.
        mapa = mapa_totales(json.loads(MARKETS_CACHE.read_text())) if MARKETS_CACHE.exists() else {}
        filas, totales = [], []
        for n, (casa, i) in enumerate((c, i) for c in CASAS for i in range(0, len(TORNEOS), TORNEOS_POR_PEDIDO)):
            lote = TORNEOS[i:i + TORNEOS_POR_PEDIDO]
            if n:
                time.sleep(PAUSA)
            try:
                r = requests.get(URL, params={'apiKey': API_KEY_ODDSPAPI, 'bookmaker': casa,
                                              'tournamentIds': ','.join(map(str, lote))}, timeout=60)
                r.raise_for_status()
            except requests.RequestException as e:
                # Solo el tipo y el codigo: la URL lleva la clave.
                print(f'[ALERTA] OddsPapi fallo para {casa} {lote}: {type(e).__name__} '
                      f'{getattr(e.response, "status_code", "")}')
                continue
            fixtures = r.json()
            filas += filas_1x2(fixtures, ts, ahora_iso)
            totales += filas_totales(fixtures, ts, ahora_iso, mapa)
        with conn:
            conn.executemany('INSERT OR IGNORE INTO cuotas_forward VALUES (?,?,?,?,?,?,?,?,?,?)', filas)
            conn.executemany('INSERT OR IGNORE INTO cuotas_forward_totales VALUES (?,?,?,?,?,?,?)', totales)
    finally:
        conn.close()
    por_casa = {}
    for f in filas:
        por_casa[f[6]] = por_casa.get(f[6], 0) + 1
    print(f'[EXITO] cuotas_forward: {len(filas)} filas {por_casa}; cuotas_forward_totales: {len(totales)} filas')


if __name__ == '__main__':
    main()

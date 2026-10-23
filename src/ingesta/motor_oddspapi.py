"""
Captura forward de cuotas 1X2 en OddsPapi: Pinnacle contra bet365 AR (adepor-6kk).

Guarda una fila por partido, casa y captura en cuotas_forward. No toca partidos_backtest ni la
decision: es la base del estudio Pinnacle vs bet365 AR.
El plan gratis da 250 pedidos por mes, y cada pedido acepta 1 casa y 5 torneos. Con 2 casas y
15 torneos son 6 pedidos; el motor captura una vez por dia (unos 185 pedidos por mes).
Betano salio el 2026-10-22: su feed en OddsPapi es Betano Rumania (ro.betano.com), no argentino.
"""
import sqlite3
import time
from datetime import datetime, timezone

import requests

from src.comun.config_sistema import API_KEY_ODDSPAPI, DB_NAME

URL = 'https://api.oddspapi.io/v4/odds-by-tournaments'
CASAS = ('pinnacle', 'bet365.bet.ar')  # la API acepta una casa por pedido
# Argentina, Copa Argentina, Libertadores, Sudamericana, Brasil, las 5 ligas top de Europa,
# Champions, Europa League, Chile, Uruguay y Colombia.
TORNEOS = (155, 1024, 384, 480, 325, 17, 8, 23, 35, 34, 7, 679, 27665, 278, 27070)
TORNEOS_POR_PEDIDO = 5  # tope de la API
MERCADO_1X2 = '101'
OUTCOMES_1X2 = ('101', '102', '103')  # local, empate, visita
PAUSA = 1.5  # cooldown del endpoint: 1 s

SQL_CUOTAS_FORWARD = """
CREATE TABLE IF NOT EXISTS cuotas_forward (
    ts_captura TEXT NOT NULL, fixture_id TEXT NOT NULL, torneo_id INTEGER, inicio_utc TEXT,
    local_id INTEGER, visita_id INTEGER, casa TEXT NOT NULL,
    cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
    PRIMARY KEY (fixture_id, casa, ts_captura));
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


def main():
    if not API_KEY_ODDSPAPI:
        print('[ERROR] Falta api_key_oddspapi en config.json.')
        raise SystemExit(1)
    ahora = datetime.now(timezone.utc)
    ts, ahora_iso = ahora.strftime('%Y-%m-%dT%H:%M:%SZ'), ahora.strftime('%Y-%m-%dT%H:%M:%S')
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.executescript(SQL_CUOTAS_FORWARD)
        # Una captura por dia UTC: la cascada corre dos veces y el cupo no alcanza para dos.
        if conn.execute('SELECT 1 FROM cuotas_forward WHERE ts_captura LIKE ?', (ts[:10] + '%',)).fetchone():
            print(f'[INFO] cuotas_forward ya tiene la captura del {ts[:10]}: no se gasta cupo.')
            return
        filas = []
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
            filas += filas_1x2(r.json(), ts, ahora_iso)
        with conn:
            conn.executemany('INSERT OR IGNORE INTO cuotas_forward VALUES (?,?,?,?,?,?,?,?,?,?)', filas)
    finally:
        conn.close()
    por_casa = {}
    for f in filas:
        por_casa[f[6]] = por_casa.get(f[6], 0) + 1
    print(f'[EXITO] cuotas_forward: {len(filas)} filas {por_casa}')


if __name__ == '__main__':
    main()

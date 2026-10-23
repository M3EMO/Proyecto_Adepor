"""
Captura forward de cuotas 1X2 de casas locales via FotMob `matchOdds` (estudio E1, docs/specs/13-estudios-forward.md).

Guarda en cuotas_forward, una fila por partido, casa y captura: la casa de FotMob (ccode ARG y GBR) y el
Pinnacle previo de partidos_backtest (`pinnacle_pb`), con el mismo ts. fixture_id = fm:<id FotMob>:<id_partido>.
No toca partidos_backtest. Uso: python -m src.ingesta.motor_cuotas_fotmob
"""
import difflib
import sqlite3
import time
from datetime import datetime, timezone

from curl_cffi import requests

from src.comun.config_sistema import DB_NAME
from src.ingesta.motor_oddspapi import SQL_CUOTAS_FORWARD
from src.nucleo.valor_v2 import prob_justa

API = 'https://www.fotmob.com/api/data/'
CCODES = ('ARG', 'GBR')  # 1xBet/Mostbet Argentina y Bet365 UK
MIN_SIM = 1.5  # suma de parecidos local+visita (maximo 2)
PAUSA = 0.7


def pedir(ruta):
    r = requests.get(API + ruta, headers={'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'},
                     impersonate='chrome', timeout=20)
    r.raise_for_status()
    return r.json()


def _sim(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def emparejar(partidos, calendario):
    """[(id_partido, id_fotmob)]. partidos: (id, local, visita, ...); calendario: (id_fm, home, away, ...).
    Descarta pares con nombres distintos o con local y visita invertidos."""
    out = []
    for p in partidos:
        pid, local, visita = p[:3]
        mejor = max(calendario, key=lambda m: _sim(m[1], local) + _sim(m[2], visita), default=None)
        if mejor is None:
            continue
        directo = _sim(mejor[1], local) + _sim(mejor[2], visita)
        invertido = _sim(mejor[1], visita) + _sim(mejor[2], local)
        if directo >= MIN_SIM and directo > invertido:
            out.append((pid, mejor[0]))
    return out


def fila_1x2(d):
    """(casa, c1, cx, c2) del mercado 1X2 de una respuesta matchOdds, o None si falta algo."""
    if not d:
        return None
    for m in (d.get('odds') or {}).get('matchfactMarkets') or []:
        if m.get('headerTranslationKey') != 'who_will_win':
            continue
        try:
            precios = [float(s['oddsDecimal']) for s in m['selections'][:3]]
        except (KeyError, ValueError, TypeError):
            return None
        if len(precios) == 3 and all(p > 1 for p in precios):
            return ((d.get('persistentKey') or 'desconocida').lower().replace(' ', '_') + '_fm', *precios)
    return None


def capturar(conn, ts, partidos, calendario, pedir_fn=pedir, pausa=PAUSA):
    """Guarda las cuotas de FotMob y el Pinnacle previo. partidos: (id, local, visita, pin_1, pin_x, pin_2).
    Devuelve las filas preparadas; INSERT OR IGNORE evita duplicar una captura repetida."""
    por_id = {m[0]: m for m in calendario}
    pin = {p[0]: p[3:6] for p in partidos}
    filas = []
    for pid, fm in emparejar(partidos, calendario):
        m = por_id[fm]
        base = (f'fm:{fm}:{pid}', m[4] if len(m) > 4 else None, m[3] if len(m) > 3 else None, None, None)
        casas = []
        for cc in CCODES:
            try:
                f = fila_1x2(pedir_fn(f'matchOdds?matchId={fm}&ccode3={cc}'))
            except Exception:  # un pedido caido no frena el lote
                f = None
            time.sleep(pausa)
            if f:
                casas.append(f)
        if casas:
            casas.append(('pinnacle_pb', *pin[pid]))
        filas += [(ts, base[0], base[1], base[2], base[3], base[4], *c) for c in casas]
    conn.executemany('INSERT OR IGNORE INTO cuotas_forward VALUES (?,?,?,?,?,?,?,?,?,?)', filas)
    conn.commit()
    return len(filas)


def clv_apuestas(conn, cierres, umbral):
    """[(casa, CLV)] de la apuesta simulada: primera captura con EV previo > umbral contra el Pinnacle de esa
    captura, valorada con la cuota guardada y el cierre de Pinnacle. cierres: {id_partido: (c1, cx, c2)}."""
    filas = conn.execute("SELECT ts_captura, fixture_id, casa, cuota_1, cuota_x, cuota_2 FROM cuotas_forward "
                         "WHERE fixture_id LIKE 'fm:%' ORDER BY ts_captura").fetchall()
    pinn = {(f[0], f[1]): f[3:6] for f in filas if f[2] == 'pinnacle_pb'}
    hechas, out = set(), []
    for ts, fid, casa, *cuotas in filas:
        if casa == 'pinnacle_pb' or (ts, fid) not in pinn:
            continue
        pid = fid.split(':', 2)[2]
        p_prev, p_cierre = prob_justa(list(pinn[(ts, fid)])), prob_justa(list(cierres.get(pid) or ()))
        if not p_prev or not p_cierre:
            continue
        for i, c in enumerate(cuotas):
            if (fid, casa, i) not in hechas and c * p_prev[i] - 1 > umbral:
                hechas.add((fid, casa, i))
                out.append((casa, c * p_cierre[i] - 1))
    return out


def main():
    conn = sqlite3.connect(DB_NAME)
    conn.executescript(SQL_CUOTAS_FORWARD)
    proximos = ("estado = 'Pendiente' AND pin_1 > 0 AND fecha BETWEEN datetime('now', 'localtime') "
                "AND datetime('now', 'localtime', '+60 hours')")
    partidos = conn.execute(f"SELECT id_partido, local, visita, pin_1, pin_x, pin_2 FROM partidos_backtest WHERE {proximos}").fetchall()
    cal = []
    for dia in sorted({r[0] for r in conn.execute(f"SELECT substr(replace(fecha, '-', ''), 1, 8) FROM partidos_backtest WHERE {proximos}")}):
        for lg in pedir(f'matches?date={dia}&timezone=America/Argentina/Buenos_Aires&ccode3=ARG')['leagues']:
            cal += [(m['id'], m['home']['name'], m['away']['name'], m['status'].get('utcTime'), lg['primaryId'])
                    for m in lg['matches'] if not m['status'].get('finished')]
        time.sleep(PAUSA)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'[EXITO] cuotas_forward (FotMob): {capturar(conn, ts, partidos, cal)} filas, {len(partidos)} partidos con Pinnacle')


if __name__ == '__main__':
    main()

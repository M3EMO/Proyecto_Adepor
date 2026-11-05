"""
Captura de cuotas de Betano AR para medir (no recalcula picks ni toca la decision).

Betano AR no tiene feed util en OddsPapi (el de OddsPapi es Betano Rumania) y DataDome bloquea
las llamadas fuera del navegador. La cuota la lee el bot semi-automatico desde la pagina real y
la guarda aqui: una fila por evento y captura en cuotas_forward, casa 'betano_ar'. Sin cambio de esquema.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from src.comun.config_sistema import PROJECT_ROOT
from src.comun.gestor_nombres import limpiar_texto
from src.nucleo.valor_v2 import cuota_minima

CASA = 'betano_ar'
_DICCIONARIO = os.path.join(PROJECT_ROOT, 'diccionario_equipos.json')
_PREFIJOS = ('ca', 'club', 'clubatletico', 'cd', 'fc')  # Betano antepone "CA " a varios clubes


def canonico(nombre, pais, diccionario):
    """Nombre canonico del club segun el diccionario de su liga, o None si no esta."""
    alias = diccionario.get(pais, {})
    clave = limpiar_texto(nombre)
    if clave in alias:
        return alias[clave]
    for p in _PREFIJOS:  # shortcut: un solo prefijo, cubre los casos vistos; ampliar con evidencia
        if clave.startswith(p) and clave[len(p):] in alias:
            return alias[clave[len(p):]]
    return None


def cargar_diccionario():
    with open(_DICCIONARIO, encoding='utf-8') as f:
        return json.load(f)


def mismo_partido(local_bt, visita_bt, local, visita, pais, diccionario):
    """True si los dos clubes de Betano resuelven a los clubes del pick, con la misma orientacion."""
    a, b = canonico(local_bt, pais, diccionario), canonico(visita_bt, pais, diccionario)
    return a is not None and b is not None and (a, b) == (canonico(local, pais, diccionario),
                                                         canonico(visita, pais, diccionario))


def guardar_cuota(conn, ts, evento_id, inicio_utc, c1, cx, c2):
    """Una fila de 1X2 de Betano AR. Valida las tres cuotas: una cuota <= 1 es un parseo roto."""
    if not all(c and c > 1 for c in (c1, cx, c2)):
        raise ValueError(f'cuotas invalidas: {c1}, {cx}, {c2}')
    with conn:
        conn.execute("INSERT OR IGNORE INTO cuotas_forward (ts_captura, fixture_id, inicio_utc, casa, "
                     "cuota_1, cuota_x, cuota_2) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (ts, f'bt:{evento_id}', inicio_utc, CASA, c1, cx, c2))


# GET de lectura que se ejecuta dentro de la pestaña de Betano (pasa DataDome con la sesion del navegador).
JS_LECTURA = ("fetch('/api/league/hot/upcoming?leagueId={liga}&timeZoneId=America/Buenos_Aires&req=s,stnf,c,mb')"
              ".then(r => r.json())")
VENTANA_INICIO_H = 3  # el inicio de Betano y el del pick deben coincidir; separa partidos repetidos


def eventos_1x2(respuesta):
    """Eventos de la respuesta de Betano con su 1X2: id, local, visita, inicio_utc, vivo y
    [(selection_id, cuota)] en orden local, empate, visita. Omite lo que no tiene 1X2 completo."""
    out = []
    for e in respuesta['data']['events']:
        mres = next((m for m in e.get('markets', []) if m.get('type') == 'MRES'), None)
        equipos = e['name'].split(' - ')
        if not mres or len(mres['selections']) != 3 or len(equipos) != 2:  # un nombre con " - " se omite
            continue
        out.append({'id': e['id'], 'local': equipos[0], 'visita': equipos[1], 'vivo': bool(e.get('liveNow')),
                    'suspendido': bool(mres.get('suspended')),
                    'inicio_utc': datetime.fromtimestamp(e['startTime'] / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M'),
                    'selecciones': [(s['id'], s['price']) for s in mres['selections']]})
    return out


def capturar(conn, ts, eventos):
    """Guarda el 1X2 de los eventos no empezados y no suspendidos. Devuelve cuantos guardo."""
    n = 0
    for e in eventos:
        if e['vivo'] or e['suspendido']:
            continue
        (_, c1), (_, cx), (_, c2) = e['selecciones']
        guardar_cuota(conn, ts, e['id'], e['inicio_utc'], c1, cx, c2)
        n += 1
    return n


def elegir(pick, eventos, diccionario):
    """Cruza un pick de la simulacion con un evento de Betano. Devuelve (seleccion, motivo):
    seleccion = {'evento_id', 'seleccion_id', 'cuota'} o None, y motivo explica el descarte."""
    local, visita = pick['partido'].split(' vs ')
    t_pick = datetime.fromisoformat(pick['inicio'])
    for e in eventos:
        if not mismo_partido(e['local'], e['visita'], local, visita, pick['liga'], diccionario):
            continue
        if abs(datetime.fromisoformat(e['inicio_utc']) - t_pick) > timedelta(hours=VENTANA_INICIO_H):
            continue
        if e['vivo'] or e['suspendido']:
            return None, 'en vivo o suspendido'
        sel_id, cuota = e['selecciones'][pick['resultado']]
        if cuota < cuota_minima(pick['p_pin']):
            return None, f'cuota {cuota} bajo la minima {cuota_minima(pick["p_pin"]):.2f}'
        return {'evento_id': e['id'], 'seleccion_id': sel_id, 'cuota': cuota}, 'ok'
    return None, 'sin evento en Betano'

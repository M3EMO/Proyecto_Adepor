"""
Bot semi-automatico de Betano AR (esqueleto). Usa TU Chrome ya logueado por CDP: no lee ni guarda
cookies ni tokens. Lee las cuotas, las captura para medir y propone cada pick. NUNCA confirma la apuesta.

Chrome debe arrancar con:  google-chrome --remote-debugging-port=9222
Por defecto es simulacion: imprime el plan y no toca la pagina ni la base.
"""
import argparse
import json
import os
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from src.comun.config_sistema import DB_NAME, PROJECT_ROOT
from src.ingesta.betano_ar import JS_LECTURA, cargar_diccionario, capturar, elegir, eventos_1x2
from src.nucleo.valor_v2 import stake_v2
from src.persistencia.bankroll import obtener_bankroll_operativo
from src.persistencia.confirmaciones import ids_confirmados, picks_por_confirmar

LIGA_BETANO = {'Argentina': 195785}  # shortcut: solo Liga Profesional, agregar ligas con su leagueId
PERFIL = os.path.expanduser('~/.chrome-betano')
URL_BETANO = 'https://www.betano.bet.ar/sport/futbol/argentina/liga-profesional/195785/'
MIN_STAKE = 35.0     # ARS: minimo de Betano AR por apuesta


def _abrir_chrome(puerto):
    """Lanza Chrome con el perfil del bot (conserva la sesion de Betano) y espera el puerto."""
    subprocess.Popen(['google-chrome', f'--remote-debugging-port={puerto}', f'--user-data-dir={PERFIL}', URL_BETANO],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(20):
        time.sleep(1)
        with socket.socket() as sk:
            if sk.connect_ex(('localhost', puerto)) == 0:
                time.sleep(3)  # la pestana de Betano termina de cargar
                return


def abrir_pagina(cdp):
    from playwright.sync_api import sync_playwright
    puerto = int(cdp.rsplit(':', 1)[1])
    with socket.socket() as sk:
        if sk.connect_ex(('localhost', puerto)) != 0:
            _abrir_chrome(puerto)
    try:
        ctx = sync_playwright().start().chromium.connect_over_cdp(cdp).contexts[0]
        return next(p for p in ctx.pages if 'betano.bet.ar' in p.url)
    except Exception as e:  # sin Chrome del bot o sin pestana de Betano: el mensaje llega al dashboard
        raise SystemExit(f'No hay una pestana de Betano en {cdp}. Inicia sesion en la ventana que abrio el bot. '
                         f'Detalle: {type(e).__name__}')


def proponer_en_cupon(pagina, sel, stake):
    # Verificado en la pagina: data-selnid de la cuota == id de la seleccion del GET de cuotas.
    pagina.click(f'[data-qa="event-selection"][data-selnid="{sel["seleccion_id"]}"]')
    # Campo de stake del cupon para una apuesta simple; entero para evitar el separador decimal.
    pagina.fill(f'[id="stakeInput_1:SGL:{sel["seleccion_id"]}"]', str(int(stake)))
    # Termina ANTES de "Apostar": ese clic lo da una persona.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cdp', default='http://localhost:9222')
    ap.add_argument('--id', help='solo este id_partido (lo usa el boton del dashboard)')
    ap.add_argument('--picks', default=str(Path(PROJECT_ROOT) / 'data/oddspapi/clv_bet365ar.json'), help='informe de picks (para simular)')
    ap.add_argument('--ejecutar', action='store_true', help='sin esto solo imprime el plan')
    a = ap.parse_args()
    picks = json.loads(Path(a.picks).read_text())['simulacion']['picks']
    con = sqlite3.connect(DB_NAME)
    ahora = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')
    vivos = picks_por_confirmar(picks, ids_confirmados(con.cursor()), ahora)  # ya excluye la sombra
    if a.id:
        vivos = [p for p in vivos if p['id'] == a.id]
        if not vivos:
            raise SystemExit(f'El pick {a.id} ya no esta vigente (empezo, se registro o esta en sombra).')
    bankroll, dic, pagina = obtener_bankroll_operativo(con.cursor()), cargar_diccionario(), None
    if a.ejecutar:
        pagina = abrir_pagina(a.cdp)
    for liga in {p['liga'] for p in vivos if p['liga'] in LIGA_BETANO}:
        eventos = eventos_1x2(pagina.evaluate(JS_LECTURA.format(liga=LIGA_BETANO[liga]))) if pagina else []
        if pagina:
            print(f'[CAPTURA] {capturar(con, ahora, eventos)} eventos guardados')
        for p in (x for x in vivos if x['liga'] == liga):
            sel, motivo = elegir(p, eventos, dic) if eventos else (None, 'simulacion: sin lectura')
            stake = stake_v2(p['p_pin'], sel['cuota'], bankroll) if sel else 0.0
            if sel and stake < MIN_STAKE:  # no se sube al minimo: eso cambiaria el tamano que da Kelly
                sel, motivo = None, f'stake {stake} bajo el minimo de Betano ({MIN_STAKE})'
            print(f"{p['partido']} | {motivo} | stake {stake}")
            if sel and a.ejecutar:
                proponer_en_cupon(pagina, sel, stake)
                print(f"CARGADO en el cupon: stake {int(stake)}. Revisalo y pulsa Apostar en Betano.")


if __name__ == '__main__':
    main()

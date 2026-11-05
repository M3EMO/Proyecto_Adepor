"""
Aviso de escritorio al final de la cascada: picks de bet365 AR que se pueden confirmar en el dashboard.
No apuesta ni escribe la base. Sin sesion grafica (notify-send falla) solo imprime.
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # -I quita el directorio del script del path
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.persistencia.confirmaciones import ids_confirmados, picks_por_confirmar  # noqa: E402

INFORME = ROOT / 'data' / 'oddspapi' / 'clv_bet365ar.json'


def texto(vivos):
    lineas = [f"{p['inicio'][5:]} UTC · {p['partido']} · {p['pick']} a {p['cuota']}" for p in vivos[:8]]
    return '\n'.join(lineas + ([f'... y {len(vivos) - 8} mas'] if len(vivos) > 8 else []))


def main():
    if not INFORME.exists():
        return
    picks = json.loads(INFORME.read_text())['simulacion']['picks']
    con = sqlite3.connect(Path(DB_NAME).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        hechos = ids_confirmados(con.cursor())
    finally:
        con.close()
    vivos = picks_por_confirmar(picks, hechos, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M'))
    if not vivos:
        print('[INFO] Sin picks nuevos para confirmar.')
        return
    titulo, cuerpo = f'Adepor: {len(vivos)} picks para confirmar', texto(vivos)
    print(f'[AVISO] {titulo}\n{cuerpo}')
    # cron no hereda la sesion grafica: el bus del usuario esta en /run/user/<uid>/bus
    env = {**os.environ, 'DBUS_SESSION_BUS_ADDRESS': os.environ.get(
        'DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')}
    try:
        subprocess.run(['notify-send', '-a', 'Adepor', titulo, cuerpo], env=env, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'[ALERTA] notify-send fallo: {type(e).__name__}')


if __name__ == '__main__':
    main()

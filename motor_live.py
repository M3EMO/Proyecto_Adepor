"""
MOTOR LIVE V5.0 — Sniper Bot de senales a Telegram (re-armado 2026-04-23).

Lee picks vivos con stake > 0 desde partidos_backtest y envia alertas a
Telegram con toda la info relevante (cuota, prob, EV, stake, fecha, liga).

Respeta el pretest_mode: stake=0 en pretest -> NO envia alerta, el pick queda
solo en DB para medir hit. Cuando liga flipea a LIVE (auto o manual),
stake>0 -> sale la alerta automaticamente.

Cache persistente en tabla log_alertas para evitar duplicados entre corridas.

Uso:
  py motor_live.py              # loop infinito cada 60s (legacy behavior)
  py motor_live.py --once       # una corrida (ideal para ejecutar post-pipeline)
  py motor_live.py --dry-run    # una corrida SIN enviar a Telegram (test)
"""
import sqlite3
import sys
import time
from datetime import datetime

import requests

# Config del sistema (16 ligas, path DB)
from src.comun.config_sistema import DB_NAME, LIGAS_ESPN  # noqa: E402

# === Credenciales Telegram ===
# Ya expuestas en git history (decision usuario: no rotar)
TELEGRAM_TOKEN   = "8608474072:AAExuuk_Fncpsxlr6VfHpnRkSAKd15X7U54"
TELEGRAM_CHAT_ID = "6589570908"

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# -------------------------------------------------------------------
# Cache de alertas enviadas (tabla log_alertas)
# -------------------------------------------------------------------
def cargar_cache_alertas(cursor):
    """Crea tabla si no existe y precarga ids ya enviados."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_alertas (
            id_alerta TEXT PRIMARY KEY,
            partido TEXT,
            mercado TEXT,
            pick TEXT,
            stake_enviado REAL,
            timestamp TEXT
        )
    """)
    # Agregar columna timestamp si no existe (migracion suave)
    try:
        cursor.execute("ALTER TABLE log_alertas ADD COLUMN timestamp TEXT")
    except sqlite3.OperationalError:
        pass
    cursor.execute("SELECT id_alerta FROM log_alertas")
    return {row[0] for row in cursor.fetchall()}


# -------------------------------------------------------------------
# Telegram
# -------------------------------------------------------------------
def enviar_telegram(mensaje, dry_run=False):
    """Envia mensaje a Telegram. Si dry_run=True, solo imprime."""
    if dry_run:
        print(f"[DRY-RUN Telegram]\n{mensaje}\n" + "-" * 40)
        return True
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(TELEGRAM_URL, data=data, timeout=10)
        return r.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Telegram: {e}")
        return False


# -------------------------------------------------------------------
# Formateo de mensajes
# -------------------------------------------------------------------
def _fecha_display(fecha_raw):
    if not fecha_raw:
        return ""
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(fecha_raw).strip(), fmt).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue
    return str(fecha_raw)[:16]


def _extraer_pick_1x2(ap):
    """De '[APOSTAR] LOCAL' -> 'LOCAL'."""
    if not ap or '[APOSTAR]' not in str(ap):
        return None
    u = str(ap).upper()
    if 'LOCAL' in u: return 'LOCAL'
    if 'EMPATE' in u: return 'EMPATE'
    if 'VISITA' in u: return 'VISITA'
    return None


def _extraer_pick_ou(ap):
    """De '[APOSTAR] OVER 2.5' -> 'OVER 2.5'."""
    if not ap or '[APOSTAR]' not in str(ap):
        return None
    u = str(ap).upper()
    if 'OVER' in u or '+2.5' in u or 'MAS' in u:
        return 'OVER 2.5'
    if 'UNDER' in u or '-2.5' in u or 'MENOS' in u:
        return 'UNDER 2.5'
    return None


def formatear_mensaje_1x2(row):
    pick = _extraer_pick_1x2(row['apuesta_1x2'])
    if not pick:
        return None
    probs  = {'LOCAL': row['prob_1'], 'EMPATE': row['prob_x'], 'VISITA': row['prob_2']}
    cuotas = {'LOCAL': row['cuota_1'], 'EMPATE': row['cuota_x'], 'VISITA': row['cuota_2']}
    p = probs[pick] or 0
    c = cuotas[pick] or 0
    ev = p * c - 1 if (p and c) else 0
    prob_impl = (1 / c) if c else 0

    return (
        f"*[SEÑAL 1X2 · {row['pais']}]*\n"
        f"{row['local']} vs {row['visita']}\n"
        f"{_fecha_display(row['fecha'])}\n"
        f"\n"
        f"Pick: *{pick}*  |  Cuota: *{c:.2f}*\n"
        f"Prob modelo: {100*p:.1f}%  (mercado: {100*prob_impl:.1f}%)\n"
        f"EV: *{100*ev:+.1f}%*  |  Stake: *${row['stake_1x2']:,.2f}*"
    )


def formatear_mensaje_ou(row):
    pick = _extraer_pick_ou(row['apuesta_ou'])
    if not pick:
        return None
    po, pu = row['prob_o25'], row['prob_u25']
    co, cu = row['cuota_o25'], row['cuota_u25']
    if pick == 'OVER 2.5':
        p, c = po or 0, co or 0
    else:
        p, c = pu or 0, cu or 0
    ev = p * c - 1 if (p and c) else 0
    prob_impl = (1 / c) if c else 0

    return (
        f"*[SEÑAL GOLES · {row['pais']}]*\n"
        f"{row['local']} vs {row['visita']}\n"
        f"{_fecha_display(row['fecha'])}\n"
        f"\n"
        f"Pick: *{pick}*  |  Cuota: *{c:.2f}*\n"
        f"Prob modelo: {100*p:.1f}%  (mercado: {100*prob_impl:.1f}%)\n"
        f"EV: *{100*ev:+.1f}%*  |  Stake: *${row['stake_ou']:,.2f}*"
    )


# -------------------------------------------------------------------
# Core: scan picks y envio
# -------------------------------------------------------------------
COLS = [
    'id_partido', 'local', 'visita', 'pais', 'fecha',
    'apuesta_1x2', 'stake_1x2', 'apuesta_ou', 'stake_ou',
    'prob_1', 'prob_x', 'prob_2', 'prob_o25', 'prob_u25',
    'cuota_1', 'cuota_x', 'cuota_2', 'cuota_o25', 'cuota_u25',
]


def scan_y_enviar(conn, cursor, enviadas, dry_run=False):
    """Busca picks vivos con stake>0, envia a Telegram los nuevos.
    Devuelve (n_enviadas_1x2, n_enviadas_ou)."""
    cursor.execute(f"""
        SELECT {', '.join(COLS)}
        FROM partidos_backtest
        WHERE estado='Calculado' AND (stake_1x2 > 0 OR stake_ou > 0)
    """)
    rows = cursor.fetchall()

    envs_1x2 = envs_ou = 0
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for tup in rows:
        row = dict(zip(COLS, tup))
        id_p   = row['id_partido']
        partido = f"{row['local']} vs {row['visita']}"

        # Mercado 1X2
        if (row['apuesta_1x2'] and '[APOSTAR]' in str(row['apuesta_1x2'])
                and (row['stake_1x2'] or 0) > 0):
            id_alerta = f"{id_p}_1X2"
            if id_alerta not in enviadas:
                msg = formatear_mensaje_1x2(row)
                if msg and enviar_telegram(msg, dry_run=dry_run):
                    if not dry_run:
                        cursor.execute(
                            "INSERT OR IGNORE INTO log_alertas "
                            "(id_alerta, partido, mercado, pick, stake_enviado, timestamp) "
                            "VALUES (?, ?, '1X2', ?, ?, ?)",
                            (id_alerta, partido, row['apuesta_1x2'], row['stake_1x2'], timestamp)
                        )
                        enviadas.add(id_alerta)
                    envs_1x2 += 1
                    print(f"[OK 1X2] {partido} -> {_extraer_pick_1x2(row['apuesta_1x2'])} stk={row['stake_1x2']:.2f}")

        # Mercado O/U
        if (row['apuesta_ou'] and '[APOSTAR]' in str(row['apuesta_ou'])
                and (row['stake_ou'] or 0) > 0):
            id_alerta = f"{id_p}_OU"
            if id_alerta not in enviadas:
                msg = formatear_mensaje_ou(row)
                if msg and enviar_telegram(msg, dry_run=dry_run):
                    if not dry_run:
                        cursor.execute(
                            "INSERT OR IGNORE INTO log_alertas "
                            "(id_alerta, partido, mercado, pick, stake_enviado, timestamp) "
                            "VALUES (?, ?, 'O/U', ?, ?, ?)",
                            (id_alerta, partido, row['apuesta_ou'], row['stake_ou'], timestamp)
                        )
                        enviadas.add(id_alerta)
                    envs_ou += 1
                    print(f"[OK O/U] {partido} -> {_extraer_pick_ou(row['apuesta_ou'])} stk={row['stake_ou']:.2f}")

    if not dry_run:
        conn.commit()
    return envs_1x2, envs_ou


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    # Modo test: enviar un ping a Telegram y salir (verificacion de integracion)
    if '--test-msg' in sys.argv:
        msg = (
            "*[TEST Motor Live V5.0]*\n"
            f"Integracion Telegram OK · {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"Ligas monitoreadas: {len(LIGAS_ESPN)}"
        )
        ok = enviar_telegram(msg)
        print("[TEST-MSG] Enviado OK" if ok else "[TEST-MSG] FALLO")
        return

    modo_once = '--once' in sys.argv
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        modo_once = True  # dry-run siempre es one-shot

    print(f"[SISTEMA] Motor Live V5.0 iniciado. "
          f"modo={'DRY-RUN' if dry_run else ('ONCE' if modo_once else 'LOOP 60s')} "
          f"ligas={len(LIGAS_ESPN)}")

    while True:
        try:
            conn = sqlite3.connect(DB_NAME, isolation_level=None)
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')

            enviadas = cargar_cache_alertas(cursor)
            if modo_once:
                # En modo once mostrar cuantas hay en cache
                print(f"[CACHE] {len(enviadas)} alertas historicas ya enviadas.")

            envs_1x2, envs_ou = scan_y_enviar(conn, cursor, enviadas, dry_run=dry_run)
            print(f"[CICLO] Enviadas: 1X2={envs_1x2}  O/U={envs_ou}")
            conn.close()
        except sqlite3.Error as e:
            print(f"[ERROR] DB: {e}")
        except Exception as e:
            print(f"[ERROR] inesperado: {e}")

        if modo_once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()

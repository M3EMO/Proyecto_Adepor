"""
Apuestas confirmadas por el usuario (reemplaza a las alertas de Telegram, decision 2026-10-13).

Confirmar = "aposte este pick a esta cuota con este stake". Se registra en
apuestas_confirmadas y se escribe en partidos_backtest la cuota tomada y el stake real:
liquidador, bankroll y metricas existentes valoran asi el precio realmente obtenido.
Un partido confirmado queda congelado: motor_calculadora no lo recalcula y motor_cuotas
solo actualiza su cuota de cierre (CLV = tomada vs cierre).
"""
import sqlite3

from src.comun.tiempo import ahora_art

_COL_CUOTA = {'LOCAL': 'cuota_1', 'EMPATE': 'cuota_x', 'VISITA': 'cuota_2',
              'OVER 2.5': 'cuota_o25', 'UNDER 2.5': 'cuota_u25'}
_COLS_MERCADO = {'1X2': ('apuesta_1x2', 'stake_1x2'), 'OU': ('apuesta_ou', 'stake_ou')}

SQL_TABLA = """CREATE TABLE IF NOT EXISTS apuestas_confirmadas (
    id_partido TEXT NOT NULL, mercado TEXT NOT NULL, pick TEXT NOT NULL,
    cuota_tomada REAL NOT NULL, stake REAL NOT NULL, ts TEXT DEFAULT CURRENT_TIMESTAMP,
    casa TEXT, PRIMARY KEY (id_partido, mercado))"""
_PICKS_MERCADO = {'1X2': ('LOCAL', 'EMPATE', 'VISITA'), 'OU': ('OVER 2.5', 'UNDER 2.5')}


def _asegurar_tabla(conn):
    conn.execute(SQL_TABLA)
    if 'casa' not in [r[1] for r in conn.execute("PRAGMA table_info(apuestas_confirmadas)")]:
        conn.execute("ALTER TABLE apuestas_confirmadas ADD COLUMN casa TEXT")


def ids_confirmados(cursor):
    """id_partido con alguna apuesta confirmada (incluye alertas legacy de log_alertas)."""
    ids = set()
    try:
        ids.update(r[0] for r in cursor.execute("SELECT id_partido FROM apuestas_confirmadas"))
    except sqlite3.OperationalError:
        pass
    try:
        ids.update(r[0].rsplit('_', 1)[0] for r in cursor.execute("SELECT id_alerta FROM log_alertas")
                   if r[0] and '_' in r[0])
    except sqlite3.OperationalError:
        pass
    return ids


def confirmar_apuesta(conn, id_partido, mercado, cuota_tomada, stake, pick=None, casa=None):
    """Registra una apuesta real. Devuelve el pick confirmado.

    pick=None (v1): confirma el pick [APOSTAR] vigente del motor.
    pick dado (v2, D-019): el usuario elige el resultado; se escribe como [APOSTAR] <pick>.
    Valida cuota > 1, stake > 0 y que el partido no haya empezado.
    """
    if mercado not in _COLS_MERCADO:
        raise ValueError(f'mercado invalido: {mercado}')
    if not cuota_tomada or cuota_tomada <= 1 or not stake or stake <= 0:
        raise ValueError('cuota debe ser > 1 y stake > 0')
    col_ap, col_stk = _COLS_MERCADO[mercado]
    fila = conn.execute(f"SELECT {col_ap}, fecha FROM partidos_backtest WHERE id_partido=?",
                        (id_partido,)).fetchone()
    if not fila:
        raise ValueError(f'{id_partido} no existe')
    if pick is not None:
        if pick not in _PICKS_MERCADO[mercado]:
            raise ValueError(f'pick {pick} no pertenece al mercado {mercado}')
        fila = (f'[APOSTAR] {pick}', fila[1])
    elif not str(fila[0] or '').startswith('[APOSTAR]'):
        raise ValueError(f'{id_partido} no tiene un pick {mercado} vigente')
    if str(fila[1] or '') <= ahora_art().strftime('%Y-%m-%d %H:%M'):
        raise ValueError(f'{id_partido} ya empezo: no se confirma post-kickoff')
    pick = fila[0].replace('[APOSTAR]', '').strip()
    col_cuota = _COL_CUOTA.get(pick)
    if col_cuota is None:
        raise ValueError(f'pick no reconocido: {pick}')
    _asegurar_tabla(conn)
    if conn.execute("SELECT 1 FROM apuestas_confirmadas WHERE id_partido=? AND mercado=?",
                    (id_partido, mercado)).fetchone():
        raise ValueError(f'{id_partido} {mercado} ya esta confirmada')
    with conn:
        conn.execute("INSERT INTO apuestas_confirmadas (id_partido, mercado, pick, cuota_tomada, stake, casa) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (id_partido, mercado, pick, cuota_tomada, stake, casa))
        conn.execute(f"UPDATE partidos_backtest SET {col_ap}=?, {col_cuota}=?, {col_stk}=? WHERE id_partido=?",
                     (fila[0], cuota_tomada, stake, id_partido))
    return pick

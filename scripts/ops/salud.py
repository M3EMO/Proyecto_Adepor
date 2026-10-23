"""
Chequeo de salud del pipeline. Sale con 0 si todo esta bien y con 1 si algo falla.
Spec: docs/specs/12-producto-deploy.md. Cron sugerido: 0 * * * * (cada hora).

Uso: python -I scripts/ops/salud.py
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'fondo_quant.db'
LOGS = ROOT / 'data' / 'logs'
SNAPSHOTS = ROOT / 'snapshots'
ESTADO = LOGS / 'salud_estado.json'  # lo lee el dashboard para mostrar el aviso
ESTADO_MAX_SEG = 3 * 3600  # mas viejo que esto, el cron de salud no corre y el estado no es confiable


def log_reciente(carpeta, patron, max_seg, ahora):
    """El archivo mas nuevo que cumple `patron` se modifico hace menos de `max_seg`."""
    archivos = sorted(Path(carpeta).glob(patron), key=lambda p: p.stat().st_mtime)
    if not archivos:
        return False, f'{patron}: no hay archivos en {carpeta}'
    edad = ahora - archivos[-1].stat().st_mtime
    return edad <= max_seg, f'{archivos[-1].name}: {edad / 3600:.1f} h (maximo {max_seg / 3600:.1f} h)'


def integridad(db):
    try:
        r = sqlite3.connect(f'file:{db}?mode=ro', uri=True).execute('PRAGMA integrity_check').fetchone()[0]
    except sqlite3.DatabaseError as e:
        return False, f'base: {e}'
    return r == 'ok', f'base: integrity_check = {r}'


PROXIMOS = ("estado = 'Pendiente' AND fecha BETWEEN datetime('now', 'localtime') "
            "AND datetime('now', 'localtime', '+48 hours')")


def cuotas_pinnacle(db, max_frac):
    """Entre los proximos 48 h con cuota de mercado (`cuota_1`), fraccion sin Pinnacle previo (`pin_1`)."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    n, sin = con.execute("SELECT COUNT(*), COALESCE(SUM(pin_1 IS NULL OR pin_1 = 0), 0) "
                         f"FROM partidos_backtest WHERE {PROXIMOS} AND cuota_1 > 0").fetchone()
    frac = sin / n if n else 0.0
    return frac <= max_frac, f'cuotas Pinnacle: {sin}/{n} proximos con cuota sin pin_1 ({frac:.0%}, maximo {max_frac:.0%})'


def ligas_sin_cuotas(db):
    """Informativo: ligas con partidos proximos y ninguna cuota. No hace fallar el chequeo."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    ligas = [r[0] for r in con.execute(f"SELECT pais FROM partidos_backtest WHERE {PROXIMOS} "
                                       "GROUP BY pais HAVING SUM(cuota_1 > 0) = 0 ORDER BY pais")]
    return True, 'ligas sin ninguna cuota (aviso): ' + (', '.join(ligas) or 'ninguna')


def chequeos():
    ahora = time.time()
    return [
        log_reciente(LOGS, 'pipeline_*.log', 26 * 3600, ahora),
        log_reciente(LOGS, 'cierre_*.log', 30 * 60, ahora),
        integridad(DB),
        log_reciente(SNAPSHOTS, 'fondo_quant_*.db', 7 * 86400, ahora),
        cuotas_pinnacle(DB, 0.2),
        ligas_sin_cuotas(DB),
    ]


def leer_estado(ruta, ahora):
    """(ok, fallas) del ultimo chequeo, o None si falta, esta corrupto o es viejo."""
    try:
        ruta = Path(ruta)
        if ahora - ruta.stat().st_mtime > ESTADO_MAX_SEG:
            return None
        d = json.loads(ruta.read_text(encoding='utf-8'))
        return bool(d['ok']), list(d['fallas'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main():
    res = chequeos()
    for ok, msg in res:
        print(('OK    ' if ok else 'FALLA ') + msg)
    fallas = [msg for ok, msg in res if not ok]
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps({'ok': not fallas, 'fallas': fallas}), encoding='utf-8')
    return 1 if fallas else 0


if __name__ == '__main__':
    sys.exit(main())

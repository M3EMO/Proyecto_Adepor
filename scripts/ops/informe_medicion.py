"""
Informe de medicion: yield, CLV y calibracion de las apuestas reales.
Spec: docs/specs/12-producto-deploy.md. Solo cuenta partidos Liquidado con stake > 0 (contrato, regla 4).

Uso: python -I scripts/ops/informe_medicion.py [--db RUTA]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # -I quita el directorio del script del path
from src.comun.picks import cuota_para_pick  # noqa: E402
from src.comun.resolucion import determinar_resultado_entero  # noqa: E402
from src.persistencia.metricas import _pl_apuesta  # noqa: E402

N_MIN = 50  # trigger adepor-hm9: con menos apuestas el informe no concluye


def ic95(x, n_boot, rng):
    x = np.asarray(x, float)
    medias = x[rng.integers(0, len(x), (n_boot, len(x)))].mean(axis=1)
    return [float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))]


def apuestas(con):
    """(P/L, stake, CLV%) de cada apuesta liquidada con stake > 0, en 1X2 y O/U."""
    filas = con.execute("SELECT apuesta_1x2, apuesta_ou, stake_1x2, stake_ou, cuota_1, cuota_x, cuota_2, "
                        "cuota_o25, cuota_u25, clv_pct_1x2, clv_pct_ou, goles_l, goles_v "
                        "FROM partidos_backtest WHERE estado = 'Liquidado'").fetchall()
    out = []
    for ap1, ap2, s1, s2, c1, cx, c2, co, cu, k1, k2, gl, gv in filas:
        for ap, stk, clv in ((ap1, s1, k1), (ap2, s2, k2)):
            if not ap or not stk or stk <= 0:
                continue
            res = determinar_resultado_entero(ap, gl, gv)
            pl = _pl_apuesta(res, stk, cuota_para_pick(ap, c1, cx, c2, co, cu)) if res else None
            if pl is not None:
                out.append((pl, stk, clv))
    return out


def calibracion(con):
    """Log-loss del 1X2 de Pinnacle previo, sin margen proporcional, en todos los liquidados."""
    ll = []
    for p1, px, p2, gl, gv in con.execute("SELECT pin_1, pin_x, pin_2, goles_l, goles_v FROM partidos_backtest "
                                          "WHERE estado = 'Liquidado' AND pin_1 > 0 AND pin_x > 0 AND pin_2 > 0 "
                                          "AND goles_l IS NOT NULL AND goles_v IS NOT NULL"):
        inv = 1 / np.array([p1, px, p2])
        p = inv / inv.sum()
        ll.append(-np.log(p[0 if gl > gv else 1 if gl == gv else 2]))
    return ll


def informe(db, n_boot=10000):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rng = np.random.default_rng(0)
    ap = apuestas(con)
    ll = calibracion(con)
    r = {'n': len(ap), 'concluyente': len(ap) >= N_MIN, 'yield': None, 'yield_ic95': None,
         'clv_medio': None, 'clv_ic95': None, 'n_clv': 0,
         'n_calibracion': len(ll), 'logloss_pinnacle': float(np.mean(ll)) if ll else None}
    if ap:
        pl, stk = np.array([a[0] for a in ap]), np.array([a[1] for a in ap])
        r['yield'] = float(pl.sum() / stk.sum())
        r['yield_ic95'] = ic95(pl / stk, n_boot, rng)  # IC del retorno medio por apuesta
    clv = [a[2] for a in ap if a[2] is not None]
    if clv:
        r['n_clv'], r['clv_medio'], r['clv_ic95'] = len(clv), float(np.mean(clv)), ic95(clv, n_boot, rng)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default=str(ROOT / 'fondo_quant.db'))
    r = informe(ap.parse_args().db)
    print(json.dumps(r, indent=2))
    if not r['concluyente']:
        print(f"AVISO: {r['n']} apuestas liquidadas, menos de {N_MIN}. Los numeros no concluyen.")
    return 0


if __name__ == '__main__':
    sys.exit(main())

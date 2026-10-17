"""
Frente de Pareto del tamaño de stake: crecimiento del bankroll vs Max Drawdown.

El yield (ganancia / monto apostado) no depende del tamaño del stake: escalar todos los
stakes escala ganancia y monto por igual. Lo que cambia es el crecimiento y el drawdown.

Stake de cada apuesta = min(fraccion * Kelly, tope) del bankroll vigente, con
Kelly = (p * cuota - 1) / (cuota - 1). Para cada combinacion (fraccion, tope) se simulan
remuestreos del orden de las apuestas (bootstrap) y se miden:
  crecimiento = mediana del log del bankroll final (log-growth total)
  max_dd_p95  = percentil 95 del Max Drawdown (peor caida pico-valle, fraccion del pico)
Se devuelven las combinaciones no dominadas y la elegida: el mayor crecimiento con
max_dd_p95 <= DD_MAX. El frente no tiene un unico optimo: el tope de drawdown es la
preferencia del usuario (un cociente crecimiento/DD empuja al riesgo maximo o al minimo).

Uso:  python analisis/pareto_stake.py   (lee picks liquidados con prob y cuota de la DB)
"""
import math
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FRACCIONES = (0.10, 0.25, 0.50, 0.75, 1.00)
TOPES = (0.01, 0.025, 0.05)
DD_MAX = 0.25   # tolerancia al drawdown (p95); decision del usuario, pendiente junto con el bankroll


def simular(apuestas, fraccion, tope):
    """(log del bankroll final, max drawdown) para un orden dado de apuestas (p, cuota, gano)."""
    banca = pico = 1.0
    max_dd = 0.0
    for p, cuota, gano in apuestas:
        kelly = (p * cuota - 1) / (cuota - 1)
        f = min(fraccion * kelly, tope) if kelly > 0 else 0.0
        banca *= (1 + f * (cuota - 1)) if gano else (1 - f)
        pico = max(pico, banca)
        max_dd = max(max_dd, 1 - banca / pico)
    return math.log(banca), max_dd


def frente_pareto(apuestas, n_boot=500, semilla=7, dd_max=DD_MAX):
    rng = random.Random(semilla)
    ordenes = [[rng.choice(apuestas) for _ in apuestas] for _ in range(n_boot)]
    filas = []
    for fr in FRACCIONES:
        for tope in TOPES:
            sims = [simular(o, fr, tope) for o in ordenes]
            logs = sorted(s[0] for s in sims)
            dds = sorted(s[1] for s in sims)
            filas.append({'fraccion_kelly': fr, 'tope': tope,
                          'crecimiento_mediano': logs[len(logs) // 2],
                          'max_dd_p95': dds[int(0.95 * len(dds)) - 1]})
    eficientes = [f for f in filas if not any(
        g['crecimiento_mediano'] >= f['crecimiento_mediano'] and g['max_dd_p95'] <= f['max_dd_p95']
        and (g['crecimiento_mediano'] > f['crecimiento_mediano'] or g['max_dd_p95'] < f['max_dd_p95'])
        for g in filas)]
    eficientes.sort(key=lambda f: f['max_dd_p95'])
    admisibles = [f for f in eficientes if f['crecimiento_mediano'] > 0 and f['max_dd_p95'] <= dd_max]
    elegida = max(admisibles, key=lambda f: f['crecimiento_mediano'], default=None)
    return eficientes, elegida


def cargar_apuestas(conn):
    """Picks liquidados (incluye pretest) con la prob del modelo y la cuota del pick."""
    from src.comun.picks import cuota_para_pick
    out = []
    for ap, p1, px, p2, c1, cx, c2 in conn.execute(
            "SELECT apuesta_1x2, prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2 "
            "FROM partidos_backtest WHERE estado='Liquidado' "
            "AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')"):
        p = {'LOCAL': p1, 'EMPATE': px, 'VISITA': p2}.get(ap.split(']')[1].strip())
        cuota = cuota_para_pick(ap, c1, cx, c2, 0, 0)
        if p and cuota and cuota > 1:
            out.append((p, cuota, ap.startswith('[GANADA]')))
    return out


def main():
    from src.comun.config_sistema import DB_NAME
    apuestas = cargar_apuestas(sqlite3.connect(DB_NAME))
    if len(apuestas) < 50:
        print(f'[SKIP] Solo {len(apuestas)} picks liquidados: el frente no es confiable con < 50.')
        return
    eficientes, elegida = frente_pareto(apuestas)
    for f in eficientes:
        print(f)
    print(f'Elegida (max crecimiento con Max DD p95 <= {DD_MAX:.0%}):', elegida)


if __name__ == '__main__':
    main()

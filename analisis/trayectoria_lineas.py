"""
Trayectoria de lineas de la apertura al cierre (estudio E5). Protocolo: docs/specs/13-estudios-forward.md.

Fuente: OddsPapi historical-odds, 1X2 (mercado 101) de pinnacle, bet365.bet.ar y betano.
Guarda un JSON reducido por partido en data/oddspapi_hist/ (no se versiona).

Uso:
  python -I analisis/trayectoria_lineas.py bajar [--max 40]   # gasta 1 pedido por partido nuevo
  python -I analisis/trayectoria_lineas.py medir               # lee lo bajado y escribe el JSON de resultados
"""
import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.nucleo.valor_v2 import UMBRAL_EV_V2, prob_justa  # noqa: E402

URL = 'https://api.oddspapi.io/v4/historical-odds'
CASAS = ('pinnacle', 'bet365.bet.ar', 'betano')
OUTCOMES = ('101', '102', '103')
CACHE = ROOT / 'data' / 'oddspapi_hist'
PASO, N_BOOT, N_MIN = 1800, 10000, 40
TRAMOS = ((72, 1e9, '>72h'), (24, 72, '24-72h'), (6, 24, '6-24h'), (0, 6, '<6h'))


def _ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def reducir(resp, inicio_utc):
    """JSON reducido: {'inicio': ts, 'casas': {casa: {outcome: [[ts, precio], ...]}}} ordenado en el tiempo."""
    casas = {}
    for casa, v in (resp.get('bookmakers') or {}).items():
        out = ((v.get('markets') or {}).get('101') or {}).get('outcomes') or {}
        casas[casa] = {o: sorted([_ts(x['createdAt']), x['price']] for x in out.get(o, {}).get('players', {}).get('0', [])
                                 if x.get('price')) for o in OUTCOMES}
    return {'inicio': _ts(inicio_utc), 'casas': casas}


def bajar(db, key, max_n, pausa=1.5):
    """Baja partidos terminados de cuotas_forward que aun no estan en cache, hasta tener max_n en total."""
    CACHE.mkdir(parents=True, exist_ok=True)
    tengo = {p.stem for p in CACHE.glob('*.json')}
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    cand = con.execute("SELECT fixture_id, inicio_utc FROM cuotas_forward WHERE fixture_id NOT LIKE 'fm:%' "
                       "AND inicio_utc < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-3 hours') "
                       "GROUP BY fixture_id ORDER BY inicio_utc").fetchall()
    nuevos = [c for c in cand if c[0] not in tengo][:max(0, max_n - len(tengo))]
    print(f'terminados disponibles: {len(cand)}, en cache: {len(tengo)}, a bajar: {len(nuevos)}')
    for fid, inicio in nuevos:
        r = requests.get(URL, params={'apiKey': key, 'fixtureId': fid, 'bookmakers': ','.join(CASAS)}, timeout=60)
        r.raise_for_status()
        (CACHE / f'{fid}.json').write_text(json.dumps(reducir(r.json(), inicio)))
        time.sleep(pausa)
    return len(cand)


def _en(serie, x):
    """Ultimo precio conocido en el instante x, o None."""
    v = None
    for ts, p in serie:
        if ts > x:
            break
        v = p
    return v


def oportunidades(tray, umbral=UMBRAL_EV_V2):
    """[(horas_al_inicio, casa, outcome, cuota, CLV)] de una trayectoria. CLV contra el cierre de Pinnacle."""
    casas, inicio = tray['casas'], tray['inicio']
    if 'pinnacle' not in casas:
        return []
    cierre = [_en(casas['pinnacle'][o], inicio) for o in OUTCOMES]
    q_cierre = prob_justa(cierre)
    if not q_cierre:
        return []
    out = []
    for casa in (c for c in casas if c != 'pinnacle'):
        inicios = [casas[c][o][0][0] for c in ('pinnacle', casa) for o in OUTCOMES if casas[c][o]]
        if len(inicios) < 6:
            continue
        x = max(inicios)
        while x < inicio:
            pin = [_en(casas['pinnacle'][o], x) for o in OUTCOMES]
            cuotas = [_en(casas[casa][o], x) for o in OUTCOMES]
            q = prob_justa(pin) if None not in pin else None
            if q and None not in cuotas:
                for i in range(3):
                    if cuotas[i] * q[i] - 1 > umbral:
                        out.append(((inicio - x) / 3600, casa, i, cuotas[i], cuotas[i] * q_cierre[i] - 1))
            x += PASO
    return out


def ic95(x, rng):
    x = np.asarray(x, float)
    m = x[rng.integers(0, len(x), (N_BOOT, len(x)))].mean(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def por_partido(opps, filtro):
    """CLV medio de cada partido (peso igual por partido) con las oportunidades que pasan `filtro`."""
    return [np.mean([o[4] for o in ops if filtro(o)]) for ops in opps if any(filtro(o) for o in ops)]


def resumen(valores, rng):
    return {'n_partidos': len(valores), 'clv_medio': float(np.mean(valores)), 'ic95': ic95(valores, rng)} if valores else {'n_partidos': 0}


def medir(dir_cache=CACHE):
    rng = np.random.default_rng(20261023)
    trays = [json.loads(p.read_text()) for p in sorted(Path(dir_cache).glob('*.json'))]
    r = {'n_partidos_bajados': len(trays), 'suficiente': len(trays) >= N_MIN, 'por_casa': {}}
    for casa in CASAS[1:]:
        opps = [[o for o in oportunidades(t) if o[1] == casa] for t in trays]
        r['por_casa'][casa] = {
            'todas': resumen(por_partido(opps, lambda o: True), rng),
            'cuota_mayor_4': resumen(por_partido(opps, lambda o: o[3] > 4), rng),
            'cuota_hasta_4': resumen(por_partido(opps, lambda o: o[3] <= 4), rng),
            'por_tramo': {nom: resumen(por_partido(opps, lambda o, lo=lo, hi=hi: lo <= o[0] < hi), rng) for lo, hi, nom in TRAMOS},
            'partidos_con_oportunidad': sum(1 for ops in opps if ops)}
        m = r['por_casa'][casa]['todas']
        m['exito'] = bool(m['n_partidos'] >= N_MIN and m['ic95'][0] > 0) if m['n_partidos'] else False
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('modo', choices=['bajar', 'medir'])
    ap.add_argument('--max', type=int, default=N_MIN)
    a = ap.parse_args()
    if a.modo == 'bajar':
        key = json.load(open(ROOT / 'config.json'))['api_key_oddspapi']
        bajar(ROOT / 'fondo_quant.db', key, a.max)
        return
    r = medir()
    texto = json.dumps(r, indent=2)
    (ROOT / 'analisis' / 'trayectoria_lineas.json').write_text(texto)
    print(texto)
    if not r['suficiente']:
        print(f"AVISO: {r['n_partidos_bajados']} partidos, menos de {N_MIN}. No concluye.")


if __name__ == '__main__':
    main()

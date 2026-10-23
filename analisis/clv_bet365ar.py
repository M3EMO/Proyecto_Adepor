"""
Seguimiento del experimento adepor-1uk (protocolo pre-registrado el 2026-10-23, ver el bead).

Pick: primera captura de cada partido en cuotas_forward donde bet365 AR paga EV >= 2 % sobre la
prob justa de Pinnacle de la misma captura. CLV = cuota bet365 x prob justa del cierre de Pinnacle - 1.
El cierre sale de partidos_backtest.pin_cierre_* (motor_cuotas --solo-cierre).
Los informes intermedios no deciden: la decision se toma una vez, con 300 picks con cierre en el
estrato primario o el 2027-06-30.

Uso:  python -I analisis/clv_bet365ar.py [salida.json]   (default: data/oddspapi/clv_bet365ar.json)
"""
import difflib
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # -I quita el directorio del script del path
from src.comun import gestor_nombres  # noqa: E402
from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.nucleo.valor_v2 import prob_justa, stake_v2  # noqa: E402

CASA = 'bet365.bet.ar'
UMBRAL_EV, EV_ERROR, DIF_MAX = 0.02, 1.0, 0.25
P_MIN_SECUNDARIO = 0.35  # corte secundario, descriptivo (sin underdogs)
SIM_APRENDER = 0.9  # un alias se aprende solo con contencion o similitud alta
# CUSUM (alerta temprana, sin decision): k = mitad de un edge objetivo de 2 %; h calibrado con Bet365
# en Europa 2019-2022 (10 % de falsas alarmas en 300 picks con edge).
CUSUM_K, CUSUM_H = 0.01, 2.10
N_PARADA, FECHA_PARADA = 300, date(2027, 6, 30)
N_BOOT, SEMILLA = 2000, 42
PRIMARIO = {155, 1024, 384, 480}
SEGUNDAS = {18, 703, 1240}  # adepor-dch: Championship, Primera Nacional, Primera B de Chile
TORNEO_PAIS = {155: 'Argentina', 1024: 'Copa Argentina', 384: 'Libertadores', 480: 'Sudamericana',
               325: 'Brasil', 17: 'Inglaterra', 8: 'Espana', 23: 'Italia', 35: 'Alemania', 34: 'Francia',
               7: 'Champions League', 679: 'Europa League', 27665: 'Chile', 278: 'Uruguay', 27070: 'Colombia',
               242: 'Estados Unidos', 27464: 'Mexico', 18: 'Inglaterra 2', 703: 'Argentina 2', 1240: 'Chile 2'}
PARTICIPANTES = ROOT / 'data' / 'oddspapi' / 'participantes_10.json'


def ev_picks(pin, b365):
    """Indices (0=local, 1=empate, 2=visita) con EV >= 2 % sobre Pinnacle. [] si la fila es sospechosa."""
    p_pin, p_b365 = prob_justa(pin), prob_justa(b365)
    if p_pin is None or p_b365 is None:
        return []
    evs = [c * p - 1 for c, p in zip(b365, p_pin)]
    if max(evs) >= EV_ERROR or max(abs(a - b) for a, b in zip(p_pin, p_b365)) > DIF_MAX:
        return []  # D-007 y error de mapeo local/visita de OddsPapi (adepor-6kk)
    return [i for i, ev in enumerate(evs) if ev >= UMBRAL_EV]


def _norm(nombre, pais):
    return gestor_nombres.limpiar_texto(gestor_nombres.obtener_nombre_estandar(nombre, liga=pais, modo_interactivo=False))


def _similitud(a, b):
    """1 si un nombre contiene al otro ('inter' en 'intermilano'); si no, SequenceMatcher."""
    corto, largo = sorted((a, b), key=len)
    return 1.0 if len(corto) >= 4 and corto in largo else difflib.SequenceMatcher(None, a, b).ratio()


def cruzar(partido, candidatos):
    """Fila de partidos_backtest del mismo partido: misma liga, kickoff a 3 h o menos, y nombres iguales
    o con similitud >= 0.6 por equipo y >= 0.75 de media (enmienda del bead adepor-1uk).
    partido: dict con pais, inicio_utc, local, visita."""
    kickoff = datetime.strptime(partido['inicio_utc'][:16], '%Y-%m-%dT%H:%M') - timedelta(hours=3)
    loc, vis = _norm(partido['local'], partido['pais']), _norm(partido['visita'], partido['pais'])
    mejor, score_max = None, 0.0
    for c in candidatos:
        try:
            fp = datetime.strptime(c['fecha'], '%Y-%m-%d %H:%M')
        except (TypeError, ValueError):
            continue
        if abs(fp - kickoff) > timedelta(hours=3):
            continue
        cl, cv = gestor_nombres.limpiar_texto(c['local']), gestor_nombres.limpiar_texto(c['visita'])
        if (cl, cv) == (loc, vis):
            return c
        sl, sv = _similitud(loc, cl), _similitud(vis, cv)
        if min(sl, sv) >= 0.6 and (sl + sv) / 2 > score_max:
            mejor, score_max = c, (sl + sv) / 2
    return mejor if score_max >= 0.75 else None


def aprender(partido, fila, revisar):
    """Banco de nombres: guarda los nombres de OddsPapi de un cruce claro como alias del pais.
    Un lado dudoso queda en revisar para que el usuario lo confirme."""
    for lado in ('local', 'visita'):
        crudo, oficial = partido[lado], fila[lado]
        a, b = _norm(crudo, partido['pais']), gestor_nombres.limpiar_texto(oficial)
        if a == b:
            continue
        if _similitud(a, b) >= SIM_APRENDER and gestor_nombres.aprender_alias(crudo, oficial, partido['pais']):
            continue
        revisar.append({'pais': partido['pais'], 'oddspapi': crudo, 'base': oficial})


def cusum(clvs, k=CUSUM_K, h=CUSUM_H):
    """S = max(0, S + k - CLV) en orden de captura. Alarma si S supera h: el edge probablemente se apago."""
    s = s_max = 0.0
    for x in clvs:
        s = max(0.0, s + k - x)
        s_max = max(s_max, s)
    return {'s': s, 's_max': s_max, 'h': h, 'alarma': s_max > h}


def cierre_aproximado(snaps, ts_pick, inicio_utc):
    """Ultima captura de Pinnacle posterior al pick y anterior al inicio (ligas sin The Odds API). None si no hay."""
    inicio = inicio_utc[:19].replace('T', ' ')
    previas = [c for ts, c in snaps if ts > ts_pick and ts[:19].replace('T', ' ') < inicio]
    return previas[-1] if previas else None


def simulacion(picks, bankroll=100_000.0):
    """Seguir el v2 a ciegas: stake_v2 sobre el bankroll del momento, en orden de inicio.
    Solo los picks ya jugados mueven el bankroll; los pendientes se listan."""
    banca, filas = bankroll, []
    for p in sorted(picks, key=lambda x: x['inicio']):
        stake = stake_v2(p['p_pin'], p['cuota'], banca) if p['pl'] is not None else None
        if stake is not None:
            banca += stake * p['pl']
        filas.append({'inicio': p['inicio'], 'liga': p['liga'], 'partido': p['partido'],
                      'pick': ('LOCAL', 'EMPATE', 'VISITA')[p['resultado']], 'cuota': p['cuota'], 'p_pin': p['p_pin'],
                      'clv': p['clv'], 'estado': 'pendiente' if p['pl'] is None else ('ganada' if p['pl'] > 0 else 'perdida'),
                      'stake': stake, 'bankroll': round(banca, 2)})
    jugados = [p for p in picks if p['pl'] is not None]
    return {'picks': filas, 'bankroll_inicial': bankroll, 'bankroll_final': round(banca, 2),
            'n_jugados': len(jugados), 'acierto': float(np.mean([p['pl'] > 0 for p in jugados])) if jugados else None}


def resumen(picks):
    clv = [p['clv'] for p in picks if p['clv'] is not None]
    pl = [p['pl'] for p in picks if p['pl'] is not None]
    out = {'n_picks': len(picks), 'n_con_cierre': len(clv), 'n_jugados': len(pl), 'cusum': cusum(clv)}
    if clv:
        a = np.asarray(clv)
        medias = a[np.random.default_rng(SEMILLA).integers(0, len(a), (N_BOOT, len(a)))].mean(axis=1)
        out.update(clv_medio=float(a.mean()), clv_ic95=[float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))])
    if pl:
        out['yield_plano'] = float(np.mean(pl))
    return out


def main():
    salida = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'data' / 'oddspapi' / 'clv_bet365ar.json')
    nombres = json.loads(PARTICIPANTES.read_text(encoding='utf-8'))
    con = sqlite3.connect(Path(DB_NAME).resolve().as_uri() + '?mode=ro', uri=True)
    filas = con.execute('SELECT fixture_id, torneo_id, inicio_utc, local_id, visita_id, casa, ts_captura, '
                        'cuota_1, cuota_x, cuota_2 FROM cuotas_forward WHERE casa IN (?, ?) '
                        'ORDER BY ts_captura', ('pinnacle', CASA)).fetchall()
    capturas, snaps_pin = {}, {}
    for fid, tid, ini, lid, vid, casa, ts, *c in filas:
        if casa == 'pinnacle':
            snaps_pin.setdefault(fid, []).append((ts, c))
        capturas.setdefault((fid, ts), {'torneo': tid, 'inicio_utc': ini, 'local': nombres.get(str(lid), ''),
                                        'visita': nombres.get(str(vid), '')})[casa] = c
    pb = [dict(zip(('id', 'fecha', 'pais', 'local', 'visita', 'gl', 'gv', 'c1', 'cx', 'c2'), r)) for r in con.execute(
        'SELECT id_partido, fecha, pais, local, visita, goles_l, goles_v, pin_cierre_1, pin_cierre_x, pin_cierre_2 '
        'FROM partidos_backtest')]
    vistos, picks, n_partidos, n_cruzados, revisar = set(), [], 0, 0, []
    margenes = {e: {'pinnacle': [], CASA: []} for e in ('primario', 'segundas', 'resto')}
    for (fid, ts_pick), d in capturas.items():  # orden por ts: la primera captura de cada partido gana
        if fid in vistos or 'pinnacle' not in d or CASA not in d or d['torneo'] not in TORNEO_PAIS:
            continue
        vistos.add(fid)
        n_partidos += 1
        pais = TORNEO_PAIS[d['torneo']]
        estrato = 'primario' if d['torneo'] in PRIMARIO else ('segundas' if d['torneo'] in SEGUNDAS else 'resto')
        for casa in ('pinnacle', CASA):
            margenes[estrato][casa].append(sum(1 / x for x in d[casa]) - 1)
        fila = cruzar({**d, 'pais': pais}, [c for c in pb if c['pais'] == pais])
        n_cruzados += fila is not None
        if fila:
            aprender({**d, 'pais': pais}, fila, revisar)
        p_cierre = prob_justa([fila['c1'], fila['cx'], fila['c2']]) if fila else None
        if p_cierre is None:  # torneo sin The Odds API: cierre aproximado de OddsPapi (enmienda del bead)
            aprox = cierre_aproximado(snaps_pin.get(fid, []), ts_pick, d['inicio_utc'])
            p_cierre = prob_justa(aprox) if aprox else None
        res = None
        if fila and fila['gl'] is not None and fila['gv'] is not None:
            res = 0 if fila['gl'] > fila['gv'] else (1 if fila['gl'] == fila['gv'] else 2)
        for i in ev_picks(d['pinnacle'], d[CASA]):
            cuota = d[CASA][i]
            picks.append({'fixture': fid, 'torneo': d['torneo'], 'resultado': i, 'cuota': cuota,
                          'p_pin': prob_justa(d['pinnacle'])[i], 'inicio': d['inicio_utc'][:16],
                          'partido': f"{d['local']} vs {d['visita']}", 'liga': pais,
                          'clv': cuota * p_cierre[i] - 1 if p_cierre else None,
                          'pl': None if res is None else (cuota - 1 if res == i else -1.0)})
    primario = [p for p in picks if p['torneo'] in PRIMARIO]
    out = {'bead': 'adepor-1uk', 'fecha': date.today().isoformat(), 'partidos_con_ambas_casas': n_partidos,
           'tasa_cruce': n_cruzados / n_partidos if n_partidos else None,
           'primario': resumen(primario),
           'resto': resumen([p for p in picks if p['torneo'] not in PRIMARIO | SEGUNDAS]),
           'segundas': {**resumen([p for p in picks if p['torneo'] in SEGUNDAS]),
                        'por_torneo': {TORNEO_PAIS[t]: resumen([p for p in picks if p['torneo'] == t]) for t in SEGUNDAS}},
           'primario_p_min_035': resumen([p for p in primario if p['p_pin'] >= P_MIN_SECUNDARIO]),
           'alias_a_revisar': revisar,
           'simulacion': simulacion(picks),
           'margen_medio': {e: {c: float(np.mean(v)) if v else None for c, v in m.items()} for e, m in margenes.items()}}
    parada = out['primario']['n_con_cierre'] >= N_PARADA or date.today() >= FECHA_PARADA
    out['decision'] = 'evaluar ahora con la regla del bead' if parada else 'informe intermedio: no decide'
    Path(salida).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()

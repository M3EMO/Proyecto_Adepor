"""
Evalua y migra el prior de las EMAs de xG (auditoria 2026-10, bead adepor-thv).

Bug: motor_data y rebuild_ema_v2 anclaban la EMA de cada EQUIPO al promedio de goles
por PARTIDO (~2.6), el doble de la escala correcta (~1.3). Las lambdas del Poisson
quedaban infladas ~1.7x, con sesgo dependiente del N de cada equipo. factor_corr_xg_ou
(0.627) y gamma_1x2 (0.59) compensaban la escala en O/U y en display, no en 1X2.

Este script hace un replay cronologico (estado AS-OF antes de cada partido, sin
look-ahead) con ambos priors y reporta por liga:
  k        = goles reales / lambda predicha (1.0 = escala correcta)
  P(X)     = empate medio predicho vs frecuencia real
  Brier / logloss 1X2 del modelo y, si hay cuotas, del mercado sin margen
  logloss O/U 2.5 con factor calibrado en la 1ra mitad y evaluado en la 2da

Uso:
  python scripts/evaluar_prior_ema.py                 # solo reporte (no escribe)
  python scripts/evaluar_prior_ema.py --aplicar       # backup + flag + recalibracion + rebuild
"""
import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.config_sistema import DB_NAME  # noqa: E402
from src.comun.config_motor import get_param  # noqa: E402
from src.nucleo.motor_calculadora import poisson, tau, RHO_FALLBACK  # noqa: E402
from scripts.rebuild_ema_v2 import cargar_partidos, reconstruir  # noqa: E402

WARMUP = 3        # partidos minimos por lado antes de evaluar un pronostico
MAX_GOLES = 10


def probs_partido(lam, mu, rho, factor_ou=1.0):
    """(p1, px, p2) con lambdas crudas y P(over 2.5) con lambdas * factor_ou."""
    def matriz(a, b):
        return [[poisson(i, a) * poisson(j, b) * tau(i, j, a, b, rho)
                 for j in range(MAX_GOLES)] for i in range(MAX_GOLES)]
    m = matriz(lam, mu)
    p1 = sum(m[i][j] for i in range(MAX_GOLES) for j in range(i))
    px = sum(m[i][i] for i in range(MAX_GOLES))
    p2 = sum(m[i][j] for i in range(MAX_GOLES) for j in range(i + 1, MAX_GOLES))
    s = p1 + px + p2
    mo = matriz(lam * factor_ou, mu * factor_ou)
    po = sum(mo[i][j] for i in range(MAX_GOLES) for j in range(MAX_GOLES) if i + j > 2)
    so = sum(map(sum, mo))
    return p1 / s, px / s, p2 / s, po / so


def _brier(p, o):
    return sum((a - b) ** 2 for a, b in zip(p, o))


def replay_con_pronosticos(conn, partidos, prior_por_equipo):
    """Devuelve (state, filas) con un pronostico as-of por partido evaluable."""
    filas = []

    def capturar(p, st_l, st_v):
        if st_l['p_h'] < WARMUP or st_v['p_a'] < WARMUP:
            return
        lam = (st_l['fav_h'] + st_v['con_a']) / 2.0
        mu = (st_v['fav_a'] + st_l['con_h']) / 2.0
        filas.append({'id': p[0], 'liga': p[2], 'gl': p[5], 'gv': p[6], 'lam': lam, 'mu': mu})

    state, _ = reconstruir(conn, partidos, prior_por_equipo, antes_de_actualizar=capturar)
    return state, filas


def metricas(filas, rhos, cuotas, factores_ou):
    """Metricas por liga. factores_ou: {liga: factor} o None para calibrar k en 1ra mitad."""
    por_liga = defaultdict(list)
    for f in filas:
        por_liga[f['liga']].append(f)
    out = {}
    for liga, fs in sorted(por_liga.items()):
        rho = rhos.get(liga, RHO_FALLBACK)
        goles = sum(f['gl'] + f['gv'] for f in fs)
        lam_tot = sum(f['lam'] + f['mu'] for f in fs)
        mitad = len(fs) // 2
        if factores_ou is None:
            primera = fs[:mitad] or fs
            fac = (sum(f['gl'] + f['gv'] for f in primera) /
                   max(1e-9, sum(f['lam'] + f['mu'] for f in primera)))
        else:
            fac = factores_ou.get(liga, factores_ou.get('global', 1.0))
        br = ll = pxs = 0.0
        ll_ou, n_ou = 0.0, 0
        ll_crudo_2da = ll_esc_2da = 0.0
        br_m = ll_m = 0.0
        n_m = 0
        for idx, f in enumerate(fs):
            p1, px, p2, po = probs_partido(f['lam'], f['mu'], rho, fac)
            o = (f['gl'] > f['gv'], f['gl'] == f['gv'], f['gl'] < f['gv'])
            br += _brier((p1, px, p2), o)
            ll -= math.log(max(1e-12, (p1, px, p2)[o.index(True)]))
            pxs += px
            if idx >= mitad:
                over = (f['gl'] + f['gv']) > 2.5
                ll_ou -= math.log(max(1e-12, po if over else 1 - po))
                n_ou += 1
                # 1X2 con lambdas escaladas por el mismo factor (flag escalar_lambda_1x2)
                q1, qx, q2, _ = probs_partido(f['lam'] * fac, f['mu'] * fac, rho)
                ll_crudo_2da -= math.log(max(1e-12, (p1, px, p2)[o.index(True)]))
                ll_esc_2da -= math.log(max(1e-12, (q1, qx, q2)[o.index(True)]))
            c = cuotas.get(f['id'])
            if c:
                q = [1 / x for x in c]
                s = sum(q)
                q = [x / s for x in q]
                br_m += _brier(q, o)
                ll_m -= math.log(q[o.index(True)])
                n_m += 1
        n = len(fs)
        out[liga] = {
            'n': n, 'k': goles / max(1e-9, lam_tot), 'factor_ou': fac,
            'px_pred': pxs / n, 'px_real': sum(f['gl'] == f['gv'] for f in fs) / n,
            'brier': br / n, 'logloss': ll / n,
            'logloss_ou_2da_mitad': (ll_ou / n_ou) if n_ou else None,
            'll_1x2_crudo_2da': (ll_crudo_2da / n_ou) if n_ou else None,
            'll_1x2_escalado_2da': (ll_esc_2da / n_ou) if n_ou else None,
            'n_mercado': n_m,
            'brier_mercado': (br_m / n_m) if n_m else None,
            'logloss_mercado': (ll_m / n_m) if n_m else None,
        }
    return out


def _imprimir(titulo, res):
    print(f'\n=== {titulo} ===')
    print(f'{"liga":<14}{"n":>6}{"k":>7}{"P(X)":>7}{"real":>7}{"Brier":>8}{"LL":>8}'
          f'{"LL_OU":>8}{"n_mkt":>7}{"Br_mkt":>8}')
    for liga, r in res.items():
        llou = f'{r["logloss_ou_2da_mitad"]:.4f}' if r['logloss_ou_2da_mitad'] else '   -'
        brm = f'{r["brier_mercado"]:.4f}' if r['brier_mercado'] else '   -'
        print(f'{liga:<14}{r["n"]:>6}{r["k"]:>7.3f}{r["px_pred"]:>7.3f}{r["px_real"]:>7.3f}'
              f'{r["brier"]:>8.4f}{r["logloss"]:>8.4f}{llou:>8}{r["n_mercado"]:>7}{brm:>8}')


def _upsert(cur, clave, scope, valor_real=None, valor_texto=None, tipo='float'):
    fila = cur.execute("SELECT bloqueado FROM config_motor_valores WHERE clave=? AND scope=?",
                       (clave, scope)).fetchone()
    if fila and fila[0] == 1:
        raise RuntimeError(f'{clave}[{scope}] esta bloqueado=1: desbloquear a mano antes de migrar')
    cur.execute("""
        INSERT INTO config_motor_valores (clave, scope, valor_real, valor_texto, tipo, fuente)
        VALUES (?, ?, ?, ?, ?, 'evaluar_prior_ema 2026-10')
        ON CONFLICT(clave, scope) DO UPDATE SET valor_real=excluded.valor_real,
            valor_texto=excluded.valor_texto, tipo=excluded.tipo, fuente=excluded.fuente,
            fecha_actualizacion=CURRENT_TIMESTAMP
    """, (clave, scope, valor_real, valor_texto, tipo))


def aplicar(conn, partidos, res_nuevo):
    """Backup + flag + factores recalibrados + rebuild, en una sola transaccion de config."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = Path(DB_NAME).resolve().parent / 'snapshots' / f'fondo_quant_{ts}_pre_prior_ema.db'
    backup.parent.mkdir(exist_ok=True)
    dst = sqlite3.connect(str(backup))
    conn.backup(dst)
    dst.close()
    print(f'\n[BACKUP] {backup}')

    # k sobre la muestra completa: se aplica hacia adelante (el reporte uso 1ra/2da mitad).
    cur = conn.cursor()
    num = den = 0.0
    for liga, r in res_nuevo.items():
        _upsert(cur, 'factor_corr_xg_ou', liga, valor_real=round(r['k'], 4))
        _upsert(cur, 'gamma_1x2', liga, valor_real=round(r['k'], 4))
        num += r['k'] * r['n']
        den += r['n']
    k_global = round(num / den, 4) if den else 1.0
    _upsert(cur, 'factor_corr_xg_ou', 'global', valor_real=k_global)
    _upsert(cur, 'gamma_1x2', 'global', valor_real=k_global)
    _upsert(cur, 'ema_prior_por_equipo', 'global', valor_texto='TRUE', tipo='bool')

    state, _ = reconstruir(conn, partidos, prior_por_equipo=True)
    cols = ('ema_xg_favor_home', 'ema_xg_contra_home', 'ema_xg_favor_away', 'ema_xg_contra_away')
    viejo = {(e, l): v for e, l, *v in cur.execute(
        f"SELECT equipo_norm, liga, {', '.join(cols)} FROM historial_equipos")}
    # Escala nueva/vieja por liga, medida en los equipos reconstruidos.
    suma = defaultdict(lambda: [0.0, 0.0])
    for key, s in state.items():
        if key in viejo and all(v is not None for v in viejo[key]):
            suma[key[1]][0] += s['fav_h'] + s['con_h'] + s['fav_a'] + s['con_a']
            suma[key[1]][1] += sum(viejo[key])
    escala = {l: n / d for l, (n, d) in suma.items() if d > 0}
    n_upd = 0
    for (eq_norm, liga), s in state.items():
        cur.execute('''
            UPDATE historial_equipos
            SET ema_xg_favor_home=?, ema_xg_contra_home=?, partidos_home=?,
                ema_xg_favor_away=?, ema_xg_contra_away=?, partidos_away=?,
                ema_var_favor_home=?, ema_var_contra_home=?,
                ema_var_favor_away=?, ema_var_contra_away=?, ultima_actualizacion=?
            WHERE equipo_norm=? AND liga=?
        ''', (s['fav_h'], s['con_h'], s['p_h'], s['fav_a'], s['con_a'], s['p_a'],
              s['var_fh'], s['var_ch'], s['var_fa'], s['var_ca'],
              datetime.now().isoformat(), eq_norm, liga))
        n_upd += cur.rowcount
    # Equipos sin stats (sot) no se reconstruyen: se reescalan con el cociente de su liga
    # para no mezclar escalas en un mismo partido. Incluye las EMAs cortas (shadow).
    # shortcut: escala promedio de liga, no replay propio; motor_data los corrige partido a partido.
    n_esc = 0
    for (eq_norm, liga) in viejo:
        if (eq_norm, liga) in state or liga not in escala:
            continue
        f = escala[liga]
        cur.execute('''
            UPDATE historial_equipos SET
                ema_xg_favor_home=ema_xg_favor_home*?, ema_xg_contra_home=ema_xg_contra_home*?,
                ema_xg_favor_away=ema_xg_favor_away*?, ema_xg_contra_away=ema_xg_contra_away*?
            WHERE equipo_norm=? AND liga=?
        ''', (f, f, f, f, eq_norm, liga))
        n_esc += cur.rowcount
    try:
        for liga, f in escala.items():
            cur.execute('''
                UPDATE historial_equipos SET
                    ema_corto_favor_home=ema_corto_favor_home*?, ema_corto_contra_home=ema_corto_contra_home*?,
                    ema_corto_favor_away=ema_corto_favor_away*?, ema_corto_contra_away=ema_corto_contra_away*?
                WHERE liga=?
            ''', (f, f, f, f, liga))
    except sqlite3.OperationalError:
        pass  # DB sin columnas ema_corto_*
    conn.commit()
    print(f'[ESCALA] equipos sin stats reescalados: {n_esc}. Cociente por liga: '
          + ', '.join(f'{l}={f:.3f}' for l, f in sorted(escala.items())))
    print(f'[APLICADO] ema_prior_por_equipo=TRUE, factor global={k_global}, '
          f'{len(res_nuevo)} ligas recalibradas, {n_upd} EMAs reescritas.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--aplicar', action='store_true')
    ap.add_argument('--liga', default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    partidos = cargar_partidos(cur, args.liga)
    print(f'Partidos liquidados con stats: {len(partidos)}')
    if not partidos:
        print('Nada que evaluar.')
        return
    rhos = {l: r for l, r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")
            if r is not None}
    cuotas = {i: (a, b, c) for i, a, b, c in cur.execute(
        "SELECT id_partido, cuota_1, cuota_x, cuota_2 FROM partidos_backtest "
        "WHERE cuota_1 > 1 AND cuota_x > 1 AND cuota_2 > 1")}
    ligas = {p[2] for p in partidos}
    factores_actuales = {l: get_param('factor_corr_xg_ou', scope=l, default=0.627) for l in ligas}

    _, filas_viejo = replay_con_pronosticos(conn, partidos, prior_por_equipo=False)
    _, filas_nuevo = replay_con_pronosticos(conn, partidos, prior_por_equipo=True)
    res_viejo = metricas(filas_viejo, rhos, cuotas, factores_actuales)
    res_nuevo = metricas(filas_nuevo, rhos, cuotas, None)
    _imprimir('PRIOR LEGACY (por partido) + factor_corr_xg_ou actual', res_viejo)
    _imprimir('PRIOR POR EQUIPO + factor O/U calibrado en 1ra mitad', res_nuevo)
    print('\nLeer: k~1 = escala correcta. Brier/LL menores = mejor. LL_OU es fuera de muestra (2da mitad).')
    print('\n=== 1X2 2da mitad: lambdas crudas vs escaladas por k (decide flag escalar_lambda_1x2) ===')
    for liga, r in res_nuevo.items():
        if r['ll_1x2_crudo_2da'] is not None:
            mejor = 'ESCALAR' if r['ll_1x2_escalado_2da'] < r['ll_1x2_crudo_2da'] else 'crudo'
            print(f'{liga:<14} crudo={r["ll_1x2_crudo_2da"]:.4f} escalado={r["ll_1x2_escalado_2da"]:.4f} -> {mejor}')
    print('El Brier 1X2 del modelo usa lambdas crudas, igual que motor_calculadora.')

    if args.aplicar:
        aplicar(conn, partidos, res_nuevo)
    conn.close()


if __name__ == '__main__':
    main()

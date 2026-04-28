"""[adepor-edk Opcion D extension] Caracterizar la POBLACION de picks afectados
por H4 X-rescue (override 'X' si V12 argmax=X y P_v12(X) > 0.35).

Por temp 2022/2023/2024 + in-sample 2026:
  - Lista de partidos X-rescue
  - Equipos involucrados (local, visita) con frecuencia
  - Posicion forward (al partido) y backward (final temp)
  - EMA tacticas (pos, pass_pct, shot_pct, sots) -> perfil ofensivo/defensivo
  - Outcome real y resultado del override (gano/perdio)

Salida: analisis/audit_yield_F2_x_rescue_population.json + .md
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import limpiar_texto

from analisis.yield_v0_v12_F2_completo import (
    probs_dc, predict_lr, feats_v12, calc_xg_legacy, calc_xg_v6,
    ajustar, real_o, amax,
    LIGAS_HIST_FULL, LIGAS_TEST,
    ALFA,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = ROOT / "fondo_quant.db"
OUT_JSON = Path(__file__).resolve().parent / "audit_yield_F2_x_rescue_population.json"
OUT_MD = Path(__file__).resolve().parent / "audit_yield_F2_x_rescue_population.md"
H4_THRESH = 0.35


def cargar_pos_backward(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pts.liga, pts.temp, pts.formato, pts.equipo, pts.posicion
        FROM posiciones_tabla_snapshot pts
        WHERE pts.fecha_snapshot = (
            SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
            WHERE liga = pts.liga AND temp = pts.temp AND formato = pts.formato
        )
    """).fetchall()
    out = {}
    for liga, temp, fm, eq, pos in rows:
        if fm in ("anual", "liga"):
            out[(liga, temp, eq)] = pos
    return out


def cargar_pos_forward(con):
    """Pos_forward: posicion al partido en predicciones_oos_con_features."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, temp, fecha, local, visita, pos_local, pos_visita
        FROM predicciones_oos_con_features
        WHERE pos_local IS NOT NULL AND pos_visita IS NOT NULL
    """).fetchall()
    out = {}
    for liga, temp, fecha, local, visita, pl, pv in rows:
        out[(liga, temp, str(fecha)[:10], local, visita)] = {'pl': pl, 'pv': pv}
    return out


def cargar_ema_estado(con, equipo, liga, fecha):
    """Ultimo snapshot ema_l_* y ema_c_* del equipo antes de fecha."""
    cur = con.cursor()
    r = cur.execute("""
        SELECT ema_l_pos, ema_c_pos, ema_l_pass_pct, ema_c_pass_pct,
               ema_l_shot_pct, ema_c_shot_pct, ema_l_sots, ema_c_sots,
               ema_l_corners, ema_c_corners
        FROM historial_equipos_stats
        WHERE liga=? AND equipo=? AND fecha < ? AND n_acum >= 5
        ORDER BY fecha DESC LIMIT 1
    """, (liga, equipo, fecha)).fetchone()
    if not r: return None
    return {
        'ema_l_pos': r[0], 'ema_c_pos': r[1],
        'ema_l_pass_pct': r[2], 'ema_c_pass_pct': r[3],
        'ema_l_shot_pct': r[4], 'ema_c_shot_pct': r[5],
        'ema_l_sots': r[6], 'ema_c_sots': r[7],
        'ema_l_corners': r[8], 'ema_c_corners': r[9],
    }


def construir_emas(con, temps_warmup):
    cur = con.cursor()
    cc_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats")}
    ols_pl = {}
    for r in cur.execute("SELECT scope, clave, valor_real FROM config_motor_valores WHERE clave LIKE '%_v6_shadow'"):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val
    rows = cur.execute(f"""
        SELECT liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats=1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({','.join(['?']*len(LIGAS_HIST_FULL))})
          AND temp IN ({','.join(['?']*len(temps_warmup))})
        ORDER BY fecha ASC
    """, LIGAS_HIST_FULL + list(temps_warmup)).fetchall()
    ema6 = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    emaL = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)
    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        cc_l = cc_pl.get(liga, 0.02)
        xg6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        xg6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        xgL_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc_l), hg, ag)
        xgL_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc_l), ag, hg)
        for em, lo, vi in [(ema6, xg6_l, xg6_v), (emaL, xgL_l, xgL_v)]:
            el = em[ht_n]; ev = em[at_n]
            if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
            else:
                el['fh'] = ALFA*lo + (1-ALFA)*el['fh']; el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
            if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
            else:
                ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']; ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
        v_l = var_eq[ht_n]; v_v = var_eq[at_n]
        if ema6[ht_n]['fh'] is not None: v_l['vfh'] = ALFA*(xg6_l - ema6[ht_n]['fh'])**2 + (1-ALFA)*v_l['vfh']
        if ema6[at_n]['fa'] is not None: v_v['vfa'] = ALFA*(xg6_v - ema6[at_n]['fa'])**2 + (1-ALFA)*v_v['vfa']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})
    return {'ema6': ema6, 'emaL': emaL, 'var_eq': var_eq, 'h2h': h2h, 'cc_pl': cc_pl, 'ols_pl': ols_pl}


def evaluar_y_capturar_x_rescue(con, estado, temp, rho_pl, pesos, fuente='oos'):
    cur = con.cursor()
    if fuente == 'oos':
        rows = cur.execute(f"""
            SELECT phe.liga, phe.fecha, phe.ht, phe.at, phe.hg, phe.ag,
                   phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac,
                   ce.psch, ce.pscd, ce.psca, ce.avgch, ce.avgcd, ce.avgca, phe.temp
            FROM partidos_historico_externo phe
            INNER JOIN cuotas_externas_historico ce
                ON ce.liga=phe.liga AND ce.fecha=substr(phe.fecha,1,10)
                AND ce.ht=phe.ht AND ce.at=phe.at
            WHERE phe.has_full_stats=1 AND phe.temp = ?
              AND phe.liga IN ({','.join(['?']*len(LIGAS_TEST))})
              AND ce.psch IS NOT NULL
            ORDER BY phe.fecha ASC
        """, [temp] + LIGAS_TEST).fetchall()
    else:  # in-sample 2026
        rows = cur.execute(f"""
            SELECT pais AS liga, fecha, local AS ht, visita AS at, goles_l AS hg, goles_v AS ag,
                   sot_l AS hst, shots_l AS hs, corners_l AS hc, sot_v AS ast, shots_v AS as_, corners_v AS ac,
                   cuota_1 AS psch, cuota_x AS pscd, cuota_2 AS psca, NULL, NULL, NULL, '2026'
            FROM partidos_backtest
            WHERE cuota_1>1 AND cuota_x>1 AND cuota_2>1
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
              AND sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
              AND pais IN ({','.join(['?']*len(LIGAS_TEST))})
              AND substr(fecha, 1, 4) = '2026'
            ORDER BY fecha ASC
        """, LIGAS_TEST).fetchall()

    ema6 = estado['ema6']; emaL = estado['emaL']
    var_eq = estado['var_eq']; h2h = estado['h2h']
    cc_pl = estado['cc_pl']; ols_pl = estado['ols_pl']

    x_picks = []
    for row in rows:
        (liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac,
         psch, pscd, psca, avgch, avgcd, avgca, temp_row) = row
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e6_l = ema6.get(ht_n); e6_v = ema6.get(at_n)
        eL_l = emaL.get(ht_n); eL_v = emaL.get(at_n)
        if not e6_l or not e6_v or not eL_l or not eL_v: continue
        if any(e6_l.get(k) is None for k in ('fh','ch')) or any(e6_v.get(k) is None for k in ('fa','ca')): continue
        if any(eL_l.get(k) is None for k in ('fh','ch')) or any(eL_v.get(k) is None for k in ('fa','ca')): continue
        c1 = psch or avgch; cx = pscd or avgcd; c2 = psca or avgca
        if not (c1 and cx and c2 and c1 > 1 and cx > 1 and c2 > 1): continue
        xg6_l = max(0.10, (e6_l['fh']+e6_v['ca'])/2); xg6_v = max(0.10, (e6_v['fa']+e6_l['ch'])/2)
        xgL_l = max(0.10, (eL_l['fh']+eL_v['ca'])/2); xgL_v = max(0.10, (eL_v['fa']+eL_l['ch'])/2)
        rho = rho_pl.get(liga, -0.04)
        real = real_o(hg, ag)
        prev = []
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
            prev.extend(h2h.get(k, []))
        if prev:
            avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
            n_l = sum(1 for p in prev if (p['home']==ht_n and p['hg']>p['ag']) or (p['home']!=ht_n and p['ag']>p['hg']))
            n_x = sum(1 for p in prev if p['hg']==p['ag'])
            f_loc = n_l/len(prev); f_x = n_x/len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26
        v_l_t = var_eq.get(ht_n, {'vfh':0.5}); v_v_t = var_eq.get(at_n, {'vfa':0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        ff = feats_v12(xg6_l, xg6_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        v12_payload = pesos.get(liga, pesos.get('global', {}))
        v0_p = probs_dc(xgL_l, xgL_v, rho)
        v12_p = predict_lr(ff, v12_payload) if v12_payload else (1/3, 1/3, 1/3)

        am_v0 = amax(*v0_p); am_v12 = amax(*v12_p)
        es_x_rescue = am_v12 == 'X' and v12_p[1] > H4_THRESH

        if es_x_rescue:
            x_picks.append({
                'liga': liga, 'temp': str(temp), 'fecha': str(fecha)[:10],
                'local': ht, 'visita': at, 'local_norm': ht_n, 'visita_norm': at_n,
                'hg': hg, 'ag': ag, 'real': real,
                'p1_v12': round(v12_p[0], 4), 'px_v12': round(v12_p[1], 4), 'p2_v12': round(v12_p[2], 4),
                'p1_v0': round(v0_p[0], 4), 'px_v0': round(v0_p[1], 4), 'p2_v0': round(v0_p[2], 4),
                'cuota_1': c1, 'cuota_x': cx, 'cuota_2': c2,
                'argmax_v0': am_v0, 'argmax_v12': am_v12,
                'override_aplicado': 'X',
                'gano_h4': real == 'X',
                'profit_h4': (cx - 1) if real == 'X' else -1,
                'profit_v0_alternativo': (
                    (c1 - 1) if (am_v0 == '1' and real == '1') else
                    (c2 - 1) if (am_v0 == '2' and real == '2') else
                    (cx - 1) if (am_v0 == 'X' and real == 'X') else -1
                ),
            })

        # update EMAs
        cc_l = cc_pl.get(liga, 0.02)
        new_xg6_l = ajustar(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        new_xg6_v = ajustar(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        new_xgL_l = ajustar(calc_xg_legacy(hst, hs, hc, hg, cc_l), hg, ag)
        new_xgL_v = ajustar(calc_xg_legacy(ast, as_, ac, ag, cc_l), ag, hg)
        for em, lo, vi in [(ema6, new_xg6_l, new_xg6_v), (emaL, new_xgL_l, new_xgL_v)]:
            el = em[ht_n]; ev = em[at_n]
            if el['fh'] is None: el['fh'] = lo; el['ch'] = vi
            else:
                el['fh'] = ALFA*lo + (1-ALFA)*el['fh']; el['ch'] = ALFA*vi + (1-ALFA)*el['ch']
            if ev['fa'] is None: ev['fa'] = vi; ev['ca'] = lo
            else:
                ev['fa'] = ALFA*vi + (1-ALFA)*ev['fa']; ev['ca'] = ALFA*lo + (1-ALFA)*ev['ca']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})
    return x_picks


def perfil_tactico(ema):
    """Clasifica perfil ofensivo segun EMA stats."""
    if not ema: return "?"
    pos = ema.get('ema_l_pos', 50) or 50
    pass_pct = ema.get('ema_l_pass_pct', 0.4) or 0.4
    sots = ema.get('ema_l_sots', 4) or 4
    if pos > 53 and pass_pct > 0.45:
        return "POSESIONAL"
    elif pos < 47:
        return "CONTRAATAQUE"
    elif sots > 5.5:
        return "OFENSIVO"
    else:
        return "EQUILIBRADO"


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}
    pesos = {}
    for r in cur.execute("""SELECT scope, valor_texto FROM config_motor_valores
                             WHERE clave='lr_v12_weights'"""):
        if r[1]: pesos[r[0]] = json.loads(r[1])

    print("Cargando pos_backward + pos_forward...")
    pos_back = cargar_pos_backward(con)
    pos_fwd = cargar_pos_forward(con)

    payload = {'fecha': '2026-04-28', 'h4_threshold': H4_THRESH, 'temps': {}}
    todos_picks = []

    for nombre, warmup, test_temp, fuente in [
        ('test_2022', [2021], 2022, 'oos'),
        ('test_2023', [2021, 2022], 2023, 'oos'),
        ('test_2024', [2021, 2022, 2023], 2024, 'oos'),
        ('in_sample_2026', [2021, 2022, 2023, 2024], '2026', 'in_sample'),
    ]:
        print(f"\n=== {nombre} (warmup={warmup}) ===")
        estado = construir_emas(con, warmup)
        x_picks = evaluar_y_capturar_x_rescue(con, estado, test_temp, rho_pl, pesos, fuente)
        print(f"  X-rescue picks: {len(x_picks)}")
        # Enrich each pick with pos + tactical
        for p in x_picks:
            key_l = (p['liga'], int(p['temp']) if p['temp'] != '2026' else 2026, p['local'])
            key_v = (p['liga'], int(p['temp']) if p['temp'] != '2026' else 2026, p['visita'])
            p['pos_local_back'] = pos_back.get(key_l)
            p['pos_visita_back'] = pos_back.get(key_v)
            kf = (p['liga'], int(p['temp']) if p['temp'] != '2026' else 2026, p['fecha'], p['local'], p['visita'])
            f = pos_fwd.get(kf)
            p['pos_local_fwd'] = f['pl'] if f else None
            p['pos_visita_fwd'] = f['pv'] if f else None
            ema_l = cargar_ema_estado(con, p['local'], p['liga'], p['fecha'])
            ema_v = cargar_ema_estado(con, p['visita'], p['liga'], p['fecha'])
            p['ema_local'] = ema_l
            p['ema_visita'] = ema_v
            p['perfil_local'] = perfil_tactico(ema_l)
            p['perfil_visita'] = perfil_tactico(ema_v)
        payload['temps'][nombre] = x_picks
        todos_picks.extend(x_picks)

    # ============ ANALISIS GLOBAL ============
    print("\n" + "=" * 95)
    print("ANALISIS GLOBAL DE LA POBLACION X-RESCUE")
    print("=" * 95)

    print(f"\nTotal X-rescue picks across all windows: {len(todos_picks)}")
    print(f"Hit rate H4: {sum(1 for p in todos_picks if p['gano_h4']) / max(1, len(todos_picks)) * 100:.1f}%")
    print(f"Profit total H4: {sum(p['profit_h4'] for p in todos_picks):+.2f}")
    print(f"Profit alternativo V0: {sum(p['profit_v0_alternativo'] for p in todos_picks):+.2f}")
    print(f"Delta H4 vs V0 unidades: {sum(p['profit_h4'] for p in todos_picks) - sum(p['profit_v0_alternativo'] for p in todos_picks):+.2f}")

    # Top equipos
    print(f"\n--- Top equipos como LOCAL en X-rescue ---")
    cnt_l = Counter((p['liga'], p['local']) for p in todos_picks)
    for (liga, eq), n in cnt_l.most_common(15):
        print(f"  {liga:<14} {eq:<30} N={n}")

    print(f"\n--- Top equipos como VISITA en X-rescue ---")
    cnt_v = Counter((p['liga'], p['visita']) for p in todos_picks)
    for (liga, eq), n in cnt_v.most_common(15):
        print(f"  {liga:<14} {eq:<30} N={n}")

    # Distribucion por bucket pos_backward (calidad estructural REAL del partido)
    print(f"\n--- Distribucion bucket pos_backward (LOCAL) ---")
    def bk(p):
        if p is None: return "?"
        if p <= 3: return "TOP-3"
        if p <= 6: return "TOP-6"
        if p <= 12: return "MID"
        if p <= 16: return "BOT-6"
        return "BOT-3"
    bkl = Counter(bk(p['pos_local_back']) for p in todos_picks)
    for b, n in sorted(bkl.items()):
        print(f"  {b:<8} N={n} ({n/len(todos_picks)*100:.1f}%)")

    print(f"\n--- Distribucion bucket pos_backward (VISITA) ---")
    bkv = Counter(bk(p['pos_visita_back']) for p in todos_picks)
    for b, n in sorted(bkv.items()):
        print(f"  {b:<8} N={n} ({n/len(todos_picks)*100:.1f}%)")

    # Matchup type
    print(f"\n--- Matchup pos_backward (TOP-vs-TOP, BOT-vs-BOT, etc.) ---")
    mch = Counter()
    for p in todos_picks:
        b1 = bk(p['pos_local_back']); b2 = bk(p['pos_visita_back'])
        # Aggregate to simpler buckets
        s1 = "TOP" if b1 in ("TOP-3", "TOP-6") else ("MID" if b1 == "MID" else ("BOT" if b1 in ("BOT-6", "BOT-3") else "?"))
        s2 = "TOP" if b2 in ("TOP-3", "TOP-6") else ("MID" if b2 == "MID" else ("BOT" if b2 in ("BOT-6", "BOT-3") else "?"))
        mch[f"{s1}-vs-{s2}"] += 1
    for m, n in sorted(mch.items(), key=lambda x: -x[1]):
        print(f"  {m:<14} N={n} ({n/len(todos_picks)*100:.1f}%)")

    # Distribucion de resultados reales
    print(f"\n--- Resultado real cuando V12 forzo X ---")
    res = Counter(p['real'] for p in todos_picks)
    for r in ['1', 'X', '2']:
        n = res.get(r, 0)
        print(f"  outcome={r}: N={n} ({n/len(todos_picks)*100:.1f}%)")

    # Perfil tactico
    print(f"\n--- Perfil tactico LOCAL ---")
    pl = Counter(p['perfil_local'] for p in todos_picks)
    for perf, n in sorted(pl.items(), key=lambda x: -x[1]):
        print(f"  {perf:<14} N={n} ({n/len(todos_picks)*100:.1f}%)")

    print(f"\n--- Perfil tactico VISITA ---")
    pv = Counter(p['perfil_visita'] for p in todos_picks)
    for perf, n in sorted(pv.items(), key=lambda x: -x[1]):
        print(f"  {perf:<14} N={n} ({n/len(todos_picks)*100:.1f}%)")

    # EMA stats medias
    print(f"\n--- EMA stats medias en partidos X-rescue (vs liga global) ---")
    ema_features = ['ema_l_pos', 'ema_l_pass_pct', 'ema_l_shot_pct', 'ema_l_sots', 'ema_l_corners']
    for f in ema_features:
        vs_l = [p['ema_local'][f] for p in todos_picks if p['ema_local'] and p['ema_local'].get(f) is not None]
        vs_v = [p['ema_visita'][f] for p in todos_picks if p['ema_visita'] and p['ema_visita'].get(f) is not None]
        if vs_l:
            print(f"  {f:<20} local mean={mean(vs_l):.3f} (N={len(vs_l)})")
        if vs_v:
            print(f"  {f.replace('_l_', '_v_'):<20} visita mean={mean(vs_v):.3f} (N={len(vs_v)})")

    payload['analisis_global'] = {
        'total': len(todos_picks),
        'hit_h4': sum(1 for p in todos_picks if p['gano_h4']),
        'profit_h4': round(sum(p['profit_h4'] for p in todos_picks), 4),
        'profit_v0': round(sum(p['profit_v0_alternativo'] for p in todos_picks), 4),
        'top_locales': [(' / '.join(map(str, k)), v) for k, v in cnt_l.most_common(15)],
        'top_visitas': [(' / '.join(map(str, k)), v) for k, v in cnt_v.most_common(15)],
        'bucket_local': dict(bkl), 'bucket_visita': dict(bkv),
        'matchup': dict(mch), 'real_distribution': dict(res),
        'perfil_local': dict(pl), 'perfil_visita': dict(pv),
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT_JSON}")
    con.close()


if __name__ == "__main__":
    main()

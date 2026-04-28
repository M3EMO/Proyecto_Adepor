"""[adepor-5y0 sub-6 multidim] Audit cruzado de la poblacion X-rescue:
H4 × cansancio (gap_dias_no_liga) × pos_backward × perfil tactico × cuota_X × liga × matchup.

Objetivo: encontrar la conjuncion de features que MAXIMIZA el alpha del Layer 3.
Output: ranking de subgrupos por delta H4 vs V0 + sig estadistica.

Tier 1: features unidimensionales (ya hecho — referencia)
Tier 2: cruzes 2D
Tier 3: cruzes 3D + filtros conjuntos
Tier 4: por equipo individual
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
INPUT = ROOT / "analisis" / "audit_yield_F2_x_rescue_population.json"
OUT_JSON = ROOT / "analisis" / "audit_x_rescue_multidim.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def gap_dias_no_liga(con, equipo, fecha):
    cur = con.cursor()
    r = cur.execute("""
        SELECT fecha FROM v_partidos_unificado
        WHERE (equipo_local=? OR equipo_visita=?)
          AND fecha < ? AND competicion_tipo != 'liga'
        ORDER BY fecha DESC LIMIT 1
    """, (equipo, equipo, fecha[:10])).fetchone()
    if not r: return None
    d1 = datetime.strptime(r[0], '%Y-%m-%d')
    d2 = datetime.strptime(fecha[:10], '%Y-%m-%d')
    return (d2 - d1).days


def yield_metrics(picks):
    if not picks: return None
    n = len(picks)
    p_h4 = [p['profit_h4'] for p in picks]
    p_v0 = [p['profit_v0_alternativo'] for p in picks]
    yld_h4 = sum(p_h4) / n
    yld_v0 = sum(p_v0) / n
    delta = yld_h4 - yld_v0
    hits_x = sum(1 for p in picks if p['gano_h4'])
    rng = np.random.default_rng(42)
    deltas = []
    a_h4 = np.array(p_h4); a_v0 = np.array(p_v0)
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        d = (a_h4[idx].sum() - a_v0[idx].sum()) / n
        deltas.append(d)
    return {
        'n': n,
        'hit_x_pct': round(100 * hits_x / n, 1),
        'yield_h4': round(yld_h4, 3),
        'yield_v0': round(yld_v0, 3),
        'delta': round(delta, 3),
        'ci95_lo': round(float(np.percentile(deltas, 2.5)), 3),
        'ci95_hi': round(float(np.percentile(deltas, 97.5)), 3),
        'sig_pos': float(np.percentile(deltas, 2.5)) > 0,
        'sig_neg': float(np.percentile(deltas, 97.5)) < 0,
    }


def fmt_metrics(m):
    if not m: return ""
    sig = '★ POS' if m['sig_pos'] else ('★ NEG' if m['sig_neg'] else '.')
    return (f"N={m['n']:>3} hitX={m['hit_x_pct']:>5.1f}% "
            f"H4={m['yield_h4']:+6.3f} V0={m['yield_v0']:+6.3f} "
            f"d={m['delta']:+6.3f} [{m['ci95_lo']:+5.2f},{m['ci95_hi']:+5.2f}] {sig}")


def pos_b(p):
    if p is None: return "?"
    if p <= 3: return "TOP3"
    if p <= 6: return "TOP6"
    if p <= 12: return "MID"
    if p <= 16: return "BOT6"
    return "BOT3"


def cuota_b(c):
    if c is None: return "?"
    if c < 3.0: return "<3.0"
    if c < 3.5: return "3.0-3.5"
    if c < 4.0: return "3.5-4.0"
    if c < 5.0: return "4.0-5.0"
    return ">=5.0"


def main():
    con = sqlite3.connect(DB)
    payload = json.load(open(INPUT, encoding='utf-8'))
    todos = []
    for picks in payload['temps'].values():
        todos.extend(picks)
    print(f"Total X-rescue picks: {len(todos)}")

    # Etiquetar con cansancio
    print("Calculando cansancio + buckets...")
    for p in todos:
        gl = gap_dias_no_liga(con, p['local'], p['fecha'])
        gv = gap_dias_no_liga(con, p['visita'], p['fecha'])
        p['gap_l'] = gl; p['gap_v'] = gv
        p['cans_l_14'] = (gl is not None and gl <= 14)
        p['cans_v_14'] = (gv is not None and gv <= 14)
        p['cans_l_7']  = (gl is not None and gl <= 7)
        p['cans_v_7']  = (gv is not None and gv <= 7)
        p['ambos_14']  = p['cans_l_14'] and p['cans_v_14']
        p['ninguno_14'] = (not p['cans_l_14']) and (not p['cans_v_14'])
        p['cualquiera_14'] = p['cans_l_14'] or p['cans_v_14']
        p['pos_l_b'] = pos_b(p.get('pos_local_back'))
        p['pos_v_b'] = pos_b(p.get('pos_visita_back'))
        p['cuota_x_b'] = cuota_b(p['cuota_x'])

    # ============== TIER 1: features unidimensionales ==============
    print("\n" + "=" * 100)
    print("TIER 1 — referencia unidim")
    print("=" * 100)
    print(f"{'split':<35} {'N':>4} {'hitX%':>6} {'H4':>7} {'V0':>7} {'delta':>7} {'CI95':>20} {'sig':>5}")
    splits1 = [
        ('TODOS',                        lambda p: True),
        ('SIN cansancio 14d (ambos)',    lambda p: p['ninguno_14']),
        ('AMBOS ≤14d',                   lambda p: p['ambos_14']),
        ('Local ≤7d',                    lambda p: p['cans_l_7']),
        ('Visita ≤7d',                   lambda p: p['cans_v_7']),
    ]
    res_t1 = {}
    for nombre, fn in splits1:
        sub = [p for p in todos if fn(p)]
        m = yield_metrics(sub)
        print(f"{nombre:<35} " + (fmt_metrics(m) if m else "vacio"))
        res_t1[nombre] = m

    # ============== TIER 2: 2D cruzes ==============
    print("\n" + "=" * 100)
    print("TIER 2 — cansancio × LIGA")
    print("=" * 100)
    res_t2 = {}
    for liga in sorted(set(p['liga'] for p in todos)):
        for nombre_can, fn_can in [('SIN_can_14d', lambda p: p['ninguno_14']),
                                     ('CON_cualquiera_14d', lambda p: p['cualquiera_14']),
                                     ('AMBOS_14d', lambda p: p['ambos_14'])]:
            sub = [p for p in todos if p['liga'] == liga and fn_can(p)]
            if len(sub) < 3: continue
            m = yield_metrics(sub)
            label = f"{liga} · {nombre_can}"
            print(f"{label:<35} " + (fmt_metrics(m) if m else "vacio"))
            res_t2[label] = m

    print("\n" + "=" * 100)
    print("TIER 2 — cansancio × pos_local_back")
    print("=" * 100)
    for pos_b_v in ['TOP3', 'TOP6', 'MID', 'BOT6', 'BOT3', '?']:
        for nombre_can, fn_can in [('SIN_can_14d', lambda p: p['ninguno_14']),
                                     ('CON_cualquiera_14d', lambda p: p['cualquiera_14'])]:
            sub = [p for p in todos if p['pos_l_b'] == pos_b_v and fn_can(p)]
            if len(sub) < 5: continue
            m = yield_metrics(sub)
            label = f"pos_l={pos_b_v} · {nombre_can}"
            print(f"{label:<35} " + (fmt_metrics(m) if m else ""))
            res_t2[label] = m

    print("\n" + "=" * 100)
    print("TIER 2 — cansancio × perfil_local")
    print("=" * 100)
    for perf in ['CONTRAATAQUE', 'EQUILIBRADO', 'POSESIONAL', 'OFENSIVO', '?']:
        for nombre_can, fn_can in [('SIN_can_14d', lambda p: p['ninguno_14']),
                                     ('CON_cualquiera_14d', lambda p: p['cualquiera_14'])]:
            sub = [p for p in todos if p['perfil_local'] == perf and fn_can(p)]
            if len(sub) < 5: continue
            m = yield_metrics(sub)
            label = f"perfil_l={perf} · {nombre_can}"
            print(f"{label:<35} " + (fmt_metrics(m) if m else ""))
            res_t2[label] = m

    print("\n" + "=" * 100)
    print("TIER 2 — cansancio × cuota_X bucket")
    print("=" * 100)
    for cb in ['<3.0', '3.0-3.5', '3.5-4.0', '4.0-5.0', '>=5.0']:
        for nombre_can, fn_can in [('SIN_can_14d', lambda p: p['ninguno_14']),
                                     ('CON_cualquiera_14d', lambda p: p['cualquiera_14'])]:
            sub = [p for p in todos if p['cuota_x_b'] == cb and fn_can(p)]
            if len(sub) < 5: continue
            m = yield_metrics(sub)
            label = f"cuotaX={cb} · {nombre_can}"
            print(f"{label:<35} " + (fmt_metrics(m) if m else ""))
            res_t2[label] = m

    print("\n" + "=" * 100)
    print("TIER 2 — matchup pos × cansancio")
    print("=" * 100)
    for p in todos:
        s1 = "TOP" if p['pos_l_b'] in ('TOP3','TOP6') else ('MID' if p['pos_l_b']=='MID' else ('BOT' if p['pos_l_b'] in ('BOT3','BOT6') else '?'))
        s2 = "TOP" if p['pos_v_b'] in ('TOP3','TOP6') else ('MID' if p['pos_v_b']=='MID' else ('BOT' if p['pos_v_b'] in ('BOT3','BOT6') else '?'))
        p['matchup'] = f"{s1}-vs-{s2}"
    matchups_orden = ['TOP-vs-TOP', 'TOP-vs-MID', 'MID-vs-TOP', 'MID-vs-MID',
                      'TOP-vs-BOT', 'BOT-vs-TOP', 'BOT-vs-MID', 'MID-vs-BOT', 'BOT-vs-BOT']
    for mch in matchups_orden:
        for nombre_can, fn_can in [('SIN_can_14d', lambda p: p['ninguno_14']),
                                     ('CON_cualquiera_14d', lambda p: p['cualquiera_14'])]:
            sub = [p for p in todos if p['matchup'] == mch and fn_can(p)]
            if len(sub) < 4: continue
            m = yield_metrics(sub)
            label = f"{mch} · {nombre_can}"
            print(f"{label:<35} " + (fmt_metrics(m) if m else ""))
            res_t2[label] = m

    # ============== TIER 3: 3D cruzes top ==============
    print("\n" + "=" * 100)
    print("TIER 3 — liga × pos_local × cansancio (filtrado)")
    print("=" * 100)
    res_t3 = {}
    for liga in ['Argentina', 'Inglaterra', 'Italia']:
        for pos_b_v in ['TOP3', 'TOP6', 'MID', 'BOT6', 'BOT3', '?']:
            sub = [p for p in todos if p['liga'] == liga and p['pos_l_b'] == pos_b_v and p['ninguno_14']]
            if len(sub) < 4: continue
            m = yield_metrics(sub)
            label = f"{liga} · pos_l={pos_b_v} · SIN_can_14d"
            print(f"{label:<48} " + (fmt_metrics(m) if m else ""))
            res_t3[label] = m

    # ============== TIER 4: por equipo (top 15 con N>=5) ==============
    print("\n" + "=" * 100)
    print("TIER 4 — TOP equipos LOCALES (N>=4) breakdown cansancio")
    print("=" * 100)
    by_eq = defaultdict(list)
    for p in todos: by_eq[(p['liga'], p['local'])].append(p)
    by_eq = sorted(by_eq.items(), key=lambda x: -len(x[1]))
    res_t4 = {}
    for (liga, eq), sub in by_eq[:20]:
        if len(sub) < 4: continue
        sin = [p for p in sub if p['ninguno_14']]
        con = [p for p in sub if p['cualquiera_14']]
        m_all = yield_metrics(sub)
        m_sin = yield_metrics(sin) if sin else None
        m_con = yield_metrics(con) if con else None
        print(f"\n  {liga} {eq} (total N={len(sub)}):")
        print(f"    {'TOTAL':<25} " + fmt_metrics(m_all))
        if m_sin: print(f"    {'SIN_can_14d':<25} " + fmt_metrics(m_sin))
        if m_con: print(f"    {'CON_cualquiera_14d':<25} " + fmt_metrics(m_con))
        res_t4[f"{liga}/{eq}"] = {'total': m_all, 'sin_can': m_sin, 'con_can': m_con}

    # ============== TIER 5: rankings finales por delta ==============
    print("\n" + "=" * 100)
    print("TIER 5 — TOP-15 subgrupos con DELTA mas positivo (N>=5)")
    print("=" * 100)
    cands = []
    for k, m in {**res_t1, **res_t2, **res_t3}.items():
        if m and m['n'] >= 5:
            cands.append((k, m))
    cands.sort(key=lambda x: -x[1]['delta'])
    for k, m in cands[:15]:
        print(f"  {k:<48} " + fmt_metrics(m))

    print("\n" + "=" * 100)
    print("TIER 5 — TOP-10 subgrupos con DELTA mas NEGATIVO (N>=5)")
    print("=" * 100)
    cands.sort(key=lambda x: x[1]['delta'])
    for k, m in cands[:10]:
        print(f"  {k:<48} " + fmt_metrics(m))

    out = {
        'fecha': '2026-04-28',
        'tier1': res_t1, 'tier2': res_t2, 'tier3': res_t3, 'tier4': res_t4,
        'top_positivos': [(k, m) for k, m in cands[:20]],
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT_JSON}")
    con.close()


if __name__ == "__main__":
    main()

"""[adepor-5y0 sub-6] Split de X-rescue picks por cansancio (copa previa <72h, <96h, <14d, none).

Hipotesis: equipos con copa internacional/nacional reciente (cansancio mid-week)
tienen mayor tendencia al empate -> H4 X-rescue genera mas alpha en ese subset.

Per pick, calcular:
  cansancio_local_72h = 1 if local jugo copa <=3 dias antes
  cansancio_local_96h = 1 if local jugo copa <=4 dias antes
  cansancio_local_14d = 1 if local jugo copa <=14 dias antes
  (idem visita)
  cualquier_cansancio_72h = local OR visita
  ambos_cansancio_72h    = local AND visita

Comparar hit X% / yield H4 / delta vs V0 entre subgrupos.

Salida: analisis/audit_x_rescue_cansancio_split.{json,md}
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
INPUT = ROOT / "analisis" / "audit_yield_F2_x_rescue_population.json"
OUT_JSON = ROOT / "analisis" / "audit_x_rescue_cansancio_split.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def gap_dias_no_liga(con, equipo, fecha):
    cur = con.cursor()
    r = cur.execute("""
        SELECT fecha, competicion FROM v_partidos_unificado
        WHERE (equipo_local=? OR equipo_visita=?)
          AND fecha < ? AND competicion_tipo != 'liga'
        ORDER BY fecha DESC LIMIT 1
    """, (equipo, equipo, fecha[:10])).fetchone()
    if not r: return None, None
    d1 = datetime.strptime(r[0], '%Y-%m-%d')
    d2 = datetime.strptime(fecha[:10], '%Y-%m-%d')
    return (d2 - d1).days, r[1]


def yield_metrics(picks, decisor_h4=True):
    """picks: lista de dict con cuotas, real, gano_h4, profit_h4, profit_v0_alternativo."""
    if not picks:
        return {'n': 0, 'yield_h4': None, 'yield_v0': None, 'delta': None,
                'hit_x_pct': None, 'ci95_lo': None, 'ci95_hi': None}
    n = len(picks)
    profits_h4 = [p['profit_h4'] for p in picks]
    profits_v0 = [p['profit_v0_alternativo'] for p in picks]
    yld_h4 = sum(profits_h4) / n
    yld_v0 = sum(profits_v0) / n
    hits_x = sum(1 for p in picks if p['gano_h4'])
    # bootstrap CI95 sobre delta H4-V0
    rng = np.random.default_rng(42)
    deltas = []
    arr_h4 = np.array(profits_h4); arr_v0 = np.array(profits_v0)
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        d = (arr_h4[idx].sum() - arr_v0[idx].sum()) / n
        deltas.append(d)
    return {
        'n': n,
        'yield_h4': round(yld_h4, 4),
        'yield_v0': round(yld_v0, 4),
        'delta': round(yld_h4 - yld_v0, 4),
        'hit_x_pct': round(100 * hits_x / n, 2),
        'ci95_lo': round(float(np.percentile(deltas, 2.5)), 4),
        'ci95_hi': round(float(np.percentile(deltas, 97.5)), 4),
    }


def main():
    con = sqlite3.connect(DB)
    payload = json.load(open(INPUT, encoding='utf-8'))
    todos = []
    for picks in payload['temps'].values():
        todos.extend(picks)
    print(f"Total X-rescue picks: {len(todos)}")

    # Etiquetar cada pick con su clase de cansancio
    print("Clasificando por cansancio...")
    for p in todos:
        gl, comp_l = gap_dias_no_liga(con, p['local'], p['fecha'])
        gv, comp_v = gap_dias_no_liga(con, p['visita'], p['fecha'])
        p['gap_local_no_liga'] = gl
        p['gap_visita_no_liga'] = gv
        p['comp_local'] = comp_l
        p['comp_visita'] = comp_v
        p['cansancio_local_72h']  = (gl is not None and gl <= 3)
        p['cansancio_local_96h']  = (gl is not None and gl <= 4)
        p['cansancio_local_7d']   = (gl is not None and gl <= 7)
        p['cansancio_local_14d']  = (gl is not None and gl <= 14)
        p['cansancio_visita_72h'] = (gv is not None and gv <= 3)
        p['cansancio_visita_96h'] = (gv is not None and gv <= 4)
        p['cansancio_visita_7d']  = (gv is not None and gv <= 7)
        p['cansancio_visita_14d'] = (gv is not None and gv <= 14)

    print()
    print("=" * 95)
    print("SPLIT POR CANSANCIO MID-WEEK (umbrales)")
    print("=" * 95)

    splits = [
        ('TODOS',                      lambda p: True),
        ('local cansancio <=72h',      lambda p: p['cansancio_local_72h']),
        ('local cansancio <=96h',      lambda p: p['cansancio_local_96h']),
        ('local cansancio <=7d',       lambda p: p['cansancio_local_7d']),
        ('local cansancio <=14d',      lambda p: p['cansancio_local_14d']),
        ('local SIN cansancio 14d',    lambda p: not p['cansancio_local_14d']),
        ('visita cansancio <=72h',     lambda p: p['cansancio_visita_72h']),
        ('visita cansancio <=96h',     lambda p: p['cansancio_visita_96h']),
        ('visita cansancio <=14d',     lambda p: p['cansancio_visita_14d']),
        ('cualquiera <=72h',           lambda p: p['cansancio_local_72h'] or p['cansancio_visita_72h']),
        ('cualquiera <=96h',           lambda p: p['cansancio_local_96h'] or p['cansancio_visita_96h']),
        ('cualquiera <=14d',           lambda p: p['cansancio_local_14d'] or p['cansancio_visita_14d']),
        ('NINGUNO <=14d',              lambda p: not (p['cansancio_local_14d'] or p['cansancio_visita_14d'])),
        ('AMBOS <=14d',                lambda p: p['cansancio_local_14d'] and p['cansancio_visita_14d']),
    ]

    resumen = {}
    print(f"{'split':<32} {'N':>5} {'hit_X%':>7} {'yld_H4':>8} {'yld_V0':>8} {'delta':>8} {'CI95':>22}")
    for nombre, fn in splits:
        sub = [p for p in todos if fn(p)]
        m = yield_metrics(sub)
        if m['n'] == 0:
            print(f"{nombre:<32} {0:>5} (vacio)")
            continue
        ci = f"[{m['ci95_lo']:+.3f}, {m['ci95_hi']:+.3f}]"
        sig = '***' if (m['ci95_lo'] is not None and m['ci95_lo'] > 0) else '.'
        print(f"{nombre:<32} {m['n']:>5} {m['hit_x_pct']:>7.1f} {m['yield_h4']:>+8.3f} {m['yield_v0']:>+8.3f} {m['delta']:>+8.3f} {ci:>22} {sig}")
        resumen[nombre] = m

    # Por liga: cansancio matters?
    print()
    print("=" * 95)
    print("Cansancio <=14d POR LIGA (delta H4-V0 con/sin cansancio)")
    print("=" * 95)
    by_liga = defaultdict(list)
    for p in todos:
        by_liga[p['liga']].append(p)
    print(f"{'liga':<14} {'cansados':>9} {'descansados':>12} {'delta_can':>10} {'delta_des':>10}")
    por_liga = {}
    for liga, sub in sorted(by_liga.items()):
        cansados = [p for p in sub if p['cansancio_local_14d'] or p['cansancio_visita_14d']]
        descan = [p for p in sub if not (p['cansancio_local_14d'] or p['cansancio_visita_14d'])]
        m_c = yield_metrics(cansados); m_d = yield_metrics(descan)
        d_c = f"{m_c['delta']:+.3f}" if m_c['delta'] is not None else 'n/a'
        d_d = f"{m_d['delta']:+.3f}" if m_d['delta'] is not None else 'n/a'
        print(f"{liga:<14} {m_c['n']:>9} {m_d['n']:>12} {d_c:>10} {d_d:>10}")
        por_liga[liga] = {'cansados': m_c, 'descansados': m_d}

    # Distribucion gap por categorias
    print()
    print("Distribucion competicion previa para los cansados (<=14d local):")
    cnt = Counter()
    for p in todos:
        if p['cansancio_local_14d'] and p['comp_local']:
            cnt[p['comp_local']] += 1
    for comp, n in cnt.most_common():
        print(f"  {comp:<25} N={n}")

    out = {
        'fecha': '2026-04-28',
        'n_total': len(todos),
        'splits': resumen,
        'por_liga': por_liga,
        'distribucion_competicion_local_cansado': dict(cnt),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT_JSON}")
    con.close()


if __name__ == "__main__":
    main()

"""[adepor-5y0] Audit cobertura: para cada X-rescue pick, computar gap_dias_local
y gap_dias_visita usando v_partidos_unificado. Reportar cobertura, mismatches, y
distribuciones de gap.

Si cobertura ≥80% → seguir con analisis cansancio.
Si <80% → agregar aliases para los equipos faltantes.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
INPUT = ROOT / "analisis" / "audit_yield_F2_x_rescue_population.json"
OUT = ROOT / "analisis" / "audit_x_rescue_cobertura_copas.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def gap_dias(con, equipo, fecha, max_window=30):
    """dias desde ultimo partido cualquiera (liga + copa) anterior a fecha."""
    cur = con.cursor()
    r = cur.execute("""
        SELECT fecha FROM v_partidos_unificado
        WHERE (equipo_local=? OR equipo_visita=?) AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (equipo, equipo, fecha[:10])).fetchone()
    if not r:
        return None, None
    d1 = datetime.strptime(r[0], '%Y-%m-%d')
    d2 = datetime.strptime(fecha[:10], '%Y-%m-%d')
    return (d2 - d1).days, r[0]


def ultimo_no_liga(con, equipo, fecha, max_window=14):
    """ultimo partido NO-LIGA (copa) en window. Retorna (gap_dias, competicion) o (None, None)."""
    cur = con.cursor()
    r = cur.execute("""
        SELECT fecha, competicion FROM v_partidos_unificado
        WHERE (equipo_local=? OR equipo_visita=?)
          AND fecha < ? AND competicion_tipo != 'liga'
          AND date(fecha) >= date(?, ?)
        ORDER BY fecha DESC LIMIT 1
    """, (equipo, equipo, fecha[:10], fecha[:10], f'-{max_window} days')).fetchone()
    if not r:
        return None, None
    d1 = datetime.strptime(r[0], '%Y-%m-%d')
    d2 = datetime.strptime(fecha[:10], '%Y-%m-%d')
    return (d2 - d1).days, r[1]


def main():
    con = sqlite3.connect(DB)
    payload = json.load(open(INPUT, encoding='utf-8'))
    todos = []
    for picks in payload['temps'].values():
        todos.extend(picks)
    print(f"Total X-rescue picks: {len(todos)}")

    cnt_local_match = 0; cnt_visita_match = 0
    locales_no_match = Counter()
    visitas_no_match = Counter()
    distrib_gap_local = []
    distrib_gap_visita = []
    con_copa_local = 0; con_copa_visita = 0
    cnt_local_con_copa_72h = 0; cnt_visita_con_copa_72h = 0
    cnt_local_con_copa_96h = 0; cnt_visita_con_copa_96h = 0

    for p in todos:
        ll = p['local']; vv = p['visita']; fc = p['fecha']
        gl, last_l = gap_dias(con, ll, fc)
        gv, last_v = gap_dias(con, vv, fc)
        if gl is not None:
            cnt_local_match += 1; distrib_gap_local.append(gl)
        else:
            locales_no_match[(p['liga'], ll)] += 1
        if gv is not None:
            cnt_visita_match += 1; distrib_gap_visita.append(gv)
        else:
            visitas_no_match[(p['liga'], vv)] += 1
        # copa-specific gap
        gl_copa, comp_l = ultimo_no_liga(con, ll, fc, max_window=14)
        gv_copa, comp_v = ultimo_no_liga(con, vv, fc, max_window=14)
        if gl_copa is not None:
            con_copa_local += 1
            if gl_copa <= 3: cnt_local_con_copa_72h += 1
            if gl_copa <= 4: cnt_local_con_copa_96h += 1
        if gv_copa is not None:
            con_copa_visita += 1
            if gv_copa <= 3: cnt_visita_con_copa_72h += 1
            if gv_copa <= 4: cnt_visita_con_copa_96h + 1

    print()
    print("=" * 80)
    print("COBERTURA gap_dias en v_partidos_unificado")
    print("=" * 80)
    print(f"  Local matched:  {cnt_local_match}/{len(todos)} ({100*cnt_local_match/len(todos):.1f}%)")
    print(f"  Visita matched: {cnt_visita_match}/{len(todos)} ({100*cnt_visita_match/len(todos):.1f}%)")

    print()
    print("=" * 80)
    print("DISTRIB gap_dias (cualquier partido previo, todos los picks matched)")
    print("=" * 80)
    if distrib_gap_local:
        import statistics as st
        print(f"  Local:  mean={st.mean(distrib_gap_local):.1f} median={st.median(distrib_gap_local):.0f} "
              f"p25={sorted(distrib_gap_local)[len(distrib_gap_local)//4]} "
              f"p75={sorted(distrib_gap_local)[3*len(distrib_gap_local)//4]}")
    if distrib_gap_visita:
        import statistics as st
        print(f"  Visita: mean={st.mean(distrib_gap_visita):.1f} median={st.median(distrib_gap_visita):.0f} "
              f"p25={sorted(distrib_gap_visita)[len(distrib_gap_visita)//4]} "
              f"p75={sorted(distrib_gap_visita)[3*len(distrib_gap_visita)//4]}")

    print()
    print("=" * 80)
    print("CANSANCIO MID-WEEK: copa <14d previa")
    print("=" * 80)
    print(f"  Local con copa <=14d:    {con_copa_local}/{len(todos)} ({100*con_copa_local/len(todos):.1f}%)")
    print(f"  Visita con copa <=14d:   {con_copa_visita}/{len(todos)} ({100*con_copa_visita/len(todos):.1f}%)")
    print(f"  Local con copa <=72h:    {cnt_local_con_copa_72h}/{len(todos)} ({100*cnt_local_con_copa_72h/len(todos):.1f}%)")
    print(f"  Local con copa <=96h:    {cnt_local_con_copa_96h}/{len(todos)} ({100*cnt_local_con_copa_96h/len(todos):.1f}%)")
    print(f"  Visita con copa <=72h:   {cnt_visita_con_copa_72h}/{len(todos)} ({100*cnt_visita_con_copa_72h/len(todos):.1f}%)")

    print()
    print("=" * 80)
    print("MISMATCHES TOP (locales sin gap, ranqueados por # picks)")
    print("=" * 80)
    for (l, eq), n in locales_no_match.most_common(15):
        print(f"  {l:<14} {eq:<35} N={n}")

    print()
    print("MISMATCHES TOP (visitas sin gap):")
    for (l, eq), n in visitas_no_match.most_common(15):
        print(f"  {l:<14} {eq:<35} N={n}")

    out = {
        'fecha': '2026-04-28',
        'cobertura': {
            'local_matched': cnt_local_match,
            'visita_matched': cnt_visita_match,
            'total_picks': len(todos),
            'pct_local': round(100*cnt_local_match/len(todos), 2),
            'pct_visita': round(100*cnt_visita_match/len(todos), 2),
        },
        'cansancio_proxy': {
            'local_con_copa_14d': con_copa_local,
            'visita_con_copa_14d': con_copa_visita,
            'local_copa_72h': cnt_local_con_copa_72h,
            'local_copa_96h': cnt_local_con_copa_96h,
            'visita_copa_72h': cnt_visita_con_copa_72h,
        },
        'top_locales_no_match': [{'liga': l, 'eq': eq, 'n': n} for (l, eq), n in locales_no_match.most_common(20)],
        'top_visitas_no_match': [{'liga': l, 'eq': eq, 'n': n} for (l, eq), n in visitas_no_match.most_common(20)],
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

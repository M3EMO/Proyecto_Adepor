"""[exploratorio] Hit rate del motor V0 sobre partidos_no_liga (copas).

Pregunta: ¿el motor predice tan bien copas como liga? Si sí, copas son universo
apostable potencial. Si no, copas tienen dinamica diferente y requieren modelo aparte.

Metodologia:
  1. Filtrar partidos_no_liga con goles_l y goles_v reales (jugados)
     AND ambos equipos en historial_equipos_stats (→ tienen EMAs)
  2. Para cada partido: lookup ema_l_xg / ema_c_xg pre-partido (forward, sin look-ahead)
  3. Computar V0 (Dixon-Coles legacy con xG + rho liga del LOCAL)
  4. argmax prediccion vs outcome real
  5. Reportar: hit rate global, por competicion, por liga del local, por fase

Sin cuotas → no puedo dar yield. Solo hit rate + Brier.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "audit_partidos_copa_hit_rate.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def poisson(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except: return 0.0


def tau(i, j, l, v, rho):
    if i == 0 and j == 0: return 1 - l*v*rho
    if i == 0 and j == 1: return 1 + l*rho
    if i == 1 and j == 0: return 1 + v*rho
    if i == 1 and j == 1: return 1 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(10):
        for j in range(10):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def amax(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # rho_calculado por liga (Dixon-Coles)
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    # Subset apostable: partidos copa con goles + ambos equipos en historial_equipos_stats
    print("Cargando partidos copa con resultados + ambos en historial_equipos_stats...")
    rows = cur.execute("""
        SELECT pnl.fecha, pnl.competicion, pnl.competicion_tipo, pnl.pais_origen,
               pnl.equipo_local, pnl.equipo_visita, pnl.goles_l, pnl.goles_v
        FROM partidos_no_liga pnl
        WHERE pnl.goles_l IS NOT NULL AND pnl.goles_v IS NOT NULL
          AND pnl.equipo_local IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
          AND pnl.equipo_visita IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
        ORDER BY pnl.fecha
    """).fetchall()
    print(f"  N partidos copa apostables: {len(rows):,}")
    print()

    # Hit rate por liga del LOCAL (porque rho lo determina la liga del local)
    # Necesito saber liga del equipo local para usar rho correcto.
    # Lookup desde historial_equipos_stats (un equipo puede aparecer en varias ligas — usar la mas frecuente)
    print("Buscando liga predominante por equipo...")
    eq_liga = {}
    for r in cur.execute("""
        SELECT equipo, liga, COUNT(*) FROM historial_equipos_stats
        GROUP BY equipo, liga
        ORDER BY equipo, COUNT(*) DESC
    """).fetchall():
        eq, liga, n = r
        if eq not in eq_liga:
            eq_liga[eq] = liga
    print(f"  Equipos mapeados: {len(eq_liga):,}")
    print()

    # Predicciones V0 + outcomes
    print("Computando V0 prediction por partido (forward EMA - sin look-ahead)...")
    n_total = 0; n_pred = 0; n_hit = 0
    by_comp = defaultdict(lambda: [0, 0])  # [pred, hit]
    by_liga_local = defaultdict(lambda: [0, 0])
    by_fase = defaultdict(lambda: [0, 0])
    brier_vals = []
    for fecha, comp, comp_tipo, pais_or, ll, vv, gl, gv in rows:
        n_total += 1
        # Lookup ema_l xG forward (último snapshot < fecha)
        # Adepor calcula xG en motor con OLS legacy. Aprox: usar gf_per_match - gc_per_match
        # de últimas N=5 jornadas. Como proxy, uso ema_l_sots, ema_l_shots, ema_l_corners.
        # Para mantener este script simple: usar PROXY de xG = gf_per_partido_recent.
        # (equivalente a calc_xg_legacy con stats EMA; pero requiere calc completo.)
        # Aprox simplificada: xG = avg goles que el equipo HACE / CONCEDE en ultimo bin.
        liga_local = eq_liga.get(ll)
        if not liga_local:
            continue

        # Pull last EMA pre-fecha
        eml = cur.execute("""
            SELECT ema_l_sots, ema_l_shots, ema_l_corners, ema_l_shot_pct
            FROM historial_equipos_stats
            WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
            ORDER BY fecha DESC LIMIT 1
        """, (liga_local, ll, fecha)).fetchone()
        emv = cur.execute("""
            SELECT ema_l_sots, ema_l_shots, ema_l_corners, ema_l_shot_pct
            FROM historial_equipos_stats
            WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
            ORDER BY fecha DESC LIMIT 1
        """, (eq_liga.get(vv) or liga_local, vv, fecha)).fetchone()
        if not eml or not emv:
            continue

        sot_l, shots_l, corners_l, shot_pct_l = eml
        sot_v, shots_v, corners_v, shot_pct_v = emv
        # xG legacy: 0.30*sots + 0.04*(shots-sots) + 0.03*corners
        xg_l = 0.30*sot_l + 0.04*max(0,(shots_l or 0)-(sot_l or 0)) + 0.03*(corners_l or 0)
        xg_v = 0.30*sot_v + 0.04*max(0,(shots_v or 0)-(sot_v or 0)) + 0.03*(corners_v or 0)
        xg_l = max(0.10, xg_l); xg_v = max(0.10, xg_v)
        rho = rho_pl.get(liga_local, -0.04)
        p1, px, p2 = probs_dc(xg_l, xg_v, rho)
        pred = amax(p1, px, p2)
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        n_pred += 1
        won = (pred == real)
        if won: n_hit += 1
        by_comp[comp][0] += 1; by_comp[comp][1] += int(won)
        by_liga_local[liga_local][0] += 1; by_liga_local[liga_local][1] += int(won)
        # Brier multinomial
        target = (1 if real=="1" else 0, 1 if real=="X" else 0, 1 if real=="2" else 0)
        brier = (p1-target[0])**2 + (px-target[1])**2 + (p2-target[2])**2
        brier_vals.append(brier)

    print()
    print(f"=" * 80)
    print(f"RESUMEN GLOBAL")
    print(f"=" * 80)
    print(f"  Partidos copa con resultado: {n_total:,}")
    print(f"  Predichos (ambos equipos con EMA suficiente): {n_pred:,}")
    print(f"  Hit rate V0: {n_hit:,}/{n_pred:,} ({100*n_hit/n_pred:.2f}%)")
    print(f"  Brier promedio: {sum(brier_vals)/len(brier_vals):.4f}" if brier_vals else "")

    print()
    print(f"=" * 80)
    print(f"POR COMPETICION (N>=20)")
    print(f"=" * 80)
    for comp, (n, h) in sorted(by_comp.items(), key=lambda x: -x[1][0]):
        if n < 20: continue
        print(f"  {comp:<25} N={n:>4} hit={h}/{n} ({100*h/n:.1f}%)")

    print()
    print(f"=" * 80)
    print(f"POR LIGA DEL LOCAL (N>=20)")
    print(f"=" * 80)
    for liga, (n, h) in sorted(by_liga_local.items(), key=lambda x: -x[1][0]):
        if n < 20: continue
        print(f"  {liga:<14} N={n:>4} hit={h}/{n} ({100*h/n:.1f}%)")

    # Comparativa: hit rate liga normal (de partidos_historico_externo)
    print()
    print(f"=" * 80)
    print(f"REFERENCIA: hit rate V0 sobre partidos_historico_externo (liga, OOS)")
    print(f"=" * 80)
    rows_liga = cur.execute("""
        SELECT phe.liga, phe.fecha, phe.ht, phe.at, phe.hg, phe.ag,
               phe.hst, phe.hs, phe.hc, phe.ast, phe.as_, phe.ac
        FROM partidos_historico_externo phe
        WHERE phe.has_full_stats=1 AND phe.temp IN (2022, 2023, 2024)
          AND phe.hg IS NOT NULL AND phe.ag IS NOT NULL
        LIMIT 5000
    """).fetchall()
    n_liga_pred = 0; n_liga_hit = 0
    for liga, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in rows_liga:
        if not (hst and hs and hc and ast and as_ and ac): continue
        xg_l = 0.30*hst + 0.04*max(0,(hs or 0)-(hst or 0)) + 0.03*(hc or 0)
        xg_v = 0.30*ast + 0.04*max(0,(as_ or 0)-(ast or 0)) + 0.03*(ac or 0)
        xg_l = max(0.10, xg_l); xg_v = max(0.10, xg_v)
        rho = rho_pl.get(liga, -0.04)
        p1, px, p2 = probs_dc(xg_l, xg_v, rho)
        pred = amax(p1, px, p2)
        real = "1" if hg > ag else ("2" if hg < ag else "X")
        n_liga_pred += 1
        if pred == real: n_liga_hit += 1
    print(f"  Liga (sample N=5000): hit={n_liga_hit}/{n_liga_pred} ({100*n_liga_hit/n_liga_pred:.2f}%)")
    print(f"  Copa (todos):         hit={n_hit}/{n_pred} ({100*n_hit/n_pred:.2f}%)")

    out = {
        'fecha': '2026-04-28',
        'n_copa_total': n_total,
        'n_copa_predichos': n_pred,
        'hit_rate_copa': round(100*n_hit/n_pred, 2) if n_pred else None,
        'brier_copa': round(sum(brier_vals)/len(brier_vals), 4) if brier_vals else None,
        'hit_rate_liga_referencia': round(100*n_liga_hit/n_liga_pred, 2) if n_liga_pred else None,
        'por_competicion': {c: {'n': n, 'hit': h, 'pct': round(100*h/n, 2)} for c, (n,h) in by_comp.items() if n >= 20},
        'por_liga_local': {l: {'n': n, 'hit': h, 'pct': round(100*h/n, 2)} for l, (n,h) in by_liga_local.items() if n >= 20},
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

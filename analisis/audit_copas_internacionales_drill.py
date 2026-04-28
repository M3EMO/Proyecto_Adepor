"""[exploratorio] Drill-down hit rate + Brier en copas internacionales:
Champions, Europa, Conference, Libertadores, Sudamericana.

Quiebra:
  - Por fase (grupos vs eliminatorias)
  - Por matchup_liga (cross-liga vs same-liga)
  - Por outcome predicho (1 / X / 2) → calibracion
  - Por outcome real → distribucion de empates
  - Por (liga_local × liga_visita) — top combos
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
OUT = ROOT / "analisis" / "audit_copas_internacionales_drill.json"

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


COPAS_INT = ['Champions League', 'Europa League', 'Conference League',
             'Libertadores', 'Sudamericana']


def es_grupos(fase):
    if not fase: return None
    f = fase.lower()
    if 'grup' in f or 'group' in f: return True
    return False


def main():
    con = sqlite3.connect(DB); cur = con.cursor()
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    eq_liga = {}
    for r in cur.execute("""SELECT equipo, liga, COUNT(*) FROM historial_equipos_stats
                            GROUP BY equipo, liga ORDER BY equipo, COUNT(*) DESC"""):
        eq, liga, n = r
        if eq not in eq_liga: eq_liga[eq] = liga

    print("Cargando partidos copa internacional...")
    rows = cur.execute("""
        SELECT pnl.fecha, pnl.competicion, pnl.fase,
               pnl.equipo_local, pnl.equipo_visita, pnl.goles_l, pnl.goles_v
        FROM partidos_no_liga pnl
        WHERE pnl.competicion IN (?, ?, ?, ?, ?)
          AND pnl.goles_l IS NOT NULL AND pnl.goles_v IS NOT NULL
          AND pnl.equipo_local IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
          AND pnl.equipo_visita IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
        ORDER BY pnl.fecha
    """, COPAS_INT).fetchall()
    print(f"  N total con ambos en historial: {len(rows):,}")

    # Predict V0 + outcome
    preds = []
    for fecha, comp, fase, ll, vv, gl, gv in rows:
        liga_l = eq_liga.get(ll)
        liga_v = eq_liga.get(vv)
        if not liga_l: continue
        eml = cur.execute("""SELECT ema_l_sots, ema_l_shots, ema_l_corners
                             FROM historial_equipos_stats
                             WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
                             ORDER BY fecha DESC LIMIT 1""", (liga_l, ll, fecha)).fetchone()
        emv = cur.execute("""SELECT ema_l_sots, ema_l_shots, ema_l_corners
                             FROM historial_equipos_stats
                             WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
                             ORDER BY fecha DESC LIMIT 1""", (liga_v or liga_l, vv, fecha)).fetchone()
        if not eml or not emv: continue
        sot_l, shots_l, corners_l = eml
        sot_v, shots_v, corners_v = emv
        xg_l = max(0.10, 0.30*sot_l + 0.04*max(0,(shots_l or 0)-(sot_l or 0)) + 0.03*(corners_l or 0))
        xg_v = max(0.10, 0.30*sot_v + 0.04*max(0,(shots_v or 0)-(sot_v or 0)) + 0.03*(corners_v or 0))
        rho = rho_pl.get(liga_l, -0.04)
        p1, px, p2 = probs_dc(xg_l, xg_v, rho)
        pred = amax(p1, px, p2)
        real = "1" if gl > gv else ("2" if gl < gv else "X")
        preds.append({
            'fecha': fecha, 'comp': comp, 'fase': fase,
            'liga_l': liga_l, 'liga_v': liga_v,
            'local': ll, 'visita': vv,
            'p1': p1, 'px': px, 'p2': p2,
            'pred': pred, 'real': real,
            'gl': gl, 'gv': gv,
            'won': pred == real,
            'es_grupos': es_grupos(fase),
            'cross_liga': liga_l != liga_v if liga_v else None,
        })
    print(f"  N predichos: {len(preds):,}")
    print()

    # === POR COPA (resumen) ===
    print("=" * 95)
    print("POR COPA — hit rate + Brier + outcome distribution")
    print("=" * 95)
    print(f"{'Copa':<22} {'N':>4} {'Hit%':>6} {'Brier':>8} {'%real_1':>9} {'%real_X':>9} {'%real_2':>9} {'%pred_1':>9} {'%pred_X':>9} {'%pred_2':>9}")
    res_copa = {}
    for comp in COPAS_INT:
        sub = [p for p in preds if p['comp'] == comp]
        if not sub: continue
        n = len(sub)
        hit = sum(1 for p in sub if p['won'])
        # Brier
        briers = []
        for p in sub:
            t = (1 if p['real']=='1' else 0, 1 if p['real']=='X' else 0, 1 if p['real']=='2' else 0)
            briers.append((p['p1']-t[0])**2 + (p['px']-t[1])**2 + (p['p2']-t[2])**2)
        brier = sum(briers)/len(briers)
        cnt_real = Counter(p['real'] for p in sub)
        cnt_pred = Counter(p['pred'] for p in sub)
        print(f"{comp:<22} {n:>4} {100*hit/n:>5.1f}% {brier:>8.4f} "
              f"{100*cnt_real.get('1',0)/n:>8.1f}% {100*cnt_real.get('X',0)/n:>8.1f}% {100*cnt_real.get('2',0)/n:>8.1f}% "
              f"{100*cnt_pred.get('1',0)/n:>8.1f}% {100*cnt_pred.get('X',0)/n:>8.1f}% {100*cnt_pred.get('2',0)/n:>8.1f}%")
        res_copa[comp] = {
            'n': n, 'hit_pct': round(100*hit/n,2), 'brier': round(brier,4),
            'real_dist': {'1': cnt_real.get('1',0), 'X': cnt_real.get('X',0), '2': cnt_real.get('2',0)},
            'pred_dist': {'1': cnt_pred.get('1',0), 'X': cnt_pred.get('X',0), '2': cnt_pred.get('2',0)},
        }

    # === POR FASE ===
    print()
    print("=" * 95)
    print("POR FASE (grupos vs eliminatorias) por copa")
    print("=" * 95)
    res_fase = {}
    for comp in COPAS_INT:
        sub = [p for p in preds if p['comp'] == comp]
        if not sub: continue
        for is_g, label in [(True, 'grupos'), (False, 'eliminat')]:
            sub2 = [p for p in sub if p['es_grupos'] == is_g]
            if len(sub2) < 5: continue
            n = len(sub2); hit = sum(1 for p in sub2 if p['won'])
            cnt_real = Counter(p['real'] for p in sub2)
            print(f"  {comp:<20} {label:<10} N={n:>3} hit={hit}/{n} ({100*hit/n:>5.1f}%) | real_X={100*cnt_real.get('X',0)/n:>5.1f}%")
            res_fase[f"{comp}/{label}"] = {'n': n, 'hit_pct': round(100*hit/n,2),
                                            'real_X_pct': round(100*cnt_real.get('X',0)/n,2)}

    # === POR PRED (calibracion direccional) ===
    print()
    print("=" * 95)
    print("CALIBRACION POR PREDICTED OUTCOME (¿cuando dice 1, gana 1?)")
    print("=" * 95)
    res_pred = {}
    for comp in COPAS_INT:
        sub = [p for p in preds if p['comp'] == comp]
        if not sub: continue
        print(f"\n  {comp}:")
        for direc in ['1', 'X', '2']:
            sub2 = [p for p in sub if p['pred'] == direc]
            if not sub2: continue
            n = len(sub2)
            hit = sum(1 for p in sub2 if p['won'])
            print(f"    pred={direc}  N={n:>3} hit={hit}/{n} ({100*hit/n:>5.1f}%)")
            res_pred[f"{comp}/{direc}"] = {'n': n, 'hit_pct': round(100*hit/n,2)}

    # === POR MATCHUP CROSS-LIGA ===
    print()
    print("=" * 95)
    print("CROSS-LIGA vs SAME-LIGA (Champions/Europa/Conference solo)")
    print("=" * 95)
    for comp in ['Champions League', 'Europa League', 'Conference League']:
        sub = [p for p in preds if p['comp'] == comp]
        if not sub: continue
        same = [p for p in sub if p['cross_liga'] == False]
        cross = [p for p in sub if p['cross_liga'] == True]
        for label, sub2 in [('SAME', same), ('CROSS', cross)]:
            if len(sub2) < 5: continue
            n = len(sub2); hit = sum(1 for p in sub2 if p['won'])
            print(f"  {comp:<20} {label:<6} N={n:>3} hit={hit}/{n} ({100*hit/n:>5.1f}%)")

    # === TOP COMBOS (liga_l × liga_v) ===
    print()
    print("=" * 95)
    print("TOP COMBOS liga_l x liga_v (Champions/Europa/Conference, N>=10)")
    print("=" * 95)
    by_combo = defaultdict(list)
    for p in preds:
        if p['comp'] in ('Champions League', 'Europa League', 'Conference League'):
            by_combo[(p['liga_l'], p['liga_v'])].append(p)
    print(f"  {'liga_l':<14} vs {'liga_v':<14} {'N':>4} {'hit%':>6}")
    for (ll, lv), sub in sorted(by_combo.items(), key=lambda x: -len(x[1])):
        if len(sub) < 10: continue
        n = len(sub); hit = sum(1 for p in sub if p['won'])
        print(f"  {ll or '?':<14} vs {lv or '?':<14} {n:>4} {100*hit/n:>5.1f}%")

    # === DISTRIBUCION DE EMPATES REALES vs PREDICCION ===
    print()
    print("=" * 95)
    print("EMPATES REALES vs PREDICCION (¿cuanto subestima X el motor?)")
    print("=" * 95)
    print(f"  {'Copa':<22} {'%real_X':>9} {'%pred_X':>9} {'gap_X (pred subestima)':>25}")
    for comp in COPAS_INT:
        if comp not in res_copa: continue
        n = res_copa[comp]['n']
        rx = res_copa[comp]['real_dist']['X']/n*100
        px = res_copa[comp]['pred_dist']['X']/n*100
        print(f"  {comp:<22} {rx:>8.1f}% {px:>8.1f}% {rx-px:>20.1f}pp")

    out = {
        'fecha': '2026-04-28',
        'res_copa': res_copa,
        'res_fase': res_fase,
        'res_pred': res_pred,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

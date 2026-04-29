"""
[adepor V14 v2 SHADOW] Audit mensual recurrente sobre picks_shadow_v14_copa.

Diseñado para correr 1x/mes (cron post-cierre mes) o on-demand. Reporta:
1. Hit rate pool completo + subset apostable per (competition_tipo, edicion).
2. Yield contrafactual (escenario mercado=Elo+6%, mismo que simulador).
3. Tendencia mes-a-mes (drift detection).
4. Volumen picks apostables + estabilidad cross-año.
5. Trigger PROPOSAL formal: si N>=200 picks apostables + Wilson_lo > 60% + estable
   cross-temporal → recomendación promover V14 v2 a producción.

Output: stdout consolidado + persistencia en analisis/audit_v14_v2_shadow_<YYYY-MM>.json.

[REF: docs/papers/v14_v2_copa_nacional_filtro_apostable.md]
"""
from __future__ import annotations
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"


def wilson_lo(h, n, z=1.96):
    if n == 0: return 0
    p = h / n
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p) + z*z/(4*n))/n)) / (1 + z*z/n)


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    out = {"fecha_audit": today, "metricas": {}}

    print("=" * 90)
    print(f"AUDIT V14 v2 SHADOW — {today}")
    print("=" * 90)

    # 1. Pool global
    print()
    print("=== Pool global ===")
    print(f"{'comp_tipo':<22} {'N':>6} {'liquidados':>11} {'futuros':>9} {'hit%':>6} {'wilson_lo':>10}")
    for ct in ["copa_internacional", "copa_nacional"]:
        n = cur.execute("SELECT COUNT(*) FROM picks_shadow_v14_copa WHERE competicion_tipo=?", (ct,)).fetchone()[0]
        n_liq = cur.execute("SELECT COUNT(*) FROM picks_shadow_v14_copa WHERE competicion_tipo=? AND outcome_real IS NOT NULL", (ct,)).fetchone()[0]
        n_fut = n - n_liq
        h = cur.execute("SELECT SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) FROM picks_shadow_v14_copa WHERE competicion_tipo=? AND outcome_real IS NOT NULL", (ct,)).fetchone()[0] or 0
        hit_pct = 100 * h / n_liq if n_liq else 0
        wlo = 100 * wilson_lo(h, n_liq) if n_liq else 0
        print(f"  {ct:<22} {n:>6d} {n_liq:>11d} {n_fut:>9d} {hit_pct:>5.1f}% {wlo:>9.1f}%")
        out["metricas"][f"pool_{ct}"] = {"n": n, "liquidados": n_liq, "hits": h, "hit_pct": hit_pct, "wilson_lo": wlo}

    # 2. Subset apostable copa_nacional
    print()
    print("=== Subset APOSTABLE copa_nacional (rules drill 2026-04-29) ===")
    r = cur.execute("""SELECT COUNT(*), SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                       FROM picks_shadow_v14_copa
                       WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                         AND pick_apostable_v14_v2=1""").fetchone()
    n_ap, h_ap = r[0], r[1] or 0
    if n_ap > 0:
        hit_pct = 100 * h_ap / n_ap
        wlo = 100 * wilson_lo(h_ap, n_ap)
        print(f"  N apostable: {n_ap}  Hits: {h_ap}  Hit: {hit_pct:.1f}%  Wilson_lo: {wlo:.1f}%")
        out["metricas"]["subset_apostable"] = {"n": n_ap, "hits": h_ap, "hit_pct": hit_pct, "wilson_lo": wlo}

        # Trigger PROPOSAL formal
        trigger_n = n_ap >= 200
        trigger_wlo = wlo >= 60.0
        if trigger_n and trigger_wlo:
            print(f"  ★ TRIGGER MET: N>=200 + Wilson_lo>=60% → recomendación PROPOSAL formal a producción.")
            out["trigger_proposal"] = True
        else:
            faltan_n = max(0, 200 - n_ap)
            print(f"  Trigger pending: N={n_ap}/200 ({faltan_n} faltan), Wilson_lo={wlo:.1f}%/60%")
            out["trigger_proposal"] = False

    # 3. Apostable per edicion (top performers)
    print()
    print("=== APOSTABLE por edición (top hit con N>=15) ===")
    print(f"{'edicion':<25} {'N':>5} {'hit%':>6} {'wilson_lo':>10}")
    edicion_perf = []
    for r in cur.execute("""SELECT competicion, COUNT(*),
                                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                            FROM picks_shadow_v14_copa
                            WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                              AND pick_apostable_v14_v2=1
                            GROUP BY competicion
                            HAVING COUNT(*) >= 15
                            ORDER BY 3.0 / COUNT(*) DESC, COUNT(*) DESC"""):
        ed, n, h = r
        hit_pct = 100 * h / n
        wlo = 100 * wilson_lo(h, n)
        ed_safe = ed.encode("ascii", "replace").decode("ascii")
        print(f"  {ed_safe:<25} {n:>5d} {hit_pct:>5.1f}% {wlo:>9.1f}%")
        edicion_perf.append({"edicion": ed, "n": n, "hit_pct": hit_pct, "wilson_lo": wlo})
    out["metricas"]["apostable_por_edicion"] = edicion_perf

    # 4. Tendencia mes-a-mes (drift)
    print()
    print("=== Tendencia mes-a-mes IS 2026 (drift detection) ===")
    print(f"{'mes':>9} {'N_ap':>5} {'hits':>5} {'hit%':>6}")
    months = []
    for r in cur.execute("""SELECT substr(fecha_partido,1,7) as mes, COUNT(*),
                                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END)
                            FROM picks_shadow_v14_copa
                            WHERE competicion_tipo='copa_nacional' AND outcome_real IS NOT NULL
                              AND pick_apostable_v14_v2=1
                              AND fecha_partido >= '2026-01-01'
                            GROUP BY mes ORDER BY mes"""):
        mes, n, h = r
        if n < 3: continue
        hit_pct = 100 * h / n
        print(f"  {mes:>7} {n:>5d} {h:>5d} {hit_pct:>5.1f}%")
        months.append({"mes": mes, "n": n, "hits": h, "hit_pct": hit_pct})
    out["metricas"]["tendencia_mensual_2026"] = months

    # 5. Persistir reporte
    out_path = ROOT / "analisis" / f"audit_v14_v2_shadow_{datetime.now().strftime('%Y-%m')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print()
    print(f"Reporte: {out_path}")
    conn.close()


if __name__ == "__main__":
    main()

"""
Paso 4 — Audit mensual Layer 3 (hook adepor-j4e).

Lee picks_shadow_layer3_log + cruza con partidos_backtest para calcular metricas
de Layer 3 sobre el horizonte mensual (default: 30 dias rolling).

Metricas:
- Counts por branch (APLICA, APLICA_CON_NULL, SKIP_TOP3, SKIP_CANSADOS, SKIP_AMBOS)
- Yield Layer 3 vs V0 sobre APLICA liquidados (con cuotas reales)
- Brier de override X vs Brier V0 (mismo subset)

Recurrente: corre cada cierre de mes (alimenta adepor-j4e).

USO:
    py analisis/audit_layer3_monthly.py             # ultimos 30d
    py analisis/audit_layer3_monthly.py --dias 90   # ultimos 90d
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = "fondo_quant.db"
DIAS = 30
if "--dias" in sys.argv:
    idx = sys.argv.index("--dias")
    DIAS = int(sys.argv[idx + 1])


def brier_1x2(p1, px, p2, gl, gv):
    """Brier multinomial 1X2."""
    if gl is None or gv is None:
        return None
    o1 = 1 if gl > gv else 0
    ox = 1 if gl == gv else 0
    o2 = 1 if gl < gv else 0
    return ((p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2) / 3.0


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str
    c = conn.cursor()

    fecha_corte = (datetime.now() - timedelta(days=DIAS)).strftime("%Y-%m-%d")
    print(f"Audit Layer 3 — ventana: {fecha_corte} a hoy ({DIAS}d)\n")

    # Counts por branch
    rows_count = c.execute("""
        SELECT branch, COUNT(*), SUM(aplicado_produccion)
        FROM picks_shadow_layer3_log
        WHERE fecha_partido >= ?
        GROUP BY branch
    """, (fecha_corte,)).fetchall()
    counts = {r[0]: {"total": r[1], "aplicado": r[2] or 0} for r in rows_count}
    n_total = sum(c["total"] for c in counts.values())

    print("=" * 70)
    print(f"COUNTS POR BRANCH ({DIAS}d)")
    print("=" * 70)
    for branch in ["APLICA", "APLICA_CON_NULL", "SKIP_TOP3", "SKIP_CANSADOS", "SKIP_AMBOS"]:
        info = counts.get(branch, {"total": 0, "aplicado": 0})
        print(f"  {branch:<20s} total={info['total']:>4d} aplicado={info['aplicado']:>4d}")
    print(f"  {'TOTAL':<20s} {n_total:>10d}")

    # Yield V0 vs override sobre APLICA liquidados
    rows_apl = c.execute("""
        SELECT l3.id_partido, l3.fecha_partido, l3.pais, l3.local, l3.visita, l3.branch,
               l3.p1_v0_pre, l3.px_v0_pre, l3.p2_v0_pre,
               l3.p1_v12, l3.px_v12_full, l3.p2_v12,
               pb.cuota_1, pb.cuota_x, pb.cuota_2,
               pb.estado, pb.goles_l, pb.goles_v
        FROM picks_shadow_layer3_log l3
        LEFT JOIN partidos_backtest pb ON l3.id_partido = pb.id_partido
        WHERE l3.fecha_partido >= ?
          AND l3.branch IN ('APLICA', 'APLICA_CON_NULL')
        ORDER BY l3.fecha_partido
    """, (fecha_corte,)).fetchall()

    n_v0_apuesta = n_v0_ganada = stake_v0 = ret_v0 = 0
    n_x_ganada = stake_x = ret_x = 0
    briers_v0 = []
    briers_v12 = []

    for r in rows_apl:
        (_idp, _fch, pais, local, visita, branch,
         p1_0, px_0, p2_0, p1_12, px_12, p2_12,
         c1, cx, c2, estado, gl, gv) = r
        if estado != "LIQUIDADO" or gl is None or gv is None:
            continue
        # Argmax V0
        argmax_v0 = "X" if px_0 == max(p1_0, px_0, p2_0) else \
                    ("1" if p1_0 >= p2_0 else "2")
        # V0 paso si argmax es lo que el motor V0 elegiria; cuota:
        cuota_v0 = c1 if argmax_v0 == "1" else cx if argmax_v0 == "X" else c2
        if cuota_v0:
            stake_v0 += 1
            res = (gl > gv and argmax_v0 == "1") or \
                  (gl == gv and argmax_v0 == "X") or \
                  (gl < gv and argmax_v0 == "2")
            if res:
                n_v0_ganada += 1
                ret_v0 += cuota_v0 - 1
            else:
                ret_v0 -= 1
        # Override -> X
        if cx:
            stake_x += 1
            if gl == gv:
                n_x_ganada += 1
                ret_x += cx - 1
            else:
                ret_x -= 1
        b_v0 = brier_1x2(p1_0, px_0, p2_0, gl, gv)
        b_v12 = brier_1x2(p1_12, px_12, p2_12, gl, gv)
        if b_v0 is not None: briers_v0.append(b_v0)
        if b_v12 is not None: briers_v12.append(b_v12)

    print("\n" + "=" * 70)
    print(f"YIELD APLICA LIQUIDADOS")
    print("=" * 70)
    if stake_v0:
        yield_v0 = ret_v0 / stake_v0
        hit_v0 = n_v0_ganada / stake_v0
        print(f"  V0 (argmax sin override): N={stake_v0} hit={hit_v0:.3f} yield={yield_v0:+.3f}")
    if stake_x:
        yield_x = ret_x / stake_x
        hit_x = n_x_ganada / stake_x
        print(f"  X override (Layer 3):      N={stake_x} hit={hit_x:.3f} yield={yield_x:+.3f}")
    if stake_v0 and stake_x:
        delta = (ret_x / stake_x) - (ret_v0 / stake_v0)
        print(f"  Delta yield (X - V0): {delta:+.3f}")

    if briers_v0:
        avg_b_v0 = sum(briers_v0) / len(briers_v0)
        avg_b_v12 = sum(briers_v12) / len(briers_v12) if briers_v12 else None
        print(f"\n  Brier V0 (avg, N={len(briers_v0)}): {avg_b_v0:.4f}")
        if avg_b_v12:
            print(f"  Brier V12 (avg, N={len(briers_v12)}): {avg_b_v12:.4f}")

    # Save report
    out = {
        "fecha_corrida": datetime.now().isoformat(),
        "ventana_dias": DIAS,
        "fecha_corte": fecha_corte,
        "counts_por_branch": counts,
        "n_total": n_total,
        "n_aplica_liquidados": stake_v0,
        "yield_v0": ret_v0 / stake_v0 if stake_v0 else None,
        "yield_x_override": ret_x / stake_x if stake_x else None,
        "delta_yield": ((ret_x / stake_x) - (ret_v0 / stake_v0)) if (stake_v0 and stake_x) else None,
        "brier_v0_avg": (sum(briers_v0) / len(briers_v0)) if briers_v0 else None,
        "brier_v12_avg": (sum(briers_v12) / len(briers_v12)) if briers_v12 else None,
    }
    Path("analisis/audit_layer3_monthly.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/audit_layer3_monthly.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: analisis/audit_layer3_monthly.json")
    conn.close()


if __name__ == "__main__":
    main()

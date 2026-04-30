"""
[adepor v14 v3] Análisis exhaustivo OOS/IS por (año × país × edición × bin4/bin8/bin12).

bin4/bin8/bin12 = posición dentro de la temporada (Q1-Q4 / 8 octavos / 12 doceavos).
Calculado on-the-fly desde liga_calendario_temp (fecha_inicio, fecha_fin).

Output:
- Bias xG/goles por bin temporal per (liga, edición)
- Detección shifts intra-temporada
- Identificación buckets de mayor/menor productividad

Sources:
- cuotas_historicas_fdco (8 ligas EU + ARG/BRA, 2022-2026, cuotas + stats EU)
- partidos_historico_externo (LATAM stats 2022-2024)
- stats_partidos_no_liga (copas internacionales/nacionales 2022-2026 stats ESPN)
- liga_calendario_temp (fecha_inicio/fin per liga × temp)
"""
from __future__ import annotations
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"


def calcular_bin(fecha_str, fecha_inicio, fecha_fin, n_bins):
    """Calcula bin (1..n_bins) según posición fracción dentro de la temporada."""
    try:
        f = datetime.strptime(fecha_str[:10], "%Y-%m-%d")
        ini = datetime.strptime(fecha_inicio[:10], "%Y-%m-%d")
        fin = datetime.strptime(fecha_fin[:10], "%Y-%m-%d")
        if f < ini: return 1
        if f > fin: return n_bins
        delta_total = (fin - ini).days
        if delta_total <= 0: return 1
        delta_partido = (f - ini).days
        bin_idx = int(delta_partido / delta_total * n_bins) + 1
        return max(1, min(n_bins, bin_idx))
    except Exception:
        return None


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # Cargar calendario temporadas
    cal = {}
    for r in cur.execute("SELECT liga, temp, fecha_inicio, fecha_fin, formato FROM liga_calendario_temp"):
        cal[(r[0], r[1])] = (r[2], r[3], r[4])

    print("=" * 100)
    print("ANALISIS BINS TEMPORALES (bin4 / bin8 / bin12) — Liga + Copa")
    print("=" * 100)

    # 1. LIGAS EU + LATAM via cuotas_historicas_fdco (con cuotas reales)
    print()
    print("=== LIGAS EU + LATAM (cuotas_historicas_fdco) ===")
    print()
    print("--- bin4 (Q1-Q4 temporada) ---")
    print(f"{'liga':<13} {'temp':>5} {'bin':>3} {'N':>5} {'goals':>7} {'g/sot':>7}")
    bins4_data = {}
    for liga in ["Inglaterra","Italia","Espana","Francia","Alemania","Turquia","Holanda","Argentina","Brasil"]:
        # Adepor: usa convención temp = año fin (EU) o año torneo (LATAM)
        # cuotas_historicas_fdco usa misma convención
        bins4_data[liga] = {}
        for temp in [2022, 2023, 2024, 2025, 2026]:
            cal_key = (liga, temp)
            if cal_key not in cal: continue
            ini, fin, _ = cal[cal_key]
            rows = cur.execute("""
                SELECT fecha, goles_l, goles_v, sot_l, sot_v
                FROM cuotas_historicas_fdco
                WHERE liga=? AND temp=? AND goles_l IS NOT NULL
            """, (liga, temp)).fetchall()
            if not rows: continue
            bins_temp = {1: [], 2: [], 3: [], 4: []}
            for r in rows:
                b = calcular_bin(r[0], ini, fin, 4)
                if b: bins_temp[b].append((r[1]+r[2], (r[3] or 0)+(r[4] or 0)))
            for b in [1,2,3,4]:
                if len(bins_temp[b]) >= 30:
                    g_avg = sum(x[0] for x in bins_temp[b])/len(bins_temp[b])
                    sot_avg = sum(x[1] for x in bins_temp[b])/len(bins_temp[b])
                    g_sot = g_avg/sot_avg if sot_avg>0 else 0
                    bins4_data[liga].setdefault(temp, {})[b] = {"n": len(bins_temp[b]), "g": g_avg, "sot": sot_avg}
                    if temp == 2026:  # solo IS
                        print(f"  {liga:<11} {temp:>5} {b:>3} {len(bins_temp[b]):>5d} {g_avg:>7.3f} {g_sot:>7.4f}")

    # 2. Bias bin4 OOS pooled vs IS 2026 per liga
    print()
    print("--- Bias goals_total bin4 (OOS pooled 22-25 vs IS 2026) ---")
    print(f"{'liga':<13} {'bin':>3} {'N_OOS':>6} {'g_OOS':>7} {'N_IS':>5} {'g_IS':>7} {'bias':>7} {'flag':>6}")
    bias_bin4 = {}
    for liga in bins4_data:
        for b in [1,2,3,4]:
            oos_data = []
            is_data = []
            for temp, bins_t in bins4_data[liga].items():
                if b in bins_t:
                    if temp <= 2025: oos_data.append(bins_t[b])
                    elif temp == 2026: is_data.append(bins_t[b])
            if not oos_data or not is_data: continue
            n_oos = sum(d["n"] for d in oos_data)
            n_is = sum(d["n"] for d in is_data)
            if n_oos < 50 or n_is < 30: continue
            g_oos = sum(d["g"] * d["n"] for d in oos_data) / n_oos
            g_is = sum(d["g"] * d["n"] for d in is_data) / n_is
            bias = g_is/g_oos if g_oos>0 else 1.0
            flag = "+" if bias>=1.10 else ("-" if bias<=0.90 else "")
            print(f"  {liga:<11} {b:>3} {n_oos:>6d} {g_oos:>7.3f} {n_is:>5d} {g_is:>7.3f} {bias:>+6.4f} {flag:>4}")
            bias_bin4.setdefault(liga, {})[b] = {
                "g_oos": round(g_oos,3), "n_oos": n_oos,
                "g_is": round(g_is,3), "n_is": n_is, "bias": round(bias,4),
            }

    # 3. COPA INTERNACIONAL bins (sin liga_calendario_temp directo)
    # Para copas, calculo bin con febrero=Q1, abril=Q2, julio=Q3 (LATAM) o meses específicos
    # Aproximación: bin4 = mes calendario / 3 (1 jan-mar, 2 abr-jun, 3 jul-sep, 4 oct-dic)
    print()
    print("=== COPA INTERNACIONAL (bin4 = trimestre calendario) ===")
    print(f"{'edicion':<22} {'period':>8} {'bin':>3} {'N':>4} {'g':>7} {'sot':>6}")
    for ed in ["Champions League","Europa League","Conference League","Libertadores","Sudamericana"]:
        for label, where in [("OOS","substr(fecha,1,4) IN ('2022','2023','2024','2025')"),
                             ("IS","substr(fecha,1,4)='2026'")]:
            for b, mes_min, mes_max in [(1,1,3),(2,4,6),(3,7,9),(4,10,12)]:
                r = cur.execute(f"""
                    SELECT COUNT(*),
                           AVG(CAST(goles_l+goles_v AS REAL)),
                           AVG(sot_l+sot_v)
                    FROM stats_partidos_no_liga
                    WHERE competicion=? AND {where}
                      AND CAST(substr(fecha,6,2) AS INTEGER) BETWEEN ? AND ?
                      AND sot_l IS NOT NULL
                """, (ed, mes_min, mes_max)).fetchone()
                if r[0] >= 20:
                    print(f"  {ed:<20s} {label:>8s} {b:>3} {r[0]:>4d} {r[1]:>7.3f} {r[2]:>6.2f}")

    # Persistir bias bin4 ligas
    out_path = ROOT / "analisis" / "v14_v3_bins_temporales.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"bias_bin4_ligas_oos_vs_is": bias_bin4}, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: {out_path}")

    # Persistir en config_motor_valores
    payload = {
        "name": "v14_v3_bias_bin4_ligas_oos_vs_is",
        "created": "2026-04-29",
        "method": "bin4 = cuarto temporada (liga_calendario_temp). Bias = g_IS/g_OOS",
        "bins": bias_bin4,
    }
    cur.execute("""INSERT OR REPLACE INTO config_motor_valores
                    (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
                    VALUES (?, ?, NULL, ?, ?, ?, 0, datetime('now'))""",
                ("v14_v3_bias_bin4_ligas", "global", json.dumps(payload), "json", "analisis_2026-04-29"))
    conn.commit()
    print("Persistido en config_motor_valores.v14_v3_bias_bin4_ligas")
    conn.close()


if __name__ == "__main__":
    main()

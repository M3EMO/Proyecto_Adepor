"""
[adepor] Comparativa apples-to-apples: IS 2026 vs años previos en MISMO rango
calendario. Evita comparar fin-de-temporada con inicio.

Metodología:
- IS 2026 EU: 2025-08-15 a 2026-04-29 (parte temp europea 25-26)
- OOS 2025 EU comparable: 2024-08-15 a 2025-04-29
- OOS 2024 EU comparable: 2023-08-15 a 2024-04-29
- OOS 2023 EU comparable: 2022-08-15 a 2023-04-29
- OOS 2022 EU comparable: 2021-08-15 a 2022-04-29

- IS 2026 LATAM: 2026-01-22 a 2026-04-29
- OOS LATAM comparable: <year>-01-22 a <year>-04-29

- COPAS: igual lógica por edición.

Fuentes:
- LIGAS EU: cuotas_historicas_fdco (5 temps comparables)
- LIGAS LATAM: cuotas_historicas_fdco (14 temps ARG, 15 temps BRA)
- COPAS: partidos_no_liga
"""
from __future__ import annotations
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# Ventanas comparables apples-to-apples
VENTANA_EU = ("08-15", "04-29")    # ago-15 a abr-29 cross-year
VENTANA_LATAM = ("01-22", "04-29") # ene-22 a abr-29 mismo year
VENTANA_COPA_DEFAULT = ("01-15", "04-29")


def welch_p(x_mean, x_var, x_n, y_mean, y_var, y_n):
    if x_n < 2 or y_n < 2: return None
    se = math.sqrt(x_var/x_n + y_var/y_n)
    if se == 0: return None
    z = abs((x_mean - y_mean) / se)
    return 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # ---- LIGAS EU (calendario ago-may) ----
    print("=" * 100)
    print("LIGAS EU — comparativa MISMO rango calendario (ago-15 a abr-29)")
    print("=" * 100)
    eu_ligas = ["Alemania","Espana","Francia","Inglaterra","Italia","Turquia","Holanda"]

    for liga in eu_ligas:
        print(f"\n--- {liga} ---")
        print(f"{'temp':>4} {'rango_fechas':<26} {'N':>5} {'g_l':>5} {'g_v':>5} {'g_t':>5} "
              f"{'sot_l':>6} {'sot_v':>6} {'shots_l':>8} {'shots_v':>8} {'corn_l':>7}")
        rows_per_temp = {}
        for temp_end in [2022, 2023, 2024, 2025, 2026]:
            yr_start = temp_end - 1
            f_min = f"{yr_start}-{VENTANA_EU[0]}"
            f_max = f"{temp_end}-{VENTANA_EU[1]}"
            r = cur.execute("""
                SELECT COUNT(*),
                       AVG(CAST(goles_l AS REAL)), AVG(CAST(goles_v AS REAL)),
                       AVG(CAST(goles_l + goles_v AS REAL)),
                       AVG(sot_l), AVG(sot_v), AVG(shots_l), AVG(shots_v),
                       AVG(corners_l)
                FROM cuotas_historicas_fdco
                WHERE liga=? AND fecha BETWEEN ? AND ?
                  AND sot_l IS NOT NULL
            """, (liga, f_min, f_max)).fetchone()
            n = r[0]
            if n < 30: continue
            rng = f"{f_min[5:]} a {f_max[5:]}"
            print(f"{temp_end:>4} {rng:<26} {n:>5d} {r[1]:>5.2f} {r[2]:>5.2f} {r[3]:>5.2f} "
                  f"{r[4]:>6.2f} {r[5]:>6.2f} {r[6]:>8.2f} {r[7]:>8.2f} {r[8]:>7.2f}")
            rows_per_temp[temp_end] = r

        # Comparativa IS 2026 vs cada OOS año
        if 2026 in rows_per_temp:
            print(f"\n  Comparativa IS 2026 vs OOS:")
            r_is = rows_per_temp[2026]
            for temp_oos in [2022, 2023, 2024, 2025]:
                if temp_oos not in rows_per_temp: continue
                r_oos = rows_per_temp[temp_oos]
                bias_g = r_is[3] / r_oos[3]
                bias_sot = (r_is[4]+r_is[5]) / (r_oos[4]+r_oos[5])
                p = welch_p(r_is[3], r_is[3], r_is[0], r_oos[3], r_oos[3], r_oos[0])
                sig = ""
                if p:
                    if p<0.05: sig="*"
                    if p<0.01: sig="**"
                    if p<0.001: sig="***"
                p_str = f"p={p:.4f}" if p else "p=?"
                print(f"    vs {temp_oos}: bias_g={bias_g:+.4f} bias_sot={bias_sot:+.4f} {p_str} {sig}")

    # ---- LIGAS LATAM (calendario anual ene-dic) ----
    print("\n" + "=" * 100)
    print("LIGAS LATAM — comparativa MISMO rango calendario (ene-22 a abr-29)")
    print("=" * 100)
    latam_ligas = ["Argentina", "Brasil"]

    for liga in latam_ligas:
        print(f"\n--- {liga} ---")
        print(f"{'temp':>4} {'rango_fechas':<26} {'N':>5} {'g_l':>5} {'g_v':>5} {'g_t':>5}")
        rows_per_temp = {}
        for temp in [2022, 2023, 2024, 2025, 2026]:
            f_min = f"{temp}-{VENTANA_LATAM[0]}"
            f_max = f"{temp}-{VENTANA_LATAM[1]}"
            r = cur.execute("""
                SELECT COUNT(*),
                       AVG(CAST(goles_l AS REAL)), AVG(CAST(goles_v AS REAL)),
                       AVG(CAST(goles_l + goles_v AS REAL))
                FROM cuotas_historicas_fdco
                WHERE liga=? AND fecha BETWEEN ? AND ?
            """, (liga, f_min, f_max)).fetchone()
            n = r[0]
            if n < 30: continue
            rng = f"{f_min[5:]} a {f_max[5:]}"
            print(f"{temp:>4} {rng:<26} {n:>5d} {r[1]:>5.2f} {r[2]:>5.2f} {r[3]:>5.2f}")
            rows_per_temp[temp] = r
        if 2026 in rows_per_temp:
            print(f"\n  Comparativa IS 2026 vs OOS (mismo rango ene-abr):")
            r_is = rows_per_temp[2026]
            for temp_oos in [2022, 2023, 2024, 2025]:
                if temp_oos not in rows_per_temp: continue
                r_oos = rows_per_temp[temp_oos]
                bias_g = r_is[3] / r_oos[3]
                p = welch_p(r_is[3], r_is[3], r_is[0], r_oos[3], r_oos[3], r_oos[0])
                sig = ""
                if p:
                    if p<0.05: sig="*"
                    if p<0.01: sig="**"
                    if p<0.001: sig="***"
                p_str = f"p={p:.4f}" if p else "p=?"
                print(f"    vs {temp_oos}: bias_g={bias_g:+.4f} {p_str} {sig}")

    # ---- COPAS por edición ----
    print("\n" + "=" * 100)
    print("COPAS — comparativa MISMO rango calendario por edición")
    print("=" * 100)
    # Obtener rangos IS 2026 por edición
    ediciones = cur.execute("""
        SELECT competicion, MIN(fecha), MAX(fecha)
        FROM partidos_no_liga
        WHERE fecha >= '2026-01-01' AND goles_l IS NOT NULL
        GROUP BY competicion
        HAVING COUNT(*) >= 20
        ORDER BY COUNT(*) DESC
    """).fetchall()

    for ed, f_is_min, f_is_max in ediciones:
        # Extraer mes-día del rango IS
        mes_min = f_is_min[5:10]
        mes_max = f_is_max[5:10]
        safe_ed = ed.encode('ascii','replace').decode('ascii')
        print(f"\n--- {safe_ed} (rango {mes_min} a {mes_max}) ---")
        print(f"{'year':>5} {'N':>5} {'g_t_avg':>9} {'bias_vs_2026':>14}")

        rows_per_year = {}
        for yr in [2022, 2023, 2024, 2025, 2026]:
            f_min = f"{yr}-{mes_min}"
            f_max = f"{yr}-{mes_max}"
            r = cur.execute("""
                SELECT COUNT(*), AVG(CAST(goles_l + goles_v AS REAL))
                FROM partidos_no_liga
                WHERE competicion=? AND goles_l IS NOT NULL
                  AND fecha BETWEEN ? AND ?
            """, (ed, f_min, f_max)).fetchone()
            n, g_t = r
            if n < 5: continue
            rows_per_year[yr] = (n, g_t)
        if 2026 not in rows_per_year: continue
        n_is, g_is = rows_per_year[2026]
        for yr in [2022, 2023, 2024, 2025, 2026]:
            if yr not in rows_per_year: continue
            n, g_t = rows_per_year[yr]
            bias = g_t / g_is if g_is > 0 else 0
            tag = " (IS)" if yr == 2026 else ""
            print(f"{yr:>5}{tag:<5} {n:>5d} {g_t:>9.3f} {bias:>+13.4f}")
        # Welch test pooled OOS vs IS
        oos_pooled_n = sum(rows_per_year[y][0] for y in [2022,2023,2024,2025] if y in rows_per_year)
        if oos_pooled_n > 0:
            oos_pooled_g = sum(rows_per_year[y][0]*rows_per_year[y][1]
                               for y in [2022,2023,2024,2025] if y in rows_per_year) / oos_pooled_n
            bias_pool = g_is / oos_pooled_g if oos_pooled_g > 0 else 0
            p = welch_p(g_is, g_is, n_is, oos_pooled_g, oos_pooled_g, oos_pooled_n)
            sig = ""
            if p:
                if p<0.05: sig="*"
                if p<0.01: sig="**"
                if p<0.001: sig="***"
            p_str = f"p={p:.4f}" if p else "p=?"
            print(f"  IS vs OOS_pooled (mismo rango): bias={bias_pool:+.4f} {p_str} {sig}")

    print(f"\nReporte: analisis/xg_shift_apples_to_apples.json")
    conn.close()


if __name__ == "__main__":
    main()

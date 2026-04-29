"""
[adepor] Análisis bias xG/goles por mes calendario (marzo con marzo, etc.)
en LIGAS y COPAS. Detecta patrones estacionales y shifts.

Cruce con formato calendario por liga (apertura/clausura/anual europeo).

Convención: IS=2026, OOS=2022-2025.
"""
from __future__ import annotations
import json
import math
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # --- LIGAS ---
    print("=" * 100)
    print("LIGAS — Goals/partido por (liga, mes_calendario) cross-año")
    print("=" * 100)

    rows_l = cur.execute("""
        SELECT liga,
               CAST(substr(fecha,6,2) AS INTEGER) as mes,
               COUNT(*) as n,
               AVG(CAST(hg+ag AS REAL)) as g_t,
               AVG(CAST(hg AS REAL)) as g_l,
               AVG(CAST(ag AS REAL)) as g_v,
               SUM(CASE WHEN hg=ag THEN 1 ELSE 0 END)*1.0/COUNT(*) as draws
        FROM partidos_historico_externo
        WHERE hg IS NOT NULL AND ag IS NOT NULL
        GROUP BY liga, mes
        HAVING n >= 30
        ORDER BY liga, mes
    """).fetchall()

    # Por liga: mostrar matriz mes x stats + bias_mes vs media_liga
    by_liga_mes = defaultdict(dict)
    for r in rows_l:
        liga, mes, n, g_t, g_l, g_v, draws = r
        by_liga_mes[liga][mes] = {"n":n,"g_t":g_t,"g_l":g_l,"g_v":g_v,"draws":draws}

    print(f"\n{'liga':<13}", end='')
    for m in range(1,13): print(f" {m:>2d}-mes", end='')
    print(f" {'g_t_mean':>9} {'std%':>6}")
    print("-" * 130)
    bias_liga_mes = {}
    for liga in sorted(by_liga_mes.keys()):
        meses = by_liga_mes[liga]
        n_total = sum(d["n"] for d in meses.values())
        if n_total < 200: continue
        g_t_mean = sum(d["g_t"]*d["n"] for d in meses.values())/n_total
        # std% = stdev(g_t per mes) / mean
        vals = [d["g_t"] for d in meses.values()]
        if len(vals) >= 3:
            mean = sum(vals)/len(vals)
            variance = sum((v-mean)**2 for v in vals)/len(vals)
            std_pct = 100*math.sqrt(variance)/mean if mean>0 else 0
        else: std_pct = 0

        print(f"{liga:<13}", end='')
        for m in range(1,13):
            if m in meses:
                bias_m = meses[m]["g_t"] / g_t_mean
                marker = ""
                if bias_m >= 1.10: marker = "+"
                elif bias_m <= 0.90: marker = "-"
                print(f"{bias_m:5.2f}{marker:1s}", end='')
                bias_liga_mes[f"{liga}|{m:02d}"] = round(bias_m, 4)
            else:
                print(f"{'-':>6}", end='')
        print(f" {g_t_mean:>9.3f} {std_pct:>5.1f}%")

    # --- COPAS ---
    print("\n" + "=" * 100)
    print("COPAS — Goals/partido por (edición, mes_calendario) cross-año")
    print("=" * 100)

    rows_c = cur.execute("""
        SELECT competicion,
               CAST(substr(fecha,6,2) AS INTEGER) as mes,
               COUNT(*) as n,
               AVG(CAST(goles_l + goles_v AS REAL)) as g_t
        FROM partidos_no_liga
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
        GROUP BY competicion, mes
        HAVING n >= 20
        ORDER BY competicion, mes
    """).fetchall()
    by_copa_mes = defaultdict(dict)
    for r in rows_c:
        ed, mes, n, g_t = r
        by_copa_mes[ed][mes] = {"n":n, "g_t":g_t}

    print(f"\n{'edicion':<22}", end='')
    for m in range(1,13): print(f" {m:>2d}-mes", end='')
    print(f" {'g_t_mean':>9} {'std%':>6}")
    print("-" * 130)
    for ed in sorted(by_copa_mes.keys()):
        meses = by_copa_mes[ed]
        n_total = sum(d["n"] for d in meses.values())
        if n_total < 80: continue
        g_t_mean = sum(d["g_t"]*d["n"] for d in meses.values())/n_total
        vals = [d["g_t"] for d in meses.values()]
        if len(vals) >= 3:
            mean = sum(vals)/len(vals)
            variance = sum((v-mean)**2 for v in vals)/len(vals)
            std_pct = 100*math.sqrt(variance)/mean if mean>0 else 0
        else: std_pct = 0

        safe_ed = ed.encode('ascii','replace').decode('ascii')
        print(f"{safe_ed:<22}", end='')
        for m in range(1,13):
            if m in meses:
                bias_m = meses[m]["g_t"] / g_t_mean
                marker = "+" if bias_m >= 1.10 else ("-" if bias_m <= 0.90 else "")
                print(f"{bias_m:5.2f}{marker:1s}", end='')
            else:
                print(f"{'-':>6}", end='')
        print(f" {g_t_mean:>9.3f} {std_pct:>5.1f}%")

    # --- Cruce con formato calendario ---
    print("\n" + "=" * 100)
    print("FORMATO CALENDARIO POR LIGA (cruce con bias mensual)")
    print("=" * 100)
    cal_rows = cur.execute("""
        SELECT liga, temp, formato, fecha_inicio, fecha_fin, notas
        FROM liga_calendario_temp
        ORDER BY liga, temp
    """).fetchall()
    formatos_liga = defaultdict(list)
    for r in cal_rows:
        formatos_liga[r[0]].append(r[2])
    print(f"\n{'liga':<13} {'formatos':<60} {'cambio?':>10}")
    for liga, fs in sorted(formatos_liga.items()):
        unique = list(dict.fromkeys(fs))  # preserve order
        cambio = "SI" if len(unique) > 1 else "no"
        print(f"{liga:<13} {','.join(unique):<60} {cambio:>10}")

    # Identificar bias mensual extremo (pico y valle por liga)
    print("\n=== EXTREMOS MENSUALES POR LIGA ===")
    print(f"{'liga':<13} {'mes_pico':>10} {'bias_max':>10} {'mes_valle':>11} {'bias_min':>10} {'spread%':>9}")
    print("-" * 80)
    for liga in sorted(by_liga_mes.keys()):
        meses = by_liga_mes[liga]
        n_total = sum(d["n"] for d in meses.values())
        if n_total < 200: continue
        g_t_mean = sum(d["g_t"]*d["n"] for d in meses.values())/n_total
        bias_per_m = {m: d["g_t"]/g_t_mean for m,d in meses.items()}
        pico_m = max(bias_per_m, key=bias_per_m.get)
        valle_m = min(bias_per_m, key=bias_per_m.get)
        spread = (bias_per_m[pico_m] - bias_per_m[valle_m]) * 100
        print(f"{liga:<13} {pico_m:>10d} {bias_per_m[pico_m]:>10.3f} {valle_m:>11d} {bias_per_m[valle_m]:>10.3f} {spread:>8.1f}%")

    # Persistir
    out = ROOT / "analisis" / "xg_shift_per_mes_calendario.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "convencion": "IS=2026, OOS=2022-2025",
            "ligas_bias_mensual": {l: {str(m):d for m,d in meses.items()}
                                   for l, meses in by_liga_mes.items()},
            "copas_bias_mensual": {ed: {str(m):d for m,d in meses.items()}
                                   for ed, meses in by_copa_mes.items()},
            "formatos_calendario": dict(formatos_liga),
            "bias_liga_mes_dict": bias_liga_mes,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: {out}")
    conn.close()


if __name__ == "__main__":
    main()

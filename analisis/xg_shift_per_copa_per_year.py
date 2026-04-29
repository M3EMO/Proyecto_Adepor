"""
[adepor V14 + xG calibration] Análisis de shift de goals/xG observado por
(año, copa, pais_origen). Detecta cambios de régimen y propone bias factors
para ajustar el motor xG en copas.

Convención (decisión usuario 2026-04-29):
- IN-SAMPLE = 2026 (año en curso)
- OOS = 2022-2025 (años pasados)

Output:
- Tabla de goals/partido por celda
- Bias factor recomendado per copa
- Detección de shift estadístico (Welch t-test entre últimos 2 años vs primeros 2)
- Ajuste motor general + per-año-copa
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


def welch_ttest(x_mean, x_var, x_n, y_mean, y_var, y_n):
    """Welch t-test 2-sample (returns t, df_aprox, p_aprox via Normal CDF)."""
    if x_n < 2 or y_n < 2:
        return None
    se = math.sqrt(x_var / x_n + y_var / y_n)
    if se == 0:
        return None
    t = (x_mean - y_mean) / se
    # df aproximado Welch
    num = (x_var/x_n + y_var/y_n) ** 2
    den = (x_var/x_n)**2/(x_n-1) + (y_var/y_n)**2/(y_n-1)
    df = num / den if den > 0 else float("inf")
    # p-value 2-sided via Normal aprox (df grande)
    z = abs(t)
    p_aprox = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return t, df, p_aprox


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    print("=" * 100)
    print("ANÁLISIS xG/GOALS SHIFT POR COPA POR AÑO")
    print(f"Convención: IS = 2026 (año en curso); OOS = 2022-2025")
    print("=" * 100)

    # Goals stats por celda (año, COMPETICION ESPECÍFICA — Libertadores/UCL/FA Cup/etc.)
    rows = cur.execute("""
        SELECT substr(fecha,1,4) as anio,
               competicion,
               competicion_tipo,
               COUNT(*) as n,
               AVG(CAST(goles_l AS REAL)) as g_l,
               AVG(CAST(goles_v AS REAL)) as g_v,
               AVG(CAST(goles_l + goles_v AS REAL)) as g_t,
               SUM(CASE WHEN goles_l = goles_v THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as draws_pct
        FROM partidos_no_liga
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
        GROUP BY anio, competicion
        HAVING n >= 20
        ORDER BY competicion_tipo, competicion, anio
    """).fetchall()

    # Reorganizar por competicion (edición específica)
    cells = defaultdict(dict)  # {comp_edicion: {year: {n, g_l, g_v, g_t, ...}}}
    cell_meta = {}
    for r in rows:
        anio, comp_ed, ct, n, g_l, g_v, g_t, dp = r
        cells[comp_ed][anio] = {
            "n": n, "g_l": g_l, "g_v": g_v, "g_t": g_t, "draws_pct": dp,
        }
        cell_meta[comp_ed] = ct

    # Compute pooled stats + variance per cell
    print("\n=== Goals por partido (observados) — desagregado por EDICIÓN ESPECÍFICA (N>=20) ===")
    print(f"{'edicion':<25} {'tipo':>20} {'2022':>9} {'2023':>9} {'2024':>9} {'2025':>9} {'2026 IS':>9} {'d 26-22':>8}")
    print("-" * 130)
    summary_per_cell = {}
    # Order: copa_internacional first (sorted by N), then copa_nacional
    sorted_keys = sorted(cells.keys(),
                         key=lambda k: (cell_meta.get(k,'?'),
                                        -sum(y['n'] for y in cells[k].values())))
    for comp_ed in sorted_keys:
        years = cells[comp_ed]
        ct = cell_meta.get(comp_ed, '?')
        row = []
        first_g_t = None
        last_g_t = None
        for y in ["2022", "2023", "2024", "2025", "2026"]:
            if y in years:
                row.append(f"{years[y]['g_t']:>9.3f}")
                if first_g_t is None: first_g_t = years[y]["g_t"]
                last_g_t = years[y]["g_t"]
            else:
                row.append(f"{'-':>9}")
        delta = (last_g_t - first_g_t) if (first_g_t and last_g_t) else None
        delta_str = f"{delta:>+7.3f}" if delta is not None else "   -    "
        # Sanitize comp_ed for output
        safe_ed = comp_ed.encode('ascii','replace').decode('ascii')
        print(f"{safe_ed:<25} {ct:>20} {' '.join(row)} {delta_str}")
        summary_per_cell[comp_ed] = {
            "tipo": ct,
            "first_year_g_t": first_g_t, "last_year_g_t": last_g_t,
            "delta_abs": delta,
            "delta_pct": (delta / first_g_t * 100) if (delta and first_g_t) else None,
        }

    # Bias factor recomendado: compare últimos 2 años (2025+2026) vs Train (2022-2024) goals_total
    print("\n=== BIAS FACTOR RECOMENDADO POR EDICIÓN ===")
    print("bias = goals_total_recent (2025+2026) / goals_total_train (2022-2024)")
    print()
    print(f"{'edicion':<25} {'tipo':>20} {'g_train':>9} {'g_recent':>9} {'N_tr':>6} {'N_re':>6} {'bias':>8} {'p':>7} {'sig':>5}")
    print("-" * 130)
    bias_dict = {}
    for comp_ed in sorted_keys:
        years = cells[comp_ed]
        ct = cell_meta.get(comp_ed, '?')
        train_years = [y for y in ["2022","2023","2024"] if y in years]
        recent_years = [y for y in ["2025","2026"] if y in years]
        if not train_years or not recent_years: continue
        n_train = sum(years[y]["n"] for y in train_years)
        n_recent = sum(years[y]["n"] for y in recent_years)
        if n_train < 40 or n_recent < 20: continue
        g_train = sum(years[y]["g_t"] * years[y]["n"] for y in train_years) / n_train
        g_recent = sum(years[y]["g_t"] * years[y]["n"] for y in recent_years) / n_recent
        bias = g_recent / g_train if g_train > 0 else 1.0
        var_train = g_train
        var_recent = g_recent
        tt = welch_ttest(g_recent, var_recent, n_recent, g_train, var_train, n_train)
        sig = ""
        p = None
        if tt:
            t, df, p = tt
            if p < 0.05: sig = "*"
            if p < 0.01: sig = "**"
            if p < 0.001: sig = "***"
        bias_dict[comp_ed] = {
            "tipo": ct,
            "g_t_train": round(g_train, 3),
            "g_t_recent": round(g_recent, 3),
            "n_train": n_train, "n_recent": n_recent,
            "bias_factor": round(bias, 4),
            "p_value": round(p, 4) if p is not None else None,
            "significancia": sig,
        }
        safe_ed = comp_ed.encode('ascii','replace').decode('ascii')
        p_str = f"{p:.4f}" if p is not None else "  -  "
        print(f"{safe_ed:<25} {ct:>20} {g_train:>9.3f} {g_recent:>9.3f} {n_train:>6d} {n_recent:>6d} {bias:>+8.4f} {p_str:>7s} {sig:>5s}")

    # Recomendación final
    print("\n=== AJUSTE MOTOR PROPUESTO ===")
    print("\n1. AJUSTE GENERAL (todas las copas con bias significativo):")
    sig_cells = [(k, v) for k, v in bias_dict.items() if v["significancia"]]
    if sig_cells:
        for k, v in sig_cells:
            direction = "ALCISTA" if v["bias_factor"] > 1 else "BAJISTA"
            print(f"   {k:35s} bias={v['bias_factor']:.3f} ({direction}) {v['significancia']}")
    else:
        print("   (ninguna copa con shift significativo p<0.05)")

    print("\n2. AJUSTE POR-AÑO (sobreponer ajuste IS=2026 sobre OOS 2022-2025 pooling):")
    is_only = []
    for comp_ed in sorted_keys:
        years = cells[comp_ed]
        ct = cell_meta.get(comp_ed, '?')
        if "2026" not in years: continue
        oos = [years[y] for y in ["2022","2023","2024","2025"] if y in years]
        if not oos: continue
        n_oos_total = sum(t["n"] for t in oos)
        if n_oos_total < 60: continue
        g_t_oos = sum(t["g_t"] * t["n"] for t in oos) / n_oos_total
        g_t_2026 = years["2026"]["g_t"]
        n_2026 = years["2026"]["n"]
        if n_2026 < 20: continue
        bias_2026 = g_t_2026 / g_t_oos if g_t_oos > 0 else 1.0
        delta_pct = (bias_2026 - 1) * 100
        flag = ""
        if abs(delta_pct) >= 15: flag = "[**] SHIFT FUERTE"
        elif abs(delta_pct) >= 8: flag = "[*]  shift moderado"
        is_only.append((comp_ed, g_t_oos, g_t_2026, n_2026, bias_2026, flag))
        safe_ed = comp_ed.encode('ascii','replace').decode('ascii')
        print(f"   {safe_ed:<25} {ct:>20}  OOS={g_t_oos:.3f}  IS_2026={g_t_2026:.3f} (N={n_2026:>3d})  bias={bias_2026:.3f}  {flag}")

    out = ROOT / "analisis" / "xg_shift_per_copa_per_year.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "convencion": "IS=2026, OOS=2022-2025 (decision usuario 2026-04-29)",
            "summary_per_cell": summary_per_cell,
            "bias_dict_recent_vs_train": bias_dict,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: {out}")
    conn.close()


if __name__ == "__main__":
    main()

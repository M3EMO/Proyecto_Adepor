"""
[adepor xG calibration analysis] Análisis comprensivo de shift xG por (liga, año):

1. Aplica fórmula motor xG actual: xG = β_sot·sot + 0.010·shots_off + 0.03·corners
2. Compara xG_estimado vs goles_reales → bias xG/goles
3. Cross-stats individuales: sot, shots, corners, fouls, cards
4. Cruce con formato calendario (apertura/clausura/anual)
5. Detecta shifts vía Welch t-test
6. Propone bias factors para motor

Convención: IS = 2026 (año en curso); OOS = 2022-2025.

Source data: partidos_historico_externo (14,489 filas con stats crudas).
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

# Coeficientes motor xG actual (calibrar_xg.py)
BETA_SOT_DEFAULT = 0.352
BETA_SHOTS_OFF = 0.010
COEF_CORNER = 0.03


def welch_ttest(x_mean, x_var, x_n, y_mean, y_var, y_n):
    if x_n < 2 or y_n < 2:
        return None
    se = math.sqrt(x_var / x_n + y_var / y_n)
    if se == 0: return None
    t = (x_mean - y_mean) / se
    z = abs(t)
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return t, p


def cargar_beta_sot_per_liga(conn):
    """Cargar β_sot calibrado por liga. Fallback default si no existe."""
    out = defaultdict(lambda: BETA_SOT_DEFAULT)
    for r in conn.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot'"):
        if r[0] != 'global' and r[1] is not None:
            out[r[0]] = r[1]
    return out


def calcular_xg_partido(sot, shots, corners, beta_sot):
    """Aplica fórmula motor xG actual."""
    if sot is None or shots is None: return None
    sh_off = max(0, shots - sot)
    co = corners or 0
    return beta_sot * sot + BETA_SHOTS_OFF * sh_off + COEF_CORNER * co


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    beta_per_liga = cargar_beta_sot_per_liga(conn)
    print("=" * 100)
    print("ANÁLISIS xG SHIFT POR LIGA POR AÑO (sobre partidos_historico_externo)")
    print(f"β_sot calibrados per-liga: {dict(beta_per_liga)}")
    print(f"Fallback: β_sot={BETA_SOT_DEFAULT}, β_shots_off={BETA_SHOTS_OFF}, coef_corner={COEF_CORNER}")
    print("=" * 100)

    rows = cur.execute("""
        SELECT liga, temp, fecha,
               hst, hs, hc, hg,
               ast, as_, ac, ag,
               hf, af, hy, ay, hr, ar
        FROM partidos_historico_externo
        WHERE has_full_stats=1
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
    """).fetchall()

    # Calcular xG por partido y agrupar
    cells = defaultdict(lambda: {
        "n": 0,
        "xg_l": 0.0, "xg_v": 0.0, "xg_t": 0.0,
        "g_l": 0, "g_v": 0,
        "sot_l": 0.0, "sot_v": 0.0,
        "shots_l": 0.0, "shots_v": 0.0,
        "corn_l": 0.0, "corn_v": 0.0,
        "fouls_l": 0.0, "fouls_v": 0.0,
        "yellow_l": 0.0, "yellow_v": 0.0,
        "red_l": 0.0, "red_v": 0.0,
        "xg_t_sq_dev": 0.0,  # for variance
    })
    for r in rows:
        liga, temp, fecha, hst, hs, hc, hg, ast, as_, ac, ag, hf, af, hy, ay, hr, ar = r
        beta = beta_per_liga[liga]
        xg_l = calcular_xg_partido(hst, hs, hc, beta)
        xg_v = calcular_xg_partido(ast, as_, ac, beta)
        if xg_l is None or xg_v is None: continue
        key = (liga, temp)
        d = cells[key]
        d["n"] += 1
        d["xg_l"] += xg_l; d["xg_v"] += xg_v; d["xg_t"] += xg_l + xg_v
        d["g_l"] += hg; d["g_v"] += ag
        d["sot_l"] += hst; d["sot_v"] += ast
        d["shots_l"] += hs; d["shots_v"] += as_
        d["corn_l"] += hc or 0; d["corn_v"] += ac or 0
        d["fouls_l"] += hf or 0; d["fouls_v"] += af or 0
        d["yellow_l"] += hy or 0; d["yellow_v"] += ay or 0
        d["red_l"] += hr or 0; d["red_v"] += ar or 0

    # Promediar
    for k in cells:
        n = cells[k]["n"]
        if n == 0: continue
        for fld in ["xg_l","xg_v","xg_t","g_l","g_v","sot_l","sot_v","shots_l","shots_v",
                    "corn_l","corn_v","fouls_l","fouls_v","yellow_l","yellow_v","red_l","red_v"]:
            cells[k][fld] /= n
        cells[k]["bias_xg"] = (cells[k]["xg_t"] / (cells[k]["g_l"] + cells[k]["g_v"])) if (cells[k]["g_l"]+cells[k]["g_v"])>0 else None

    # Reorganizar por liga
    by_liga = defaultdict(dict)
    for (liga, temp), d in cells.items():
        by_liga[liga][temp] = d

    print("\n=== xG_estimado vs goles reales POR (liga, temp) ===")
    print(f"{'liga':<13} {'temp':>5} {'N':>4} {'xG_l':>5} {'xG_v':>5} {'xG_t':>5} {'g_l':>5} {'g_v':>5} {'g_t':>5} {'bias_xG/g':>10}")
    print("-" * 100)
    for liga in sorted(by_liga.keys()):
        for temp in sorted(by_liga[liga].keys()):
            d = by_liga[liga][temp]
            print(f"{liga:<13} {temp:>5} {d['n']:>4} {d['xg_l']:>5.2f} {d['xg_v']:>5.2f} {d['xg_t']:>5.2f} "
                  f"{d['g_l']:>5.2f} {d['g_v']:>5.2f} {d['g_l']+d['g_v']:>5.2f} {d.get('bias_xg') or 0:>9.3f}")

    # Detect shifts: train (2022-2024) vs recent (2025-2026)
    print("\n=== SHIFT TEST: recent (2025-2026) vs train (2022-2024) ===")
    print(f"{'liga':<13} {'g_train':>9} {'g_recent':>9} {'xG_train':>10} {'xG_recent':>11} {'N_tr':>6} {'N_re':>6} "
          f"{'bias_g':>8} {'bias_xG':>9} {'p':>8} {'sig':>5}")
    print("-" * 130)
    bias_dict = {}
    for liga in sorted(by_liga.keys()):
        train = [by_liga[liga][t] for t in [2022,2023,2024] if t in by_liga[liga]]
        recent = [by_liga[liga][t] for t in [2025,2026] if t in by_liga[liga]]
        if not train or not recent: continue
        n_tr = sum(d["n"] for d in train)
        n_re = sum(d["n"] for d in recent)
        if n_tr < 80 or n_re < 30: continue
        g_tr = sum((d["g_l"]+d["g_v"]) * d["n"] for d in train) / n_tr
        g_re = sum((d["g_l"]+d["g_v"]) * d["n"] for d in recent) / n_re
        xg_tr = sum(d["xg_t"] * d["n"] for d in train) / n_tr
        xg_re = sum(d["xg_t"] * d["n"] for d in recent) / n_re
        bias_g = g_re / g_tr
        bias_xg = xg_re / xg_tr
        # Welch t-test sobre goles_total
        var_tr = g_tr; var_re = g_re  # Poisson
        tt = welch_ttest(g_re, var_re, n_re, g_tr, var_tr, n_tr)
        sig = ""
        p = None
        if tt:
            t,p = tt
            if p < 0.05: sig="*"
            if p < 0.01: sig="**"
            if p < 0.001: sig="***"
        bias_dict[liga] = {
            "g_train": round(g_tr,3), "g_recent": round(g_re,3),
            "xg_train": round(xg_tr,3), "xg_recent": round(xg_re,3),
            "n_train": n_tr, "n_recent": n_re,
            "bias_goles": round(bias_g,4), "bias_xg": round(bias_xg,4),
            "p_value": round(p,4) if p is not None else None,
            "significancia": sig,
        }
        p_str = f"{p:.4f}" if p is not None else "  -  "
        print(f"{liga:<13} {g_tr:>9.3f} {g_re:>9.3f} {xg_tr:>10.3f} {xg_re:>11.3f} {n_tr:>6} {n_re:>6} "
              f"{bias_g:>+7.4f} {bias_xg:>+8.4f} {p_str:>8} {sig:>5}")

    # Stats individuales por (liga, temp): detección de shifts en sot, shots, fouls
    print("\n=== STATS INDIVIDUALES — % shift recent vs train ===")
    print(f"{'liga':<13} {'sot_l':>7} {'shots_l':>8} {'corn_l':>8} {'fouls_l':>9} {'yellow_l':>10} {'red_l':>7}")
    print("-" * 100)
    for liga in sorted(by_liga.keys()):
        train = [by_liga[liga][t] for t in [2022,2023,2024] if t in by_liga[liga]]
        recent = [by_liga[liga][t] for t in [2025,2026] if t in by_liga[liga]]
        if not train or not recent: continue
        n_tr = sum(d["n"] for d in train)
        n_re = sum(d["n"] for d in recent)
        if n_tr < 80 or n_re < 30: continue
        def avg_field(arr, fld, n):
            return sum(d[fld] * d["n"] for d in arr) / n
        delta_pct = {}
        for fld in ["sot_l","shots_l","corn_l","fouls_l","yellow_l","red_l"]:
            tr = avg_field(train, fld, n_tr)
            re_ = avg_field(recent, fld, n_re)
            delta_pct[fld] = (re_/tr - 1) * 100 if tr > 0 else 0
        print(f"{liga:<13} {delta_pct['sot_l']:>+6.1f}% {delta_pct['shots_l']:>+7.1f}% "
              f"{delta_pct['corn_l']:>+7.1f}% {delta_pct['fouls_l']:>+8.1f}% "
              f"{delta_pct['yellow_l']:>+9.1f}% {delta_pct['red_l']:>+6.1f}%")

    # Bias factors recomendados motor (xG-bias por liga)
    print("\n=== BIAS FACTORS PROPUESTOS (recent vs train, p<0.10) ===")
    print("Aplicar en motor: xG_predicho_ajustado = xG_predicho * bias_xg[liga]")
    sig_ligas = [(k,v) for k,v in bias_dict.items() if v.get("p_value") and v["p_value"] < 0.10]
    if sig_ligas:
        for k, v in sig_ligas:
            dir_ = "ALCISTA" if v["bias_goles"] > 1 else "BAJISTA"
            print(f"  {k:13s} bias={v['bias_goles']:.4f} ({dir_}) {v['significancia']:3s} p={v['p_value']:.4f}")
    else:
        print("  (ninguna liga con shift p<0.10)")

    # Convención IS=2026 (año en curso) vs OOS 2022-2025
    print("\n=== AJUSTE IS=2026 vs OOS 2022-2025 ===")
    print(f"{'liga':<13} {'OOS g_t':>9} {'IS g_t':>9} {'N_2026':>7} {'bias_2026':>10} {'flag':>20}")
    print("-" * 80)
    is_dict = {}
    for liga in sorted(by_liga.keys()):
        oos = [by_liga[liga][t] for t in [2022,2023,2024,2025] if t in by_liga[liga]]
        if 2026 not in by_liga[liga]: continue
        is_data = by_liga[liga][2026]
        if is_data["n"] < 25: continue
        n_oos = sum(d["n"] for d in oos)
        if n_oos < 50: continue
        g_oos = sum((d["g_l"]+d["g_v"]) * d["n"] for d in oos) / n_oos
        g_is = is_data["g_l"] + is_data["g_v"]
        bias_is = g_is / g_oos if g_oos > 0 else 1.0
        delta = (bias_is - 1) * 100
        flag = ""
        if abs(delta) >= 15: flag = "[**] SHIFT FUERTE"
        elif abs(delta) >= 8: flag = "[*]  shift moderado"
        is_dict[liga] = {"g_oos": round(g_oos,3), "g_is": round(g_is,3),
                          "n_2026": is_data["n"], "bias_2026": round(bias_is,4)}
        print(f"{liga:<13} {g_oos:>9.3f} {g_is:>9.3f} {is_data['n']:>7} {bias_is:>+10.4f} {flag:>20}")

    out = ROOT / "analisis" / "xg_shift_per_liga_per_year.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "convencion": "IS=2026, OOS=2022-2025",
            "params_motor_xg": {
                "beta_sot_default": BETA_SOT_DEFAULT,
                "beta_shots_off": BETA_SHOTS_OFF,
                "coef_corner": COEF_CORNER,
                "beta_per_liga": dict(beta_per_liga),
            },
            "by_liga_temp": {f"{l}|{t}": d for (l,t), d in cells.items()},
            "bias_recent_vs_train": bias_dict,
            "bias_is_2026_vs_oos": is_dict,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: {out}")
    conn.close()


if __name__ == "__main__":
    main()

"""
Audit ratio híbrido xG en motor_data.calcular_xg_hibrido.

Pregunta: ¿xg_final = 0.70·xg_calc + 0.30·goles_reales es empíricamente óptimo?

Método:
- Grid θ ∈ {0.0, 0.05, ..., 1.0}
- Para cada partido del equipo (local o visita):
    xg_calc = β_sot(liga) * SOT + 0.010 * shots_off + 0.03 * corners
    xg_p(θ) = θ * xg_calc + (1-θ) * goles_propios
- EMA forward-looking con α(liga) sobre xg_p(θ).
- Predicción partido t = EMA_{t-1} (estricto pasado).
- Solo predecir cuando n_partidos_previos >= 5 (warm-up).
- Métrica: RMSE, MAE, Poisson-NLL.
- Splits: por año (2022..2026) + IS agregado.

Output:
- Stdout: tabla θ × año con métrica óptima resaltada.
- JSON: analisis/audit_xg_hibrido_ratio_grid.json (todos los puntos).
"""
import sqlite3
import json
import math
from collections import defaultdict
from itertools import groupby
from pathlib import Path

DB = "fondo_quant.db"
WARMUP = 5
ALFA_DEFAULT = 0.15
BETA_DEFAULT = 0.352
BETA_SHOTS_OFF = 0.010
COEF_CORNER = 0.03

THETAS = [round(i * 0.05, 2) for i in range(21)]


def get_param(cur, clave, scope, default):
    r = cur.execute(
        "SELECT valor_real FROM config_motor_valores WHERE clave=? AND scope=?",
        (clave, scope),
    ).fetchone()
    if r and r[0] is not None:
        return r[0]
    return default


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    print("Cargando stats_partido_espn...")
    rows = cur.execute(
        """
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs  IS NOT NULL AND as_v IS NOT NULL
          AND hc  IS NOT NULL AND ac   IS NOT NULL
        ORDER BY ht, fecha
        """
    ).fetchall()
    print(f"  rows con stats completas: {len(rows)}")

    ligas = sorted({r[0] for r in rows})
    beta = {l: get_param(cur, "beta_sot", l, BETA_DEFAULT) for l in ligas}
    alfa = {l: get_param(cur, "alfa_ema", l, ALFA_DEFAULT) for l in ligas}

    eventos = []
    for liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac in rows:
        eventos.append((ht, fecha, liga, hst, hs, hc, hg))
        eventos.append((at, fecha, liga, ast, asv, ac, ag))
    eventos.sort(key=lambda x: (x[0], x[1]))

    print(f"  eventos equipo-partido: {len(eventos)}")
    print(f"  ligas: {len(ligas)}")
    print(f"  beta rango: {min(beta.values()):.3f} .. {max(beta.values()):.3f}")
    print(f"  alfa rango: {min(alfa.values()):.3f} .. {max(alfa.values()):.3f}")
    print()

    resultados = {t: defaultdict(list) for t in THETAS}

    for equipo, grupo in groupby(eventos, key=lambda x: x[0]):
        partidos = list(grupo)
        for theta in THETAS:
            ema = None
            n_prev = 0
            for _, fecha, liga, sot, shots, corn, goles in partidos:
                shots_off = max(0, shots - sot)
                xg_calc = beta[liga] * sot + BETA_SHOTS_OFF * shots_off + COEF_CORNER * corn
                xg_p = theta * xg_calc + (1.0 - theta) * goles
                if n_prev >= WARMUP and ema is not None:
                    anio = fecha[:4]
                    resultados[theta][anio].append((ema, goles, liga))
                a = alfa[liga]
                ema = xg_p if ema is None else a * xg_p + (1.0 - a) * ema
                n_prev += 1

    metricas = {}
    for theta in THETAS:
        metricas[theta] = {}
        all_pairs = []
        for anio, pairs in resultados[theta].items():
            n = len(pairs)
            if n == 0:
                continue
            ps = [p for p, _, _ in pairs]
            ys = [y for _, y, _ in pairs]
            rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n)
            mae = sum(abs(p - y) for p, y in zip(ps, ys)) / n
            nll = sum(max(p, 0.01) - y * math.log(max(p, 0.01)) for p, y in zip(ps, ys)) / n
            metricas[theta][anio] = {"n": n, "rmse": rmse, "mae": mae, "nll": nll}
            all_pairs.extend(pairs)
        n = len(all_pairs)
        if n > 0:
            ps = [p for p, _, _ in all_pairs]
            ys = [y for _, y, _ in all_pairs]
            rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n)
            mae = sum(abs(p - y) for p, y in zip(ps, ys)) / n
            nll = sum(max(p, 0.01) - y * math.log(max(p, 0.01)) for p, y in zip(ps, ys)) / n
            metricas[theta]["IS"] = {"n": n, "rmse": rmse, "mae": mae, "nll": nll}

    print("=" * 90)
    print("RESULTADOS - RMSE por anio (menor=mejor)")
    print("=" * 90)
    anios = sorted({a for t in THETAS for a in metricas[t].keys() if a != "IS"})
    header = f"{'theta':<8s}" + "".join(f"{a:>10s}" for a in anios) + f"{'IS':>10s}"
    print(header)
    for theta in THETAS:
        row = f"{theta:<8.2f}"
        for a in anios:
            v = metricas[theta].get(a, {}).get("rmse")
            row += f"{v:>10.4f}" if v is not None else f"{'-':>10s}"
        v = metricas[theta].get("IS", {}).get("rmse")
        row += f"{v:>10.4f}" if v is not None else f"{'-':>10s}"
        marker = "  <- motor actual" if theta == 0.70 else ""
        print(row + marker)

    print()
    print("=" * 90)
    print("THETA OPTIMO por metrica x split")
    print("=" * 90)
    for split in anios + ["IS"]:
        best = {"rmse": None, "mae": None, "nll": None}
        for met in ["rmse", "mae", "nll"]:
            cand = [(t, metricas[t].get(split, {}).get(met)) for t in THETAS]
            cand = [(t, v) for t, v in cand if v is not None]
            if cand:
                best[met] = min(cand, key=lambda x: x[1])
        actual_metrics = metricas.get(0.70, {}).get(split, {})
        print(f"\n{split} (N={actual_metrics.get('n', '-')}):")
        for met in ["rmse", "mae", "nll"]:
            t_opt, v_opt = best[met] if best[met] else (None, None)
            v_actual = actual_metrics.get(met)
            if v_opt is not None and v_actual is not None:
                delta = (v_actual - v_opt) / v_opt * 100
                print(f"  {met.upper():<5s}  theta_opt={t_opt:.2f}  v={v_opt:.4f}  |  motor 0.70 v={v_actual:.4f}  (gap +{delta:.2f}%)")

    out_path = Path("analisis/audit_xg_hibrido_ratio_grid.json")
    out_path.write_text(json.dumps(metricas, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON persistido: {out_path}")


if __name__ == "__main__":
    main()

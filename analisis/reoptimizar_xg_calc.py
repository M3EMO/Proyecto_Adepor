"""
Re-optimizacion de xg_calc.

Objetivo: encontrar formula xg_calc(stats) que sea mejor predictor que goles puros
en metrica forward-EMA. Si nueva xg_calc gana a goles puros, Opcion B (EMA xG real
extranjeros) se vuelve viable.

Variantes:
  V0  Motor actual (theta=0.70 hibrido)               [baseline]
  V0t Motor actual con theta=0.10 (tuned grid prev)   [baseline tuned]
  V1  Goles puros (theta=0)                           [baseline]
  V2  NNLS_3feat (SOT, shots_off, corners)            [veto-recomendado]
  V3  NNLS_5feat (V2 + possession, saves_rival)
  V4  NNLS_8feat (V3 + pass_pct, blocks_rival, longballs_acc)
  V5  Ridge_5feat (alpha=1.0)
  V6  NNLS_8feat + intercept (positivo)

Para cada variante OLS/NNLS:
  Train: 2022-2024 (in-sample fit).
  Test:  2025-2026 (out-of-sample).
  Tambien walk-forward por anio (2023..2026 train hasta anio-1).

Metricas finales:
  R2 intra-partido (sobre target = goles_intra).
  RMSE forward-EMA (sobre target = goles del proximo partido del equipo).
  Para cada variante, encontrar theta_hibrido optimo en grid {0.0, 0.1, ..., 1.0}.

Output:
  Tabla comparativa: variante x split x metrica.
  JSON: analisis/reoptimizar_xg_calc.json
"""
import sqlite3
import json
import math
import numpy as np
from collections import defaultdict
from itertools import groupby
from scipy.optimize import nnls
from sklearn.linear_model import Ridge
from pathlib import Path

DB = "fondo_quant.db"
WARMUP = 5
ALFA_DEFAULT = 0.15
THETAS = [round(i * 0.1, 2) for i in range(11)]


def get_alfa_map(cur):
    return {
        r[0]: r[1] for r in cur.execute(
            "SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND valor_real IS NOT NULL"
        ).fetchall()
    }


def get_beta_sot_map(cur):
    return {
        r[0]: r[1] for r in cur.execute(
            "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
        ).fetchall()
    }


def cargar_partidos(cur):
    """Devuelve filas con (liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac,
    h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves, h_blocks, a_blocks,
    h_longballs_acc, a_longballs_acc)."""
    rows = cur.execute(
        """
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
               h_blocks, a_blocks, h_longballs_acc, a_longballs_acc
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs  IS NOT NULL AND as_v IS NOT NULL
          AND hc  IS NOT NULL AND ac   IS NOT NULL
          AND h_pos IS NOT NULL AND a_pos IS NOT NULL
          AND h_pass_pct IS NOT NULL AND a_pass_pct IS NOT NULL
          AND h_saves IS NOT NULL AND a_saves IS NOT NULL
          AND h_blocks IS NOT NULL AND a_blocks IS NOT NULL
          AND h_longballs_acc IS NOT NULL AND a_longballs_acc IS NOT NULL
        ORDER BY fecha
        """
    ).fetchall()
    return rows


def construir_eventos(rows):
    """Convierte rows partido -> eventos equipo-perspectiva.
    Cada evento es feature vector + goles propios (target descriptor)."""
    eventos = []
    for r in rows:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac,
         h_pos, a_pos, h_pp, a_pp, h_sv, a_sv, h_bl, a_bl, h_lba, a_lba) = r
        # Local: features = stats propias + saves del rival (visita) + blocks rival (visita)
        eventos.append({
            "liga": liga, "fecha": fecha, "equipo": ht, "goles": hg,
            "sot": hst, "shots_off": max(0, hs - hst), "corners": hc,
            "pos": h_pos, "pass_pct": h_pp,
            "saves_rival": a_sv, "blocks_rival": a_bl,
            "longballs_acc": h_lba,
        })
        eventos.append({
            "liga": liga, "fecha": fecha, "equipo": at, "goles": ag,
            "sot": ast, "shots_off": max(0, asv - ast), "corners": ac,
            "pos": a_pos, "pass_pct": a_pp,
            "saves_rival": h_sv, "blocks_rival": h_bl,
            "longballs_acc": a_lba,
        })
    return eventos


def features_v(variant):
    """Devuelve lista de keys feature para cada variante."""
    if variant == "V2":
        return ["sot", "shots_off", "corners"]
    if variant == "V3":
        return ["sot", "shots_off", "corners", "pos", "saves_rival"]
    if variant == "V4":
        return ["sot", "shots_off", "corners", "pos", "saves_rival",
                "pass_pct", "blocks_rival", "longballs_acc"]
    if variant == "V5":
        return ["sot", "shots_off", "corners", "pos", "saves_rival"]
    if variant == "V6":
        return ["sot", "shots_off", "corners", "pos", "saves_rival",
                "pass_pct", "blocks_rival", "longballs_acc"]
    return None


def fit_variante(variante, eventos_train):
    """Devuelve dict con coefs ajustados sobre eventos_train."""
    feats = features_v(variante)
    if not feats:
        return None
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    if variante in ("V2", "V3", "V4"):
        coef, _ = nnls(X, y)
        intercept = 0.0
    elif variante == "V6":
        # NNLS con intercepto: agrego columna de 1s al frente
        X_aug = np.column_stack([np.ones(len(X)), X])
        coef_aug, _ = nnls(X_aug, y)
        intercept = coef_aug[0]
        coef = coef_aug[1:]
    elif variante == "V5":
        m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
        coef = m.coef_
        intercept = float(m.intercept_)
    return {"feats": feats, "coef": coef.tolist(), "intercept": float(intercept)}


def aplicar_variante(variante, ev, fit_cache, beta_sot_map, beta_default=0.352):
    """Devuelve xg_calc del evento segun variante."""
    if variante == "V0_baseline":
        beta = beta_sot_map.get(ev["liga"], beta_default)
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + 0.03 * ev["corners"]
        return 0.70 * xg_calc + 0.30 * ev["goles"]
    if variante == "V0t_tuned_010":
        beta = beta_sot_map.get(ev["liga"], beta_default)
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + 0.03 * ev["corners"]
        return 0.10 * xg_calc + 0.90 * ev["goles"]
    if variante == "V1_goles":
        return ev["goles"]
    f = fit_cache[variante]
    feats = f["feats"]
    return f["intercept"] + sum(f["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def medir_forward_rmse(variante, eventos, fit_cache, beta_sot_map, alfa_map, theta=None):
    """Mide RMSE de prediccion forward via EMA por equipo.

    Si theta dado, mezcla xg_p = theta*xg_calc + (1-theta)*goles.
    Si theta=None, xg_p = xg_calc directo (sin mezcla).
    Devuelve dict {anio: (n, rmse, nll, mae)} y agregado IS.
    """
    eventos_eq = sorted(eventos, key=lambda x: (x["equipo"], x["fecha"]))
    resultados = defaultdict(list)
    for equipo, grupo in groupby(eventos_eq, key=lambda x: x["equipo"]):
        partidos = list(grupo)
        ema = None
        n_prev = 0
        for ev in partidos:
            xg_calc = aplicar_variante(variante, ev, fit_cache, beta_sot_map)
            if theta is None:
                xg_p = xg_calc
            else:
                xg_p = theta * xg_calc + (1.0 - theta) * ev["goles"]
            if n_prev >= WARMUP and ema is not None:
                anio = ev["fecha"][:4]
                resultados[anio].append((ema, ev["goles"]))
            a = alfa_map.get(ev["liga"], ALFA_DEFAULT)
            ema = xg_p if ema is None else a * xg_p + (1.0 - a) * ema
            n_prev += 1

    out = {}
    all_pairs = []
    for anio, pairs in resultados.items():
        n = len(pairs)
        if n == 0: continue
        ps = [p for p, _ in pairs]; ys = [y for _, y in pairs]
        rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n)
        mae = sum(abs(p - y) for p, y in zip(ps, ys)) / n
        nll = sum(max(p, 0.01) - y * math.log(max(p, 0.01)) for p, y in zip(ps, ys)) / n
        out[anio] = {"n": n, "rmse": rmse, "mae": mae, "nll": nll}
        all_pairs.extend(pairs)
    n = len(all_pairs)
    if n > 0:
        ps = [p for p, _ in all_pairs]; ys = [y for _, y in all_pairs]
        rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n)
        mae = sum(abs(p - y) for p, y in zip(ps, ys)) / n
        nll = sum(max(p, 0.01) - y * math.log(max(p, 0.01)) for p, y in zip(ps, ys)) / n
        out["IS"] = {"n": n, "rmse": rmse, "mae": mae, "nll": nll}
    return out


def medir_intra_r2(variante, eventos, fit_cache, beta_sot_map):
    """R2 + RMSE intra-partido sobre goles_real."""
    if variante in ("V0_baseline", "V0t_tuned_010", "V1_goles"):
        # Estos no son descriptores intra; saltamos
        return None
    feats = fit_cache[variante]["feats"]
    coef = fit_cache[variante]["coef"]
    inter = fit_cache[variante]["intercept"]
    X = np.array([[ev[f] for f in feats] for ev in eventos], dtype=float)
    y = np.array([ev["goles"] for ev in eventos], dtype=float)
    pred = X @ np.array(coef) + inter
    rss = float(np.sum((y - pred) ** 2))
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - rss / tss
    rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
    return {"R2": r2, "RMSE_intra": rmse, "N": len(y)}


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("Cargando stats_partido_espn (con stats avanzadas completas)...")
    rows = cargar_partidos(cur)
    print(f"  rows: {len(rows)}")
    eventos = construir_eventos(rows)
    print(f"  eventos equipo-perspectiva: {len(eventos)}")
    eventos_train = [ev for ev in eventos if ev["fecha"][:4] in ("2022", "2023", "2024")]
    eventos_test = [ev for ev in eventos if ev["fecha"][:4] in ("2025", "2026")]
    print(f"  train (2022-2024): {len(eventos_train)}")
    print(f"  test  (2025-2026): {len(eventos_test)}")

    alfa_map = get_alfa_map(cur)
    beta_sot_map = get_beta_sot_map(cur)

    variantes = ["V0_baseline", "V0t_tuned_010", "V1_goles", "V2", "V3", "V4", "V5", "V6"]
    fit_cache = {}
    print("\n=== FIT (sobre 2022-2024 train) ===")
    for v in variantes:
        if v in ("V0_baseline", "V0t_tuned_010", "V1_goles"):
            print(f"  {v}: baseline (sin fit)")
            continue
        fit = fit_variante(v, eventos_train)
        fit_cache[v] = fit
        print(f"  {v} feats={fit['feats']}")
        print(f"     intercept={fit['intercept']:.4f}  coef={[round(c,4) for c in fit['coef']]}")

    print("\n=== R2 INTRA-PARTIDO (sobre train, descriptor power) ===")
    for v in variantes:
        r = medir_intra_r2(v, eventos_train, fit_cache, beta_sot_map)
        if r:
            print(f"  {v}: R2={r['R2']:.4f}  RMSE_intra={r['RMSE_intra']:.4f}  N={r['N']}")

    print("\n=== FORWARD-EMA RMSE (xg_p = xg_calc, sin hibrido extra) ===")
    print(f"{'variante':<18s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}")
    full_results = {}
    for v in variantes:
        # Para baselines hibridos V0/V0t/V1 ya tienen su mezcla incorporada en aplicar_variante.
        # Para V2..V6 medimos xg_calc puro.
        res = medir_forward_rmse(v, eventos, fit_cache, beta_sot_map, alfa_map, theta=None)
        full_results[v] = {"forward_pure": res}
        row = f"{v:<18s}"
        for a in ["2022", "2023", "2024", "2025", "2026", "IS"]:
            x = res.get(a)
            row += f"{x['rmse']:>10.4f}" if x else f"{'-':>10s}"
        print(row)

    print("\n=== HIBRIDO OPTIMO POR VARIANTE (theta de mezcla con goles) ===")
    print(f"{'variante':<18s}{'theta_opt':>12s}{'rmse_opt_IS':>14s}{'rmse_theta1':>14s}{'gain_vs_t1':>14s}")
    for v in ["V2", "V3", "V4", "V5", "V6"]:
        best = (None, math.inf)
        all_thetas = {}
        for t in THETAS:
            res = medir_forward_rmse(v, eventos, fit_cache, beta_sot_map, alfa_map, theta=t)
            r_is = res.get("IS", {}).get("rmse", math.inf)
            all_thetas[t] = res
            if r_is < best[1]: best = (t, r_is)
        full_results[v]["forward_grid_theta"] = all_thetas
        rmse_t1 = all_thetas[1.0]["IS"]["rmse"]
        gain = (rmse_t1 - best[1]) / rmse_t1 * 100
        print(f"{v:<18s}{best[0]:>12.2f}{best[1]:>14.4f}{rmse_t1:>14.4f}{gain:>13.2f}%")

    print("\n=== COMPARATIVA FINAL — RMSE IS forward (menor=mejor) ===")
    print(f"{'variante':<25s}{'config':<22s}{'rmse_IS':>10s}{'vs_motor':>12s}{'vs_goles':>12s}")
    motor_rmse = full_results["V0_baseline"]["forward_pure"]["IS"]["rmse"]
    goles_rmse = full_results["V1_goles"]["forward_pure"]["IS"]["rmse"]
    rows_final = []
    for v in ["V0_baseline", "V0t_tuned_010", "V1_goles"]:
        r = full_results[v]["forward_pure"]["IS"]["rmse"]
        rows_final.append((v, "(baseline)", r))
    for v in ["V2", "V3", "V4", "V5", "V6"]:
        # mejor theta del grid
        grid = full_results[v]["forward_grid_theta"]
        best_t = min(grid.keys(), key=lambda t: grid[t]["IS"]["rmse"])
        r = grid[best_t]["IS"]["rmse"]
        rows_final.append((v, f"theta_opt={best_t}", r))
        # tambien xg_calc puro (theta=1)
        rp = full_results[v]["forward_pure"]["IS"]["rmse"]
        rows_final.append((v + "_pure", "theta=1.0", rp))
    rows_final.sort(key=lambda x: x[2])
    for v, cfg, r in rows_final:
        d_motor = (motor_rmse - r) / motor_rmse * 100
        d_goles = (goles_rmse - r) / goles_rmse * 100
        marker = "  *MEJOR*" if r == rows_final[0][2] else ""
        print(f"{v:<25s}{cfg:<22s}{r:>10.4f}{d_motor:>+11.2f}%{d_goles:>+11.2f}%{marker}")

    Path("analisis/reoptimizar_xg_calc.json").write_text(
        json.dumps({"fit": fit_cache, "results": full_results, "rows_final": rows_final},
                   indent=2, default=str), encoding="utf-8"
    )
    print("\nJSON: analisis/reoptimizar_xg_calc.json")


if __name__ == "__main__":
    main()

"""adepor-3ip Audit V13 OOS: aplicar coeficientes calibrados a temp 2024 y
medir Brier + yield vs V0 (xG hibrido legacy).

Pipeline V13:
  1. xG_local_v13 = ridge_predict(features, intercept_local, coefs_local)
  2. xG_visita_v13 = ridge_predict(features, intercept_visita, coefs_visita)
  3. Probs via Poisson bivariado + tau Dixon-Coles (mismo motor que V0/V6)
  4. Comparar con V0 (probs ya en predicciones_oos_con_features.prob_*)

Umbral de elegibilidad V13 por liga: R2_oos >= 0.05 (umbral conservador).
Ligas no elegibles -> fallback V0 (no se loggea V13).

Output: JSON con metricas comparativas y elegibilidad final.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "v13_audit_oos.json"

R2_THRESHOLD = 0.05
RHO_FALLBACK = -0.09  # mismo que motor productivo


def cargar_coefs_v13(con):
    """Carga ultimos coefs por (liga, target). Retorna dict[liga][target] = coefs."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, target, intercept, coefs_json, r2_oos, mse_test
        FROM v13_coef_por_liga
        WHERE (liga, target, calibrado_en) IN (
            SELECT liga, target, MAX(calibrado_en)
            FROM v13_coef_por_liga
            GROUP BY liga, target
        )
    """).fetchall()
    coefs = defaultdict(dict)
    for liga, target, intercept, coefs_json, r2, mse in rows:
        coefs[liga][target] = {
            "intercept": intercept,
            "coefs": json.loads(coefs_json),
            "r2_oos": r2,
            "mse_test": mse,
        }
    return coefs


def cargar_oos_24(con):
    """OOS predicciones temp 2024 + EMA pre-partido para V13."""
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag,
               (SELECT json_object(
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'corners', ema_l_corners,
                    'sots_c', ema_c_sots, 'shot_pct_c', ema_c_shot_pct,
                    'n', n_acum)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.ht AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               (SELECT json_object(
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'corners', ema_l_corners,
                    'sots_c', ema_c_sots, 'shot_pct_c', ema_c_shot_pct,
                    'n', n_acum)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.at AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_v_json,
               -- Probs V0 + cuotas Pinnacle desde predicciones_oos_con_features (si match)
               -- Match por fecha truncada YYYY-MM-DD (formato distinto entre tablas)
               (SELECT json_object(
                    'prob_1', prob_1, 'prob_x', prob_x, 'prob_2', prob_2,
                    'psch', psch, 'pscd', pscd, 'psca', psca, 'outcome', outcome)
                FROM predicciones_oos_con_features
                WHERE liga=phe.liga
                  AND substr(fecha,1,10) = substr(phe.fecha,1,10)
                  AND local=phe.ht AND visita=phe.at
                LIMIT 1) AS oos_json
        FROM partidos_historico_externo phe
        WHERE phe.temp = 2024
          AND phe.hg IS NOT NULL AND phe.ag IS NOT NULL
    """
    rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if not d["ema_l_json"] or not d["ema_v_json"] or not d["oos_json"]:
            continue
        try:
            d["ema_l"] = json.loads(d["ema_l_json"])
            d["ema_v"] = json.loads(d["ema_v_json"])
            d["oos"] = json.loads(d["oos_json"])
        except Exception:
            continue
        if any(v is None for v in d["ema_l"].values()):
            continue
        if any(v is None for v in d["ema_v"].values()):
            continue
        out.append(d)
    return out


def construir_features(row, target_local=True):
    if target_local:
        ataque = row["ema_l"]
        defensa = row["ema_v"]
    else:
        ataque = row["ema_v"]
        defensa = row["ema_l"]
    return np.array([
        ataque["sots"], ataque["shot_pct"], ataque["pos"],
        ataque["pass_pct"], ataque["corners"],
        defensa["sots_c"], defensa["shot_pct_c"],
    ])


FEATURE_NAMES = [
    "atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
    "def_sots_c", "def_shot_pct_c",
]


def calcular_xg_v13(row, coefs_liga, target_local=True):
    target = "local" if target_local else "visita"
    cf = coefs_liga.get(target)
    if not cf:
        return None
    feats = construir_features(row, target_local=target_local)
    coefs_arr = np.array([cf["coefs"][n] for n in FEATURE_NAMES])
    pred = float(feats @ coefs_arr + cf["intercept"])
    return max(0.10, pred)


def poisson_pmf(k, lam):
    if lam <= 0:
        return 0.0 if k > 0 else 1.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def tau_dc(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    elif i == 1 and j == 0:
        return 1.0 + mu * rho
    elif i == 0 and j == 1:
        return 1.0 + lam * rho
    elif i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho=RHO_FALLBACK, max_g=8):
    if xg_l <= 0 or xg_v <= 0:
        return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    if s <= 0: return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


def kelly_fraction(p, cuota, cap=0.025):
    if cuota <= 1.0 or p <= 0: return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < 0.05:
        return None
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0: return None
    if prob * cuota - 1 < 0.03: return None
    stake = kelly_fraction(prob, cuota)
    if stake <= 0: return None
    profit = stake * (cuota - 1) if label == outcome else -stake
    gano = (label == outcome)
    return {"stake": stake, "profit": profit, "gano": gano, "label": label, "prob": prob, "cuota": cuota}


def brier_3way(p1, px, p2, outcome):
    target = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(outcome)
    if target is None: return None
    return (p1 - target[0]) ** 2 + (px - target[1]) ** 2 + (p2 - target[2]) ** 2


def yield_metrics(picks_dict_list):
    n_apost = sum(1 for p in picks_dict_list if p)
    n_gano = sum(1 for p in picks_dict_list if p and p["gano"])
    sum_stake = sum(p["stake"] for p in picks_dict_list if p)
    sum_pl = sum(p["profit"] for p in picks_dict_list if p)
    yld = (sum_pl / sum_stake * 100) if sum_stake > 0 else 0
    hit = (n_gano / n_apost * 100) if n_apost > 0 else 0
    pares = [(p["stake"], p["profit"]) for p in picks_dict_list if p]
    if pares:
        rng = np.random.default_rng(42)
        stks = np.array([p[0] for p in pares])
        profs = np.array([p[1] for p in pares])
        ys = []
        for _ in range(1000):
            idx = rng.integers(0, len(pares), size=len(pares))
            s, pp = stks[idx].sum(), profs[idx].sum()
            if s > 0: ys.append(pp / s * 100)
        ci_lo, ci_hi = float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))
    else:
        ci_lo = ci_hi = None
    return {
        "n_apost": n_apost, "n_gano": n_gano,
        "hit_pct": round(hit, 2), "yield_pct": round(yld, 2),
        "ci95_lo": round(ci_lo, 2) if ci_lo is not None else None,
        "ci95_hi": round(ci_hi, 2) if ci_hi is not None else None,
    }


def main():
    con = sqlite3.connect(DB)
    print("Cargando coefs V13...")
    coefs = cargar_coefs_v13(con)
    ligas_calib = sorted(coefs.keys())
    print(f"  Ligas con calibracion V13: {ligas_calib}")
    elegibles = [l for l in ligas_calib
                 if coefs[l].get("local", {}).get("r2_oos", -1) >= R2_THRESHOLD
                 or coefs[l].get("visita", {}).get("r2_oos", -1) >= R2_THRESHOLD]
    print(f"  Ligas con R2_oos>={R2_THRESHOLD} (elegibles V13): {elegibles}")
    print()

    print("Cargando OOS temp 2024 con EMA + cuotas Pinnacle...")
    rows = cargar_oos_24(con)
    print(f"  N partidos OOS 2024 con EMA+cuotas: {len(rows):,}")
    print()

    payload = {
        "fecha_audit": "2026-04-28",
        "r2_threshold": R2_THRESHOLD,
        "ligas_calibradas": ligas_calib,
        "ligas_elegibles_v13": elegibles,
        "n_oos_24": len(rows),
        "tests": {},
    }

    # Comparativa GLOBAL: V0 vs V13 (solo en ligas elegibles)
    print("=== Comparativa GLOBAL OOS 2024 ===")
    print(f"{'arquitectura':<18} {'NPred':>5} {'Brier':>8} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")

    rows_elegibles = [r for r in rows if r["liga"] in elegibles]
    print(f"  Subset ligas elegibles: N={len(rows_elegibles):,}")

    # V0 sobre ligas elegibles
    v0_briers = []
    v0_picks = []
    for r in rows_elegibles:
        p1, px, p2 = r["oos"]["prob_1"], r["oos"]["prob_x"], r["oos"]["prob_2"]
        c1, cx, c2 = r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"]
        outcome = r["oos"]["outcome"]
        b = brier_3way(p1, px, p2, outcome)
        if b is not None: v0_briers.append(b)
        v0_picks.append(evaluar_pick(p1, px, p2, c1, cx, c2, outcome))
    v0_metrics = yield_metrics(v0_picks)
    v0_brier = float(np.mean(v0_briers)) if v0_briers else None
    print(f"  {'V0 (legacy hibrido)':<18s} {len(rows_elegibles):>5} {v0_brier:>8.4f} "
          f"{v0_metrics['n_apost']:>7} {v0_metrics['hit_pct']:>6.1f} {v0_metrics['yield_pct']:>+8.1f} "
          f"[{v0_metrics['ci95_lo']:>+5.1f},{v0_metrics['ci95_hi']:>+5.1f}]")

    # V13 sobre ligas elegibles
    v13_briers = []
    v13_picks = []
    v13_skipped = 0
    for r in rows_elegibles:
        cf_liga = coefs.get(r["liga"], {})
        xg_l = calcular_xg_v13(r, cf_liga, target_local=True)
        xg_v = calcular_xg_v13(r, cf_liga, target_local=False)
        if xg_l is None or xg_v is None:
            v13_skipped += 1
            continue
        p1, px, p2 = probs_dc(xg_l, xg_v, rho=RHO_FALLBACK)
        c1, cx, c2 = r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"]
        outcome = r["oos"]["outcome"]
        b = brier_3way(p1, px, p2, outcome)
        if b is not None: v13_briers.append(b)
        v13_picks.append(evaluar_pick(p1, px, p2, c1, cx, c2, outcome))
    v13_metrics = yield_metrics(v13_picks)
    v13_brier = float(np.mean(v13_briers)) if v13_briers else None
    print(f"  {'V13 (xG aumentado)':<18s} {len(rows_elegibles)-v13_skipped:>5} {v13_brier:>8.4f} "
          f"{v13_metrics['n_apost']:>7} {v13_metrics['hit_pct']:>6.1f} {v13_metrics['yield_pct']:>+8.1f} "
          f"[{v13_metrics['ci95_lo']:>+5.1f},{v13_metrics['ci95_hi']:>+5.1f}]")
    print()
    print(f"  Brier delta V13-V0: {v13_brier - v0_brier:+.4f} ({'mejora' if v13_brier < v0_brier else 'empeora'})")

    payload["tests"]["global_v0_vs_v13"] = {
        "v0": {"brier": round(v0_brier, 4), **v0_metrics},
        "v13": {"brier": round(v13_brier, 4), "n_skipped": v13_skipped, **v13_metrics},
        "brier_delta": round(v13_brier - v0_brier, 4),
    }

    # Comparativa por liga
    print("\n=== Por liga (solo elegibles) ===")
    print(f"{'liga':<14} {'arch':<5} {'NPred':>5} {'Brier':>7} {'NApost':>6} {'Hit%':>6} {'Yield%':>7}")
    payload["tests"]["por_liga"] = {}
    for liga in elegibles:
        sub = [r for r in rows_elegibles if r["liga"] == liga]
        # V0
        v0_b, v0_p = [], []
        for r in sub:
            p1, px, p2 = r["oos"]["prob_1"], r["oos"]["prob_x"], r["oos"]["prob_2"]
            c1, cx, c2 = r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"]
            outcome = r["oos"]["outcome"]
            b = brier_3way(p1, px, p2, outcome)
            if b is not None: v0_b.append(b)
            v0_p.append(evaluar_pick(p1, px, p2, c1, cx, c2, outcome))
        v0_m = yield_metrics(v0_p)
        v0_br = float(np.mean(v0_b)) if v0_b else 0
        # V13
        v13_b, v13_p = [], []
        cf_liga = coefs[liga]
        for r in sub:
            xg_l = calcular_xg_v13(r, cf_liga, target_local=True)
            xg_v = calcular_xg_v13(r, cf_liga, target_local=False)
            if xg_l is None or xg_v is None:
                continue
            p1, px, p2 = probs_dc(xg_l, xg_v, rho=RHO_FALLBACK)
            c1, cx, c2 = r["oos"]["psch"], r["oos"]["pscd"], r["oos"]["psca"]
            outcome = r["oos"]["outcome"]
            b = brier_3way(p1, px, p2, outcome)
            if b is not None: v13_b.append(b)
            v13_p.append(evaluar_pick(p1, px, p2, c1, cx, c2, outcome))
        v13_m = yield_metrics(v13_p)
        v13_br = float(np.mean(v13_b)) if v13_b else 0
        print(f"{liga:<14} {'V0':<5} {len(sub):>5} {v0_br:>7.4f} {v0_m['n_apost']:>6} {v0_m['hit_pct']:>6.1f} {v0_m['yield_pct']:>+7.1f}")
        print(f"{liga:<14} {'V13':<5} {len(v13_b):>5} {v13_br:>7.4f} {v13_m['n_apost']:>6} {v13_m['hit_pct']:>6.1f} {v13_m['yield_pct']:>+7.1f}")
        payload["tests"]["por_liga"][liga] = {
            "v0": {"brier": round(v0_br, 4), **v0_m},
            "v13": {"brier": round(v13_br, 4), **v13_m},
        }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

"""Calibracion OLS de coeficientes xG por liga sobre partidos_historico_externo.

Pregunta: ¿valen la pena coeficientes xG distintos por liga (vs global)?

Modelo (per-match, per-team):
    goles = beta_sot * SoT + beta_off * shots_off + coef_corner * corners + intercept + e

Donde shots_off = shots - SoT.

Estructura: para cada liga, dual obs por partido (local, visita) -> goles_loc | goles_vis
con sus stats correspondientes. N total ~ 2 × n_partidos.

Comparativa contra:
- beta_sot global motor: 0.352 (P4 fase3)
- beta_shots_off global: 0.010
- coef_corner_liga: viene de ligas_stats.coef_corner_calculado

OLS via numpy linalg (no pandas, no sklearn — minimal deps).
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = ROOT / "analisis" / "calibracion_xg_ols_por_liga.json"

# Coeficientes globales actuales
BETA_SOT_GLOBAL = 0.352
BETA_OFF_GLOBAL = 0.010
COEF_CORNER_DEFAULT = 0.020


def ols_fit(X, y):
    """OLS con intercept. Returns (coefs, intercept, R2, residual_std)."""
    n, p = X.shape
    Xc = np.hstack([np.ones((n, 1)), X])
    beta, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    intercept = beta[0]
    coefs = beta[1:]
    y_pred = Xc @ beta
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    rmse = np.sqrt(ss_res / n)
    return coefs, intercept, r2, rmse


def calibrar_liga(con, liga):
    """OLS sobre partidos de esa liga. Pool home + away obs."""
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT hg, ag, hst, ast, hs, as_, hc, ac
        FROM partidos_historico_externo
        WHERE liga = ? AND has_full_stats = 1
        """,
        (liga,),
    ).fetchall()
    if not rows:
        return None

    # Build X, y: cada partido aporta 2 observaciones (home anota, away anota)
    X_rows = []
    y_rows = []
    for r in rows:
        hg, ag, hst, ast, hs, as_, hc, ac = r
        if hs is None or hst is None or hc is None:
            continue
        # home obs: goles_home = f(SoT_home, shots_off_home, corners_home)
        shots_off_h = max(0, hs - hst)
        X_rows.append([hst, shots_off_h, hc])
        y_rows.append(hg)
        # away obs
        shots_off_a = max(0, as_ - ast)
        X_rows.append([ast, shots_off_a, ac])
        y_rows.append(ag)

    if len(X_rows) < 100:
        return {"n": len(X_rows), "skip": "N<100"}

    X = np.array(X_rows, dtype=float)
    y = np.array(y_rows, dtype=float)
    coefs, intercept, r2, rmse = ols_fit(X, y)

    return {
        "n_obs": len(y),
        "n_partidos": len(rows),
        "beta_sot": float(coefs[0]),
        "beta_shots_off": float(coefs[1]),
        "coef_corner": float(coefs[2]),
        "intercept": float(intercept),
        "r2": float(r2),
        "rmse": float(rmse),
        "avg_goles": float(y.mean()),
        "avg_sot": float(X[:, 0].mean()),
        "avg_shots_off": float(X[:, 1].mean()),
        "avg_corners": float(X[:, 2].mean()),
    }


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    print("=" * 95)
    print("Calibracion OLS xG por liga — sobre partidos_historico_externo")
    print("=" * 95)
    print(f"Globales actuales: beta_sot={BETA_SOT_GLOBAL}, beta_off={BETA_OFF_GLOBAL}, coef_corner_default={COEF_CORNER_DEFAULT}")
    print()

    # Lista de ligas con stats
    ligas = [r[0] for r in cur.execute("""
        SELECT liga FROM partidos_historico_externo
        WHERE has_full_stats = 1
        GROUP BY liga
        HAVING COUNT(*) >= 100
        ORDER BY liga
    """)]
    print(f"Ligas con N>=100 partidos full-stats: {ligas}")
    print()

    print(f"{'Liga':<13} {'N_obs':>6} {'beta_sot':>9} {'beta_off':>9} {'coef_corner':>12} {'intercept':>10} {'R2':>6} {'RMSE':>6}")
    print(f"{'-'*13} {'-'*6} {'-'*9} {'-'*9} {'-'*12} {'-'*10} {'-'*6} {'-'*6}")

    out = {}
    for liga in ligas:
        r = calibrar_liga(con, liga)
        if not r or "skip" in r:
            print(f"{liga:<13} {'SKIP':>6}")
            continue
        out[liga] = r
        # Diferencia vs global
        delta_sot = r["beta_sot"] - BETA_SOT_GLOBAL
        delta_off = r["beta_shots_off"] - BETA_OFF_GLOBAL
        flag = ""
        if abs(delta_sot) > 0.05:
            flag += "BSDIF "
        if abs(delta_off) > 0.02:
            flag += "BODIF "
        print(f"{liga:<13} {r['n_obs']:>6} {r['beta_sot']:>9.4f} {r['beta_shots_off']:>9.4f} {r['coef_corner']:>12.4f} {r['intercept']:>10.4f} {r['r2']:>6.3f} {r['rmse']:>6.3f}  {flag}")

    print()
    print("=" * 95)
    print("Comparativa contra coef GLOBAL (motor actual)")
    print("=" * 95)
    print(f"{'Liga':<13} {'delta_β_sot':>11} {'delta_β_off':>11} {'delta_corner':>12}")
    for liga, r in sorted(out.items(), key=lambda x: -abs(x[1]["beta_sot"] - BETA_SOT_GLOBAL)):
        d_sot = r["beta_sot"] - BETA_SOT_GLOBAL
        d_off = r["beta_shots_off"] - BETA_OFF_GLOBAL
        # coef_corner_real (de ligas_stats)
        cc = cur.execute("SELECT coef_corner_calculado FROM ligas_stats WHERE liga=?", (liga,)).fetchone()
        cc_real = cc[0] if cc and cc[0] is not None else COEF_CORNER_DEFAULT
        d_corner = r["coef_corner"] - cc_real
        print(f"{liga:<13} {d_sot:>+11.4f} {d_off:>+11.4f} {d_corner:>+12.4f}")

    print()
    print("Veredicto: si delta_beta_sot > 0.05 en una liga, justifica scope-by-liga")
    print("           (motor real ya tiene scope por liga via P4 fase3 OLS)")
    print()

    # Calibracion POOLED (todas las ligas juntas) como referencia
    print("=" * 95)
    print("Pool global (todas ligas juntas, N>=100): coef pooled")
    print("=" * 95)
    rows_all = cur.execute("""
        SELECT hg, ag, hst, ast, hs, as_, hc, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1
    """).fetchall()
    X_pool, y_pool = [], []
    for r in rows_all:
        hg, ag, hst, ast, hs, as_, hc, ac = r
        if hs is None or hst is None or hc is None:
            continue
        X_pool.append([hst, max(0, hs - hst), hc])
        y_pool.append(hg)
        X_pool.append([ast, max(0, as_ - ast), ac])
        y_pool.append(ag)
    X_pool = np.array(X_pool, dtype=float)
    y_pool = np.array(y_pool, dtype=float)
    coefs_p, int_p, r2_p, rmse_p = ols_fit(X_pool, y_pool)
    print(f"Pool N={len(y_pool):>5} obs:")
    print(f"  beta_sot     = {coefs_p[0]:+.4f}  (motor actual: {BETA_SOT_GLOBAL})")
    print(f"  beta_off     = {coefs_p[1]:+.4f}  (motor actual: {BETA_OFF_GLOBAL})")
    print(f"  coef_corner  = {coefs_p[2]:+.4f}  (default actual: {COEF_CORNER_DEFAULT})")
    print(f"  intercept    = {int_p:+.4f}  (modelo asume 0 implicito)")
    print(f"  R²           = {r2_p:.4f}")
    print(f"  RMSE goles   = {rmse_p:.4f}")

    out["__pool__"] = {
        "n_obs": len(y_pool),
        "beta_sot": float(coefs_p[0]),
        "beta_shots_off": float(coefs_p[1]),
        "coef_corner": float(coefs_p[2]),
        "intercept": float(int_p),
        "r2": float(r2_p),
        "rmse": float(rmse_p),
    }

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Output: {OUT}")
    con.close()


if __name__ == "__main__":
    main()

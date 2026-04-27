"""[adepor-d7h] Calibracion V10 (x_mult per-liga) + V11 (LPM multinomial OLS).

V10:
  Para cada liga, calcular x_mult_v10_<liga> = freq_X_real / mean(P(X) v6 raw).
  Esto hace que P(X) reescalada matchee la freq_X observada en promedio.
  Mantiene el rho_boost = -0.10 de V8 como base.

V11:
  Linear Probability Model (3 OLS sobre indicators y_1, y_x, y_2).
  Features: [1 (intercept), xg_l, xg_v, xg_l-xg_v, |xg_l-xg_v|, (xg_l+xg_v)/2, xg_l*xg_v]
  Persiste coefs como JSON en config_motor_valores (clave lpm_v11_coefs_<liga>).

Ambos usan EMAs ya construidas en historial_equipos_v6_shadow + xG OLS.
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.gestor_nombres import limpiar_texto

DB = ROOT / "fondo_quant.db"
LIGAS = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
         'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
FUENTE = "V10V11_calib_2026-04-26_adepor-d7h"


def poisson_pmf(k, lam):
    if lam <= 0 or k < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def tau_dc(i, j, lam_l, lam_v, rho):
    if i == 0 and j == 0:
        return 1 - lam_l * lam_v * rho
    if i == 0 and j == 1:
        return 1 + lam_l * rho
    if i == 1 and j == 0:
        return 1 + lam_v * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def probs_poisson_dc(xg_l, xg_v, rho, max_g=10):
    if xg_l <= 0 or xg_v <= 0:
        return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    s = p1 + px + p2
    return (p1/s, px/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def features(xg_l, xg_v):
    """Vector de features V11 LPM (7 dims con intercept)."""
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v) / 2.0, xg_l * xg_v]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar EMAs V6
    v6 = {}
    for r in cur.execute("""
        SELECT equipo_norm, ema_xg_v6_favor_home, ema_xg_v6_contra_home,
               ema_xg_v6_favor_away, ema_xg_v6_contra_away
        FROM historial_equipos_v6_shadow
    """):
        v6[r[0]] = {'fh': r[1], 'ch': r[2], 'fa': r[3], 'ca': r[4]}
    rho_por_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    # Construir dataset por liga
    print("=" * 90)
    print("CALIBRACION V10 (x_mult per-liga) + V11 (LPM multinomial)")
    print("=" * 90)

    rows = cur.execute("""
        SELECT liga, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
    """.format(','.join(['?'] * len(LIGAS))), LIGAS).fetchall()

    por_liga = {liga: {'X': [], 'y': [], 'pX_v6': [], 'real': []} for liga in LIGAS}

    for liga, ht, at, hg, ag, *_ in rows:
        ht_n = limpiar_texto(ht)
        at_n = limpiar_texto(at)
        v_l = v6.get(ht_n)
        v_v = v6.get(at_n)
        if not v_l or not v_v:
            continue
        if any(v_l[k] is None for k in ('fh', 'ch')) or any(v_v[k] is None for k in ('fa', 'ca')):
            continue
        xg_l = max(0.10, (v_l['fh'] + v_v['ca']) / 2.0)
        xg_v = max(0.10, (v_v['fa'] + v_l['ch']) / 2.0)
        rho = rho_por_liga.get(liga, -0.04)

        _, px_v6, _ = probs_poisson_dc(xg_l, xg_v, rho)
        real = "1" if hg > ag else ("X" if hg == ag else "2")

        d = por_liga[liga]
        d['X'].append(features(xg_l, xg_v))
        d['real'].append(real)
        d['pX_v6'].append(px_v6)
        # y multinomial (3-vec): [y_1, y_x, y_2]
        y = [int(real == "1"), int(real == "X"), int(real == "2")]
        d['y'].append(y)

    # === V10: x_mult per liga ===
    print("\n--- V10 x_mult per-liga (rho_boost = -0.10 base) ---")
    print(f"{'Liga':<13s} {'N':>5s} {'mean_pX_v6':>11s} {'freq_X_real':>12s} {'x_mult_v10':>11s}")
    v10_mults = {}
    for liga in LIGAS:
        d = por_liga[liga]
        n = len(d['real'])
        if n == 0:
            print(f"{liga:<13s} {'SKIP':>5s}")
            continue
        mean_px = float(np.mean(d['pX_v6']))
        freq_x = sum(1 for r in d['real'] if r == 'X') / n
        mult = freq_x / mean_px if mean_px > 0 else 1.0
        # Clamp [1.0, 4.0] para robustez (mult <1 desactiva, >4 inestable)
        mult = max(1.0, min(4.0, mult))
        v10_mults[liga] = mult
        print(f"{liga:<13s} {n:>5d} {mean_px:>11.4f} {freq_x:>12.4f} {mult:>11.4f}")

    # === V11: LPM multinomial OLS ===
    print("\n--- V11 LPM multinomial OLS (3 betas) ---")
    print(f"{'Liga':<13s} {'N':>5s} {'R2_y1':>7s} {'R2_yX':>7s} {'R2_y2':>7s} {'coef_dim':>9s}")
    v11_coefs = {}
    for liga in LIGAS:
        d = por_liga[liga]
        n = len(d['real'])
        if n < 50:
            print(f"{liga:<13s} {n:>5d} skip (<50 obs)")
            continue
        X = np.array(d['X'], dtype=float)
        y = np.array(d['y'], dtype=float)
        # 3 OLS independientes
        betas = []
        r2s = []
        for k in range(3):
            yk = y[:, k]
            beta_k, _, _, _ = np.linalg.lstsq(X, yk, rcond=None)
            y_pred = X @ beta_k
            ss_res = np.sum((yk - y_pred) ** 2)
            ss_tot = np.sum((yk - yk.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            betas.append(beta_k.tolist())
            r2s.append(r2)
        v11_coefs[liga] = betas
        print(f"{liga:<13s} {n:>5d} {r2s[0]:>7.3f} {r2s[1]:>7.3f} {r2s[2]:>7.3f} {len(betas[0]):>9d}")

    # === Pool global LPM (para fallback ligas sin OLS específico) ===
    X_all = []
    y_all = []
    for liga in LIGAS:
        X_all.extend(por_liga[liga]['X'])
        y_all.extend(por_liga[liga]['y'])
    X_all = np.array(X_all, dtype=float)
    y_all = np.array(y_all, dtype=float)
    pool_betas = []
    for k in range(3):
        b, _, _, _ = np.linalg.lstsq(X_all, y_all[:, k], rcond=None)
        pool_betas.append(b.tolist())
    v11_coefs['__global__'] = pool_betas
    print(f"\n[POOL] N={len(y_all)} obs | coefs persistidos como scope=global")

    # === Persistir en config_motor_valores ===
    print("\n--- Persistencia en config_motor_valores ---")
    n_ins = 0
    for liga, mult in v10_mults.items():
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('x_mult_v10', ?, ?, NULL, 'real', ?, 0)
        """, (liga, mult, FUENTE))
        n_ins += 1
    # Default global x_mult_v10 = 1.0 (sin boost)
    cur.execute("""
        INSERT OR REPLACE INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
        VALUES ('x_mult_v10', 'global', 1.0, NULL, 'real', ?, 0)
    """, (FUENTE,))
    n_ins += 1

    for liga, betas in v11_coefs.items():
        scope = 'global' if liga == '__global__' else liga
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('lpm_v11_coefs', ?, NULL, ?, 'json', ?, 0)
        """, (scope, json.dumps(betas), FUENTE))
        n_ins += 1

    con.commit()
    print(f"[DONE] {n_ins} filas persistidas")
    con.close()


if __name__ == "__main__":
    main()

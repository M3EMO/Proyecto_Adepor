"""[adepor-2yo] V12b + Skellam-con-filtros + analisis empate. OOS estricto.

PARTE 1 — Analisis exploratorio empate sobre train:
    Para cada feature, computa Cohen's d y freq_X por quintil.
    Identifica los predictores mas potentes de X.

PARTE 2 — V12b variantes (pool global, ridge fuerte):
    V12b1: pool global, lambda=0.1, mismas features que V12
    V12b2: pool global, lambda=0.1, sin H2H, class_weight X x3 (boost empate en loss)

PARTE 3 — Skellam pool global con filtros:
    Sk_base: Skellam crudo
    Sk_xmult: + multiplicador post-hoc P(X) global (calibrado a freq train)
    Sk_delta: pickea X solo si |xg_l-xg_v| < threshold (calibrado max-margen empate)
    Sk_combo: combinacion de los anteriores

PARTE 4 — Eval OOS test 2024 + reporte.
"""
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comun.gestor_nombres import limpiar_texto

DB = ROOT / "fondo_quant.db"
LIGAS = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
         'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']
TRAIN_TEMP = {2021, 2022, 2023}
TEST_TEMP = {2024}
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}


# =========================================================================
# UTILIDADES
# =========================================================================

def poisson_pmf(k, lam):
    if lam <= 0 or k < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError): return 0.0


def probs_skellam(xg_l, xg_v, max_g=10):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p_h = p_d = p_a = 0.0
    for d in range(-max_g, max_g + 1):
        p_d_v = sum(poisson_pmf(d + y, xg_l) * poisson_pmf(y, xg_v)
                    for y in range(max(0, -d), max_g + 1))
        if d > 0: p_h += p_d_v
        elif d == 0: p_d += p_d_v
        else: p_a += p_d_v
    s = p_h + p_d + p_a
    return (p_h/s, p_d/s, p_a/s) if s > 0 else (1/3, 1/3, 1/3)


def softmax(Z):
    Z = Z - Z.max(axis=-1, keepdims=True)
    exp = np.exp(Z)
    return exp / exp.sum(axis=-1, keepdims=True)


def fit_logistic(X, Y, lr=0.05, n_iter=1500, ridge=0.1, class_weight=None):
    """class_weight: array (K,) para ponderar loss por clase."""
    N, D = X.shape; K = Y.shape[1]
    W = np.zeros((K, D))
    cw = np.array(class_weight) if class_weight is not None else np.ones(K)
    losses = []
    for it in range(n_iter):
        logits = X @ W.T
        P = softmax(logits)
        ce_per_class = -np.sum(Y * np.log(np.clip(P, 1e-12, 1)) * cw, axis=1)
        loss = ce_per_class.mean() + 0.5 * ridge * np.sum(W * W)
        losses.append(loss)
        # Gradient with class weighting
        dW = ((P - Y) * cw).T @ X / N + ridge * W
        W -= lr * dW
        if it > 0 and losses[-1] > losses[-2] * 1.5:
            lr *= 0.5
    return W, losses[-1]


def standardize(X, mean=None, std=None):
    X = np.array(X, dtype=float)
    if mean is None:
        mean = X.mean(axis=0); std = X.std(axis=0)
        std[std == 0] = 1.0; std[0] = 1.0; mean[0] = 0.0
    Xs = X.copy()
    Xs[:, 1:] = (X[:, 1:] - mean[1:]) / std[1:]
    return Xs, mean, std


def predict_lr(feats, W, mean, std):
    x = np.array(feats, dtype=float)
    xs = x.copy()
    for i in range(1, len(x)):
        xs[i] = (x[i] - mean[i]) / std[i]
    logits = W @ xs
    logits -= logits.max()
    e = np.exp(logits); s = e.sum()
    return (e[0]/s, e[1]/s, e[2]/s) if s > 0 else (1/3, 1/3, 1/3)


def feats_full(xg_l, xg_v, h2h_g, h2h_floc, h2h_fx, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v) / 2.0, xg_l * xg_v,
            h2h_g, h2h_floc, h2h_fx, var_l, var_v, float(mes)]


def feats_sin_h2h(xg_l, xg_v, var_l, var_v, mes):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
            (xg_l + xg_v) / 2.0, xg_l * xg_v, var_l, var_v, float(mes)]


def argmax_o(p1, px, p2):
    if p1 >= px and p1 >= p2: return "1"
    if p2 >= px and p2 >= p1: return "2"
    return "X"


def real_o(hg, ag):
    return "1" if hg > ag else ("2" if hg < ag else "X")


def brier(p1, px, p2, real):
    return ((p1 - (1 if real == "1" else 0))**2 +
            (px - (1 if real == "X" else 0))**2 +
            (p2 - (1 if real == "2" else 0))**2)


def calc_xg_v6(sot, shots, corners, goles, liga, ols):
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    c = ols.get(liga, OLS_GLOBAL)
    xg_calc = sot * c['beta_sot'] + shots_off * c['beta_off'] + corners * c['coef_corner'] + c['intercept']
    xg_calc = max(0.0, xg_calc)
    if xg_calc == 0 and goles > 0: return goles
    return (xg_calc * 0.70) + (goles * 0.30)


def ajustar_xg(xg, gf, gc):
    diff = (gf or 0) - (gc or 0)
    if diff > 0: return xg * min(1.0 + 0.08 * math.log(1 + diff), 1.20)
    if diff < 0: return xg * max(1.0 - 0.05 * math.log(1 + abs(diff)), 0.80)
    return xg


# =========================================================================
# MAIN
# =========================================================================

def main():
    con = sqlite3.connect(DB); cur = con.cursor()

    print("=" * 100)
    print("V12b + SKELLAM-FILTROS + ANALISIS EMPATE  Train 2021-23 / Test 2024 (OOS)")
    print("=" * 100)

    # Cargar OLS coefs
    ols_pl = {}
    for r in cur.execute("""SELECT scope, clave, valor_real FROM config_motor_valores
                             WHERE clave LIKE '%_v6_shadow'"""):
        scope, clave, val = r
        kmap = {'beta_sot_v6_shadow': 'beta_sot', 'beta_off_v6_shadow': 'beta_off',
                 'coef_corner_v6_shadow': 'coef_corner', 'intercept_v6_shadow': 'intercept'}
        if clave in kmap:
            ols_pl.setdefault(scope, {})[kmap[clave]] = val
    rho_pl = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    # Cargar partidos
    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha ASC
    """.format(','.join(['?'] * len(LIGAS))), LIGAS).fetchall()

    train_rows = [r for r in rows if r[1] in TRAIN_TEMP]
    test_rows  = [r for r in rows if r[1] in TEST_TEMP]
    print(f"Train: {len(train_rows)}  Test: {len(test_rows)}\n")

    # === BUILD EMA train-only + features train ===
    print("[1] Construyendo EMAs train-only + features dataset...")
    ema = defaultdict(lambda: {'fh': None, 'ch': None, 'fa': None, 'ca': None})
    var_eq = defaultdict(lambda: {'vfh': 0.5, 'vfa': 0.5})
    h2h = defaultdict(list)
    train_data = []  # (liga, feats_full, feats_sin_h2h, real, xg_l, xg_v)

    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in train_rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: continue
        e_l = ema[ht_n]; e_v = ema[at_n]

        if e_l['fh'] is not None and e_v['fa'] is not None:
            xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
            xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
            prev = []
            for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
                for p in h2h.get(k, []):
                    if p['fecha'] < fecha: prev.append(p)
            if prev:
                avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
                n_l = sum(1 for p in prev if (p['home'] == ht_n and p['hg'] > p['ag']) or
                                              (p['home'] != ht_n and p['ag'] > p['hg']))
                n_x = sum(1 for p in prev if p['hg'] == p['ag'])
                f_loc = n_l / len(prev); f_x = n_x / len(prev)
            else:
                avg_g, f_loc, f_x = 2.7, 0.45, 0.26
            v_l_t = var_eq[ht_n]; v_v_t = var_eq[at_n]
            mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
            ff = feats_full(xg_l, xg_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
            fs = feats_sin_h2h(xg_l, xg_v, v_l_t['vfh'], v_v_t['vfa'], mes)
            real = real_o(hg, ag)
            train_data.append((liga, ff, fs, real, xg_l, xg_v))

        # Update EMAs + var + H2H
        xg_v6_l = ajustar_xg(calc_xg_v6(hst, hs, hc, hg, liga, ols_pl), hg, ag)
        xg_v6_v = ajustar_xg(calc_xg_v6(ast, as_, ac, ag, liga, ols_pl), ag, hg)
        v_l_t = var_eq[ht_n]; v_v_t = var_eq[at_n]
        if e_l['fh'] is not None:
            v_l_t['vfh'] = ALFA * (xg_v6_l - e_l['fh'])**2 + (1-ALFA) * v_l_t['vfh']
        if e_v['fa'] is not None:
            v_v_t['vfa'] = ALFA * (xg_v6_v - e_v['fa'])**2 + (1-ALFA) * v_v_t['vfa']
        if e_l['fh'] is None:
            e_l['fh'] = xg_v6_l; e_l['ch'] = xg_v6_v
        else:
            e_l['fh'] = ALFA * xg_v6_l + (1-ALFA) * e_l['fh']
            e_l['ch'] = ALFA * xg_v6_v + (1-ALFA) * e_l['ch']
        if e_v['fa'] is None:
            e_v['fa'] = xg_v6_v; e_v['ca'] = xg_v6_l
        else:
            e_v['fa'] = ALFA * xg_v6_v + (1-ALFA) * e_v['fa']
            e_v['ca'] = ALFA * xg_v6_l + (1-ALFA) * e_v['ca']
        h2h[(liga, ht_n, at_n)].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home': ht_n})

    print(f"  Train con features (post-EMA warmup): {len(train_data)}")

    # === [PARTE 1] ANALISIS EXPLORATORIO EMPATE ===
    print("\n[2] === ANALISIS EXPLORATORIO: que features predicen X? ===")
    F = np.array([d[1] for d in train_data])  # full features (D=13)
    R = np.array([d[3] for d in train_data])
    is_x = (R == "X")
    feat_names = ['intercept', 'xg_l', 'xg_v', 'delta', '|delta|', 'avg_xg', 'prod_xg',
                  'h2h_avg_g', 'h2h_floc', 'h2h_fx', 'var_l', 'var_v', 'mes']

    print(f"\n{'feature':<12s} {'mean(X)':>9s} {'mean(noX)':>9s} {'cohen_d':>8s} {'freq_X by quintil (Q1->Q5)':>40s}")
    print("-" * 90)
    for i in range(1, F.shape[1]):  # skip intercept
        v = F[:, i]
        m1 = v[is_x].mean(); m0 = v[~is_x].mean()
        s1 = v[is_x].std(); s0 = v[~is_x].std()
        n1, n0 = is_x.sum(), (~is_x).sum()
        pooled = math.sqrt(((n1-1)*s1**2 + (n0-1)*s0**2) / (n1 + n0 - 2)) if (n1 + n0) > 2 else 1.0
        d = (m1 - m0) / pooled if pooled > 0 else 0
        # Quintiles
        qs = np.quantile(v, [0, 0.2, 0.4, 0.6, 0.8, 1.0])
        freq_q = []
        for qi in range(5):
            mask = (v >= qs[qi]) & (v <= qs[qi+1] if qi == 4 else v < qs[qi+1])
            freq_q.append(is_x[mask].mean() if mask.sum() > 0 else 0)
        freq_str = " ".join(f"{f:.3f}" for f in freq_q)
        print(f"{feat_names[i]:<12s} {m1:>9.3f} {m0:>9.3f} {d:>+8.3f}  {freq_str}")

    # Combinaciones interesantes
    print("\n=== COMBINACIONES (buckets bivariate) ===")
    avg_xg = F[:, 5]; abs_delta = F[:, 4]
    print("avg_xg  |  abs_delta  | freq_X | N")
    for avg_b in [(0, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 99)]:
        for delta_b in [(0, 0.1), (0.1, 0.3), (0.3, 0.6), (0.6, 99)]:
            mask = (avg_xg >= avg_b[0]) & (avg_xg < avg_b[1]) & (abs_delta >= delta_b[0]) & (abs_delta < delta_b[1])
            n = mask.sum()
            if n < 30: continue
            fX = is_x[mask].mean()
            print(f"  [{avg_b[0]:.1f},{avg_b[1]:.1f})  [{delta_b[0]:.1f},{delta_b[1]:.1f})  {fX:.3f}  {n}")

    # === [PARTE 2] ENTRENAR V12b ===
    print("\n[3] === V12b variantes (pool global ridge=0.1) ===")
    # V12b1: full features, ridge=0.1, class_weight uniforme
    X_full = np.array([d[1] for d in train_data])
    Y = np.zeros((len(train_data), 3))
    for i, d in enumerate(train_data):
        idx = {"1": 0, "X": 1, "2": 2}[d[3]]
        Y[i, idx] = 1.0
    X_full_s, mean_full, std_full = standardize(X_full)
    W_b1, loss_b1 = fit_logistic(X_full_s, Y, ridge=0.1)
    print(f"  V12b1 full features ridge=0.1 loss={loss_b1:.4f}")

    # V12b2: sin H2H, ridge=0.1, class_weight X x3
    X_sh = np.array([d[2] for d in train_data])
    X_sh_s, mean_sh, std_sh = standardize(X_sh)
    W_b2, loss_b2 = fit_logistic(X_sh_s, Y, ridge=0.1, class_weight=[1, 3, 1])
    print(f"  V12b2 sin H2H ridge=0.1 cw=[1,3,1] loss={loss_b2:.4f}")

    # V12b3: full + cw=[1,5,1] (mucho mas peso a X)
    W_b3, loss_b3 = fit_logistic(X_full_s, Y, ridge=0.1, class_weight=[1, 5, 1])
    print(f"  V12b3 full ridge=0.1 cw=[1,5,1] loss={loss_b3:.4f}")

    # === [PARTE 3] SKELLAM CON FILTROS pool global ===
    print("\n[4] === Skellam pool global + filtros ===")
    # Calibrar x_mult global Skellam
    px_skellam_train = []
    for liga, ff, fs, real, xg_l, xg_v in train_data:
        _, px, _ = probs_skellam(xg_l, xg_v)
        px_skellam_train.append(px)
    mean_px_sk = np.mean(px_skellam_train)
    freq_x_train = (R == "X").mean()
    x_mult_sk = freq_x_train / mean_px_sk if mean_px_sk > 0 else 1.0
    print(f"  Skellam: mean(P_X)={mean_px_sk:.4f}, freq_X_real={freq_x_train:.4f}, x_mult={x_mult_sk:.4f}")

    # Calibrar threshold delta para Skellam: en quintil mas bajo de |delta|, freq_X = ?
    abs_d_train = F[:, 4]
    quintiles_d = np.quantile(abs_d_train, [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    threshold_delta = quintiles_d[1]  # quintil 1 (top 20% mas pareja)
    fx_low_delta = (R[abs_d_train < threshold_delta] == "X").mean()
    print(f"  Threshold delta < {threshold_delta:.3f} (Q20): freq_X = {fx_low_delta:.3f}")

    # === [PARTE 4] EVAL OOS test 2024 ===
    print("\n[5] === Evaluando OOS test 2024 ===")
    # Estado EMA train-final
    final_ema = dict(ema); final_var = dict(var_eq); final_h2h = dict(h2h)

    arquitecturas = ['V0', 'V6', 'V12_old', 'V12b1', 'V12b2', 'V12b3',
                     'Sk_base', 'Sk_xmult', 'Sk_delta', 'Sk_combo']
    stats = {a: {'hit': 0, 'br': 0.0, 'argmax': {'1': 0, 'X': 0, '2': 0}, 'hit_x': 0} for a in arquitecturas}
    n_eval = 0
    real_count = {'1': 0, 'X': 0, '2': 0}

    # V12_old weights (LR per-liga global del train original — usar el mismo W_b1 sin class weight como referencia)
    W_v12_old = W_b1  # V12b1 = V12 con ridge=0.1 ≈ V12 mejorado standard

    # Necesito tambien V0 legacy y V6 OLS+DC — uso EMA ema+ pero con xG legacy/OLS
    # Para simplificar: V0=V6 con xG legacy, V6=Skellam con xG OLS
    # Ya tenemos xG OLS via EMA ema; para V0 legacy reconstruyo separado
    # Skip V0 aqui — comparativa anterior ya lo cubrio. Foco en V12b vs Skellam variantes.

    n_skip = 0
    for liga, temp, fecha, ht, at, hg, ag, hst, hs, hc, ast, as_, ac in test_rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        if not ht_n or not at_n: n_skip += 1; continue
        e_l = final_ema.get(ht_n); e_v = final_ema.get(at_n)
        if not e_l or not e_v or any(e_l.get(k) is None for k in ('fh', 'ch')) or any(e_v.get(k) is None for k in ('fa', 'ca')):
            n_skip += 1; continue
        xg_l = max(0.10, (e_l['fh'] + e_v['ca']) / 2.0)
        xg_v = max(0.10, (e_v['fa'] + e_l['ch']) / 2.0)
        prev = []
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
            prev.extend(final_h2h.get(k, []))
        if prev:
            avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
            n_l = sum(1 for p in prev if (p['home'] == ht_n and p['hg'] > p['ag']) or
                                          (p['home'] != ht_n and p['ag'] > p['hg']))
            n_x = sum(1 for p in prev if p['hg'] == p['ag'])
            f_loc = n_l / len(prev); f_x = n_x / len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26
        v_l_t = final_var.get(ht_n, {'vfh': 0.5}); v_v_t = final_var.get(at_n, {'vfa': 0.5})
        mes = int(fecha[5:7]) if len(fecha) >= 7 else 6
        real = real_o(hg, ag)

        n_eval += 1
        real_count[real] += 1

        # V12b1
        ff = feats_full(xg_l, xg_v, avg_g, f_loc, f_x, v_l_t['vfh'], v_v_t['vfa'], mes)
        p_b1 = predict_lr(ff, W_b1, mean_full, std_full)
        am_b1 = argmax_o(*p_b1)
        # V12b2 (sin H2H, cw=3)
        fs = feats_sin_h2h(xg_l, xg_v, v_l_t['vfh'], v_v_t['vfa'], mes)
        p_b2 = predict_lr(fs, W_b2, mean_sh, std_sh)
        am_b2 = argmax_o(*p_b2)
        # V12b3 (full, cw=5)
        p_b3 = predict_lr(ff, W_b3, mean_full, std_full)
        am_b3 = argmax_o(*p_b3)

        # V12_old (=V12b1 sin class weight, mismo)
        am_v12 = am_b1; p_v12 = p_b1

        # V0 legacy + V6 OLS+DC: ya cubierto en walk_forward_v12_oos.py — skip aqui

        # Skellam
        p_sk = probs_skellam(xg_l, xg_v)
        am_sk = argmax_o(*p_sk)
        # Sk_xmult: P(X) * x_mult global, renormalizar
        px_new = p_sk[1] * x_mult_sk
        s = p_sk[0] + px_new + p_sk[2]
        p_sk_xm = (p_sk[0]/s, px_new/s, p_sk[2]/s) if s > 0 else (1/3, 1/3, 1/3)
        am_sk_xm = argmax_o(*p_sk_xm)
        # Sk_delta: si |xg_l-xg_v| < threshold, force argmax=X (boost agresivo)
        if abs(xg_l - xg_v) < threshold_delta:
            # P(X) <- max(P(X), max(P(1), P(2)) + 0.01) para forzar argmax X
            px_force = max(p_sk[1], max(p_sk[0], p_sk[2]) + 0.01)
            s = p_sk[0] + px_force + p_sk[2]
            p_sk_d = (p_sk[0]/s, px_force/s, p_sk[2]/s) if s > 0 else (1/3, 1/3, 1/3)
        else:
            p_sk_d = p_sk
        am_sk_d = argmax_o(*p_sk_d)
        # Sk_combo: xmult + delta
        if abs(xg_l - xg_v) < threshold_delta:
            px_force = max(p_sk_xm[1] * 1.3, max(p_sk_xm[0], p_sk_xm[2]) + 0.01)
            s = p_sk_xm[0] + px_force + p_sk_xm[2]
            p_sk_c = (p_sk_xm[0]/s, px_force/s, p_sk_xm[2]/s) if s > 0 else p_sk_xm
        else:
            p_sk_c = p_sk_xm
        am_sk_c = argmax_o(*p_sk_c)

        # Acumular metricas
        for arch, (am, pp) in [
            ('V12b1', (am_b1, p_b1)), ('V12b2', (am_b2, p_b2)), ('V12b3', (am_b3, p_b3)),
            ('V12_old', (am_v12, p_v12)),
            ('Sk_base', (am_sk, p_sk)), ('Sk_xmult', (am_sk_xm, p_sk_xm)),
            ('Sk_delta', (am_sk_d, p_sk_d)), ('Sk_combo', (am_sk_c, p_sk_c)),
        ]:
            stats[arch]['hit'] += (1 if am == real else 0)
            stats[arch]['br'] += brier(*pp, real)
            stats[arch]['argmax'][am] += 1
            if am == 'X' and real == 'X':
                stats[arch]['hit_x'] += 1

    print(f"  Test evaluado: {n_eval}  Skip: {n_skip}\n")

    # === REPORTE ===
    print("=" * 100)
    print(f"OOS TEST 2024 (N={n_eval})")
    print("=" * 100)
    base_x = real_count['X'] / n_eval
    print(f"Base rate: 1={real_count['1']/n_eval:.3f}  X={base_x:.3f}  2={real_count['2']/n_eval:.3f}\n")

    print(f"{'arch':<12s} {'hit':>6s} {'Brier':>7s} {'%1':>6s} {'%X':>6s} {'%2':>6s} {'N_X':>5s} {'prec_X':>8s} {'edge_X':>8s}")
    print("-" * 75)
    archs_to_print = ['V12_old', 'V12b1', 'V12b2', 'V12b3', 'Sk_base', 'Sk_xmult', 'Sk_delta', 'Sk_combo']
    for a in archs_to_print:
        s = stats[a]
        hit = s['hit'] / n_eval
        br = s['br'] / n_eval
        p1 = s['argmax']['1'] / n_eval; pX = s['argmax']['X'] / n_eval; p2 = s['argmax']['2'] / n_eval
        nx = s['argmax']['X']
        prec_x = s['hit_x'] / nx if nx else 0
        edge = (prec_x - base_x) * 100 if nx else 0
        print(f"{a:<12s} {hit:>6.3f} {br:>7.4f} {p1:>6.3f} {pX:>6.3f} {p2:>6.3f} {nx:>5d} {prec_x:>8.3f} {edge:>+7.1f}pp")

    print(f"\n{'baseline V0 OOS':<12s} hit=0.488 Brier=0.6182 (referencia walk_forward_v12_oos.py)")
    print(f"{'baseline V6 OOS':<12s} hit=0.482 Brier=0.6222")

    con.close()


if __name__ == "__main__":
    main()

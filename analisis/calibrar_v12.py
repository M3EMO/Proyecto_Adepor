"""[adepor-d7h] V12 Logistic Multinomial OLS + features ampliados.

Features (D=13):
  [1, xg_l, xg_v, delta, |delta|, avg_xg, prod_xg,    <- V11 base (7)
   h2h_avg_goles, h2h_freq_local, h2h_freq_x,         <- H2H (3)
   var_l, var_v,                                       <- varianza histórica (2)
   mes_partido]                                        <- temporada (1)

Modelo: P(c|x) = softmax(W @ x), W shape (3, D).
Train: gradient descent con ridge λ=0.01, 500 iter, lr=0.05.
Per-liga + global pool fallback.

Persiste W como JSON en config_motor_valores 'lr_v12_weights' scope=liga|global.
"""
import json
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
FUENTE = "V12_logistic_multinomial_2026-04-26_adepor-d7h"

LR = 0.05
N_ITER = 800
RIDGE = 0.01


def softmax_rows(Z):
    """Softmax row-wise. Z shape (N, K) -> probs (N, K)."""
    Z = Z - Z.max(axis=1, keepdims=True)
    exp = np.exp(Z)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_logistic_multinomial(X, Y, lr=LR, n_iter=N_ITER, ridge=RIDGE):
    """Gradient descent multinomial logistic. X (N, D), Y (N, K) one-hot.
    Returns W shape (K, D), final loss.
    """
    N, D = X.shape
    K = Y.shape[1]
    W = np.zeros((K, D))
    losses = []
    for it in range(n_iter):
        logits = X @ W.T  # (N, K)
        P = softmax_rows(logits)
        # Cross entropy + ridge
        ce = -np.mean(np.sum(Y * np.log(np.clip(P, 1e-12, 1)), axis=1))
        reg = 0.5 * ridge * np.sum(W * W)
        loss = ce + reg
        losses.append(loss)
        # Gradient
        dW = (P - Y).T @ X / N + ridge * W   # (K, D)
        W -= lr * dW
        # Adaptive: if loss explodes, halve lr
        if it > 0 and losses[-1] > losses[-2] * 1.5:
            lr *= 0.5
    return W, losses[-1]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar EMAs V6 + varianzas
    print("Cargando EMAs y varianzas...")
    v6 = {}
    for r in cur.execute("""
        SELECT equipo_norm, ema_xg_v6_favor_home, ema_xg_v6_contra_home,
               ema_xg_v6_favor_away, ema_xg_v6_contra_away
        FROM historial_equipos_v6_shadow
    """):
        v6[r[0]] = {'fh': r[1], 'ch': r[2], 'fa': r[3], 'ca': r[4]}

    # Varianzas históricas (de tabla legacy, ya pre-calculadas via motor_data)
    var_eq = {}
    for r in cur.execute("""
        SELECT equipo_norm, ema_var_favor_home, ema_var_contra_home,
               ema_var_favor_away, ema_var_contra_away
        FROM historial_equipos
    """):
        var_eq[r[0]] = {
            'vfh': r[1] or 0.0, 'vch': r[2] or 0.0,
            'vfa': r[3] or 0.0, 'vca': r[4] or 0.0,
        }

    # Construir índice H2H: para cada par (liga, eq_a_norm, eq_b_norm), lista de partidos
    print("Construyendo índice H2H...")
    h2h = defaultdict(list)
    for r in cur.execute("""
        SELECT liga, ht, at, hg, ag, fecha
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY fecha ASC
    """):
        liga, ht, at, hg, ag, fecha = r
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        # Pair-canonical key (orden alfabético) para queries simétricas
        key = (liga, ht_n, at_n)
        h2h[key].append({'fecha': fecha, 'hg': hg, 'ag': ag, 'home_real': ht_n})

    # Mes desde fecha
    def mes_de(fecha_str):
        try:
            return int(fecha_str[5:7])
        except Exception:
            return 6

    # Construir dataset por liga
    print("\n=== Construcción dataset V12 ===")
    rows = cur.execute("""
        SELECT liga, ht, at, hg, ag, fecha
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha ASC
    """.format(','.join(['?'] * len(LIGAS))), LIGAS).fetchall()

    por_liga = {liga: {'X': [], 'y': [], 'real': []} for liga in LIGAS}
    n_skip = 0

    for liga, ht, at, hg, ag, fecha in rows:
        ht_n = limpiar_texto(ht); at_n = limpiar_texto(at)
        v_l = v6.get(ht_n); v_v = v6.get(at_n)
        if not v_l or not v_v:
            n_skip += 1
            continue
        if any(v_l[k] is None for k in ('fh', 'ch')) or any(v_v[k] is None for k in ('fa', 'ca')):
            n_skip += 1
            continue
        xg_l = max(0.10, (v_l['fh'] + v_v['ca']) / 2.0)
        xg_v = max(0.10, (v_v['fa'] + v_l['ch']) / 2.0)

        # H2H sobre partidos previos (incluye mismo orden y orden invertido)
        key1 = (liga, ht_n, at_n)
        key2 = (liga, at_n, ht_n)
        prev = []
        for k in (key1, key2):
            for p in h2h.get(k, []):
                if p['fecha'] < fecha:
                    prev.append(p)
        if prev:
            avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
            # Ajustar perspectiva: contar "freq_local" desde perspectiva del LOCAL del partido actual
            n_loc_win = sum(1 for p in prev if (p['home_real'] == ht_n and p['hg'] > p['ag']) or
                                                (p['home_real'] != ht_n and p['ag'] > p['hg']))
            n_x = sum(1 for p in prev if p['hg'] == p['ag'])
            f_loc = n_loc_win / len(prev)
            f_x = n_x / len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26  # defaults pool global

        var_l = var_eq.get(ht_n, {'vfh': 0.5, 'vch': 0.5})
        var_v = var_eq.get(at_n, {'vfa': 0.5, 'vca': 0.5})
        var_local_pred = (var_l['vfh'] + var_v['vca']) / 2.0  # variabilidad ofensiva local + def visita
        var_visita_pred = (var_v['vfa'] + var_l['vch']) / 2.0

        mes = mes_de(fecha)

        feats = [
            1.0,                          # intercept
            xg_l, xg_v,                   # xG OLS
            xg_l - xg_v,                  # delta
            abs(xg_l - xg_v),             # |delta|
            (xg_l + xg_v) / 2.0,          # avg
            xg_l * xg_v,                  # producto
            avg_g,                        # H2H avg goles
            f_loc,                        # H2H freq local
            f_x,                          # H2H freq X
            var_local_pred,               # varianza local
            var_visita_pred,              # varianza visita
            mes,                          # mes calendario
        ]

        real = "1" if hg > ag else ("X" if hg == ag else "2")
        y = [int(real == "1"), int(real == "X"), int(real == "2")]

        d = por_liga[liga]
        d['X'].append(feats)
        d['y'].append(y)
        d['real'].append(real)

    print(f"Skip lookup miss: {n_skip}")

    # === Train per-liga + global ===
    print(f"\n--- V12 logistic multinomial (lr={LR}, n_iter={N_ITER}, ridge={RIDGE}) ---")
    print(f"{'Liga':<13s} {'N':>5s} {'D':>3s} {'loss':>8s} {'%X_train':>9s} {'%X_pred':>9s} {'hit_in':>7s} {'Brier_in':>9s}")

    weights_por_liga = {}

    # Standardize features (per-liga, persist mean/std for inference)
    def standardize(X, mean=None, std=None):
        X = np.array(X, dtype=float)
        if mean is None:
            mean = X.mean(axis=0)
            std = X.std(axis=0)
            std[std == 0] = 1.0
            std[0] = 1.0  # intercept queda como 1
            mean[0] = 0.0
        Xs = X.copy()
        Xs[:, 1:] = (X[:, 1:] - mean[1:]) / std[1:]
        return Xs, mean, std

    for liga in LIGAS:
        d = por_liga[liga]
        N = len(d['X'])
        if N < 100:
            print(f"{liga:<13s} {N:>5d}  SKIP (<100)")
            continue
        Xs, mean, std = standardize(d['X'])
        Y = np.array(d['y'], dtype=float)
        W, loss = fit_logistic_multinomial(Xs, Y)

        # In-sample predict
        logits = Xs @ W.T
        P = softmax_rows(logits)
        argmax_pred = P.argmax(axis=1)
        argmax_real = Y.argmax(axis=1)
        hit_in = float((argmax_pred == argmax_real).mean())
        brier_in = float(((P - Y) ** 2).sum(axis=1).mean())
        x_pct_train = Y[:, 1].mean()
        x_pct_pred = (argmax_pred == 1).mean()

        weights_por_liga[liga] = {
            'W': W.tolist(),
            'mean': mean.tolist(),
            'std': std.tolist(),
        }
        print(f"{liga:<13s} {N:>5d} {Xs.shape[1]:>3d} {loss:>8.4f} {x_pct_train:>9.3f} {x_pct_pred:>9.3f} {hit_in:>7.3f} {brier_in:>9.4f}")

    # Pool global
    print("\n--- Pool global ---")
    X_all = []
    Y_all = []
    for liga in LIGAS:
        X_all.extend(por_liga[liga]['X'])
        Y_all.extend(por_liga[liga]['y'])
    Xs, mean, std = standardize(X_all)
    Y_arr = np.array(Y_all, dtype=float)
    W_g, loss_g = fit_logistic_multinomial(Xs, Y_arr)
    logits = Xs @ W_g.T
    P = softmax_rows(logits)
    hit_in = float((P.argmax(axis=1) == Y_arr.argmax(axis=1)).mean())
    brier_in = float(((P - Y_arr) ** 2).sum(axis=1).mean())
    x_pct_pred = (P.argmax(axis=1) == 1).mean()
    print(f"GLOBAL N={len(Y_all)} loss={loss_g:.4f} %X_pred={x_pct_pred:.3f} hit={hit_in:.3f} Brier={brier_in:.4f}")
    weights_por_liga['__global__'] = {'W': W_g.tolist(), 'mean': mean.tolist(), 'std': std.tolist()}

    # Persistir
    n_ins = 0
    for liga, payload in weights_por_liga.items():
        scope = 'global' if liga == '__global__' else liga
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('lr_v12_weights', ?, NULL, ?, 'json', ?, 0)
        """, (scope, json.dumps(payload), FUENTE))
        n_ins += 1

    con.commit()
    print(f"\n[DONE] {n_ins} pesos persistidos como lr_v12_weights")
    con.close()


if __name__ == "__main__":
    main()

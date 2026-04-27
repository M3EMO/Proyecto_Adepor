"""[adepor-d7h F1] Online SGD prototype para V12 LR multinomial.

Aplica un SGD step incremental sobre lr_v12_weights[scope] dado un partido liquidado.
Persiste W actualizado + log diagnostico en online_sgd_log.

Uso interactivo (testing):
    py scripts/online_sgd_v12.py --liga Argentina --partidos 100

Uso programatico (desde motor_data.py):
    from scripts.online_sgd_v12 import sgd_step_partido
    sgd_step_partido(conn, liga, features, real_outcome)

Limites:
- mean/std FROZEN del entrenamiento batch (lr_v12_weights tiene mean+std embeddidos).
- Update solo si N_acum >= 100 (warmup).
- lr clamp [0.001, 0.01].
- Anchor regularization opcional (lambda_anchor).
"""
import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "fondo_quant.db"
LR_BASE = 0.005          # learning rate online
LAMBDA_RIDGE = 0.1       # ridge (mismo que batch)
LAMBDA_ANCHOR = 0.05     # anchor regularization hacia W_batch (anti-catastrophic forget)
WARMUP_N = 100           # min partidos batch antes de habilitar online
DELTA_LOSS_MAX = 1.5     # si loss post-step > pre × 1.5, revertir


def softmax(z):
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def init_log_table():
    """Crea tabla online_sgd_log si no existe."""
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS online_sgd_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_log TEXT NOT NULL,
            bead_id TEXT,
            arch TEXT NOT NULL,
            n_partidos_acum INTEGER,
            grad_norm REAL,
            weight_norm REAL,
            brier_pre REAL,
            loss_pre REAL,
            loss_post REAL,
            delta_weight REAL,
            reverted INTEGER DEFAULT 0,
            notes TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_online_sgd_arch ON online_sgd_log(arch)")
    con.commit(); con.close()


def get_batch_anchor(liga, conn):
    """Carga W_batch (snapshot del último entrenamiento batch) para anchor regularization."""
    row = conn.execute("""
        SELECT valor_texto FROM config_motor_valores
        WHERE clave='lr_v12_weights' AND scope=?
    """, (liga or 'global',)).fetchone()
    if not row or row[0] is None:
        return None
    payload = json.loads(row[0])
    return np.array(payload['W']), np.array(payload['mean']), np.array(payload['std']), payload


def cross_entropy(P, y_idx):
    return -math.log(max(1e-12, P[y_idx]))


def sgd_step(W, mean, std, x_raw, y_one_hot, W_anchor=None,
              lr=LR_BASE, ridge=LAMBDA_RIDGE, lambda_anchor=LAMBDA_ANCHOR):
    """Un step SGD multinomial logistic.
    Returns: W_new, grad_norm, loss_pre, loss_post, P_pre.
    """
    # Standardize
    x_std = x_raw.copy()
    for i in range(1, len(x_raw)):
        s = std[i] if std[i] > 0 else 1.0
        x_std[i] = (x_raw[i] - mean[i]) / s

    # Forward (pre-update)
    logits = W @ x_std
    P_pre = softmax(logits)
    y_idx = int(np.argmax(y_one_hot))
    loss_pre = cross_entropy(P_pre, y_idx) + 0.5 * ridge * np.sum(W * W)
    if W_anchor is not None:
        loss_pre += 0.5 * lambda_anchor * np.sum((W - W_anchor) ** 2)

    # Gradient: (P - y) ⊗ x_std + ridge*W + λ_anchor*(W - W_anchor)
    error = (P_pre - y_one_hot)  # (3,)
    grad = np.outer(error, x_std) + ridge * W
    if W_anchor is not None:
        grad += lambda_anchor * (W - W_anchor)
    grad_norm = float(np.linalg.norm(grad))

    # Step
    W_new = W - lr * grad

    # Validate post-step loss
    logits_post = W_new @ x_std
    P_post = softmax(logits_post)
    loss_post = cross_entropy(P_post, y_idx) + 0.5 * ridge * np.sum(W_new * W_new)
    if W_anchor is not None:
        loss_post += 0.5 * lambda_anchor * np.sum((W_new - W_anchor) ** 2)

    return W_new, grad_norm, loss_pre, loss_post, P_pre


def sgd_step_partido(conn, liga, features_v12, real_outcome, bead_id="online_v12"):
    """API pública: un step SGD sobre el partido y persistir.

    Args:
        conn: sqlite3.Connection
        liga: str (scope, 'global' como fallback)
        features_v12: list[float] de 13 elementos (mismo orden que feats_v12 batch)
        real_outcome: '1' | 'X' | '2'
    """
    init_log_table()
    cur = conn.cursor()

    # 1. Cargar W actual (puede haber sido updateado por SGD anteriores)
    W, mean, std, payload = get_batch_anchor(liga, conn) or (None, None, None, None)
    if W is None:
        return False, "no_weights"

    # 2. Cargar anchor (snapshot batch)
    anchor_row = cur.execute("""
        SELECT valor_texto FROM config_motor_valores
        WHERE clave='lr_v12_weights_batch_anchor' AND scope=?
    """, (liga,)).fetchone()
    if anchor_row and anchor_row[0]:
        W_anchor = np.array(json.loads(anchor_row[0])['W'])
    else:
        # Si no existe anchor: el W actual ES el anchor (primera vez)
        W_anchor = W.copy()
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('lr_v12_weights_batch_anchor', ?, NULL, ?, 'json', ?, 0)
        """, (liga, json.dumps({'W': W_anchor.tolist()}), 'snapshot_batch'))

    # 3. N_acum tracker (tabla simple)
    n_row = cur.execute("""
        SELECT valor_real FROM config_motor_valores
        WHERE clave='online_sgd_n_partidos' AND scope=?
    """, (liga,)).fetchone()
    n_acum = int(n_row[0]) if n_row and n_row[0] else 0

    if n_acum < WARMUP_N:
        # Warmup: incrementar contador sin SGD
        cur.execute("""
            INSERT OR REPLACE INTO config_motor_valores
                (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
            VALUES ('online_sgd_n_partidos', ?, ?, NULL, 'real', ?, 0)
        """, (liga, n_acum + 1, 'online_sgd'))
        conn.commit()
        return False, f"warmup ({n_acum + 1}/{WARMUP_N})"

    # 4. Construir y_one_hot
    y_idx = {'1': 0, 'X': 1, '2': 2}[real_outcome]
    y_one_hot = np.zeros(3); y_one_hot[y_idx] = 1.0

    x_raw = np.array(features_v12, dtype=float)

    # 5. SGD step
    W_new, grad_norm, loss_pre, loss_post, P_pre = sgd_step(
        W, mean, std, x_raw, y_one_hot, W_anchor=W_anchor)

    delta_w = float(np.linalg.norm(W_new - W))
    weight_norm = float(np.linalg.norm(W_new))
    brier_pre = float(np.sum((P_pre - y_one_hot) ** 2))

    # 6. Sanity check: revertir si loss explode
    reverted = 0
    if loss_post > loss_pre * DELTA_LOSS_MAX:
        W_new = W
        reverted = 1

    # 7. Persistir W_new (sobreescribe lr_v12_weights[scope])
    if not reverted:
        new_payload = dict(payload)
        new_payload['W'] = W_new.tolist()
        cur.execute("""
            UPDATE config_motor_valores SET valor_texto=?, fecha_actualizacion=CURRENT_TIMESTAMP
            WHERE clave='lr_v12_weights' AND scope=?
        """, (json.dumps(new_payload), liga))

    # 8. Update n_acum
    cur.execute("""
        INSERT OR REPLACE INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
        VALUES ('online_sgd_n_partidos', ?, ?, NULL, 'real', ?, 0)
    """, (liga, n_acum + 1, 'online_sgd'))

    # 9. Log
    cur.execute("""
        INSERT INTO online_sgd_log
            (fecha_log, bead_id, arch, n_partidos_acum, grad_norm, weight_norm,
             brier_pre, loss_pre, loss_post, delta_weight, reverted, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), bead_id, f'v12_{liga}', n_acum + 1,
          grad_norm, weight_norm, brier_pre, loss_pre, loss_post, delta_w, reverted,
          f"y={real_outcome} P_pre=[{P_pre[0]:.3f},{P_pre[1]:.3f},{P_pre[2]:.3f}]"))

    conn.commit()
    return True, f"step_done (delta_w={delta_w:.4f}, reverted={reverted})"


def demo_run(n_partidos=100, liga='global'):
    """Demo: simula online SGD sobre N partidos sintéticos para verificar pipeline."""
    init_log_table()
    con = sqlite3.connect(DB)

    print(f"=== Demo Online SGD V12 ===")
    print(f"  liga={liga}  n_partidos={n_partidos}")

    # Reset n_acum a 0 para demo
    con.execute("DELETE FROM config_motor_valores WHERE clave='online_sgd_n_partidos' AND scope=?", (liga,))
    con.execute("DELETE FROM config_motor_valores WHERE clave='lr_v12_weights_batch_anchor' AND scope=?", (liga,))
    con.commit()

    # Generar partidos sintéticos
    np.random.seed(42)
    n_done = 0; n_warmup = 0; n_reverted = 0
    for i in range(n_partidos):
        # Features sintéticos (rango razonable)
        xg_l = np.random.uniform(0.5, 2.5)
        xg_v = np.random.uniform(0.5, 2.5)
        feats = [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
                 (xg_l + xg_v)/2, xg_l*xg_v,
                 np.random.uniform(2.0, 3.5),    # h2h_avg_g
                 np.random.uniform(0.30, 0.55),  # h2h_floc
                 np.random.uniform(0.20, 0.32),  # h2h_fx
                 np.random.uniform(0.3, 1.2),    # var_l
                 np.random.uniform(0.3, 1.2),    # var_v
                 np.random.randint(1, 13)]       # mes
        # Outcome random ponderado
        outcome = np.random.choice(['1', 'X', '2'], p=[0.45, 0.25, 0.30])
        ok, msg = sgd_step_partido(con, liga, feats, outcome)
        if ok:
            n_done += 1
            if 'reverted=1' in msg: n_reverted += 1
        else:
            n_warmup += 1
        if (i + 1) % 20 == 0:
            print(f"  partido {i+1}: {msg}")

    print(f"\n[DONE] warmup={n_warmup} steps_done={n_done} reverted={n_reverted}")

    # Mostrar log reciente
    print("\n=== online_sgd_log (ultimas 5 entradas) ===")
    for r in con.execute("""SELECT n_partidos_acum, grad_norm, weight_norm, brier_pre, delta_weight, reverted
                             FROM online_sgd_log WHERE arch=? ORDER BY id DESC LIMIT 5""", (f'v12_{liga}',)):
        print(f"  N={r[0]}  grad={r[1]:.4f}  W_norm={r[2]:.3f}  Brier={r[3]:.3f}  dW={r[4]:.4f}  rev={r[5]}")

    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Online SGD V12 prototype")
    parser.add_argument('--liga', default='global', help='scope (default: global)')
    parser.add_argument('--partidos', type=int, default=150, help='N partidos demo (default: 150)')
    args = parser.parse_args()
    demo_run(args.partidos, args.liga)

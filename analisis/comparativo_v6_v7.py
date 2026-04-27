"""[adepor-d7h] Comparativa V0_legacy / V6 / V7 / V8 / V9.

Aprovecha historial_equipos_v6_shadow (xG OLS) y historial_equipos (xG legacy)
para evaluar retrospectivamente sobre partidos liquidados con stats raw.

V0 = xG legacy + Poisson DC                       (motor actual)
V6 = xG OLS    + Poisson DC                       (recalibración stats)
V7 = xG OLS    + Skellam (sin tau DC)             (distribución alternativa)
V8 = xG OLS    + Poisson DC con rho boosted       (activar empates vía tau)
V9 = xG OLS    + Poisson DC + X-multiplier post-hoc (activar empates vía mult)

Params V8/V9 leídos desde config_motor_valores (scope=global).

NOTA SOBRE LEAK: los EMAs incluyen al propio partido. Esto sesga el hit rate
absoluto al alza, pero la COMPARATIVA inter-arquitecturas sigue siendo válida
porque todas sufren el mismo leak. Las cifras NO son predicciones out-of-sample.

Métricas:
  - Hit rate del argmax 1X2
  - Brier multiclase (sum (p_i - y_i)²)
  - Bias xG total vs goles totales
  - Distribución argmax (% picks por outcome)
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

# Ligas con cobertura ALTA (>=20 partidos avg en V6 shadow)
LIGAS_AUDIT = ['Alemania', 'Argentina', 'Brasil', 'Chile', 'Colombia',
               'Espana', 'Francia', 'Inglaterra', 'Italia', 'Turquia']


def poisson_pmf(k, lam):
    if lam <= 0 or k < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def tau_dc(i, j, lam_l, lam_v, rho):
    """Dixon-Coles tau para corregir baja-puntuación."""
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


def probs_skellam(xg_l, xg_v, max_g=10):
    if xg_l <= 0 or xg_v <= 0:
        return 1/3, 1/3, 1/3
    p_h = p_d = p_a = 0.0
    for d in range(-max_g, max_g + 1):
        p_d_val = sum(poisson_pmf(d + y, xg_l) * poisson_pmf(y, xg_v)
                      for y in range(max(0, -d), max_g + 1))
        if d > 0:
            p_h += p_d_val
        elif d == 0:
            p_d += p_d_val
        else:
            p_a += p_d_val
    s = p_h + p_d + p_a
    return (p_h/s, p_d/s, p_a/s) if s > 0 else (1/3, 1/3, 1/3)


def argmax_outcome(p1, px, p2):
    if p1 >= px and p1 >= p2:
        return "1"
    if p2 >= px and p2 >= p1:
        return "2"
    return "X"


def real_outcome(hg, ag):
    if hg > ag:
        return "1"
    if hg < ag:
        return "2"
    return "X"


def brier(p1, px, p2, real):
    y1 = 1 if real == "1" else 0
    yx = 1 if real == "X" else 0
    y2 = 1 if real == "2" else 0
    return (p1 - y1)**2 + (px - yx)**2 + (p2 - y2)**2


def aplicar_v9_x_mult(p1, px, p2, mult):
    """V9: multiplica P(X) y renormaliza."""
    if mult <= 0:
        return p1, px, p2
    px_new = px * mult
    s = p1 + px_new + p2
    return (p1/s, px_new/s, p2/s) if s > 0 else (1/3, 1/3, 1/3)


def features_v11(xg_l, xg_v):
    return [1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v), (xg_l + xg_v) / 2.0, xg_l * xg_v]


def probs_v11_lpm(xg_l, xg_v, betas):
    """V11 LPM. betas = [[β_y1...], [β_yx...], [β_y2...]] o None."""
    if not betas:
        return 1/3, 1/3, 1/3
    feats = features_v11(xg_l, xg_v)
    preds = []
    for beta in betas:
        yhat = sum(b * f for b, f in zip(beta, feats))
        preds.append(max(0.001, min(0.999, yhat)))
    s = sum(preds)
    if s <= 0:
        return 1/3, 1/3, 1/3
    return preds[0]/s, preds[1]/s, preds[2]/s


def features_v12(xg_l, xg_v, h2h_avg_g, h2h_f_loc, h2h_f_x, var_l_pred, var_v_pred, mes):
    """V12: 13 features con H2H + varianza + temporada."""
    return [
        1.0, xg_l, xg_v, xg_l - xg_v, abs(xg_l - xg_v),
        (xg_l + xg_v) / 2.0, xg_l * xg_v,
        h2h_avg_g, h2h_f_loc, h2h_f_x,
        var_l_pred, var_v_pred, float(mes),
    ]


def probs_v12_lr(feats, payload):
    """V12 logistic multinomial. payload = {'W': [[3xD]], 'mean': [D], 'std': [D]}."""
    if not payload:
        return 1/3, 1/3, 1/3
    W = np.array(payload['W'])
    mean = np.array(payload['mean'])
    std = np.array(payload['std'])
    x = np.array(feats, dtype=float)
    xs = x.copy()
    xs[1:] = (x[1:] - mean[1:]) / std[1:]
    logits = W @ xs
    logits = logits - logits.max()
    exp = np.exp(logits)
    p = exp / exp.sum()
    return float(p[0]), float(p[1]), float(p[2])


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar params V8/V9 desde config
    import json as _json
    rho_v8_delta = cur.execute(
        "SELECT valor_real FROM config_motor_valores WHERE clave='rho_v8_delta' AND scope='global'"
    ).fetchone()
    rho_v8_delta = rho_v8_delta[0] if rho_v8_delta else -0.10
    x_mult_v9 = cur.execute(
        "SELECT valor_real FROM config_motor_valores WHERE clave='x_mult_v9' AND scope='global'"
    ).fetchone()
    x_mult_v9 = x_mult_v9[0] if x_mult_v9 else 1.40

    # V10: x_mult per-liga
    x_mult_v10 = {}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='x_mult_v10'"):
        x_mult_v10[r[0]] = r[1]

    # V11: LPM coefs per-liga + global
    lpm_v11 = {}
    for r in cur.execute("SELECT scope, valor_texto FROM config_motor_valores WHERE clave='lpm_v11_coefs'"):
        if r[1]:
            lpm_v11[r[0]] = _json.loads(r[1])

    # V12: logistic multinomial weights + standardization (W, mean, std) per-liga + global
    lr_v12 = {}
    for r in cur.execute("SELECT scope, valor_texto FROM config_motor_valores WHERE clave='lr_v12_weights'"):
        if r[1]:
            lr_v12[r[0]] = _json.loads(r[1])

    print(f"Params V8/V9: rho_v8_delta={rho_v8_delta:+.3f}  x_mult_v9={x_mult_v9:.3f}")
    print(f"Params V10:   x_mult per-liga loaded ({len(x_mult_v10)} ligas)")
    print(f"Params V11:   LPM coefs loaded ({len(lpm_v11)} scopes)")
    print(f"Params V12:   logistic LR weights loaded ({len(lr_v12)} scopes)\n")

    # Cargar EMAs V6 shadow + xG legacy en memoria
    print("Cargando EMAs...")
    v6 = {}
    for r in cur.execute("""
        SELECT equipo_norm, ema_xg_v6_favor_home, ema_xg_v6_contra_home,
               ema_xg_v6_favor_away, ema_xg_v6_contra_away
        FROM historial_equipos_v6_shadow
    """):
        v6[r[0]] = {'fh': r[1], 'ch': r[2], 'fa': r[3], 'ca': r[4]}

    legacy = {}
    for r in cur.execute("""
        SELECT equipo_norm, ema_xg_favor_home, ema_xg_contra_home,
               ema_xg_favor_away, ema_xg_contra_away
        FROM historial_equipos
    """):
        legacy[r[0]] = {'fh': r[1], 'ch': r[2], 'fa': r[3], 'ca': r[4]}

    # Varianzas históricas (legacy historial_equipos)
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

    # Índice H2H (mismo orden o invertido) — solo de partidos histórico_externo
    h2h_index = defaultdict(list)
    for r in cur.execute("""
        SELECT liga, ht, at, hg, ag, fecha
        FROM partidos_historico_externo
        WHERE has_full_stats = 1 AND hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY fecha ASC
    """):
        liga_h, ht_h, at_h, hg_h, ag_h, fecha_h = r
        ht_n_h = limpiar_texto(ht_h); at_n_h = limpiar_texto(at_h)
        h2h_index[(liga_h, ht_n_h, at_n_h)].append({
            'fecha': fecha_h, 'hg': hg_h, 'ag': ag_h, 'home_real': ht_n_h
        })

    rho_por_liga = {r[0]: r[1] for r in cur.execute("SELECT liga, rho_calculado FROM ligas_stats")}

    print(f"V6 shadow: {len(v6)} equipos | legacy: {len(legacy)} equipos | rho: {len(rho_por_liga)} ligas\n")

    # Iterar partidos liquidados con stats raw (orden cronológico para H2H casual)
    rows = cur.execute("""
        SELECT liga, ht, at, hg, ag, hst, hs, hc, ast, as_, ac, fecha
        FROM partidos_historico_externo
        WHERE has_full_stats = 1
          AND hst IS NOT NULL AND hs IS NOT NULL AND hc IS NOT NULL
          AND hg IS NOT NULL AND ag IS NOT NULL
          AND liga IN ({})
        ORDER BY fecha DESC
        LIMIT 5000
    """.format(','.join(['?'] * len(LIGAS_AUDIT))), LIGAS_AUDIT).fetchall()

    def mes_de(fecha_str):
        try:
            return int(fecha_str[5:7])
        except Exception:
            return 6

    def h2h_features(liga, ht_n, at_n, fecha):
        """avg_g, freq_local (perspectiva del local del partido actual), freq_x sobre H2H previos."""
        prev = []
        for k in [(liga, ht_n, at_n), (liga, at_n, ht_n)]:
            for p in h2h_index.get(k, []):
                if p['fecha'] < fecha:
                    prev.append(p)
        if not prev:
            return 2.7, 0.45, 0.26
        avg_g = sum(p['hg'] + p['ag'] for p in prev) / len(prev)
        n_loc_win = sum(1 for p in prev if (p['home_real'] == ht_n and p['hg'] > p['ag']) or
                                            (p['home_real'] != ht_n and p['ag'] > p['hg']))
        n_x = sum(1 for p in prev if p['hg'] == p['ag'])
        return avg_g, n_loc_win / len(prev), n_x / len(prev)

    print(f"Partidos test: {len(rows)} (últimos 5000 con stats, ligas cobertura alta)\n")

    # Acumuladores por liga
    stats_por_liga = {}

    n_skip_lookup = 0
    for liga, ht, at, hg, ag, hst, hs, hc, ast, as_, ac, fecha in rows:
        ht_n = limpiar_texto(ht)
        at_n = limpiar_texto(at)

        v6_l = v6.get(ht_n)
        v6_v = v6.get(at_n)
        leg_l = legacy.get(ht_n)
        leg_v = legacy.get(at_n)

        # V6 lookup
        if not v6_l or not v6_v or v6_l['fh'] is None or v6_v['fa'] is None or v6_l['ch'] is None or v6_v['ca'] is None:
            n_skip_lookup += 1
            continue

        xg_v6_l = max(0.10, (v6_l['fh'] + v6_v['ca']) / 2.0)
        xg_v6_v = max(0.10, (v6_v['fa'] + v6_l['ch']) / 2.0)

        # Legacy lookup (puede fallar — caer al pool de la liga)
        if leg_l and leg_v and leg_l['fh'] is not None and leg_v['fa'] is not None and leg_l['ch'] is not None and leg_v['ca'] is not None:
            xg_leg_l = max(0.10, (leg_l['fh'] + leg_v['ca']) / 2.0)
            xg_leg_v = max(0.10, (leg_v['fa'] + leg_l['ch']) / 2.0)
        else:
            xg_leg_l, xg_leg_v = None, None

        rho = rho_por_liga.get(liga, -0.04)
        real = real_outcome(hg, ag)

        # V0 legacy (xG legacy + Poisson DC)
        if xg_leg_l is not None:
            p1_0, px_0, p2_0 = probs_poisson_dc(xg_leg_l, xg_leg_v, rho)
            am_0 = argmax_outcome(p1_0, px_0, p2_0)
            hit_0 = 1 if am_0 == real else 0
            br_0 = brier(p1_0, px_0, p2_0, real)
            bias_0 = (xg_leg_l + xg_leg_v) - (hg + ag)
        else:
            am_0 = None
            hit_0 = None
            br_0 = None
            bias_0 = None

        # V6 (xG recal + Poisson DC)
        p1_6, px_6, p2_6 = probs_poisson_dc(xg_v6_l, xg_v6_v, rho)
        am_6 = argmax_outcome(p1_6, px_6, p2_6)
        hit_6 = 1 if am_6 == real else 0
        br_6 = brier(p1_6, px_6, p2_6, real)

        # V7 (xG recal + Skellam)
        p1_7, px_7, p2_7 = probs_skellam(xg_v6_l, xg_v6_v)
        am_7 = argmax_outcome(p1_7, px_7, p2_7)
        hit_7 = 1 if am_7 == real else 0
        br_7 = brier(p1_7, px_7, p2_7, real)

        # V8 (xG recal + Poisson DC con rho boosted)
        rho_v8 = min(rho, 0.0) + rho_v8_delta
        max_abs = 1.0 / max(0.01, xg_v6_l * xg_v6_v)
        if rho_v8 < -max_abs:
            rho_v8 = -max_abs * 0.95
        p1_8, px_8, p2_8 = probs_poisson_dc(xg_v6_l, xg_v6_v, rho_v8)
        am_8 = argmax_outcome(p1_8, px_8, p2_8)
        hit_8 = 1 if am_8 == real else 0
        br_8 = brier(p1_8, px_8, p2_8, real)

        # V9 (V6 + X-multiplier global)
        p1_9, px_9, p2_9 = aplicar_v9_x_mult(p1_6, px_6, p2_6, x_mult_v9)
        am_9 = argmax_outcome(p1_9, px_9, p2_9)
        hit_9 = 1 if am_9 == real else 0
        br_9 = brier(p1_9, px_9, p2_9, real)

        # V10 (V6 + X-multiplier per-liga)
        mult_l = x_mult_v10.get(liga, x_mult_v10.get('global', 1.0))
        p1_10, px_10, p2_10 = aplicar_v9_x_mult(p1_6, px_6, p2_6, mult_l)
        am_10 = argmax_outcome(p1_10, px_10, p2_10)
        hit_10 = 1 if am_10 == real else 0
        br_10 = brier(p1_10, px_10, p2_10, real)

        # V11 (LPM multinomial OLS)
        betas = lpm_v11.get(liga, lpm_v11.get('global'))
        p1_11, px_11, p2_11 = probs_v11_lpm(xg_v6_l, xg_v6_v, betas)
        am_11 = argmax_outcome(p1_11, px_11, p2_11)
        hit_11 = 1 if am_11 == real else 0
        br_11 = brier(p1_11, px_11, p2_11, real)

        # V12 (logistic multinomial con features ampliados)
        h2h_g, h2h_floc, h2h_fx = h2h_features(liga, ht_n, at_n, fecha)
        var_l_eq = var_eq.get(ht_n, {'vfh': 0.5, 'vch': 0.5, 'vfa': 0.5, 'vca': 0.5})
        var_v_eq = var_eq.get(at_n, {'vfh': 0.5, 'vch': 0.5, 'vfa': 0.5, 'vca': 0.5})
        var_loc_pred = (var_l_eq['vfh'] + var_v_eq['vca']) / 2.0
        var_vis_pred = (var_v_eq['vfa'] + var_l_eq['vch']) / 2.0
        feats_v12 = features_v12(xg_v6_l, xg_v6_v, h2h_g, h2h_floc, h2h_fx,
                                  var_loc_pred, var_vis_pred, mes_de(fecha))
        payload_v12 = lr_v12.get(liga, lr_v12.get('global'))
        p1_12, px_12, p2_12 = probs_v12_lr(feats_v12, payload_v12)
        am_12 = argmax_outcome(p1_12, px_12, p2_12)
        hit_12 = 1 if am_12 == real else 0
        br_12 = brier(p1_12, px_12, p2_12, real)

        bias_v6 = (xg_v6_l + xg_v6_v) - (hg + ag)

        s = stats_por_liga.setdefault(liga, {
            'n': 0, 'n_v0': 0,
            'hit_v0': 0, 'hit_v6': 0, 'hit_v7': 0, 'hit_v8': 0,
            'hit_v9': 0, 'hit_v10': 0, 'hit_v11': 0, 'hit_v12': 0,
            'brier_v0': 0.0, 'brier_v6': 0.0, 'brier_v7': 0.0, 'brier_v8': 0.0,
            'brier_v9': 0.0, 'brier_v10': 0.0, 'brier_v11': 0.0, 'brier_v12': 0.0,
            'bias_v0_sum': 0.0, 'bias_v6_sum': 0.0,
            'argmax_v6': {'1': 0, 'X': 0, '2': 0},
            'argmax_v7': {'1': 0, 'X': 0, '2': 0},
            'argmax_v8': {'1': 0, 'X': 0, '2': 0},
            'argmax_v9': {'1': 0, 'X': 0, '2': 0},
            'argmax_v10': {'1': 0, 'X': 0, '2': 0},
            'argmax_v11': {'1': 0, 'X': 0, '2': 0},
            'argmax_v12': {'1': 0, 'X': 0, '2': 0},
            'hit_v8_when_x': 0, 'hit_v9_when_x': 0,
            'hit_v10_when_x': 0, 'hit_v11_when_x': 0, 'hit_v12_when_x': 0,
            'real': {'1': 0, 'X': 0, '2': 0},
            'agree_v6_v7': 0,
        })
        s['n'] += 1
        s['hit_v6'] += hit_6; s['hit_v7'] += hit_7
        s['hit_v8'] += hit_8; s['hit_v9'] += hit_9
        s['hit_v10'] += hit_10; s['hit_v11'] += hit_11
        s['hit_v12'] += hit_12
        s['brier_v6'] += br_6; s['brier_v7'] += br_7
        s['brier_v8'] += br_8; s['brier_v9'] += br_9
        s['brier_v10'] += br_10; s['brier_v11'] += br_11
        s['brier_v12'] += br_12
        s['bias_v6_sum'] += bias_v6
        s['argmax_v6'][am_6] += 1; s['argmax_v7'][am_7] += 1
        s['argmax_v8'][am_8] += 1; s['argmax_v9'][am_9] += 1
        s['argmax_v10'][am_10] += 1; s['argmax_v11'][am_11] += 1
        s['argmax_v12'][am_12] += 1
        s['real'][real] += 1
        s['agree_v6_v7'] += (1 if am_6 == am_7 else 0)
        if am_8 == 'X' and real == 'X': s['hit_v8_when_x'] += 1
        if am_9 == 'X' and real == 'X': s['hit_v9_when_x'] += 1
        if am_10 == 'X' and real == 'X': s['hit_v10_when_x'] += 1
        if am_11 == 'X' and real == 'X': s['hit_v11_when_x'] += 1
        if am_12 == 'X' and real == 'X': s['hit_v12_when_x'] += 1
        if am_0 is not None:
            s['n_v0'] += 1
            s['hit_v0'] += hit_0
            s['brier_v0'] += br_0
            s['bias_v0_sum'] += bias_0

    print(f"Skip por lookup miss V6: {n_skip_lookup}\n")

    # === TABLA PRINCIPAL: hit rate y Brier por liga ===
    archs = ['v6', 'v7', 'v8', 'v9', 'v10', 'v11', 'v12']
    arch_labels = {'v6': 'V6', 'v7': 'V7', 'v8': 'V8', 'v9': 'V9',
                   'v10': 'V10', 'v11': 'V11', 'v12': 'V12'}

    print("=" * 140)
    print(f"COMPARATIVA  V0=legacy+DC  V6=OLS+DC  V7=OLS+Skellam  V8=DC(rho{rho_v8_delta:+.2f})  V9=Xmult{x_mult_v9:.2f}  V10=Xmult-liga  V11=LPM")
    print("=" * 140)
    print(f"{'Liga':<12s} {'N':>5s} " + " ".join(f"{'hit_'+lbl:>7s}" for lbl in ['V0'] + [arch_labels[a] for a in archs]))
    print("-" * 140)

    tot = {'n': 0, 'n_v0': 0, 'hit_v0': 0, 'brier_v0': 0.0, 'bias_v0_sum': 0.0, 'bias_v6_sum': 0.0, 'agree_v6_v7': 0}
    for a in archs:
        tot[f'hit_{a}'] = 0
        tot[f'brier_{a}'] = 0.0

    for liga in sorted(stats_por_liga.keys()):
        s = stats_por_liga[liga]
        n = s['n']
        n_v0 = s['n_v0']
        hr_v0 = s['hit_v0'] / n_v0 if n_v0 else 0
        line = f"{liga:<12s} {n:>5d} {hr_v0:>7.3f}"
        for a in archs:
            line += f" {s[f'hit_{a}']/n:>7.3f}"
        print(line)
        for k in tot:
            tot[k] += s[k] if k in s else 0

    print("-" * 140)
    n = tot['n']; n0 = tot['n_v0']
    line = f"{'TOTAL':<12s} {n:>5d} {tot['hit_v0']/n0 if n0 else 0:>7.3f}"
    for a in archs:
        line += f" {tot[f'hit_{a}']/n:>7.3f}"
    print(line)

    # Brier por arquitectura
    print(f"\n{'BRIER':<12s} {'N':>5s} {'br_V0':>7s} " + " ".join(f"{'br_'+arch_labels[a]:>7s}" for a in archs))
    print("-" * 140)
    n_tot = tot['n']
    for liga in sorted(stats_por_liga.keys()):
        s = stats_por_liga[liga]
        n_liga = s['n']; n_v0_liga = s['n_v0']
        line = f"{liga:<12s} {n_liga:>5d} {s['brier_v0']/n_v0_liga if n_v0_liga else 0:>7.4f}"
        for a in archs:
            line += f" {s[f'brier_{a}']/n_liga:>7.4f}"
        print(line)
    print("-" * 140)
    line = f"{'TOTAL':<12s} {n_tot:>5d} {tot['brier_v0']/n0 if n0 else 0:>7.4f}"
    for a in archs:
        line += f" {tot[f'brier_{a}']/n_tot:>7.4f}"
    print(line)

    # === DISTRIBUCION ARGMAX ===
    print("\n=== Distribucion argmax 1X2 (% picks globales) ===")
    am_tot = {a: {'1': 0, 'X': 0, '2': 0} for a in archs}
    real_tot = {'1': 0, 'X': 0, '2': 0}
    for s in stats_por_liga.values():
        for k in '1X2':
            for a in archs:
                am_tot[a][k] += s[f'argmax_{a}'][k]
            real_tot[k] += s['real'][k]
    n = sum(real_tot.values())
    print(f"{'arch':<14s} {'1':>8s} {'X':>8s} {'2':>8s}")
    desc = {'v6': 'V6 OLS+DC', 'v7': 'V7 Skellam', 'v8': 'V8 rho_boost',
            'v9': 'V9 x_mult', 'v10': 'V10 x_mult/liga', 'v11': 'V11 LPM',
            'v12': 'V12 LR+H2H'}
    for a in archs:
        am = am_tot[a]
        print(f"{desc[a]:<14s} {am['1']/n:>8.3f} {am['X']/n:>8.3f} {am['2']/n:>8.3f}")
    print(f"{'real':<14s} {real_tot['1']/n:>8.3f} {real_tot['X']/n:>8.3f} {real_tot['2']/n:>8.3f}")

    # === PRECISION DE PICKS X ===
    print("\n=== Precision argmax=X (hit cuando se pickea X) ===")
    base_x = real_tot['X'] / n
    print(f"{'arch':<14s} {'N_pickX':>9s} {'%picks':>8s} {'precision':>10s}  (real X = {base_x:.1%})")
    print("-" * 70)
    for a, key_n, key_h in [('v8', 'argmax_v8', 'hit_v8_when_x'),
                             ('v9', 'argmax_v9', 'hit_v9_when_x'),
                             ('v10', 'argmax_v10', 'hit_v10_when_x'),
                             ('v11', 'argmax_v11', 'hit_v11_when_x'),
                             ('v12', 'argmax_v12', 'hit_v12_when_x')]:
        nx = sum(s[key_n]['X'] for s in stats_por_liga.values())
        hx = sum(s[key_h] for s in stats_por_liga.values())
        prec = hx / nx if nx else 0
        print(f"{desc[a]:<14s} {nx:>9d} {nx/n*100:>7.1f}% {prec:>10.3f}")

    # === DESGLOSE V11/V12 POR LIGA (precision X) ===
    print("\n=== V11 LPM y V12 LR+H2H por liga: precision X ===")
    print(f"{'Liga':<12s} {'N':>5s} {'V11_X':>7s} {'V11_%':>6s} {'V11_pr':>7s} {'V12_X':>7s} {'V12_%':>6s} {'V12_pr':>7s}")
    for liga, s in sorted(stats_por_liga.items()):
        n11 = s['argmax_v11']['X']; h11 = s['hit_v11_when_x']
        p11 = h11/n11 if n11 else 0
        n12 = s['argmax_v12']['X']; h12 = s['hit_v12_when_x']
        p12 = h12/n12 if n12 else 0
        print(f"{liga:<12s} {s['n']:>5d} {n11:>7d} {n11/s['n']*100:>5.1f}% {p11:>7.3f} "
              f"{n12:>7d} {n12/s['n']*100:>5.1f}% {p12:>7.3f}")

    # Notas finales
    print("\n=== INTERPRETACIÓN ===")
    print("- V6 y V7 usan EXACTAMENTE el mismo xG (OLS recal). Diferencia: V6=Poisson+DC tau, V7=Skellam (sin tau).")
    print("- bias_V6 == bias_V7 (mismo xG); por eso solo se reporta bias_V6.")
    print("- agree_v6_v7 = % partidos donde V6 y V7 eligen el mismo argmax (alto = distribucion casi indistinguible).")
    print("- Brier menor = mejor calibración. Hit rate alto = mejor argmax.")
    print("- AVISO: EMAs incluyen al partido evaluado (leak comparativo, no out-of-sample).")
    print("         Todas las arquitecturas sufren mismo leak = comparacion valida.")

    con.close()


if __name__ == "__main__":
    main()

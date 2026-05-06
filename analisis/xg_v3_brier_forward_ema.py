"""
Brier PREDICTOR real sobre EMAs forward (no xG del partido en curso).

xG_l_pre = EMA forward-strict de xG histórico equipo local PRE-partido
xG_v_pre = idem visita
P(1X2) = Poisson(xG_l_pre, xG_v_pre) marginalizada
Brier pre-match comparable con Mercado.

Comparar: V_custom_forward, V_v3_forward, Mercado.

WARMUP=5 partidos, ALFA=0.10 EMA.
"""
import sqlite3, json, math
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')

ALFA = 0.10
WARMUP = 5
THETA = 0.20  # hibrido xg + goles


def poisson_1x2_probs(lambda_l, lambda_v, max_goals=8):
    p1, px, p2 = 0, 0, 0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p_ij = poisson.pmf(i, lambda_l) * poisson.pmf(j, lambda_v)
            if i > j:
                p1 += p_ij
            elif i == j:
                px += p_ij
            else:
                p2 += p_ij
    return p1, px, p2


def poisson_o25(lambda_total):
    return 1 - sum(poisson.pmf(k, lambda_total) for k in range(3))


def brier_1x2(preds, truths):
    sse = 0
    for (p1, px, p2), t in zip(preds, truths):
        target = (1, 0, 0) if t == '1' else ((0, 1, 0) if t == 'X' else (0, 0, 1))
        sse += (p1 - target[0]) ** 2 + (px - target[1]) ** 2 + (p2 - target[2]) ** 2
    return sse / len(preds)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar partidos cronológicamente con cuotas
    rows = cur.execute('''
        SELECT s.liga, s.fecha, s.ht, s.at, s.hg, s.ag,
               s.xg_shotmap_l, s.xg_shotmap_v,
               s.xg_v3_l, s.xg_v3_v,
               c.cuota_1, c.cuota_x, c.cuota_2, c.cuota_o25, c.cuota_u25
        FROM sofascore_match_features s
        JOIN cuotas_historicas_fdco c
          ON s.liga = c.liga AND s.fecha = c.fecha
        WHERE s.error IS NULL AND s.xg_v3_l IS NOT NULL
          AND s.hg IS NOT NULL AND s.ag IS NOT NULL
          AND c.cuota_1 IS NOT NULL
        ORDER BY s.fecha ASC
    ''').fetchall()
    print(f'Partidos con SOFA + cuotas: {len(rows)}')

    # Build forward EMA per equipo, both versions
    state_custom = defaultdict(lambda: {'fav_h': 1.4, 'con_h': 1.4, 'p_h': 0,
                                         'fav_a': 1.4, 'con_a': 1.4, 'p_a': 0})
    state_v3 = defaultdict(lambda: {'fav_h': 1.4, 'con_h': 1.4, 'p_h': 0,
                                     'fav_a': 1.4, 'con_a': 1.4, 'p_a': 0})

    truths_1x2 = []
    truths_o25 = []
    preds_v_custom = []
    preds_v_v3 = []
    preds_mkt = []
    preds_v_custom_o25 = []
    preds_v_v3_o25 = []
    preds_mkt_o25 = []

    n_post_warmup = 0

    for r in rows:
        liga, fecha, ht, at, hg, ag = r[0], r[1], r[2], r[3], r[4], r[5]
        xg_c_l, xg_c_v, xg_v3_l, xg_v3_v = r[6], r[7], r[8], r[9]
        c1, cx, c2, co25, cu25 = r[10], r[11], r[12], r[13], r[14]

        key_l = (ht, liga)
        key_v = (at, liga)
        s_l_c = state_custom[key_l]
        s_v_c = state_custom[key_v]
        s_l_3 = state_v3[key_l]
        s_v_3 = state_v3[key_v]

        # Si AMBOS equipos tienen warmup → predecir
        if (s_l_c['p_h'] >= WARMUP and s_v_c['p_a'] >= WARMUP
                and s_l_3['p_h'] >= WARMUP and s_v_3['p_a'] >= WARMUP):
            # xG predicción pre-match: Bayesian update with EMA fav home + EMA contra away
            # lambda_l = (ema_fav_l_home + ema_contra_v_away) / 2
            # lambda_v = (ema_fav_v_away + ema_contra_l_home) / 2
            lam_l_c = (s_l_c['fav_h'] + s_v_c['con_a']) / 2
            lam_v_c = (s_v_c['fav_a'] + s_l_c['con_h']) / 2
            lam_l_3 = (s_l_3['fav_h'] + s_v_3['con_a']) / 2
            lam_v_3 = (s_v_3['fav_a'] + s_l_3['con_h']) / 2

            res_1x2 = '1' if hg > ag else ('2' if ag > hg else 'X')
            res_o25 = 1 if (hg + ag) > 2 else 0
            truths_1x2.append(res_1x2)
            truths_o25.append(res_o25)

            preds_v_custom.append(poisson_1x2_probs(lam_l_c, lam_v_c))
            preds_v_v3.append(poisson_1x2_probs(lam_l_3, lam_v_3))
            preds_v_custom_o25.append(poisson_o25(lam_l_c + lam_v_c))
            preds_v_v3_o25.append(poisson_o25(lam_l_3 + lam_v_3))

            # Mercado
            p1_raw = 1 / c1; px_raw = 1 / cx; p2_raw = 1 / c2
            over = p1_raw + px_raw + p2_raw
            preds_mkt.append((p1_raw / over, px_raw / over, p2_raw / over))
            if co25 and cu25:
                po_raw = 1 / co25; pu_raw = 1 / cu25
                ou_over = po_raw + pu_raw
                preds_mkt_o25.append(po_raw / ou_over)
            else:
                preds_mkt_o25.append(None)

            n_post_warmup += 1

        # UPDATE EMA con partido actual (custom + v3)
        # xG_final = θ·xg + (1-θ)·goles
        xg_final_c_l = THETA * (xg_c_l or 0) + (1 - THETA) * hg
        xg_final_c_v = THETA * (xg_c_v or 0) + (1 - THETA) * ag
        xg_final_3_l = THETA * (xg_v3_l or 0) + (1 - THETA) * hg
        xg_final_3_v = THETA * (xg_v3_v or 0) + (1 - THETA) * ag

        # Update local home perspective
        s_l_c['fav_h'] = ALFA * xg_final_c_l + (1 - ALFA) * s_l_c['fav_h']
        s_l_c['con_h'] = ALFA * xg_final_c_v + (1 - ALFA) * s_l_c['con_h']
        s_l_c['p_h'] += 1
        s_l_3['fav_h'] = ALFA * xg_final_3_l + (1 - ALFA) * s_l_3['fav_h']
        s_l_3['con_h'] = ALFA * xg_final_3_v + (1 - ALFA) * s_l_3['con_h']
        s_l_3['p_h'] += 1

        # Update visita away perspective
        s_v_c['fav_a'] = ALFA * xg_final_c_v + (1 - ALFA) * s_v_c['fav_a']
        s_v_c['con_a'] = ALFA * xg_final_c_l + (1 - ALFA) * s_v_c['con_a']
        s_v_c['p_a'] += 1
        s_v_3['fav_a'] = ALFA * xg_final_3_v + (1 - ALFA) * s_v_3['fav_a']
        s_v_3['con_a'] = ALFA * xg_final_3_l + (1 - ALFA) * s_v_3['con_a']
        s_v_3['p_a'] += 1

    print(f'Post-warmup eventos: {n_post_warmup}')

    if n_post_warmup < 30:
        print('N insuficiente post-warmup')
        return

    b_custom = brier_1x2(preds_v_custom, truths_1x2)
    b_v3 = brier_1x2(preds_v_v3, truths_1x2)
    b_mkt = brier_1x2(preds_mkt, truths_1x2)

    b_custom_o25 = np.mean([(p - t) ** 2 for p, t in zip(preds_v_custom_o25, truths_o25)])
    b_v3_o25 = np.mean([(p - t) ** 2 for p, t in zip(preds_v_v3_o25, truths_o25)])
    valid_mkt = [(p, t) for p, t in zip(preds_mkt_o25, truths_o25) if p is not None]
    b_mkt_o25 = np.mean([(p - t) ** 2 for p, t in valid_mkt])

    print()
    print(f'=== Brier PREDICTOR (forward EMA, pre-match, N={n_post_warmup}) ===')
    print(f'{"Modelo":<12s} {"Brier_1X2":>12s} {"vs_Mkt":>10s} {"Brier_O25":>12s} {"vs_Mkt":>10s}')
    print(f'{"V_custom":<12s} {b_custom:>12.4f} {b_custom-b_mkt:>+10.4f} {b_custom_o25:>12.4f} {b_custom_o25-b_mkt_o25:>+10.4f}')
    print(f'{"V_v3":<12s} {b_v3:>12.4f} {b_v3-b_mkt:>+10.4f} {b_v3_o25:>12.4f} {b_v3_o25-b_mkt_o25:>+10.4f}')
    print(f'{"Mercado":<12s} {b_mkt:>12.4f} {0:>+10.4f} {b_mkt_o25:>12.4f} {0:>+10.4f}')

    print()
    print(f'=== Mejora V3 vs V_custom forward ===')
    print(f'  Brier_1X2: {b_v3-b_custom:+.4f} ({100*(b_v3-b_custom)/b_custom:+.1f}%)')
    print(f'  Brier_O25: {b_v3_o25-b_custom_o25:+.4f} ({100*(b_v3_o25-b_custom_o25)/b_custom_o25:+.1f}%)')

    print()
    print(f'=== Gap vs mercado (referencia eficiencia) ===')
    gap_v3 = (b_v3 - b_mkt) / b_mkt * 100
    gap_custom = (b_custom - b_mkt) / b_mkt * 100
    print(f'  V_custom Brier_1X2 vs Mkt: {gap_custom:+.1f}% (peor que mkt)')
    print(f'  V_v3     Brier_1X2 vs Mkt: {gap_v3:+.1f}%')
    print(f'  Mejora gap V3 sobre custom: {gap_v3 - gap_custom:+.1f}pp')

    con.close()


if __name__ == '__main__':
    main()

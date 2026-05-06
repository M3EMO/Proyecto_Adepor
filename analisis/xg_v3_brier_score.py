"""
Brier score V_custom vs V_v3 vs Mercado (P_implícita cuotas).

Brier 1X2 multiclass:
  prob_pick = Poisson(lambda_xg_l, lambda_xg_v) marginalizada (independiente sin DC)
  Brier_1X2 = mean( ||prob_vector - one_hot(outcome)||² )

Brier O25 binario:
  P(over_2.5) = 1 - Poisson_CDF(2, lambda_l + lambda_v)
  Brier_O25 = mean( (P_over - actual_over)² )

Comparar:
  - V_custom (xg_shotmap)
  - V_v3 (xg_v3 híbrido SOFA xgot + custom fallback)
  - Baseline V0 productivo (xg_calc β·SOT + ...)
  - Mercado (P_implícita de cuotas, ground truth de calibración)
"""
import sqlite3, json, math
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')


def poisson_1x2_probs(lambda_l, lambda_v, max_goals=8):
    """Probabilidad 1X2 con Poisson independiente."""
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
    """P(over_2.5) sumando Poisson over total goals."""
    return 1 - sum(poisson.pmf(k, lambda_total) for k in range(3))


def brier_1x2(preds, truths):
    """preds: list of (p1, px, p2). truths: list of '1', 'X', '2'."""
    sse = 0
    for (p1, px, p2), t in zip(preds, truths):
        target = (1, 0, 0) if t == '1' else ((0, 1, 0) if t == 'X' else (0, 0, 1))
        sse += (p1 - target[0]) ** 2 + (px - target[1]) ** 2 + (p2 - target[2]) ** 2
    return sse / len(preds)


def brier_binario(preds, truths):
    return np.mean([(p - t) ** 2 for p, t in zip(preds, truths)])


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar V_custom + V_v3 + cuotas
    rows = cur.execute('''
        SELECT s.liga, s.fecha, s.ht, s.at, s.hg, s.ag,
               s.xg_shotmap_l, s.xg_shotmap_v,
               s.xg_v3_l, s.xg_v3_v,
               s.shots_total_l, s.shots_total_v,
               c.cuota_1, c.cuota_x, c.cuota_2, c.cuota_o25, c.cuota_u25
        FROM sofascore_match_features s
        JOIN cuotas_historicas_fdco c
          ON s.liga = c.liga AND s.fecha = c.fecha
        WHERE s.error IS NULL AND s.xg_v3_l IS NOT NULL
          AND s.hg IS NOT NULL AND s.ag IS NOT NULL
          AND c.cuota_1 IS NOT NULL AND c.cuota_x IS NOT NULL AND c.cuota_2 IS NOT NULL
    ''').fetchall()
    print(f'Partidos con cuotas matched: {len(rows)}')

    if len(rows) == 0:
        # Fallback: solo Brier sin mercado
        rows_no_mkt = cur.execute('''
            SELECT liga, fecha, ht, at, hg, ag,
                   xg_shotmap_l, xg_shotmap_v, xg_v3_l, xg_v3_v
            FROM sofascore_match_features
            WHERE error IS NULL AND xg_v3_l IS NOT NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
        ''').fetchall()
        print(f'Partidos sin cuotas (Brier solo modelos): {len(rows_no_mkt)}')

        truths_1x2 = []
        truths_o25 = []
        preds_v_custom = []
        preds_v3 = []
        preds_v_custom_o25 = []
        preds_v3_o25 = []

        for r in rows_no_mkt:
            liga, fecha, ht, at, hg, ag, xg_c_l, xg_c_v, xg_v3_l, xg_v3_v = r
            res_1x2 = '1' if hg > ag else ('2' if ag > hg else 'X')
            res_o25 = 1 if (hg + ag) > 2 else 0
            truths_1x2.append(res_1x2)
            truths_o25.append(res_o25)

            # V_custom probs
            p1c, pxc, p2c = poisson_1x2_probs(xg_c_l, xg_c_v)
            preds_v_custom.append((p1c, pxc, p2c))
            preds_v_custom_o25.append(poisson_o25(xg_c_l + xg_c_v))

            # V_v3 probs
            p1v, pxv, p2v = poisson_1x2_probs(xg_v3_l, xg_v3_v)
            preds_v3.append((p1v, pxv, p2v))
            preds_v3_o25.append(poisson_o25(xg_v3_l + xg_v3_v))

        b_custom = brier_1x2(preds_v_custom, truths_1x2)
        b_v3 = brier_1x2(preds_v3, truths_1x2)
        b_custom_o25 = brier_binario(preds_v_custom_o25, truths_o25)
        b_v3_o25 = brier_binario(preds_v3_o25, truths_o25)

        print()
        print(f'=== Brier sin mercado (N={len(rows_no_mkt)}) ===')
        print(f'{"Modelo":<12s} {"Brier_1X2":>12s} {"Brier_O25":>12s}')
        print(f'{"V_custom":<12s} {b_custom:>12.4f} {b_custom_o25:>12.4f}')
        print(f'{"V_v3":<12s} {b_v3:>12.4f} {b_v3_o25:>12.4f}')
        print(f'{"Mejora V3":<12s} {b_v3-b_custom:>+12.4f} {b_v3_o25-b_custom_o25:>+12.4f}')
        return

    # Con mercado
    truths_1x2 = []
    truths_o25 = []
    preds_v_custom = []
    preds_v3 = []
    preds_mkt = []
    preds_v_custom_o25 = []
    preds_v3_o25 = []
    preds_mkt_o25 = []

    for r in rows:
        liga, fecha, ht, at, hg, ag = r[0], r[1], r[2], r[3], r[4], r[5]
        xg_c_l, xg_c_v, xg_v3_l, xg_v3_v = r[6], r[7], r[8], r[9]
        c1, cx, c2, co25, cu25 = r[12], r[13], r[14], r[15], r[16]

        res_1x2 = '1' if hg > ag else ('2' if ag > hg else 'X')
        res_o25 = 1 if (hg + ag) > 2 else 0
        truths_1x2.append(res_1x2)
        truths_o25.append(res_o25)

        # V_custom
        p1c, pxc, p2c = poisson_1x2_probs(xg_c_l, xg_c_v)
        preds_v_custom.append((p1c, pxc, p2c))
        preds_v_custom_o25.append(poisson_o25(xg_c_l + xg_c_v))

        # V_v3
        p1v, pxv, p2v = poisson_1x2_probs(xg_v3_l, xg_v3_v)
        preds_v3.append((p1v, pxv, p2v))
        preds_v3_o25.append(poisson_o25(xg_v3_l + xg_v3_v))

        # Mercado: P_implícita normalized
        p1_raw = 1 / c1
        px_raw = 1 / cx
        p2_raw = 1 / c2
        over = p1_raw + px_raw + p2_raw
        preds_mkt.append((p1_raw / over, px_raw / over, p2_raw / over))

        # Mercado O25
        if co25 and cu25:
            po_raw = 1 / co25
            pu_raw = 1 / cu25
            ou_over = po_raw + pu_raw
            preds_mkt_o25.append(po_raw / ou_over)
        else:
            preds_mkt_o25.append(None)

    b_custom = brier_1x2(preds_v_custom, truths_1x2)
    b_v3 = brier_1x2(preds_v3, truths_1x2)
    b_mkt = brier_1x2(preds_mkt, truths_1x2)

    b_custom_o25 = brier_binario(preds_v_custom_o25, truths_o25)
    b_v3_o25 = brier_binario(preds_v3_o25, truths_o25)
    valid_mkt_o25 = [(p, t) for p, t in zip(preds_mkt_o25, truths_o25) if p is not None]
    b_mkt_o25 = brier_binario([p for p, _ in valid_mkt_o25], [t for _, t in valid_mkt_o25])

    print()
    print(f'=== Brier scores (N={len(rows)} con cuotas) ===')
    print(f'{"Modelo":<12s} {"Brier_1X2":>12s} {"vs_Mkt":>10s} {"Brier_O25":>12s} {"vs_Mkt":>10s}')
    print(f'{"V_custom":<12s} {b_custom:>12.4f} {b_custom-b_mkt:>+10.4f} {b_custom_o25:>12.4f} {b_custom_o25-b_mkt_o25:>+10.4f}')
    print(f'{"V_v3":<12s} {b_v3:>12.4f} {b_v3-b_mkt:>+10.4f} {b_v3_o25:>12.4f} {b_v3_o25-b_mkt_o25:>+10.4f}')
    print(f'{"Mercado":<12s} {b_mkt:>12.4f} {0:>+10.4f} {b_mkt_o25:>12.4f} {0:>+10.4f}')

    print()
    print(f'=== Mejora V3 vs V_custom ===')
    print(f'  Brier_1X2: {b_v3-b_custom:+.4f} ({100*(b_v3-b_custom)/b_custom:+.1f}%)')
    print(f'  Brier_O25: {b_v3_o25-b_custom_o25:+.4f} ({100*(b_v3_o25-b_custom_o25)/b_custom_o25:+.1f}%)')

    # Per liga
    print()
    print('=== Brier por liga (V_custom vs V_v3) ===')
    by_liga = defaultdict(lambda: {'preds_c': [], 'preds_3': [], 'truths_1': [], 'truths_o': [], 'preds_c_o25': [], 'preds_3_o25': []})
    for i, r in enumerate(rows):
        liga = r[0]
        by_liga[liga]['preds_c'].append(preds_v_custom[i])
        by_liga[liga]['preds_3'].append(preds_v3[i])
        by_liga[liga]['truths_1'].append(truths_1x2[i])
        by_liga[liga]['truths_o'].append(truths_o25[i])
        by_liga[liga]['preds_c_o25'].append(preds_v_custom_o25[i])
        by_liga[liga]['preds_3_o25'].append(preds_v3_o25[i])

    print(f'{"Liga":<14s} {"N":>4s} {"B1X2_c":>9s} {"B1X2_v3":>9s} {"D":>+8s} {"BOu_c":>8s} {"BOu_v3":>8s} {"D":>+8s}')
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l]['preds_c'])):
        b = by_liga[liga]
        if len(b['preds_c']) < 5:
            continue
        bc1 = brier_1x2(b['preds_c'], b['truths_1'])
        bv1 = brier_1x2(b['preds_3'], b['truths_1'])
        bco = brier_binario(b['preds_c_o25'], b['truths_o'])
        bvo = brier_binario(b['preds_3_o25'], b['truths_o'])
        print(f'{liga:<14s} {len(b["preds_c"]):>4d} {bc1:>9.4f} {bv1:>9.4f} {bv1-bc1:>+8.4f} {bco:>8.4f} {bvo:>8.4f} {bvo-bco:>+8.4f}')

    con.close()


if __name__ == '__main__':
    main()

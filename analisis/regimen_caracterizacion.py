"""adepor-bix Fase 1 predictor regimen: caracterizacion cuantitativa 2022/2023/2024.

Para cada (liga, temp) calcula:
  Frecuenciales:
    n_partidos, avg_goles_total, std_goles_total, avg_goles_local, avg_goles_visita
    pct_local_win, pct_empate, pct_visita_win, home_advantage
  Estilisticas (cuando ema_l_* disponible en historial_equipos_stats):
    avg_corners, avg_shots, avg_sots, avg_pos, avg_pass_pct,
    avg_yellow, avg_red, avg_fouls
  Calibracion motor (cuando OOS disponible):
    brier_v0_avg, brier_v0_std, yield_v0_unitario
  Mercado:
    pinnacle_vig_avg, edge_motor

Output:
  - tabla comparativa por liga x temp (printeada)
  - tabla agregada por temp (sin distincion liga)
  - analisis/regimen_caracterizacion.json
  - identificacion TOP-3 features que separan 2023 vs 2022/2024 (welch t-test).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "regimen_caracterizacion.json"

TEMPS = [2022, 2023, 2024]


def cargar_partidos(con):
    """Cargar partidos liquidados (con outcome) de partidos_historico_externo +
    JOIN con cuotas Pinnacle si disponibles en predicciones_oos_con_features."""
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha, phe.ht, phe.at,
               phe.hg, phe.ag, phe.hst, phe.ast, phe.hs, phe.as_,
               phe.hc, phe.ac, phe.hf, phe.af, phe.hy, phe.ay, phe.hr, phe.ar,
               (SELECT json_object(
                    'prob_1', prob_1, 'prob_x', prob_x, 'prob_2', prob_2,
                    'psch', psch, 'pscd', pscd, 'psca', psca, 'outcome', outcome)
                FROM predicciones_oos_con_features
                WHERE liga=phe.liga
                  AND substr(fecha,1,10) = substr(phe.fecha,1,10)
                  AND local=phe.ht AND visita=phe.at
                LIMIT 1) AS oos_json
        FROM partidos_historico_externo phe
        WHERE phe.hg IS NOT NULL AND phe.ag IS NOT NULL
          AND phe.temp IN (2022, 2023, 2024)
    """
    rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["oos"] = json.loads(d["oos_json"]) if d["oos_json"] else None
        out.append(d)
    return out


def brier_3way(p1, px, p2, outcome):
    t = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(outcome)
    if t is None: return None
    return (p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2


def kelly_fraction(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05: return None
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(opts, key=lambda x: x[1])
    if not cuota or cuota <= 1.0 or prob * cuota - 1 < 0.03: return None
    stake = kelly_fraction(prob, cuota)
    if stake <= 0: return None
    return {"stake": stake,
            "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def calcular_features(partidos):
    """Aggregar features sobre lista de partidos (subset liga,temp o agregado)."""
    if not partidos:
        return None
    n = len(partidos)
    goles_l = [p["hg"] for p in partidos]
    goles_v = [p["ag"] for p in partidos]
    goles_total = [g_l + g_v for g_l, g_v in zip(goles_l, goles_v)]
    n_local = sum(1 for p in partidos if p["hg"] > p["ag"])
    n_empate = sum(1 for p in partidos if p["hg"] == p["ag"])
    n_visita = sum(1 for p in partidos if p["hg"] < p["ag"])

    # Estadisticas estilisticas (donde stats completas)
    corners_l = [p["hc"] for p in partidos if p["hc"] is not None]
    corners_v = [p["ac"] for p in partidos if p["ac"] is not None]
    shots_l = [p["hs"] for p in partidos if p["hs"] is not None]
    shots_v = [p["as_"] for p in partidos if p["as_"] is not None]
    sots_l = [p["hst"] for p in partidos if p["hst"] is not None]
    sots_v = [p["ast"] for p in partidos if p["ast"] is not None]
    yellow_l = [p["hy"] for p in partidos if p["hy"] is not None]
    yellow_v = [p["ay"] for p in partidos if p["ay"] is not None]
    red_l = [p["hr"] for p in partidos if p["hr"] is not None]
    red_v = [p["ar"] for p in partidos if p["ar"] is not None]
    fouls_l = [p["hf"] for p in partidos if p["hf"] is not None]
    fouls_v = [p["af"] for p in partidos if p["af"] is not None]

    # Mercado + motor (sobre subset OOS)
    oos_partidos = [p for p in partidos if p.get("oos")]
    n_oos = len(oos_partidos)
    briers = []
    pinnacle_vigs = []
    edges_motor = []
    picks = []
    for p in oos_partidos:
        o = p["oos"]
        b = brier_3way(o["prob_1"], o["prob_x"], o["prob_2"], o["outcome"])
        if b is not None: briers.append(b)
        # Vig Pinnacle
        try:
            vig = (1/o["psch"] + 1/o["pscd"] + 1/o["psca"]) - 1
            pinnacle_vigs.append(vig)
        except Exception: pass
        # Edge motor (prob_motor - prob_implicita_pinnacle) por outcome
        try:
            implied_1 = 1 / o["psch"]
            implied_x = 1 / o["pscd"]
            implied_2 = 1 / o["psca"]
            sum_imp = implied_1 + implied_x + implied_2
            implied_1 /= sum_imp; implied_x /= sum_imp; implied_2 /= sum_imp
            edge = abs(o["prob_1"] - implied_1) + abs(o["prob_x"] - implied_x) + abs(o["prob_2"] - implied_2)
            edges_motor.append(edge)
        except Exception: pass
        # Pick V0 audit
        pick = evaluar_pick(o["prob_1"], o["prob_x"], o["prob_2"],
                              o["psch"], o["pscd"], o["psca"], o["outcome"])
        picks.append(pick)

    # Yield V0 unitario
    yld_v0 = None
    n_apost_v0 = 0
    if picks:
        n_apost_v0 = sum(1 for p in picks if p)
        sum_pl = sum(p["profit"] for p in picks if p)
        sum_stake = sum(p["stake"] for p in picks if p)
        yld_v0 = (sum_pl / sum_stake * 100) if sum_stake > 0 else None

    f = {
        "n_partidos": n,
        # Frecuenciales
        "avg_goles_total": round(float(np.mean(goles_total)), 3),
        "std_goles_total": round(float(np.std(goles_total)), 3),
        "avg_goles_local": round(float(np.mean(goles_l)), 3),
        "avg_goles_visita": round(float(np.mean(goles_v)), 3),
        "pct_local_win": round(n_local / n, 4),
        "pct_empate": round(n_empate / n, 4),
        "pct_visita_win": round(n_visita / n, 4),
        "home_advantage": round((n_local / n) - 0.45, 4),
        # Estilisticas (avg jaja, sumamos local+visita)
        "avg_corners_partido": round((np.mean(corners_l) + np.mean(corners_v)), 3) if corners_l and corners_v else None,
        "avg_shots_partido": round((np.mean(shots_l) + np.mean(shots_v)), 3) if shots_l and shots_v else None,
        "avg_sots_partido": round((np.mean(sots_l) + np.mean(sots_v)), 3) if sots_l and sots_v else None,
        "avg_yellow_partido": round((np.mean(yellow_l) + np.mean(yellow_v)), 3) if yellow_l and yellow_v else None,
        "avg_red_partido": round((np.mean(red_l) + np.mean(red_v)), 4) if red_l and red_v else None,
        "avg_fouls_partido": round((np.mean(fouls_l) + np.mean(fouls_v)), 3) if fouls_l and fouls_v else None,
        # Calibracion + mercado
        "n_oos": n_oos,
        "brier_v0_avg": round(float(np.mean(briers)), 4) if briers else None,
        "brier_v0_std": round(float(np.std(briers)), 4) if briers else None,
        "pinnacle_vig_avg": round(float(np.mean(pinnacle_vigs)) * 100, 3) if pinnacle_vigs else None,
        "edge_motor_avg": round(float(np.mean(edges_motor)), 4) if edges_motor else None,
        "n_apost_v0": n_apost_v0,
        "yield_v0_unitario": round(yld_v0, 2) if yld_v0 is not None else None,
    }
    return f


def welch_t_test(a, b):
    """Welch's t-test (no asume varianzas iguales). Devuelve (t, p_aprox)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or len(b) < 2: return None, None
    mean_a, mean_b = a.mean(), b.mean()
    var_a, var_b = a.var(ddof=1), b.var(ddof=1)
    se = math.sqrt(var_a / len(a) + var_b / len(b))
    if se == 0: return None, None
    t = (mean_a - mean_b) / se
    df = (var_a / len(a) + var_b / len(b)) ** 2 / (
        (var_a / len(a)) ** 2 / (len(a) - 1) + (var_b / len(b)) ** 2 / (len(b) - 1)
    )
    # P-value aprox via formula de Wilson-Hilferty para Student's t -> Normal
    # Para |t| < 5 con df > 30, normal approx OK
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))  # 2-tailed normal approx
    return float(t), float(p)


def main():
    con = sqlite3.connect(DB)
    print("Cargando partidos historicos 2022-2024...")
    partidos = cargar_partidos(con)
    print(f"  N partidos liquidados: {len(partidos):,}")

    # Por (liga, temp)
    by_liga_temp = defaultdict(list)
    by_temp = defaultdict(list)
    for p in partidos:
        by_liga_temp[(p["liga"], p["temp"])].append(p)
        by_temp[p["temp"]].append(p)

    # Caracterizacion por liga x temp
    print("\n=== FEATURES POR (liga, temp) ===")
    print(f"{'liga':<14} {'temp':<5} {'N':>4} {'avg_g':>6} {'%LW':>5} {'%X':>5} {'%VW':>5} {'%R':>6} {'BS_v0':>7} {'Y_v0%':>8} {'vig%':>6}")
    feats_por_liga_temp = {}
    for liga in sorted(set(p["liga"] for p in partidos)):
        feats_por_liga_temp[liga] = {}
        for temp in TEMPS:
            sub = by_liga_temp.get((liga, temp), [])
            if not sub: continue
            f = calcular_features(sub)
            if not f: continue
            feats_por_liga_temp[liga][temp] = f
            avg_red = f.get("avg_red_partido", 0) or 0
            print(f"{liga:<14} {temp:<5} {f['n_partidos']:>4} "
                  f"{f['avg_goles_total']:>6.2f} {f['pct_local_win']*100:>4.1f}% "
                  f"{f['pct_empate']*100:>4.1f}% {f['pct_visita_win']*100:>4.1f}% "
                  f"{avg_red:>6.3f} "
                  f"{f.get('brier_v0_avg', '-') or '-':>7} "
                  f"{f.get('yield_v0_unitario', '-') or '-':>8} "
                  f"{f.get('pinnacle_vig_avg', '-') or '-':>6}")

    # Caracterizacion AGREGADA por temp (todos los partidos juntos)
    print("\n=== FEATURES AGREGADAS POR TEMP (todas las ligas) ===")
    print(f"{'temp':<5} {'N':>5} {'avg_g':>6} {'%LW':>5} {'%X':>5} {'%VW':>5} {'%R':>6} {'BS_v0':>7} {'Y_v0%':>8} {'vig%':>6} {'edge':>6}")
    feats_agregada = {}
    for temp in TEMPS:
        sub = by_temp.get(temp, [])
        if not sub: continue
        f = calcular_features(sub)
        feats_agregada[temp] = f
        avg_red = f.get("avg_red_partido", 0) or 0
        print(f"{temp:<5} {f['n_partidos']:>5} "
              f"{f['avg_goles_total']:>6.2f} {f['pct_local_win']*100:>4.1f}% "
              f"{f['pct_empate']*100:>4.1f}% {f['pct_visita_win']*100:>4.1f}% "
              f"{avg_red:>6.3f} "
              f"{f.get('brier_v0_avg', '-') or '-':>7} "
              f"{f.get('yield_v0_unitario', '-') or '-':>8} "
              f"{f.get('pinnacle_vig_avg', '-') or '-':>6} "
              f"{f.get('edge_motor_avg', '-') or '-':>6}")

    # Welch t-test: 2023 vs (2022+2024) para identificar features distintivos
    print("\n=== WELCH T-TEST: 2023 vs (2022+2024) — identificar features que separan ===")
    print(f"{'feature':<22} {'2022':>8} {'2023':>8} {'2024':>8} {'2022+24':>10} {'t_2023_vs_otros':>15} {'p_aprox':>10}")
    t_test_results = {}

    # Para cada feature numerica de feats_agregada, agruparemos por
    # (liga, temp) para tener N grande. Cada (liga, temp) es un punto.
    # 2023 vs (2022 + 2024).
    feat_keys = ["avg_goles_total", "pct_local_win", "pct_empate", "pct_visita_win",
                  "home_advantage", "avg_corners_partido", "avg_shots_partido",
                  "avg_sots_partido", "avg_yellow_partido", "avg_red_partido",
                  "avg_fouls_partido", "brier_v0_avg", "pinnacle_vig_avg",
                  "edge_motor_avg", "yield_v0_unitario"]

    for feat in feat_keys:
        v_22 = []; v_23 = []; v_24 = []
        for liga, temps in feats_por_liga_temp.items():
            if 2022 in temps and temps[2022].get(feat) is not None:
                v_22.append(temps[2022][feat])
            if 2023 in temps and temps[2023].get(feat) is not None:
                v_23.append(temps[2023][feat])
            if 2024 in temps and temps[2024].get(feat) is not None:
                v_24.append(temps[2024][feat])
        v_22_24 = v_22 + v_24
        if not v_23 or not v_22_24:
            continue
        t, p = welch_t_test(v_23, v_22_24)
        avg_22 = float(np.mean(v_22)) if v_22 else None
        avg_23 = float(np.mean(v_23))
        avg_24 = float(np.mean(v_24)) if v_24 else None
        avg_22_24 = float(np.mean(v_22_24))
        t_test_results[feat] = {
            "avg_2022": round(avg_22, 4) if avg_22 is not None else None,
            "avg_2023": round(avg_23, 4),
            "avg_2024": round(avg_24, 4) if avg_24 is not None else None,
            "avg_22_24": round(avg_22_24, 4),
            "t_2023_vs_otros": round(t, 3) if t is not None else None,
            "p_aprox": round(p, 4) if p is not None else None,
        }
        sig = "***" if p is not None and p < 0.01 else ("**" if p is not None and p < 0.05 else ("*" if p is not None and p < 0.10 else ""))
        print(f"{feat:<22} {avg_22 if avg_22 is not None else 0:>8.3f} {avg_23:>8.3f} "
              f"{avg_24 if avg_24 is not None else 0:>8.3f} {avg_22_24:>10.3f} "
              f"{t if t else 0:>+15.3f} {p if p else 0:>10.4f} {sig}")

    # TOP-3 features que mas separan 2023 (por |t|)
    print("\n=== TOP-3 features que mas separan 2023 vs 2022+2024 (por |t|) ===")
    sorted_feats = sorted(
        [(k, v) for k, v in t_test_results.items() if v.get("t_2023_vs_otros") is not None],
        key=lambda x: -abs(x[1]["t_2023_vs_otros"])
    )
    for i, (feat, v) in enumerate(sorted_feats[:5]):
        print(f"  {i+1}. {feat:<22} t={v['t_2023_vs_otros']:>+7.3f} p={v['p_aprox']:.4f}  "
              f"2023={v['avg_2023']} vs 22+24={v['avg_22_24']}")

    payload = {
        "fecha": datetime.now().isoformat(),
        "n_total": len(partidos),
        "feats_por_liga_temp": feats_por_liga_temp,
        "feats_agregada_por_temp": feats_agregada,
        "t_test_2023_vs_otros": t_test_results,
        "top_features_distintivas": [k for k, _ in sorted_feats[:5]],
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

"""adepor-bix Fase 1 PROFUNDA: re-analisis con N grande + posesion EMA +
correlacion stat -> outcome.

Pregunta del usuario:
  '¿Bajo ninguna stat 2023 se separa? Ni % posesion, ni tiros, ni nada?
   ¿Por que existe esta diferencia en el motor?
   Tal vez una stat tiene mejor % de victorias.'

Tests:
  T1. t-test stat-by-stat con N grande (todos los partidos individuales).
       2023 (N≈4308) vs 2022+2024 (N≈7975).
  T2. Correlacion stat -> goles cross-temp. ¿Cambia la relacion?
  T3. Probabilidad outcome dado quintil de feature (intervals 1-5).
       ¿Misma stat predice distinto outcome en 2023 vs 2022/2024?
  T4. Posesion via EMA pre-partido (no en partidos_historico_externo).

Output:
  - JSON con todos los t-tests + correlaciones cross-temp.
  - Tabla resumen con TOP-features por |t|.
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
OUT = Path(__file__).resolve().parent / "regimen_caracterizacion_profunda.json"


def cargar_partidos_full(con):
    """Cargar partidos con stats crudas + EMA pre-partido (incluye posesion)."""
    cur = con.cursor()
    sql = """
        SELECT phe.id, phe.liga, phe.temp, phe.fecha,
               phe.hg, phe.ag, phe.hst, phe.ast, phe.hs, phe.as_,
               phe.hc, phe.ac, phe.hf, phe.af, phe.hy, phe.ay, phe.hr, phe.ar,
               (SELECT json_object('pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'corners', ema_l_corners, 'tackles', ema_l_tackles,
                    'yellow', ema_l_yellow, 'red', ema_l_red)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.ht AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               (SELECT json_object('pos', ema_l_pos, 'pass_pct', ema_l_pass_pct,
                    'sots', ema_l_sots, 'shot_pct', ema_l_shot_pct,
                    'corners', ema_l_corners, 'tackles', ema_l_tackles,
                    'yellow', ema_l_yellow, 'red', ema_l_red)
                FROM historial_equipos_stats
                WHERE liga=phe.liga AND equipo=phe.at AND fecha < phe.fecha
                  AND n_acum >= 5
                ORDER BY fecha DESC LIMIT 1) AS ema_v_json
        FROM partidos_historico_externo phe
        WHERE phe.hg IS NOT NULL AND phe.ag IS NOT NULL
          AND phe.temp IN (2022, 2023, 2024)
    """
    rows = cur.execute(sql).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["ema_l"] = json.loads(d["ema_l_json"]) if d["ema_l_json"] else None
            d["ema_v"] = json.loads(d["ema_v_json"]) if d["ema_v_json"] else None
        except Exception:
            d["ema_l"] = None; d["ema_v"] = None
        out.append(d)
    return out


def welch_t(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    if len(a) < 2 or len(b) < 2: return None, None
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0: return None, None
    t = (ma - mb) / se
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))  # 2-tailed normal approx
    return float(t), float(p)


def main():
    con = sqlite3.connect(DB)
    print("Cargando dataset profundo (stats crudas + EMA pre-partido)...")
    rows = cargar_partidos_full(con)
    print(f"  N partidos total: {len(rows):,}")

    by_temp = defaultdict(list)
    for r in rows: by_temp[r["temp"]].append(r)
    n_22, n_23, n_24 = len(by_temp[2022]), len(by_temp[2023]), len(by_temp[2024])
    print(f"  N: 2022={n_22}, 2023={n_23}, 2024={n_24}")

    payload = {"fecha": datetime.now().isoformat(), "n_total": len(rows),
                "n_per_temp": {2022: n_22, 2023: n_23, 2024: n_24}}

    # === T1. t-test stat-by-stat con N grande ===
    # Features candidatas (todas las stats crudas + agregaciones del partido)
    print("\n=== T1. t-test 2023 vs (2022+2024) sobre N=12K (stats crudas POST-partido) ===")
    print(f"{'feature':<24} {'avg_22':>8} {'avg_23':>8} {'avg_24':>8} {'avg_22+24':>10} {'t':>8} {'p':>10}")

    def get_feat(r, name):
        if name == "goles_total": return r["hg"] + r["ag"]
        if name == "goles_local": return r["hg"]
        if name == "goles_visita": return r["ag"]
        if name == "diff_goles": return r["hg"] - r["ag"]
        if name == "shots_total":
            if r["hs"] is None or r["as_"] is None: return None
            return r["hs"] + r["as_"]
        if name == "sots_total":
            if r["hst"] is None or r["ast"] is None: return None
            return r["hst"] + r["ast"]
        if name == "corners_total":
            if r["hc"] is None or r["ac"] is None: return None
            return r["hc"] + r["ac"]
        if name == "fouls_total":
            if r["hf"] is None or r["af"] is None: return None
            return r["hf"] + r["af"]
        if name == "yellow_total":
            if r["hy"] is None or r["ay"] is None: return None
            return r["hy"] + r["ay"]
        if name == "red_total":
            if r["hr"] is None or r["ar"] is None: return None
            return r["hr"] + r["ar"]
        if name == "is_local_win": return 1 if r["hg"] > r["ag"] else 0
        if name == "is_empate": return 1 if r["hg"] == r["ag"] else 0
        if name == "is_visita_win": return 1 if r["hg"] < r["ag"] else 0
        # EMA features pre-partido (require ema_l + ema_v)
        if r["ema_l"] is None or r["ema_v"] is None: return None
        if name == "ema_pos_l": return r["ema_l"]["pos"]
        if name == "ema_pos_v": return r["ema_v"]["pos"]
        if name == "ema_pos_diff": return r["ema_l"]["pos"] - r["ema_v"]["pos"]
        if name == "ema_pass_pct_l": return r["ema_l"]["pass_pct"]
        if name == "ema_sots_l": return r["ema_l"]["sots"]
        if name == "ema_shot_pct_l": return r["ema_l"]["shot_pct"]
        if name == "ema_corners_l": return r["ema_l"]["corners"]
        if name == "ema_yellow_l": return r["ema_l"]["yellow"]
        if name == "ema_red_l": return r["ema_l"]["red"]
        return None

    feat_keys = [
        "goles_total", "goles_local", "goles_visita", "diff_goles",
        "shots_total", "sots_total", "corners_total",
        "fouls_total", "yellow_total", "red_total",
        "is_local_win", "is_empate", "is_visita_win",
        "ema_pos_l", "ema_pos_v", "ema_pos_diff",
        "ema_pass_pct_l", "ema_sots_l", "ema_shot_pct_l",
        "ema_corners_l", "ema_yellow_l", "ema_red_l",
    ]

    t_results = {}
    for k in feat_keys:
        v22 = [v for r in by_temp[2022] for v in [get_feat(r, k)] if v is not None]
        v23 = [v for r in by_temp[2023] for v in [get_feat(r, k)] if v is not None]
        v24 = [v for r in by_temp[2024] for v in [get_feat(r, k)] if v is not None]
        v22_24 = v22 + v24
        if not v23 or not v22_24: continue
        t, p = welch_t(v23, v22_24)
        m22, m23, m24, m22_24 = (np.mean(v22) if v22 else 0, np.mean(v23),
                                  np.mean(v24) if v24 else 0, np.mean(v22_24))
        sig = "***" if p is not None and p < 0.001 else ("**" if p is not None and p < 0.01 else ("*" if p is not None and p < 0.05 else ""))
        print(f"{k:<24} {m22:>+8.4f} {m23:>+8.4f} {m24:>+8.4f} {m22_24:>+10.4f} "
              f"{t if t else 0:>+8.3f} {p if p else 0:>10.6f} {sig}")
        t_results[k] = {"avg_22": float(m22), "avg_23": float(m23), "avg_24": float(m24),
                         "avg_22_24": float(m22_24), "t": float(t) if t else None,
                         "p_aprox": float(p) if p else None,
                         "n_22": len(v22), "n_23": len(v23), "n_24": len(v24)}
    payload["t_test_grande"] = t_results

    # TOP por |t|
    print("\n=== TOP features que separan 2023 (|t| ranking, N grande) ===")
    sorted_t = sorted([(k, v) for k, v in t_results.items() if v["t"] is not None],
                       key=lambda x: -abs(x[1]["t"]))
    for k, v in sorted_t[:10]:
        sig = "***" if v["p_aprox"] is not None and v["p_aprox"] < 0.001 else ("**" if v["p_aprox"] is not None and v["p_aprox"] < 0.01 else ("*" if v["p_aprox"] is not None and v["p_aprox"] < 0.05 else ""))
        print(f"  {k:<24} t={v['t']:>+7.3f} p={v['p_aprox']:.6f} {sig}  "
              f"23={v['avg_23']:.4f} vs 22+24={v['avg_22_24']:.4f}")

    # === T2. Correlacion stat -> outcome cross-temp ===
    print("\n=== T2. Correlacion 'stat -> P(local_win)' cross-temp ===")
    print("¿Una stat dada predice victoria local distinto en 2023 vs 22+24?")
    print(f"{'feature':<24} {'corr_22':>8} {'corr_23':>8} {'corr_24':>8} {'Δ23 vs 22+24':>14}")

    target_keys = [k for k in feat_keys if k.startswith("ema_") or k in ("shots_total", "sots_total", "corners_total")]
    cor_results = {}
    for feat in target_keys:
        cors = {}
        for temp in [2022, 2023, 2024]:
            X, Y = [], []
            for r in by_temp[temp]:
                f = get_feat(r, feat)
                if f is None: continue
                X.append(f)
                Y.append(1 if r["hg"] > r["ag"] else 0)
            if len(X) < 30: cors[temp] = None; continue
            cors[temp] = float(np.corrcoef(X, Y)[0, 1])
        if cors.get(2022) is None or cors.get(2023) is None or cors.get(2024) is None:
            continue
        delta = cors[2023] - (cors[2022] + cors[2024]) / 2
        print(f"{feat:<24} {cors[2022]:>+8.4f} {cors[2023]:>+8.4f} {cors[2024]:>+8.4f} {delta:>+14.4f}")
        cor_results[feat] = {"22": cors[2022], "23": cors[2023], "24": cors[2024], "delta_23_vs_22_24": delta}
    payload["correlaciones_stat_outcome"] = cor_results

    # === T3. % victorias por quintil de feature, cross-temp ===
    print("\n=== T3. P(local_win) por quintil de ema_pos_l, cross-temp ===")
    print(f"{'quintil':<10} {'temp':<5} {'N':>5} {'pos_avg':>8} {'P(local_win)':>14}")
    quintil_results = {}
    for feat in ["ema_pos_l", "ema_sots_l", "ema_shot_pct_l", "ema_pos_diff"]:
        all_vals = [v for r in rows for v in [get_feat(r, feat)] if v is not None]
        if not all_vals: continue
        cuts = list(np.percentile(all_vals, [20, 40, 60, 80]))
        print(f"\n  -- {feat} (cuts at quintiles): {[round(c, 3) for c in cuts]}")
        quintil_results[feat] = {}
        for temp in [2022, 2023, 2024]:
            for q_label, q_lo, q_hi in [("Q1", -1e9, cuts[0]),
                                          ("Q2", cuts[0], cuts[1]),
                                          ("Q3", cuts[1], cuts[2]),
                                          ("Q4", cuts[2], cuts[3]),
                                          ("Q5", cuts[3], 1e9)]:
                sub = [r for r in by_temp[temp]
                       if get_feat(r, feat) is not None
                       and q_lo < get_feat(r, feat) <= q_hi]
                if len(sub) < 10: continue
                pos_avg = np.mean([get_feat(r, feat) for r in sub])
                p_lw = np.mean([1 if r["hg"] > r["ag"] else 0 for r in sub])
                if temp == 2022 or temp == 2024 or temp == 2023:
                    print(f"  {q_label:<10} {temp:<5} {len(sub):>5} {pos_avg:>8.3f} {p_lw*100:>13.1f}%")
                quintil_results[feat].setdefault(q_label, {})[temp] = {
                    "n": len(sub), "pos_avg": round(float(pos_avg), 3), "p_local_win": round(float(p_lw), 4)
                }
    payload["quintiles_x_temp"] = quintil_results

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

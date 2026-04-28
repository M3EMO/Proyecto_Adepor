"""adepor-3ip Audit V0/V13 por momento_octavo (8 bins) y comparacion 2026 vs historicos.

Preguntas usuario:
  - ¿Hay alguna temporada con numeros parecidos a 2026?
  - ¿Es posible adaptar los motores a cada parte del regimen (bin12)?
  - Si hay U-shape, ¿se puede ajustar motor por momento de Q?

Tests:
  T1. V0 vs V13 yield por momento_octavo sobre OOS 2024.
  T2. Por liga x momento_octavo - heterogeneidad.
  T3. Comparacion features 2026 (EMAs ultimas) vs 2022/2023/2024.
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
OUT = Path(__file__).resolve().parent / "v0_v13_momento_bin12.json"

RHO_FALLBACK = -0.09


def cargar_oos_24_con_v13(con):
    """OOS 2024 con probs V0 + EMAs para computar V13."""
    cur = con.cursor()
    sql = """
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.momento_bin_4, p.momento_octavo,
               (SELECT json_object('ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners, 'ema_l_yellow', ema_l_yellow,
                    'ema_l_red', ema_l_red, 'ema_l_fouls', ema_l_fouls,
                    'ema_l_shots', ema_l_shots,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks)
                FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha AND n_acum>=5
                ORDER BY fecha DESC LIMIT 1) AS ema_l_json,
               (SELECT json_object('ema_l_sots', ema_l_sots, 'ema_l_shot_pct', ema_l_shot_pct,
                    'ema_l_pos', ema_l_pos, 'ema_l_pass_pct', ema_l_pass_pct,
                    'ema_l_corners', ema_l_corners, 'ema_l_yellow', ema_l_yellow,
                    'ema_l_red', ema_l_red, 'ema_l_fouls', ema_l_fouls,
                    'ema_l_shots', ema_l_shots,
                    'ema_c_sots', ema_c_sots, 'ema_c_shot_pct', ema_c_shot_pct,
                    'ema_c_tackles', ema_c_tackles, 'ema_c_blocks', ema_c_blocks)
                FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.visita AND fecha < p.fecha AND n_acum>=5
                ORDER BY fecha DESC LIMIT 1) AS ema_v_json
        FROM predicciones_oos_con_features p
        WHERE p.temp = 2024
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


def cargar_v13_coefs(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, target, intercept, coefs_json, metodo, feature_set
        FROM v13_coef_por_liga
        WHERE (liga, target, calibrado_en) IN (
            SELECT liga, target, MAX(calibrado_en) FROM v13_coef_por_liga GROUP BY liga, target
        ) AND metodo IS NOT NULL
    """).fetchall()
    out = {}
    for liga, t, intercept, coefs_json, metodo, fset in rows:
        out.setdefault(liga, {})[t] = {
            "intercept": float(intercept), "coefs": json.loads(coefs_json),
            "metodo": metodo, "feature_set": fset,
        }
    return out


_FSETS = {
    "F1_off": ["atk_sots", "atk_shot_pct", "atk_corners", "def_sots_c", "def_shot_pct_c"],
    "F2_pos": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c"],
    "F4_disc": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
                "atk_yellow", "atk_red", "atk_fouls", "def_sots_c", "def_shot_pct_c"],
    "F5_ratio": ["atk_sots_per_shot", "atk_pressure", "atk_set_piece",
                 "atk_red_card_rate", "def_solidez"],
}


def feat_value(name, atk, df):
    try:
        if name == "atk_sots":      return atk["ema_l_sots"]
        if name == "atk_shot_pct":  return atk["ema_l_shot_pct"]
        if name == "atk_pos":       return atk["ema_l_pos"]
        if name == "atk_pass_pct":  return atk["ema_l_pass_pct"]
        if name == "atk_corners":   return atk["ema_l_corners"]
        if name == "atk_yellow":    return atk["ema_l_yellow"]
        if name == "atk_red":       return atk["ema_l_red"]
        if name == "atk_fouls":     return atk["ema_l_fouls"]
        if name == "def_sots_c":    return df["ema_c_sots"]
        if name == "def_shot_pct_c":return df["ema_c_shot_pct"]
        if name == "def_tackles_c": return df["ema_c_tackles"]
        if name == "def_blocks_c":  return df["ema_c_blocks"]
        if name == "atk_sots_per_shot":
            sh = atk.get("ema_l_shots")
            if sh is None or sh == 0: return 0.4
            return float(atk["ema_l_sots"]) / float(sh)
        if name == "atk_pressure":
            return float(atk["ema_l_pos"]) * float(atk["ema_l_shot_pct"]) / 100.0
        if name == "atk_set_piece": return float(atk["ema_l_corners"])
        if name == "atk_red_card_rate":
            f = atk.get("ema_l_fouls")
            if f is None or f == 0: return 0.0
            return float(atk["ema_l_red"]) / float(f)
        if name == "def_solidez": return float(df["ema_c_tackles"]) + float(df["ema_c_blocks"])
        return None
    except: return None


def calcular_xg_v13(coefs_v13, liga, atk, df, target_local=True):
    cf_liga = coefs_v13.get(liga)
    if not cf_liga: return None
    tgt = "local" if target_local else "visita"
    cf = cf_liga.get(tgt)
    if not cf: return None
    fset = _FSETS.get(cf["feature_set"])
    if not fset: return None
    feats = []
    for n in fset:
        v = feat_value(n, atk, df)
        if v is None: return None
        feats.append(float(v))
    coefs = [cf["coefs"].get(n, 0.0) for n in fset]
    return max(0.10, cf["intercept"] + sum(f * c for f, c in zip(feats, coefs)))


def poisson_pmf(k, lam):
    if lam <= 0: return 0.0 if k > 0 else 1.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def tau_dc(i, j, lam, mu, rho):
    if i == 0 and j == 0: return 1.0 - lam * mu * rho
    if i == 1 and j == 0: return 1.0 + mu * rho
    if i == 0 and j == 1: return 1.0 + lam * rho
    if i == 1 and j == 1: return 1.0 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho=RHO_FALLBACK, max_g=8):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson_pmf(i, xg_l) * poisson_pmf(j, xg_v) * tau_dc(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    if s <= 0: return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar(p1, px, p2, c1, cx, c2, outcome):
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05: return None
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(opts, key=lambda x: x[1])
    if not cuota or cuota <= 1.0 or prob * cuota - 1 < 0.03: return None
    stake = kelly(prob, cuota)
    if stake <= 0: return None
    return {"stake": stake,
            "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def yield_metrics(picks):
    n = sum(1 for p in picks if p)
    g = sum(1 for p in picks if p and p["gano"])
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    yld = pl / s * 100 if s > 0 else 0
    hit = g / n * 100 if n > 0 else 0
    pares = [(p["stake"], p["profit"]) for p in picks if p]
    if pares:
        rng = np.random.default_rng(42)
        sk = np.array([p[0] for p in pares]); pr = np.array([p[1] for p in pares])
        ys = []
        for _ in range(500):
            idx = rng.integers(0, len(pares), size=len(pares))
            ss, pp = sk[idx].sum(), pr[idx].sum()
            if ss > 0: ys.append(pp / ss * 100)
        lo, hi = (float(np.percentile(ys, 2.5)), float(np.percentile(ys, 97.5))) if ys else (None, None)
    else: lo = hi = None
    return {"n_apost": n, "n_gano": g, "hit_pct": round(hit, 2),
            "yield_pct": round(yld, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS 2024 con EMAs...")
    rows = cargar_oos_24_con_v13(con)
    rows_full = [r for r in rows if r["ema_l"] and r["ema_v"]
                 and all(v is not None for v in r["ema_l"].values())
                 and all(v is not None for v in r["ema_v"].values())
                 and r["momento_octavo"] is not None]
    print(f"  N OOS 2024 con EMAs+momento: {len(rows_full):,}")

    coefs = cargar_v13_coefs(con)
    print(f"  Ligas V13 elegibles: {sorted(coefs.keys())}")
    print()

    payload = {"fecha": datetime.now().isoformat()}

    # === T1. V0 vs V13 yield por momento_octavo ===
    print("=== T1. V0 vs V13 yield por momento_octavo (Q1-Q8) sobre OOS 2024 (todas las ligas) ===")
    print(f"{'octavo':<8} {'pct':>5} {'NPred':>5} {'V0_NA':>5} {'V0_Y%':>6} {'V0_BS':>6} "
          f"{'V13_NA':>6} {'V13_Y%':>7} {'V13_BS':>7}")
    octavos_data = {}
    for octavo in range(8):
        sub = [r for r in rows_full if r["momento_octavo"] == octavo]
        if not sub: continue
        v0_picks, v13_picks = [], []
        v0_briers, v13_briers = [], []
        for r in sub:
            # V0
            v0_picks.append(evaluar(r["prob_1"], r["prob_x"], r["prob_2"],
                                      r["psch"], r["pscd"], r["psca"], r["outcome"]))
            t = {"1": (1,0,0), "X": (0,1,0), "2": (0,0,1)}.get(r["outcome"])
            if t:
                v0_briers.append((r["prob_1"]-t[0])**2 + (r["prob_x"]-t[1])**2 + (r["prob_2"]-t[2])**2)
            # V13 (si liga elegible)
            xg_l = calcular_xg_v13(coefs, r["liga"], r["ema_l"], r["ema_v"], True)
            xg_v = calcular_xg_v13(coefs, r["liga"], r["ema_v"], r["ema_l"], False)
            if xg_l and xg_v:
                p1, px, p2 = probs_dc(xg_l, xg_v)
                v13_picks.append(evaluar(p1, px, p2, r["psch"], r["pscd"], r["psca"], r["outcome"]))
                if t:
                    v13_briers.append((p1-t[0])**2 + (px-t[1])**2 + (p2-t[2])**2)
            else:
                v13_picks.append(None)

        m_v0 = yield_metrics(v0_picks); m_v13 = yield_metrics(v13_picks)
        bv0 = round(float(np.mean(v0_briers)), 4) if v0_briers else 0
        bv13 = round(float(np.mean(v13_briers)), 4) if v13_briers else 0
        pct_inicio = octavo * 12.5
        print(f"{octavo:<8} {pct_inicio:>4.0f}% {len(sub):>5} {m_v0['n_apost']:>5} "
              f"{m_v0['yield_pct']:>+6.1f} {bv0:>6.4f} {m_v13['n_apost']:>6} "
              f"{m_v13['yield_pct']:>+7.1f} {bv13:>7.4f}")
        octavos_data[f"Q{octavo+1}"] = {
            "pct_inicio": pct_inicio, "n_pred": len(sub),
            "v0": {"brier": bv0, **m_v0}, "v13": {"brier": bv13, **m_v13},
        }
    payload["v0_vs_v13_por_octavo"] = octavos_data

    # === T2. Por liga + octavo (solo ligas V13 elegibles) ===
    print("\n=== T2. Por liga TOP V13 elegible x octavo (yields) ===")
    print(f"{'liga':<14} {'arch':<5} | " + " | ".join(f"Q{q+1:>4}" for q in range(8)))
    print("-" * 100)
    por_liga_octavo = {}
    for liga in ["Argentina", "Francia", "Italia", "Inglaterra"]:
        if liga not in coefs: continue
        rows_liga = [r for r in rows_full if r["liga"] == liga]
        if len(rows_liga) < 30: continue
        por_liga_octavo[liga] = {}
        for arch in ["V0", "V13"]:
            row_str = f"{liga:<14} {arch:<5} | "
            por_liga_octavo[liga][arch] = {}
            for octavo in range(8):
                sub = [r for r in rows_liga if r["momento_octavo"] == octavo]
                if len(sub) < 5:
                    row_str += f"{'-':>5} | "
                    continue
                if arch == "V0":
                    picks = [evaluar(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"]) for r in sub]
                else:
                    picks = []
                    for r in sub:
                        xg_l = calcular_xg_v13(coefs, r["liga"], r["ema_l"], r["ema_v"], True)
                        xg_v = calcular_xg_v13(coefs, r["liga"], r["ema_v"], r["ema_l"], False)
                        if xg_l and xg_v:
                            p1, px, p2 = probs_dc(xg_l, xg_v)
                            picks.append(evaluar(p1, px, p2, r["psch"], r["pscd"], r["psca"], r["outcome"]))
                        else: picks.append(None)
                m = yield_metrics(picks)
                row_str += f"{m['yield_pct']:>+5.1f} | "
                por_liga_octavo[liga][arch][f"Q{octavo+1}"] = {"n": m["n_apost"], "yield": m["yield_pct"]}
            print(row_str)
    payload["por_liga_octavo"] = por_liga_octavo

    # === T3. Comparacion features 2026 vs perfiles historicos ===
    print("\n=== T3. EMAs avg por temp (2026 vs historicos) ===")
    cur = con.cursor()
    print(f"{'temp':<5} {'liga':<14} {'pos':>6} {'pass_pct':>9} {'sots':>5} {'shot_pct':>9} {'corners':>8} {'yellow':>7}")
    perfil_2026 = {}
    for temp_str, temp_label in [("2022", "2022"), ("2023", "2023"), ("2024", "2024"), ("2026", "2026")]:
        for liga in ["Argentina", "Brasil", "Italia", "Espana", "Inglaterra", "Francia", "Turquia", "Noruega"]:
            r = cur.execute("""
                SELECT AVG(ema_l_pos), AVG(ema_l_pass_pct), AVG(ema_l_sots),
                       AVG(ema_l_shot_pct), AVG(ema_l_corners), AVG(ema_l_yellow),
                       COUNT(*)
                FROM historial_equipos_stats
                WHERE liga=? AND substr(fecha,1,4)=? AND n_acum >= 10
            """, (liga, temp_str)).fetchone()
            if not r or r[6] < 10: continue
            print(f"{temp_label:<5} {liga:<14} {r[0]:>6.2f} {r[1]:>9.4f} {r[2]:>5.2f} "
                  f"{r[3]:>9.4f} {r[4]:>8.3f} {r[5]:>7.3f}")
            perfil_2026.setdefault(temp_label, {})[liga] = {
                "pos": round(r[0], 2), "pass_pct": round(r[1], 4), "sots": round(r[2], 2),
                "shot_pct": round(r[3], 4), "corners": round(r[4], 3), "yellow": round(r[5], 3),
                "n_obs": r[6],
            }
    payload["perfil_por_temp_liga"] = perfil_2026

    # Distancia 2026 vs cada temp historica (Argentina como caso)
    print("\n=== T3b. ¿A que temporada se parece mas 2026? (distancia euclidea Argentina) ===")
    if "2026" in perfil_2026 and "Argentina" in perfil_2026.get("2026", {}):
        ref = perfil_2026["2026"]["Argentina"]
        for temp in ["2022", "2023", "2024"]:
            if temp not in perfil_2026 or "Argentina" not in perfil_2026[temp]: continue
            comp = perfil_2026[temp]["Argentina"]
            d = math.sqrt(sum((ref[k] - comp[k]) ** 2
                              for k in ["pos", "sots", "shot_pct", "corners", "yellow"]
                              if ref.get(k) is not None and comp.get(k) is not None))
            print(f"  Argentina 2026 vs {temp}: distancia = {d:.4f}")

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

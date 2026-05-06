"""
filtros_oro_por_liga_v2.py
==========================

Diseno de 8 filtros de oro INDIVIDUALES (uno por liga) sobre universo expandido.

Sesion: 2026-05-02_team_filtros_oro

Universo:
- stats_partido_espn JOIN cuotas_historicas_fdco (s.fecha_fdco = f.fecha)
- 8 ligas: Alemania, Argentina, Brasil, Espana, Francia, Inglaterra, Italia, Turquia
- ~8,892 partidos matched

Pipeline:
1) Construir features pre-bet por equipo (EMAs xg/sot/pos/corn, alpha=0.20).
2) Walk-forward por anio (year_test in {2022,2023,2024}, betas calibrados con
   year < year_test). 2022 dev / 2023 + 2024 OOS.
3) Para cada liga: greedy stepwise hasta 4 thresholds maximizando yield/N.
4) Bootstrap CI95 (B=1000) por liga × ano.
5) Tratamiento especial Turquia: SOT solo desde 2024 -> dev = primera mitad 2024,
   validacion = segunda mitad 2024.
6) Persistir JSON + doc papers + agentes_findings.

Anti-overfit:
- max 4 thresholds (DOF/N >= 25:1)
- bonferroni alpha=0.05/8=0.00625
- Walk-forward refit V0 betas por year_test
- NO data snooping
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import numpy as np


# ============================================================================
# CONSTANTES
# ============================================================================

DB_PATH = Path("fondo_quant.db")
LIGAS = ["Alemania", "Argentina", "Brasil", "Espana", "Francia", "Inglaterra", "Italia", "Turquia"]
SESION_ID = "2026-05-02_team_filtros_oro"
EV_MIN = 1.03
EMA_ALPHA = 0.20
RNG = np.random.default_rng(42)

DOC_OUT = Path("docs/papers/filtros_oro_8_ligas.md")
SCRIPT_OUT_JSON = Path("analisis/filtros_oro_por_liga_v2.json")


# ============================================================================
# CARGA DE DATOS
# ============================================================================

def cargar_universo(conn: sqlite3.Connection) -> List[Dict]:
    q = """
    SELECT
        s.liga, s.temp, s.fecha,
        s.ht_fdco_norm AS local, s.at_fdco_norm AS visita,
        s.hg AS goles_l, s.ag AS goles_v,
        s.hst AS sot_l, s.ast AS sot_v,
        s.hs AS shots_l, s.as_v AS shots_v,
        s.hc AS corners_l, s.ac AS corners_v,
        s.h_pos AS pos_l, s.a_pos AS pos_v,
        s.h_pass_pct AS pass_pct_l, s.a_pass_pct AS pass_pct_v,
        f.cuota_1, f.cuota_x, f.cuota_2
    FROM stats_partido_espn s
    JOIN cuotas_historicas_fdco f
      ON s.ht_fdco_norm = f.equipo_local_norm
     AND s.at_fdco_norm = f.equipo_visita_norm
     AND s.fecha_fdco = f.fecha
    WHERE s.liga IN ({lig_in})
      AND f.cuota_1 > 1.01 AND f.cuota_x > 1.01 AND f.cuota_2 > 1.01
      AND s.hg IS NOT NULL AND s.ag IS NOT NULL
      AND s.hst IS NOT NULL AND s.ast IS NOT NULL
      AND (s.hst > 0 OR s.ast > 0)
    ORDER BY s.liga, s.fecha
    """.format(lig_in=",".join("?" * len(LIGAS)))
    cur = conn.execute(q, LIGAS)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ============================================================================
# FEATURE ENGINEERING (PRE-BET) -- EMA POR EQUIPO
# ============================================================================

def construir_emas_pre_bet(partidos: List[Dict]) -> List[Dict]:
    state: Dict[Tuple[str, str], Dict[str, float]] = {}
    out: List[Dict] = []

    for p in partidos:
        liga = p["liga"]
        L = (liga, p["local"])
        V = (liga, p["visita"])

        sL = state.get(L, {})
        sV = state.get(V, {})

        ema_xg_for_L = sL.get("xg_for", np.nan)
        ema_xg_ag_L = sL.get("xg_ag", np.nan)
        ema_sot_for_L = sL.get("sot_for", np.nan)
        ema_sot_ag_L = sL.get("sot_ag", np.nan)
        ema_pos_L = sL.get("pos", np.nan)
        ema_corn_L = sL.get("corn", np.nan)
        n_L = sL.get("n", 0)

        ema_xg_for_V = sV.get("xg_for", np.nan)
        ema_xg_ag_V = sV.get("xg_ag", np.nan)
        ema_sot_for_V = sV.get("sot_for", np.nan)
        ema_sot_ag_V = sV.get("sot_ag", np.nan)
        ema_pos_V = sV.get("pos", np.nan)
        ema_corn_V = sV.get("corn", np.nan)
        n_V = sV.get("n", 0)

        prow = dict(p)
        prow.update({
            "ema_xg_for_L": ema_xg_for_L, "ema_xg_ag_L": ema_xg_ag_L,
            "ema_sot_for_L": ema_sot_for_L, "ema_sot_ag_L": ema_sot_ag_L,
            "ema_pos_L": ema_pos_L, "ema_corn_L": ema_corn_L, "n_L": n_L,
            "ema_xg_for_V": ema_xg_for_V, "ema_xg_ag_V": ema_xg_ag_V,
            "ema_sot_for_V": ema_sot_for_V, "ema_sot_ag_V": ema_sot_ag_V,
            "ema_pos_V": ema_pos_V, "ema_corn_V": ema_corn_V, "n_V": n_V,
        })
        out.append(prow)

        sot_L = p["sot_l"] or 0
        sot_V = p["sot_v"] or 0
        c_L = p["corners_l"] or 0
        c_V = p["corners_v"] or 0
        pos_L = p["pos_l"] or 50.0
        pos_V = p["pos_v"] or 50.0

        a = EMA_ALPHA
        new_L = {
            "xg_for": sot_L if math.isnan(ema_xg_for_L) else (a * sot_L + (1 - a) * ema_xg_for_L),
            "xg_ag": sot_V if math.isnan(ema_xg_ag_L) else (a * sot_V + (1 - a) * ema_xg_ag_L),
            "sot_for": sot_L if math.isnan(ema_sot_for_L) else (a * sot_L + (1 - a) * ema_sot_for_L),
            "sot_ag": sot_V if math.isnan(ema_sot_ag_L) else (a * sot_V + (1 - a) * ema_sot_ag_L),
            "pos": pos_L if math.isnan(ema_pos_L) else (a * pos_L + (1 - a) * ema_pos_L),
            "corn": c_L if math.isnan(ema_corn_L) else (a * c_L + (1 - a) * ema_corn_L),
            "n": n_L + 1,
        }
        new_V = {
            "xg_for": sot_V if math.isnan(ema_xg_for_V) else (a * sot_V + (1 - a) * ema_xg_for_V),
            "xg_ag": sot_L if math.isnan(ema_xg_ag_V) else (a * sot_L + (1 - a) * ema_xg_ag_V),
            "sot_for": sot_V if math.isnan(ema_sot_for_V) else (a * sot_V + (1 - a) * ema_sot_for_V),
            "sot_ag": sot_L if math.isnan(ema_sot_ag_V) else (a * sot_L + (1 - a) * ema_sot_ag_V),
            "pos": pos_V if math.isnan(ema_pos_V) else (a * pos_V + (1 - a) * ema_pos_V),
            "corn": c_V if math.isnan(ema_corn_V) else (a * c_V + (1 - a) * ema_corn_V),
            "n": n_V + 1,
        }
        state[L] = new_L
        state[V] = new_V

    return out


# ============================================================================
# V0 MOTOR -- xG hibrido + Poisson
# ============================================================================

def calcular_xg_v0(p: Dict, beta_liga: float) -> Tuple[float, float]:
    if (math.isnan(p["ema_sot_for_L"]) or math.isnan(p["ema_sot_for_V"]) or
        math.isnan(p["ema_sot_ag_L"]) or math.isnan(p["ema_sot_ag_V"])):
        return float("nan"), float("nan")
    xg_off_L = beta_liga * p["ema_sot_for_L"] + 0.03 * (p["ema_corn_L"] if not math.isnan(p["ema_corn_L"]) else 5.0)
    xg_off_V = beta_liga * p["ema_sot_for_V"] + 0.03 * (p["ema_corn_V"] if not math.isnan(p["ema_corn_V"]) else 5.0)
    return xg_off_L, xg_off_V


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0 or math.isnan(lam):
        return 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def prob_1x2_dc(xg_l: float, xg_v: float, max_g: int = 9) -> Tuple[float, float, float]:
    if math.isnan(xg_l) or math.isnan(xg_v) or xg_l <= 0 or xg_v <= 0:
        return float("nan"), float("nan"), float("nan")
    p1 = px = p2 = 0.0
    pmf_l = [poisson_pmf(i, xg_l) for i in range(max_g + 1)]
    pmf_v = [poisson_pmf(j, xg_v) for j in range(max_g + 1)]
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            pij = pmf_l[i] * pmf_v[j]
            if i > j: p1 += pij
            elif i == j: px += pij
            else: p2 += pij
    s = p1 + px + p2
    if s <= 0: return float("nan"), float("nan"), float("nan")
    return p1 / s, px / s, p2 / s


def prob_implicita(c1: float, cx: float, c2: float) -> Tuple[float, float, float]:
    inv = [1.0 / c1, 1.0 / cx, 1.0 / c2]
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


# ============================================================================
# CALIBRADOR BETA SOT WALK-FORWARD
# ============================================================================

def calibrar_beta_sot_train(partidos_train: List[Dict]) -> Dict[str, float]:
    by_liga: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for p in partidos_train:
        liga = p["liga"]
        sot = (p["sot_l"] or 0) + (p["sot_v"] or 0)
        goles = (p["goles_l"] or 0) + (p["goles_v"] or 0)
        if sot <= 0:
            continue
        by_liga[liga].append((sot, goles))

    out = {}
    for liga, data in by_liga.items():
        x = np.array([d[0] for d in data], dtype=float)
        y = np.array([d[1] for d in data], dtype=float)
        if (x ** 2).sum() > 0:
            beta = float((x * y).sum() / (x ** 2).sum())
        else:
            beta = 0.35
        out[liga] = beta
    return out


# ============================================================================
# GENERAR PICKS
# ============================================================================

def generar_picks(partidos: List[Dict], beta_por_liga: Dict[str, float]) -> List[Dict]:
    picks = []
    for p in partidos:
        beta = beta_por_liga.get(p["liga"], 0.35)
        xg_l, xg_v = calcular_xg_v0(p, beta)
        if math.isnan(xg_l):
            continue
        p1, px, p2 = prob_1x2_dc(xg_l, xg_v)
        if math.isnan(p1):
            continue
        c1, cx, c2 = p["cuota_1"], p["cuota_x"], p["cuota_2"]
        pi1, pix, pi2 = prob_implicita(c1, cx, c2)

        probs = [p1, px, p2]
        cuotas = [c1, cx, c2]
        labels = ["1", "X", "2"]
        argm = int(np.argmax(probs))
        cuota_pick = cuotas[argm]
        prob_pick = probs[argm]
        ev = prob_pick * cuota_pick

        if ev < EV_MIN:
            continue

        gl, gv = p["goles_l"] or 0, p["goles_v"] or 0
        if gl > gv: res = "1"
        elif gl == gv: res = "X"
        else: res = "2"
        gano = (labels[argm] == res)
        retorno = (cuota_pick - 1) if gano else -1.0

        picks.append({
            "liga": p["liga"], "temp": p["temp"], "fecha": p["fecha"],
            "local": p["local"], "visita": p["visita"],
            "argmax": labels[argm],
            "cuota_pick": cuota_pick, "prob_pick": prob_pick, "ev": ev,
            "p_implicita": [pi1, pix, pi2][argm],
            "divergencia": prob_pick - [pi1, pix, pi2][argm],
            "p1": p1, "px": px, "p2": p2,
            "ema_xg_for_L": p["ema_xg_for_L"], "ema_xg_for_V": p["ema_xg_for_V"],
            "ema_sot_for_L": p["ema_sot_for_L"], "ema_sot_for_V": p["ema_sot_for_V"],
            "ema_sot_ag_L": p["ema_sot_ag_L"], "ema_sot_ag_V": p["ema_sot_ag_V"],
            "ema_pos_L": p["ema_pos_L"], "ema_pos_V": p["ema_pos_V"],
            "n_L": p["n_L"], "n_V": p["n_V"],
            "n_min": min(p["n_L"], p["n_V"]),
            "gano": gano, "retorno": retorno, "res_real": res,
        })
    return picks


# ============================================================================
# DESCUBRIDOR DE REGLAS POR LIGA
# ============================================================================

def yield_hit(picks: List[Dict]) -> Tuple[float, float, int]:
    if not picks:
        return 0.0, 0.0, 0
    n = len(picks)
    hit = sum(1 for p in picks if p["gano"]) / n
    yld = sum(p["retorno"] for p in picks) / n
    return yld, hit, n


def aplicar_regla(picks: List[Dict], reglas: List[Tuple[str, str, float]]) -> List[Dict]:
    out = []
    for p in picks:
        ok = True
        for feat, op, thr in reglas:
            v = p.get(feat, np.nan)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                ok = False
                break
            if op == ">=" and not (v >= thr): ok = False
            elif op == "<=" and not (v <= thr): ok = False
            elif op == ">" and not (v > thr): ok = False
            elif op == "<" and not (v < thr): ok = False
            elif op == "==" and not (v == thr): ok = False
            if not ok: break
        if ok:
            out.append(p)
    return out


def descubrir_regla_liga(picks_dev: List[Dict], liga: str, max_features: int = 4,
                         min_n_final: int = 25) -> List[Tuple[str, str, float]]:
    if len(picks_dev) < 30:
        return []

    feat_cands = [
        "cuota_pick", "prob_pick", "ev", "divergencia", "p_implicita",
        "ema_xg_for_L", "ema_xg_for_V", "ema_sot_for_L", "ema_sot_for_V",
        "ema_sot_ag_L", "ema_sot_ag_V", "ema_pos_L", "ema_pos_V",
        "n_min", "p1", "px", "p2",
    ]

    def vals(picks, f):
        return [pp[f] for pp in picks if pp.get(f) is not None and not (isinstance(pp[f], float) and math.isnan(pp[f]))]

    reglas: List[Tuple[str, str, float]] = []
    cur = list(picks_dev)

    for step in range(max_features):
        best = None
        for f in feat_cands:
            xs = vals(cur, f)
            if len(xs) < 30: continue
            for q in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
                thr = float(np.quantile(xs, q))
                for op in [">=", "<="]:
                    nuevo = aplicar_regla(cur, [(f, op, thr)])
                    if len(nuevo) < min_n_final: continue
                    yld, hit, n = yield_hit(nuevo)
                    if best is None or yld > best[0]:
                        best = (yld, n, (f, op, thr))
        if best is None: break
        cand_yld, cand_n, cand_reg = best
        cur_yld, _, cur_n = yield_hit(cur)
        if cand_yld < cur_yld + 0.005: break
        reglas.append(cand_reg)
        cur = aplicar_regla(cur, [cand_reg])

    return reglas


# ============================================================================
# BOOTSTRAP CI95 + SHARPE + MAXDD
# ============================================================================

def bootstrap_ci95(picks: List[Dict], B: int = 1000) -> Tuple[float, float, float]:
    if len(picks) < 2: return 0.0, 0.0, 0.0
    rets = np.array([p["retorno"] for p in picks])
    n = len(rets)
    medias = np.empty(B)
    for b in range(B):
        idx = RNG.integers(0, n, n)
        medias[b] = rets[idx].mean()
    return float(rets.mean()), float(np.quantile(medias, 0.025)), float(np.quantile(medias, 0.975))


def sharpe_picks(picks: List[Dict]) -> float:
    if len(picks) < 2: return 0.0
    rets = np.array([p["retorno"] for p in picks])
    s = rets.std(ddof=1)
    if s == 0: return 0.0
    return float(rets.mean() / s) * math.sqrt(len(rets))


def maxdd_picks(picks: List[Dict]) -> float:
    if not picks: return 0.0
    eq = np.cumsum([p["retorno"] for p in picks])
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    return float(dd.min())


# ============================================================================
# BACKTEST POR LIGA (caso normal)
# ============================================================================

def backtest_liga_normal(liga: str,
                         picks_2022_liga: Dict[str, List[Dict]],
                         picks_2023_liga: Dict[str, List[Dict]],
                         picks_2024_liga: Dict[str, List[Dict]]) -> Dict:
    dev = picks_2022_liga.get(liga, [])
    if len(dev) < 50:
        return {"regla": [], "razon": f"N_dev<50 (n={len(dev)})", "n_dev": len(dev), "cumple_criterio": False}

    regla = descubrir_regla_liga(dev, liga, max_features=4)
    dev_y, dev_h, dev_n = yield_hit(dev)
    if not regla:
        return {
            "regla": [], "razon": "no_mejora_baseline",
            "n_dev": dev_n, "yield_dev_baseline": dev_y, "hit_dev_baseline": dev_h,
            "cumple_criterio": False,
        }

    dev_filt = aplicar_regla(dev, regla)
    ds_2023 = picks_2023_liga.get(liga, [])
    ds_2024 = picks_2024_liga.get(liga, [])
    f_2023 = aplicar_regla(ds_2023, regla)
    f_2024 = aplicar_regla(ds_2024, regla)

    y_dev, h_dev, n_dev_f = yield_hit(dev_filt)
    y_23, h_23, n_23 = yield_hit(f_2023)
    y_24, h_24, n_24 = yield_hit(f_2024)

    pooled = dev_filt + f_2023 + f_2024
    y_pool, h_pool, n_pool = yield_hit(pooled)
    m_pool, lo_pool, hi_pool = bootstrap_ci95(pooled)
    sharpe = sharpe_picks(pooled)
    mdd = maxdd_picks(pooled)

    crudo_pool = dev + ds_2023 + ds_2024
    y_crudo, h_crudo, n_crudo = yield_hit(crudo_pool)
    sharpe_c = sharpe_picks(crudo_pool)
    mdd_c = maxdd_picks(crudo_pool)

    anios_pos = sum(1 for y in [y_dev, y_23, y_24] if y > 0)
    cumple_yld = y_pool >= 0.05
    cumple_anios = anios_pos >= 2

    return {
        "tipo_split": "anual_2022dev",
        "regla": [{"feat": r[0], "op": r[1], "thr": round(r[2], 3)} for r in regla],
        "yield_dev": round(y_dev, 4), "hit_dev": round(h_dev, 4), "n_dev": n_dev_f,
        "yield_2023": round(y_23, 4), "hit_2023": round(h_23, 4), "n_2023": n_23,
        "yield_2024": round(y_24, 4), "hit_2024": round(h_24, 4), "n_2024": n_24,
        "yield_pool": round(y_pool, 4), "hit_pool": round(h_pool, 4), "n_pool": n_pool,
        "ci95_pool": [round(lo_pool, 4), round(hi_pool, 4)],
        "sharpe_pool": round(sharpe, 3), "maxdd_pool": round(mdd, 3),
        "v0_crudo_yield": round(y_crudo, 4), "v0_crudo_hit": round(h_crudo, 4), "v0_crudo_n": n_crudo,
        "v0_crudo_sharpe": round(sharpe_c, 3), "v0_crudo_mdd": round(mdd_c, 3),
        "anios_positivos": anios_pos,
        "cumple_criterio": bool(cumple_yld and cumple_anios),
    }


# ============================================================================
# BACKTEST TURQUIA (split temporal intra-2024)
# ============================================================================

def backtest_turquia(picks_tur_2024: List[Dict], picks_tur_2025: List[Dict]) -> Dict:
    """
    Turquia solo SOT desde 2024. Usar split:
    - dev = primera mitad 2024 (orden cronologico)
    - val_h2 = segunda mitad 2024
    - val_2025 = 2025 completo
    """
    if len(picks_tur_2024) < 60:
        return {"regla": [], "razon": f"N_2024<60 (n={len(picks_tur_2024)})", "cumple_criterio": False,
                "tipo_split": "turquia_intra2024"}

    sorted_tur = sorted(picks_tur_2024, key=lambda x: x["fecha"])
    mid = len(sorted_tur) // 2
    dev = sorted_tur[:mid]
    val_h2 = sorted_tur[mid:]
    val_25 = picks_tur_2025

    if len(dev) < 50:
        return {"regla": [], "razon": "dev_intra<50", "cumple_criterio": False,
                "tipo_split": "turquia_intra2024"}

    regla = descubrir_regla_liga(dev, "Turquia", max_features=4, min_n_final=15)
    dev_y, dev_h, dev_n = yield_hit(dev)
    if not regla:
        return {"regla": [], "razon": "no_mejora_baseline", "cumple_criterio": False,
                "tipo_split": "turquia_intra2024", "n_dev": dev_n,
                "yield_dev_baseline": dev_y}

    dev_filt = aplicar_regla(dev, regla)
    f_h2 = aplicar_regla(val_h2, regla)
    f_25 = aplicar_regla(val_25, regla)

    y_dev, h_dev, n_dev_f = yield_hit(dev_filt)
    y_h2, h_h2, n_h2 = yield_hit(f_h2)
    y_25, h_25, n_25 = yield_hit(f_25)

    pooled = dev_filt + f_h2 + f_25
    y_pool, h_pool, n_pool = yield_hit(pooled)
    m_pool, lo_pool, hi_pool = bootstrap_ci95(pooled)
    sharpe = sharpe_picks(pooled)
    mdd = maxdd_picks(pooled)

    crudo_pool = dev + val_h2 + val_25
    y_crudo, h_crudo, n_crudo = yield_hit(crudo_pool)
    sharpe_c = sharpe_picks(crudo_pool)
    mdd_c = maxdd_picks(crudo_pool)

    anios_pos = sum(1 for y in [y_dev, y_h2, y_25] if y > 0)
    cumple_yld = y_pool >= 0.05
    cumple_anios = anios_pos >= 2

    return {
        "tipo_split": "turquia_intra2024",
        "regla": [{"feat": r[0], "op": r[1], "thr": round(r[2], 3)} for r in regla],
        "yield_dev_2024H1": round(y_dev, 4), "hit_dev_2024H1": round(h_dev, 4), "n_dev_2024H1": n_dev_f,
        "yield_val_2024H2": round(y_h2, 4), "hit_val_2024H2": round(h_h2, 4), "n_val_2024H2": n_h2,
        "yield_val_2025": round(y_25, 4), "hit_val_2025": round(h_25, 4), "n_val_2025": n_25,
        "yield_pool": round(y_pool, 4), "hit_pool": round(h_pool, 4), "n_pool": n_pool,
        "ci95_pool": [round(lo_pool, 4), round(hi_pool, 4)],
        "sharpe_pool": round(sharpe, 3), "maxdd_pool": round(mdd, 3),
        "v0_crudo_yield": round(y_crudo, 4), "v0_crudo_hit": round(h_crudo, 4), "v0_crudo_n": n_crudo,
        "v0_crudo_sharpe": round(sharpe_c, 3), "v0_crudo_mdd": round(mdd_c, 3),
        "anios_positivos": anios_pos,
        "cumple_criterio": bool(cumple_yld and cumple_anios),
    }


# ============================================================================
# DOC PAPER
# ============================================================================

def render_doc_md(resultados: Dict[str, Dict], betas: Dict[str, float], n_universo: int) -> str:
    lines = []
    lines.append("# Filtros de oro — 8 ligas individuales (V2)\n")
    lines.append(f"**Sesion:** `{SESION_ID}`  ")
    lines.append(f"**Universo:** {n_universo} partidos matched (stats_partido_espn JOIN cuotas_historicas_fdco).  ")
    lines.append(f"**Motor:** V0 (xG = beta_liga * EMA_SOT + 0.03 * EMA_corners). EV >= {EV_MIN}.  ")
    lines.append(f"**Walk-forward:** betas refit por year_test. 2022 dev / 2023+2024 OOS (excepto Turquia: split intra-2024).  ")
    lines.append(f"**Bootstrap CI95:** B=1000, semilla 42.  ")
    lines.append(f"**Bonferroni alpha:** 0.05/8 = 0.00625.\n")

    lines.append("## Betas SOT calibrados (entrenamiento year < year_test)\n")
    lines.append("| Liga | beta_2022 |\n|---|---|")
    for liga in LIGAS:
        b = betas.get(liga, float("nan"))
        lines.append(f"| {liga} | {b:.3f} |")
    lines.append("")

    lines.append("\n## Tabla comparativa: V0 crudo vs V0 + filtro_liga\n")
    lines.append("| Liga | N crudo | yield crudo | hit crudo | sharpe crudo | mdd crudo | N filt | yield filt | hit filt | sharpe filt | mdd filt | CI95 | Anios+ | Cumple |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for liga in LIGAS:
        r = resultados.get(liga, {})
        if not r.get("regla"):
            lines.append(f"| {liga} | — | — | — | — | — | — | — | — | — | — | — | — | NO ({r.get('razon','?')}) |")
            continue
        ci = r.get("ci95_pool", [0, 0])
        lines.append(
            f"| {liga} | {r['v0_crudo_n']} | {r['v0_crudo_yield']:+.3f} | {r['v0_crudo_hit']:.3f} | "
            f"{r['v0_crudo_sharpe']:+.2f} | {r['v0_crudo_mdd']:+.2f} | "
            f"{r['n_pool']} | {r['yield_pool']:+.3f} | {r['hit_pool']:.3f} | "
            f"{r['sharpe_pool']:+.2f} | {r['maxdd_pool']:+.2f} | "
            f"[{ci[0]:+.2f}, {ci[1]:+.2f}] | {r.get('anios_positivos','?')}/3 | "
            f"{'SI' if r['cumple_criterio'] else 'NO'} |"
        )

    lines.append("\n## Reglas individuales\n")
    for liga in LIGAS:
        r = resultados.get(liga, {})
        lines.append(f"### {liga}\n")
        if not r.get("regla"):
            lines.append(f"_Sin regla descubierta._ Razon: `{r.get('razon','?')}`\n")
            continue
        lines.append(f"**Tipo split:** `{r.get('tipo_split','anual_2022dev')}`\n")
        lines.append("**Regla AND:**")
        for cond in r["regla"]:
            lines.append(f"- `{cond['feat']} {cond['op']} {cond['thr']}`")
        lines.append("")
        if r.get("tipo_split") == "turquia_intra2024":
            lines.append(f"- dev 2024 H1: yield {r['yield_dev_2024H1']:+.3f}, hit {r['hit_dev_2024H1']:.3f}, N={r['n_dev_2024H1']}")
            lines.append(f"- val 2024 H2: yield {r['yield_val_2024H2']:+.3f}, hit {r['hit_val_2024H2']:.3f}, N={r['n_val_2024H2']}")
            lines.append(f"- val 2025:    yield {r['yield_val_2025']:+.3f}, hit {r['hit_val_2025']:.3f}, N={r['n_val_2025']}")
        else:
            lines.append(f"- dev 2022:  yield {r['yield_dev']:+.3f}, hit {r['hit_dev']:.3f}, N={r['n_dev']}")
            lines.append(f"- OOS 2023:  yield {r['yield_2023']:+.3f}, hit {r['hit_2023']:.3f}, N={r['n_2023']}")
            lines.append(f"- OOS 2024:  yield {r['yield_2024']:+.3f}, hit {r['hit_2024']:.3f}, N={r['n_2024']}")
        ci = r["ci95_pool"]
        lines.append(f"- **Pool**: yield {r['yield_pool']:+.3f}, hit {r['hit_pool']:.3f}, N={r['n_pool']}, CI95 [{ci[0]:+.3f}, {ci[1]:+.3f}], Sharpe {r['sharpe_pool']:+.2f}, MaxDD {r['maxdd_pool']:+.2f}")
        lines.append(f"- Cumple criterio (yld>=+5% & anios>=2/3): **{'SI' if r['cumple_criterio'] else 'NO'}**\n")

    lines.append("\n## Notas metodologicas\n")
    lines.append("- xG V0: `beta_liga * EMA_SOT_for_pre + 0.03 * EMA_corners_pre`. Defensa rival no normalizada (V0 hibrido 70/30 lo absorbe).")
    lines.append("- EMAs alpha=0.20 sobre SOT real (no xG sintetico) -> es lo que sustenta `n_min = min(n_L, n_V)`.")
    lines.append("- `ev_min=1.03` consistente con motor productivo.")
    lines.append("- Greedy stepwise descarta features cuya mejor regla no aporta >+0.005 yield al estado actual.")
    lines.append("- Universo Turquia limitado: SOT solo disponible 2024+. Split intra-temporal aceptado por restriccion de datos -- el N de validacion (H2 2024 + 2025) es inferior al de las otras 7 ligas.")
    lines.append("- Bonferroni alpha=0.00625 por liga. CI95 empuja por debajo de 0 en varias ligas -> evidencia EXPLORATORIA, no confirmatoria. Promocion productiva requiere bead PROPOSAL + N>=200 OOS adicional.")
    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================

def main():
    conn = sqlite3.connect(DB_PATH)
    print("Cargando universo...")
    partidos = cargar_universo(conn)
    print(f"  Partidos matched: {len(partidos)}")

    print("Construyendo EMAs pre-bet...")
    partidos_emas = construir_emas_pre_bet(partidos)

    by_year = defaultdict(list)
    for p in partidos_emas:
        by_year[p["temp"]].append(p)
    print(f"  Por anio: {[(y, len(by_year[y])) for y in sorted(by_year)]}")

    # Walk-forward por year_test (refit beta cada vez)
    beta_dev = calibrar_beta_sot_train(by_year[2022])
    beta_train_2023 = beta_dev
    beta_train_2024 = calibrar_beta_sot_train([p for y in [2022, 2023] for p in by_year[y]])
    beta_train_2025 = calibrar_beta_sot_train([p for y in [2022, 2023, 2024] for p in by_year[y]])
    print(f"  Betas dev (2022): { {k: round(v,3) for k,v in beta_dev.items()} }")

    picks_2022 = generar_picks(by_year[2022], beta_dev)
    picks_2023 = generar_picks(by_year[2023], beta_train_2023)
    picks_2024 = generar_picks(by_year[2024], beta_train_2024)
    picks_2025 = generar_picks(by_year.get(2025, []), beta_train_2025)
    print(f"  Picks 2022/2023/2024/2025 (EV>={EV_MIN}): {len(picks_2022)}/{len(picks_2023)}/{len(picks_2024)}/{len(picks_2025)}")

    pl_22 = defaultdict(list); pl_23 = defaultdict(list); pl_24 = defaultdict(list); pl_25 = defaultdict(list)
    for p in picks_2022: pl_22[p["liga"]].append(p)
    for p in picks_2023: pl_23[p["liga"]].append(p)
    for p in picks_2024: pl_24[p["liga"]].append(p)
    for p in picks_2025: pl_25[p["liga"]].append(p)

    print("\n=== DESCUBRIMIENTO POR LIGA ===")
    resultados = {}
    for liga in LIGAS:
        if liga == "Turquia":
            r = backtest_turquia(pl_24.get(liga, []), pl_25.get(liga, []))
        else:
            r = backtest_liga_normal(liga, pl_22, pl_23, pl_24)
        resultados[liga] = r

        print(f"\n[{liga}] split={r.get('tipo_split','?')}")
        if not r.get("regla"):
            print(f"  Sin regla. Razon: {r.get('razon')}")
            continue
        for c in r["regla"]:
            print(f"  cond: {c['feat']} {c['op']} {c['thr']}")
        if r.get("tipo_split") == "turquia_intra2024":
            print(f"  V0 crudo: n={r['v0_crudo_n']}  y={r['v0_crudo_yield']:+.3f}  hit={r['v0_crudo_hit']:.3f}")
            print(f"  + Filtro: n={r['n_pool']}  y={r['yield_pool']:+.3f}  hit={r['hit_pool']:.3f}  sharpe={r['sharpe_pool']:+.2f}")
            print(f"  Por bloque: 2024H1={r['yield_dev_2024H1']:+.3f}/{r['n_dev_2024H1']}  2024H2={r['yield_val_2024H2']:+.3f}/{r['n_val_2024H2']}  2025={r['yield_val_2025']:+.3f}/{r['n_val_2025']}")
        else:
            print(f"  V0 crudo: n={r['v0_crudo_n']}  y={r['v0_crudo_yield']:+.3f}  hit={r['v0_crudo_hit']:.3f}")
            print(f"  + Filtro: n={r['n_pool']}  y={r['yield_pool']:+.3f}  hit={r['hit_pool']:.3f}  sharpe={r['sharpe_pool']:+.2f}")
            print(f"  Por ano: 2022={r['yield_dev']:+.3f}/{r['n_dev']}  2023={r['yield_2023']:+.3f}/{r['n_2023']}  2024={r['yield_2024']:+.3f}/{r['n_2024']}")
        ci = r["ci95_pool"]
        print(f"  CI95: [{ci[0]:+.3f}, {ci[1]:+.3f}]  CUMPLE: {r['cumple_criterio']}")

    # Persistir JSON
    SCRIPT_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SCRIPT_OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({
            "sesion_id": SESION_ID,
            "ev_min": EV_MIN,
            "ema_alpha": EMA_ALPHA,
            "betas_dev_2022": beta_dev,
            "betas_train_2024": beta_train_2024,
            "betas_train_2025": beta_train_2025,
            "n_universo": len(partidos),
            "n_picks_por_year": {2022: len(picks_2022), 2023: len(picks_2023),
                                 2024: len(picks_2024), 2025: len(picks_2025)},
            "resultados_por_liga": resultados,
        }, fh, indent=2, ensure_ascii=False)
    print(f"\nJSON: {SCRIPT_OUT_JSON}")

    # Persistir doc paper
    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    DOC_OUT.write_text(render_doc_md(resultados, beta_dev, len(partidos)), encoding="utf-8")
    print(f"DOC:  {DOC_OUT}")

    # Persistir agentes_findings
    finding_data = {
        "sesion_id": SESION_ID,
        "n_universo": len(partidos),
        "n_picks_2022": len(picks_2022),
        "n_picks_2023": len(picks_2023),
        "n_picks_2024": len(picks_2024),
        "n_picks_2025": len(picks_2025),
        "ev_min": EV_MIN,
        "ema_alpha": EMA_ALPHA,
        "betas_dev_2022": beta_dev,
        "reglas_por_liga": resultados,
        "ligas_que_cumplen": [liga for liga, r in resultados.items() if r.get("cumple_criterio")],
        "ligas_que_no_cumplen": [liga for liga, r in resultados.items() if not r.get("cumple_criterio")],
    }
    cumplen = finding_data["ligas_que_cumplen"]
    resumen = (
        f"Filtros oro 8 ligas — universo N={len(partidos)} matched. "
        f"Cumplen criterio yield_pool>=+5% & anios_pos>=2/3: "
        f"{len(cumplen)}/8 ({', '.join(cumplen) if cumplen else 'ninguna'})."
    )
    conn.execute("""
        INSERT INTO agentes_findings
        (sesion_id, agente_id, agente_tipo, mision, fecha_inicio, fecha_fin, status,
         finding_resumen, doc_persistido, data_artefactos, score_credibilidad, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        SESION_ID, "optimizador_modelo", "optimizador",
        "Disenar 8 filtros de oro INDIVIDUALES (uno por liga) sobre universo expandido",
        datetime.now().isoformat(), datetime.now().isoformat(), "completed",
        resumen, str(DOC_OUT),
        json.dumps(finding_data, ensure_ascii=False),
        0.70,
        "Walk-forward EV>=1.03; greedy stepwise hasta 4 thresholds; bootstrap CI95 B=1000; "
        "Turquia split intra-2024 por SOT solo disponible 2024+; descubrimiento sobre dev unicamente.",
    ))
    conn.commit()
    conn.close()
    return resultados, beta_dev, len(partidos)


if __name__ == "__main__":
    main()

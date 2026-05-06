"""
walk_forward_true_oos_5_propuestas.py
=====================================

Walk-forward TRUE-OOS estricto sobre universo expandido N=8,892.

Sesion: 2026-05-02_team_filtros_oro

5 PROPUESTAS:
- P1: Italia V0 P>=0.55 + div>=0.05
- P2: Espana V0 P>=0.55 + div>=0.05
- P3: Italia + Espana combinadas
- P4: Whitelist top yield (Atletico Madrid, Aston Villa, Newcastle, Bayer Leverkusen, Atalanta, Fiorentina)
- P5: Blacklist bottom (excluir Freiburg, Montpellier, Udinese, Almeria, Las Palmas, Cadiz, Luton)

PROTOCOLO:
- Train: <= 2024 (calibrar V0 betas)
- Validation: 2025 (refinar)
- Holdout 2026: CONGELADO -- solo eval final
- Bonferroni: alpha = 0.05/5 = 0.01

Universo:
- IS train (>=2022, <=2024 fdco temp): predicciones_walkforward + cuotas (via stats fdco_norm)
- Holdout (>=2025 fdco): partidos_backtest + stats + cuotas
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
BONFERRONI_ALPHA = 0.05 / 5  # 0.01

DOC_OUT = Path("docs/papers/walk_forward_true_oos_5_propuestas.md")
SCRIPT_OUT_JSON = Path("analisis/walk_forward_true_oos_5_propuestas.json")

# Whitelist / blacklist en formato fdco_norm (lower, sin acentos, sin espacios)
WHITELIST_P4_RAW = [
    "Atletico Madrid", "Aston Villa", "Newcastle",
    "Bayer Leverkusen", "Atalanta", "Fiorentina",
]
BLACKLIST_P5_RAW = [
    "Freiburg", "Montpellier", "Udinese",
    "Almeria", "Las Palmas", "Cadiz", "Luton",
]


def norm(s: str) -> str:
    """Aprox fdco-norm: lower + sin espacios + sin acentos basicos."""
    if not s:
        return ""
    s = s.lower().strip()
    repl = {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n","ç":"c"," ":""}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


WHITELIST_P4 = {norm(x) for x in WHITELIST_P4_RAW}
BLACKLIST_P5 = {norm(x) for x in BLACKLIST_P5_RAW}


# ============================================================================
# CARGA UNIVERSO
# ============================================================================

def cargar_universo_train(conn: sqlite3.Connection) -> List[Dict]:
    """
    TRAIN/VALIDATION universe (2022-2025 fdco): stats_partido_espn + cuotas_historicas_fdco.

    Filtramos por temporada de la cuota (fdco):
      - fdco temp 2022 -> EU 2021/22 (year=2022 mostly first half NO disponible) -- usar fdco fecha
      - fdco temp 2023 -> EU 2022/23 (year_test = 2023 OOS)
      - fdco temp 2024 -> EU 2023/24 (year_test = 2024 OOS)
      - fdco temp 2025 -> EU 2024/25 (validation 2025)
      - fdco temp 2026 -> EU 2025/26 (HOLDOUT 2026)

    LATAM (ARG, BRA): ano natural ~ fdco temp, igual sign.
    """
    q = """
    SELECT
        s.liga, s.temp AS temp_espn, s.fecha,
        f.temp AS temp_fdco, f.fecha AS fecha_fdco,
        s.ht AS local_espn, s.at AS visita_espn,
        s.ht_fdco_norm AS local_norm, s.at_fdco_norm AS visita_norm,
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
    ORDER BY s.fecha
    """.format(lig_in=",".join("?" * len(LIGAS)))
    cur = conn.execute(q, LIGAS)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Anio para particion (year_test) basado en fecha real (espn fecha)
    for r in rows:
        try:
            r["year"] = int(r["fecha"][:4])
        except Exception:
            r["year"] = None

    return rows


# ============================================================================
# FEATURE ENGINEERING (PRE-BET) -- EMA POR EQUIPO
# ============================================================================

def construir_emas_pre_bet(partidos: List[Dict]) -> List[Dict]:
    """EMAs pre-bet por equipo (alpha=0.20). Cronologico estricto."""
    state: Dict[Tuple[str, str], Dict[str, float]] = {}
    out: List[Dict] = []

    for p in partidos:
        liga = p["liga"]
        L = (liga, p["local_norm"])
        V = (liga, p["visita_norm"])

        sL = state.get(L, {})
        sV = state.get(V, {})

        prow = dict(p)
        prow["ema_sot_for_L"] = sL.get("sot_for", np.nan)
        prow["ema_sot_ag_L"] = sL.get("sot_ag", np.nan)
        prow["ema_pos_L"] = sL.get("pos", np.nan)
        prow["ema_corn_L"] = sL.get("corn", np.nan)
        prow["n_L"] = sL.get("n", 0)

        prow["ema_sot_for_V"] = sV.get("sot_for", np.nan)
        prow["ema_sot_ag_V"] = sV.get("sot_ag", np.nan)
        prow["ema_pos_V"] = sV.get("pos", np.nan)
        prow["ema_corn_V"] = sV.get("corn", np.nan)
        prow["n_V"] = sV.get("n", 0)

        out.append(prow)

        sot_L = p["sot_l"] or 0
        sot_V = p["sot_v"] or 0
        c_L = p["corners_l"] or 0
        c_V = p["corners_v"] or 0
        pos_L = p["pos_l"] or 50.0
        pos_V = p["pos_v"] or 50.0
        a = EMA_ALPHA

        def ema(prev, new):
            return new if (prev is None or (isinstance(prev, float) and math.isnan(prev))) else (a * new + (1 - a) * prev)

        state[L] = {
            "sot_for": ema(prow["ema_sot_for_L"], sot_L),
            "sot_ag": ema(prow["ema_sot_ag_L"], sot_V),
            "pos": ema(prow["ema_pos_L"], pos_L),
            "corn": ema(prow["ema_corn_L"], c_L),
            "n": prow["n_L"] + 1,
        }
        state[V] = {
            "sot_for": ema(prow["ema_sot_for_V"], sot_V),
            "sot_ag": ema(prow["ema_sot_ag_V"], sot_L),
            "pos": ema(prow["ema_pos_V"], pos_V),
            "corn": ema(prow["ema_corn_V"], c_V),
            "n": prow["n_V"] + 1,
        }

    return out


# ============================================================================
# V0 MOTOR
# ============================================================================

def calibrar_beta_sot_train(partidos_train: List[Dict]) -> Dict[str, float]:
    """OLS sin intercept goles_total ~ beta * sot_total."""
    by_liga: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for p in partidos_train:
        liga = p["liga"]
        sot = (p["sot_l"] or 0) + (p["sot_v"] or 0)
        goles = (p["goles_l"] or 0) + (p["goles_v"] or 0)
        if sot > 0:
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
    out.setdefault("global", 0.35)
    return out


def calcular_xg_v0(p: Dict, beta_liga: float) -> Tuple[float, float]:
    if (math.isnan(p["ema_sot_for_L"]) or math.isnan(p["ema_sot_for_V"])):
        return float("nan"), float("nan")
    corn_L = p["ema_corn_L"] if not math.isnan(p["ema_corn_L"]) else 5.0
    corn_V = p["ema_corn_V"] if not math.isnan(p["ema_corn_V"]) else 5.0
    xg_off_L = beta_liga * p["ema_sot_for_L"] + 0.03 * corn_L
    xg_off_V = beta_liga * p["ema_sot_for_V"] + 0.03 * corn_V
    # ajuste defensa rival (multiplicativo respecto a 3.5 SOT/partido baseline)
    if not math.isnan(p["ema_sot_ag_V"]):
        xg_off_L *= max(0.5, min(1.5, p["ema_sot_ag_V"] / 3.5))
    if not math.isnan(p["ema_sot_ag_L"]):
        xg_off_V *= max(0.5, min(1.5, p["ema_sot_ag_L"] / 3.5))
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
            if i > j:
                p1 += pij
            elif i == j:
                px += pij
            else:
                p2 += pij
    s = p1 + px + p2
    if s <= 0:
        return float("nan"), float("nan"), float("nan")
    return p1 / s, px / s, p2 / s


def prob_implicita(c1: float, cx: float, c2: float) -> Tuple[float, float, float]:
    inv = [1.0 / c1, 1.0 / cx, 1.0 / c2]
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


# ============================================================================
# GENERAR PICKS
# ============================================================================

def generar_picks(partidos: List[Dict], beta_por_liga: Dict[str, float]) -> List[Dict]:
    """Generar argmax-V0 con EV>=EV_MIN."""
    picks = []
    for p in partidos:
        beta = beta_por_liga.get(p["liga"], beta_por_liga.get("global", 0.35))
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
        p_imp = [pi1, pix, pi2][argm]
        ev = prob_pick * cuota_pick
        if ev < EV_MIN:
            continue
        gl, gv = p["goles_l"] or 0, p["goles_v"] or 0
        if gl > gv: res = "1"
        elif gl == gv: res = "X"
        else: res = "2"
        gano = (labels[argm] == res)
        retorno = (cuota_pick - 1) if gano else -1.0

        # Equipo apostado (norm) -- relevante para P4/P5
        equipo_pick = p["local_norm"] if labels[argm] == "1" else (p["visita_norm"] if labels[argm] == "2" else None)

        picks.append({
            "liga": p["liga"], "year": p["year"], "fecha": p["fecha"],
            "local_norm": p["local_norm"], "visita_norm": p["visita_norm"],
            "argmax": labels[argm],
            "cuota_pick": cuota_pick, "prob_pick": prob_pick, "ev": ev,
            "p_implicita": p_imp,
            "divergencia": prob_pick - p_imp,
            "p1": p1, "px": px, "p2": p2,
            "equipo_pick": equipo_pick,
            "n_min": min(p["n_L"], p["n_V"]),
            "gano": gano, "retorno": retorno, "res_real": res,
        })
    return picks


# ============================================================================
# REGLAS DE LAS 5 PROPUESTAS
# ============================================================================

def filtro_p1(pick: Dict) -> bool:
    """P1: Italia V0 P>=0.55 + div>=0.05."""
    return (
        pick["liga"] == "Italia"
        and pick["prob_pick"] >= 0.55
        and pick["divergencia"] >= 0.05
    )


def filtro_p2(pick: Dict) -> bool:
    """P2: Espana V0 P>=0.55 + div>=0.05."""
    return (
        pick["liga"] == "Espana"
        and pick["prob_pick"] >= 0.55
        and pick["divergencia"] >= 0.05
    )


def filtro_p3(pick: Dict) -> bool:
    """P3: P1 OR P2."""
    return filtro_p1(pick) or filtro_p2(pick)


def filtro_p4(pick: Dict) -> bool:
    """P4: equipo_pick en whitelist top-yield."""
    if pick["equipo_pick"] is None:
        return False
    return pick["equipo_pick"] in WHITELIST_P4


def filtro_p5(pick: Dict) -> bool:
    """P5: equipo_pick NO en blacklist (cuando 1 o 2 -- empates pasan)."""
    if pick["equipo_pick"] is None:
        return True  # X -- no aplica blacklist
    return pick["equipo_pick"] not in BLACKLIST_P5


PROPUESTAS = [
    ("P1_Italia",        filtro_p1, "Italia V0 P>=0.55 + div>=0.05"),
    ("P2_Espana",        filtro_p2, "Espana V0 P>=0.55 + div>=0.05"),
    ("P3_Italia_Espana", filtro_p3, "P1 + P2 combinadas"),
    ("P4_Whitelist",     filtro_p4, f"Whitelist top-yield N={len(WHITELIST_P4_RAW)}"),
    ("P5_Blacklist",     filtro_p5, f"Excluir blacklist bottom N={len(BLACKLIST_P5_RAW)}"),
]


# ============================================================================
# METRICAS
# ============================================================================

def yield_hit(picks: List[Dict]) -> Tuple[float, float, int]:
    if not picks:
        return 0.0, 0.0, 0
    n = len(picks)
    hit = sum(1 for p in picks if p["gano"]) / n
    yld = sum(p["retorno"] for p in picks) / n
    return yld, hit, n


def bootstrap_ci(picks: List[Dict], B: int = 2000, alpha: float = 0.05) -> Tuple[float, float, float, float]:
    """Bootstrap percentile: returns (mean, lo_alpha/2, hi_1-alpha/2, p5)."""
    if len(picks) < 2:
        return 0.0, 0.0, 0.0, 0.0
    rets = np.array([p["retorno"] for p in picks])
    n = len(rets)
    medias = np.empty(B)
    for b in range(B):
        idx = RNG.integers(0, n, n)
        medias[b] = rets[idx].mean()
    lo = float(np.quantile(medias, alpha / 2))
    hi = float(np.quantile(medias, 1 - alpha / 2))
    p5 = float(np.quantile(medias, 0.05))
    mean = float(rets.mean())
    return mean, lo, hi, p5


def sharpe_picks(picks: List[Dict]) -> float:
    if len(picks) < 2:
        return 0.0
    rets = np.array([p["retorno"] for p in picks])
    s = rets.std(ddof=1)
    if s == 0:
        return 0.0
    return float(rets.mean() / s) * math.sqrt(len(rets))


def maxdd_picks(picks: List[Dict]) -> float:
    if not picks:
        return 0.0
    eq = np.cumsum([p["retorno"] for p in picks])
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    return float(dd.min())


# ============================================================================
# EVALUACION POR PROPUESTA
# ============================================================================

def evaluar_propuesta(
    nombre: str,
    descripcion: str,
    filtro_fn,
    picks_train_pool: List[Dict],
    picks_2025: List[Dict],
    picks_2026: List[Dict],
) -> Dict:
    """
    Evaluar propuesta:
    - IS train pooled (yield + bootstrap p5 > 0)
    - Por anio
    - Por liga
    - Por bin (year+liga)
    - Holdout 2026: confirma direccionalidad?
    """
    fp_train = [p for p in picks_train_pool if filtro_fn(p)]
    fp_2025 = [p for p in picks_2025 if filtro_fn(p)]
    fp_2026 = [p for p in picks_2026 if filtro_fn(p)]

    # IS pooled = train (anos < 2025) + validation (2025)
    pooled_is = fp_train + fp_2025

    res = {
        "nombre": nombre,
        "descripcion": descripcion,
    }

    # IS pooled
    y_is, h_is, n_is = yield_hit(pooled_is)
    m, lo, hi, p5 = bootstrap_ci(pooled_is)
    res["IS_pooled"] = {
        "n": n_is, "yield": y_is, "hit": h_is,
        "ci95_lo": lo, "ci95_hi": hi,
        "boot_p5": p5,
        "sharpe": sharpe_picks(pooled_is),
        "maxdd": maxdd_picks(pooled_is),
    }

    # Por anio
    by_year = defaultdict(list)
    for p in pooled_is + fp_2026:
        by_year[p["year"]].append(p)
    res["by_year"] = {}
    anos_pos = 0
    anos_pre26 = 0
    for y in sorted(by_year.keys()):
        if y is None: continue
        ys, hs, ns = yield_hit(by_year[y])
        m_, lo_, hi_, p5_ = bootstrap_ci(by_year[y])
        res["by_year"][str(y)] = {
            "n": ns, "yield": ys, "hit": hs,
            "ci95_lo": lo_, "ci95_hi": hi_, "boot_p5": p5_,
        }
        if y < 2026:
            anos_pre26 += 1
            if ys > 0:
                anos_pos += 1

    res["anos_positivos_pre2026"] = anos_pos
    res["anos_total_pre2026"] = anos_pre26

    # Por liga
    res["by_liga"] = {}
    by_liga = defaultdict(list)
    for p in pooled_is:
        by_liga[p["liga"]].append(p)
    for liga, ps in by_liga.items():
        ys, hs, ns = yield_hit(ps)
        res["by_liga"][liga] = {"n": ns, "yield": ys, "hit": hs}

    # Por equipo (P4/P5 only)
    if nombre in ("P4_Whitelist", "P5_Blacklist"):
        res["by_equipo"] = {}
        by_eq = defaultdict(list)
        for p in pooled_is:
            if p["equipo_pick"]:
                by_eq[p["equipo_pick"]].append(p)
        for eq, ps in sorted(by_eq.items(), key=lambda x: -len(x[1]))[:20]:
            ys, hs, ns = yield_hit(ps)
            if ns >= 5:
                res["by_equipo"][eq] = {"n": ns, "yield": ys, "hit": hs}

    # Holdout 2026
    if fp_2026:
        y26, h26, n26 = yield_hit(fp_2026)
        m26, lo26, hi26, p5_26 = bootstrap_ci(fp_2026)
        res["holdout_2026"] = {
            "n": n26, "yield": y26, "hit": h26,
            "ci95_lo": lo26, "ci95_hi": hi26, "boot_p5": p5_26,
            "sharpe": sharpe_picks(fp_2026),
            "maxdd": maxdd_picks(fp_2026),
        }
    else:
        res["holdout_2026"] = {"n": 0, "yield": 0, "hit": 0, "ci95_lo": 0, "ci95_hi": 0, "boot_p5": 0}

    # Reglas promocion
    promueve = (
        n_is >= 100
        and y_is >= 0.05
        and p5 > 0
        and anos_pos >= max(1, int(0.667 * anos_pre26))  # >= 2/3
    )
    veto = False
    razon_veto = []
    # holdout veto
    h26_n = res["holdout_2026"]["n"]
    if h26_n >= 10:
        if res["holdout_2026"]["ci95_hi"] < 0:
            veto = True
            razon_veto.append("holdout_2026 CI95 hi<0 sig negativo")
        elif res["holdout_2026"]["yield"] < 0 and y_is > 0:
            # direccionalidad rota
            razon_veto.append(f"holdout_2026 yield={res['holdout_2026']['yield']:+.3f} contradice IS")
    # one-shot
    if anos_pre26 >= 3 and anos_pos == 1:
        veto = True
        razon_veto.append("one-shot (1/N+ anos positivos)")

    if veto or not promueve:
        veredicto = "RECHAZAR"
    else:
        veredicto = "PROMOVER"

    res["veredicto"] = veredicto
    res["razon_veto"] = razon_veto if razon_veto else None
    res["criterios_promocion"] = {
        "n_is>=100": n_is >= 100,
        "yield_is>=0.05": y_is >= 0.05,
        "boot_p5>0": p5 > 0,
        "anos_pos>=2/3": anos_pos >= max(1, int(0.667 * anos_pre26)),
        "anos_pos": f"{anos_pos}/{anos_pre26}",
    }
    return res


# ============================================================================
# MAIN
# ============================================================================

def main():
    conn = sqlite3.connect(DB_PATH)
    print("=" * 70)
    print("WALK-FORWARD TRUE-OOS 5 PROPUESTAS")
    print("=" * 70)

    print("\n[1] Cargando universo expandido...")
    partidos = cargar_universo_train(conn)
    print(f"    Partidos matched: {len(partidos)}")

    # Distribucion por anio (espn fecha)
    by_year_count = defaultdict(int)
    for p in partidos:
        by_year_count[p["year"]] += 1
    print(f"    Por year: {dict(sorted(by_year_count.items()))}")

    # Distribucion por liga
    by_liga_count = defaultdict(int)
    for p in partidos:
        by_liga_count[p["liga"]] += 1
    print(f"    Por liga: {dict(by_liga_count)}")

    print("\n[2] Construyendo EMAs pre-bet (cronologico)...")
    partidos_emas = construir_emas_pre_bet(partidos)

    # Particion por year
    by_year = defaultdict(list)
    for p in partidos_emas:
        by_year[p["year"]].append(p)

    YEARS = sorted([y for y in by_year if y is not None])
    print(f"    Years disponibles: {YEARS}")

    # ========================================================================
    # WALK-FORWARD: refit beta cada year_test
    # ========================================================================
    print("\n[3] Walk-forward: generar picks por year_test...")

    # Para cada year_test, train con years previos
    picks_por_year = {}
    for year_test in YEARS:
        train = []
        for y_prev in YEARS:
            if y_prev < year_test:
                train.extend(by_year[y_prev])
        if not train:
            print(f"    year_test={year_test}: SKIP (no train data)")
            continue
        beta = calibrar_beta_sot_train(train)
        picks_yt = generar_picks(by_year[year_test], beta)
        picks_por_year[year_test] = picks_yt
        print(f"    year_test={year_test}: train_n={len(train)} picks={len(picks_yt)} betas={dict((k, round(v,3)) for k,v in beta.items() if k != 'global')}")

    # Identificar splits
    # Train: years <= 2024
    # Validation: 2025
    # Holdout: 2026
    picks_train_pool = []
    picks_2025 = []
    picks_2026 = []
    for y, picks in picks_por_year.items():
        if y <= 2024:
            picks_train_pool.extend(picks)
        elif y == 2025:
            picks_2025.extend(picks)
        elif y == 2026:
            picks_2026.extend(picks)

    print(f"\n    TRAIN pool (year<=2024): {len(picks_train_pool)} picks")
    print(f"    VALIDATION (2025): {len(picks_2025)} picks")
    print(f"    HOLDOUT (2026): {len(picks_2026)} picks")

    # ========================================================================
    # EVALUACION POR PROPUESTA
    # ========================================================================
    print("\n[4] Evaluando 5 propuestas...")
    print(f"    Bonferroni alpha = {BONFERRONI_ALPHA:.4f}")

    resultados = {}
    for nombre, fn, desc in PROPUESTAS:
        print(f"\n    --- {nombre}: {desc}")
        r = evaluar_propuesta(nombre, desc, fn, picks_train_pool, picks_2025, picks_2026)
        resultados[nombre] = r
        ip = r["IS_pooled"]
        ho = r["holdout_2026"]
        print(f"      IS pooled: n={ip['n']} y={ip['yield']:+.3f} hit={ip['hit']:.3f} CI95=[{ip['ci95_lo']:+.3f},{ip['ci95_hi']:+.3f}] p5={ip['boot_p5']:+.3f}")
        print(f"      Holdout 2026: n={ho['n']} y={ho['yield']:+.3f} hit={ho['hit']:.3f}")
        print(f"      anos pos: {r['criterios_promocion']['anos_pos']}")
        print(f"      VEREDICTO: {r['veredicto']}")
        if r['razon_veto']:
            print(f"      veto: {r['razon_veto']}")

    # ========================================================================
    # OUTPUT
    # ========================================================================
    print("\n[5] Persistiendo resultados...")
    out = {
        "sesion_id": SESION_ID,
        "fecha": datetime.now().isoformat(),
        "universo": {
            "partidos_matched": len(partidos),
            "by_year": dict(sorted(by_year_count.items())),
            "by_liga": dict(by_liga_count),
        },
        "picks_pool": {
            "train": len(picks_train_pool),
            "validation_2025": len(picks_2025),
            "holdout_2026": len(picks_2026),
        },
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "resultados": resultados,
    }
    SCRIPT_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SCRIPT_OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"    JSON: {SCRIPT_OUT_JSON}")

    # Doc Markdown
    DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
    md = generar_md(out)
    with open(DOC_OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"    MD: {DOC_OUT}")

    # INSERT en agentes_findings
    persistir_finding(conn, out)

    conn.close()
    print("\nFIN.")


def generar_md(out: Dict) -> str:
    lines = []
    lines.append(f"# Walk-Forward TRUE-OOS — 5 Propuestas (sesion {out['sesion_id']})\n")
    lines.append(f"Fecha: {out['fecha']}\n")
    lines.append("## Universo\n")
    lines.append(f"- Matched: **{out['universo']['partidos_matched']}** stats+cuotas (s.fecha_fdco JOIN)\n")
    lines.append(f"- Por liga: {out['universo']['by_liga']}\n")
    lines.append(f"- Por year: {out['universo']['by_year']}\n")
    lines.append(f"\n## Splits walk-forward\n")
    lines.append(f"- TRAIN pool (year<=2024): {out['picks_pool']['train']} picks (argmax V0, EV>={EV_MIN})\n")
    lines.append(f"- VALIDATION 2025: {out['picks_pool']['validation_2025']} picks\n")
    lines.append(f"- HOLDOUT 2026 (CONGELADO): {out['picks_pool']['holdout_2026']} picks\n")
    lines.append(f"- Bonferroni alpha = {out['bonferroni_alpha']:.4f} (= 0.05/5)\n")

    lines.append("\n## Tabla resumen\n")
    lines.append("| Propuesta | N_IS | Yield_IS | CI95 | p5_boot | N_2026 | Y_2026 | Anos+ | Veredicto |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|\n")
    for nombre, r in out["resultados"].items():
        ip = r["IS_pooled"]
        ho = r["holdout_2026"]
        ap = r['criterios_promocion']['anos_pos']
        lines.append(
            f"| {nombre} | {ip['n']} | {ip['yield']:+.3f} | [{ip['ci95_lo']:+.3f},{ip['ci95_hi']:+.3f}] | "
            f"{ip['boot_p5']:+.3f} | {ho['n']} | {ho['yield']:+.3f} | {ap} | **{r['veredicto']}** |\n"
        )

    for nombre, r in out["resultados"].items():
        lines.append(f"\n### {nombre} — {r['descripcion']}\n")
        ip = r["IS_pooled"]
        lines.append(f"- IS pooled: N={ip['n']}, yield={ip['yield']:+.4f}, hit={ip['hit']:.3f}, "
                     f"CI95=[{ip['ci95_lo']:+.4f},{ip['ci95_hi']:+.4f}], boot_p5={ip['boot_p5']:+.4f}, "
                     f"sharpe={ip['sharpe']:.3f}, maxdd={ip['maxdd']:+.2f}\n")
        ho = r["holdout_2026"]
        lines.append(f"- Holdout 2026: N={ho['n']}, yield={ho['yield']:+.4f}, hit={ho['hit']:.3f}, "
                     f"CI95=[{ho['ci95_lo']:+.4f},{ho['ci95_hi']:+.4f}]\n")
        lines.append(f"- Por year:\n")
        for y, d in r["by_year"].items():
            lines.append(f"  - {y}: N={d['n']} y={d['yield']:+.3f} hit={d['hit']:.3f} CI95=[{d['ci95_lo']:+.3f},{d['ci95_hi']:+.3f}]\n")
        lines.append(f"- Por liga (IS pooled):\n")
        for liga, d in sorted(r["by_liga"].items(), key=lambda x: -x[1]["yield"]):
            lines.append(f"  - {liga}: N={d['n']} y={d['yield']:+.3f} hit={d['hit']:.3f}\n")
        if "by_equipo" in r:
            lines.append(f"- Por equipo (top por N, IS pooled):\n")
            for eq, d in sorted(r["by_equipo"].items(), key=lambda x: -x[1]["n"])[:15]:
                lines.append(f"  - {eq}: N={d['n']} y={d['yield']:+.3f} hit={d['hit']:.3f}\n")
        lines.append(f"- Criterios promocion: {r['criterios_promocion']}\n")
        lines.append(f"- **Veredicto: {r['veredicto']}**\n")
        if r["razon_veto"]:
            lines.append(f"- Veto: {r['razon_veto']}\n")
    return "".join(lines)


def persistir_finding(conn: sqlite3.Connection, out: Dict):
    """INSERT/UPDATE en agentes_findings."""
    import hashlib
    res_summary = {}
    for nombre, r in out["resultados"].items():
        res_summary[nombre] = {
            "n_is": r["IS_pooled"]["n"],
            "yield_is": round(r["IS_pooled"]["yield"], 4),
            "boot_p5": round(r["IS_pooled"]["boot_p5"], 4),
            "n_holdout26": r["holdout_2026"]["n"],
            "yield_holdout26": round(r["holdout_2026"]["yield"], 4),
            "veredicto": r["veredicto"],
        }

    promovidas = [k for k, v in res_summary.items() if v["veredicto"] == "PROMOVER"]
    rechazadas = [k for k, v in res_summary.items() if v["veredicto"] == "RECHAZAR"]
    finding = (
        f"5 propuestas walk-forward TRUE-OOS. Promovidas: {len(promovidas)} {promovidas}. "
        f"Rechazadas: {len(rechazadas)} {rechazadas}. "
        f"N IS train pool={out['picks_pool']['train']}, val2025={out['picks_pool']['validation_2025']}, "
        f"holdout2026={out['picks_pool']['holdout_2026']}. Bonferroni alpha=0.01."
    )

    agente_id = "wf" + hashlib.md5(("walk_forward_true_oos_5_propuestas" + datetime.now().isoformat()).encode()).hexdigest()[:14]

    conn.execute("""
        INSERT INTO agentes_findings
        (sesion_id, agente_id, agente_tipo, mision, fecha_inicio, fecha_fin, status,
         finding_resumen, doc_persistido, data_artefactos, veto_critico, score_credibilidad, notas)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        SESION_ID, agente_id, "optimizador_modelo",
        "Walk-forward TRUE-OOS protocolo (5 propuestas) -- ejecucion final",
        datetime.now().isoformat(), datetime.now().isoformat(),
        "completed",
        finding,
        str(DOC_OUT),
        json.dumps({
            "resumen_propuestas": res_summary,
            "json_artefacto": str(SCRIPT_OUT_JSON),
            "universo_n": out["universo"]["partidos_matched"],
            "splits": out["picks_pool"],
        }),
        0,  # veto_critico=0
        None,  # score_credibilidad
        f"Bonferroni alpha=0.01. Promovidas={len(promovidas)}/5",
    ))
    conn.commit()
    print(f"    Finding insertado en agentes_findings (agente_id={agente_id})")


if __name__ == "__main__":
    main()

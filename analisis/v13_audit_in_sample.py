"""adepor-3ip Audit IN-SAMPLE V13: aplicar V13 extended sobre picks reales 2026-03/04.

Pregunta del usuario: como funcionaria V13 in-sample real?

Pipeline:
1. Cargar picks reales de Backtest_Modelo.xlsx hoja 'Si Hubiera' (N=358).
2. Para cada pick (liga, fecha, local, visita, cuota, resultado real):
   - Si liga in V13 elegibles (Arg, Fra, Ita, Ing actualmente): aplicar V13.
   - Calcular xG_l, xG_v V13 -> probs DC -> pick + cuota -> profit.
3. Comparar:
   - V0 (real): yield reportado por motor productivo.
   - V13: yield contrafactual con V13 BEST por liga.
   - V13 stake real: si V13 hubiera sido el motor, cual habria sido el stake/PL?

Limitacion: V13 SOLO aplica si liga elegible Y EMAs disponibles.
Las ligas TOP-5 V5.1 actualmente: Argentina, Brasil, Inglaterra, Noruega, Turquia.
Intersection con V13 elegibles: SOLO Argentina + Inglaterra (Francia/Italia no en TOP-5).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Backtest_Modelo.xlsx"
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "v13_audit_in_sample.json"

RHO_FALLBACK = -0.09


def parse_fecha(s):
    if not s: return None
    try:
        return datetime.strptime(str(s), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


def cargar_picks_reales():
    """Carga picks de hoja 'Si Hubiera'."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha = parse_fecha(row[0])
        if fecha is None: continue
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"): continue
        partido = row[1] or ""
        local, visita = None, None
        for sep in [" vs ", " - ", " v ", "-"]:
            if sep in partido:
                parts = partido.split(sep, 1)
                if len(parts) == 2:
                    local = parts[0].strip()
                    visita = parts[1].strip()
                    break
        picks.append({
            "fecha": fecha, "fecha_str": fecha.isoformat(),
            "partido": partido, "local": local, "visita": visita,
            "liga": row[2], "pick": row[3], "cuota": row[4] or 0,
            "camino": row[5], "resultado": resultado,
            "stake": row[8] or 0, "pl": row[9] or 0,
        })
    return picks


# === Replica de _calcular_xg_v13 + helpers (offline para no importar motor entero) ===
def cargar_v13_coefs(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, target, intercept, coefs_json, r2_oos, metodo, feature_set
        FROM v13_coef_por_liga
        WHERE (liga, target, calibrado_en) IN (
            SELECT liga, target, MAX(calibrado_en)
            FROM v13_coef_por_liga
            GROUP BY liga, target
        )
        AND metodo IS NOT NULL
    """).fetchall()
    out = {}
    for liga, t, intercept, coefs_json, r2, metodo, fset in rows:
        out.setdefault(liga, {})[t] = {
            "intercept": float(intercept),
            "coefs": json.loads(coefs_json),
            "r2_oos": r2, "metodo": metodo, "feature_set": fset,
        }
    return out


_V13_FEATURE_SETS = {
    "F1_off": ["atk_sots", "atk_shot_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c"],
    "F2_pos": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c"],
    "F3_def": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c", "def_tackles_c", "def_blocks_c"],
    "F4_disc": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
                "atk_yellow", "atk_red", "atk_fouls",
                "def_sots_c", "def_shot_pct_c"],
    "F5_ratio": ["atk_sots_per_shot", "atk_pressure", "atk_set_piece",
                 "atk_red_card_rate", "def_solidez"],
    "F6_full": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
                "atk_yellow", "atk_red", "atk_fouls",
                "atk_sots_per_shot", "atk_pressure", "atk_red_card_rate",
                "def_sots_c", "def_shot_pct_c", "def_solidez"],
}

_EMA_COLS = ["ema_l_sots", "ema_l_shot_pct", "ema_l_pos", "ema_l_pass_pct",
             "ema_l_corners", "ema_l_yellow", "ema_l_red", "ema_l_fouls",
             "ema_l_shots", "ema_c_sots", "ema_c_shot_pct", "ema_c_tackles",
             "ema_c_blocks", "ema_c_yellow"]


def _feat_value(name, ema_atk, ema_def):
    try:
        if name == "atk_sots":      return ema_atk["ema_l_sots"]
        if name == "atk_shot_pct":  return ema_atk["ema_l_shot_pct"]
        if name == "atk_pos":       return ema_atk["ema_l_pos"]
        if name == "atk_pass_pct":  return ema_atk["ema_l_pass_pct"]
        if name == "atk_corners":   return ema_atk["ema_l_corners"]
        if name == "atk_yellow":    return ema_atk["ema_l_yellow"]
        if name == "atk_red":       return ema_atk["ema_l_red"]
        if name == "atk_fouls":     return ema_atk["ema_l_fouls"]
        if name == "def_sots_c":    return ema_def["ema_c_sots"]
        if name == "def_shot_pct_c":return ema_def["ema_c_shot_pct"]
        if name == "def_tackles_c": return ema_def["ema_c_tackles"]
        if name == "def_blocks_c":  return ema_def["ema_c_blocks"]
        if name == "atk_sots_per_shot":
            sh = ema_atk.get("ema_l_shots")
            if sh is None or sh == 0: return 0.4
            return float(ema_atk["ema_l_sots"]) / float(sh)
        if name == "atk_pressure":
            return float(ema_atk["ema_l_pos"]) * float(ema_atk["ema_l_shot_pct"]) / 100.0
        if name == "atk_set_piece":
            return float(ema_atk["ema_l_corners"])
        if name == "atk_red_card_rate":
            f = ema_atk.get("ema_l_fouls")
            if f is None or f == 0: return 0.0
            return float(ema_atk["ema_l_red"]) / float(f)
        if name == "def_solidez":
            return float(ema_def["ema_c_tackles"]) + float(ema_def["ema_c_blocks"])
        return None
    except Exception: return None


def calcular_xg_v13(coefs_v13, liga, atacante, defensor, fecha_str, con, target_local=True):
    cf_liga = coefs_v13.get(liga)
    if not cf_liga: return None
    tgt = "local" if target_local else "visita"
    cf = cf_liga.get(tgt)
    if not cf: return None
    fset = _V13_FEATURE_SETS.get(cf["feature_set"])
    if not fset: return None
    try:
        cur = con.cursor()
        cols_sql = ", ".join(_EMA_COLS)
        r_atk = cur.execute(f"""SELECT {cols_sql} FROM historial_equipos_stats
                                 WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
                                 ORDER BY fecha DESC LIMIT 1""", (liga, atacante, fecha_str)).fetchone()
        r_def = cur.execute(f"""SELECT {cols_sql} FROM historial_equipos_stats
                                 WHERE liga=? AND equipo=? AND fecha<? AND n_acum>=5
                                 ORDER BY fecha DESC LIMIT 1""", (liga, defensor, fecha_str)).fetchone()
        if not r_atk or not r_def: return None
        ema_atk = dict(zip(_EMA_COLS, r_atk))
        ema_def = dict(zip(_EMA_COLS, r_def))
        feats = []
        for n in fset:
            v = _feat_value(n, ema_atk, ema_def)
            if v is None: return None
            feats.append(float(v))
        coefs = [cf["coefs"].get(n, 0.0) for n in fset]
        pred = cf["intercept"] + sum(f * c for f, c in zip(feats, coefs))
        return max(0.10, float(pred))
    except Exception: return None


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


def kelly_fraction(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick_v13(p1, px, p2, cuota, outcome_real_label, label_pick_motor):
    """V13 evalua el pick. Si V13 hubiera apostado, ¿coincide su pick con el real?
    Si V13 dice argmax distinto, hace pick distinto (o pasa).
    Aqui asumimos misma logica que motor: argmax con gap >= 5%, EV >= 3%.

    Returns (pick_v13, prob_v13, decision: 'APOSTAR' o 'PASAR', stake_v13, profit_si_apostara)

    Para audit: usar la cuota REAL del bookie y outcome real para determinar profit.
    """
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05:
        return None  # PASAR por margen
    opts = [("LOCAL", p1), ("EMPATE", px), ("VISITA", p2)]
    label, prob = max(opts, key=lambda x: x[1])
    # Aqui usamos la cuota REAL del partido (la que el motor productivo tomo)
    # para mantener comparacion vs in-sample real.
    if not cuota or cuota <= 1.0: return None
    if prob * cuota - 1 < 0.03: return None
    stake = kelly_fraction(prob, cuota, cap=0.025)
    if stake <= 0: return None
    # Necesitamos saber si el pick de V13 gana segun outcome real
    # outcome_real_label viene del motor (ya esta en la hoja Si Hubiera): "GANADA" o "PERDIDA"
    # PERO esto depende de SI el pick de V13 coincide con el pick del motor.
    # Estrategia 1: si V13 dice mismo pick que motor -> usar outcome_real_label.
    # Estrategia 2: si V13 dice otro -> calcular outcome con la cuota tirada, asumir que ganamos
    #              solo si outcome real = nuestro pick.
    # NOTA: la hoja Si Hubiera no nos dice outcome real (1/X/2), solo si el pick del motor gano.
    # Asumimos que pick_v13 == pick_motor para simplificar (caso comun: misma logica con xG distinto).
    # Si pick_v13 != pick_motor, no podemos saber sin outcome real.
    return {"label": label, "prob": prob, "stake": stake, "cuota": cuota}


# === Pick original del motor (label esperado) ===
PICK_LABEL_NORMALIZADO = {
    "1": "LOCAL", "X": "EMPATE", "2": "VISITA",
    "LOCAL": "LOCAL", "EMPATE": "EMPATE", "VISITA": "VISITA",
    "Local": "LOCAL", "Empate": "EMPATE", "Visita": "VISITA",
}


def yield_metrics_real(picks):
    """Para subset de picks (con stake>0 si aplica). Devuelve metrics agg + bootstrap."""
    n_apost = len(picks)
    n_gano = sum(1 for p in picks if p.get("gano"))
    sum_stake = sum(p["stake"] for p in picks)
    sum_pl = sum(p["profit"] for p in picks)
    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
    hit = n_gano / n_apost * 100 if n_apost > 0 else 0
    if picks:
        rng = np.random.default_rng(42)
        sk = np.array([p["stake"] for p in picks])
        pr = np.array([p["profit"] for p in picks])
        ys = []
        for _ in range(1000):
            idx = rng.integers(0, len(picks), size=len(picks))
            ss, pp = sk[idx].sum(), pr[idx].sum()
            if ss > 0: ys.append(pp / ss * 100)
        lo = float(np.percentile(ys, 2.5)) if ys else None
        hi = float(np.percentile(ys, 97.5)) if ys else None
    else:
        lo = hi = None
    return {"n_apost": n_apost, "n_gano": n_gano,
            "hit_pct": round(hit, 2), "yield_pct": round(yld, 2),
            "sum_stake": round(sum_stake, 2), "sum_pl": round(sum_pl, 2),
            "ci95_lo": round(lo, 2) if lo is not None else None,
            "ci95_hi": round(hi, 2) if hi is not None else None}


def main():
    print("Cargando picks reales 2026-03/04...")
    picks = cargar_picks_reales()
    print(f"  N picks reales: {len(picks)}")

    con = sqlite3.connect(DB)
    coefs_v13 = cargar_v13_coefs(con)
    ligas_elegibles = sorted(coefs_v13.keys())
    print(f"  Ligas V13 elegibles: {ligas_elegibles}")
    print()

    # === Audit V13: aplicar V13 a cada pick ===
    print("=== Aplicando V13 a picks reales (donde aplica) ===")
    v13_picks = []
    no_aplica = []
    for p in picks:
        if not p["liga"] or not p["local"] or not p["visita"]:
            no_aplica.append({**p, "razon": "datos faltantes"})
            continue
        if p["liga"] not in ligas_elegibles:
            no_aplica.append({**p, "razon": f"liga {p['liga']} no elegible V13"})
            continue
        xg_l = calcular_xg_v13(coefs_v13, p["liga"], p["local"], p["visita"], p["fecha_str"], con, True)
        xg_v = calcular_xg_v13(coefs_v13, p["liga"], p["visita"], p["local"], p["fecha_str"], con, False)
        if xg_l is None or xg_v is None:
            no_aplica.append({**p, "razon": "EMA pre-partido falta"})
            continue
        p1, px, p2 = probs_dc(xg_l, xg_v)
        # Pick logic: argmax con gap >=5%, EV>=3%, K cap 2.5%
        s = sorted([p1, px, p2], reverse=True)
        if s[0] - s[1] < 0.05:
            v13_picks.append({**p, "v13_decision": "PASAR_margen", "v13_pick": None,
                              "v13_xg_l": xg_l, "v13_xg_v": xg_v})
            continue
        opts = [("LOCAL", p1), ("EMPATE", px), ("VISITA", p2)]
        label_v13, prob_v13 = max(opts, key=lambda x: x[1])
        cuota = float(p["cuota"]) if p["cuota"] else 0
        if cuota <= 1.0 or prob_v13 * cuota - 1 < 0.03:
            v13_picks.append({**p, "v13_decision": "PASAR_ev_min", "v13_pick": label_v13,
                              "v13_prob": prob_v13, "v13_xg_l": xg_l, "v13_xg_v": xg_v})
            continue
        stake_v13 = kelly_fraction(prob_v13, cuota, cap=0.025)
        if stake_v13 <= 0:
            v13_picks.append({**p, "v13_decision": "PASAR_kelly", "v13_pick": label_v13,
                              "v13_xg_l": xg_l, "v13_xg_v": xg_v})
            continue

        # V13 apostaria. Comparar con pick_motor (el real que se aposto en producción).
        pick_motor_norm = PICK_LABEL_NORMALIZADO.get(p["pick"], p["pick"])
        v13_apostar_mismo = (label_v13 == pick_motor_norm)

        if v13_apostar_mismo:
            # V13 coincide con motor: usar resultado real
            gano = (p["resultado"] == "GANADA")
            profit_v13 = stake_v13 * (cuota - 1) if gano else -stake_v13
        else:
            # V13 dice otro pick. No tenemos outcome real para ese pick distinto,
            # pero como el resultado del motor con SU pick es disjoint, podemos inferir:
            # Si motor GANO (su pick fue correcto), entonces el pick distinto de V13 perdio.
            # Si motor PERDIO (su pick fue incorrecto), V13 PUEDE haber ganado o perdido,
            # depende del outcome real (1/X/2). No lo tenemos.
            # Asumir que V13 perdio (caso conservador).
            if p["resultado"] == "GANADA":
                gano = False
                profit_v13 = -stake_v13
            else:
                # V13 PUEDE haber ganado (50/50 incertidumbre real)
                # Asumir empate (es probabilistico). Mejor tratarlo como "incierto".
                gano = None
                profit_v13 = None  # no contable

        v13_picks.append({
            **p, "v13_decision": "APOSTAR",
            "v13_pick": label_v13, "v13_prob": prob_v13,
            "v13_stake_pct": stake_v13,
            "v13_xg_l": xg_l, "v13_xg_v": xg_v,
            "v13_apuesta_misma_q_motor": v13_apostar_mismo,
            "v13_gano": gano, "v13_profit_norm": profit_v13,
        })

    # Métricas
    print(f"  V13 apostarian (decision=APOSTAR): {sum(1 for p in v13_picks if p.get('v13_decision') == 'APOSTAR')}")
    print(f"  V13 PASAR: {sum(1 for p in v13_picks if p.get('v13_decision', '').startswith('PASAR'))}")
    print(f"  No aplica V13 (liga/EMA): {len(no_aplica)}")
    print()

    # Yield V0 real (motor produccion) sobre el subset que V13 podria evaluar
    subset_evaluable = [p for p in v13_picks if p.get("v13_decision") == "APOSTAR" and p.get("v13_profit_norm") is not None]

    print(f"=== Subset comparable: V13 APOSTAR + outcome contable (N={len(subset_evaluable)}) ===")
    if subset_evaluable:
        # V0 (real)
        v0_picks_real = [{
            "stake": float(p["stake"]) if p["stake"] else 0,
            "profit": float(p["pl"]) if p["pl"] else 0,
            "gano": p["resultado"] == "GANADA",
        } for p in subset_evaluable if p["stake"] > 0]
        v0_unitario = [{
            "stake": 1.0,
            "profit": (float(p["cuota"]) - 1) if p["resultado"] == "GANADA" else -1.0,
            "gano": p["resultado"] == "GANADA",
        } for p in subset_evaluable]
        v0_real_metrics = yield_metrics_real(v0_picks_real)
        v0_unit_metrics = yield_metrics_real(v0_unitario)
        # V13 sobre mismo subset (unitario, asumiendo stake=1)
        v13_unitario = [{
            "stake": p["v13_stake_pct"],
            "profit": p["v13_profit_norm"],
            "gano": p["v13_gano"],
        } for p in subset_evaluable]
        v13_unit_metrics = yield_metrics_real(v13_unitario)

        print(f"\n{'arch':<25} {'N':>4} {'Hit%':>6} {'Yield%':>8} {'CI95':>22}")
        print(f"{'V0 real (stake $)':<25} {v0_real_metrics['n_apost']:>4} {v0_real_metrics['hit_pct']:>6.1f} {v0_real_metrics['yield_pct']:>+8.1f} [{v0_real_metrics['ci95_lo']:>+5.1f},{v0_real_metrics['ci95_hi']:>+5.1f}]")
        print(f"{'V0 unitario':<25} {v0_unit_metrics['n_apost']:>4} {v0_unit_metrics['hit_pct']:>6.1f} {v0_unit_metrics['yield_pct']:>+8.1f} [{v0_unit_metrics['ci95_lo']:>+5.1f},{v0_unit_metrics['ci95_hi']:>+5.1f}]")
        print(f"{'V13 unitario (Kelly)':<25} {v13_unit_metrics['n_apost']:>4} {v13_unit_metrics['hit_pct']:>6.1f} {v13_unit_metrics['yield_pct']:>+8.1f} [{v13_unit_metrics['ci95_lo']:>+5.1f},{v13_unit_metrics['ci95_hi']:>+5.1f}]")

    # Por liga
    print(f"\n=== Por liga V13 elegibles ===")
    print(f"{'liga':<14} {'N apost V0':>11} {'Yield V0':>9} {'N V13':>6} {'Yield V13':>10} {'V13 igual%':>11}")
    por_liga = {}
    for liga in ligas_elegibles:
        sub_liga = [p for p in v13_picks if p["liga"] == liga and p.get("v13_decision") == "APOSTAR" and p.get("v13_profit_norm") is not None]
        if not sub_liga: continue
        v0_picks = [{"stake": 1.0, "profit": (float(p["cuota"])-1) if p["resultado"]=="GANADA" else -1.0,
                     "gano": p["resultado"]=="GANADA"} for p in sub_liga]
        v13_picks_l = [{"stake": p["v13_stake_pct"], "profit": p["v13_profit_norm"],
                       "gano": p["v13_gano"]} for p in sub_liga]
        m_v0 = yield_metrics_real(v0_picks)
        m_v13 = yield_metrics_real(v13_picks_l)
        coincidencia = sum(1 for p in sub_liga if p.get("v13_apuesta_misma_q_motor")) / len(sub_liga) * 100
        print(f"{liga:<14} {m_v0['n_apost']:>11} {m_v0['yield_pct']:>+8.1f}% {m_v13['n_apost']:>6} {m_v13['yield_pct']:>+9.1f}% {coincidencia:>10.1f}%")
        por_liga[liga] = {"v0": m_v0, "v13": m_v13, "coincidencia_pick_pct": coincidencia}

    # Razones de PASAR V13
    print(f"\n=== Razones V13 PASA (no apuesta) ===")
    razones = {}
    for p in v13_picks:
        d = p.get("v13_decision", "")
        if d.startswith("PASAR"):
            razones[d] = razones.get(d, 0) + 1
    for r, n in sorted(razones.items(), key=lambda x: -x[1]):
        print(f"  {r}: {n}")

    payload = {
        "fecha": datetime.now().isoformat(),
        "n_picks_total": len(picks),
        "ligas_v13_elegibles": ligas_elegibles,
        "n_v13_apostar": sum(1 for p in v13_picks if p.get('v13_decision') == 'APOSTAR'),
        "n_v13_pasar": sum(1 for p in v13_picks if p.get('v13_decision', '').startswith('PASAR')),
        "n_no_aplica": len(no_aplica),
        "subset_comparable": len(subset_evaluable),
        "metrics_global": {
            "v0_real_stake": v0_real_metrics if subset_evaluable else None,
            "v0_unitario": v0_unit_metrics if subset_evaluable else None,
            "v13_unitario_kelly": v13_unit_metrics if subset_evaluable else None,
        },
        "por_liga": por_liga,
        "razones_v13_pasar": razones,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

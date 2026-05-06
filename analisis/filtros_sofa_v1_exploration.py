"""
Fase 1.1 - Exploracion descriptiva filtros SOFA categorias A-J.

Pre-requisito: tabla `universo_filtros_sofa_v1` (correr filtros_sofa_v1_universo.py primero).

Para cada filtro candidato:
- Define condition (booleana) y pick implicito (1, X, 2 o O25 / U25)
- Computa yield pool, hit, N
- Bootstrap CI95 percentile (1000 resamples)

NOTA leakage: features pre-match (referee, formation, manager) NO requieren lag-1.
Stats partido + ratings + xG_shotmap requieren lag-1 (partido anterior MISMO equipo)
para evitar leakage.

Output:
- JSON `filtros_sofa_v1_exploration.json` con métricas crudas
"""
from __future__ import annotations
import sqlite3
import json
import math
import statistics
import random
from collections import defaultdict
from pathlib import Path

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
random.seed(42)

# ================== Helpers ==================

def bootstrap_ci(values: list[float], n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    mean_boots = []
    n = len(values)
    for _ in range(n_boot):
        sample = [values[random.randrange(n)] for _ in range(n)]
        mean_boots.append(sum(sample) / n)
    mean_boots.sort()
    lo = mean_boots[int(alpha / 2 * n_boot)]
    hi = mean_boots[int((1 - alpha / 2) * n_boot)]
    return (lo, hi)


def yield_metric(events: list[dict], pick_field: str) -> dict:
    """Computa yield pool sobre subset events filtrados, asumiendo pick = pick_field (yield_local, yield_visita, yield_empate, yield_o25...)."""
    vals = [e.get(pick_field) for e in events if e.get(pick_field) is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "yield_mean": None, "ci95_lo": None, "ci95_hi": None, "hit_rate": None}
    mean = sum(vals) / n
    hit_field = pick_field.replace("yield_", "hit_")
    hits = [e.get(hit_field) for e in events if e.get(hit_field) is not None]
    hit_rate = sum(hits) / len(hits) if hits else None
    lo, hi = bootstrap_ci(vals)
    return {
        "n": n,
        "yield_mean": mean,
        "ci95_lo": lo,
        "ci95_hi": hi,
        "hit_rate": hit_rate,
    }


# ================== Cargar universo + enriquecer ==================

def cargar_universo() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute("SELECT * FROM universo_filtros_sofa_v1").fetchall()
    return [dict(r) for r in rows]


def cargar_o25_yields(universo: list[dict]) -> None:
    """Enriquece eventos con hit_o25, yield_o25, hit_u25, yield_u25."""
    for e in universo:
        gl, gv = e["hg"], e["ag"]
        if gl is None or gv is None:
            continue
        total = gl + gv
        if e.get("cuota_o25"):
            hit_o = 1 if total > 2 else 0
            e["hit_o25"] = hit_o
            e["yield_o25"] = (e["cuota_o25"] - 1) if hit_o else -1
        if e.get("cuota_u25"):
            hit_u = 1 if total <= 2 else 0
            e["hit_u25"] = hit_u
            e["yield_u25"] = (e["cuota_u25"] - 1) if hit_u else -1


def construir_lag1_features(universo: list[dict]) -> None:
    """Para cada evento, busca partido anterior del MISMO equipo (local o visita) en universo SOFA
    + agrega features lag-1 como propiedades del evento.
    Usa fecha estricta (lag-1 = ultimo partido fecha < fecha_evento).
    """
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    sofa_all = cur.execute(
        """SELECT sofa_event_id, liga, fecha, ht, at,
                  big_chances_l, big_chances_v,
                  big_chances_missed_l, big_chances_missed_v,
                  shots_total_l, shots_total_v,
                  shots_on_target_l, shots_on_target_v,
                  shots_inside_box_l, shots_inside_box_v,
                  touches_penalty_area_l, touches_penalty_area_v,
                  errors_lead_to_shot_l, errors_lead_to_shot_v,
                  recoveries_l, recoveries_v,
                  ball_possession_l, ball_possession_v,
                  avg_rating_l, avg_rating_v,
                  max_rating_l, max_rating_v,
                  keeper_save_value_l, keeper_save_value_v,
                  xg_shotmap_l, xg_shotmap_v
           FROM sofascore_match_features WHERE error IS NULL"""
    ).fetchall()
    sofa_by_team = defaultdict(list)
    for r in sofa_all:
        d = dict(r)
        for side in ("l", "v"):
            equipo = d["ht"] if side == "l" else d["at"]
            sofa_by_team[(d["liga"], equipo)].append((d["fecha"][:10], side, d))

    for k in sofa_by_team:
        sofa_by_team[k].sort(key=lambda x: x[0])

    LAG_FIELDS = [
        "big_chances", "big_chances_missed", "shots_total", "shots_on_target",
        "shots_inside_box", "touches_penalty_area", "errors_lead_to_shot",
        "recoveries", "ball_possession", "avg_rating", "max_rating",
        "keeper_save_value", "xg_shotmap",
    ]

    for e in universo:
        for side in ("l", "v"):
            equipo = e["ht"] if side == "l" else e["at"]
            history = sofa_by_team.get((e["liga"], equipo), [])
            prev = None
            for h in history:
                if h[0] < e["fecha"]:
                    prev = h
                else:
                    break
            for f in LAG_FIELDS:
                if prev is None:
                    e[f"{f}_lag1_{side}"] = None
                else:
                    pside = prev[1]
                    e[f"{f}_lag1_{side}"] = prev[2].get(f"{f}_{pside}")


# ================== Definir filtros ==================

def filtros_definidos() -> list[dict]:
    """Lista de filtros candidatos. Cada filtro es dict con:
    - id: identificador
    - desc: descripcion
    - condition: callable(event) -> bool
    - pick_field: 'yield_local'|'yield_visita'|'yield_empate'|'yield_o25'|'yield_u25'
    """
    F = []

    # === A. Arbitros (PRE-match) ===
    def cards_per_game(e):
        if e["referee_games"] is None or e["referee_games"] < 5:
            return None
        if e["referee_yellows"] is None:
            return None
        return (e["referee_yellows"] + (e["referee_reds"] or 0)) / e["referee_games"]

    F.append({"id": "A1_strict_emp", "desc": "ref strict (cards/g>=6) -> empate",
              "condition": lambda e: (cards_per_game(e) is not None and cards_per_game(e) >= 6),
              "pick_field": "yield_empate"})
    F.append({"id": "A1_strict_o25", "desc": "ref strict (cards/g>=6) -> o25",
              "condition": lambda e: (cards_per_game(e) is not None and cards_per_game(e) >= 6),
              "pick_field": "yield_o25"})
    F.append({"id": "A2_red_freq_visita", "desc": "ref red/g>=0.30 -> visita",
              "condition": lambda e: (e["referee_games"] is not None and e["referee_games"] >= 5
                                      and (e["referee_reds"] or 0)/max(e["referee_games"],1) >= 0.30),
              "pick_field": "yield_visita"})
    F.append({"id": "A3_lax_local", "desc": "ref lax (cards/g<=4) -> local",
              "condition": lambda e: (cards_per_game(e) is not None and cards_per_game(e) <= 4),
              "pick_field": "yield_local"})
    F.append({"id": "A4_novel_neg", "desc": "ref novel (games<30) -> filtro NEG visita",
              "condition": lambda e: (e["referee_games"] is not None and e["referee_games"] < 30),
              "pick_field": "yield_local"})
    F.append({"id": "A4_novel_under", "desc": "ref novel (games<30) -> u25",
              "condition": lambda e: (e["referee_games"] is not None and e["referee_games"] < 30),
              "pick_field": "yield_u25"})

    # === B. Formaciones (PRE-match) ===
    def form_back(f: str | None) -> int | None:
        if not f or "-" not in f:
            return None
        try:
            return int(f.split("-")[0])
        except Exception:
            return None

    F.append({"id": "B1_3vs5_o25", "desc": "form 3-x vs 5-x -> o25",
              "condition": lambda e: (form_back(e["formation_l"]) == 3 and form_back(e["formation_v"]) == 5)
                                      or (form_back(e["formation_l"]) == 5 and form_back(e["formation_v"]) == 3),
              "pick_field": "yield_o25"})
    F.append({"id": "B2_4231_local", "desc": "local 4-2-3-1 vs 5-x -> local",
              "condition": lambda e: e["formation_l"] == "4-2-3-1" and form_back(e["formation_v"]) == 5,
              "pick_field": "yield_local"})
    F.append({"id": "B5_5atras_loc_neg_loc", "desc": "local 5-atras -> NO local (visita)",
              "condition": lambda e: form_back(e["formation_l"]) == 5,
              "pick_field": "yield_visita"})
    F.append({"id": "B5_5atras_loc_emp", "desc": "local 5-atras -> empate",
              "condition": lambda e: form_back(e["formation_l"]) == 5,
              "pick_field": "yield_empate"})
    F.append({"id": "B_3atras_loc_o25", "desc": "local 3-atras -> o25",
              "condition": lambda e: form_back(e["formation_l"]) == 3,
              "pick_field": "yield_o25"})
    F.append({"id": "B_4atras_balanc_local", "desc": "ambos 4-atras -> local",
              "condition": lambda e: form_back(e["formation_l"]) == 4 and form_back(e["formation_v"]) == 4,
              "pick_field": "yield_local"})

    # === C. Managers (PRE-match) - skipped per match-only; no histórico DT en SOFA ===
    # === D. Stats partido lag-1 ===
    def safe(v):
        return v if v is not None else 0

    F.append({"id": "D1_bcm_lag1_l_o25", "desc": "big_chances_missed_lag1_l>=3 -> o25",
              "condition": lambda e: safe(e.get("big_chances_missed_lag1_l")) >= 3,
              "pick_field": "yield_o25"})
    F.append({"id": "D1_bcm_lag1_v_o25", "desc": "big_chances_missed_lag1_v>=3 -> o25",
              "condition": lambda e: safe(e.get("big_chances_missed_lag1_v")) >= 3,
              "pick_field": "yield_o25"})
    F.append({"id": "D2_err_lag1_l_visita", "desc": "errors_lead_lag1_l>=2 -> visita",
              "condition": lambda e: safe(e.get("errors_lead_to_shot_lag1_l")) >= 2,
              "pick_field": "yield_visita"})
    F.append({"id": "D2_err_lag1_v_local", "desc": "errors_lead_lag1_v>=2 -> local",
              "condition": lambda e: safe(e.get("errors_lead_to_shot_lag1_v")) >= 2,
              "pick_field": "yield_local"})
    F.append({"id": "D3_tpa_lag1_l_local", "desc": "touches_pen_lag1_l>=25 -> local",
              "condition": lambda e: safe(e.get("touches_penalty_area_lag1_l")) >= 25,
              "pick_field": "yield_local"})
    F.append({"id": "D5_recov_lag1_l_low_visita", "desc": "recoveries_lag1_l<50 -> visita",
              "condition": lambda e: e.get("recoveries_lag1_l") is not None and e["recoveries_lag1_l"] < 50,
              "pick_field": "yield_visita"})

    # === E. Player ratings (lag-1) ===
    F.append({"id": "E1_max_lag1_l_local", "desc": "max_rating_lag1_l>=8.5 -> local",
              "condition": lambda e: e.get("max_rating_lag1_l") is not None and e["max_rating_lag1_l"] >= 8.5,
              "pick_field": "yield_local"})
    F.append({"id": "E1_max_lag1_v_visita", "desc": "max_rating_lag1_v>=8.5 -> visita",
              "condition": lambda e: e.get("max_rating_lag1_v") is not None and e["max_rating_lag1_v"] >= 8.5,
              "pick_field": "yield_visita"})
    F.append({"id": "E2_avg_lag1_l_low_visita", "desc": "avg_rating_lag1_l<6.5 -> visita",
              "condition": lambda e: e.get("avg_rating_lag1_l") is not None and e["avg_rating_lag1_l"] < 6.5,
              "pick_field": "yield_visita"})

    # === F. Keeper (lag-1) ===
    F.append({"id": "F1_keeper_lag1_l_high_visita", "desc": "keeper_save_lag1_l>1.5 -> visita",
              "condition": lambda e: e.get("keeper_save_value_lag1_l") is not None and e["keeper_save_value_lag1_l"] > 1.5,
              "pick_field": "yield_visita"})
    F.append({"id": "F2_keeper_lag1_l_low_o25", "desc": "keeper_save_lag1_l<0.3 -> o25",
              "condition": lambda e: e.get("keeper_save_value_lag1_l") is not None and 0 < e["keeper_save_value_lag1_l"] < 0.3,
              "pick_field": "yield_o25"})

    # === H. Pregame form (lag-1) ===
    F.append({"id": "H_xg_lag1_diff_local", "desc": "xg_shotmap_lag1_l - xg_shotmap_lag1_v >= 1.0 -> local",
              "condition": lambda e: (e.get("xg_shotmap_lag1_l") is not None and e.get("xg_shotmap_lag1_v") is not None
                                      and (e["xg_shotmap_lag1_l"] - e["xg_shotmap_lag1_v"]) >= 1.0),
              "pick_field": "yield_local"})
    F.append({"id": "H_xg_lag1_diff_visita", "desc": "xg_shotmap_lag1_v - xg_shotmap_lag1_l >= 1.0 -> visita",
              "condition": lambda e: (e.get("xg_shotmap_lag1_l") is not None and e.get("xg_shotmap_lag1_v") is not None
                                      and (e["xg_shotmap_lag1_v"] - e["xg_shotmap_lag1_l"]) >= 1.0),
              "pick_field": "yield_visita"})
    F.append({"id": "H_sot_lag1_diff_local", "desc": "sot_lag1_l - sot_lag1_v >= 3 -> local",
              "condition": lambda e: (e.get("shots_on_target_lag1_l") is not None and e.get("shots_on_target_lag1_v") is not None
                                      and (e["shots_on_target_lag1_l"] - e["shots_on_target_lag1_v"]) >= 3),
              "pick_field": "yield_local"})
    F.append({"id": "H_sot_lag1_diff_visita", "desc": "sot_lag1_v - sot_lag1_l >= 3 -> visita",
              "condition": lambda e: (e.get("shots_on_target_lag1_l") is not None and e.get("shots_on_target_lag1_v") is not None
                                      and (e["shots_on_target_lag1_v"] - e["shots_on_target_lag1_l"]) >= 3),
              "pick_field": "yield_visita"})

    # === I. Combinaciones ===
    F.append({"id": "I1_strict_3v5_o25", "desc": "ref strict + form 3-x vs 5-x -> o25",
              "condition": lambda e: (cards_per_game(e) is not None and cards_per_game(e) >= 6
                                      and ((form_back(e["formation_l"]) == 3 and form_back(e["formation_v"]) == 5)
                                           or (form_back(e["formation_l"]) == 5 and form_back(e["formation_v"]) == 3))),
              "pick_field": "yield_o25"})
    F.append({"id": "I3_keeper_low_lag1_o25", "desc": "keeper_lag1_l<0.3 OR keeper_lag1_v<0.3 -> o25",
              "condition": lambda e: ((e.get("keeper_save_value_lag1_l") is not None and 0 < e["keeper_save_value_lag1_l"] < 0.3)
                                      or (e.get("keeper_save_value_lag1_v") is not None and 0 < e["keeper_save_value_lag1_v"] < 0.3)),
              "pick_field": "yield_o25"})

    # === J. Patrones globales referee/formacion ===
    # Ref home_bias: con N>=10 obs/ref, calcular hit_local rate y filtrar refs con bias>=55%
    # (calculado en analisis post)

    # === Bonus: anti-filtros conocidos NEGATIVOS sobre universo SOFA ===
    F.append({"id": "Z1_pos_local_random", "desc": "BASE: apostar local todos -> baseline",
              "condition": lambda e: True,
              "pick_field": "yield_local"})
    F.append({"id": "Z2_pos_visita_random", "desc": "BASE: apostar visita todos -> baseline",
              "condition": lambda e: True,
              "pick_field": "yield_visita"})
    F.append({"id": "Z3_pos_emp_random", "desc": "BASE: apostar empate todos -> baseline",
              "condition": lambda e: True,
              "pick_field": "yield_empate"})
    F.append({"id": "Z4_pos_o25_random", "desc": "BASE: apostar o25 todos -> baseline",
              "condition": lambda e: True,
              "pick_field": "yield_o25"})
    F.append({"id": "Z5_pos_u25_random", "desc": "BASE: apostar u25 todos -> baseline",
              "condition": lambda e: True,
              "pick_field": "yield_u25"})

    return F


# ================== Main ==================

def main() -> None:
    universo = cargar_universo()
    cargar_o25_yields(universo)
    construir_lag1_features(universo)
    filtros = filtros_definidos()

    n_filtros = len([f for f in filtros if not f["id"].startswith("Z")])
    bonferroni_alpha = 0.05 / n_filtros

    resultados = {
        "universo_total": len(universo),
        "n_filtros_no_baseline": n_filtros,
        "bonferroni_alpha": bonferroni_alpha,
        "filtros": [],
    }

    for f in filtros:
        events_filt = [e for e in universo if f["condition"](e)]
        m = yield_metric(events_filt, f["pick_field"])

        # Refs blacklist por liga
        per_liga = defaultdict(lambda: {"yields": [], "hits": []})
        for e in events_filt:
            v = e.get(f["pick_field"])
            h = e.get(f["pick_field"].replace("yield_", "hit_"))
            if v is not None:
                per_liga[e["liga"]]["yields"].append(v)
                per_liga[e["liga"]]["hits"].append(h)

        liga_breakdown = {}
        for liga, d in per_liga.items():
            if not d["yields"]:
                continue
            liga_breakdown[liga] = {
                "n": len(d["yields"]),
                "yield_mean": sum(d["yields"])/len(d["yields"]),
                "hit_rate": sum(d["hits"])/len(d["hits"]) if d["hits"] else None,
            }

        resultados["filtros"].append({
            "id": f["id"],
            "desc": f["desc"],
            "pick_field": f["pick_field"],
            "n": m["n"],
            "yield_mean": m["yield_mean"],
            "hit_rate": m["hit_rate"],
            "ci95_lo": m["ci95_lo"],
            "ci95_hi": m["ci95_hi"],
            "ci95_lo_gt_zero": (m["ci95_lo"] is not None and m["ci95_lo"] > 0),
            "supera_bonferroni_5pct": (
                m["ci95_lo"] is not None and m["ci95_lo"] > 0 and m["yield_mean"] > 0.05
            ),
            "per_liga": liga_breakdown,
        })

    # Ordenar por yield (descending)
    resultados["filtros"].sort(key=lambda x: (x.get("yield_mean") or -99), reverse=True)

    out = ROOT / "analisis" / "filtros_sofa_v1_exploration.json"
    out.write_text(json.dumps(resultados, indent=2, default=float, ensure_ascii=False), encoding="utf-8")

    # Print resumen
    print(f"=== Fase 1.1 — Exploracion descriptiva ===")
    print(f"Universo: {resultados['universo_total']} eventos")
    print(f"Filtros no-baseline: {n_filtros}")
    print(f"Bonferroni alpha: {bonferroni_alpha:.5f}")
    print()
    print(f"{'ID':<32} {'pick':<13} {'N':>4} {'yield':>8} {'hit':>6} {'CI95':>20} {'supera Bonf+5%':>4}")
    for f in resultados["filtros"]:
        cl = f"[{f['ci95_lo']:+.3f},{f['ci95_hi']:+.3f}]" if f['ci95_lo'] is not None else "n/a"
        print(f"{f['id']:<32} {f['pick_field']:<13} {f['n']:>4} {(f['yield_mean'] or 0):>+8.3%} {(f['hit_rate'] or 0):>6.1%} {cl:>20} {'YES' if f.get('supera_bonferroni_5pct') else ''}")


if __name__ == "__main__":
    main()

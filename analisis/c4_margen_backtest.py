"""adepor-gbw BACKTEST CONTRAFACTUAL: C4 con relajacion de filtros.

Diagnostico revisado:
  El bead gbw asume que el rechazo de picks C4 viene de EV_MIN. Pero el codigo
  motor_calculadora.py:985 muestra que C4 NO tiene filtro EV explicito. El
  rechazo real viene del filtro 'margen predictivo' (default 5%) que se evalua
  ANTES de los caminos.

  C4 actual (motor_calculadora.py:1027-1038):
    if (fav_modelo == fav_mercado
        and p_fav >= 0.36
        and 1.12 <= c_fav <= 2.00
        and div_fav <= div_max):
        return APOSTAR

  Filtro margen previo (linea 985):
    if (prob_max - prob_segundo) < margen_pred:  # default 0.05
        return [PASAR] Margen Predictivo Insuficiente

  Por lo tanto, la proposal CORRECTA seria 'reducir margen para C4-eligible'
  o 'ignorar margen cuando C4 calificaria'.

Tests:
  T1. Cuantos picks pasarian C4 sin filtro margen?
  T2. Yield de C4 con margen=5% (actual) vs margen=3% vs margen=0% (ignorar).
  T3. Por liga: heterogeneidad del efecto.
  T4. Comparativo C4 + filtros adepor-0ac (n_acum/momento) — combinacion.

Logica: usa cuotas Pinnacle reales del OOS (N=4584).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "c4_margen_backtest.json"

# Constantes C4 (replicadas de motor_calculadora.py)
CONSENSO_PROB_MIN = 0.36
CONSENSO_CUOTA_MIN = 1.12
CONSENSO_CUOTA_MAX = 2.00
DIVERGENCIA_MAX_DEFAULT = 0.15

# Constantes pre-C4 (otros caminos)
TECHO_CUOTA_1X2 = 5.0
TECHO_CUOTA_ALTA_CONV = 8.0
UMBRAL_EV_BASE = 0.03
FLOOR_PROB_MIN = 0.40
DESACUERDO_PROB_MIN = 0.40
DIVERGENCIA_DESACUERDO_MAX = 0.30
CONVICCION_EV_MIN = 1.0


def kelly_fraction(p, cuota, cap=0.025):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, cap))


def min_ev_escalado(p, umbral=0.03):
    if p >= 0.50: return umbral
    if p >= 0.40: return umbral * 2.67
    if p >= 0.33: return umbral * 4.0
    return 999


def evaluar_pick_camino(p1, px, p2, c1, cx, c2, margen_pred=0.05, c4_only=False):
    """Replica motor_calculadora.py:evaluar_mercado_1x2 exactamente.
    Retorna (camino, fav_key, p_fav, c_fav, ev_fav) o None.
    Si c4_only=True, retorna solo cuando C4 hubiera disparado (saltea C1/C2B/C3/C2).
    """
    if not all(isinstance(c, (int, float)) and c > 0 for c in [c1, cx, c2]):
        return None
    probs_ord = sorted([p1, px, p2])
    margen_real = probs_ord[2] - probs_ord[1]
    if margen_real < margen_pred:
        return None  # rechaza por margen

    probs = {"LOCAL": p1, "EMPATE": px, "VISITA": p2}
    cuotas = {"LOCAL": c1, "EMPATE": cx, "VISITA": c2}
    fav_key = max(probs, key=probs.get)
    p_fav, c_fav = probs[fav_key], cuotas[fav_key]
    ev_fav = (p_fav * c_fav) - 1
    umb_fav = (UMBRAL_EV_BASE * (0.5 / p_fav)) if p_fav > 0 else 999
    div_fav = p_fav - (1 / c_fav)
    div_max = DIVERGENCIA_MAX_DEFAULT

    if c4_only:
        # Saltea C1/C2B/C3/C2 — solo evalua C4
        fav_mkt_key = min(cuotas, key=cuotas.get)
        if (fav_key == fav_mkt_key
                and p_fav >= CONSENSO_PROB_MIN
                and CONSENSO_CUOTA_MIN <= c_fav <= CONSENSO_CUOTA_MAX
                and div_fav <= div_max):
            return ("C4", fav_key, p_fav, c_fav, ev_fav)
        return None

    # Pipeline COMPLETO (replica del motor)
    if c_fav <= TECHO_CUOTA_1X2 and ev_fav >= umb_fav and div_fav <= div_max:
        return ("C1", fav_key, p_fav, c_fav, ev_fav)
    fav_mkt_key = min(cuotas, key=cuotas.get)
    if (fav_key != fav_mkt_key
            and p_fav >= DESACUERDO_PROB_MIN
            and div_max < div_fav <= DIVERGENCIA_DESACUERDO_MAX
            and ev_fav >= min_ev_escalado(p_fav)
            and c_fav <= TECHO_CUOTA_ALTA_CONV):
        return ("C2B", fav_key, p_fav, c_fav, ev_fav)
    if (p_fav >= FLOOR_PROB_MIN
            and ev_fav >= CONVICCION_EV_MIN
            and c_fav <= TECHO_CUOTA_ALTA_CONV):
        return ("C3", fav_key, p_fav, c_fav, ev_fav)
    if (fav_key == fav_mkt_key
            and p_fav >= CONSENSO_PROB_MIN
            and CONSENSO_CUOTA_MIN <= c_fav <= CONSENSO_CUOTA_MAX
            and div_fav <= div_max):
        return ("C4", fav_key, p_fav, c_fav, ev_fav)
    # C2
    evs = {k: (probs[k] * cuotas[k]) - 1 for k in probs}
    ev_key = max(evs, key=evs.get)
    p_ev, c_ev, m_ev = probs[ev_key], cuotas[ev_key], evs[ev_key]
    umb_ev = (UMBRAL_EV_BASE * (0.5 / p_ev)) if p_ev > 0 else 999
    div_ev = p_ev - (1 / c_ev)
    if c_ev <= TECHO_CUOTA_1X2 and m_ev >= umb_ev and div_ev <= div_max:
        return ("C2", ev_key, p_ev, c_ev, m_ev)
    return None


def cargar_oos(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.fecha, p.liga, p.temp, p.local, p.visita, p.outcome,
               p.prob_1, p.prob_x, p.prob_2, p.psch, p.pscd, p.psca,
               p.pct_temp, p.momento_bin_4,
               (SELECT n_acum FROM historial_equipos_stats
                WHERE liga=p.liga AND equipo=p.local AND fecha < p.fecha
                ORDER BY fecha DESC LIMIT 1) AS n_acum_l
        FROM predicciones_oos_con_features p
    """).fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def yield_metrics_kelly(picks_eval):
    """picks_eval es lista de dicts con (fav, c_fav, outcome, ...). Aplica
    Kelly (cap 2.5%) y devuelve metricas agregadas."""
    n_apost = 0
    n_gano = 0
    sum_stake = 0.0
    sum_pl = 0.0
    pares = []
    for r in picks_eval:
        ap = r.get("apostar")
        if not ap:
            continue
        prob = r["prob"]
        cuota = r["cuota"]
        outcome = r["outcome"]
        fav = r["fav"]
        # Mapear fav al outcome ('LOCAL'->'1','EMPATE'->'X','VISITA'->'2')
        outcome_map = {"LOCAL": "1", "EMPATE": "X", "VISITA": "2"}
        gano = (outcome == outcome_map[fav])
        stake = kelly_fraction(prob, cuota, cap=0.025)
        if stake <= 0:
            continue
        n_apost += 1
        if gano:
            n_gano += 1
            prof = stake * (cuota - 1)
        else:
            prof = -stake
        sum_stake += stake
        sum_pl += prof
        pares.append((stake, prof))
    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
    hit = n_gano / n_apost * 100 if n_apost > 0 else 0
    # bootstrap
    if pares:
        rng = np.random.default_rng(42)
        stks = np.array([p[0] for p in pares])
        profs = np.array([p[1] for p in pares])
        B = 1000
        ys = []
        for _ in range(B):
            idx = rng.integers(0, len(pares), size=len(pares))
            s = stks[idx].sum()
            p = profs[idx].sum()
            if s > 0:
                ys.append(p / s * 100)
        ci_lo = float(np.percentile(ys, 2.5)) if ys else None
        ci_hi = float(np.percentile(ys, 97.5)) if ys else None
    else:
        ci_lo = ci_hi = None
    return {
        "n_apost": n_apost, "n_gano": n_gano,
        "hit_pct": round(hit, 2),
        "yield_pct": round(yld, 2),
        "ci95_lo": round(ci_lo, 2) if ci_lo is not None else None,
        "ci95_hi": round(ci_hi, 2) if ci_hi is not None else None,
        "sum_stake_norm": round(sum_stake, 4),
        "sum_pl_norm": round(sum_pl, 4),
    }


def evaluar_subset(rows, margen_pred, c4_only=False):
    """Aplica evaluar_pick_camino sobre rows con margen_pred dado. Retorna picks_eval."""
    picks = []
    for r in rows:
        res = evaluar_pick_camino(
            r["prob_1"], r["prob_x"], r["prob_2"],
            r["psch"], r["pscd"], r["psca"],
            margen_pred=margen_pred,
            c4_only=c4_only,
        )
        if res:
            camino, fav, p, c, ev = res
            picks.append({
                "apostar": True, "camino": camino, "fav": fav,
                "prob": p, "cuota": c, "ev": ev,
                "outcome": r["outcome"], "liga": r["liga"],
                "n_acum_l": r.get("n_acum_l"), "momento_bin_4": r.get("momento_bin_4"),
            })
    return picks


def main():
    con = sqlite3.connect(DB)
    print("Cargando OOS...")
    rows = cargar_oos(con)
    print(f"  N OOS total: {len(rows):,}")

    payload = {
        "n_total_oos": len(rows),
        "constantes_c4": {
            "prob_min": CONSENSO_PROB_MIN,
            "cuota_min": CONSENSO_CUOTA_MIN,
            "cuota_max": CONSENSO_CUOTA_MAX,
            "div_max": DIVERGENCIA_MAX_DEFAULT,
        },
        "tests": {},
    }

    # ==========================================
    # T1. Pipeline completo motor con margen variable
    # ==========================================
    print("\n=== T1. Pipeline completo del motor con margen variable ===")
    print(f"{'margen_pred':<14} {'NApost':>7} {'C1':>5} {'C2B':>5} {'C3':>5} {'C4':>5} {'C2':>5} {'Yield%':>8} {'CI95':>20}")
    t1 = {}
    for mg in [0.00, 0.02, 0.03, 0.05, 0.07]:
        picks = evaluar_subset(rows, margen_pred=mg, c4_only=False)
        m = yield_metrics_kelly(picks)
        cnt = defaultdict(int)
        for p in picks:
            cnt[p["camino"]] += 1
        c1n = cnt.get("C1", 0)
        c2bn = cnt.get("C2B", 0)
        c3n = cnt.get("C3", 0)
        c4n = cnt.get("C4", 0)
        c2n = cnt.get("C2", 0)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{mg:<14.2f} {m['n_apost']:>7} {c1n:>5} {c2bn:>5} {c3n:>5} {c4n:>5} {c2n:>5} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t1[f"margen_{mg:.2f}"] = {
            **m, "caminos": dict(cnt),
        }
    payload["tests"]["T1_pipeline_completo"] = t1

    # ==========================================
    # T2. C4 SOLO (saltando otros caminos) con margen variable
    # ==========================================
    print("\n=== T2. C4 SOLO (saltando C1/C2B/C3/C2) con margen variable ===")
    print(f"{'margen_pred':<14} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20} {'Sum_stake_norm':>14}")
    t2 = {}
    for mg in [0.00, 0.02, 0.03, 0.05, 0.07]:
        picks = evaluar_subset(rows, margen_pred=mg, c4_only=True)
        m = yield_metrics_kelly(picks)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{mg:<14.2f} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20} {m['sum_stake_norm']:>14.2f}")
        t2[f"margen_{mg:.2f}"] = m
    payload["tests"]["T2_c4_solo"] = t2

    # ==========================================
    # T3. C4 SOLO por liga (margen=0.00 vs 0.05)
    # ==========================================
    print("\n=== T3. C4 SOLO por liga: margen=0.00 (relajado) vs 0.05 (actual) ===")
    print(f"{'liga':<14} | {'NA(0.00)':>10} | {'Y(0.00)':>10} | {'NA(0.05)':>10} | {'Y(0.05)':>10} | {'Delta_NA':>9} | {'Delta_Y':>9}")
    t3 = {}
    ligas = sorted(set(r["liga"] for r in rows))
    for liga in ligas:
        rows_liga = [r for r in rows if r["liga"] == liga]
        picks_relajado = evaluar_subset(rows_liga, margen_pred=0.00, c4_only=True)
        picks_actual = evaluar_subset(rows_liga, margen_pred=0.05, c4_only=True)
        m_r = yield_metrics_kelly(picks_relajado)
        m_a = yield_metrics_kelly(picks_actual)
        delta_na = m_r["n_apost"] - m_a["n_apost"]
        delta_y = m_r["yield_pct"] - m_a["yield_pct"]
        print(f"{liga:<14} | {m_r['n_apost']:>10} | {m_r['yield_pct']:>+9.1f}% | {m_a['n_apost']:>10} | {m_a['yield_pct']:>+9.1f}% | {delta_na:>+9} | {delta_y:>+9.1f}")
        t3[liga] = {"relajado": m_r, "actual": m_a, "delta_na": delta_na, "delta_y": round(delta_y, 2)}
    payload["tests"]["T3_c4_por_liga"] = t3

    # ==========================================
    # T4. Cruce C4 con filtros adepor-0ac (n_acum + momento)
    # ==========================================
    print("\n=== T4. C4 SOLO + filtros adepor-0ac (n_acum + momento) ===")
    print(f"{'Filtro':<55} {'NApost':>7} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    t4 = {}
    for nombre, condicion in [
        ("Pipeline completo, margen 0.05 (BASELINE)", None),
        ("C4 SOLO, margen 0.00", "c4_relajado"),
        ("C4 SOLO, margen 0.00, excluir n_acum_l>=60", "c4_relajado_n"),
        ("C4 SOLO, margen 0.00, excluir Q4", "c4_relajado_q"),
        ("C4 SOLO, margen 0.00, excluir (n_acum>=60 OR Q4)", "c4_relajado_nq"),
    ]:
        if condicion is None:
            picks = evaluar_subset(rows, margen_pred=0.05, c4_only=False)
        else:
            picks = evaluar_subset(rows, margen_pred=0.00, c4_only=True)
            if condicion == "c4_relajado_n":
                picks = [p for p in picks if p.get("n_acum_l") is None or p["n_acum_l"] < 60]
            elif condicion == "c4_relajado_q":
                picks = [p for p in picks if p.get("momento_bin_4") != 3]
            elif condicion == "c4_relajado_nq":
                picks = [p for p in picks
                         if (p.get("n_acum_l") is None or p["n_acum_l"] < 60)
                         and p.get("momento_bin_4") != 3]
        m = yield_metrics_kelly(picks)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<55} {m['n_apost']:>7} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        t4[nombre] = m
    payload["tests"]["T4_c4_con_filtros_0ac"] = t4

    # ==========================================
    # T5. Walk-forward por temporada (validar regimen)
    # ==========================================
    print("\n=== T5. Walk-forward por temp: pipeline completo (margen 0.05) vs C4 relajado ===")
    print(f"{'temp':<6} {'pipe_NA':>8} {'pipe_Y%':>8} {'c4r_NA':>8} {'c4r_Y%':>8} {'union_NA':>10} {'union_Y%':>10}")
    t5 = {}
    temps = sorted(set(r["temp"] for r in rows))
    for temp in temps:
        rows_t = [r for r in rows if r["temp"] == temp]
        picks_pipe = evaluar_subset(rows_t, margen_pred=0.05, c4_only=False)
        picks_c4r = evaluar_subset(rows_t, margen_pred=0.00, c4_only=True)
        m_p = yield_metrics_kelly(picks_pipe)
        m_c = yield_metrics_kelly(picks_c4r)
        # union: pipe + c4_relajado pero sin doble-contar
        # (un pick puede aparecer en ambos: pipe lo asigna a otro camino, c4_relajado a C4)
        # Simplificacion: usar pipe normal + agregar C4_relajado los que NO estan ya
        # (para auditar realmente impacto agregado)
        ids_pipe = set()
        for r in rows_t:
            res = evaluar_pick_camino(r["prob_1"], r["prob_x"], r["prob_2"],
                                        r["psch"], r["pscd"], r["psca"],
                                        margen_pred=0.05, c4_only=False)
            if res:
                ids_pipe.add((r["fecha"], r["local"], r["visita"]))
        # Picks adicionales por c4 relajado
        picks_extra = []
        for r in rows_t:
            res_c4 = evaluar_pick_camino(r["prob_1"], r["prob_x"], r["prob_2"],
                                          r["psch"], r["pscd"], r["psca"],
                                          margen_pred=0.00, c4_only=True)
            if res_c4 and (r["fecha"], r["local"], r["visita"]) not in ids_pipe:
                camino, fav, p, c, ev = res_c4
                picks_extra.append({
                    "apostar": True, "camino": "C4r", "fav": fav,
                    "prob": p, "cuota": c, "ev": ev, "outcome": r["outcome"],
                })
        picks_union = picks_pipe + picks_extra
        m_u = yield_metrics_kelly(picks_union)
        print(f"{temp:<6} {m_p['n_apost']:>8} {m_p['yield_pct']:>+8.1f} {m_c['n_apost']:>8} {m_c['yield_pct']:>+8.1f} {m_u['n_apost']:>10} {m_u['yield_pct']:>+10.1f}")
        t5[str(temp)] = {"pipe_actual": m_p, "c4_relajado_solo": m_c, "union": m_u}
    payload["tests"]["T5_walk_forward_temp"] = t5

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

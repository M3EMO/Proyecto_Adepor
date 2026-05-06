"""Filtro de oro — combinar V0, V_dual, V_ruido, MKT como SEÑALES para detectar
zona apostable de máximo ROI/yield/N.

Componentes:
  PARTE 1 — ROI base 100 con simulación drawdown / sharpe / racha negativa.
  PARTE 2 — Investigación profunda 2025 (overround, ligas, cuota distribución, hit rate).
  PARTE 3 — Filtro de oro: scoring multi-criterio para identificar mejores picks.
  PARTE 4 — Optimización: maximizar ROI dado N mínimo.
"""
import sqlite3
import math
import json
import random
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge

DB = "fondo_quant.db"
WARMUP = 5
MAX_GOALS = 8
ALFA_EMA = 0.10
THETA_V0 = 0.30
EV_MIN = 1.03
YEARS_TEST = ["2023", "2024", "2025", "2026"]
TOP_LIGAS = {"Inglaterra", "Espana", "Italia", "Francia", "Alemania"}
random.seed(42)


def get_beta_sot_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
    ).fetchall()}


def cargar(cur):
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
               h_blocks, a_blocks, h_longballs_acc, a_longballs_acc
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs IS NOT NULL AND as_v IS NOT NULL
          AND hc IS NOT NULL AND ac IS NOT NULL
          AND h_pos IS NOT NULL AND a_pos IS NOT NULL
          AND h_pass_pct IS NOT NULL AND a_pass_pct IS NOT NULL
          AND h_saves IS NOT NULL AND a_saves IS NOT NULL
          AND h_blocks IS NOT NULL AND a_blocks IS NOT NULL
          AND h_longballs_acc IS NOT NULL AND a_longballs_acc IS NOT NULL
        ORDER BY fecha
    """).fetchall()
    cuotas = {}
    for r in cur.execute("""
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f
          ON s.liga=f.liga AND s.fecha=f.fecha
         AND LOWER(REPLACE(REPLACE(REPLACE(s.ht,' ',''),'-',''),'.','')) = f.equipo_local_norm
         AND LOWER(REPLACE(REPLACE(REPLACE(s.at,' ',''),'-',''),'.','')) = f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
    """).fetchall():
        cuotas[(r[0], r[1], r[2], r[3])] = (r[4], r[5], r[6])
    cal = {(r[0], r[1]): (r[2], r[3]) for r in cur.execute(
        "SELECT liga, temp, fecha_inicio, fecha_fin FROM liga_calendario_temp"
    ).fetchall()}
    return rows, cuotas, cal


def construir_eventos(rows):
    eventos = []
    for r in rows:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac,
         hp, ap, hpp, app, hsv, asv2, hbl, abl, hlba, alba) = r
        eventos.append({"liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
                        "goles": hg, "goles_rival": ag, "sot": hst, "shots_off": max(0, hs - hst),
                        "corners": hc, "pos": hp or 50, "pass_pct": hpp or 0,
                        "saves_rival": asv2 or 0, "blocks_rival": abl or 0, "longballs_acc": hlba or 0})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast),
                        "corners": ac, "pos": ap or 50, "pass_pct": app or 0,
                        "saves_rival": hsv or 0, "blocks_rival": hbl or 0, "longballs_acc": alba or 0})
    return eventos


def fit_v5_xg(eventos_train):
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def fit_v_ruido(eventos_train):
    feats = ["shots_off", "corners", "pos", "pass_pct", "saves_rival", "blocks_rival", "longballs_acc"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def calc_xg(ev, fit):
    return fit["intercept"] + sum(fit["coef"][i]*ev[fit["feats"][i]] for i in range(len(fit["feats"])))


def construir_state_dual(eventos, fit_xg, alfa):
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    keys_ord = sorted(matches.keys(), key=lambda k: k[1])
    state = defaultdict(lambda: {"xg_h": None, "xg_a": None, "res_h": None, "res_a": None, "n_h": 0, "n_a": 0})
    out = {}
    for key in keys_ord:
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]
        sh, sa = state[ht], state[at]
        out[key] = {"xg_h": sh["xg_h"], "res_h": sh["res_h"], "n_h": sh["n_h"],
                    "xg_v": sa["xg_a"], "res_v": sa["res_a"], "n_v": sa["n_a"],
                    "hg": ev_l["goles"], "ag": ev_l["goles_rival"],
                    "fecha": key[1], "liga": key[0]}
        xl = calc_xg(ev_l, fit_xg); xv = calc_xg(ev_v, fit_xg)
        rl = ev_l["goles"]-xl; rv = ev_v["goles"]-xv
        sh["xg_h"] = xl if sh["xg_h"] is None else alfa*xl+(1-alfa)*sh["xg_h"]
        sh["res_h"] = rl if sh["res_h"] is None else alfa*rl+(1-alfa)*sh["res_h"]; sh["n_h"] += 1
        sa["xg_a"] = xv if sa["xg_a"] is None else alfa*xv+(1-alfa)*sa["xg_a"]
        sa["res_a"] = rv if sa["res_a"] is None else alfa*rv+(1-alfa)*sa["res_a"]; sa["n_a"] += 1
    return out


def construir_state_ruido(eventos, fit_xg, alfa):
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    keys_ord = sorted(matches.keys(), key=lambda k: k[1])
    state = defaultdict(lambda: {"h": None, "a": None, "n_h": 0, "n_a": 0})
    out = {}
    for key in keys_ord:
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]
        sh, sa = state[ht], state[at]
        out[key] = {"h": sh["h"], "a": sa["a"], "n_h": sh["n_h"], "n_a": sa["n_a"]}
        xl = calc_xg(ev_l, fit_xg); xv = calc_xg(ev_v, fit_xg)
        sh["h"] = xl if sh["h"] is None else alfa*xl+(1-alfa)*sh["h"]; sh["n_h"] += 1
        sa["a"] = xv if sa["a"] is None else alfa*xv+(1-alfa)*sa["a"]; sa["n_a"] += 1
    return out


def construir_emas_v0(eventos, beta_sot_map, alfa, theta):
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    keys_ord = sorted(matches.keys(), key=lambda k: k[1])
    state = defaultdict(lambda: {"fh": None, "fa": None, "nfh": 0, "nfa": 0})
    out = {}
    for key in keys_ord:
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]
        sh, sa = state[ht], state[at]
        lam_h = sh["fh"] if sh["nfh"] >= WARMUP else None
        lam_v = sa["fa"] if sa["nfa"] >= WARMUP else None
        out[key] = (lam_h, lam_v, ev_l["goles"], ev_l["goles_rival"])
        beta = beta_sot_map.get(key[0], 0.352)
        xl = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]
        xl = 0.70*xl + 0.30*ev_l["goles"]
        xv = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]
        xv = 0.70*xv + 0.30*ev_v["goles"]
        xlp = theta*xl + (1-theta)*ev_l["goles"]
        xvp = theta*xv + (1-theta)*ev_v["goles"]
        sh["fh"] = xlp if sh["fh"] is None else alfa*xlp+(1-alfa)*sh["fh"]; sh["nfh"] += 1
        sa["fa"] = xvp if sa["fa"] is None else alfa*xvp+(1-alfa)*sa["fa"]; sa["nfa"] += 1
    return out


def fit_lambda_dual(state, year_max):
    rows, y = [], []
    for key, d in state.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= year_max: continue
        rows.append([d["xg_h"], d["res_h"]]); y.append(d["hg"])
        rows.append([d["xg_v"], d["res_v"]]); y.append(d["ag"])
    if not rows: return None
    m = Ridge(alpha=1.0, fit_intercept=True).fit(np.array(rows), np.array(y))
    return {"intercept": float(m.intercept_), "coef": m.coef_.tolist()}


def fit_lambda_ruido(state_ruido, state_dual, year_max):
    rows, y = [], []
    for key, d in state_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= year_max: continue
        d_r = state_ruido.get(key)
        if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
        rows.append([d_r["h"]]); y.append(d["hg"])
        rows.append([d_r["a"]]); y.append(d["ag"])
    if not rows: return None
    m = Ridge(alpha=1.0, fit_intercept=True).fit(np.array(rows), np.array(y))
    return {"intercept": float(m.intercept_), "coef": m.coef_.tolist()}


def poisson_pmf(k, lam):
    if lam <= 0: lam = 0.01
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def dc_tau(h, a, lh, lv, rho):
    if h == 0 and a == 0: return 1 - lh*lv*rho
    if h == 0 and a == 1: return 1 + lh*rho
    if h == 1 and a == 0: return 1 + lv*rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0


def prob_1x2(lh, lv, rho):
    pl=pe=pv=0.0
    for h in range(MAX_GOALS+1):
        for a in range(MAX_GOALS+1):
            p = poisson_pmf(h, lh)*poisson_pmf(a, lv)*dc_tau(h, a, lh, lv, rho)
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl+pe+pv
    if s > 0: pl/=s; pe/=s; pv/=s
    return pl, pe, pv


def calibrar_rho(pairs, year_max):
    grid = [round(-0.2 + 0.005*i, 3) for i in range(81)]
    by_liga = defaultdict(list)
    for liga, fecha, lh, lv, hg, ag in pairs:
        if fecha[:4] >= year_max: continue
        if lh > 0 and lv > 0: by_liga[liga].append((lh, lv, hg, ag))
    rhos = {}
    for liga, ps in by_liga.items():
        if len(ps) < 50: rhos[liga] = -0.05; continue
        best, best_ll = -0.05, -math.inf
        for rho in grid:
            ll = 0.0
            for lh, lv, hg, ag in ps:
                p = poisson_pmf(hg, lh)*poisson_pmf(ag, lv)*dc_tau(hg, ag, lh, lv, rho)
                if p > 0: ll += math.log(p)
                else: ll = -math.inf; break
            if ll > best_ll: best_ll, best = ll, rho
        rhos[liga] = best
    return rhos


def get_bin(liga, fecha, cal, n_bins):
    anio = int(fecha[:4])
    for temp in (anio, anio+1):
        if (liga, temp) in cal:
            inicio, fin = cal[(liga, temp)]
            if inicio <= fecha <= fin:
                from datetime import date
                d = date.fromisoformat(fecha[:10]); di = date.fromisoformat(inicio[:10]); df = date.fromisoformat(fin[:10])
                tot = (df-di).days
                if tot <= 0: return None
                pct = max(0.0, min(0.9999, (d-di).days/tot))
                return min(n_bins-1, int(pct*n_bins))
    return None


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas, cal = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas, {len(cal)} calendarios")

    # Recolectar predicciones walk-forward
    records = []
    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train)
        fit_ruido = fit_v_ruido(ev_train)
        state_dual = construir_state_dual(eventos, fit_v5, ALFA_EMA)
        state_ruido = construir_state_ruido(eventos, fit_ruido, ALFA_EMA)
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        fit_lam_d = fit_lambda_dual(state_dual, yt)
        fit_lam_r = fit_lambda_ruido(state_ruido, state_dual, yt)
        if not fit_lam_d or not fit_lam_r: continue
        pairs_v0, pairs_d, pairs_r = [], [], []
        for key, val in emas_v0.items():
            lh, lv, _, _ = val
            if lh is None or lv is None: continue
            pairs_v0.append((key[0], key[1], lh, lv, val[2], val[3]))
        for key, d in state_dual.items():
            if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            d_r = state_ruido.get(key)
            if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
            lh_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_h"]+fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_v"]+fit_lam_d["coef"][1]*d["res_v"])
            lh_r = max(0.05, fit_lam_r["intercept"]+fit_lam_r["coef"][0]*d_r["h"])
            lv_r = max(0.05, fit_lam_r["intercept"]+fit_lam_r["coef"][0]*d_r["a"])
            pairs_d.append((d["liga"], d["fecha"], lh_d, lv_d, d["hg"], d["ag"]))
            pairs_r.append((d["liga"], d["fecha"], lh_r, lv_r, d["hg"], d["ag"]))
        rhos_v0 = calibrar_rho(pairs_v0, yt)
        rhos_d = calibrar_rho(pairs_d, yt)
        rhos_r = calibrar_rho(pairs_r, yt)
        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key); d_r = state_ruido.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            lh_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_h"]+fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_v"]+fit_lam_d["coef"][1]*d["res_v"])
            pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
            lh_r = max(0.05, fit_lam_r["intercept"]+fit_lam_r["coef"][0]*d_r["h"])
            lv_r = max(0.05, fit_lam_r["intercept"]+fit_lam_r["coef"][0]*d_r["a"])
            plr, per, pvr = prob_1x2(lh_r, lv_r, rhos_r.get(key[0], -0.05))
            outcome = "L" if hg > ag else ("E" if hg == ag else "V")
            bin4 = get_bin(key[0], key[1], cal, 4)
            records.append({
                "key": key, "year": yt, "liga": key[0], "outcome": outcome,
                "V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd), "Vruido": (plr, per, pvr),
                "cuotas": cuotas.get(key), "bin4": bin4
            })
    print(f"Records: {len(records)}, con cuotas: {sum(1 for r in records if r['cuotas'])}")

    # =========================================================================
    # PARTE 2 — Investigación 2025
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 2 — Régimen 2025 detallado")
    print("="*100)
    by_year_liga = defaultdict(lambda: {"n": 0, "overround": [], "cuota_l_mean": [], "hit_local": 0})
    for r in records:
        if r["cuotas"] is None: continue
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        d = by_year_liga[(r["year"], r["liga"])]
        d["n"] += 1; d["overround"].append(ov); d["cuota_l_mean"].append(c1)
        if r["outcome"] == "L": d["hit_local"] += 1

    # Por liga 2025 vs 2024 (overround)
    print(f"\n{'liga':<14s}{'year':<6s}{'N':>6s}{'overround':>12s}{'cuota_L_mean':>14s}{'%L':>8s}")
    for liga in sorted({r["liga"] for r in records if r["cuotas"]}):
        for yt in ("2023", "2024", "2025", "2026"):
            d = by_year_liga.get((yt, liga))
            if not d or d["n"] < 10: continue
            ov_avg = sum(d["overround"])/len(d["overround"])
            c_avg = sum(d["cuota_l_mean"])/len(d["cuota_l_mean"])
            pct_l = d["hit_local"]/d["n"]*100
            print(f"{liga:<14s}{yt:<6s}{d['n']:>6d}{ov_avg:>12.4f}{c_avg:>14.2f}{pct_l:>7.2f}%")
        print()

    # =========================================================================
    # PARTE 3 — Filtro de oro: scoring multi-criterio
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 3 — FILTRO DE ORO: scoring multi-criterio")
    print("="*100)

    def get_filter_score(r):
        """Calcula score sumando criterios. Solo para records con cuotas."""
        if r["cuotas"] is None: return None, None, None, None
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
        # Picks de cada modelo
        opc_v0 = sorted([(r["V0"][0], "L"), (r["V0"][1], "E"), (r["V0"][2], "V")], key=lambda x: -x[0])
        opc_vd = sorted([(r["Vdual"][0], "L"), (r["Vdual"][1], "E"), (r["Vdual"][2], "V")], key=lambda x: -x[0])
        opc_vr = sorted([(r["Vruido"][0], "L"), (r["Vruido"][1], "E"), (r["Vruido"][2], "V")], key=lambda x: -x[0])
        opc_mkt = sorted([(pi_l, "L"), (pi_e, "E"), (pi_v, "V")], key=lambda x: -x[0])
        pick_v0, pick_vd, pick_vr, pick_mkt = opc_v0[0][1], opc_vd[0][1], opc_vr[0][1], opc_mkt[0][1]
        p_v0, p_vd, p_vr = opc_v0[0][0], opc_vd[0][0], opc_vr[0][0]
        # Probas de cada pick segun modelos
        pl_v0, pe_v0, pv_v0 = r["V0"]
        # Pick consensuado - usar V0 como base, aceptar si Vdual coincide
        score = 0
        # Criterio 1: V0 + Vdual coinciden
        if pick_v0 == pick_vd: score += 2
        # Criterio 2: V0 + Vruido coinciden
        if pick_v0 == pick_vr: score += 1
        # Criterio 3: V0 P_top alto
        if p_v0 >= 0.55: score += 2
        if p_v0 >= 0.60: score += 1
        # Criterio 4: divergencia con mercado
        pi_pick_v0 = pi_l if pick_v0=="L" else pi_e if pick_v0=="E" else pi_v
        div = p_v0 - pi_pick_v0
        if div >= 0.05: score += 1
        if div >= 0.10: score += 2
        # Criterio 5: cuota en banda calibrada [1.5, 2.5)
        cuota_pick = c1 if pick_v0=="L" else cx if pick_v0=="E" else c2
        if 1.5 <= cuota_pick < 2.5: score += 1
        if 1.5 <= cuota_pick < 2.0: score += 1  # zona favorita underconfident
        # Criterio 6: Vdual underconfident (pick coincide y P_dual < P_v0 — Vdual subestima)
        p_vd_pick = r["Vdual"][0] if pick_v0=="L" else r["Vdual"][1] if pick_v0=="E" else r["Vdual"][2]
        if pick_vd == pick_v0 and p_vd_pick < p_v0:
            score += 1  # underconfidence de Vdual confirma
        # Criterio 7: liga TOP_EU (mejor cobertura cuotas, calibracion mas estable)
        if r["liga"] in TOP_LIGAS: score += 1
        # Criterio 8: bin4 en {0, 1} (inicio/medio temporada — menos ruido)
        if r["bin4"] is not None and r["bin4"] in (0, 1): score += 1
        # Criterio 9: NO en Turquia (régimen mercado eficiente confirmado)
        if r["liga"] == "Turquia": score -= 2
        # Criterio 10: NO en 2025+ (régimen mercado eficiente)
        # (este criterio es retrospectivo; en producción NO se sabe el año, desactivado)
        return score, pick_v0, p_v0, cuota_pick

    # Eval: para cada threshold de score, calcular yield, N
    print(f"\n{'score_min':<12s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'cuota_avg':>11s}{'pnl':>9s}")
    score_results = {}
    for score_min in range(-2, 12):
        bets = []
        for r in records:
            score, pick, p_top, cuota_pick = get_filter_score(r)
            if score is None or score < score_min: continue
            ev = p_top * cuota_pick
            if ev < EV_MIN: continue
            won = pick == r["outcome"]
            pnl = (cuota_pick - 1.0) if won else -1.0
            bets.append((won, cuota_pick, pnl, r["year"]))
        if len(bets) < 10: continue
        n = len(bets); hits = sum(b[0] for b in bets); pnl = sum(b[2] for b in bets)
        cuota_avg = sum(b[1] for b in bets)/n
        yld = pnl/n*100
        score_results[score_min] = (n, hits/n*100, yld, pnl, bets)
        print(f"{score_min:<12d}{n:>6d}{hits/n*100:>6.2f}%{yld:>8.2f}%{cuota_avg:>11.2f}{pnl:>9.2f}")

    # =========================================================================
    # PARTE 1 — ROI base 100 + simulación drawdown
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 1 — ROI base 100 con bankroll dinamico")
    print("="*100)

    # Para cada estrategia top, simular: stake fijo flat 1u sobre 100u bankroll
    top_strategies = [
        ("V0 P>=0.6 div>=0.05 (top yield N>30)", lambda r: filter_v0_floor(r, 0.6, 0.05)),
        ("V0 P>=0.55 div>=0.05 (sweet spot)", lambda r: filter_v0_floor(r, 0.55, 0.05)),
        ("V0 div>=0.15 (motor original)", lambda r: filter_v0_div(r, 0.15)),
        ("V0+Vdual CONSENSUS div>=0.10 (max N)", lambda r: filter_consensus(r, 0.10)),
    ]

    def filter_v0_floor(r, floor_p, div_thr):
        if r["cuotas"] is None: return None
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        opc = sorted([(r["V0"][0], "L"), (r["V0"][1], "E"), (r["V0"][2], "V")], key=lambda x: -x[0])
        p_top, pick = opc[0]
        pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
        pi_pick = pi_l if pick=="L" else pi_e if pick=="E" else pi_v
        if p_top < floor_p: return None
        if p_top - pi_pick < div_thr: return None
        cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
        if p_top * cuota_pick < EV_MIN: return None
        return pick, cuota_pick

    def filter_v0_div(r, div_thr):
        if r["cuotas"] is None: return None
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        opc = sorted([(r["V0"][0], "L"), (r["V0"][1], "E"), (r["V0"][2], "V")], key=lambda x: -x[0])
        p_top, pick = opc[0]
        pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
        pi_pick = pi_l if pick=="L" else pi_e if pick=="E" else pi_v
        if p_top - pi_pick < div_thr: return None
        cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
        if p_top * cuota_pick < EV_MIN: return None
        return pick, cuota_pick

    def filter_consensus(r, div_thr):
        if r["cuotas"] is None: return None
        opc_v0 = sorted([(r["V0"][0], "L"), (r["V0"][1], "E"), (r["V0"][2], "V")], key=lambda x: -x[0])
        opc_vd = sorted([(r["Vdual"][0], "L"), (r["Vdual"][1], "E"), (r["Vdual"][2], "V")], key=lambda x: -x[0])
        if opc_v0[0][1] != opc_vd[0][1]: return None
        pick = opc_v0[0][1]
        p_top = (opc_v0[0][0] + opc_vd[0][0])/2
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
        if p_top - pi_pick < div_thr: return None
        cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
        if p_top * cuota_pick < EV_MIN: return None
        return pick, cuota_pick

    print(f"\n{'strategy':<48s}{'N':>5s}{'yield%':>8s}{'ROI_100':>9s}{'maxDD%':>8s}{'sharpe':>8s}{'racha':>7s}")
    # Filtro de oro
    BEST_SCORE_MIN = max(score_results.keys(), key=lambda k: score_results[k][2] * math.log(score_results[k][0]+1) if score_results[k][2] > 0 else -999)
    top_strategies.append((f"FILTRO_ORO score>={BEST_SCORE_MIN}",
                           lambda r, sm=BEST_SCORE_MIN: (lambda res: (res[1], None) if res[0] is not None and res[0] >= sm else None)(get_filter_score(r))))

    # Re-write filtro_oro to be cleaner
    def filter_oro(r):
        score, pick, p_top, cuota_pick = get_filter_score(r)
        if score is None or score < BEST_SCORE_MIN: return None
        if p_top * cuota_pick < EV_MIN: return None
        return pick, cuota_pick

    top_strategies[-1] = (f"FILTRO_ORO score>={BEST_SCORE_MIN}", filter_oro)

    for label, ffn in top_strategies:
        bets = []
        for r in records:
            res = ffn(r)
            if res is None: continue
            pick, cuota_pick = res
            won = pick == r["outcome"]
            pnl = (cuota_pick - 1.0) if won else -1.0
            bets.append((won, cuota_pick, pnl, r["year"], r["key"][1]))
        if len(bets) < 5:
            print(f"{label:<48s}{len(bets):>5d}     -       -       -       -       -")
            continue
        bets.sort(key=lambda x: x[4])  # ordenar cronologicamente
        # Bankroll evolucion (stake 1u flat)
        bankroll = 100.0
        peak = 100.0
        max_dd = 0.0
        rachas_neg = []
        racha_actual = 0
        max_racha = 0
        for won, cuota, pnl, _, _ in bets:
            bankroll += pnl
            peak = max(peak, bankroll)
            dd = (peak - bankroll)/peak * 100
            max_dd = max(max_dd, dd)
            if not won:
                racha_actual += 1
                max_racha = max(max_racha, racha_actual)
            else:
                if racha_actual > 0: rachas_neg.append(racha_actual)
                racha_actual = 0
        n = len(bets); pnl_total = sum(b[2] for b in bets)
        yld = pnl_total/n*100
        roi = (bankroll - 100)/100 * 100  # ROI sobre 100u
        # Sharpe simplificado (mean / std de pnl por bet)
        pnls = [b[2] for b in bets]
        mean = sum(pnls)/n; var = sum((p-mean)**2 for p in pnls)/n
        std = math.sqrt(var) if var > 0 else 1
        sharpe = mean/std * math.sqrt(n)  # anualizado por sqrt(N)
        print(f"{label:<48s}{n:>5d}{yld:>7.2f}%{roi:>8.2f}%{max_dd:>7.2f}%{sharpe:>7.2f}{max_racha:>7d}")

    # =========================================================================
    # PARTE 4 — Filtro de oro: detalle por año + bin4
    # =========================================================================
    print("\n" + "="*100)
    print(f"PARTE 4 — FILTRO_ORO score>={BEST_SCORE_MIN} desglosado")
    print("="*100)
    bets_oro = []
    for r in records:
        score, pick, p_top, cuota_pick = get_filter_score(r)
        if score is None or score < BEST_SCORE_MIN: continue
        if p_top * cuota_pick < EV_MIN: continue
        won = pick == r["outcome"]
        pnl = (cuota_pick - 1.0) if won else -1.0
        bets_oro.append({"won": won, "cuota": cuota_pick, "pnl": pnl, "year": r["year"],
                         "liga": r["liga"], "bin4": r["bin4"], "fecha": r["key"][1]})

    print(f"\nN total bets FILTRO_ORO: {len(bets_oro)}")

    # Por anio
    print("\n--- Yield por anio ---")
    print(f"{'anio':<6s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'ROI_100':>9s}")
    for yt in YEARS_TEST:
        bets_y = [b for b in bets_oro if b["year"] == yt]
        if not bets_y: continue
        n = len(bets_y); pnl = sum(b["pnl"] for b in bets_y); hits = sum(b["won"] for b in bets_y)
        bankroll = 100 + pnl
        print(f"{yt:<6s}{n:>6d}{hits/n*100:>6.2f}%{pnl/n*100:>8.2f}%{(bankroll-100):>8.2f}%")

    # Por liga
    print("\n--- Yield por liga (filtro oro) ---")
    print(f"{'liga':<14s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}")
    by_liga = defaultdict(list)
    for b in bets_oro:
        by_liga[b["liga"]].append(b)
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        b_l = by_liga[liga]
        n = len(b_l)
        if n < 3: continue
        pnl = sum(b["pnl"] for b in b_l); hits = sum(b["won"] for b in b_l)
        print(f"{liga:<14s}{n:>6d}{hits/n*100:>6.2f}%{pnl/n*100:>8.2f}%")

    # Bootstrap CI95% sobre filtro de oro
    if bets_oro:
        print("\n--- Bootstrap CI95% sobre filtro de oro ---")
        pnls = [b["pnl"] for b in bets_oro]
        boot_yields = []
        for _ in range(10000):
            sample = [random.choice(pnls) for _ in range(len(pnls))]
            boot_yields.append(sum(sample)/len(sample)*100)
        boot_yields.sort()
        ci_lo = boot_yields[250]; ci_hi = boot_yields[9750]
        prob_pos = sum(1 for y in boot_yields if y > 0)/10000*100
        print(f"  N={len(pnls)}  yield_obs={sum(pnls)/len(pnls)*100:+.2f}%")
        print(f"  CI95% = [{ci_lo:+.2f}%, {ci_hi:+.2f}%]")
        print(f"  P(yield > 0) = {prob_pos:.1f}%")

    Path("analisis/filtro_de_oro.json").write_text(
        json.dumps({"BEST_SCORE_MIN": BEST_SCORE_MIN,
                    "score_results": {str(k): list(v[:4]) for k, v in score_results.items()},
                    "bets_oro": [{"won": b["won"], "cuota": b["cuota"], "pnl": b["pnl"],
                                  "year": b["year"], "liga": b["liga"]} for b in bets_oro]},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/filtro_de_oro.json")


if __name__ == "__main__":
    main()

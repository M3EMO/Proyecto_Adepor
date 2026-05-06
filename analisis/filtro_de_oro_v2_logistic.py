"""Filtro de oro v2 — análisis profundo de qué tienen en común los ganadores.

Approach: para cada partido apostable, generar feature vector.
Logistic regression sobre target=won (won = pick coincide con outcome).
Identificar features más discriminantes (coefs grandes).

Features del partido:
- V0_p_top, V0_pick_es_local, V0_pick_es_empate, V0_pick_es_visita
- Vdual_p_top, Vdual_p_top_match_v0
- Vruido_p_top
- divergencia_v0_mkt, divergencia_vdual_mkt
- consensus_count (cuántos modelos coinciden)
- cuota_pick, cuota_pick_band (one-hot 6 bandas)
- pi_pick (P_implícita_mercado del pick)
- bin4 (one-hot 4)
- liga (one-hot top vs no_top)
- mes
- delta_p_top_v0_vs_mkt
- delta_p_top_vdual_vs_v0

Train: 2022-2024. Test: 2025-2026. Walk-forward también.
"""
import sqlite3
import math
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler

DB = "fondo_quant.db"
WARMUP = 5
MAX_GOALS = 8
ALFA_EMA = 0.10
THETA_V0 = 0.30
EV_MIN = 1.03
YEARS_TEST = ["2023", "2024", "2025", "2026"]
TOP_LIGAS = {"Inglaterra", "Espana", "Italia", "Francia", "Alemania"}


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


def featurize_record(r):
    """Genera features para cada record con cuotas. Pick = argmax(V0)."""
    if r["cuotas"] is None: return None
    c1, cx, c2 = r["cuotas"]
    ov = (1/c1)+(1/cx)+(1/c2)
    pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
    pl0, pe0, pv0 = r["V0"]
    pld, ped, pvd = r["Vdual"]
    plr, per, pvr = r["Vruido"]
    opc_v0 = sorted([(pl0, "L"), (pe0, "E"), (pv0, "V")], key=lambda x: -x[0])
    pick_v0 = opc_v0[0][1]; p_top_v0 = opc_v0[0][0]
    opc_vd = sorted([(pld, "L"), (ped, "E"), (pvd, "V")], key=lambda x: -x[0])
    pick_vd = opc_vd[0][1]
    opc_vr = sorted([(plr, "L"), (per, "E"), (pvr, "V")], key=lambda x: -x[0])
    pick_vr = opc_vr[0][1]
    cuota_pick = c1 if pick_v0=="L" else cx if pick_v0=="E" else c2
    pi_pick = pi_l if pick_v0=="L" else pi_e if pick_v0=="E" else pi_v
    ev = p_top_v0 * cuota_pick
    if ev < EV_MIN: return None  # filtro EV minimo

    won = pick_v0 == r["outcome"]

    # Vdual P_top sobre el pick de V0 (no su propio top)
    p_vd_on_v0pick = pld if pick_v0=="L" else ped if pick_v0=="E" else pvd
    p_vr_on_v0pick = plr if pick_v0=="L" else per if pick_v0=="E" else pvr

    div_v0_mkt = p_top_v0 - pi_pick
    div_vd_mkt = p_vd_on_v0pick - pi_pick

    feats = {
        "p_top_v0": p_top_v0,
        "p_vd_on_v0pick": p_vd_on_v0pick,
        "p_vr_on_v0pick": p_vr_on_v0pick,
        "p_implícita_pick": pi_pick,
        "div_v0_mkt": div_v0_mkt,
        "div_vd_mkt": div_vd_mkt,
        "delta_v0_vd": p_top_v0 - p_vd_on_v0pick,
        "consensus_v0_vd": int(pick_v0 == pick_vd),
        "consensus_v0_vr": int(pick_v0 == pick_vr),
        "consensus_3": int(pick_v0 == pick_vd == pick_vr),
        "cuota_pick": cuota_pick,
        "log_cuota": math.log(cuota_pick),
        "is_local": int(pick_v0 == "L"),
        "is_empate": int(pick_v0 == "E"),
        "is_visita": int(pick_v0 == "V"),
        "is_top_liga": int(r["liga"] in TOP_LIGAS),
        "is_turquia": int(r["liga"] == "Turquia"),
        "bin4_q1": int(r.get("bin4") == 0),
        "bin4_q2": int(r.get("bin4") == 1),
        "bin4_q3": int(r.get("bin4") == 2),
        "bin4_q4": int(r.get("bin4") == 3),
        "year": int(r["year"]) - 2022,  # 0..3
    }
    return feats, won, cuota_pick, pick_v0


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas, cal = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas, {len(cal)} calendarios")

    # Walk-forward
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

    # Featurize todos los records con cuotas
    feat_rows = []
    for r in records:
        res = featurize_record(r)
        if res is None: continue
        feats, won, cuota, pick = res
        feat_rows.append((feats, won, cuota, r["year"], r["liga"], pick))

    print(f"Records con feats (post EV>=1.03): {len(feat_rows)}")

    feat_keys = list(feat_rows[0][0].keys())
    print(f"Features: {feat_keys}")

    # ===========================================================================
    # ANÁLISIS 1 — Comparación features entre ganadores vs perdedores
    # ===========================================================================
    print("\n" + "="*100)
    print("ANALISIS 1 — features promedio: ganadores vs perdedores")
    print("="*100)
    print(f"{'feature':<22s}{'won_mean':>10s}{'lost_mean':>11s}{'delta':>10s}{'won_med':>10s}{'lost_med':>10s}")
    won_rows = [r for r in feat_rows if r[1]]
    lost_rows = [r for r in feat_rows if not r[1]]
    print(f"\nN won: {len(won_rows)}  N lost: {len(lost_rows)}")
    print(f"hit_rate global: {len(won_rows)/len(feat_rows)*100:.2f}%\n")
    for k in feat_keys:
        won_vals = [r[0][k] for r in won_rows]
        lost_vals = [r[0][k] for r in lost_rows]
        if not won_vals or not lost_vals: continue
        won_mean = sum(won_vals)/len(won_vals)
        lost_mean = sum(lost_vals)/len(lost_vals)
        delta = won_mean - lost_mean
        won_med = sorted(won_vals)[len(won_vals)//2]
        lost_med = sorted(lost_vals)[len(lost_vals)//2]
        print(f"{k:<22s}{won_mean:>10.4f}{lost_mean:>11.4f}{delta:>+10.4f}{won_med:>10.4f}{lost_med:>10.4f}")

    # ===========================================================================
    # ANÁLISIS 2 — Logistic regression sobre todos los features (TRAIN 2023-24, TEST 25-26)
    # ===========================================================================
    print("\n" + "="*100)
    print("ANALISIS 2 — Logistic regression: predict won")
    print("="*100)
    train = [r for r in feat_rows if r[3] in ("2023", "2024")]
    test  = [r for r in feat_rows if r[3] in ("2025", "2026")]
    X_train = np.array([[r[0][k] for k in feat_keys] for r in train])
    y_train = np.array([int(r[1]) for r in train])
    X_test = np.array([[r[0][k] for k in feat_keys] for r in test])
    y_test = np.array([int(r[1]) for r in test])

    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    X_test_s = scaler.transform(X_test)

    lr = LogisticRegression(max_iter=2000, C=1.0).fit(X_train_s, y_train)
    coefs = list(zip(feat_keys, lr.coef_[0]))
    coefs.sort(key=lambda x: -abs(x[1]))

    print(f"\n{'feature':<22s}{'coef_std':>10s}")
    for k, c in coefs:
        sign = "+" if c > 0 else ""
        print(f"{k:<22s}  {sign}{c:>+8.4f}")

    # Predict probas test
    probs_test = lr.predict_proba(X_test_s)[:, 1]
    # Aplicar threshold sobre prob_won, medir yield
    print("\n--- ANÁLISIS 3 — Yield aplicando filtro logistic ---")
    print(f"{'thr_p_won':<10s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'pnl':>9s}")
    for thr in [0.40, 0.45, 0.50, 0.55, 0.60]:
        bets = [(r, p) for r, p in zip(test, probs_test) if p >= thr]
        if len(bets) < 5: continue
        wins = sum(1 for r, _ in bets if r[1])
        pnl = sum((r[2]-1.0) if r[1] else -1.0 for r, _ in bets)
        n = len(bets)
        print(f"{thr:<10.2f}{n:>6d}{wins/n*100:>6.2f}%{pnl/n*100:>8.2f}%{pnl:>9.2f}")

    # ===========================================================================
    # ANÁLISIS 4 — Walk-forward LR (refit cada año test)
    # ===========================================================================
    print("\n" + "="*100)
    print("ANALISIS 4 — Walk-forward LR refit por año test")
    print("="*100)
    print(f"{'year_test':<12s}{'thr':<6s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'ROI':>9s}")
    bets_total = []
    for yt in YEARS_TEST:
        train_y = [r for r in feat_rows if r[3] < yt]
        test_y  = [r for r in feat_rows if r[3] == yt]
        if len(train_y) < 50 or not test_y: continue
        Xtr = np.array([[r[0][k] for k in feat_keys] for r in train_y])
        ytr = np.array([int(r[1]) for r in train_y])
        Xte = np.array([[r[0][k] for k in feat_keys] for r in test_y])
        sc = StandardScaler().fit(Xtr)
        Xtr_s = sc.transform(Xtr); Xte_s = sc.transform(Xte)
        lr_y = LogisticRegression(max_iter=2000, C=1.0).fit(Xtr_s, ytr)
        probs = lr_y.predict_proba(Xte_s)[:, 1]
        for thr in [0.45, 0.50, 0.55, 0.60]:
            bets = [(r, p) for r, p in zip(test_y, probs) if p >= thr]
            if len(bets) < 3: continue
            wins = sum(1 for r, _ in bets if r[1])
            pnl = sum((r[2]-1.0) if r[1] else -1.0 for r, _ in bets)
            n = len(bets)
            roi = pnl  # base 100
            print(f"{yt:<12s}{thr:<6.2f}{n:>6d}{wins/n*100:>6.2f}%{pnl/n*100:>8.2f}%{roi:>+8.2f}")
            if thr == 0.55:
                for r, _ in bets:
                    bets_total.append((r[1], r[2], r[3], r[4]))
        print()

    # IS pooled walk-forward thr=0.55
    if bets_total:
        n = len(bets_total); wins = sum(b[0] for b in bets_total)
        pnl = sum((b[1]-1.0) if b[0] else -1.0 for b in bets_total)
        print(f"\nIS POOLED walk-forward (thr=0.55): N={n} hit={wins/n*100:.2f}% yield={pnl/n*100:+.2f}% ROI_100={pnl:+.2f}")

        # Bootstrap
        import random
        random.seed(42)
        pnls = [(b[1]-1.0) if b[0] else -1.0 for b in bets_total]
        boot = [sum(random.choice(pnls) for _ in range(n))/n*100 for _ in range(10000)]
        boot.sort()
        print(f"Bootstrap CI95%: [{boot[250]:+.2f}%, {boot[9750]:+.2f}%]  P(>0)={sum(1 for x in boot if x>0)/100:.1f}%")

    # ===========================================================================
    # ANÁLISIS 5 — Reglas hard-coded basadas en findings
    # ===========================================================================
    print("\n" + "="*100)
    print("ANALISIS 5 — Reglas hard-coded multi-criterio")
    print("="*100)

    def regla_oro_v2(feats):
        """Regla compuesta: combinación AND de criterios discriminantes."""
        score = 0
        # P_top alto
        if feats["p_top_v0"] >= 0.55: score += 1
        if feats["p_top_v0"] >= 0.60: score += 1
        # Divergencia
        if feats["div_v0_mkt"] >= 0.05: score += 1
        if feats["div_v0_mkt"] >= 0.10: score += 1
        # Consensus
        if feats["consensus_v0_vd"]: score += 1
        if feats["consensus_3"]: score += 1
        # Pick LOCAL (descalibracion confirmada en favoritos)
        if feats["is_local"]: score += 1
        # Cuota in [1.5, 2.5)
        if 1.5 <= feats["cuota_pick"] < 2.5: score += 1
        # NO Turquía
        if feats["is_turquia"]: score -= 3
        # Vdual subestima vs V0 (delta positivo = V0 más confidente)
        if feats["delta_v0_vd"] > 0.05: score += 1
        return score

    print(f"\n{'score_min':<10s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'cuota_avg':>11s}{'ROI_100':>9s}")
    score_grid = {}
    for sm in range(-2, 11):
        bets = []
        for r, won, cuota, year, liga, pick in feat_rows:
            if regla_oro_v2(r) < sm: continue
            bets.append((won, cuota, (cuota-1.0) if won else -1.0, year, liga))
        if len(bets) < 10: continue
        n = len(bets); wins = sum(b[0] for b in bets); pnl = sum(b[2] for b in bets)
        cuota_avg = sum(b[1] for b in bets)/n
        score_grid[sm] = (n, wins/n*100, pnl/n*100, pnl, cuota_avg)
        print(f"{sm:<10d}{n:>6d}{wins/n*100:>6.2f}%{pnl/n*100:>8.2f}%{cuota_avg:>11.2f}{pnl:>+8.2f}")

    # Persist
    Path("analisis/filtro_de_oro_v2_logistic.json").write_text(
        json.dumps({"feat_keys": feat_keys, "lr_coefs_sorted": [(k, c) for k, c in coefs],
                    "score_grid_v2": {str(k): list(v) for k, v in score_grid.items()}},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/filtro_de_oro_v2_logistic.json")


if __name__ == "__main__":
    main()

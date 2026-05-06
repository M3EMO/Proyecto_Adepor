"""Filtro de oro v3 — universo expandido (N=7990 cuotas vs 2689 antes).

Usa cols ht_fdco_norm/at_fdco_norm (post fix mappings).

Análisis adicional:
1. Stats reales del partido (pre-EMA) — ¿qué stats tienen en común los ganadores?
2. EMAs pre-partido (estado del equipo al momento de apostar).
3. Re-cálculo filtro de oro con N expandido.
"""
import sqlite3
import math
import json
import random
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
        JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha=f.fecha
         AND s.ht_fdco_norm = f.equipo_local_norm
         AND s.at_fdco_norm = f.equipo_visita_norm
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
                        "saves_rival": asv2 or 0, "blocks_rival": abl or 0, "longballs_acc": hlba or 0,
                        "match_stats": {"sot_l": hst, "sot_v": ast, "shots_l": hs, "shots_v": asv,
                                        "corners_l": hc, "corners_v": ac, "pos_l": hp, "pos_v": ap,
                                        "pass_pct_l": hpp, "pass_pct_v": app, "saves_l": hsv, "saves_v": asv2,
                                        "blocks_l": hbl, "blocks_v": abl, "longballs_l": hlba, "longballs_v": alba}})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast),
                        "corners": ac, "pos": ap or 50, "pass_pct": app or 0,
                        "saves_rival": hsv or 0, "blocks_rival": hbl or 0, "longballs_acc": alba or 0,
                        "match_stats": {"sot_l": hst, "sot_v": ast, "shots_l": hs, "shots_v": asv,
                                        "corners_l": hc, "corners_v": ac, "pos_l": hp, "pos_v": ap,
                                        "pass_pct_l": hpp, "pass_pct_v": app, "saves_l": hsv, "saves_v": asv2,
                                        "blocks_l": hbl, "blocks_v": abl, "longballs_l": hlba, "longballs_v": alba}})
    return eventos


def fit_v5_xg(eventos_train):
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
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
                    "fecha": key[1], "liga": key[0], "match_stats": ev_l["match_stats"]}
        xl = calc_xg(ev_l, fit_xg); xv = calc_xg(ev_v, fit_xg)
        rl = ev_l["goles"]-xl; rv = ev_v["goles"]-xv
        sh["xg_h"] = xl if sh["xg_h"] is None else alfa*xl+(1-alfa)*sh["xg_h"]
        sh["res_h"] = rl if sh["res_h"] is None else alfa*rl+(1-alfa)*sh["res_h"]; sh["n_h"] += 1
        sa["xg_a"] = xv if sa["xg_a"] is None else alfa*xv+(1-alfa)*sa["xg_a"]
        sa["res_a"] = rv if sa["res_a"] is None else alfa*rv+(1-alfa)*sa["res_a"]; sa["n_a"] += 1
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


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas, cal = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas (POST FIX MATCH)")

    records = []
    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train)
        state_dual = construir_state_dual(eventos, fit_v5, ALFA_EMA)
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        fit_lam_d = fit_lambda_dual(state_dual, yt)
        if not fit_lam_d: continue
        pairs_v0, pairs_d = [], []
        for key, val in emas_v0.items():
            lh, lv, _, _ = val
            if lh is None or lv is None: continue
            pairs_v0.append((key[0], key[1], lh, lv, val[2], val[3]))
        for key, d in state_dual.items():
            if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            lh_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_h"]+fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_v"]+fit_lam_d["coef"][1]*d["res_v"])
            pairs_d.append((d["liga"], d["fecha"], lh_d, lv_d, d["hg"], d["ag"]))
        rhos_v0 = calibrar_rho(pairs_v0, yt)
        rhos_d = calibrar_rho(pairs_d, yt)
        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            lh_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_h"]+fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"]+fit_lam_d["coef"][0]*d["xg_v"]+fit_lam_d["coef"][1]*d["res_v"])
            pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
            outcome = "L" if hg > ag else ("E" if hg == ag else "V")
            records.append({
                "key": key, "year": yt, "liga": key[0], "outcome": outcome,
                "V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd),
                "cuotas": cuotas.get(key), "match_stats": d.get("match_stats"),
                "ema_xg_h": d["xg_h"], "ema_xg_v": d["xg_v"],
                "ema_res_h": d["res_h"], "ema_res_v": d["res_v"]
            })
    print(f"Records: {len(records)}, con cuotas: {sum(1 for r in records if r['cuotas'])}")

    # ============================================================
    # FILTRO DE ORO V3 sobre N expandido
    # ============================================================
    def regla_oro_v2(r):
        if r["cuotas"] is None: return None
        c1, cx, c2 = r["cuotas"]
        ov = (1/c1)+(1/cx)+(1/c2)
        pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
        opc = sorted([(r["V0"][0],"L"),(r["V0"][1],"E"),(r["V0"][2],"V")], key=lambda x: -x[0])
        p_top, pick = opc[0]
        opc_d = sorted([(r["Vdual"][0],"L"),(r["Vdual"][1],"E"),(r["Vdual"][2],"V")], key=lambda x: -x[0])
        pick_d = opc_d[0][1]
        cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
        pi_pick = pi_l if pick=="L" else pi_e if pick=="E" else pi_v
        ev = p_top * cuota_pick
        if ev < EV_MIN: return None
        score = 0
        if p_top >= 0.55: score += 1
        if p_top >= 0.60: score += 1
        if p_top - pi_pick >= 0.05: score += 1
        if p_top - pi_pick >= 0.10: score += 1
        if pick == pick_d: score += 1
        if pick == "L": score += 1
        if 1.5 <= cuota_pick < 2.5: score += 1
        p_dual_pick = r["Vdual"][0] if pick=="L" else r["Vdual"][1] if pick=="E" else r["Vdual"][2]
        if p_top - p_dual_pick > 0.05: score += 1
        if r["liga"] == "Turquia": score -= 3
        return score, pick, cuota_pick, p_top

    print("\n" + "="*100)
    print("FILTRO ORO v2 sobre UNIVERSO EXPANDIDO (N=7990 cuotas)")
    print("="*100)
    print(f"{'score_min':<10s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'cuota_avg':>11s}{'ROI_100':>9s}")
    score_results = {}
    for sm in range(-2, 11):
        bets = []
        for r in records:
            res = regla_oro_v2(r)
            if res is None: continue
            score, pick, cuota_pick, p_top = res
            if score < sm: continue
            won = pick == r["outcome"]
            pnl = (cuota_pick - 1.0) if won else -1.0
            bets.append((won, cuota_pick, pnl, r["year"], r["liga"]))
        if len(bets) < 10: continue
        n = len(bets); hits = sum(b[0] for b in bets); pnl = sum(b[2] for b in bets)
        cuota_avg = sum(b[1] for b in bets)/n
        score_results[sm] = (n, hits/n*100, pnl/n*100, pnl, cuota_avg, bets)
        print(f"{sm:<10d}{n:>6d}{hits/n*100:>6.2f}%{pnl/n*100:>8.2f}%{cuota_avg:>11.2f}{pnl:>+8.2f}")

    # Bootstrap CI95% sobre score_min con mejor ROI/N
    print("\n--- Bootstrap CI95% por score_min ---")
    print(f"{'score':<8s}{'N':>6s}{'yield':>9s}{'CI95_lo':>10s}{'CI95_hi':>10s}{'P(>0)':>9s}{'maxDD':>9s}{'sharpe':>8s}")
    for sm in sorted(score_results.keys()):
        n, hit, yld, pnl, cuota, bets = score_results[sm]
        if n < 50: continue
        pnls = [b[2] for b in bets]
        # Bootstrap
        boots = [sum(random.choice(pnls) for _ in range(n))/n*100 for _ in range(5000)]
        boots.sort()
        ci_lo, ci_hi = boots[125], boots[4875]
        ppos = sum(1 for x in boots if x > 0)/5000*100
        # MaxDD simulando bankroll
        bets_sorted = sorted(bets, key=lambda b: b[3])  # year as proxy
        bk = 100; peak = 100; max_dd = 0
        for b in bets_sorted:
            bk += b[2]; peak = max(peak, bk)
            dd = (peak - bk)/peak*100
            max_dd = max(max_dd, dd)
        # Sharpe
        mean_pnl = sum(pnls)/n; var = sum((p-mean_pnl)**2 for p in pnls)/n
        std = math.sqrt(var); sharpe = mean_pnl/std*math.sqrt(n) if std > 0 else 0
        print(f"{sm:<8d}{n:>6d}{yld:>+8.2f}%{ci_lo:>+9.2f}%{ci_hi:>+9.2f}%{ppos:>+8.2f}%{max_dd:>8.2f}%{sharpe:>8.2f}")

    # ============================================================
    # ANÁLISIS STATS REALES PARTIDO — qué tienen en común ganadores
    # ============================================================
    print("\n" + "="*100)
    print("ANALISIS STATS REALES — qué tienen en común ganadores (over Filtro_oro score>=8)")
    print("="*100)
    # Solo records que pasan filtro oro v2 score>=8 y tienen match_stats
    bets_8 = []
    for r in records:
        res = regla_oro_v2(r)
        if res is None: continue
        score, pick, cuota_pick, p_top = res
        if score < 8: continue
        if r["match_stats"] is None: continue
        won = pick == r["outcome"]
        bets_8.append({"won": won, "cuota": cuota_pick, "pick": pick, "ms": r["match_stats"],
                       "ema_xg_h": r["ema_xg_h"], "ema_xg_v": r["ema_xg_v"],
                       "ema_res_h": r["ema_res_h"], "ema_res_v": r["ema_res_v"],
                       "liga": r["liga"], "year": r["year"]})
    won_b = [b for b in bets_8 if b["won"]]; lost_b = [b for b in bets_8 if not b["won"]]
    print(f"\nN bets score>=8: {len(bets_8)} (won={len(won_b)}, lost={len(lost_b)})")
    print(f"Hit rate: {len(won_b)/len(bets_8)*100:.2f}%")

    # Stats reales: comparar promedios won vs lost
    feat_names = ["sot_l", "sot_v", "shots_l", "shots_v", "corners_l", "corners_v",
                  "pos_l", "pos_v", "pass_pct_l", "pass_pct_v",
                  "saves_l", "saves_v", "blocks_l", "blocks_v", "longballs_l", "longballs_v"]
    print(f"\n{'stat real':<16s}{'won_avg':>10s}{'lost_avg':>10s}{'delta':>10s}{'pct_diff':>10s}")
    for f in feat_names:
        won_v = [b["ms"][f] for b in won_b if b["ms"].get(f) is not None]
        lost_v = [b["ms"][f] for b in lost_b if b["ms"].get(f) is not None]
        if not won_v or not lost_v: continue
        wa, la = sum(won_v)/len(won_v), sum(lost_v)/len(lost_v)
        delta = wa - la
        pct = (delta/la*100) if la else 0
        print(f"{f:<16s}{wa:>10.2f}{la:>10.2f}{delta:>+10.2f}{pct:>+9.1f}%")

    # EMAs pre-partido
    print(f"\n{'EMA pre-bet':<20s}{'won_avg':>10s}{'lost_avg':>10s}{'delta':>10s}")
    for f in ("ema_xg_h", "ema_xg_v", "ema_res_h", "ema_res_v"):
        won_v = [b[f] for b in won_b if b.get(f) is not None]
        lost_v = [b[f] for b in lost_b if b.get(f) is not None]
        if not won_v or not lost_v: continue
        wa, la = sum(won_v)/len(won_v), sum(lost_v)/len(lost_v)
        print(f"{f:<20s}{wa:>10.4f}{la:>10.4f}{(wa-la):>+10.4f}")

    # diferencia EMAs ataque/defensa
    print(f"\n{'EMA diff':<20s}{'won_avg':>10s}{'lost_avg':>10s}{'delta':>10s}")
    won_diffs = []
    lost_diffs = []
    for b in won_b:
        if all(b[f] is not None for f in ("ema_xg_h", "ema_xg_v")):
            won_diffs.append(b["ema_xg_h"] - b["ema_xg_v"])
    for b in lost_b:
        if all(b[f] is not None for f in ("ema_xg_h", "ema_xg_v")):
            lost_diffs.append(b["ema_xg_h"] - b["ema_xg_v"])
    if won_diffs and lost_diffs:
        wa = sum(won_diffs)/len(won_diffs); la = sum(lost_diffs)/len(lost_diffs)
        print(f"{'ema_xg_h - ema_xg_v':<20s}{wa:>10.4f}{la:>10.4f}{(wa-la):>+10.4f}")

    # Logistic regression sobre stats reales + EMAs
    print("\n--- LR predict won — features stats reales + EMAs ---")
    train = [b for b in bets_8 if b["year"] in ("2023", "2024")]
    test = [b for b in bets_8 if b["year"] in ("2025", "2026")]
    if len(train) > 30 and len(test) > 5:
        feats_lr = ["sot_l", "sot_v", "shots_l", "shots_v", "corners_l", "corners_v",
                    "pos_l", "pos_v", "saves_l", "saves_v", "ema_xg_h", "ema_xg_v",
                    "ema_res_h", "ema_res_v"]
        def feat_vec(b):
            v = []
            for f in feats_lr:
                if f.startswith("ema_"): v.append(b.get(f) or 0)
                else: v.append(b["ms"].get(f) or 0)
            return v
        Xtr = np.array([feat_vec(b) for b in train]); ytr = np.array([int(b["won"]) for b in train])
        Xte = np.array([feat_vec(b) for b in test]); yte = np.array([int(b["won"]) for b in test])
        sc = StandardScaler().fit(Xtr); Xtr_s = sc.transform(Xtr); Xte_s = sc.transform(Xte)
        lr = LogisticRegression(max_iter=2000).fit(Xtr_s, ytr)
        coefs = sorted(zip(feats_lr, lr.coef_[0]), key=lambda x: -abs(x[1]))
        print(f"\n{'feature':<16s}{'coef':>10s}")
        for f, c in coefs:
            print(f"{f:<16s}{c:>+10.4f}")

    Path("analisis/filtro_de_oro_v3.json").write_text(
        json.dumps({"score_results": {str(k): list(v[:5]) for k, v in score_results.items()}},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/filtro_de_oro_v3.json")


if __name__ == "__main__":
    main()

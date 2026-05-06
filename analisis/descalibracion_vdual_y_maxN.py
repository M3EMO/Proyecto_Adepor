"""Análisis profundo descalibración V_dual + maximización N apostable.

PARTE A — Descalibración V_dual:
  Por bucket P_top, por liga, por pick (L/E/V), por cuota, por bin4
  identificar DÓNDE V_dual underestima sus probas.

PARTE B — Maximizar N apostable manteniendo yield > 0:
  Estrategias usando V0, V_dual, V_ruido, MKT como ensemble.

PARTE C — Estrategias compuestas para producción:
  Distintas combinaciones probando max_N preservando yield.
"""
import sqlite3
import math
import json
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
    return rows, cuotas


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


def normalize_3(p1, p2, p3):
    s = p1+p2+p3
    if s > 0: return p1/s, p2/s, p3/s
    return 1/3, 1/3, 1/3


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas")

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
            records.append({
                "key": key, "year": yt, "liga": key[0], "outcome": outcome,
                "V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd), "Vruido": (plr, per, pvr),
                "cuotas": cuotas.get(key)
            })

    print(f"Records OOS: {len(records)}")
    rec_cuotas = [r for r in records if r["cuotas"] is not None]
    print(f"Records con cuotas: {len(rec_cuotas)}")

    # ===========================================================================
    # PARTE A — Descalibracion V_dual desglosada
    # ===========================================================================
    print("\n" + "="*120)
    print("PARTE A — DESCALIBRACION V_DUAL (P_top vs hit_obs)")
    print("="*120)

    # A.1 — Por bucket P × pick (L/E/V)
    print("\n--- A.1 — V_dual ECE por bucket P × pick ---")
    print(f"{'pick':<6s}{'bucket':<14s}{'N':>6s}{'P_avg':>8s}{'hit_obs':>9s}{'gap':>9s}")
    pick_bucket = defaultdict(lambda: {"P": [], "won": []})
    for r in records:
        pl, pe, pv = r["Vdual"]
        opciones = [(pl, "L"), (pe, "E"), (pv, "V")]
        opciones.sort(key=lambda x: -x[0])
        p_top, pick = opciones[0]
        won = pick == r["outcome"]
        pick_bucket[pick]["P"].append(p_top)
        pick_bucket[pick]["won"].append(won)
    BUCKETS = [(0.0, 0.30), (0.30, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.0)]
    for pick in ("L", "E", "V"):
        ps = pick_bucket[pick]["P"]; ws = pick_bucket[pick]["won"]
        for lo, hi in BUCKETS:
            in_b = [(p, w) for p, w in zip(ps, ws) if lo <= p < hi]
            if len(in_b) < 5: continue
            p_avg = sum(p for p, _ in in_b)/len(in_b)
            hit = sum(w for _, w in in_b)/len(in_b)
            gap = hit - p_avg  # positivo = underconfident
            print(f"{pick:<6s}[{lo:.2f},{hi:.2f}){'':<3s}{len(in_b):>6d}{p_avg:>8.4f}{hit:>9.4f}{gap:>+9.4f}")
        print()

    # A.2 — Por liga × bucket apostable (P >= 0.50)
    print("\n--- A.2 — V_dual ECE en bucket apostable (P >= 0.50) por liga ---")
    print(f"{'liga':<14s}{'N':>6s}{'P_avg':>8s}{'hit_obs':>9s}{'gap':>9s}")
    by_liga = defaultdict(lambda: {"P": [], "won": []})
    for r in records:
        pl, pe, pv = r["Vdual"]
        opciones = [(pl, "L"), (pe, "E"), (pv, "V")]
        opciones.sort(key=lambda x: -x[0])
        p_top, pick = opciones[0]
        if p_top < 0.50: continue
        by_liga[r["liga"]]["P"].append(p_top)
        by_liga[r["liga"]]["won"].append(pick == r["outcome"])
    for liga in sorted(by_liga.keys()):
        ps = by_liga[liga]["P"]; ws = by_liga[liga]["won"]
        if len(ps) < 10: continue
        p_avg = sum(ps)/len(ps); hit = sum(ws)/len(ws); gap = hit - p_avg
        print(f"{liga:<14s}{len(ps):>6d}{p_avg:>8.4f}{hit:>9.4f}{gap:>+9.4f}")

    # A.3 — Por cuota_pick × bucket P (descalib en favoritos vs underdogs)
    print("\n--- A.3 — V_dual descalib por banda de cuota_pick ---")
    bands_cuota = [(1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.5), (3.5, 5.0), (5.0, 99)]
    print(f"{'banda':<14s}{'N':>6s}{'P_avg':>8s}{'hit_obs':>9s}{'gap':>9s}")
    for lo, hi in bands_cuota:
        in_b = []
        for r in rec_cuotas:
            pl, pe, pv = r["Vdual"]
            opciones = [(pl, "L"), (pe, "E"), (pv, "V")]
            opciones.sort(key=lambda x: -x[0])
            p_top, pick = opciones[0]
            c1, cx, c2 = r["cuotas"]
            cuota_pick = c1 if pick == "L" else cx if pick == "E" else c2
            if not (lo <= cuota_pick < hi): continue
            in_b.append((p_top, pick == r["outcome"]))
        if len(in_b) < 10: continue
        p_avg = sum(p for p, _ in in_b)/len(in_b)
        hit = sum(w for _, w in in_b)/len(in_b)
        gap = hit - p_avg
        print(f"[{lo:.1f},{hi:.1f}){'':<5s}{len(in_b):>6d}{p_avg:>8.4f}{hit:>9.4f}{gap:>+9.4f}")

    # ===========================================================================
    # PARTE B — Maximizar N apostable manteniendo yield > 0
    # ===========================================================================
    print("\n" + "="*120)
    print("PARTE B — Estrategias para MAX N apostable con yield > 0")
    print("="*120)

    def evaluate_strategy(records, pick_fn, filter_fn, label):
        """pick_fn(rec) -> (pick, p_top, p_modelo_full). filter_fn(rec, p_top) -> bool."""
        bets = []
        for r in records:
            if r["cuotas"] is None: continue
            res = pick_fn(r)
            if res is None: continue
            pick, p_top = res
            if not filter_fn(r, pick, p_top): continue
            c1, cx, c2 = r["cuotas"]
            cuota_pick = c1 if pick == "L" else cx if pick == "E" else c2
            ev = p_top * cuota_pick
            if ev < EV_MIN: continue
            won = pick == r["outcome"]
            pnl = (cuota_pick - 1.0) if won else -1.0
            bets.append((won, cuota_pick, pnl, r["year"]))
        if not bets:
            return None
        n = len(bets); wins = sum(b[0] for b in bets); pnl = sum(b[2] for b in bets)
        yld = pnl/n*100
        # Por anio
        by_year = defaultdict(lambda: [0, 0])  # [n, pnl]
        for b in bets:
            by_year[b[3]][0] += 1; by_year[b[3]][1] += b[2]
        return {"label": label, "N": n, "hit": wins/n*100, "yield": yld, "pnl": pnl,
                "by_year": {y: (d[0], d[1]/d[0]*100 if d[0] else 0) for y, d in by_year.items()}}

    def pick_argmax(modelo):
        def fn(r):
            ps = r[modelo]
            if ps[0] is None: return None
            opc = [(ps[0], "L"), (ps[1], "E"), (ps[2], "V")]
            opc.sort(key=lambda x: -x[0])
            return opc[0][1], opc[0][0]
        return fn

    def pick_consensus(modelos):
        def fn(r):
            picks = []
            ptops = []
            for m in modelos:
                ps = r[m]
                if ps[0] is None: return None
                opc = [(ps[0], "L"), (ps[1], "E"), (ps[2], "V")]
                opc.sort(key=lambda x: -x[0])
                picks.append(opc[0][1]); ptops.append(opc[0][0])
            if len(set(picks)) == 1:
                return picks[0], sum(ptops)/len(ptops)
            return None
        return fn

    def pick_avg(modelos):
        def fn(r):
            avg_l = avg_e = avg_v = 0
            for m in modelos:
                ps = r[m]
                if ps[0] is None: return None
                avg_l += ps[0]; avg_e += ps[1]; avg_v += ps[2]
            n = len(modelos)
            avg_l /= n; avg_e /= n; avg_v /= n
            opc = [(avg_l, "L"), (avg_e, "E"), (avg_v, "V")]
            opc.sort(key=lambda x: -x[0])
            return opc[0][1], opc[0][0]
        return fn

    def filter_div(modelo, thr):
        def fn(r, pick, p_top):
            c1, cx, c2 = r["cuotas"]
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
            return p_top - pi_pick >= thr
        return fn

    def filter_div_avg(thr):
        def fn(r, pick, p_top):
            c1, cx, c2 = r["cuotas"]
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
            return p_top - pi_pick >= thr
        return fn

    def filter_no(r, pick, p_top): return True

    def filter_p_apostable(thr_p_min, thr_div=0.0):
        def fn(r, pick, p_top):
            if p_top < thr_p_min: return False
            c1, cx, c2 = r["cuotas"]
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
            return p_top - pi_pick >= thr_div
        return fn

    print("\n--- B.1 — Estrategias single model con filtros ---")
    print(f"{'strategy':<48s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}")
    strategies = []
    for modelo in ("V0", "Vdual", "Vruido"):
        for div in (0.00, 0.05, 0.10):
            r = evaluate_strategy(records, pick_argmax(modelo), filter_div(modelo, div),
                                   f"{modelo} div>={div}")
            if r and r["N"] >= 30:
                strategies.append(r)
                print(f"{r['label']:<48s}{r['N']:>6d}{r['hit']:>6.2f}%{r['yield']:>8.2f}%")

    print("\n--- B.2 — Estrategias ensemble (avg, consensus) ---")
    for combos in [["V0", "Vdual"], ["V0", "Vruido"], ["Vdual", "Vruido"], ["V0", "Vdual", "Vruido"]]:
        # Avg
        for div in (0.00, 0.05, 0.10):
            label_a = "+".join(combos) + f" AVG div>={div}"
            r = evaluate_strategy(records, pick_avg(combos), filter_div_avg(div), label_a)
            if r and r["N"] >= 30:
                strategies.append(r)
                print(f"{r['label']:<48s}{r['N']:>6d}{r['hit']:>6.2f}%{r['yield']:>8.2f}%")
        # Consensus
        for div in (0.00, 0.05, 0.10):
            label_c = "+".join(combos) + f" CONSENSUS div>={div}"
            r = evaluate_strategy(records, pick_consensus(combos), filter_div_avg(div), label_c)
            if r and r["N"] >= 30:
                strategies.append(r)
                print(f"{r['label']:<48s}{r['N']:>6d}{r['hit']:>6.2f}%{r['yield']:>8.2f}%")

    print("\n--- B.3 — Estrategias con FLOOR_P alto (zona apostable maxima N) ---")
    for modelo in ("V0", "Vdual"):
        for floor_p in (0.45, 0.50, 0.55, 0.60):
            r = evaluate_strategy(records, pick_argmax(modelo),
                                   filter_p_apostable(floor_p, 0.05), f"{modelo} P>={floor_p} div>=0.05")
            if r and r["N"] >= 30:
                strategies.append(r)
                print(f"{r['label']:<48s}{r['N']:>6d}{r['hit']:>6.2f}%{r['yield']:>8.2f}%")

    print("\n--- B.4 — Anchor a mercado (V_dual + alpha*MKT) ---")
    def pick_anchor(modelo, alpha):
        def fn(r):
            ps = r[modelo]
            if ps[0] is None or r["cuotas"] is None: return None
            c1, cx, c2 = r["cuotas"]
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
            pl = alpha*ps[0] + (1-alpha)*pi_l
            pe = alpha*ps[1] + (1-alpha)*pi_e
            pv = alpha*ps[2] + (1-alpha)*pi_v
            s = pl+pe+pv
            pl/=s; pe/=s; pv/=s
            opc = [(pl, "L"), (pe, "E"), (pv, "V")]
            opc.sort(key=lambda x: -x[0])
            return opc[0][1], opc[0][0]
        return fn

    for modelo in ("V0", "Vdual"):
        for alpha in (0.3, 0.5, 0.7):
            for div in (0.05, 0.10):
                r = evaluate_strategy(records, pick_anchor(modelo, alpha), filter_div_avg(div),
                                       f"{modelo} anchor={alpha} div>={div}")
                if r and r["N"] >= 30:
                    strategies.append(r)
                    print(f"{r['label']:<48s}{r['N']:>6d}{r['hit']:>6.2f}%{r['yield']:>8.2f}%")

    # ============================================================================
    # PARTE C — TOP 10 estrategias por (yield > 0 + max N)
    # ============================================================================
    print("\n" + "="*120)
    print("PARTE C — TOP estrategias YIELD > 0 priorizadas por N (volumen)")
    print("="*120)
    yieldpos = [s for s in strategies if s["yield"] > 0]
    yieldpos.sort(key=lambda x: -x["N"])
    print(f"\n{'strategy':<48s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'pnl':>9s}")
    for s in yieldpos[:15]:
        print(f"{s['label']:<48s}{s['N']:>6d}{s['hit']:>6.2f}%{s['yield']:>8.2f}%{s['pnl']:>9.2f}")

    print("\n--- TOP por yield (N >= 100) ---")
    yp_n100 = [s for s in strategies if s["yield"] > 0 and s["N"] >= 100]
    yp_n100.sort(key=lambda x: -x["yield"])
    print(f"{'strategy':<48s}{'N':>6s}{'yield%':>9s}")
    for s in yp_n100[:10]:
        print(f"{s['label']:<48s}{s['N']:>6d}{s['yield']:>8.2f}%")

    print("\n--- TOP por yield (N >= 200) ---")
    yp_n200 = [s for s in strategies if s["yield"] > 0 and s["N"] >= 200]
    yp_n200.sort(key=lambda x: -x["yield"])
    print(f"{'strategy':<48s}{'N':>6s}{'yield%':>9s}")
    for s in yp_n200[:10]:
        print(f"{s['label']:<48s}{s['N']:>6d}{s['yield']:>8.2f}%")

    # Persist
    Path("analisis/descalibracion_vdual_y_maxN.json").write_text(
        json.dumps([{"label": s["label"], "N": s["N"], "hit": s["hit"], "yield": s["yield"], "pnl": s["pnl"], "by_year": s["by_year"]} for s in strategies],
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/descalibracion_vdual_y_maxN.json")


if __name__ == "__main__":
    main()

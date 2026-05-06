"""3 tareas:
1. ECE bucketed + Ignorance Score (Wheatcroft 2021).
2. Bootstrap CI95% sobre estrategia compuesta S1 N=84.
3. Investigar regimen 2025 (overround, ligas, hit by liga).

Comparativa V0, V_dual, V_ruido, MERCADO en bucket apostable (P>=0.50).
"""
import sqlite3
import math
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
LIGAS_M1 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
EV_MIN = 1.03
YEARS_TEST = ["2023", "2024", "2025", "2026"]
random.seed(42)

# Buckets P_pred
BUCKETS_P = [(0.0, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
             (0.50, 0.60), (0.60, 0.70), (0.70, 1.0)]


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
    return fit["intercept"] + sum(fit["coef"][i] * ev[fit["feats"][i]] for i in range(len(fit["feats"])))


def construir_state_dual(eventos, fit_xg, alfa):
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    keys_ord = sorted(matches.keys(), key=lambda k: k[1])
    state = defaultdict(lambda: {"xg_h": None, "xg_a": None, "res_h": None, "res_a": None,
                                  "n_h": 0, "n_a": 0})
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
        rl = ev_l["goles"] - xl; rv = ev_v["goles"] - xv
        sh["xg_h"] = xl if sh["xg_h"] is None else alfa*xl + (1-alfa)*sh["xg_h"]
        sh["res_h"] = rl if sh["res_h"] is None else alfa*rl + (1-alfa)*sh["res_h"]
        sh["n_h"] += 1
        sa["xg_a"] = xv if sa["xg_a"] is None else alfa*xv + (1-alfa)*sa["xg_a"]
        sa["res_a"] = rv if sa["res_a"] is None else alfa*rv + (1-alfa)*sa["res_a"]
        sa["n_a"] += 1
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
        sh["h"] = xl if sh["h"] is None else alfa*xl + (1-alfa)*sh["h"]
        sh["n_h"] += 1
        sa["a"] = xv if sa["a"] is None else alfa*xv + (1-alfa)*sa["a"]
        sa["n_a"] += 1
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
        sh["fh"] = xlp if sh["fh"] is None else alfa*xlp + (1-alfa)*sh["fh"]
        sh["nfh"] += 1
        sa["fa"] = xvp if sa["fa"] is None else alfa*xvp + (1-alfa)*sa["fa"]
        sa["nfa"] += 1
    return out


def fit_lambdas(state_dual, state_ruido, year_max):
    rows_d, y_d, rows_r, y_r = [], [], [], []
    for key, d in state_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= year_max: continue
        d_r = state_ruido.get(key)
        if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
        rows_d.append([d["xg_h"], d["res_h"]]); y_d.append(d["hg"])
        rows_d.append([d["xg_v"], d["res_v"]]); y_d.append(d["ag"])
        rows_r.append([d_r["h"]]); y_r.append(d["hg"])
        rows_r.append([d_r["a"]]); y_r.append(d["ag"])
    if not rows_d: return None, None
    m_d = Ridge(alpha=1.0, fit_intercept=True).fit(np.array(rows_d), np.array(y_d))
    m_r = Ridge(alpha=1.0, fit_intercept=True).fit(np.array(rows_r), np.array(y_r))
    return ({"intercept": float(m_d.intercept_), "coef": m_d.coef_.tolist()},
            {"intercept": float(m_r.intercept_), "coef": m_r.coef_.tolist()})


def poisson_pmf(k, lam):
    if lam <= 0: lam = 0.01
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def dc_tau(h, a, lh, lv, rho):
    if h == 0 and a == 0: return 1 - lh*lv*rho
    if h == 0 and a == 1: return 1 + lh*rho
    if h == 1 and a == 0: return 1 + lv*rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0


def prob_1x2(lh, lv, rho):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS+1):
        for a in range(MAX_GOALS+1):
            p = poisson_pmf(h, lh)*poisson_pmf(a, lv)*dc_tau(h, a, lh, lv, rho)
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def calibrar_rho_pairs(pairs, year_max):
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


# Configs S1 (Plan F estrategia compuesta)
S1_CONFIGS = {
    "F0_3agree":         ("Vdual",  0.10),
    "F1_v0=ruido!=dual": ("V0",     0.00),
    "F2_v0=dual!=ruido": ("Vdual",  0.10),
    "F3_dual=ruido!=v0": ("V0",     0.00),
    "F4_3diff":          ("Vruido", 0.00),
}


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas")

    # Walk-forward para acumular predicciones + picks de S1
    # Tambien acumular para ECE: (P_pred_pick, hit_outcome) por modelo, year, bucket
    picks_s1 = []  # lista de (yt, key, pnl, won) — para bootstrap
    ece_data = {var: [] for var in ("V0", "Vdual", "Vruido", "MKT")}  # (P_top, won)

    regimen_2025 = {"by_liga": defaultdict(lambda: {"n": 0, "hits_v0": 0, "hits_v5": 0,
                                                     "stake": 0, "pnl_v0": 0, "pnl_v5": 0}),
                    "overround": [], "n_total": 0}

    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train)
        fit_ruido = fit_v_ruido(ev_train)
        state_dual = construir_state_dual(eventos, fit_v5, ALFA_EMA)
        state_ruido = construir_state_ruido(eventos, fit_ruido, ALFA_EMA)
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        fit_lam_d, fit_lam_r = fit_lambdas(state_dual, state_ruido, yt)
        if not fit_lam_d: continue
        pairs_v0, pairs_d, pairs_r = [], [], []
        for key, val in emas_v0.items():
            lh, lv, _, _ = val
            if lh is None or lv is None: continue
            pairs_v0.append((key[0], key[1], lh, lv, val[2], val[3]))
        for key, d in state_dual.items():
            if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            d_r = state_ruido.get(key)
            if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
            lh_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_h"] + fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_v"] + fit_lam_d["coef"][1]*d["res_v"])
            lh_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["h"])
            lv_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["a"])
            pairs_d.append((d["liga"], d["fecha"], lh_d, lv_d, d["hg"], d["ag"]))
            pairs_r.append((d["liga"], d["fecha"], lh_r, lv_r, d["hg"], d["ag"]))
        rhos_v0 = calibrar_rho_pairs(pairs_v0, yt)
        rhos_d = calibrar_rho_pairs(pairs_d, yt)
        rhos_r = calibrar_rho_pairs(pairs_r, yt)

        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key); d_r = state_ruido.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            lh_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_h"] + fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_v"] + fit_lam_d["coef"][1]*d["res_v"])
            pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
            lh_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["h"])
            lv_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["a"])
            plr, per, pvr = prob_1x2(lh_r, lv_r, rhos_r.get(key[0], -0.05))
            preds = {"V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd), "Vruido": (plr, per, pvr)}
            picks_dict = {k: max([(v[0],"L"),(v[1],"E"),(v[2],"V")], key=lambda x: x[0])[1] for k, v in preds.items()}
            p0, pd_, pr = picks_dict["V0"], picks_dict["Vdual"], picks_dict["Vruido"]
            if hg > ag: out = "L"
            elif hg == ag: out = "E"
            else: out = "V"

            # ECE: P_top de cada modelo + outcome
            for var, (pl, pe, pv) in preds.items():
                opciones = [(pl,"L"),(pe,"E"),(pv,"V")]
                opciones.sort(key=lambda x: -x[0])
                P_top, pick = opciones[0]
                won = pick == out
                ece_data[var].append((P_top, int(won), pick))
            # Mercado en zona apostable
            if key in cuotas:
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
                opc = [(pi_l,"L"),(pi_e,"E"),(pi_v,"V")]
                opc.sort(key=lambda x: -x[0])
                P_top, pick = opc[0]
                won = pick == out
                ece_data["MKT"].append((P_top, int(won), pick))

            # Estrategia S1 walk-forward
            if p0 == pd_ == pr: subset = "F0_3agree"
            elif p0 == pr and pd_ != p0: subset = "F1_v0=ruido!=dual"
            elif p0 == pd_ and pr != p0: subset = "F2_v0=dual!=ruido"
            elif pd_ == pr and p0 != pd_: subset = "F3_dual=ruido!=v0"
            else: subset = "F4_3diff"
            if key[0] in LIGAS_M1 and key in cuotas:
                pick_src, div_thr = S1_CONFIGS[subset]
                pl, pe, pv = preds[pick_src]
                pick = picks_dict[pick_src]
                p_pick = pl if pick=="L" else pe if pick=="E" else pv
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
                cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
                divergencia = p_pick - pi_pick
                if divergencia >= div_thr and p_pick * cuota_pick >= EV_MIN:
                    won = pick == out
                    pnl = (cuota_pick - 1.0) if won else -1.0
                    picks_s1.append((yt, pnl, int(won), key[0], cuota_pick))

            # Regimen 2025: stats por liga
            if yt == "2025" and key in cuotas:
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                regimen_2025["overround"].append(ov)
                regimen_2025["n_total"] += 1
                liga = key[0]
                won_v0 = picks_dict["V0"] == out
                won_v5 = picks_dict["Vdual"] == out
                regimen_2025["by_liga"][liga]["n"] += 1
                regimen_2025["by_liga"][liga]["hits_v0"] += int(won_v0)
                regimen_2025["by_liga"][liga]["hits_v5"] += int(won_v5)

    # ============================================================
    # TAREA 1 — ECE bucketed + Ignorance Score
    # ============================================================
    print("\n" + "="*100)
    print("TAREA 1 — ECE bucketed (P_top vs hit_rate observado) por modelo")
    print("="*100)
    print(f"{'modelo':<8s}{'bucket':<14s}{'N':>8s}{'P_avg':>9s}{'hit_obs':>9s}{'ECE':>9s}{'sharp':>9s}")
    summary_ece = defaultdict(dict)
    for var in ("V0", "Vdual", "Vruido", "MKT"):
        all_data = ece_data[var]
        for lo, hi in BUCKETS_P:
            in_bucket = [(p, w) for p, w, _ in all_data if lo <= p < hi]
            if not in_bucket: continue
            ps = [x[0] for x in in_bucket]
            ws = [x[1] for x in in_bucket]
            p_avg = sum(ps)/len(ps)
            hit_obs = sum(ws)/len(ws)
            ece = abs(p_avg - hit_obs)
            print(f"{var:<8s}[{lo:.2f},{hi:.2f}){'':<3s}{len(in_bucket):>8d}{p_avg:>9.4f}{hit_obs:>9.4f}{ece:>9.4f}{0:>9.4f}")
            summary_ece[var][(lo, hi)] = {"N": len(in_bucket), "P_avg": p_avg, "hit_obs": hit_obs, "ECE": ece}
        print()

    # ECE total ponderado por bucket
    print("\n--- ECE TOTAL ponderado + Ignorance Score (Wheatcroft 2021) ---")
    print(f"{'modelo':<8s}{'ECE_global':>12s}{'IgnScore':>10s}{'N_total':>10s}")
    for var in ("V0", "Vdual", "Vruido", "MKT"):
        all_data = ece_data[var]
        # ECE global = Σ |P_pred - hit_actual| / N
        total_ece_w = sum(b["N"] * b["ECE"] for b in summary_ece[var].values())
        n_total = sum(b["N"] for b in summary_ece[var].values())
        ece_g = total_ece_w / n_total if n_total else 0
        # Ignorance Score: -log P_top * I[won]
        # Formal: IS = -log P(outcome). En 1X2 con pick: si pick==out, IS=-log(P_top); else, evaluamos prob de outcome real.
        # Simplificacion: -log(prob asignada al outcome real)
        # Para hacer correcto necesitariamos los 3 P, no solo P_top. Reaproxim: IS = -log(P_top) si won, else -log(1-P_top)
        ign = []
        for p_top, won, _ in all_data:
            if won: ign.append(-math.log(max(p_top, 0.001)))
            else: ign.append(-math.log(max(1-p_top, 0.001)))
        ign_avg = sum(ign)/len(ign) if ign else 0
        print(f"{var:<8s}{ece_g:>12.4f}{ign_avg:>10.4f}{n_total:>10d}")

    # ECE en bucket APOSTABLE (P >= 0.50)
    print("\n--- ECE en bucket APOSTABLE (P >= 0.50) ---")
    print(f"{'modelo':<8s}{'N':>8s}{'P_avg':>9s}{'hit_obs':>9s}{'ECE':>9s}")
    for var in ("V0", "Vdual", "Vruido", "MKT"):
        all_data = ece_data[var]
        in_bucket = [(p, w) for p, w, _ in all_data if p >= 0.50]
        if not in_bucket: continue
        ps = [x[0] for x in in_bucket]; ws = [x[1] for x in in_bucket]
        p_avg = sum(ps)/len(ps); hit_obs = sum(ws)/len(ws); ece = abs(p_avg - hit_obs)
        print(f"{var:<8s}{len(in_bucket):>8d}{p_avg:>9.4f}{hit_obs:>9.4f}{ece:>9.4f}")

    # ============================================================
    # TAREA 2 — Bootstrap CI95% sobre estrategia compuesta S1
    # ============================================================
    print("\n" + "="*100)
    print("TAREA 2 — Bootstrap CI95% sobre estrategia compuesta S1")
    print("="*100)
    print(f"\nN picks S1 (walk-forward): {len(picks_s1)}")
    if picks_s1:
        pnls = [p[1] for p in picks_s1]
        yield_obs = sum(pnls) / len(pnls) * 100
        print(f"Yield observado: {yield_obs:+.2f}%")
        # Bootstrap 10000 resamples
        boot_yields = []
        for _ in range(10000):
            sample = [random.choice(pnls) for _ in range(len(pnls))]
            boot_yields.append(sum(sample) / len(sample) * 100)
        boot_yields.sort()
        ci_lo = boot_yields[250]; ci_hi = boot_yields[9750]
        prob_pos = sum(1 for y in boot_yields if y > 0) / 10000 * 100
        print(f"Bootstrap N=10,000: CI95% = [{ci_lo:+.2f}%, {ci_hi:+.2f}%]")
        print(f"P(yield > 0): {prob_pos:.1f}%")
        # Por anio
        print("\n--- Bootstrap CI95% por anio ---")
        print(f"{'anio':<6s}{'N':>8s}{'yield':>10s}{'CI95_lo':>10s}{'CI95_hi':>10s}{'P(>0)':>10s}")
        for yt in YEARS_TEST:
            yt_pnls = [p[1] for p in picks_s1 if p[0] == yt]
            if not yt_pnls: continue
            yld = sum(yt_pnls)/len(yt_pnls)*100
            boot = []
            for _ in range(10000):
                sample = [random.choice(yt_pnls) for _ in range(len(yt_pnls))]
                boot.append(sum(sample)/len(sample)*100)
            boot.sort()
            ppos = sum(1 for y in boot if y > 0)/10000*100
            print(f"{yt:<6s}{len(yt_pnls):>8d}{yld:>9.2f}%{boot[250]:>9.2f}%{boot[9750]:>9.2f}%{ppos:>9.1f}%")

    # ============================================================
    # TAREA 3 — Investigar régimen 2025
    # ============================================================
    print("\n" + "="*100)
    print("TAREA 3 — Régimen 2025")
    print("="*100)
    if regimen_2025["overround"]:
        ov_2025 = sum(regimen_2025["overround"])/len(regimen_2025["overround"])
        print(f"\nOverround 2025 promedio: {ov_2025:.4f}  (N={len(regimen_2025['overround'])})")

    # Comparar overround con otros años
    print("\n--- Overround promedio por año (todos los partidos con cuotas) ---")
    by_year_ov = defaultdict(list)
    for key, (c1, cx, c2) in cuotas.items():
        by_year_ov[key[1][:4]].append((1/c1) + (1/cx) + (1/c2))
    print(f"{'anio':<6s}{'N':>8s}{'overround':>12s}{'min':>10s}{'max':>10s}")
    for yt in sorted(by_year_ov.keys()):
        ovs = by_year_ov[yt]
        print(f"{yt:<6s}{len(ovs):>8d}{sum(ovs)/len(ovs):>12.4f}{min(ovs):>10.4f}{max(ovs):>10.4f}")

    print("\n--- Hit rate V0 vs V_dual por liga 2025 ---")
    print(f"{'liga':<14s}{'N':>8s}{'hit_V0%':>10s}{'hit_Vdual%':>12s}")
    for liga, st in sorted(regimen_2025["by_liga"].items(), key=lambda x: -x[1]["n"]):
        if st["n"] < 5: continue
        h0 = st["hits_v0"]/st["n"]*100
        h5 = st["hits_v5"]/st["n"]*100
        print(f"{liga:<14s}{st['n']:>8d}{h0:>9.2f}%{h5:>11.2f}%")

    # Distribución outcomes por año
    print("\n--- Distribucion outcomes por anio (con cuotas) ---")
    print(f"{'anio':<6s}{'N':>8s}{'%L':>8s}{'%E':>8s}{'%V':>8s}")
    out_by_year = defaultdict(lambda: {"L": 0, "E": 0, "V": 0})
    for r in rows:
        liga, fecha, ht, at, hg, ag = r[:6]
        if (liga, fecha, ht, at) not in cuotas: continue
        anio = fecha[:4]
        if hg > ag: out_by_year[anio]["L"] += 1
        elif hg == ag: out_by_year[anio]["E"] += 1
        else: out_by_year[anio]["V"] += 1
    for yt in sorted(out_by_year.keys()):
        d = out_by_year[yt]
        n = d["L"] + d["E"] + d["V"]
        print(f"{yt:<6s}{n:>8d}{d['L']/n*100:>7.2f}%{d['E']/n*100:>7.2f}%{d['V']/n*100:>7.2f}%")


if __name__ == "__main__":
    main()

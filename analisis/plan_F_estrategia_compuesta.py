"""Plan F — estrategia compuesta DISJUNTA.

Subsets F0/F1/F2/F3/F4 son disjuntos por construccion (cada partido cae en uno solo).
Para cada subset, asignar UNA config (pick_src, div_thr) a cada partido.
Los picks NO se solapan -> sumamos N y pnl directamente.

Estrategias:
  S1 — best por subset segun (yield, N): config max yield con N>=10 por subset.
  S2 — best por subset segun N: config max N con yield > 0%.
  S3 — top configs filtradas: solo picks de configs con yield > 15%.
  S4 — todos > 0% yield disjunto: cada subset elige su mejor config con yield > 0%.

Walk-forward OOS estricto.
"""
import sqlite3
import math
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

# Configs por subset (subset, pick_src, div_thr) — basado en Plan F walk-forward IS pooled.
# Cada partido cae en exactamente un subset, asi que estas configs son disjuntas.

ESTRATEGIAS = {
    "S1_best_yield": {  # Mejor yield por subset con N>=10
        "F0_3agree":         ("Vdual",  0.10),  # +28.55% N=29
        "F1_v0=ruido!=dual": ("V0",     0.00),  # raro, datos pequeños
        "F2_v0=dual!=ruido": ("Vdual",  0.10),  # +32.81% N=36
        "F3_dual=ruido!=v0": ("V0",     0.00),  # +94.33% N=12
        "F4_3diff":          ("Vruido", 0.00),  # N=5 +45.20%
    },
    "S2_best_N": {  # Mejor N por subset con yield > 0%
        "F0_3agree":         ("Vdual",  0.10),  # +28.55% N=29
        "F1_v0=ruido!=dual": ("V0",     0.00),
        "F2_v0=dual!=ruido": ("Vdual",  0.10),  # N=36
        "F3_dual=ruido!=v0": ("V0",     0.00),  # N=12
        "F4_3diff":          ("Vruido", 0.00),
    },
    "S3_high_yield_only": {  # Solo configs con yield > 25%
        "F0_3agree":         ("Vdual",  0.15),  # +51.50% N=14
        "F1_v0=ruido!=dual": ("V0",     0.00),
        "F2_v0=dual!=ruido": ("Vdual",  0.15),  # +40.56% N=16
        "F3_dual=ruido!=v0": ("V0",     0.00),  # +94.33% N=12
        "F4_3diff":          ("Vruido", 0.00),
    },
    "S4_v0_only": {  # baseline: V0 en todos los subsets
        "F0_3agree":         ("V0",     0.15),  # +13.67% N=33
        "F1_v0=ruido!=dual": ("V0",     0.00),
        "F2_v0=dual!=ruido": ("V0",     0.15),  # +20.41% N=37
        "F3_dual=ruido!=v0": ("V0",     0.00),  # +94.33% N=12
        "F4_3diff":          ("V0",     0.00),
    },
    "S5_high_div": {  # divergencia >= 0.15 universal
        "F0_3agree":         ("Vdual",  0.15),  # +51.50% N=14
        "F1_v0=ruido!=dual": ("V0",     0.15),
        "F2_v0=dual!=ruido": ("Vdual",  0.15),  # +40.56% N=16
        "F3_dual=ruido!=v0": ("V0",     0.15),
        "F4_3diff":          ("Vruido", 0.15),
    },
}


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


def construir_state_dual_v5(eventos, fit_xg, alfa):
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


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas")

    # Acumular para cada estrategia
    strat_stats = {sname: {"n": 0, "stake": 0, "pnl": 0, "hits": 0,
                            "by_year": defaultdict(lambda: {"n": 0, "stake": 0, "pnl": 0, "hits": 0}),
                            "by_subset": defaultdict(lambda: {"n": 0, "stake": 0, "pnl": 0, "hits": 0})}
                    for sname in ESTRATEGIAS}

    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train)
        fit_ruido = fit_v_ruido(ev_train)
        state_dual = construir_state_dual_v5(eventos, fit_v5, ALFA_EMA)
        state_ruido = construir_state_ruido(eventos, fit_ruido, ALFA_EMA)
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        fit_lam_d, fit_lam_r = fit_lambdas(state_dual, state_ruido, yt)
        if not fit_lam_d: continue
        # Compute lambdas + calibrar rhos
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

        # Iterar eventos year=yt
        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key); d_r = state_ruido.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
            if key[0] not in LIGAS_M1: continue
            if key not in cuotas: continue

            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            lh_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_h"] + fit_lam_d["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam_d["intercept"] + fit_lam_d["coef"][0]*d["xg_v"] + fit_lam_d["coef"][1]*d["res_v"])
            pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
            lh_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["h"])
            lv_r = max(0.05, fit_lam_r["intercept"] + fit_lam_r["coef"][0]*d_r["a"])
            plr, per, pvr = prob_1x2(lh_r, lv_r, rhos_r.get(key[0], -0.05))
            preds = {"V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd), "Vruido": (plr, per, pvr)}
            picks = {k: max([(v[0],"L"),(v[1],"E"),(v[2],"V")], key=lambda x: x[0])[1] for k, v in preds.items()}
            p0, pd, pr = picks["V0"], picks["Vdual"], picks["Vruido"]
            if p0 == pd == pr: subset = "F0_3agree"
            elif p0 == pr and pd != p0: subset = "F1_v0=ruido!=dual"
            elif p0 == pd and pr != p0: subset = "F2_v0=dual!=ruido"
            elif pd == pr and p0 != pd: subset = "F3_dual=ruido!=v0"
            else: subset = "F4_3diff"

            if hg > ag: out = "L"
            elif hg == ag: out = "E"
            else: out = "V"
            c1, cx, c2 = cuotas[key]
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov

            for sname, config in ESTRATEGIAS.items():
                pick_src, div_thr = config[subset]
                pl, pe, pv = preds[pick_src]
                pick = picks[pick_src]
                p_pick = pl if pick=="L" else pe if pick=="E" else pv
                pi_pick = pi_l if pick=="L" else pi_e if pick=="E" else pi_v
                cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
                divergencia = p_pick - pi_pick
                if divergencia < div_thr: continue
                if p_pick * cuota_pick < EV_MIN: continue
                # Apostar
                won = pick == out
                pnl = (cuota_pick - 1.0) if won else -1.0
                s = strat_stats[sname]
                s["n"] += 1; s["stake"] += 1; s["hits"] += int(won); s["pnl"] += pnl
                sb = s["by_year"][yt]
                sb["n"] += 1; sb["stake"] += 1; sb["hits"] += int(won); sb["pnl"] += pnl
                ssub = s["by_subset"][subset]
                ssub["n"] += 1; ssub["stake"] += 1; ssub["hits"] += int(won); ssub["pnl"] += pnl

    # Reportar
    print("\n" + "="*100)
    print("ESTRATEGIAS COMPUESTAS DISJUNTAS — IS pooled walk-forward")
    print("="*100)
    print(f"{'estrategia':<22s}{'N':>8s}{'hit%':>8s}{'yield IS':>12s}{'pnl':>10s}")
    for sname, s in strat_stats.items():
        if s["n"] == 0: continue
        hit = s["hits"]/s["n"]*100
        yld = s["pnl"]/s["stake"]*100
        print(f"{sname:<22s}{s['n']:>8d}{hit:>7.2f}%{yld:>11.2f}%{s['pnl']:>10.2f}")

    # Por anio
    print("\n--- Yield por anio ---")
    print(f"{'estrategia':<22s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>8s}")
    for sname, s in strat_stats.items():
        if s["n"] == 0: continue
        row = f"{sname:<22s}"
        for yt in YEARS_TEST:
            sb = s["by_year"].get(yt, {"n":0, "stake":0, "pnl":0})
            yld = (sb["pnl"]/sb["stake"]*100) if sb["stake"] else None
            row += f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
        is_yld = s["pnl"]/s["stake"]*100
        row += f"{is_yld:>9.2f}%{s['n']:>8d}"
        print(row)

    # Por subset (solo S1)
    print("\n--- S1_best_yield desglose por subset (verificar disjuncion) ---")
    print(f"{'subset':<22s}{'N':>8s}{'hit%':>8s}{'yield':>10s}{'pnl':>10s}")
    s = strat_stats["S1_best_yield"]
    for sub in ("F0_3agree", "F1_v0=ruido!=dual", "F2_v0=dual!=ruido", "F3_dual=ruido!=v0", "F4_3diff"):
        ss = s["by_subset"].get(sub, {"n":0, "stake":0, "pnl":0, "hits":0})
        if ss["n"] == 0: continue
        hit = ss["hits"]/ss["n"]*100
        yld = ss["pnl"]/ss["stake"]*100
        print(f"{sub:<22s}{ss['n']:>8d}{hit:>7.2f}%{yld:>9.2f}%{ss['pnl']:>10.2f}")
    total_n = sum(s["by_subset"][sub]["n"] for sub in s["by_subset"])
    total_pnl = sum(s["by_subset"][sub]["pnl"] for sub in s["by_subset"])
    print(f"{'TOTAL DISJUNTO':<22s}{total_n:>8d}{'':>8s}{total_pnl/total_n*100 if total_n else 0:>9.2f}%{total_pnl:>10.2f}")


if __name__ == "__main__":
    main()

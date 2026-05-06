"""
Plan F — triple medidor (V0 motor + V_dual + V_ruido) -> ensamble high-yield.

V_ruido: predictor sobre features que NNLS shrinkó a 0 (stats "no significativas"
que sin embargo V0 captura via su mezcla 0.70/0.30 con goles).

Features V_ruido: shots_off, corners, possession, saves_rival, blocks_rival,
longballs_acc, pass_pct. NO incluye SOT (que ya esta en V_dual).

Ridge UNCONSTRAINED (allow neg coefs) — el ruido puede tener signos negativos
(ej. blocks rival defensivos).

Triple medidor: tres picks por partido.
  Subsets:
    F0 — todos acuerdan (3-acuerdo)
    F1 — V0 == V_ruido != V_dual (V_dual divergente)
    F2 — V0 == V_dual != V_ruido (V_ruido divergente)
    F3 — V_dual == V_ruido != V0 (V0 divergente)
    F4 — los 3 difieren (V0, V_dual, V_ruido)
    F5 — modelos vs mercado: pick_modelos_consenso != pick_mercado

Yield por subset + grid divergencia con mercado.
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
DIV_THRS = [0.00, 0.05, 0.10, 0.15]


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
         h_pos, a_pos, h_pp, a_pp, h_sv, a_sv, h_bl, a_bl, h_lba, a_lba) = r
        eventos.append({"liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
                        "goles": hg, "goles_rival": ag, "sot": hst, "shots_off": max(0, hs - hst),
                        "corners": hc, "pos": h_pos or 50, "pass_pct": h_pp or 0,
                        "saves_rival": a_sv or 0, "blocks_rival": a_bl or 0,
                        "longballs_acc": h_lba or 0})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast),
                        "corners": ac, "pos": a_pos or 50, "pass_pct": a_pp or 0,
                        "saves_rival": h_sv or 0, "blocks_rival": h_bl or 0,
                        "longballs_acc": a_lba or 0})
    return eventos


def fit_v5_xg(eventos_train):
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def fit_v_ruido(eventos_train):
    """V_ruido: features sin SOT, Ridge unconstrained."""
    feats = ["shots_off", "corners", "pos", "pass_pct", "saves_rival", "blocks_rival", "longballs_acc"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, fit_intercept=True).fit(X, y)
    r2 = float(m.score(X, y))
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_), "R2": r2}


def calc_xg(ev, fit):
    return fit["intercept"] + sum(fit["coef"][i] * ev[fit["feats"][i]] for i in range(len(fit["feats"])))


def construir_emas_canal(eventos, fit_xg, alfa, residuo=False):
    """EMA dual home/away por equipo. Si residuo=True devuelve EMA(goles - xg_calc),
    else EMA(xg_calc)."""
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
        xl = calc_xg(ev_l, fit_xg)
        xv = calc_xg(ev_v, fit_xg)
        if residuo:
            v_l = ev_l["goles"] - xl
            v_v = ev_v["goles"] - xv
        else:
            v_l, v_v = xl, xv
        sh["h"] = v_l if sh["h"] is None else alfa*v_l + (1-alfa)*sh["h"]
        sh["n_h"] += 1
        sa["a"] = v_v if sa["a"] is None else alfa*v_v + (1-alfa)*sa["a"]
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


def fit_lambda_dual(emas_xg, emas_res):
    """Ridge: target = goles_partido. Features [ema_xg, ema_residuo]."""
    rows_h, rows_v, y_h, y_v = [], [], [], []
    for key, d_xg in emas_xg.items():
        if d_xg["n_h"] < WARMUP or d_xg["n_a"] < WARMUP: continue
        if key[1][:4] >= "2026": continue
        d_res = emas_res.get(key)
        if not d_res: continue
        # Necesito hg, ag — los recargo por ev en main outer
        # Aqui asumo que se pasaran junto.
        pass
    return None  # implementacion abajo con eventos directly


def construir_emas_dual_v5(eventos, fit_xg_v5, alfa):
    """EMA dual con xg_v5 + residuo en single dict."""
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
        xl = calc_xg(ev_l, fit_xg_v5)
        xv = calc_xg(ev_v, fit_xg_v5)
        rl = ev_l["goles"] - xl
        rv = ev_v["goles"] - xv
        sh["xg_h"] = xl if sh["xg_h"] is None else alfa*xl + (1-alfa)*sh["xg_h"]
        sh["res_h"] = rl if sh["res_h"] is None else alfa*rl + (1-alfa)*sh["res_h"]
        sh["n_h"] += 1
        sa["xg_a"] = xv if sa["xg_a"] is None else alfa*xv + (1-alfa)*sa["xg_a"]
        sa["res_a"] = rv if sa["res_a"] is None else alfa*rv + (1-alfa)*sa["res_a"]
        sa["n_a"] += 1
    return out


def fit_lambda_from_emas(emas, year_max, feature_keys_h, feature_keys_v, target_h, target_v):
    rows = []; y = []
    for key, d in emas.items():
        if d.get("n_h", 0) < WARMUP or d.get("n_v", d.get("n_a", 0)) < WARMUP: continue
        if d.get("fecha", key[1])[:4] >= year_max: continue
        # Local row
        try:
            row_h = [d[k] for k in feature_keys_h]
            row_v = [d[k] for k in feature_keys_v]
            if any(v is None for v in row_h + row_v): continue
            rows.append(row_h); y.append(d[target_h])
            rows.append(row_v); y.append(d[target_v])
        except KeyError:
            continue
    if not rows: return None
    X = np.array(rows, dtype=float); y = np.array(y, dtype=float)
    m = Ridge(alpha=1.0, fit_intercept=True).fit(X, y)
    return {"intercept": float(m.intercept_), "coef": m.coef_.tolist()}


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


def calibrar_rho(pairs):
    grid = [round(-0.2 + 0.005*i, 3) for i in range(81)]
    by_liga = defaultdict(list)
    for liga, lh, lv, hg, ag in pairs:
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

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit_v5 = fit_v5_xg(eventos_train)
    fit_ruido = fit_v_ruido(eventos_train)
    print(f"\nV_ruido fit (sin SOT, Ridge unconstrained):")
    print(f"  intercept={fit_ruido['intercept']:.4f}  R2={fit_ruido['R2']:.4f}")
    for f, c in zip(fit_ruido["feats"], fit_ruido["coef"]):
        print(f"    {f:<18s} = {c:+.4f}")

    # Construir EMAs
    emas_v5_dual = construir_emas_dual_v5(eventos, fit_v5, ALFA_EMA)
    emas_ruido = construir_emas_canal(eventos, fit_ruido, ALFA_EMA, residuo=False)
    emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)

    # Fit lambda V_dual y V_ruido
    rows_d_h, rows_d_v, y_d_h, y_d_v = [], [], [], []
    rows_r_h, rows_r_v, y_r_h, y_r_v = [], [], [], []
    for key, d in emas_v5_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= "2026": continue
        d_r = emas_ruido.get(key)
        if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
        rows_d_h.append([d["xg_h"], d["res_h"]]); y_d_h.append(d["hg"])
        rows_d_v.append([d["xg_v"], d["res_v"]]); y_d_v.append(d["ag"])
        rows_r_h.append([d_r["h"]]); y_r_h.append(d["hg"])
        rows_r_v.append([d_r["a"]]); y_r_v.append(d["ag"])
    X_d = np.array(rows_d_h + rows_d_v); y_d = np.array(y_d_h + y_d_v)
    X_r = np.array(rows_r_h + rows_r_v); y_r = np.array(y_r_h + y_r_v)
    m_d = Ridge(alpha=1.0, fit_intercept=True).fit(X_d, y_d)
    m_r = Ridge(alpha=1.0, fit_intercept=True).fit(X_r, y_r)
    print(f"\nV_dual lambda fit: intercept={m_d.intercept_:.4f}  c=[{m_d.coef_[0]:.4f}, {m_d.coef_[1]:.4f}]")
    print(f"V_ruido lambda fit: intercept={m_r.intercept_:.4f}  c=[{m_r.coef_[0]:.4f}]")

    def lam_dual(d): return max(0.05, m_d.intercept_ + m_d.coef_[0]*d["xg_h"] + m_d.coef_[1]*d["res_h"]), \
                            max(0.05, m_d.intercept_ + m_d.coef_[0]*d["xg_v"] + m_d.coef_[1]*d["res_v"])
    def lam_ruido(d_r): return max(0.05, m_r.intercept_ + m_r.coef_[0]*d_r["h"]), \
                              max(0.05, m_r.intercept_ + m_r.coef_[0]*d_r["a"])

    # Calibrar rho per liga para los 3 modelos
    pairs_v0 = [(k[0], v[0], v[1], v[2], v[3]) for k, v in emas_v0.items()
                if v[0] is not None and v[1] is not None]
    pairs_d = []; pairs_r = []
    for key, d in emas_v5_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        d_r = emas_ruido.get(key)
        if not d_r or d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
        lh, lv = lam_dual(d)
        pairs_d.append((d["liga"], lh, lv, d["hg"], d["ag"]))
        lh_r, lv_r = lam_ruido(d_r)
        pairs_r.append((d["liga"], lh_r, lv_r, d["hg"], d["ag"]))
    rhos_v0 = calibrar_rho(pairs_v0)
    rhos_d = calibrar_rho(pairs_d)
    rhos_r = calibrar_rho(pairs_r)

    # Compute predicciones para los 3 modelos
    print("\n" + "="*120)
    print("PLAN F — Triple medidor (V0 + V_dual + V_ruido) sobre subset cuotas")
    print("="*120)
    preds = {}
    for key, val in emas_v0.items():
        lh, lv, hg, ag = val
        if lh is None or lv is None: continue
        d = emas_v5_dual.get(key)
        d_r = emas_ruido.get(key)
        if not d or not d_r: continue
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d_r["n_h"] < WARMUP or d_r["n_a"] < WARMUP: continue
        pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
        lh_d, lv_d = lam_dual(d)
        pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
        lh_r, lv_r = lam_ruido(d_r)
        plr, per, pvr = prob_1x2(lh_r, lv_r, rhos_r.get(key[0], -0.05))
        pick0 = max([(pl0,"L"),(pe0,"E"),(pv0,"V")], key=lambda x: x[0])[1]
        pickd = max([(pld,"L"),(ped,"E"),(pvd,"V")], key=lambda x: x[0])[1]
        pickr = max([(plr,"L"),(per,"E"),(pvr,"V")], key=lambda x: x[0])[1]
        preds[key] = {"V0": (pl0, pe0, pv0, pick0),
                      "Vdual": (pld, ped, pvd, pickd),
                      "Vruido": (plr, per, pvr, pickr),
                      "outcome": (hg, ag)}

    # Subsets ensemble
    subsets = {"F0_3agree": 0, "F1_v0=ruido_!=dual": 0, "F2_v0=dual_!=ruido": 0,
               "F3_dual=ruido_!=v0": 0, "F4_3diff": 0}
    for k, p in preds.items():
        p0, pd, pr = p["V0"][3], p["Vdual"][3], p["Vruido"][3]
        if p0 == pd == pr: subsets["F0_3agree"] += 1
        elif p0 == pr and pd != p0: subsets["F1_v0=ruido_!=dual"] += 1
        elif p0 == pd and pr != p0: subsets["F2_v0=dual_!=ruido"] += 1
        elif pd == pr and p0 != pd: subsets["F3_dual=ruido_!=v0"] += 1
        else: subsets["F4_3diff"] += 1
    print(f"\nDistribucion subsets (universo total preds={len(preds)}):")
    for s, n in subsets.items():
        print(f"  {s:<25s} {n:>6d}  ({n/len(preds)*100:.1f}%)")

    # Yield por subset (M.1 + EV>=1.03 + grid div)
    print("\n" + "="*120)
    print("YIELD POR SUBSET (M.1 + EV>=1.03 + grid divergencia con mercado)")
    print("="*120)
    print(f"{'subset':<22s}{'pick_src':<10s}{'div':<8s}{'N':>6s}{'hit%':>8s}{'yield%':>10s}{'pnl':>10s}")
    for subset_name in ["F0_3agree", "F1_v0=ruido_!=dual", "F2_v0=dual_!=ruido", "F3_dual=ruido_!=v0", "F4_3diff"]:
        # Pick source: para subsets con consenso, usar pick consensuado.
        # Para F4_3diff, probar V0 y V_dual y V_ruido por separado.
        if subset_name == "F4_3diff":
            pick_sources = ["V0", "Vdual", "Vruido"]
        else:
            pick_sources = ["V0", "Vdual", "Vruido"]  # tambien probar todos en consensuados
        for pick_src in pick_sources:
            for thr in DIV_THRS:
                apuestas = stake = pnl = hits = 0
                for key, p in preds.items():
                    liga = key[0]
                    if liga not in LIGAS_M1: continue
                    if key not in cuotas: continue
                    p0, pd, pr = p["V0"][3], p["Vdual"][3], p["Vruido"][3]
                    if subset_name == "F0_3agree" and not (p0 == pd == pr): continue
                    if subset_name == "F1_v0=ruido_!=dual" and not (p0 == pr and pd != p0): continue
                    if subset_name == "F2_v0=dual_!=ruido" and not (p0 == pd and pr != p0): continue
                    if subset_name == "F3_dual=ruido_!=v0" and not (pd == pr and p0 != pd): continue
                    if subset_name == "F4_3diff" and not (p0 != pd and pd != pr and p0 != pr): continue
                    pl, pe, pv, pick = p[pick_src]
                    hg, ag = p["outcome"]
                    if hg > ag: out = "L"
                    elif hg == ag: out = "E"
                    else: out = "V"
                    c1, cx, c2 = cuotas[key]
                    ov = (1/c1)+(1/cx)+(1/c2)
                    pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
                    pi_pick = pi_l if pick=="L" else pi_e if pick=="E" else pi_v
                    p_pick = pl if pick=="L" else pe if pick=="E" else pv
                    cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
                    divergencia = p_pick - pi_pick
                    if divergencia < thr: continue
                    if p_pick * cuota_pick < EV_MIN: continue
                    apuestas += 1; stake += 1; hits += int(pick == out)
                    pnl += (cuota_pick - 1.0) if pick == out else -1.0
                yld = (pnl/stake*100) if stake else None
                yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
                hit_str = f"{hits/apuestas*100:>7.2f}%" if apuestas else f"{'-':>8s}"
                if apuestas > 0:
                    print(f"{subset_name:<22s}{pick_src:<10s}{thr:<8.2f}{apuestas:>6d}{hit_str}{yld_str}{pnl:>10.2f}")
        print()


if __name__ == "__main__":
    main()

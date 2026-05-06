"""
Yield por bucket de divergencia (P_modelo_pick - P_implicita_pick).

Hipotesis: el yield se concentra en partidos donde el modelo difiere mas del
mercado. ¿Hay sweet spot de divergencia? ¿zona donde divergencia muy alta
significa modelo se equivoca?

Buckets divergencia: [-inf, 0), [0, 0.05), [0.05, 0.10), [0.10, 0.15), [0.15, 0.20),
[0.20, 0.25), [0.25, 0.30), [0.30+).

Compare V0 vs V5 vs V_dual.
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

BUCKETS = [(-1.0, 0.0), (0.0, 0.05), (0.05, 0.10), (0.10, 0.15),
           (0.15, 0.20), (0.20, 0.25), (0.25, 0.30), (0.30, 1.0)]


def get_beta_sot_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
    ).fetchall()}


def cargar_partidos(cur):
    return cur.execute(
        """
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_saves, a_saves
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL
          AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs IS NOT NULL AND as_v IS NOT NULL
          AND hc IS NOT NULL AND ac IS NOT NULL
          AND h_pos IS NOT NULL AND a_pos IS NOT NULL
          AND h_saves IS NOT NULL AND a_saves IS NOT NULL
        ORDER BY fecha
        """
    ).fetchall()


def cargar_cuotas(cur):
    out = {}
    for r in cur.execute(
        """
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f
          ON s.liga=f.liga AND s.fecha=f.fecha
         AND LOWER(REPLACE(REPLACE(REPLACE(s.ht,' ',''),'-',''),'.','')) = f.equipo_local_norm
         AND LOWER(REPLACE(REPLACE(REPLACE(s.at,' ',''),'-',''),'.','')) = f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
        """
    ).fetchall():
        out[(r[0], r[1], r[2], r[3])] = (r[4], r[5], r[6])
    return out


def construir_eventos(rows):
    eventos = []
    for r in rows:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac, hp, ap, hsv, asv2 = r
        eventos.append({"liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
                        "goles": hg, "goles_rival": ag, "sot": hst, "shots_off": max(0, hs - hst),
                        "corners": hc, "pos": hp or 50, "saves_rival": asv2 or 0})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast),
                        "corners": ac, "pos": ap or 50, "saves_rival": hsv or 0})
    return eventos


def fit_v5_xg(eventos_train):
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def calcular_xg_v5(ev, fit):
    feats = fit["feats"]
    return fit["intercept"] + sum(fit["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def construir_emas_dual(eventos, fit_v5, alfa):
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
        xl_p = calcular_xg_v5(ev_l, fit_v5)
        xv_p = calcular_xg_v5(ev_v, fit_v5)
        res_l = ev_l["goles"] - xl_p
        res_v = ev_v["goles"] - xv_p
        sh["xg_h"] = xl_p if sh["xg_h"] is None else alfa*xl_p + (1-alfa)*sh["xg_h"]
        sh["res_h"] = res_l if sh["res_h"] is None else alfa*res_l + (1-alfa)*sh["res_h"]
        sh["n_h"] += 1
        sa["xg_a"] = xv_p if sa["xg_a"] is None else alfa*xv_p + (1-alfa)*sa["xg_a"]
        sa["res_a"] = res_v if sa["res_a"] is None else alfa*res_v + (1-alfa)*sa["res_a"]
        sa["n_a"] += 1
    return out


def fit_lambda_dual(emas_dict):
    rows_h, rows_v = [], []
    y_h, y_v = [], []
    for key, d in emas_dict.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= "2026": continue
        rows_h.append([d["xg_h"], d["res_h"]]); y_h.append(d["hg"])
        rows_v.append([d["xg_v"], d["res_v"]]); y_v.append(d["ag"])
    X = np.array(rows_h + rows_v, dtype=float)
    y = np.array(y_h + y_v, dtype=float)
    m = Ridge(alpha=1.0, fit_intercept=True).fit(X, y)
    return {"intercept": float(m.intercept_), "coef": m.coef_.tolist()}


def predict_lambda_dual(d, fit):
    lh = fit["intercept"] + fit["coef"][0]*d["xg_h"] + fit["coef"][1]*d["res_h"]
    lv = fit["intercept"] + fit["coef"][0]*d["xg_v"] + fit["coef"][1]*d["res_v"]
    return max(0.05, lh), max(0.05, lv)


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
            p = poisson_pmf(h, lh) * poisson_pmf(a, lv) * dc_tau(h, a, lh, lv, rho)
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def calibrar_rho_pairs(pairs):
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


def evaluar_buckets(predicciones, cuotas, m1_only=False):
    """Para cada partido pasa filtros (M.1 si aplica + EV>=1.03 + tiene cuotas).
    Bucketiza por divergencia. Retorna stats por bucket."""
    buckets = {b: {"n": 0, "hits": 0, "stake": 0.0, "pnl": 0.0,
                   "by_year": defaultdict(lambda: {"n": 0, "stake": 0, "pnl": 0})}
               for b in BUCKETS}
    for key, (pl, pe, pv) in predicciones.items():
        liga, fecha, ht, at = key
        if m1_only and liga not in LIGAS_M1: continue
        if key not in cuotas: continue
        c1, cx, c2 = cuotas[key]
        ov = (1/c1) + (1/cx) + (1/c2)
        pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
        opciones = [(pl,"L",c1,pi_l), (pe,"E",cx,pi_e), (pv,"V",c2,pi_v)]
        opciones.sort(key=lambda x: -x[0])
        prob_top, pick, c_pick, pi_pick = opciones[0]
        divergencia = prob_top - pi_pick
        ev = prob_top * c_pick
        if ev < EV_MIN: continue
        # Determinar bucket
        bucket = None
        for lo, hi in BUCKETS:
            if lo <= divergencia < hi: bucket = (lo, hi); break
        if bucket is None: continue
        # Outcome
        # Necesito hg, ag — los recargo desde predicciones (los inserte como atributo)
        # En este path predicciones no tiene outcome. Cambiar: guardar outcome al lado.
        pass
    return buckets


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas(cur)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas")

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit_v5 = fit_v5_xg(eventos_train)
    emas_dual = construir_emas_dual(eventos, fit_v5, ALFA_EMA)
    fit_dual = fit_lambda_dual(emas_dual)
    emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)

    # Calibrar rho
    pairs_v0 = []; pairs_v5 = []; pairs_dual = []
    for key, val in emas_v0.items():
        lh, lv, hg, ag = val
        if lh is not None and lv is not None:
            pairs_v0.append((key[0], lh, lv, hg, ag))
    for key, d in emas_dual.items():
        if d["n_h"] >= WARMUP and d["n_v"] >= WARMUP:
            pairs_v5.append((d["liga"], d["xg_h"], d["xg_v"], d["hg"], d["ag"]))
            lh_d, lv_d = predict_lambda_dual(d, fit_dual)
            pairs_dual.append((d["liga"], lh_d, lv_d, d["hg"], d["ag"]))
    rhos_v0 = calibrar_rho_pairs(pairs_v0)
    rhos_v5 = calibrar_rho_pairs(pairs_v5)
    rhos_dual = calibrar_rho_pairs(pairs_dual)

    # Compute predicciones para cada modelo (P_L, P_E, P_V) + outcome real
    preds = defaultdict(dict)
    for key, val in emas_v0.items():
        lh, lv, hg, ag = val
        if lh is None or lv is None: continue
        pl, pe, pv = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
        preds[key]["V0"] = (pl, pe, pv)
        preds[key]["outcome"] = (hg, ag)
    for key, d in emas_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        pl5, pe5, pv5 = prob_1x2(d["xg_h"], d["xg_v"], rhos_v5.get(d["liga"], -0.05))
        lh_d, lv_d = predict_lambda_dual(d, fit_dual)
        pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_dual.get(d["liga"], -0.05))
        preds[key]["V5"] = (pl5, pe5, pv5)
        preds[key]["Vdual"] = (pld, ped, pvd)
        preds[key]["outcome"] = (d["hg"], d["ag"])

    # Bucketizar por divergencia
    print("\n" + "="*120)
    print("YIELD POR BUCKET DIVERGENCIA — universo ALL ligas (sin M.1) + EV>=1.03")
    print("="*120)
    print(f"{'modelo':<10s}{'div_bucket':<16s}{'N':>8s}{'hit%':>8s}{'yield%':>10s}{'pnl':>10s}{'avg_div':>10s}")
    for var in ("V0", "V5", "Vdual"):
        for lo, hi in BUCKETS:
            apuestas = stake = pnl = hits = 0
            divs_in = []
            for key, dpred in preds.items():
                if var not in dpred: continue
                if key not in cuotas: continue
                pl, pe, pv = dpred[var]
                hg, ag = dpred["outcome"]
                if hg > ag: out = "L"
                elif hg == ag: out = "E"
                else: out = "V"
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
                opciones = [(pl,"L",c1,pi_l), (pe,"E",cx,pi_e), (pv,"V",c2,pi_v)]
                opciones.sort(key=lambda x: -x[0])
                prob_top, pick, c_pick, pi_pick = opciones[0]
                divergencia = prob_top - pi_pick
                if not (lo <= divergencia < hi): continue
                ev = prob_top * c_pick
                if ev < EV_MIN: continue
                apuestas += 1; stake += 1; hits += int(pick == out)
                pnl += (c_pick - 1.0) if pick == out else -1.0
                divs_in.append(divergencia)
            yld = (pnl/stake*100) if stake else None
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            hit_str = f"{hits/apuestas*100:>7.2f}%" if apuestas else f"{'-':>8s}"
            avg = sum(divs_in)/len(divs_in) if divs_in else 0
            print(f"{var:<10s}[{lo:.2f},{hi:.2f}){'':<3s}{apuestas:>8d}{hit_str}{yld_str}{pnl:>10.2f}{avg:>10.4f}")
        print()

    print("\n" + "="*120)
    print("YIELD POR BUCKET DIVERGENCIA — solo M.1 ligas core + EV>=1.03")
    print("="*120)
    print(f"{'modelo':<10s}{'div_bucket':<16s}{'N':>8s}{'hit%':>8s}{'yield%':>10s}{'pnl':>10s}{'avg_div':>10s}")
    for var in ("V0", "V5", "Vdual"):
        for lo, hi in BUCKETS:
            apuestas = stake = pnl = hits = 0
            divs_in = []
            for key, dpred in preds.items():
                if var not in dpred: continue
                if key[0] not in LIGAS_M1: continue
                if key not in cuotas: continue
                pl, pe, pv = dpred[var]
                hg, ag = dpred["outcome"]
                if hg > ag: out = "L"
                elif hg == ag: out = "E"
                else: out = "V"
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
                opciones = [(pl,"L",c1,pi_l), (pe,"E",cx,pi_e), (pv,"V",c2,pi_v)]
                opciones.sort(key=lambda x: -x[0])
                prob_top, pick, c_pick, pi_pick = opciones[0]
                divergencia = prob_top - pi_pick
                if not (lo <= divergencia < hi): continue
                ev = prob_top * c_pick
                if ev < EV_MIN: continue
                apuestas += 1; stake += 1; hits += int(pick == out)
                pnl += (c_pick - 1.0) if pick == out else -1.0
                divs_in.append(divergencia)
            yld = (pnl/stake*100) if stake else None
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            hit_str = f"{hits/apuestas*100:>7.2f}%" if apuestas else f"{'-':>8s}"
            avg = sum(divs_in)/len(divs_in) if divs_in else 0
            print(f"{var:<10s}[{lo:.2f},{hi:.2f}){'':<3s}{apuestas:>8d}{hit_str}{yld_str}{pnl:>10.2f}{avg:>10.4f}")
        print()


if __name__ == "__main__":
    main()

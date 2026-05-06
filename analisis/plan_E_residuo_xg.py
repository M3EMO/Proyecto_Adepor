"""
Plan E — Feature engineering "ruido informativo" (xg + residuo dual).

Hipotesis: V0 retiene info incremental sobre goles directos (clutch finishing,
luck, talento, score effects) que V5 elimina al solo medir SOT. La info util para
yield esta en el residuo (goles_real - xg_v5) que se acumula cronologicamente.

Modelo:
  Para cada equipo, cada perspectiva (home/away):
    ema_xg_v5(equipo)     = EMA de xg_calc_v5(stats_partido)
    ema_residuo(equipo)   = EMA de (goles_propios - xg_calc_v5(stats_partido))

  Lambda predicho via Ridge multivariable:
    lambda = c0 + c1*ema_xg + c2*ema_residuo

  Coefs (c0, c1, c2) fitted con Ridge sobre target = goles_partido en eventos pre-2026.

Compare contra:
  V5 (lambda = ema_xg_v5 puro, sin residuo)
  V0 (motor actual)
  V_dual (con residuo)

Metricas:
  Brier 1X2 + hit rate + RMSE goles + yield (con divergencia + EV).
"""
import sqlite3
import json
import math
from collections import defaultdict
from itertools import groupby
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


def fit_v5_xg_calc(eventos_train):
    """Fit Ridge para xg_calc(stats) — coefs intercepto+SOT."""
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def calcular_xg_v5(ev, fit):
    feats = fit["feats"]
    return fit["intercept"] + sum(fit["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def construir_emas_dual(eventos, fit_v5, alfa):
    """Construye 4 EMAs por equipo separadas home/away:
      ema_xg_favor (favor cuando juega como home/away)
      ema_residuo_favor (overperformance: goles - xg_v5_partido)
    Tambien retorna lambda_h, lambda_v (xg puro v5) para compatibilidad.
    """
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    keys_ord = sorted(matches.keys(), key=lambda k: k[1])
    state = defaultdict(lambda: {
        "xg_h": None, "xg_a": None,
        "res_h": None, "res_a": None,
        "n_h": 0, "n_a": 0,
    })
    out = {}  # key -> dict con features pre-partido + outcome
    for key in keys_ord:
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]
        sh, sa = state[ht], state[at]
        # Features pre-partido (estado actual antes de incorporar este partido)
        out[key] = {
            "xg_h": sh["xg_h"], "res_h": sh["res_h"], "n_h": sh["n_h"],
            "xg_v": sa["xg_a"], "res_v": sa["res_a"], "n_v": sa["n_a"],
            "hg": ev_l["goles"], "ag": ev_l["goles_rival"],
            "fecha": key[1], "liga": key[0],
        }
        # Calcular xg_v5_partido para cada perspectiva
        xg_l_partido = calcular_xg_v5(ev_l, fit_v5)
        xg_v_partido = calcular_xg_v5(ev_v, fit_v5)
        # residuo = goles_real - xg_v5_partido
        res_l = ev_l["goles"] - xg_l_partido
        res_v = ev_v["goles"] - xg_v_partido
        # Update HOME EMAs (equipo como local)
        sh["xg_h"] = xg_l_partido if sh["xg_h"] is None else alfa * xg_l_partido + (1-alfa)*sh["xg_h"]
        sh["res_h"] = res_l if sh["res_h"] is None else alfa * res_l + (1-alfa)*sh["res_h"]
        sh["n_h"] += 1
        # Update AWAY EMAs (rival visitante)
        sa["xg_a"] = xg_v_partido if sa["xg_a"] is None else alfa * xg_v_partido + (1-alfa)*sa["xg_a"]
        sa["res_a"] = res_v if sa["res_a"] is None else alfa * res_v + (1-alfa)*sa["res_a"]
        sa["n_a"] += 1
    return out


def fit_lambda_dual(emas_dict):
    """Ridge: target=goles_partido (hg para local, ag para visita) sobre features
    [ema_xg, ema_residuo] del equipo. Fitea coefs para predict lambda."""
    rows_h = []; rows_v = []
    y_h = []; y_v = []
    for key, d in emas_dict.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        if d["fecha"][:4] >= "2026": continue  # train pre-2026
        rows_h.append([d["xg_h"], d["res_h"]])
        y_h.append(d["hg"])
        rows_v.append([d["xg_v"], d["res_v"]])
        y_v.append(d["ag"])
    # Pool home + away: lambda_predict como funcion de (ema_xg, ema_res) propios
    X = np.array(rows_h + rows_v, dtype=float)
    y = np.array(y_h + y_v, dtype=float)
    m = Ridge(alpha=1.0, fit_intercept=True).fit(X, y)
    return {"intercept": float(m.intercept_), "coef": m.coef_.tolist(),
            "N_train": len(y), "R2": float(m.score(X, y))}


def predict_lambda(d_pre, fit_dual):
    lam_h = fit_dual["intercept"] + fit_dual["coef"][0] * d_pre["xg_h"] + fit_dual["coef"][1] * d_pre["res_h"]
    lam_v = fit_dual["intercept"] + fit_dual["coef"][0] * d_pre["xg_v"] + fit_dual["coef"][1] * d_pre["res_v"]
    return max(0.05, lam_h), max(0.05, lam_v)


def construir_emas_v0(eventos, beta_sot_map, alfa, theta):
    """V0 standard EMA dual."""
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
        xl = beta * ev_l["sot"] + 0.010 * ev_l["shots_off"] + 0.03 * ev_l["corners"]
        xl = 0.70 * xl + 0.30 * ev_l["goles"]
        xv = beta * ev_v["sot"] + 0.010 * ev_v["shots_off"] + 0.03 * ev_v["corners"]
        xv = 0.70 * xv + 0.30 * ev_v["goles"]
        xlp = theta * xl + (1.0 - theta) * ev_l["goles"]
        xvp = theta * xv + (1.0 - theta) * ev_v["goles"]
        sh["fh"] = xlp if sh["fh"] is None else alfa * xlp + (1 - alfa) * sh["fh"]
        sh["nfh"] += 1
        sa["fa"] = xvp if sa["fa"] is None else alfa * xvp + (1 - alfa) * sa["fa"]
        sa["nfa"] += 1
    return out


def poisson_pmf(k, lam):
    if lam <= 0: lam = 0.01
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def dc_tau(h, a, lh, lv, rho):
    if h == 0 and a == 0: return 1 - lh * lv * rho
    if h == 0 and a == 1: return 1 + lh * rho
    if h == 1 and a == 0: return 1 + lv * rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0


def prob_1x2(lh, lv, rho):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lh) * poisson_pmf(a, lv) * dc_tau(h, a, lh, lv, rho)
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def calibrar_rho_pairs(pairs):
    grid = [round(-0.2 + 0.005 * i, 3) for i in range(81)]
    by_liga = defaultdict(list)
    for liga, lh, lv, hg, ag in pairs:
        if lh > 0 and lv > 0: by_liga[liga].append((lh, lv, hg, ag))
    rhos = {}
    for liga, ps in by_liga.items():
        if len(ps) < 50:
            rhos[liga] = -0.05; continue
        best, ll_best = -0.05, -math.inf
        for rho in grid:
            ll = 0.0
            for lh, lv, hg, ag in ps:
                p = poisson_pmf(hg, lh) * poisson_pmf(ag, lv) * dc_tau(hg, ag, lh, lv, rho)
                if p > 0: ll += math.log(p)
                else: ll = -math.inf; break
            if ll > ll_best: ll_best, best = ll, rho
        rhos[liga] = best
    return rhos


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas(cur)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} con cuotas matched")

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit_v5_xg = fit_v5_xg_calc(eventos_train)
    print(f"V5 xg_calc fit: intercept={fit_v5_xg['intercept']:.4f}  beta_SOT={fit_v5_xg['coef'][0]:.4f}")

    # Construir EMAs duales V5 (xg + residuo)
    print("\nConstruyendo EMAs duales (xg + residuo)...")
    emas_dual = construir_emas_dual(eventos, fit_v5_xg, ALFA_EMA)

    # Fit lambda predictor con [ema_xg, ema_residuo]
    fit_dual = fit_lambda_dual(emas_dual)
    print(f"V_dual fit: intercept={fit_dual['intercept']:.4f}  c_xg={fit_dual['coef'][0]:.4f}  c_residuo={fit_dual['coef'][1]:.4f}")
    print(f"  R2 train={fit_dual['R2']:.4f}  N={fit_dual['N_train']}")

    # Tambien construir V5 puro (sin residuo) para comparar — usar V5 lambda = ema_xg solo
    # Y V0 standard
    emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)

    # Calibrar rho per liga
    print("\nCalibrando rho per liga...")
    pairs_v0 = []
    pairs_v5 = []
    pairs_dual = []
    for key, val in emas_v0.items():
        lh, lv, hg, ag = val
        if lh is not None and lv is not None:
            pairs_v0.append((key[0], lh, lv, hg, ag))
    for key, d in emas_dual.items():
        if d["n_h"] >= WARMUP and d["n_v"] >= WARMUP:
            # V5 puro: lambda = ema_xg
            lh_v5 = d["xg_h"]; lv_v5 = d["xg_v"]
            pairs_v5.append((d["liga"], lh_v5, lv_v5, d["hg"], d["ag"]))
            # V_dual: lambda predicho con (xg + residuo)
            lh_d, lv_d = predict_lambda(d, fit_dual)
            pairs_dual.append((d["liga"], lh_d, lv_d, d["hg"], d["ag"]))
    rhos_v0 = calibrar_rho_pairs(pairs_v0)
    rhos_v5 = calibrar_rho_pairs(pairs_v5)
    rhos_dual = calibrar_rho_pairs(pairs_dual)

    # Evaluar Brier 1X2 + yield para los 3 modelos
    print("\n" + "="*100)
    print("EVALUACION — V0 vs V5_puro vs V_dual (xg+residuo)")
    print("="*100)

    # Compute predicciones para los 3 modelos
    preds = defaultdict(dict)  # [(liga,fecha,ht,at)] -> {var: (pl,pe,pv,lh,lv)}
    for key, d in emas_dual.items():
        if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
        liga = d["liga"]
        # V5 puro
        lh_v5, lv_v5 = d["xg_h"], d["xg_v"]
        pl_v5, pe_v5, pv_v5 = prob_1x2(lh_v5, lv_v5, rhos_v5.get(liga, -0.05))
        # V_dual
        lh_d, lv_d = predict_lambda(d, fit_dual)
        pl_d, pe_d, pv_d = prob_1x2(lh_d, lv_d, rhos_dual.get(liga, -0.05))
        preds[key]["V5"] = (pl_v5, pe_v5, pv_v5, lh_v5, lv_v5)
        preds[key]["Vdual"] = (pl_d, pe_d, pv_d, lh_d, lv_d)
        preds[key]["hg"] = d["hg"]
        preds[key]["ag"] = d["ag"]
    for key, val in emas_v0.items():
        if key in preds:
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            pl, pe, pv = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            preds[key]["V0"] = (pl, pe, pv, lh, lv)

    # Brier + hit + RMSE goles
    print("\n--- Brier 1X2 IS, Hit IS, RMSE goles totales IS ---")
    print(f"{'modelo':<12s}{'N':>6s}{'Brier':>10s}{'hit%':>8s}{'RMSE_total':>12s}")
    for var in ("V0", "V5", "Vdual"):
        bs, hits, e_sq = [], [], []
        for key, dpred in preds.items():
            if var not in dpred: continue
            pl, pe, pv, lh, lv = dpred[var]
            hg, ag = dpred["hg"], dpred["ag"]
            if hg > ag: out = "L"
            elif hg == ag: out = "E"
            else: out = "V"
            target = (1 if out=="L" else 0, 1 if out=="E" else 0, 1 if out=="V" else 0)
            b = (pl - target[0])**2 + (pe - target[1])**2 + (pv - target[2])**2
            bs.append(b)
            pick = max([(pl,"L"),(pe,"E"),(pv,"V")], key=lambda x: x[0])[1]
            hits.append(int(pick == out))
            e_sq.append((lh + lv - (hg + ag))**2)
        if bs:
            print(f"{var:<12s}{len(bs):>6d}{sum(bs)/len(bs):>10.4f}{sum(hits)/len(hits)*100:>7.2f}%{math.sqrt(sum(e_sq)/len(e_sq)):>12.4f}")

    # Yield grid divergencia (sobre subset cuotas + M.1)
    print("\n--- Yield IS, grid divergencia (M.1 + EV>=1.03) ---")
    print(f"{'modelo':<12s}{'div_thr':<10s}{'N':>6s}{'hit%':>8s}{'yield%':>10s}{'pnl':>10s}")
    for var in ("V0", "V5", "Vdual"):
        for thr in DIV_THRS:
            apuestas, stake, pnl, hits = 0, 0.0, 0.0, 0
            for key, dpred in preds.items():
                if var not in dpred: continue
                liga, fecha, ht, at = key
                if liga not in LIGAS_M1: continue
                if key not in cuotas: continue
                pl, pe, pv, lh, lv = dpred[var]
                hg, ag = dpred["hg"], dpred["ag"]
                if hg > ag: out = "L"
                elif hg == ag: out = "E"
                else: out = "V"
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
                opciones = [(pl,"L",c1,pi_l),(pe,"E",cx,pi_e),(pv,"V",c2,pi_v)]
                opciones.sort(key=lambda x: -x[0])
                prob_top, pick, c_pick, pi_pick = opciones[0]
                divergencia = prob_top - pi_pick
                if divergencia < thr: continue
                ev = prob_top * c_pick
                if ev < EV_MIN: continue
                apuestas += 1; stake += 1; hits += int(pick == out)
                pnl += (c_pick - 1.0) if pick == out else -1.0
            yld = (pnl/stake*100) if stake else None
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            hit_str = f"{hits/apuestas*100:>7.2f}%" if apuestas else f"{'-':>8s}"
            print(f"{var:<12s}{thr:<10.2f}{apuestas:>6d}{hit_str}{yld_str}{pnl:>10.2f}")
        print()


if __name__ == "__main__":
    main()

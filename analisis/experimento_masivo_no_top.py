"""Experimento masivo: maximizar yield en ligas no-top + combinaciones de motores.

Modelos:
  V0      Motor actual
  Vdual   xg_v5 + residuo
  MKT     Mercado puro
  Vanc05  Anchor a mercado alpha=0.5  (TOP 3 optimizador)
  Vanc07  Anchor alpha=0.7
  Vamp    Amplificador divergencia: P_apuesta = P_modelo + 0.5*(P_modelo - P_mercado)

Walk-forward OOS estricto por year_test.

Slices:
  - Universo total
  - Por liga
  - Por bin4 (Q1-Q4 calendario individual)
  - Categoria: TOP (ENG/ESP/ITA/FRA/ALE) vs NO_TOP (resto)
  - Por anio

Metricas:
  Brier, Hit, Sharpness (std P_top), N apostable, Yield (con grid div), Rango cuotas.
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
DIV_THRS = [0.00, 0.05, 0.10, 0.15, 0.20]
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


def normalize_3(p1, p2, p3):
    s = p1+p2+p3
    if s > 0: return p1/s, p2/s, p3/s
    return 1/3, 1/3, 1/3


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows, cuotas, cal = cargar(cur)
    eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos, {len(cuotas)} cuotas, {len(cal)} calendarios")

    # Recolectar predicciones por partido walk-forward
    # records: list[ (key, year, liga, bin4, bin8, bin12, model_probs_dict, outcome, cuotas) ]
    records = []
    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train)
        state_dual = construir_state_dual(eventos, fit_v5, ALFA_EMA)
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        fit_lam = fit_lambda_dual(state_dual, yt)
        if not fit_lam: continue

        pairs_v0, pairs_d = [], []
        for key, val in emas_v0.items():
            lh, lv, _, _ = val
            if lh is None or lv is None: continue
            pairs_v0.append((key[0], key[1], lh, lv, val[2], val[3]))
        for key, d in state_dual.items():
            if d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            lh = max(0.05, fit_lam["intercept"]+fit_lam["coef"][0]*d["xg_h"]+fit_lam["coef"][1]*d["res_h"])
            lv = max(0.05, fit_lam["intercept"]+fit_lam["coef"][0]*d["xg_v"]+fit_lam["coef"][1]*d["res_v"])
            pairs_d.append((d["liga"], d["fecha"], lh, lv, d["hg"], d["ag"]))
        rhos_v0 = calibrar_rho(pairs_v0, yt)
        rhos_d = calibrar_rho(pairs_d, yt)

        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            lh_d = max(0.05, fit_lam["intercept"]+fit_lam["coef"][0]*d["xg_h"]+fit_lam["coef"][1]*d["res_h"])
            lv_d = max(0.05, fit_lam["intercept"]+fit_lam["coef"][0]*d["xg_v"]+fit_lam["coef"][1]*d["res_v"])
            pld, ped, pvd = prob_1x2(lh_d, lv_d, rhos_d.get(key[0], -0.05))
            # Mercado
            if key in cuotas:
                c1, cx, c2 = cuotas[key]
                ov = (1/c1)+(1/cx)+(1/c2)
                pi_l, pi_e, pi_v = (1/c1)/ov, (1/cx)/ov, (1/c2)/ov
            else:
                pi_l = pi_e = pi_v = None
                c1 = cx = c2 = None
            # Anchored y amplificado solo si mercado disponible
            if pi_l is not None:
                # anchor 0.5
                anc05 = normalize_3(0.5*pl0+0.5*pi_l, 0.5*pe0+0.5*pi_e, 0.5*pv0+0.5*pi_v)
                anc07 = normalize_3(0.7*pld+0.3*pi_l, 0.7*ped+0.3*pi_e, 0.7*pvd+0.3*pi_v)
                # amplificar: P_apuesta = P_dual + 0.5*(P_dual - P_mkt)
                amp_l = pld + 0.5*(pld - pi_l)
                amp_e = ped + 0.5*(ped - pi_e)
                amp_v = pvd + 0.5*(pvd - pi_v)
                amp_l = max(0.001, amp_l); amp_e = max(0.001, amp_e); amp_v = max(0.001, amp_v)
                amp = normalize_3(amp_l, amp_e, amp_v)
            else:
                anc05 = anc07 = amp = (None, None, None)
            mkt = (pi_l, pi_e, pi_v) if pi_l is not None else (None, None, None)
            outcome = "L" if hg > ag else ("E" if hg == ag else "V")
            bin4 = get_bin(key[0], key[1], cal, 4)
            bin8 = get_bin(key[0], key[1], cal, 8)
            bin12 = get_bin(key[0], key[1], cal, 12)
            records.append({
                "key": key, "year": yt, "liga": key[0], "bin4": bin4, "bin8": bin8, "bin12": bin12,
                "outcome": outcome, "hg": hg, "ag": ag,
                "V0": (pl0, pe0, pv0), "Vdual": (pld, ped, pvd),
                "MKT": mkt, "Vanc05": anc05, "Vanc07": anc07, "Vamp": amp,
                "cuotas": (c1, cx, c2) if c1 is not None else None
            })
    print(f"Records OOS: {len(records)}")

    # Helper: agregar metricas para un slice
    def metrics_slice(recs, modelo, div_thr=0.0, require_cuotas=True):
        bs, hits = [], []
        bets = []  # (won, cuota_pick, p_top, p_mkt_pick)
        ptop_list = []
        for r in recs:
            ps = r[modelo]
            if ps[0] is None: continue
            pl, pe, pv = ps
            if hg_ag := True:
                opciones = [(pl,"L"),(pe,"E"),(pv,"V")]
                opciones.sort(key=lambda x: -x[0])
                p_top, pick = opciones[0]
                ptop_list.append(p_top)
            outcome = r["outcome"]
            target = (1 if outcome=="L" else 0, 1 if outcome=="E" else 0, 1 if outcome=="V" else 0)
            b = sum((p-t)**2 for p,t in zip(ps, target))
            bs.append(b); hits.append(int(pick == outcome))
            if require_cuotas and r["cuotas"] is None: continue
            if r["cuotas"] is None: continue
            c1, cx, c2 = r["cuotas"]
            cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
            mkt_ps = r["MKT"]
            pi_pick = mkt_ps[0] if pick=="L" else mkt_ps[1] if pick=="E" else mkt_ps[2]
            divergencia = p_top - pi_pick
            if divergencia < div_thr: continue
            ev = p_top * cuota_pick
            if ev < EV_MIN: continue
            bets.append((int(pick == outcome), cuota_pick))
        if not bs:
            return None
        n = len(bs)
        # Brier
        brier = sum(bs)/n
        # Hit
        hit = sum(hits)/n
        # Sharpness = std(P_top)
        if len(ptop_list) > 1:
            mean = sum(ptop_list)/len(ptop_list)
            var = sum((x-mean)**2 for x in ptop_list)/len(ptop_list)
            sharp = math.sqrt(var)
        else: sharp = 0
        # ECE simple en bucket apostable >=0.50
        in_b = [(p, w) for p, w in zip(ptop_list, hits) if p >= 0.50]
        if in_b:
            p_avg = sum(p for p, _ in in_b)/len(in_b)
            h_avg = sum(w for _, w in in_b)/len(in_b)
            ece_apost = abs(p_avg - h_avg)
        else: ece_apost = None
        # Yield
        if bets:
            wins = sum(w for w, _ in bets)
            stake = len(bets)
            pnl = sum((c - 1.0) if w else -1.0 for w, c in bets)
            yield_pct = pnl / stake * 100
            cuotas_picks = [c for _, c in bets]
            cuota_avg = sum(cuotas_picks)/len(cuotas_picks)
            cuota_min = min(cuotas_picks); cuota_max = max(cuotas_picks)
        else:
            yield_pct = None; pnl = 0; stake = 0; cuota_avg = cuota_min = cuota_max = None; wins = 0
        return {"N_universe": n, "Brier": brier, "Hit": hit, "Sharp": sharp,
                "ECE_apost": ece_apost, "N_bets": stake, "Yield": yield_pct,
                "Cuota_avg": cuota_avg, "Cuota_min": cuota_min, "Cuota_max": cuota_max,
                "wins": wins, "pnl": pnl}

    modelos = ["V0", "Vdual", "MKT", "Vanc05", "Vanc07", "Vamp"]

    # ============================================================
    # 1. Yield por LIGA × MODELO (universal y M.1)
    # ============================================================
    print("\n" + "="*120)
    print("YIELD POR LIGA × MODELO (div=0.10, EV>=1.03)")
    print("="*120)
    print(f"{'liga':<14s}{'modelo':<10s}{'N_b':>5s}{'hit%':>7s}{'Brier':>8s}{'sharp':>7s}{'yield%':>9s}{'cuota_avg':>11s}")
    ligas_all = sorted({r["liga"] for r in records})
    res_liga = {}
    for liga in ligas_all:
        recs_liga = [r for r in records if r["liga"] == liga]
        for modelo in modelos:
            m = metrics_slice(recs_liga, modelo, div_thr=0.10)
            if m is None or m["N_bets"] < 5: continue
            res_liga[(liga, modelo)] = m
            cat = "TOP" if liga in TOP_LIGAS else "no_top"
            print(f"{liga:<14s}{modelo:<10s}{m['N_bets']:>5d}{m['Hit']*100:>6.2f}%{m['Brier']:>8.4f}{m['Sharp']:>7.4f}{(m['Yield'] if m['Yield'] is not None else 0):>8.2f}%{m['Cuota_avg']:>11.2f}")

    # ============================================================
    # 2. Por categoria TOP vs NO_TOP
    # ============================================================
    print("\n" + "="*120)
    print("CATEGORIA TOP vs NO_TOP — yield por modelo + grid div_thr")
    print("="*120)
    print(f"{'cat':<8s}{'modelo':<10s}{'div':<6s}{'N_b':>5s}{'hit%':>7s}{'yield%':>9s}{'Brier':>8s}{'cuota_avg':>11s}")
    for cat, ligas_set in [("TOP", TOP_LIGAS), ("NO_TOP", set(ligas_all) - TOP_LIGAS)]:
        recs_cat = [r for r in records if r["liga"] in ligas_set]
        for modelo in modelos:
            for thr in DIV_THRS:
                m = metrics_slice(recs_cat, modelo, div_thr=thr)
                if m is None or m["N_bets"] < 5: continue
                cuota_str = f"{m['Cuota_avg']:>11.2f}" if m['Cuota_avg'] else f"{'-':>11s}"
                print(f"{cat:<8s}{modelo:<10s}{thr:<6.2f}{m['N_bets']:>5d}{m['Hit']*100:>6.2f}%{(m['Yield'] if m['Yield'] is not None else 0):>8.2f}%{m['Brier']:>8.4f}{cuota_str}")
            print()

    # ============================================================
    # 3. Por liga NO_TOP × bin4 × modelo (focus 4 ligas: ARG, BRA, TUR, NOR)
    # ============================================================
    print("\n" + "="*120)
    print("LIGAS NO_TOP focus (ARG/BRA/TUR/NOR) — bin4 × modelo (div=0.10)")
    print("="*120)
    target_ligas = ["Argentina", "Brasil", "Turquia", "Noruega"]
    print(f"{'liga':<12s}{'bin4':<6s}{'modelo':<10s}{'N_b':>5s}{'hit%':>7s}{'yield%':>9s}{'cuota_avg':>11s}")
    for liga in target_ligas:
        for bin4 in (0, 1, 2, 3):
            recs_lb = [r for r in records if r["liga"] == liga and r["bin4"] == bin4]
            for modelo in modelos:
                m = metrics_slice(recs_lb, modelo, div_thr=0.10)
                if m is None or m["N_bets"] < 3: continue
                cuota_str = f"{m['Cuota_avg']:>11.2f}" if m['Cuota_avg'] else f"{'-':>11s}"
                print(f"{liga:<12s}{bin4:<6d}{modelo:<10s}{m['N_bets']:>5d}{m['Hit']*100:>6.2f}%{(m['Yield'] if m['Yield'] is not None else 0):>8.2f}%{cuota_str}")
            print()

    # ============================================================
    # 4. Por anio × cat × modelo (div=0.10)
    # ============================================================
    print("\n" + "="*120)
    print("YIELD POR ANIO × CATEGORIA × MODELO (div=0.10)")
    print("="*120)
    print(f"{'cat':<8s}{'modelo':<10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}")
    for cat, ligas_set in [("TOP", TOP_LIGAS), ("NO_TOP", set(ligas_all) - TOP_LIGAS)]:
        for modelo in modelos:
            row = f"{cat:<8s}{modelo:<10s}"
            all_pnl = 0; all_n = 0
            for yt in YEARS_TEST:
                recs_cy = [r for r in records if r["liga"] in ligas_set and r["year"] == yt]
                m = metrics_slice(recs_cy, modelo, div_thr=0.10)
                if m and m["N_bets"] >= 3:
                    yld = m["Yield"]; n = m["N_bets"]
                    row += f"{yld:>8.2f}%({n:>2d})" if yld is not None else f"{'-':>10s}"
                    all_pnl += m["pnl"]; all_n += n
                else:
                    row += f"{'-':>10s}"
            row += f"{all_pnl/all_n*100:>8.2f}%({all_n:>2d})" if all_n else f"{'-':>10s}"
            print(row)
        print()

    # Persist JSON
    Path("analisis/experimento_masivo_no_top.json").write_text(
        json.dumps({"liga_modelo": {f"{k[0]}|{k[1]}": v for k, v in res_liga.items()}}, default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/experimento_masivo_no_top.json")


if __name__ == "__main__":
    main()

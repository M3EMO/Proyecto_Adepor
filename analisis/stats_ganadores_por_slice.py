"""Stats ganadores vs perdedores desglosadas por año, liga, equipo (local).

Para los picks que pasan EV >= 1.03 sobre universo expandido (N=7990 cuotas).
"""
import sqlite3, math, json, random
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge

DB = "fondo_quant.db"; WARMUP = 5; MAX_GOALS = 8; ALFA_EMA = 0.10; THETA_V0 = 0.30; EV_MIN = 1.03
YEARS_TEST = ["2023", "2024", "2025", "2026"]
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
        WHERE hg IS NOT NULL AND ag IS NOT NULL AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs IS NOT NULL AND as_v IS NOT NULL AND hc IS NOT NULL AND ac IS NOT NULL
          AND h_pos IS NOT NULL AND a_pos IS NOT NULL AND h_pass_pct IS NOT NULL AND a_pass_pct IS NOT NULL
          AND h_saves IS NOT NULL AND a_saves IS NOT NULL AND h_blocks IS NOT NULL AND a_blocks IS NOT NULL
          AND h_longballs_acc IS NOT NULL AND a_longballs_acc IS NOT NULL
        ORDER BY fecha
    """).fetchall()
    cuotas = {}
    for r in cur.execute("""
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha=f.fecha
         AND s.ht_fdco_norm=f.equipo_local_norm AND s.at_fdco_norm=f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
    """).fetchall():
        cuotas[(r[0], r[1], r[2], r[3])] = (r[4], r[5], r[6])
    return rows, cuotas


def construir_eventos(rows):
    eventos = []
    for r in rows:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac, hp, ap, hpp, app, hsv, asv2, hbl, abl, hlba, alba) = r
        for es_local, equipo, rival, goles, goles_rival, sot, shots, corners, pos, pass_pct, saves_rival, blocks_rival, lb in [
            (True, ht, at, hg, ag, hst, hs, hc, hp or 50, hpp or 0, asv2 or 0, abl or 0, hlba or 0),
            (False, at, ht, ag, hg, ast, asv, ac, ap or 50, app or 0, hsv or 0, hbl or 0, alba or 0)]:
            eventos.append({"liga": liga, "fecha": fecha, "equipo": equipo, "rival": rival, "es_local": es_local,
                            "goles": goles, "goles_rival": goles_rival, "sot": sot, "shots_off": max(0, shots-sot),
                            "corners": corners, "pos": pos, "pass_pct": pass_pct, "saves_rival": saves_rival,
                            "blocks_rival": blocks_rival, "longballs_acc": lb,
                            "ms": {"sot_l": hst, "sot_v": ast, "shots_l": hs, "shots_v": asv,
                                   "corners_l": hc, "corners_v": ac, "pos_l": hp or 50, "pos_v": ap or 50,
                                   "pass_pct_l": hpp or 0, "pass_pct_v": app or 0}})
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
    state = defaultdict(lambda: {"xg_h": None, "xg_a": None, "res_h": None, "res_a": None, "n_h": 0, "n_a": 0})
    out = {}
    for key in sorted(matches.keys(), key=lambda k: k[1]):
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None); ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]; sh, sa = state[ht], state[at]
        out[key] = {"xg_h": sh["xg_h"], "res_h": sh["res_h"], "n_h": sh["n_h"],
                    "xg_v": sa["xg_a"], "res_v": sa["res_a"], "n_v": sa["n_a"],
                    "hg": ev_l["goles"], "ag": ev_l["goles_rival"], "fecha": key[1], "liga": key[0],
                    "ht": ht, "at": at, "ms": ev_l["ms"]}
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
    state = defaultdict(lambda: {"fh": None, "fa": None, "nfh": 0, "nfa": 0})
    out = {}
    for key in sorted(matches.keys(), key=lambda k: k[1]):
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None); ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]; sh, sa = state[ht], state[at]
        lam_h = sh["fh"] if sh["nfh"] >= WARMUP else None; lam_v = sa["fa"] if sa["nfa"] >= WARMUP else None
        out[key] = (lam_h, lam_v, ev_l["goles"], ev_l["goles_rival"])
        beta = beta_sot_map.get(key[0], 0.352)
        xl = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]; xl = 0.70*xl + 0.30*ev_l["goles"]
        xv = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]; xv = 0.70*xv + 0.30*ev_v["goles"]
        xlp = theta*xl + (1-theta)*ev_l["goles"]; xvp = theta*xv + (1-theta)*ev_v["goles"]
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
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows, cuotas = cargar(cur); eventos = construir_eventos(rows); beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} stats, {len(cuotas)} cuotas")

    bets_all = []
    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fit_v5 = fit_v5_xg(ev_train); state_dual = construir_state_dual(eventos, fit_v5, ALFA_EMA)
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
        rhos_v0 = calibrar_rho(pairs_v0, yt); rhos_d = calibrar_rho(pairs_d, yt)
        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            d = state_dual.get(key)
            if not d or d["n_h"] < WARMUP or d["n_v"] < WARMUP: continue
            if key not in cuotas: continue
            pl0, pe0, pv0 = prob_1x2(lh, lv, rhos_v0.get(key[0], -0.05))
            opc = sorted([(pl0,"L"),(pe0,"E"),(pv0,"V")], key=lambda x: -x[0])
            p_top, pick = opc[0]
            c1, cx, c2 = cuotas[key]
            cuota_pick = c1 if pick=="L" else cx if pick=="E" else c2
            ev_calc = p_top * cuota_pick
            if ev_calc < EV_MIN: continue
            outcome = "L" if hg > ag else ("E" if hg == ag else "V")
            won = pick == outcome
            ov = (1/c1)+(1/cx)+(1/c2)
            pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
            div = p_top - pi_pick
            bets_all.append({
                "liga": key[0], "year": yt, "fecha": key[1], "ht": key[2], "at": key[3],
                "won": won, "cuota": cuota_pick, "pick": pick, "p_top": p_top, "div": div,
                "ema_xg_h": d["xg_h"], "ema_xg_v": d["xg_v"],
                "ema_res_h": d["res_h"], "ema_res_v": d["res_v"], "ms": d["ms"]
            })
    print(f"Bets total (EV>=1.03): {len(bets_all)}")

    # ============================================================
    # POR LIGA
    # ============================================================
    print("\n" + "="*100)
    print("STATS GANADORES vs PERDEDORES POR LIGA (todos los picks que pasan EV)")
    print("="*100)
    print(f"{'liga':<14s}{'N':>6s}{'won%':>7s}{'sot_l_w':>9s}{'sot_l_l':>9s}{'sot_v_w':>9s}{'sot_v_l':>9s}{'res_h_w':>9s}{'res_h_l':>9s}")
    for liga in sorted({b["liga"] for b in bets_all}):
        b_l = [b for b in bets_all if b["liga"] == liga]
        if len(b_l) < 30: continue
        won = [b for b in b_l if b["won"]]; lost = [b for b in b_l if not b["won"]]
        if not won or not lost: continue
        sot_l_w = sum(b["ms"]["sot_l"] for b in won)/len(won)
        sot_l_l = sum(b["ms"]["sot_l"] for b in lost)/len(lost)
        sot_v_w = sum(b["ms"]["sot_v"] for b in won)/len(won)
        sot_v_l = sum(b["ms"]["sot_v"] for b in lost)/len(lost)
        res_h_w = sum(b["ema_res_h"] for b in won)/len(won)
        res_h_l = sum(b["ema_res_h"] for b in lost)/len(lost)
        print(f"{liga:<14s}{len(b_l):>6d}{len(won)/len(b_l)*100:>6.2f}%"
              f"{sot_l_w:>9.2f}{sot_l_l:>9.2f}{sot_v_w:>9.2f}{sot_v_l:>9.2f}{res_h_w:>+9.4f}{res_h_l:>+9.4f}")

    # ============================================================
    # POR AÑO
    # ============================================================
    print("\n" + "="*100)
    print("STATS GANADORES vs PERDEDORES POR AÑO")
    print("="*100)
    print(f"{'year':<6s}{'N':>6s}{'won%':>7s}{'sot_l_w':>9s}{'sot_l_l':>9s}{'sot_v_w':>9s}{'sot_v_l':>9s}{'res_h_w':>9s}{'res_h_l':>9s}")
    for yt in YEARS_TEST:
        b_y = [b for b in bets_all if b["year"] == yt]
        won = [b for b in b_y if b["won"]]; lost = [b for b in b_y if not b["won"]]
        if not won or not lost: continue
        sot_l_w = sum(b["ms"]["sot_l"] for b in won)/len(won)
        sot_l_l = sum(b["ms"]["sot_l"] for b in lost)/len(lost)
        sot_v_w = sum(b["ms"]["sot_v"] for b in won)/len(won)
        sot_v_l = sum(b["ms"]["sot_v"] for b in lost)/len(lost)
        res_h_w = sum(b["ema_res_h"] for b in won)/len(won)
        res_h_l = sum(b["ema_res_h"] for b in lost)/len(lost)
        print(f"{yt:<6s}{len(b_y):>6d}{len(won)/len(b_y)*100:>6.2f}%"
              f"{sot_l_w:>9.2f}{sot_l_l:>9.2f}{sot_v_w:>9.2f}{sot_v_l:>9.2f}{res_h_w:>+9.4f}{res_h_l:>+9.4f}")

    # ============================================================
    # TOP EQUIPOS LOCALES con yield positivo (apostando como local)
    # ============================================================
    print("\n" + "="*100)
    print("TOP EQUIPOS LOCALES con MEJOR yield (N >= 5 picks como local)")
    print("="*100)
    by_team_local = defaultdict(list)
    for b in bets_all:
        if b["pick"] == "L":  # picks LOCALES
            by_team_local[(b["liga"], b["ht"])].append(b)
    print(f"{'liga':<14s}{'equipo':<28s}{'N':>5s}{'won':>5s}{'hit%':>7s}{'yield%':>9s}")
    rows_team = []
    for (liga, equipo), bs in by_team_local.items():
        if len(bs) < 5: continue
        won = sum(b["won"] for b in bs)
        pnl = sum((b["cuota"]-1.0) if b["won"] else -1.0 for b in bs)
        rows_team.append((liga, equipo, len(bs), won, won/len(bs)*100, pnl/len(bs)*100))
    rows_team.sort(key=lambda x: -x[5])
    for liga, equipo, n, won, hit, yld in rows_team[:25]:
        print(f"{liga:<14s}{equipo:<28s}{n:>5d}{won:>5d}{hit:>6.2f}%{yld:>+8.2f}%")

    print("\n--- BOTTOM equipos locales (peor yield) ---")
    rows_team.sort(key=lambda x: x[5])
    for liga, equipo, n, won, hit, yld in rows_team[:15]:
        print(f"{liga:<14s}{equipo:<28s}{n:>5d}{won:>5d}{hit:>6.2f}%{yld:>+8.2f}%")

    # ============================================================
    # YIELD POR LIGA × AÑO
    # ============================================================
    print("\n" + "="*100)
    print("YIELD POR LIGA × AÑO (picks con EV >= 1.03)")
    print("="*100)
    print(f"{'liga':<14s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N_total':>10s}")
    for liga in sorted({b["liga"] for b in bets_all}):
        b_l = [b for b in bets_all if b["liga"] == liga]
        if len(b_l) < 20: continue
        row = f"{liga:<14s}"
        n_total = 0; pnl_total = 0
        for yt in YEARS_TEST:
            b_ly = [b for b in b_l if b["year"] == yt]
            if len(b_ly) < 5: row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum((b["cuota"]-1.0) if b["won"] else -1.0 for b in b_ly)
            yld = pnl/n*100
            row += f"{yld:>+8.2f}%({n:>2d})"
            n_total += n; pnl_total += pnl
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%({n_total:>4d})"
        print(row)

    # Persist
    Path("analisis/stats_ganadores_por_slice.json").write_text(
        json.dumps({"top_teams": [{"liga": l, "equipo": e, "n": n, "won": w, "hit": h, "yield": y}
                                   for l, e, n, w, h, y in rows_team[:50]]},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/stats_ganadores_por_slice.json")


if __name__ == "__main__":
    main()

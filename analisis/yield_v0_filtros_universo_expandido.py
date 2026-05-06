"""Yield V0 P>=0.60 + div>=0.05 sobre universo expandido N=7990 cuotas.

Compara también V0 sin filtros (solo EV>=1.03) y otras combinaciones.
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
                            "blocks_rival": blocks_rival, "longballs_acc": lb})
    return eventos


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
        emas_v0 = construir_emas_v0(eventos, beta_sot_map, ALFA_EMA, THETA_V0)
        pairs = []
        for key, val in emas_v0.items():
            lh, lv, _, _ = val
            if lh is None or lv is None: continue
            pairs.append((key[0], key[1], lh, lv, val[2], val[3]))
        rhos = calibrar_rho(pairs, yt)
        for key, val in emas_v0.items():
            if key[1][:4] != yt: continue
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            if key not in cuotas: continue
            pl, pe, pv = prob_1x2(lh, lv, rhos.get(key[0], -0.05))
            opc = sorted([(pl,"L"),(pe,"E"),(pv,"V")], key=lambda x: -x[0])
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
            pnl = (cuota_pick-1.0) if won else -1.0
            bets_all.append({"liga": key[0], "year": yt, "won": won, "pnl": pnl,
                             "p_top": p_top, "div": div, "cuota": cuota_pick, "pick": pick})
    print(f"Bets totales (EV>=1.03): {len(bets_all)}")

    # Estrategias a probar
    strategies = {
        "V0 EV>=1.03 (sin filtros)": lambda b: True,
        "V0 P>=0.55 + div>=0.05": lambda b: b["p_top"] >= 0.55 and b["div"] >= 0.05,
        "V0 P>=0.60 + div>=0.05": lambda b: b["p_top"] >= 0.60 and b["div"] >= 0.05,
        "V0 P>=0.55 + div>=0.10": lambda b: b["p_top"] >= 0.55 and b["div"] >= 0.10,
        "V0 P>=0.60 + div>=0.10": lambda b: b["p_top"] >= 0.60 and b["div"] >= 0.10,
        "V0 div>=0.15": lambda b: b["div"] >= 0.15,
        "V0 P>=0.50 + div>=0.05 + cuota in [1.5,2.5)": lambda b: b["p_top"] >= 0.50 and b["div"] >= 0.05 and 1.5 <= b["cuota"] < 2.5,
        "V0 P>=0.55 + div>=0.05 + pick=L": lambda b: b["p_top"] >= 0.55 and b["div"] >= 0.05 and b["pick"]=="L",
    }

    print("\n" + "="*120)
    print("YIELD POR ESTRATEGIA — universo expandido N=7990 cuotas")
    print("="*120)
    print(f"{'estrategia':<55s}{'N':>6s}{'hit%':>7s}{'yield%':>9s}{'cuota_avg':>11s}{'ROI_100':>9s}")
    res_strat = {}
    for name, fn in strategies.items():
        bets = [b for b in bets_all if fn(b)]
        if len(bets) < 10: continue
        n = len(bets); hits = sum(b["won"] for b in bets); pnl = sum(b["pnl"] for b in bets)
        cavg = sum(b["cuota"] for b in bets)/n
        yld = pnl/n*100
        res_strat[name] = bets
        print(f"{name:<55s}{n:>6d}{hits/n*100:>6.2f}%{yld:>+8.2f}%{cavg:>11.2f}{pnl:>+8.2f}")

    print("\n" + "="*120)
    print("YIELD POR LIGA × AÑO — V0 P>=0.60 + div>=0.05 (la mejor del estudio previo)")
    print("="*120)
    bets = res_strat.get("V0 P>=0.60 + div>=0.05", [])
    print(f"{'liga':<14s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N_total':>10s}")
    for liga in sorted({b["liga"] for b in bets}):
        b_l = [b for b in bets if b["liga"] == liga]
        if len(b_l) < 5: continue
        row = f"{liga:<14s}"; nt = pt = 0
        for yt in YEARS_TEST:
            b_ly = [b for b in b_l if b["year"] == yt]
            if len(b_ly) < 3:
                row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            nt += n; pt += pnl
        is_yld = pt/nt*100 if nt else 0
        row += f"{is_yld:>+7.2f}%({nt:>4d})"
        print(row)

    print("\n" + "="*120)
    print("YIELD POR LIGA × AÑO — V0 P>=0.55 + div>=0.05 (más volumen)")
    print("="*120)
    bets = res_strat.get("V0 P>=0.55 + div>=0.05", [])
    print(f"{'liga':<14s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N_total':>10s}")
    for liga in sorted({b["liga"] for b in bets}):
        b_l = [b for b in bets if b["liga"] == liga]
        if len(b_l) < 5: continue
        row = f"{liga:<14s}"; nt = pt = 0
        for yt in YEARS_TEST:
            b_ly = [b for b in b_l if b["year"] == yt]
            if len(b_ly) < 3:
                row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            nt += n; pt += pnl
        is_yld = pt/nt*100 if nt else 0
        row += f"{is_yld:>+7.2f}%({nt:>4d})"
        print(row)

    # Bootstrap CI95% sobre cada estrategia
    print("\n" + "="*120)
    print("BOOTSTRAP CI95% por estrategia")
    print("="*120)
    print(f"{'estrategia':<55s}{'N':>6s}{'yield':>9s}{'CI95_lo':>10s}{'CI95_hi':>10s}{'P(>0)':>8s}{'Sharpe':>8s}{'maxDD':>8s}")
    for name, bets in res_strat.items():
        n = len(bets); pnls = [b["pnl"] for b in bets]
        if n < 30: continue
        yld_obs = sum(pnls)/n*100
        boots = [sum(random.choice(pnls) for _ in range(n))/n*100 for _ in range(5000)]
        boots.sort()
        ci_lo, ci_hi = boots[125], boots[4875]
        ppos = sum(1 for x in boots if x > 0)/5000*100
        bets_sorted = sorted(bets, key=lambda b: b["year"])
        bk = 100; peak = 100; max_dd = 0
        for b in bets_sorted:
            bk += b["pnl"]; peak = max(peak, bk)
            dd = (peak - bk)/peak*100; max_dd = max(max_dd, dd)
        mean_pnl = sum(pnls)/n; var = sum((p-mean_pnl)**2 for p in pnls)/n
        std = math.sqrt(var); sharpe = mean_pnl/std*math.sqrt(n) if std > 0 else 0
        print(f"{name:<55s}{n:>6d}{yld_obs:>+8.2f}%{ci_lo:>+9.2f}%{ci_hi:>+9.2f}%{ppos:>+7.1f}%{sharpe:>8.2f}{max_dd:>7.2f}%")


if __name__ == "__main__":
    main()

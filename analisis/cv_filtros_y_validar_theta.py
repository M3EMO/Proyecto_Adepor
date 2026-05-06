"""3 análisis:

1. CV-Schema A: train filtro con TODO, evaluar en cada año por separado.
2. CV-Schema B: train filtro con CADA año, evaluar en el resto (leave-one-year-out + holdout otros años).
3. Validar θ del híbrido xg_final = θ·xg_calc + (1-θ)·goles. Motor usa θ=0.70.
   Grid θ ∈ [0, 1] sobre RMSE forward-EMA goles. Global + por año.
"""
import sqlite3, math, json, random
from collections import defaultdict
from pathlib import Path
import numpy as np

DB = "fondo_quant.db"; WARMUP = 5; MAX_GOALS = 8; ALFA_EMA = 0.10; EV_MIN = 1.03
YEARS = ["2022", "2023", "2024", "2025", "2026"]
random.seed(42)


def get_beta_sot_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
    ).fetchall()}


def get_alfa_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND valor_real IS NOT NULL"
    ).fetchall()}


def cargar(cur):
    rows = cur.execute("""
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hg IS NOT NULL AND ag IS NOT NULL AND hst IS NOT NULL AND ast IS NOT NULL
          AND hs IS NOT NULL AND as_v IS NOT NULL AND hc IS NOT NULL AND ac IS NOT NULL
        ORDER BY fecha
    """).fetchall()
    cuotas = {}
    for r in cur.execute("""
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha_fdco=f.fecha
         AND s.ht_fdco_norm=f.equipo_local_norm AND s.at_fdco_norm=f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
    """).fetchall():
        cuotas[(r[0], r[1], r[2], r[3])] = (r[4], r[5], r[6])
    return rows, cuotas


def construir_eventos(rows):
    eventos = []
    for r in rows:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac = r
        eventos.append({"liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
                        "goles": hg, "goles_rival": ag, "sot": hst, "shots_off": max(0, hs - hst), "corners": hc})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast), "corners": ac})
    return eventos


def ema_v0_with_theta(eventos, beta_sot_map, alfa_map, theta):
    """EMA con xg_final = theta*xg_calc + (1-theta)*goles. Para validar theta empírico."""
    matches = defaultdict(list)
    for ev in eventos:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    state = defaultdict(lambda: {"fh": None, "fa": None, "nfh": 0, "nfa": 0})
    out = {}
    for key in sorted(matches.keys(), key=lambda k: k[1]):
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        ht, at = key[2], key[3]; sh, sa = state[ht], state[at]
        liga = key[0]
        beta = beta_sot_map.get(liga, 0.352)
        alfa = alfa_map.get(liga, ALFA_EMA)
        # Pre-event EMA capture (forward-strict)
        out[key] = {"lh_pre": sh["fh"], "lv_pre": sa["fa"], "n_h": sh["nfh"], "n_a": sa["nfa"],
                    "hg": ev_l["goles"], "ag": ev_l["goles_rival"], "fecha": key[1], "liga": liga}
        # Update con xg_final = theta*xg_calc + (1-theta)*goles
        xg_calc_l = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]
        xg_calc_v = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]
        xg_final_l = theta*xg_calc_l + (1-theta)*ev_l["goles"]
        xg_final_v = theta*xg_calc_v + (1-theta)*ev_v["goles"]
        sh["fh"] = xg_final_l if sh["fh"] is None else alfa*xg_final_l + (1-alfa)*sh["fh"]; sh["nfh"] += 1
        sa["fa"] = xg_final_v if sa["fa"] is None else alfa*xg_final_v + (1-alfa)*sa["fa"]; sa["nfa"] += 1
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


def build_bets_all(emas, cuotas, rhos):
    bets = []
    for key, ev in emas.items():
        lh, lv = ev["lh_pre"], ev["lv_pre"]
        if lh is None or lv is None or key not in cuotas: continue
        if ev["n_h"] < WARMUP or ev["n_a"] < WARMUP: continue
        pl, pe, pv = prob_1x2(lh, lv, rhos.get(ev["liga"], -0.05))
        opc = sorted([(pl, "L"), (pe, "E"), (pv, "V")], key=lambda x: -x[0])
        p_top, pick = opc[0]
        c1, cx, c2 = cuotas[key]
        cuota_pick = c1 if pick == "L" else cx if pick == "E" else c2
        ev_calc = p_top * cuota_pick
        if ev_calc < EV_MIN: continue
        outcome = "L" if ev["hg"] > ev["ag"] else ("E" if ev["hg"] == ev["ag"] else "V")
        won = pick == outcome
        ov = (1/c1)+(1/cx)+(1/c2)
        pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
        bets.append({"liga": ev["liga"], "year": key[1][:4], "won": won,
                     "pnl": (cuota_pick-1.0) if won else -1.0, "p_top": p_top,
                     "div": p_top - pi_pick, "cuota_pick": cuota_pick, "lh": lh, "lv": lv})
    return bets


def find_best_filter(b_l, grid_p, grid_d, grid_cmin, grid_cmax, n_min=20):
    best = None; best_score = -math.inf
    for p_min in grid_p:
        for d_min in grid_d:
            for c_min in grid_cmin:
                for c_max in grid_cmax:
                    if c_min >= c_max: continue
                    bs = [b for b in b_l if b["p_top"] >= p_min and b["div"] >= d_min and c_min <= b["cuota_pick"] <= c_max]
                    if len(bs) < n_min: continue
                    yld = sum(b["pnl"] for b in bs)/len(bs)*100
                    if yld <= 0: continue
                    yrs_pnl = defaultdict(list)
                    for b in bs: yrs_pnl[b["year"]].append(b["pnl"])
                    yrs_pos = sum(1 for y, ps in yrs_pnl.items() if len(ps) >= 5 and sum(ps)/len(ps) > 0)
                    yrs_count = sum(1 for y, ps in yrs_pnl.items() if len(ps) >= 5)
                    if yrs_count == 0: continue
                    score = yld * math.log(len(bs)+1) * (yrs_pos / yrs_count)**1.5
                    if score > best_score:
                        best_score = score
                        best = {"p_min": p_min, "d_min": d_min, "c_min": c_min, "c_max": c_max,
                                "N": len(bs), "yield": yld, "yrs_pos": yrs_pos, "yrs_count": yrs_count}
    return best


def apply_filter(b_l, f):
    return [b for b in b_l if b["p_top"] >= f["p_min"] and b["div"] >= f["d_min"]
            and f["c_min"] <= b["cuota_pick"] <= f["c_max"]]


def main():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows, cuotas = cargar(cur); eventos = construir_eventos(rows)
    beta_sot_map = get_beta_sot_map(cur); alfa_map = get_alfa_map(cur)

    # Build bets V0 motor productivo (theta=0.70)
    print("Construyendo emas V0 (theta=0.70)...")
    emas = ema_v0_with_theta(eventos, beta_sot_map, alfa_map, theta=0.70)
    pairs = [(ev["liga"], ev["lh_pre"], ev["lv_pre"], ev["hg"], ev["ag"])
             for k, ev in emas.items() if ev["lh_pre"] is not None and ev["lv_pre"] is not None]
    rhos = calibrar_rho_pairs(pairs)
    bets = build_bets_all(emas, cuotas, rhos)
    print(f"N bets V0 motor productivo (theta=0.70): {len(bets)}")

    LIGAS_OBJ = ["Alemania","Argentina","Brasil","Espana","Francia","Inglaterra","Italia","Turquia"]
    grid_p = [0.0, 0.40, 0.45, 0.50, 0.55, 0.60]
    grid_d = [-0.05, 0.0, 0.05, 0.08, 0.10, 0.15, 0.20]
    grid_cmin = [0, 1.5, 2.0]
    grid_cmax = [99, 4.0, 3.0, 2.5]

    # =========================================================
    # SCHEMA A: Train filtro con TODO los partidos, eval en cada año
    # =========================================================
    print("\n" + "="*120)
    print("SCHEMA A — Train filtro con TODOS los anios, evaluar EACH year separately")
    print("="*120)
    print(f"{'liga':<14s}{'cfg_train_all':<32s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>6s}")
    schema_a = {}
    for liga in LIGAS_OBJ:
        b_l = [b for b in bets if b["liga"] == liga]
        if len(b_l) < 50: continue
        best = find_best_filter(b_l, grid_p, grid_d, grid_cmin, grid_cmax, n_min=30)
        if not best:
            print(f"{liga:<14s}{'sin filtro':<32s}")
            continue
        # Aplicar filtro y mostrar yield por año
        bs = apply_filter(b_l, best)
        cfg = f"P>={best['p_min']:.2f} d>={best['d_min']:.2f}"
        if best['c_max'] < 99: cfg += f" c<={best['c_max']:.1f}"
        if best['c_min'] > 0: cfg += f" c>={best['c_min']:.1f}"
        row = f"{liga:<14s}{cfg:<32s}"
        n_total = pnl_total = 0
        by_year = {}
        for yt in YEARS:
            b_ly = [b for b in bs if b["year"] == yt]
            if len(b_ly) < 3:
                row += f"{'-':>10s}"
                by_year[yt] = None
                continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            by_year[yt] = {"N": n, "yield": yld}
            n_total += n; pnl_total += pnl
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%{n_total:>6d}"
        print(row)
        schema_a[liga] = {"filter": best, "by_year": by_year, "IS": is_yld, "N": n_total}

    # =========================================================
    # SCHEMA B: Train filtro con CADA año, evaluar en otros años (LOYO)
    # =========================================================
    print("\n" + "="*120)
    print("SCHEMA B — Train filtro con CADA año, evaluar en el resto (LOYO)")
    print("="*120)
    print(f"{'liga':<14s}{'train_year':<12s}{'cfg_train':<32s}{'IS_train':>10s}{'OOS_otros':>11s}{'N_oos':>6s}")
    schema_b = defaultdict(list)
    for liga in LIGAS_OBJ:
        b_l = [b for b in bets if b["liga"] == liga]
        if len(b_l) < 50: continue
        for yt_train in YEARS:
            b_train = [b for b in b_l if b["year"] == yt_train]
            b_test = [b for b in b_l if b["year"] != yt_train]
            if len(b_train) < 30 or len(b_test) < 20: continue
            best = find_best_filter(b_train, grid_p, grid_d, grid_cmin, grid_cmax, n_min=15)
            if not best:
                print(f"{liga:<14s}{yt_train:<12s}{'no filtro train':<32s}")
                continue
            bs_te = apply_filter(b_test, best)
            cfg = f"P>={best['p_min']:.2f} d>={best['d_min']:.2f}"
            if best['c_max'] < 99: cfg += f" c<={best['c_max']:.1f}"
            if best['c_min'] > 0: cfg += f" c>={best['c_min']:.1f}"
            n_te = len(bs_te); pnl_te = sum(b["pnl"] for b in bs_te) if bs_te else 0
            yld_te = pnl_te/n_te*100 if n_te else None
            yld_te_s = f"{yld_te:+.2f}%" if yld_te is not None else "(N=0)"
            print(f"{liga:<14s}{yt_train:<12s}{cfg:<32s}{best['yield']:>+9.2f}%{yld_te_s:>11s}{n_te:>6d}")
            schema_b[liga].append({"train_year": yt_train, "cfg": best, "IS_train": best['yield'],
                                    "OOS": yld_te, "N_oos": n_te})
        print()

    # =========================================================
    # CONSISTENCIA: filtros que sobreviven AMBOS schemas
    # =========================================================
    print("\n" + "="*120)
    print("CONSISTENCIA — ligas con yield positivo en ambos schemas")
    print("="*120)
    print(f"{'liga':<14s}{'A_yield_IS':>12s}{'A_anos_pos':>12s}{'B_yield_avg_OOS':>18s}{'B_anos_train_pos':>18s}{'verdicto':>15s}")
    for liga in LIGAS_OBJ:
        a = schema_a.get(liga)
        b_results = schema_b.get(liga, [])
        if not a or not b_results: continue
        a_yld = a["IS"]
        a_anos_pos = sum(1 for v in a["by_year"].values() if v is not None and v["yield"] > 0)
        a_anos_count = sum(1 for v in a["by_year"].values() if v is not None)
        b_oos_pos = sum(1 for r in b_results if r["OOS"] is not None and r["OOS"] > 0)
        b_oos_avg = (sum(r["OOS"]*r["N_oos"] for r in b_results if r["OOS"] is not None)
                     / sum(r["N_oos"] for r in b_results if r["OOS"] is not None)) if any(r["OOS"] is not None for r in b_results) else None
        verdict = "VALIDADO" if (a_yld > 5 and a_anos_pos >= a_anos_count*0.5
                                  and b_oos_avg is not None and b_oos_avg > 0
                                  and b_oos_pos >= len(b_results)*0.5) else "RECHAZAR"
        b_oos_str = f"{b_oos_avg:+.2f}%" if b_oos_avg is not None else "n/a"
        a_str = f"{a_anos_pos}/{a_anos_count}"
        b_str = f"{b_oos_pos}/{len(b_results)}"
        print(f"{liga:<14s}{a_yld:>+11.2f}%{a_str:>12s}{b_oos_str:>18s}{b_str:>18s}{verdict:>15s}")

    # =========================================================
    # 3. VALIDACION EMPIRICA THETA xg_final híbrido
    # =========================================================
    print("\n" + "="*120)
    print("VALIDACION THETA EMPIRICA — RMSE forward EMA goles, motor productivo theta=0.70")
    print("="*120)

    THETAS = [round(i*0.05, 2) for i in range(21)]
    print(f"\n{'theta':<8s}{'RMSE_global':>14s}", end="")
    for yt in YEARS: print(f"{('RMSE_'+yt):>11s}", end="")
    print()

    results_theta = {}
    for theta in THETAS:
        emas_theta = ema_v0_with_theta(eventos, beta_sot_map, alfa_map, theta)
        # RMSE forward: predict goles_real_t con EMA pre-partido
        # Para cada equipo, es el "ema_xg_pre" como predictor de "goles_t"
        pairs_pred = defaultdict(list)
        for k, ev in emas_theta.items():
            if ev["lh_pre"] is None or ev["lv_pre"] is None: continue
            if ev["n_h"] < WARMUP: continue
            yt = k[1][:4]
            # Local: EMA local predice goles_real local
            pairs_pred["all"].append((ev["lh_pre"], ev["hg"]))
            pairs_pred[yt].append((ev["lh_pre"], ev["hg"]))
            pairs_pred["all"].append((ev["lv_pre"], ev["ag"]))
            pairs_pred[yt].append((ev["lv_pre"], ev["ag"]))
        rmse = {}
        for k, pairs in pairs_pred.items():
            if not pairs: continue
            rmse[k] = math.sqrt(sum((p[0] - p[1])**2 for p in pairs) / len(pairs))
        results_theta[theta] = rmse
        marker = " <- motor" if theta == 0.70 else ""
        row = f"{theta:<8.2f}{rmse.get('all', 0):>14.4f}"
        for yt in YEARS:
            row += f"{rmse.get(yt, 0):>11.4f}" if yt in rmse else f"{'-':>11s}"
        print(row + marker)

    # Best theta global + per year
    print("\nMejor theta:")
    best_global = min(results_theta.keys(), key=lambda t: results_theta[t].get("all", math.inf))
    print(f"  global: theta={best_global:.2f} RMSE={results_theta[best_global].get('all', 0):.4f}")
    print(f"  motor productivo theta=0.70 RMSE={results_theta[0.70].get('all', 0):.4f}")
    for yt in YEARS:
        ts = [(t, r.get(yt, math.inf)) for t, r in results_theta.items() if yt in r]
        if ts:
            best_yt = min(ts, key=lambda x: x[1])
            print(f"  {yt}: theta_opt={best_yt[0]:.2f} RMSE={best_yt[1]:.4f}, motor 0.70 RMSE={results_theta[0.70].get(yt, 0):.4f}")

    Path("analisis/cv_filtros_y_theta.json").write_text(
        json.dumps({"schema_A": {k: {"filter": v["filter"], "IS": v["IS"], "N": v["N"], "by_year": v["by_year"]}
                                  for k, v in schema_a.items()},
                    "schema_B": {k: v for k, v in schema_b.items()},
                    "theta_grid": {str(k): v for k, v in results_theta.items()}},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/cv_filtros_y_theta.json")


if __name__ == "__main__":
    main()

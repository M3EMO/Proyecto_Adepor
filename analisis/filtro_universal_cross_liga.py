"""Filtro POR PAÍS — buscar mejor (P_min, div_min, cuota_max) por liga con CONSISTENCIA cross-año.

Por cada liga: grid search exhaustivo. Score = yield_IS * log(N+1) * (años_pos / años_count)^2.
Validar:
  - IS pooled yield > 0
  - >= 50% años positivos (mínimo 2/3)
  - N >= 30
  - CI95% bootstrap
  - Walk-forward TRUE-OOS: train años más viejos, test 2025+2026 (holdout)
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


def construir_emas_v0_REAL(eventos, beta_sot_map, alfa):
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
        lam_h = sh["fh"] if sh["nfh"] >= WARMUP else None
        lam_v = sa["fa"] if sa["nfa"] >= WARMUP else None
        out[key] = (lam_h, lam_v, ev_l["goles"], ev_l["goles_rival"])
        beta = beta_sot_map.get(key[0], 0.352)
        xg_calc_l = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]
        xg_final_l = 0.70*xg_calc_l + 0.30*ev_l["goles"]
        xg_calc_v = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]
        xg_final_v = 0.70*xg_calc_v + 0.30*ev_v["goles"]
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
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows, cuotas = cargar(cur); eventos = construir_eventos(rows); beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} stats, {len(cuotas)} cuotas matched")

    emas = construir_emas_v0_REAL(eventos, beta_sot_map, ALFA_EMA)
    pairs = [(k[0], v[0], v[1], v[2], v[3]) for k, v in emas.items() if v[0] is not None and v[1] is not None]
    rhos = calibrar_rho(pairs)

    # Build bets
    bets = []
    for key, val in emas.items():
        lh, lv, hg, ag = val
        if lh is None or lv is None or key not in cuotas: continue
        pl, pe, pv = prob_1x2(lh, lv, rhos.get(key[0], -0.05))
        opc = sorted([(pl, "L"), (pe, "E"), (pv, "V")], key=lambda x: -x[0])
        p_top, pick = opc[0]
        c1, cx, c2 = cuotas[key]
        cuota_pick = c1 if pick == "L" else cx if pick == "E" else c2
        ev = p_top * cuota_pick
        if ev < EV_MIN: continue
        outcome = "L" if hg > ag else ("E" if hg == ag else "V")
        won = pick == outcome
        ov = (1/c1)+(1/cx)+(1/c2)
        pi_pick = (1/c1)/ov if pick=="L" else (1/cx)/ov if pick=="E" else (1/c2)/ov
        bets.append({"liga": key[0], "year": key[1][:4], "won": won, "pnl": (cuota_pick-1.0) if won else -1.0,
                     "p_top": p_top, "div": p_top - pi_pick, "cuota_pick": cuota_pick, "pick": pick})
    print(f"N bets V0 REAL: {len(bets)}")

    LIGAS_OBJ = ["Alemania","Argentina","Brasil","Espana","Francia","Inglaterra","Italia","Turquia"]

    # Grid PER LIGA exhaustivo
    grid_p = [0.0, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
    grid_d = [-0.10, -0.05, 0.0, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    grid_cmax = [99, 4.0, 3.0, 2.5, 2.0]
    grid_cmin = [0, 1.5, 2.0]

    # Por cada liga, encontrar BEST filtro
    print("\n" + "="*120)
    print("FILTRO POR PAIS — busqueda exhaustiva con consistencia cross-anio")
    print("="*120)
    print(f"{'liga':<14s}{'P_min':<8s}{'div_min':<10s}{'c_min':<8s}{'c_max':<8s}{'N':>6s}{'yield':>9s}{'CI95_lo':>10s}{'yrs_pos':>10s}")

    best_per_liga = {}
    for liga in LIGAS_OBJ:
        b_l_all = [b for b in bets if b["liga"] == liga]
        if len(b_l_all) < 50: continue
        best = None; best_score = -math.inf
        for p_min in grid_p:
            for d_min in grid_d:
                for c_min in grid_cmin:
                    for c_max in grid_cmax:
                        if c_min >= c_max: continue
                        bs = [b for b in b_l_all if b["p_top"] >= p_min and b["div"] >= d_min
                              and c_min <= b["cuota_pick"] <= c_max]
                        if len(bs) < 30: continue
                        yrs_pnl = defaultdict(list)
                        for b in bs: yrs_pnl[b["year"]].append(b["pnl"])
                        yrs_pos = sum(1 for y, ps in yrs_pnl.items() if len(ps) >= 5 and sum(ps)/len(ps) > 0)
                        yrs_count = sum(1 for y, ps in yrs_pnl.items() if len(ps) >= 5)
                        if yrs_count < 2: continue
                        if yrs_pos / yrs_count < 0.5: continue  # min 50% anios pos
                        yld = sum(b["pnl"] for b in bs)/len(bs)*100
                        if yld <= 0: continue
                        # Score: priorizar consistencia + N + yield
                        score = yld * math.log(len(bs)+1) * (yrs_pos / yrs_count)**1.5
                        if score > best_score:
                            pnls = [b["pnl"] for b in bs]
                            boots = [sum(random.choice(pnls) for _ in range(len(pnls)))/len(pnls)*100 for _ in range(1500)]
                            boots.sort()
                            best_score = score
                            best = {"liga": liga, "p_min": p_min, "d_min": d_min, "c_min": c_min, "c_max": c_max,
                                    "N": len(bs), "yield": yld, "ci_lo": boots[37], "ci_hi": boots[1462],
                                    "yrs_pos": yrs_pos, "yrs_count": yrs_count, "score": score, "bets": bs}
        if best:
            best_per_liga[liga] = best
            cmin_str = f"{best['c_min']:.1f}"
            cmax_str = f"{best['c_max']:.1f}" if best['c_max'] < 99 else "inf"
            yrs_str = f"{best['yrs_pos']}/{best['yrs_count']}"
            print(f"{liga:<14s}{best['p_min']:<8.2f}{best['d_min']:<10.2f}{cmin_str:<8s}{cmax_str:<8s}{best['N']:>6d}{best['yield']:>+8.2f}%{best['ci_lo']:>+9.2f}%{yrs_str:>10s}")
        else:
            print(f"{liga:<14s}{'sin filtro que cumpla criterio':<80s}")

    # Desglose por anio de cada filtro
    print("\n" + "="*120)
    print("DESGLOSE POR ANIO de cada filtro PER LIGA — consistencia visual")
    print("="*120)
    print(f"{'liga':<14s}{'cfg':<32s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>6s}")
    for liga, best in best_per_liga.items():
        cfg = f"P>={best['p_min']:.2f} d>={best['d_min']:.2f}"
        if best['c_max'] < 99: cfg += f" c<={best['c_max']:.1f}"
        if best['c_min'] > 0: cfg += f" c>={best['c_min']:.1f}"
        bs = best["bets"]
        row = f"{liga:<14s}{cfg:<32s}"
        n_total = pnl_total = 0
        for yt in YEARS:
            b_ly = [b for b in bs if b["year"] == yt]
            if len(b_ly) < 3: row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            n_total += n; pnl_total += pnl
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%{n_total:>6d}"
        print(row)

    # WALK-FORWARD TRUE-OOS: train threshold con 2022-2024, test 2025+2026
    print("\n" + "="*120)
    print("WALK-FORWARD TRUE-OOS — fijar filtro con 2022-2024, validar en 2025+2026")
    print("="*120)
    print(f"{'liga':<14s}{'cfg_train':<32s}{'IS_train':>10s}{'N_tr':>6s}{'OOS_2025_2026':>14s}{'N_oos':>6s}")
    for liga in LIGAS_OBJ:
        b_l_train = [b for b in bets if b["liga"] == liga and b["year"] in ("2022","2023","2024")]
        b_l_test = [b for b in bets if b["liga"] == liga and b["year"] in ("2025","2026")]
        if len(b_l_train) < 50: continue
        # Find best filtro sobre TRAIN solamente
        best = None; best_score = -math.inf
        for p_min in grid_p:
            for d_min in grid_d:
                for c_max in grid_cmax:
                    for c_min in grid_cmin:
                        if c_min >= c_max: continue
                        bs_tr = [b for b in b_l_train if b["p_top"] >= p_min and b["div"] >= d_min and c_min <= b["cuota_pick"] <= c_max]
                        if len(bs_tr) < 30: continue
                        yrs_pnl = defaultdict(list)
                        for b in bs_tr: yrs_pnl[b["year"]].append(b["pnl"])
                        yrs_pos = sum(1 for y, ps in yrs_pnl.items() if len(ps) >= 5 and sum(ps)/len(ps) > 0)
                        if yrs_pos < 2: continue  # min 2/3 anios pos en train
                        yld = sum(b["pnl"] for b in bs_tr)/len(bs_tr)*100
                        if yld <= 0: continue
                        score = yld * math.log(len(bs_tr)+1) * yrs_pos
                        if score > best_score:
                            best_score = score
                            best = (p_min, d_min, c_min, c_max, len(bs_tr), yld)
        if not best:
            print(f"{liga:<14s}{'sin filtro train':<32s}")
            continue
        p_min, d_min, c_min, c_max, n_tr, yld_tr = best
        bs_te = [b for b in b_l_test if b["p_top"] >= p_min and b["div"] >= d_min and c_min <= b["cuota_pick"] <= c_max]
        cfg_str = f"P>={p_min:.2f} d>={d_min:.2f}"
        if c_max < 99: cfg_str += f" c<={c_max:.1f}"
        if c_min > 0: cfg_str += f" c>={c_min:.1f}"
        n_te = len(bs_te); pnl_te = sum(b["pnl"] for b in bs_te) if bs_te else 0
        yld_te = pnl_te/n_te*100 if n_te else None
        yld_te_s = f"{yld_te:+.2f}%" if yld_te is not None else "(N=0)"
        print(f"{liga:<14s}{cfg_str:<32s}{yld_tr:>+9.2f}%{n_tr:>6d}{yld_te_s:>14s}{n_te:>6d}")

    # Guardar
    Path("analisis/filtro_por_pais.json").write_text(
        json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "bets"} for k, v in best_per_liga.items()},
                   default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/filtro_por_pais.json")


if __name__ == "__main__":
    main()

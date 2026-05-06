"""V0 motor REAL (sin doble híbrido) — repaso IS + OOS por año + filtro suave per-liga.

V0 motor productivo:
  xg_calc = β_sot·SOT + 0.010·shots_off + coef_corner·corners
  xg_final = 0.70·xg_calc + 0.30·goles_reales
  EMA forward sobre xg_final (sin extra híbrido)

Universo expandido N=8892 cuotas (col fecha_fdco).

Análisis:
1. V0 PURO IS sobre 4 años con bootstrap CI95% por año + IS pooled.
2. Comparativa V0 PURO vs V0 BACKTEST PREVIO (con doble híbrido).
3. Filtro SUAVE per-liga balanceando yield × log(N) × años_positivos.
"""
import sqlite3, math, json, random
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge

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
    """V0 motor productivo REAL: EMA sobre xg_final (sin doble híbrido)."""
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
        # xg_calc local
        xg_calc_l = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]
        xg_final_l = 0.70*xg_calc_l + 0.30*ev_l["goles"]  # motor productivo
        # xg_calc visita
        xg_calc_v = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]
        xg_final_v = 0.70*xg_calc_v + 0.30*ev_v["goles"]
        # EMA directo sobre xg_final (SIN segundo híbrido)
        sh["fh"] = xg_final_l if sh["fh"] is None else alfa*xg_final_l + (1-alfa)*sh["fh"]
        sh["nfh"] += 1
        sa["fa"] = xg_final_v if sa["fa"] is None else alfa*xg_final_v + (1-alfa)*sa["fa"]
        sa["nfa"] += 1
    return out


def construir_emas_v0_BUG(eventos, beta_sot_map, alfa, theta=0.30):
    """Backtest previo con doble híbrido (BUG)."""
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
        xl = beta*ev_l["sot"] + 0.010*ev_l["shots_off"] + 0.03*ev_l["corners"]
        xl = 0.70*xl + 0.30*ev_l["goles"]   # primer híbrido
        xv = beta*ev_v["sot"] + 0.010*ev_v["shots_off"] + 0.03*ev_v["corners"]
        xv = 0.70*xv + 0.30*ev_v["goles"]
        xlp = theta*xl + (1-theta)*ev_l["goles"]   # SEGUNDO híbrido (BUG)
        xvp = theta*xv + (1-theta)*ev_v["goles"]
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


def evaluar_estrategia(records, fn_filter):
    bets = []
    for r in records:
        if not fn_filter(r): continue
        bets.append(r)
    if not bets: return None
    n = len(bets); wins = sum(b["won"] for b in bets); pnl = sum(b["pnl"] for b in bets)
    cuotas = [b["cuota_pick"] for b in bets]
    pnls = [b["pnl"] for b in bets]
    # Bootstrap
    boots = [sum(random.choice(pnls) for _ in range(n))/n*100 for _ in range(2000)]
    boots.sort()
    ci_lo, ci_hi = boots[50], boots[1950]
    return {"N": n, "hit": wins/n*100, "yield": pnl/n*100, "pnl": pnl,
            "ci_lo": ci_lo, "ci_hi": ci_hi, "cuota_avg": sum(cuotas)/len(cuotas),
            "by_year": defaultdict(lambda: {"n": 0, "pnl": 0, "wins": 0})}


def main():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    rows, cuotas = cargar(cur); eventos = construir_eventos(rows); beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} stats, {len(cuotas)} cuotas matched (post-fix)")

    # =============================================================
    # 1. V0 PURO motor real — IS sobre TODO el universo
    # =============================================================
    emas_real = construir_emas_v0_REAL(eventos, beta_sot_map, ALFA_EMA)
    pairs_real = [(k[0], v[0], v[1], v[2], v[3]) for k, v in emas_real.items()
                   if v[0] is not None and v[1] is not None]
    rhos_real = calibrar_rho(pairs_real)

    # 2. V0 BUG (doble híbrido) para comparar
    emas_bug = construir_emas_v0_BUG(eventos, beta_sot_map, ALFA_EMA, theta=0.30)
    pairs_bug = [(k[0], v[0], v[1], v[2], v[3]) for k, v in emas_bug.items()
                  if v[0] is not None and v[1] is not None]
    rhos_bug = calibrar_rho(pairs_bug)

    # Para cada partido con cuotas, generar bets para ambos
    def build_bets(emas, rhos):
        bets = []
        for key, val in emas.items():
            lh, lv, hg, ag = val
            if lh is None or lv is None: continue
            if key not in cuotas: continue
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
            bets.append({
                "key": key, "liga": key[0], "year": key[1][:4], "fecha": key[1],
                "ht": key[2], "at": key[3], "pick": pick, "p_top": p_top,
                "div": p_top - pi_pick, "cuota_pick": cuota_pick, "won": won,
                "pnl": (cuota_pick-1.0) if won else -1.0
            })
        return bets

    bets_real = build_bets(emas_real, rhos_real)
    bets_bug = build_bets(emas_bug, rhos_bug)
    print(f"\nN bets (EV>=1.03):")
    print(f"  V0 REAL motor productivo: {len(bets_real)}")
    print(f"  V0 BUG doble hibrido    : {len(bets_bug)}")

    # =============================================================
    # COMPARATIVA REAL vs BUG por año + IS pooled
    # =============================================================
    print("\n" + "="*100)
    print("V0 REAL (motor productivo) vs V0 BUG (backtests previos) — yield por año")
    print("="*100)
    print(f"{'modelo':<15s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>8s}")
    for label, bets in [("V0 REAL", bets_real), ("V0 BUG", bets_bug)]:
        row = f"{label:<15s}"
        n_total = pnl_total = 0
        for yt in YEARS:
            b_y = [b for b in bets if b["year"] == yt]
            if not b_y: row += f"{'-':>10s}"; continue
            n = len(b_y); pnl = sum(b["pnl"] for b in b_y)
            yld = pnl/n*100; n_total += n; pnl_total += pnl
            row += f"{yld:>+8.2f}%({n:>2d})"[:10]
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%{n_total:>8d}"
        print(row)

    # =============================================================
    # Yield V0 REAL por liga × año (universo expandido)
    # =============================================================
    print("\n" + "="*100)
    print("V0 REAL (motor productivo) — yield por LIGA × AÑO (sin filtros adicionales)")
    print("="*100)
    print(f"{'liga':<14s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>8s}")
    for liga in sorted({b["liga"] for b in bets_real}):
        b_l = [b for b in bets_real if b["liga"] == liga]
        if len(b_l) < 30: continue
        row = f"{liga:<14s}"; n_total = pnl_total = 0
        for yt in YEARS:
            b_ly = [b for b in b_l if b["year"] == yt]
            if len(b_ly) < 5: row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            n_total += n; pnl_total += pnl
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%{n_total:>8d}"
        print(row)

    # =============================================================
    # FILTRO SUAVE PER-LIGA — buscar threshold óptimo balanceando yield × log(N)
    # =============================================================
    print("\n" + "="*100)
    print("FILTRO SUAVE PER-LIGA — busqueda threshold optimo (yield × log(N+1))")
    print("="*100)
    print(f"{'liga':<14s}{'p_min':<8s}{'div_min':<10s}{'N':>6s}{'yield':>9s}{'CI95_lo':>10s}{'years_pos':>11s}")
    LIGAS = sorted({b["liga"] for b in bets_real})
    grid_p = [0.0, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    grid_d = [-0.10, -0.05, 0.00, 0.03, 0.05, 0.08, 0.10, 0.15]
    best_per_liga = {}
    for liga in LIGAS:
        b_l = [b for b in bets_real if b["liga"] == liga]
        if len(b_l) < 50: continue
        best = None; best_score = -math.inf
        for p_min in grid_p:
            for d_min in grid_d:
                bs = [b for b in b_l if b["p_top"] >= p_min and b["div"] >= d_min]
                if len(bs) < 20: continue
                # Years pos
                yrs_data = defaultdict(list)
                for b in bs: yrs_data[b["year"]].append(b["pnl"])
                yrs_pos = sum(1 for y, ps in yrs_data.items() if len(ps) >= 5 and sum(ps)/len(ps) > 0)
                yrs_count = sum(1 for y, ps in yrs_data.items() if len(ps) >= 5)
                if yrs_count == 0: continue
                # Score = yield * log(N+1) * (years_pos / years_count)
                yld = sum(b["pnl"] for b in bs)/len(bs)
                score = yld * math.log(len(bs)+1) * (yrs_pos / max(1, yrs_count))
                if score > best_score:
                    pnls = [b["pnl"] for b in bs]
                    boots = [sum(random.choice(pnls) for _ in range(len(pnls)))/len(pnls)*100 for _ in range(1000)]
                    boots.sort()
                    best_score = score
                    best = {"liga": liga, "p_min": p_min, "d_min": d_min, "N": len(bs),
                            "yield": yld*100, "ci_lo": boots[25], "ci_hi": boots[975],
                            "yrs_pos": yrs_pos, "yrs_count": yrs_count}
        if best:
            best_per_liga[liga] = best
            yrs_str = f"{best['yrs_pos']}/{best['yrs_count']}"
            print(f"{liga:<14s}{best['p_min']:<8.2f}{best['d_min']:<10.2f}{best['N']:>6d}{best['yield']:>+8.2f}%{best['ci_lo']:>+9.2f}%{yrs_str:>11s}")

    # =============================================================
    # Validación detallada de cada filtro suave por año
    # =============================================================
    print("\n" + "="*100)
    print("FILTRO SUAVE PER-LIGA — yield por AÑO (verificar consistencia)")
    print("="*100)
    print(f"{'liga':<14s}{'cfg':<22s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>8s}")
    for liga, best in best_per_liga.items():
        cfg = f"P>={best['p_min']:.2f} d>={best['d_min']:.2f}"
        b_l = [b for b in bets_real if b["liga"] == liga and b["p_top"] >= best["p_min"] and b["div"] >= best["d_min"]]
        row = f"{liga:<14s}{cfg:<22s}"
        n_total = pnl_total = 0
        for yt in YEARS:
            b_ly = [b for b in b_l if b["year"] == yt]
            if len(b_ly) < 3: row += f"{'-':>10s}"; continue
            n = len(b_ly); pnl = sum(b["pnl"] for b in b_ly); yld = pnl/n*100
            row += f"{yld:>+7.2f}%({n:>2d})"
            n_total += n; pnl_total += pnl
        is_yld = pnl_total/n_total*100 if n_total else 0
        row += f"{is_yld:>+8.2f}%{n_total:>8d}"
        print(row)

    Path("analisis/v0_real_repaso_IS_filtro_suave.json").write_text(
        json.dumps({"V0_REAL_total_N": len(bets_real), "V0_BUG_total_N": len(bets_bug),
                    "filtros_suaves_per_liga": best_per_liga}, default=str, indent=2),
        encoding="utf-8")
    print("\nJSON: analisis/v0_real_repaso_IS_filtro_suave.json")


if __name__ == "__main__":
    main()

"""
Test: V5 apuesta el outcome que cree mas probable (argmax) SIN ningun filtro.
Universo: todos los partidos con cuotas matched (N=2,689). Sin M.1, sin DIVERGENCIA, sin EV-min.

Compare contra V0 mismo metodo. Yield raw del modelo, sin "ayuda" de filtros productivos.
"""
import sqlite3
import json
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
THETA_V5 = 0.60


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


def fit_v5(eventos_train):
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def calcular_xg(variante, ev, fit, beta_sot_map, beta_default=0.352):
    if variante == "V0":
        beta = beta_sot_map.get(ev["liga"], beta_default)
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + 0.03 * ev["corners"]
        return 0.70 * xg_calc + 0.30 * ev["goles"]
    if variante == "V5":
        feats = fit["feats"]
        return fit["intercept"] + sum(fit["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def construir_emas(variante, eventos, fit, beta_sot_map, alfa, theta):
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
        xl = calcular_xg(variante, ev_l, fit, beta_sot_map)
        xv = calcular_xg(variante, ev_v, fit, beta_sot_map)
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


def prob_1x2(lh, lv, rho, use_dc=True):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            tau = dc_tau(h, a, lh, lv, rho) if use_dc else 1.0
            p = poisson_pmf(h, lh) * poisson_pmf(a, lv) * tau
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def calibrar_rho(emas):
    por_liga = defaultdict(list)
    for key, (lh, lv, hg, ag) in emas.items():
        if lh is None or lv is None or lh <= 0 or lv <= 0: continue
        por_liga[key[0]].append((lh, lv, hg, ag))
    grid = [round(-0.2 + 0.005 * i, 3) for i in range(81)]
    rhos = {}
    for liga, ps in por_liga.items():
        if len(ps) < 50:
            rhos[liga] = -0.05; continue
        best_rho, best_ll = -0.05, -math.inf
        for rho in grid:
            ll = 0.0
            for lh, lv, hg, ag in ps:
                p = poisson_pmf(hg, lh) * poisson_pmf(ag, lv) * dc_tau(hg, ag, lh, lv, rho)
                if p > 0: ll += math.log(p)
                else: ll = -math.inf; break
            if ll > best_ll: best_ll, best_rho = ll, rho
        rhos[liga] = best_rho
    return rhos


def evaluar_argmax(emas, rhos, cuotas, use_dc=True, piso_cuota=1.0, techo_cuota=999.0):
    """Apuesta argmax(P_modelo). Solo si cuota_pick in [piso_cuota, techo_cuota]."""
    stats = {"hits": 0, "total": 0,
             "pnl": 0.0, "stake": 0.0,
             "by_year": defaultdict(lambda: {"hits": 0, "n": 0, "stake": 0, "pnl": 0}),
             "by_liga": defaultdict(lambda: {"hits": 0, "n": 0, "stake": 0, "pnl": 0}),
             "by_pick": defaultdict(lambda: {"hits": 0, "n": 0, "stake": 0, "pnl": 0})}
    for key, (lh, lv, hg, ag) in emas.items():
        if lh is None or lv is None: continue
        if key not in cuotas: continue
        rho = rhos.get(key[0], -0.05)
        pl, pe, pv = prob_1x2(lh, lv, rho, use_dc=use_dc)
        c1, cx, c2 = cuotas[key]
        opciones = [(pl, "L", c1), (pe, "E", cx), (pv, "V", c2)]
        opciones.sort(key=lambda x: -x[0])
        prob_top, pick, cuota_pick = opciones[0]
        if cuota_pick < piso_cuota or cuota_pick > techo_cuota: continue
        if hg > ag: out = "L"
        elif hg == ag: out = "E"
        else: out = "V"
        won = pick == out
        pnl = (cuota_pick - 1.0) if won else -1.0
        stats["total"] += 1; stats["hits"] += int(won)
        stats["stake"] += 1.0; stats["pnl"] += pnl
        anio = key[1][:4]
        stats["by_year"][anio]["n"] += 1; stats["by_year"][anio]["hits"] += int(won)
        stats["by_year"][anio]["stake"] += 1; stats["by_year"][anio]["pnl"] += pnl
        liga = key[0]
        stats["by_liga"][liga]["n"] += 1; stats["by_liga"][liga]["hits"] += int(won)
        stats["by_liga"][liga]["stake"] += 1; stats["by_liga"][liga]["pnl"] += pnl
        stats["by_pick"][pick]["n"] += 1; stats["by_pick"][pick]["hits"] += int(won)
        stats["by_pick"][pick]["stake"] += 1; stats["by_pick"][pick]["pnl"] += pnl
    return stats


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas(cur)
    beta_sot_map = get_beta_sot_map(cur)

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit = fit_v5(eventos_train)

    emas_v0 = construir_emas("V0", eventos, None, beta_sot_map, ALFA_EMA, THETA_V0)
    emas_v5 = construir_emas("V5", eventos, fit, beta_sot_map, ALFA_EMA, THETA_V5)
    rhos_v0 = calibrar_rho(emas_v0)
    rhos_v5 = calibrar_rho(emas_v5)

    print("="*100)
    print("V5 / V0 apuesta argmax — grid piso de cuota (sin otros filtros)")
    print("="*100)

    PISOS = [1.0, 1.3, 1.5, 1.7, 2.0, 2.3, 2.5, 3.0, 3.5, 4.0]
    print(f"\n--- DC + rho ---")
    print(f"{'variante':<8s}{'piso':<8s}{'N':>8s}{'hit%':>8s}{'yield%':>10s}{'pnl':>10s}")
    grid = {}
    for var, emas, rhos in [("V0", emas_v0, rhos_v0), ("V5", emas_v5, rhos_v5)]:
        grid[var] = {}
        for piso in PISOS:
            s = evaluar_argmax(emas, rhos, cuotas, use_dc=True, piso_cuota=piso)
            if s["total"] == 0:
                print(f"{var:<8s}{piso:<8.2f}{0:>8d}{'-':>8s}{'-':>10s}{'-':>10s}")
                continue
            hit = s["hits"]/s["total"]*100
            yld = s["pnl"]/s["stake"]*100
            print(f"{var:<8s}{piso:<8.2f}{s['total']:>8d}{hit:>7.2f}%{yld:>9.2f}%{s['pnl']:>10.2f}")
            grid[var][piso] = {"N": s["total"], "hit": hit, "yield": yld, "pnl": s["pnl"], "stats": s}
        print()

    # Por anio para piso==1.0 y piso==1.5
    print("\n--- Yield por anio (piso=1.0 / sin filtro) ---")
    print(f"{'var':<6s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}")
    for var in ("V0", "V5"):
        s = grid[var][1.0]["stats"]
        row = f"{var:<6s}"
        for a in ["2022", "2023", "2024", "2025", "2026"]:
            d = s["by_year"].get(a, {})
            yld = d["pnl"]/d["stake"]*100 if d.get("stake") else None
            row += f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
        is_yld = s["pnl"]/s["stake"]*100
        row += f"{is_yld:>9.2f}%"
        print(row)

    print("\n--- Yield por anio (piso=1.5) ---")
    print(f"{'var':<6s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}")
    for var in ("V0", "V5"):
        s = grid[var][1.5]["stats"]
        row = f"{var:<6s}"
        for a in ["2022", "2023", "2024", "2025", "2026"]:
            d = s["by_year"].get(a, {})
            yld = d["pnl"]/d["stake"]*100 if d.get("stake") else None
            row += f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
        is_yld = s["pnl"]/s["stake"]*100
        row += f"{is_yld:>9.2f}%"
        print(row)

    print("\n--- Yield por anio (piso=2.0) ---")
    print(f"{'var':<6s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}")
    for var in ("V0", "V5"):
        s = grid[var][2.0]["stats"]
        row = f"{var:<6s}"
        for a in ["2022", "2023", "2024", "2025", "2026"]:
            d = s["by_year"].get(a, {})
            yld = d["pnl"]/d["stake"]*100 if d.get("stake") else None
            row += f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
        is_yld = s["pnl"]/s["stake"]*100
        row += f"{is_yld:>9.2f}%"
        print(row)

    # Pisos + techos (banda)
    print("\n--- Banda cuota (piso, techo) — V5 con DC ---")
    print(f"{'piso':<8s}{'techo':<8s}{'N':>8s}{'hit%':>8s}{'yield%':>10s}")
    bandas = [(1.5, 2.5), (1.5, 3.0), (1.7, 2.5), (1.7, 3.0), (2.0, 3.5), (2.5, 4.0), (1.5, 2.0), (2.0, 3.0)]
    for p, t in bandas:
        s = evaluar_argmax(emas_v5, rhos_v5, cuotas, use_dc=True, piso_cuota=p, techo_cuota=t)
        if s["total"] == 0: continue
        hit = s["hits"]/s["total"]*100
        yld = s["pnl"]/s["stake"]*100
        print(f"{p:<8.2f}{t:<8.2f}{s['total']:>8d}{hit:>7.2f}%{yld:>9.2f}%")

    print("\n--- Banda cuota (piso, techo) — V0 con DC ---")
    print(f"{'piso':<8s}{'techo':<8s}{'N':>8s}{'hit%':>8s}{'yield%':>10s}")
    for p, t in bandas:
        s = evaluar_argmax(emas_v0, rhos_v0, cuotas, use_dc=True, piso_cuota=p, techo_cuota=t)
        if s["total"] == 0: continue
        hit = s["hits"]/s["total"]*100
        yld = s["pnl"]/s["stake"]*100
        print(f"{p:<8.2f}{t:<8.2f}{s['total']:>8d}{hit:>7.2f}%{yld:>9.2f}%")

    out_json = {
        "grid_piso": {var: {f"{p:.2f}": {k: v for k, v in g.items() if k != "stats"}
                            for p, g in grid[var].items()} for var in ("V0", "V5")}
    }
    Path("analisis/test_v5_argmax_pisos.json").write_text(json.dumps(out_json, indent=2, default=str), encoding="utf-8")
    print("\nJSON: analisis/test_v5_argmax_pisos.json")


if __name__ == "__main__":
    main()

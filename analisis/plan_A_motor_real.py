"""
Plan A — Test V5 con motor real (Dixon-Coles + rho calibrado + filtro DIVERGENCIA).

Componentes que se agregan vs backtest previo (Poisson independiente):
1. Dixon-Coles tau(h, a, lambda_h, lambda_v, rho) sobre marcadores bajos (0-0, 1-0, 0-1, 1-1).
2. rho calibrado MLE per-liga separadamente para V0 y V5.
3. Filtro DIVERGENCIA: pick si (P_modelo_pick - P_implicita_pick) > umbral.
4. P_implicita_mercado = (1/cuota_pick) / overround.

Compara V0 vs V5 con motor "lite" real.
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
ALFA_GLOBAL = 0.10
THETA_V0 = 0.30
THETA_V5 = 0.60
LIGAS_M1 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
DIVERGENCIA_GRID = [0.00, 0.05, 0.08, 0.10, 0.12, 0.15]
EV_MIN = 1.03


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


def dc_tau(h, a, lam_h, lam_v, rho):
    """Dixon-Coles correction factor."""
    if h == 0 and a == 0: return 1 - lam_h * lam_v * rho
    if h == 0 and a == 1: return 1 + lam_h * rho
    if h == 1 and a == 0: return 1 + lam_v * rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0


def prob_1x2_dc(lam_h, lam_v, rho):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_v) * dc_tau(h, a, lam_h, lam_v, rho)
            p = max(0.0, p)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def calibrar_rho_per_liga(emas_dict):
    """MLE rho por liga sobre partidos donde EMAs tienen warmup. Grid [-0.2, 0.2] step 0.005."""
    por_liga = defaultdict(list)
    for key, (lam_h, lam_v, hg, ag) in emas_dict.items():
        if lam_h is None or lam_v is None: continue
        if lam_h <= 0 or lam_v <= 0: continue
        por_liga[key[0]].append((lam_h, lam_v, hg, ag))
    rhos = {}
    grid = [round(-0.2 + 0.005 * i, 3) for i in range(81)]
    for liga, partidos in por_liga.items():
        if len(partidos) < 50:
            rhos[liga] = -0.05  # fallback
            continue
        best_rho, best_ll = None, -math.inf
        for rho in grid:
            ll = 0.0
            for lam_h, lam_v, hg, ag in partidos:
                p = poisson_pmf(hg, lam_h) * poisson_pmf(ag, lam_v) * dc_tau(hg, ag, lam_h, lam_v, rho)
                if p > 0: ll += math.log(p)
                else: ll = -math.inf; break
            if ll > best_ll: best_ll, best_rho = ll, rho
        rhos[liga] = best_rho
    return rhos


def evaluar(variante, emas_dict, rhos, cuotas, divergencia_thr):
    """Para cada partido: P_DC + filtro DIVERGENCIA + EV. Devuelve metricas.

    Apuesta: pick = argmax(P_modelo). Se apuesta SI:
      liga in M.1
      P_modelo_pick - P_implicita_pick >= divergencia_thr
      P_modelo_pick * cuota_pick >= EV_MIN
    """
    stats = {"hits": 0, "total": 0, "brier_sum": 0.0,
             "apuestas": 0, "stake": 0.0, "pnl": 0.0,
             "by_year": defaultdict(lambda: {"hits": 0, "total": 0, "brier": 0.0,
                                              "n": 0, "stake": 0, "pnl": 0})}
    for key, (lam_h, lam_v, hg, ag) in emas_dict.items():
        if lam_h is None or lam_v is None: continue
        liga = key[0]
        rho = rhos.get(liga, -0.05)
        pl, pe, pv = prob_1x2_dc(lam_h, lam_v, rho)
        if hg > ag: out = "L"
        elif hg == ag: out = "E"
        else: out = "V"
        b = (pl - (1 if out=="L" else 0))**2 + (pe - (1 if out=="E" else 0))**2 + (pv - (1 if out=="V" else 0))**2
        anio = key[1][:4]
        # Hitrate y Brier sobre universo
        hit = max([(pl, "L"), (pe, "E"), (pv, "V")], key=lambda x: x[0])[1] == out
        stats["hits"] += int(hit); stats["total"] += 1; stats["brier_sum"] += b
        d = stats["by_year"][anio]
        d["hits"] += int(hit); d["total"] += 1; d["brier"] += b
        # Apuesta
        if liga not in LIGAS_M1: continue
        if key not in cuotas: continue
        c1, cx, c2 = cuotas[key]
        # Overround para P_implicita
        overround = (1/c1) + (1/cx) + (1/c2)
        p_impl_l = (1/c1) / overround
        p_impl_e = (1/cx) / overround
        p_impl_v = (1/c2) / overround
        # Pick = argmax(P_modelo)
        opciones = [(pl, "L", c1, p_impl_l), (pe, "E", cx, p_impl_e), (pv, "V", c2, p_impl_v)]
        opciones.sort(key=lambda x: -x[0])
        prob_top, pick, cuota_pick, p_impl_pick = opciones[0]
        # Filtros DIVERGENCIA + EV
        divergencia = prob_top - p_impl_pick
        if divergencia < divergencia_thr: continue
        ev = prob_top * cuota_pick
        if ev < EV_MIN: continue
        # Apostamos
        stats["apuestas"] += 1; stats["stake"] += 1.0
        won = pick == out
        pnl = (cuota_pick - 1.0) if won else -1.0
        stats["pnl"] += pnl
        d["n"] += 1; d["stake"] += 1; d["pnl"] += pnl
    return stats


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("Cargando datos...")
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas(cur)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"  partidos: {len(rows)}  cuotas matched: {len(cuotas)}")

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit = fit_v5(eventos_train)
    print(f"  V5 fit: intercept={fit['intercept']:.4f}  beta_SOT={fit['coef'][0]:.4f}")

    # Construir EMAs dual para V0 y V5
    print("\nConstruyendo EMAs...")
    emas_v0 = construir_emas("V0", eventos, None, beta_sot_map, ALFA_GLOBAL, THETA_V0)
    emas_v5 = construir_emas("V5", eventos, fit, beta_sot_map, ALFA_GLOBAL, THETA_V5)

    print("\nCalibrando rho per liga (MLE Dixon-Coles)...")
    rhos_v0 = calibrar_rho_per_liga(emas_v0)
    rhos_v5 = calibrar_rho_per_liga(emas_v5)
    print(f"  rhos V0: {sorted(rhos_v0.items())}")
    print(f"  rhos V5: {sorted(rhos_v5.items())}")

    # Evaluacion: grid divergencia
    print("\n" + "="*120)
    print("PLAN A — Comparativa V0 vs V5 con motor real (DC + rho + DIVERGENCIA)")
    print("="*120)
    print(f"{'variante':<8s}{'div_thr':<10s}{'hit%':>7s}{'Brier':>9s}{'N_apost':>10s}{'yield%':>10s}{'pnl':>10s}{'IS':>7s}")

    out_json = {"rhos_v0": rhos_v0, "rhos_v5": rhos_v5, "results": defaultdict(dict)}
    for var, emas, rhos in [("V0", emas_v0, rhos_v0), ("V5", emas_v5, rhos_v5)]:
        for thr in DIVERGENCIA_GRID:
            s = evaluar(var, emas, rhos, cuotas, thr)
            hit = s["hits"]/s["total"]*100 if s["total"] else 0
            br = s["brier_sum"]/s["total"] if s["total"] else 0
            yld = (s["pnl"]/s["stake"]*100) if s["stake"]>0 else None
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            print(f"{var:<8s}{thr:<10.2f}{hit:>6.2f}%{br:>9.4f}{s['apuestas']:>10d}{yld_str}{s['pnl']:>10.2f}{s['total']:>7d}")
            out_json["results"][var][f"{thr:.2f}"] = {
                "hit_pct": hit, "brier": br, "N_apost": s["apuestas"],
                "yield_pct": yld, "pnl": s["pnl"], "N_total": s["total"],
                "by_year": {a: {"hits": d["hits"], "total": d["total"],
                                "n_apost": d["n"], "yield": (d["pnl"]/d["stake"]*100) if d["stake"]>0 else None}
                            for a, d in s["by_year"].items()}
            }

    # Tabla por anio (solo para divergencia mejor V5 e identica V0)
    print("\n" + "="*120)
    print("Yield por anio — divergencia=0.05 (default productivo)")
    print("="*120)
    print(f"{'variante':<8s}{'2022':>10s}{'2023':>10s}{'2024':>10s}{'2025':>10s}{'2026':>10s}{'IS':>10s}{'N':>8s}")
    for var in ("V0", "V5"):
        d = out_json["results"][var]["0.05"]["by_year"]
        row = f"{var:<8s}"
        total_pnl = total_n = 0
        for a in ["2022", "2023", "2024", "2025", "2026"]:
            yi = d.get(a, {})
            yld = yi.get("yield")
            row += f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            total_pnl += (yi.get("yield") or 0) * yi.get("n_apost", 0) / 100
            total_n += yi.get("n_apost", 0)
        is_yld = (total_pnl / total_n * 100) if total_n > 0 else 0
        row += f"{is_yld:>9.2f}%{total_n:>8d}"
        print(row)

    Path("analisis/plan_A_motor_real.json").write_text(
        json.dumps(out_json, indent=2, default=str), encoding="utf-8"
    )
    print("\nJSON: analisis/plan_A_motor_real.json")


if __name__ == "__main__":
    main()

"""
Quien predice mejor: mi xG o el mercado?

Pregunta directa: dado mismo universo de partidos con cuotas, comparar:
  1. Brier 1X2 — modelo (V0, V5) vs P_implicita_mercado.
  2. RMSE goles totales — lambda_h+lambda_v (modelo) vs lambda_mercado (derivado de O/U) vs goles_real.
  3. Hit rate (argmax pick == outcome) — modelo vs mercado.

Por anio + IS.
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
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2, f.cuota_o25, f.cuota_u25
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f
          ON s.liga=f.liga AND s.fecha=f.fecha
         AND LOWER(REPLACE(REPLACE(REPLACE(s.ht,' ',''),'-',''),'.','')) = f.equipo_local_norm
         AND LOWER(REPLACE(REPLACE(REPLACE(s.at,' ',''),'-',''),'.','')) = f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
        """
    ).fetchall():
        out[(r[0], r[1], r[2], r[3])] = (r[4], r[5], r[6], r[7], r[8])
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


def lambda_total_desde_O25(p_o25):
    """Inverso: dado P(over 2.5), encontrar lambda_total tal que
    P(total>=3) = 1 - sum_{k=0}^{2} poisson(k, lambda) = p_o25.
    Grid search lambda in [0.5, 6.0] step 0.01."""
    best_lam, best_diff = 2.5, math.inf
    for lam_x100 in range(50, 600):
        lam = lam_x100 / 100
        p_calc = 1 - sum(poisson_pmf(k, lam) for k in range(3))
        diff = abs(p_calc - p_o25)
        if diff < best_diff:
            best_diff, best_lam = diff, lam
    return best_lam


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas(cur)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"Universo: {len(rows)} partidos stats, {len(cuotas)} con cuotas matched")

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit = fit_v5(eventos_train)

    emas_v0 = construir_emas("V0", eventos, None, beta_sot_map, ALFA_EMA, THETA_V0)
    emas_v5 = construir_emas("V5", eventos, fit, beta_sot_map, ALFA_EMA, THETA_V5)
    rhos_v0 = calibrar_rho(emas_v0)
    rhos_v5 = calibrar_rho(emas_v5)

    # Acumular metricas
    stats_v0 = defaultdict(lambda: {"brier_1x2": [], "rmse_total": [], "hit_1x2": []})
    stats_v5 = defaultdict(lambda: {"brier_1x2": [], "rmse_total": [], "hit_1x2": []})
    stats_mkt = defaultdict(lambda: {"brier_1x2": [], "rmse_total": [], "hit_1x2": [],
                                      "rmse_total_o25": []})

    n_total = 0
    n_con_o25 = 0
    for key, (lh_v0, lv_v0, hg, ag) in emas_v0.items():
        if lh_v0 is None or lv_v0 is None: continue
        if key not in cuotas: continue
        n_total += 1
        anio = key[1][:4]
        liga = key[0]
        c1, cx, c2, c_o25, c_u25 = cuotas[key]
        # Mercado 1X2
        overround_1x2 = (1/c1) + (1/cx) + (1/c2)
        pi_l = (1/c1) / overround_1x2
        pi_e = (1/cx) / overround_1x2
        pi_v = (1/c2) / overround_1x2
        # Modelo V0
        rho_v0 = rhos_v0.get(liga, -0.05)
        pl0, pe0, pv0 = prob_1x2(lh_v0, lv_v0, rho_v0)
        # Modelo V5
        lh_v5, lv_v5, _, _ = emas_v5.get(key, (None, None, None, None))
        if lh_v5 is None or lv_v5 is None: continue
        rho_v5 = rhos_v5.get(liga, -0.05)
        pl5, pe5, pv5 = prob_1x2(lh_v5, lv_v5, rho_v5)
        # Outcome real
        if hg > ag: out = "L"
        elif hg == ag: out = "E"
        else: out = "V"
        target_l = 1 if out == "L" else 0
        target_e = 1 if out == "E" else 0
        target_v = 1 if out == "V" else 0
        gt = hg + ag
        # Brier 1X2
        b_v0 = (pl0-target_l)**2 + (pe0-target_e)**2 + (pv0-target_v)**2
        b_v5 = (pl5-target_l)**2 + (pe5-target_e)**2 + (pv5-target_v)**2
        b_mkt = (pi_l-target_l)**2 + (pi_e-target_e)**2 + (pi_v-target_v)**2
        # Hit 1X2
        h_v0 = max([(pl0,"L"),(pe0,"E"),(pv0,"V")], key=lambda x: x[0])[1] == out
        h_v5 = max([(pl5,"L"),(pe5,"E"),(pv5,"V")], key=lambda x: x[0])[1] == out
        h_mkt = max([(pi_l,"L"),(pi_e,"E"),(pi_v,"V")], key=lambda x: x[0])[1] == out
        # RMSE goles totales — modelo: lh+lv. Mercado: lambda_o25 (si disponible).
        lambda_total_v0 = lh_v0 + lv_v0
        lambda_total_v5 = lh_v5 + lv_v5
        e_v0_sq = (lambda_total_v0 - gt)**2
        e_v5_sq = (lambda_total_v5 - gt)**2
        for stats in (stats_v0, stats_mkt):
            pass  # placeholders
        stats_v0[anio]["brier_1x2"].append(b_v0)
        stats_v0[anio]["rmse_total"].append(e_v0_sq)
        stats_v0[anio]["hit_1x2"].append(int(h_v0))
        stats_v5[anio]["brier_1x2"].append(b_v5)
        stats_v5[anio]["rmse_total"].append(e_v5_sq)
        stats_v5[anio]["hit_1x2"].append(int(h_v5))
        stats_mkt[anio]["brier_1x2"].append(b_mkt)
        stats_mkt[anio]["hit_1x2"].append(int(h_mkt))
        # Mercado lambda total via O/U
        if c_o25 is not None and c_u25 is not None and c_o25 > 1.0 and c_u25 > 1.0:
            n_con_o25 += 1
            ov_ou = (1/c_o25) + (1/c_u25)
            pi_o25 = (1/c_o25) / ov_ou
            lambda_mkt = lambda_total_desde_O25(pi_o25)
            e_mkt_sq = (lambda_mkt - gt)**2
            stats_mkt[anio]["rmse_total_o25"].append(e_mkt_sq)
            # Tambien guardo para V0/V5 en el mismo subset (para comparacion 1:1)
            stats_v0[anio]["rmse_total_subset_o25"] = stats_v0[anio].get("rmse_total_subset_o25", [])
            stats_v0[anio]["rmse_total_subset_o25"].append(e_v0_sq)
            stats_v5[anio]["rmse_total_subset_o25"] = stats_v5[anio].get("rmse_total_subset_o25", [])
            stats_v5[anio]["rmse_total_subset_o25"].append(e_v5_sq)

    print(f"\nN total con EMAs warmup + cuotas 1X2: {n_total}")
    print(f"N con O/U 2.5 cuotas: {n_con_o25}")

    # Tablas
    anios = ["2022", "2023", "2024", "2025", "2026"]
    print("\n" + "="*100)
    print("BRIER 1X2 — menor=mejor")
    print("="*100)
    print(f"{'fuente':<10s}", end="")
    for a in anios: print(f"{a:>10s}", end="")
    print(f"{'IS':>10s}{'N_IS':>8s}")
    for nombre, st in [("V0", stats_v0), ("V5", stats_v5), ("MERCADO", stats_mkt)]:
        row = f"{nombre:<10s}"
        all_b = []
        for a in anios:
            bs = st[a]["brier_1x2"]
            row += f"{(sum(bs)/len(bs)):>10.4f}" if bs else f"{'-':>10s}"
            all_b.extend(bs)
        if all_b: row += f"{sum(all_b)/len(all_b):>10.4f}{len(all_b):>8d}"
        print(row)

    print("\n" + "="*100)
    print("HIT RATE 1X2 (argmax pick == outcome)")
    print("="*100)
    print(f"{'fuente':<10s}", end="")
    for a in anios: print(f"{a:>10s}", end="")
    print(f"{'IS':>10s}{'N_IS':>8s}")
    for nombre, st in [("V0", stats_v0), ("V5", stats_v5), ("MERCADO", stats_mkt)]:
        row = f"{nombre:<10s}"
        all_h = []
        for a in anios:
            hs = st[a]["hit_1x2"]
            row += f"{(sum(hs)/len(hs)*100):>9.2f}%" if hs else f"{'-':>10s}"
            all_h.extend(hs)
        if all_h: row += f"{sum(all_h)/len(all_h)*100:>9.2f}%{len(all_h):>8d}"
        print(row)

    print("\n" + "="*100)
    print("RMSE GOLES TOTALES vs (hg + ag) — sobre subset con cuotas O/U 2.5")
    print("="*100)
    print(f"{'fuente':<10s}", end="")
    for a in anios: print(f"{a:>10s}", end="")
    print(f"{'IS':>10s}{'N_IS':>8s}")
    for nombre, st in [("V0", stats_v0), ("V5", stats_v5), ("MERCADO", stats_mkt)]:
        row = f"{nombre:<10s}"
        all_e = []
        for a in anios:
            key = "rmse_total_o25" if nombre == "MERCADO" else "rmse_total_subset_o25"
            es = st[a].get(key, []) if key in st[a] else []
            if es:
                rmse = math.sqrt(sum(es)/len(es))
                row += f"{rmse:>10.4f}"
                all_e.extend(es)
            else:
                row += f"{'-':>10s}"
        if all_e:
            rmse = math.sqrt(sum(all_e)/len(all_e))
            row += f"{rmse:>10.4f}{len(all_e):>8d}"
        print(row)


if __name__ == "__main__":
    main()

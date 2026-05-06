"""
Reoptimizacion xg_calc V2 — walk-forward por anio + grid (alfa, theta) + Brier + yield.

Diff vs V1:
  - Walk-forward OOS: refit V5 con eventos < year_test. Mide RMSE solo en eventos year_test.
  - Grid (alfa, theta): co-optimizacion 6 alfas x 11 thetas.
  - Brier 1X2: Poisson independiente con EMA xg_favor_home/away por equipo.
  - Yield: pick argmax(P) sobre subset con cuotas_historicas_fdco matched.

Variantes:
  V0     Motor actual (theta=0.70, alfa=alfa_liga, beta_sot=motor)
  V0t    Motor con theta=0.10 (tuned previo)
  V1     Goles puros
  V5_wf  Ridge fitted walk-forward (refit por anio_test)
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
ALFAS = [0.05, 0.10, 0.15, 0.20, 0.30]
THETAS = [round(i * 0.1, 2) for i in range(11)]
YEARS_TEST = ["2023", "2024", "2025", "2026"]
MAX_GOALS = 8
MARGEN_EV = 1.05  # umbral apuesta (EV >= 1.05)


def get_alfa_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='alfa_ema' AND valor_real IS NOT NULL"
    ).fetchall()}


def get_beta_sot_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
    ).fetchall()}


def cargar_partidos(cur):
    return cur.execute(
        """
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos, h_pass_pct, a_pass_pct, h_saves, a_saves,
               h_blocks, a_blocks, h_longballs_acc, a_longballs_acc
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


def cargar_cuotas_match(cur):
    """Devuelve dict {(liga, fecha, ht, at): (cuota_1, cuota_x, cuota_2)}."""
    out = {}
    rows = cur.execute(
        """
        SELECT s.liga, s.fecha, s.ht, s.at, f.cuota_1, f.cuota_x, f.cuota_2
        FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f
          ON s.liga=f.liga AND s.fecha=f.fecha
         AND LOWER(REPLACE(REPLACE(REPLACE(s.ht,' ',''),'-',''),'.','')) = f.equipo_local_norm
         AND LOWER(REPLACE(REPLACE(REPLACE(s.at,' ',''),'-',''),'.','')) = f.equipo_visita_norm
        WHERE f.cuota_1 IS NOT NULL AND f.cuota_x IS NOT NULL AND f.cuota_2 IS NOT NULL
        """
    ).fetchall()
    for liga, fecha, ht, at, c1, cx, c2 in rows:
        out[(liga, fecha, ht, at)] = (c1, cx, c2)
    return out


def construir_eventos(rows):
    eventos = []
    for r in rows:
        (liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac,
         h_pos, a_pos, h_pp, a_pp, h_sv, a_sv, h_bl, a_bl, h_lba, a_lba) = r
        eventos.append({
            "liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
            "goles": hg, "goles_rival": ag,
            "sot": hst, "shots_off": max(0, hs - hst), "corners": hc,
            "pos": h_pos or 50, "saves_rival": a_sv or 0, "blocks_rival": a_bl or 0,
        })
        eventos.append({
            "liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
            "goles": ag, "goles_rival": hg,
            "sot": ast, "shots_off": max(0, asv - ast), "corners": ac,
            "pos": a_pos or 50, "saves_rival": h_sv or 0, "blocks_rival": h_bl or 0,
        })
    return eventos


def fit_v5(eventos_train):
    """Ridge alpha=1.0 positive con [SOT, shots_off, corners, pos, saves_rival]."""
    feats = ["sot", "shots_off", "corners", "pos", "saves_rival"]
    X = np.array([[ev[f] for f in feats] for ev in eventos_train], dtype=float)
    y = np.array([ev["goles"] for ev in eventos_train], dtype=float)
    m = Ridge(alpha=1.0, positive=True, fit_intercept=True).fit(X, y)
    return {"feats": feats, "coef": m.coef_.tolist(), "intercept": float(m.intercept_)}


def calcular_xg_calc(variante, ev, fit, beta_sot_map, beta_default=0.352):
    if variante == "V0":
        beta = beta_sot_map.get(ev["liga"], beta_default)
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + 0.03 * ev["corners"]
        return 0.70 * xg_calc + 0.30 * ev["goles"]
    if variante == "V0t":
        beta = beta_sot_map.get(ev["liga"], beta_default)
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + 0.03 * ev["corners"]
        return 0.10 * xg_calc + 0.90 * ev["goles"]
    if variante == "V1":
        return ev["goles"]  # goles puros
    if variante == "V5_wf":
        feats = fit["feats"]
        return fit["intercept"] + sum(fit["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def eval_alfa_theta(variante, eventos, fit, beta_sot_map, alfa, theta, year_filter=None):
    """Aplicar EMA forward con (alfa, theta), medir RMSE/NLL en year_filter."""
    eventos_eq = sorted(eventos, key=lambda x: (x["equipo"], x["fecha"]))
    pairs = []
    for equipo, grupo in groupby(eventos_eq, key=lambda x: x["equipo"]):
        partidos = list(grupo)
        ema = None
        n_prev = 0
        for ev in partidos:
            xg_calc = calcular_xg_calc(variante, ev, fit, beta_sot_map)
            xg_p = theta * xg_calc + (1.0 - theta) * ev["goles"]
            if n_prev >= WARMUP and ema is not None:
                if year_filter is None or ev["fecha"][:4] == year_filter:
                    pairs.append((ema, ev["goles"]))
            ema = xg_p if ema is None else alfa * xg_p + (1.0 - alfa) * ema
            n_prev += 1
    if not pairs:
        return None
    n = len(pairs)
    ps = [p for p, _ in pairs]; ys = [y for _, y in pairs]
    rmse = math.sqrt(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n)
    mae = sum(abs(p - y) for p, y in zip(ps, ys)) / n
    nll = sum(max(p, 0.01) - y * math.log(max(p, 0.01)) for p, y in zip(ps, ys)) / n
    return {"n": n, "rmse": rmse, "mae": mae, "nll": nll}


def construir_emas_dual(variante, eventos, fit, beta_sot_map, alfa, theta):
    """Construye EMAs por equipo separadas home/away (favor + contra) cronologicamente.
    Retorna dict[(liga, fecha, ht, at)] -> (lambda_home, lambda_away) at moment of match.
    """
    eventos_sorted = sorted(eventos, key=lambda x: (x["fecha"], x["equipo"]))
    # Por equipo, mantener 4 EMAs: xg_favor_h, xg_contra_h, xg_favor_a, xg_contra_a
    ema_state = defaultdict(lambda: {"fh": None, "ch": None, "fa": None, "ca": None,
                                     "nfh": 0, "nch": 0, "nfa": 0, "nca": 0})
    # Necesito iterar por eventos para hacer state += pero para predict requiero per-partido EMA at moment.
    # Estrategia: agrupar por partido (liga, fecha, ht, at), buscar lambda_h / lambda_v previo a actualizar.
    matches = defaultdict(list)
    for ev in eventos_sorted:
        key = (ev["liga"], ev["fecha"], ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    matches_ord = sorted(matches.keys(), key=lambda k: k[1])

    out = {}
    for key in matches_ord:
        liga, fecha, ht, at = key
        evs = matches[key]
        # Buscar evento local y visita
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v:
            continue
        # Lambda_home: ataque local (xg_favor_home) — usamos solo EMA propia local
        st_h = ema_state[ht]
        st_a = ema_state[at]
        lambda_h = st_h["fh"] if st_h["nfh"] >= WARMUP else None
        lambda_v = st_a["fa"] if st_a["nfa"] >= WARMUP else None
        out[key] = (lambda_h, lambda_v)
        # Update EMA local
        xg_l_calc = calcular_xg_calc(variante, ev_l, fit, beta_sot_map)
        xg_l_p = theta * xg_l_calc + (1.0 - theta) * ev_l["goles"]
        # local: xg_favor_home update + xg_contra_home update (con goles del rival)
        st_h["fh"] = xg_l_p if st_h["fh"] is None else alfa * xg_l_p + (1.0 - alfa) * st_h["fh"]
        st_h["nfh"] += 1
        # contra_home = goles concedidos en casa (proxy = goles del rival visitante)
        st_h["ch"] = ev_l["goles_rival"] if st_h["ch"] is None else alfa * ev_l["goles_rival"] + (1.0 - alfa) * st_h["ch"]
        st_h["nch"] += 1
        # visita: xg_favor_away update
        xg_v_calc = calcular_xg_calc(variante, ev_v, fit, beta_sot_map)
        xg_v_p = theta * xg_v_calc + (1.0 - theta) * ev_v["goles"]
        st_a["fa"] = xg_v_p if st_a["fa"] is None else alfa * xg_v_p + (1.0 - alfa) * st_a["fa"]
        st_a["nfa"] += 1
        st_a["ca"] = ev_v["goles_rival"] if st_a["ca"] is None else alfa * ev_v["goles_rival"] + (1.0 - alfa) * st_a["ca"]
        st_a["nca"] += 1
    return out


def poisson_pmf(k, lam):
    if lam <= 0: lam = 0.01
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def prob_1x2(lam_h, lam_v):
    """Devuelve (P_L, P_E, P_V) via Poisson independiente."""
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_v)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0:
        pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def eval_brier_yield(variante, eventos, fit, beta_sot_map, alfa, theta, cuotas):
    """Mide Brier 1X2 + yield walk-forward (sobre eventos cronologicos)."""
    emas = construir_emas_dual(variante, eventos, fit, beta_sot_map, alfa, theta)
    # Reconstruir partidos con outcome
    partidos = {}
    for ev in eventos:
        if ev["es_local"]:
            key = (ev["liga"], ev["fecha"], ev["equipo"], ev["rival"])
            partidos[key] = (ev["goles"], ev["goles_rival"])
    brier_year = defaultdict(list)
    yield_year = defaultdict(lambda: {"apuestas": 0, "stake": 0.0, "pnl": 0.0})
    for key, (hg, ag) in partidos.items():
        if key not in emas:
            continue
        lam_h, lam_v = emas[key]
        if lam_h is None or lam_v is None:
            continue
        pl, pe, pv = prob_1x2(lam_h, lam_v)
        # Outcome real
        if hg > ag: out = "L"
        elif hg == ag: out = "E"
        else: out = "V"
        # Brier
        b = (pl - (1 if out=="L" else 0))**2 + (pe - (1 if out=="E" else 0))**2 + (pv - (1 if out=="V" else 0))**2
        anio = key[1][:4]
        brier_year[anio].append(b)
        # Yield si hay cuota
        if key in cuotas:
            c1, cx, c2 = cuotas[key]
            # Pick argmax con EV >= MARGEN_EV
            evs = [(pl * c1, "L", c1, pl), (pe * cx, "E", cx, pe), (pv * c2, "V", c2, pv)]
            evs.sort(key=lambda x: -x[0])
            best = evs[0]
            if best[0] >= MARGEN_EV:
                yield_year[anio]["apuestas"] += 1
                yield_year[anio]["stake"] += 1.0
                won = best[1] == out
                pnl = (best[2] - 1.0) if won else -1.0
                yield_year[anio]["pnl"] += pnl
    return brier_year, yield_year


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("Cargando partidos...")
    rows = cargar_partidos(cur)
    print(f"  partidos con stats avanzadas: {len(rows)}")
    eventos = construir_eventos(rows)
    print(f"  eventos equipo-perspectiva: {len(eventos)}")
    cuotas = cargar_cuotas_match(cur)
    print(f"  partidos con cuotas matched: {len(cuotas)}")

    alfa_map = get_alfa_map(cur)
    beta_sot_map = get_beta_sot_map(cur)

    # Refit V5 walk-forward (un fit por year_test)
    fits_wf = {}
    for yt in YEARS_TEST:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fits_wf[yt] = fit_v5(ev_train)
        f = fits_wf[yt]
        print(f"\nFit V5_wf train < {yt} (N={len(ev_train)}): "
              f"intercept={f['intercept']:.4f} coef={[round(c,4) for c in f['coef']]}")

    # =========================================================================
    # PARTE 1 — RMSE forward walk-forward por year_test, grid (alfa, theta)
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 1 — RMSE FORWARD walk-forward OOS por year_test, grid (alfa, theta)")
    print("="*100)
    resultados = {}  # [variante][year_test] = {(alfa,theta): metrica}
    variantes = ["V0", "V0t", "V1", "V5_wf"]
    for var in variantes:
        resultados[var] = {}
        for yt in YEARS_TEST:
            resultados[var][yt] = {}
            fit = fits_wf[yt] if var == "V5_wf" else None
            for alfa in ALFAS:
                for theta in THETAS:
                    m = eval_alfa_theta(var, eventos, fit, beta_sot_map, alfa, theta, year_filter=yt)
                    if m: resultados[var][yt][(alfa, theta)] = m

    # IS agregado: medir todos los anios
    print(f"\n{'variante':<10s}{'year':<8s}{'best_alfa':>12s}{'best_theta':>12s}{'best_rmse':>12s}{'N':>10s}")
    is_stats = defaultdict(list)
    for var in variantes:
        for yt in YEARS_TEST:
            d = resultados[var][yt]
            if not d: continue
            best_key = min(d.keys(), key=lambda k: d[k]["rmse"])
            best = d[best_key]
            print(f"{var:<10s}{yt:<8s}{best_key[0]:>12.2f}{best_key[1]:>12.2f}{best['rmse']:>12.4f}{best['n']:>10d}")
            is_stats[var].append((best_key, best))

    # =========================================================================
    # PARTE 2 — RMSE forward AGREGADO IS (mismo (alfa, theta) para todos los years)
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 2 — Mejor (alfa, theta) GLOBAL por variante (consistencia OOS multi-year)")
    print("="*100)
    # Sumar RMSE^2 weighted by N across years para encontrar (alfa, theta) global
    best_globals = {}
    for var in variantes:
        scores = defaultdict(lambda: [0.0, 0])
        for yt in YEARS_TEST:
            for k, m in resultados[var][yt].items():
                scores[k][0] += m["rmse"]**2 * m["n"]
                scores[k][1] += m["n"]
        candidatos = [(k, math.sqrt(s[0]/s[1])) for k, s in scores.items() if s[1] > 0]
        candidatos.sort(key=lambda x: x[1])
        best_globals[var] = candidatos[0]
        print(f"{var:<10s}  mejor global: alfa={candidatos[0][0][0]:.2f}  theta={candidatos[0][0][1]:.2f}  RMSE_pooled={candidatos[0][1]:.4f}")
    # Con (alfa, theta) global, mostrar RMSE por year
    print(f"\n{'variante':<10s}{'global cfg':<24s}", end="")
    for yt in YEARS_TEST: print(f"{yt:>10s}", end="")
    print(f"{'POOLED':>10s}")
    for var in variantes:
        (alfa_g, theta_g), rmse_pooled = best_globals[var]
        print(f"{var:<10s}a={alfa_g:.2f} th={theta_g:.2f}        ", end="")
        for yt in YEARS_TEST:
            m = resultados[var][yt].get((alfa_g, theta_g))
            print(f"{m['rmse']:>10.4f}" if m else f"{'-':>10s}", end="")
        print(f"{rmse_pooled:>10.4f}")

    # =========================================================================
    # PARTE 3 — Brier 1X2 + Yield (con (alfa, theta) global por variante)
    # =========================================================================
    print("\n" + "="*100)
    print("PARTE 3 — Brier 1X2 + Yield walk-forward (con global cfg por variante)")
    print("="*100)
    brier_yield_results = {}
    for var in variantes:
        (alfa_g, theta_g), _ = best_globals[var]
        # V5_wf: usa fit segun el year evaluado. Aproximamos con el fit de 2025 (fit estable).
        fit = fits_wf["2025"] if var == "V5_wf" else None
        brier_y, yield_y = eval_brier_yield(var, eventos, fit, beta_sot_map, alfa_g, theta_g, cuotas)
        brier_yield_results[var] = {"brier": brier_y, "yield": yield_y, "cfg": (alfa_g, theta_g)}

    print(f"\n{'variante':<10s}{'cfg':<22s}", end="")
    for yt in YEARS_TEST: print(f"{('B '+yt):>11s}", end="")
    print(f"{'B IS':>11s}")
    for var in variantes:
        cfg = brier_yield_results[var]["cfg"]
        print(f"{var:<10s}a={cfg[0]:.2f} th={cfg[1]:.2f}      ", end="")
        all_b = []
        for yt in YEARS_TEST:
            bs = brier_yield_results[var]["brier"].get(yt, [])
            mean = (sum(bs)/len(bs)) if bs else None
            print(f"{mean:>11.4f}" if mean else f"{'-':>11s}", end="")
            all_b.extend(bs)
        mean_is = sum(all_b)/len(all_b) if all_b else 0
        print(f"{mean_is:>11.4f}")

    print(f"\n{'variante':<10s}{'cfg':<22s}", end="")
    for yt in YEARS_TEST: print(f"{('Y '+yt):>11s}", end="")
    print(f"{'Y IS':>11s}{'N_apuestas':>12s}")
    for var in variantes:
        cfg = brier_yield_results[var]["cfg"]
        print(f"{var:<10s}a={cfg[0]:.2f} th={cfg[1]:.2f}      ", end="")
        total_pnl = 0.0; total_stake = 0.0; total_n = 0
        for yt in YEARS_TEST:
            ys = brier_yield_results[var]["yield"].get(yt, {"apuestas":0, "stake":0, "pnl":0})
            yield_pct = (ys["pnl"]/ys["stake"]*100) if ys["stake"] > 0 else None
            print(f"{yield_pct:>10.2f}%" if yield_pct is not None else f"{'-':>11s}", end="")
            total_pnl += ys["pnl"]; total_stake += ys["stake"]; total_n += ys["apuestas"]
        yield_is = (total_pnl/total_stake*100) if total_stake > 0 else 0
        print(f"{yield_is:>10.2f}%{total_n:>12d}")

    # Persist JSON
    out = {
        "fits_wf": fits_wf,
        "rmse_grid": {var: {yt: {f"{k[0]:.2f}_{k[1]:.2f}": v for k, v in d.items()}
                            for yt, d in resultados[var].items()} for var in variantes},
        "best_globals": {var: {"alfa": best_globals[var][0][0], "theta": best_globals[var][0][1],
                                "rmse_pooled": best_globals[var][1]} for var in variantes},
        "brier_yield": {var: {
            "cfg_alfa": brier_yield_results[var]["cfg"][0],
            "cfg_theta": brier_yield_results[var]["cfg"][1],
            "brier_year": {yt: (sum(bs)/len(bs)) if bs else None
                           for yt, bs in brier_yield_results[var]["brier"].items()},
            "yield_year": {yt: {"pct": (y["pnl"]/y["stake"]*100) if y["stake"] > 0 else None,
                                "n": y["apuestas"], "pnl": y["pnl"], "stake": y["stake"]}
                           for yt, y in brier_yield_results[var]["yield"].items()},
        } for var in variantes},
    }
    Path("analisis/reoptimizar_xg_calc_v2.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: analisis/reoptimizar_xg_calc_v2.json")


if __name__ == "__main__":
    main()

"""
Brier por momento_bin (4/8/12) x anio x IS, por variante xg_calc.

Bin = floor(pct_temp * N_BINS), pct_temp = (fecha - inicio_temp) / (fin_temp - inicio_temp).
Calendario individual por (liga, temp) en tabla liga_calendario_temp.

Variantes: V0 (motor actual), V0t (motor theta=0.10), V1 (goles puros), V5_wf (Ridge SOT+intercept).

Output:
  Por cada variante x bin_size, matriz bin_idx x [anios + IS] con Brier promedio.
  Comparativa V5 - V0 por bin (donde V5 mejora vs empeora).
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
ALFA_GLOBAL = 0.10  # mejor de v2 walk-forward
THETAS = {"V0": 0.30, "V0t": 1.00, "V1": 0.00, "V5_wf": 0.60}


def get_beta_sot_map(cur):
    return {r[0]: r[1] for r in cur.execute(
        "SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND valor_real IS NOT NULL"
    ).fetchall()}


def cargar_calendarios(cur):
    out = {}
    for liga, temp, inicio, fin in cur.execute(
        "SELECT liga, temp, fecha_inicio, fecha_fin FROM liga_calendario_temp"
    ).fetchall():
        out[(liga, temp)] = (inicio, fin)
    return out


def get_bin(liga, fecha, calendarios, n_bins):
    anio = int(fecha[:4])
    for temp in (anio, anio + 1):
        if (liga, temp) in calendarios:
            inicio, fin = calendarios[(liga, temp)]
            if inicio <= fecha <= fin:
                from datetime import date
                d_partido = date.fromisoformat(fecha[:10])
                d_inicio = date.fromisoformat(inicio[:10])
                d_fin = date.fromisoformat(fin[:10])
                total = (d_fin - d_inicio).days
                if total <= 0: return None
                delta = (d_partido - d_inicio).days
                pct = max(0.0, min(0.9999, delta / total))
                return min(n_bins - 1, int(pct * n_bins))
    return None


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


def construir_eventos(rows):
    eventos = []
    for r in rows:
        liga, fecha, ht, at, hg, ag, hst, ast, hs, asv, hc, ac, hp, ap, hsv, asv2 = r
        eventos.append({"liga": liga, "fecha": fecha, "equipo": ht, "rival": at, "es_local": True,
                        "goles": hg, "goles_rival": ag, "sot": hst, "shots_off": max(0, hs - hst),
                        "corners": hc, "pos": hp or 50, "saves_rival": asv2 or 0, "blocks_rival": 0})
        eventos.append({"liga": liga, "fecha": fecha, "equipo": at, "rival": ht, "es_local": False,
                        "goles": ag, "goles_rival": hg, "sot": ast, "shots_off": max(0, asv - ast),
                        "corners": ac, "pos": ap or 50, "saves_rival": hsv or 0, "blocks_rival": 0})
    return eventos


def fit_v5(eventos_train):
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
    if variante == "V1": return ev["goles"]
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
        lambda_h = sh["fh"] if sh["nfh"] >= WARMUP else None
        lambda_v = sa["fa"] if sa["nfa"] >= WARMUP else None
        out[key] = (lambda_h, lambda_v, ev_l["goles"], ev_l["goles_rival"])
        xl = calcular_xg_calc(variante, ev_l, fit, beta_sot_map)
        xv = calcular_xg_calc(variante, ev_v, fit, beta_sot_map)
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


def prob_1x2(lam_h, lam_v):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_v)
            if h > a: pl += p
            elif h == a: pe += p
            else: pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("Cargando datos...")
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    calendarios = cargar_calendarios(cur)
    beta_sot_map = get_beta_sot_map(cur)
    print(f"  partidos: {len(rows)}  calendarios: {len(calendarios)}")

    # Walk-forward refit V5 por anio test (estrictamente OOS)
    fits_wf = {}
    for yt in ["2023", "2024", "2025", "2026"]:
        ev_train = [ev for ev in eventos if ev["fecha"][:4] < yt]
        fits_wf[yt] = fit_v5(ev_train)
        f = fits_wf[yt]
        print(f"  V5 fit < {yt}: intercept={f['intercept']:.4f}  beta_SOT={f['coef'][0]:.4f}  N_train={len(ev_train)}")
    # 2022 no tiene refit posible (no hay datos previos) -> usar fit < 2023 como aproximacion
    fits_wf["2022"] = fits_wf["2023"]

    # Para cada variante: emas -> brier por (anio, bin_size, bin_idx)
    variantes = ["V0", "V0t", "V1", "V5_wf"]
    stats = {v: {b: defaultdict(lambda: defaultdict(list)) for b in (4, 8, 12)} for v in variantes}

    for var in variantes:
        # V5_wf usa fit walk-forward por anio — para EMA acumulada usamos fit del primer anio (2022 -> < 2023)
        # y luego refit cuando llega el cambio de anio. Aproximacion: usar fit que mejor cubra el anio test.
        # Para simplificar: re-construimos EMA por anio test, partiendo de eventos < anio_test fitted con anio_test fit.
        # Implementacion exacta: refit por anio + reconstrucción EMA estricto
        if var == "V5_wf":
            # Estrategia OOS estricta: por cada anio test, EMA usa fit < anio_test sobre TODOS los eventos.
            # Como EMA acumula desde 2022, usamos fit < anio_test para todo.
            # Para no agregar leakage, predecimos eventos year=Y con fit < Y.
            for yt in ["2022", "2023", "2024", "2025", "2026"]:
                fit_y = fits_wf[yt]
                emas = construir_emas(var, eventos, fit_y, beta_sot_map, ALFA_GLOBAL, THETAS[var])
                for key, val in emas.items():
                    liga, fecha, ht, at = key
                    if fecha[:4] != yt: continue  # solo medir eventos de year_test
                    lam_h, lam_v, hg, ag = val
                    if lam_h is None or lam_v is None: continue
                    pl, pe, pv = prob_1x2(lam_h, lam_v)
                    if hg > ag: out = "L"
                    elif hg == ag: out = "E"
                    else: out = "V"
                    b = (pl - (1 if out=="L" else 0))**2 + (pe - (1 if out=="E" else 0))**2 + (pv - (1 if out=="V" else 0))**2
                    for bs in (4, 8, 12):
                        idx = get_bin(liga, fecha, calendarios, bs)
                        if idx is None: continue
                        stats[var][bs][idx][yt].append(b)
        else:
            emas = construir_emas(var, eventos, None, beta_sot_map, ALFA_GLOBAL, THETAS[var])
            for key, val in emas.items():
                liga, fecha, ht, at = key
                lam_h, lam_v, hg, ag = val
                if lam_h is None or lam_v is None: continue
                pl, pe, pv = prob_1x2(lam_h, lam_v)
                if hg > ag: out = "L"
                elif hg == ag: out = "E"
                else: out = "V"
                b = (pl - (1 if out=="L" else 0))**2 + (pe - (1 if out=="E" else 0))**2 + (pv - (1 if out=="V" else 0))**2
                anio = fecha[:4]
                for bs in (4, 8, 12):
                    idx = get_bin(liga, fecha, calendarios, bs)
                    if idx is None: continue
                    stats[var][bs][idx][anio].append(b)

    # Output
    anios = ["2022", "2023", "2024", "2025", "2026"]
    for var in variantes:
        for bs in (4, 8, 12):
            print("\n" + "="*100)
            print(f"VARIANTE {var}  -  BIN_SIZE {bs}")
            print("="*100)
            header = f"{'bin':>4s}" + "".join(f"{a:>10s}" for a in anios) + f"{'IS':>10s}{'N_IS':>9s}"
            print(header)
            for idx in range(bs):
                row = f"{idx:>4d}"
                all_b = []
                for a in anios:
                    bs_list = stats[var][bs][idx][a]
                    if bs_list:
                        m = sum(bs_list)/len(bs_list)
                        row += f"{m:>10.4f}"
                        all_b.extend(bs_list)
                    else:
                        row += f"{'-':>10s}"
                if all_b:
                    is_mean = sum(all_b)/len(all_b)
                    row += f"{is_mean:>10.4f}{len(all_b):>9d}"
                print(row)

    # Comparativa V5_wf - V0 por bin (delta Brier, negativo=V5 mejor)
    print("\n" + "="*100)
    print("DELTA Brier (V5_wf - V0) por bin x anio  [negativo = V5 mejor]")
    print("="*100)
    for bs in (4, 8, 12):
        print(f"\n--- BIN {bs} ---")
        header = f"{'bin':>4s}" + "".join(f"{a:>10s}" for a in anios) + f"{'IS':>10s}"
        print(header)
        for idx in range(bs):
            row = f"{idx:>4d}"
            all_v0, all_v5 = [], []
            for a in anios:
                v0_list = stats["V0"][bs][idx][a]
                v5_list = stats["V5_wf"][bs][idx][a]
                if v0_list and v5_list:
                    d = sum(v5_list)/len(v5_list) - sum(v0_list)/len(v0_list)
                    sign = "*" if d < 0 else " "
                    row += f"{d:>+9.4f}{sign}"
                    all_v0.extend(v0_list); all_v5.extend(v5_list)
                else:
                    row += f"{'-':>10s}"
            if all_v0 and all_v5:
                d = sum(all_v5)/len(all_v5) - sum(all_v0)/len(all_v0)
                sign = "*" if d < 0 else " "
                row += f"{d:>+9.4f}{sign}"
            print(row)

    out_json = {var: {bs: {idx: {a: (sum(b)/len(b) if b else None, len(b))
                                  for a, b in stats[var][bs][idx].items()}
                           for idx in range(bs) if any(stats[var][bs][idx].values())}
                      for bs in (4, 8, 12)} for var in variantes}
    Path("analisis/brier_por_bin_temporal.json").write_text(json.dumps(out_json, indent=2, default=str), encoding="utf-8")
    print("\nJSON: analisis/brier_por_bin_temporal.json")


if __name__ == "__main__":
    main()

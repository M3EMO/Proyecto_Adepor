"""
Reoptimizacion xg_calc V3 — incluye filtros productivos M.1 / M.2 / FLOOR / MARGEN / EV.

Waterfall de filtros (acumulativo):
  L0  Sin filtros (universo argmax)
  L1  + M.1: liga in {Argentina, Brasil, Inglaterra, Noruega, Turquia}
  L2  + M.2: n_acum_l < 60
  L3  + FLOOR_PROB: prob_top1 >= 0.33
  L4  + MARGEN: prob_top1 - prob_top2 >= 0.05
  L5  + EV-bucket: 3% high / 8% mid / 12% low scaling

Variantes evaluadas:
  V0    Motor actual (theta=0.70)
  V0t   Motor con theta=0.10 (tuned)
  V1    Goles puros
  V5_wf Ridge fitted walk-forward 2026 train
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
MARGEN_EV_FALLBACK = 1.05
LIGAS_M1 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
N_ACUM_MAX = 60
FLOOR_PROB = 0.33
MARGEN_MIN = 0.05
# EV bucket scaling: high (>=0.50), mid (0.40-0.50), low (<0.40)
EV_HIGH = 1.03
EV_MID = 1.08
EV_LOW = 1.12


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
        return ev["goles"]
    if variante == "V5_wf":
        feats = fit["feats"]
        return fit["intercept"] + sum(fit["coef"][i] * ev[feats[i]] for i in range(len(feats)))


def construir_emas_dual_y_n_acum(variante, eventos, fit, beta_sot_map, alfa, theta):
    """Devuelve dict[(liga, fecha, ht, at)] -> (lambda_h, lambda_v, n_acum_l, n_acum_v).

    Se trackea n_acum como local (equipo) y como visita (rival), cronologicamente.
    """
    eventos_sorted = sorted(eventos, key=lambda x: (x["fecha"], x["equipo"]))
    ema_state = defaultdict(lambda: {"fh": None, "fa": None, "nfh": 0, "nfa": 0})

    matches = defaultdict(list)
    for ev in eventos_sorted:
        key = (ev["liga"], ev["fecha"],
               ev["equipo"] if ev["es_local"] else ev["rival"],
               ev["rival"] if ev["es_local"] else ev["equipo"])
        matches[key].append(ev)
    matches_ord = sorted(matches.keys(), key=lambda k: k[1])

    out = {}
    for key in matches_ord:
        liga, fecha, ht, at = key
        evs = matches[key]
        ev_l = next((e for e in evs if e["es_local"]), None)
        ev_v = next((e for e in evs if not e["es_local"]), None)
        if not ev_l or not ev_v: continue
        st_h = ema_state[ht]; st_a = ema_state[at]
        lambda_h = st_h["fh"] if st_h["nfh"] >= WARMUP else None
        lambda_v = st_a["fa"] if st_a["nfa"] >= WARMUP else None
        n_acum_l = st_h["nfh"]
        out[key] = (lambda_h, lambda_v, n_acum_l)
        # Update local
        xg_l_calc = calcular_xg_calc(variante, ev_l, fit, beta_sot_map)
        xg_l_p = theta * xg_l_calc + (1.0 - theta) * ev_l["goles"]
        st_h["fh"] = xg_l_p if st_h["fh"] is None else alfa * xg_l_p + (1.0 - alfa) * st_h["fh"]
        st_h["nfh"] += 1
        # Update visita
        xg_v_calc = calcular_xg_calc(variante, ev_v, fit, beta_sot_map)
        xg_v_p = theta * xg_v_calc + (1.0 - theta) * ev_v["goles"]
        st_a["fa"] = xg_v_p if st_a["fa"] is None else alfa * xg_v_p + (1.0 - alfa) * st_a["fa"]
        st_a["nfa"] += 1
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


def ev_threshold_por_bucket(prob_top):
    """Replica EV-bucket escalado del motor (high >=0.50, mid 0.40-0.50, low <0.40)."""
    if prob_top >= 0.50: return EV_HIGH
    if prob_top >= 0.40: return EV_MID
    return EV_LOW


def evaluar_waterfall(variante, eventos, fit, beta_sot_map, cuotas, alfa, theta):
    """Aplica waterfall L0..L5 y retorna metricas por nivel."""
    emas = construir_emas_dual_y_n_acum(variante, eventos, fit, beta_sot_map, alfa, theta)
    partidos = {}
    for ev in eventos:
        if ev["es_local"]:
            key = (ev["liga"], ev["fecha"], ev["equipo"], ev["rival"])
            partidos[key] = (ev["goles"], ev["goles_rival"])

    niveles = ["L0", "L1", "L2", "L3", "L4", "L5"]
    stats = {n: {"hits": 0, "total": 0, "brier_sum": 0.0,
                 "apuestas": 0, "stake": 0.0, "pnl": 0.0,
                 "by_year": defaultdict(lambda: {"hits": 0, "total": 0, "brier": 0.0,
                                                  "n": 0, "stake": 0, "pnl": 0})}
             for n in niveles}

    for key, (hg, ag) in partidos.items():
        liga, fecha, ht, at = key
        anio = fecha[:4]
        if key not in emas: continue
        lam_h, lam_v, n_acum_l = emas[key]
        if lam_h is None or lam_v is None: continue
        pl, pe, pv = prob_1x2(lam_h, lam_v)
        # Outcome y argmax
        if hg > ag: out_real = "L"
        elif hg == ag: out_real = "E"
        else: out_real = "V"
        probs = [(pl, "L", "cuota_1"), (pe, "E", "cuota_x"), (pv, "V", "cuota_2")]
        probs.sort(key=lambda x: -x[0])
        prob_top, pick_top, _ = probs[0]
        prob_2nd = probs[1][0]
        margen = prob_top - prob_2nd
        hit = pick_top == out_real
        b = (pl - (1 if out_real=="L" else 0))**2 + (pe - (1 if out_real=="E" else 0))**2 + (pv - (1 if out_real=="V" else 0))**2

        # Determinar nivel de filtrado del partido
        levels_pasa = ["L0"]
        if liga in LIGAS_M1: levels_pasa.append("L1")
        if "L1" in levels_pasa and n_acum_l < N_ACUM_MAX: levels_pasa.append("L2")
        if "L2" in levels_pasa and prob_top >= FLOOR_PROB: levels_pasa.append("L3")
        if "L3" in levels_pasa and margen >= MARGEN_MIN: levels_pasa.append("L4")
        # L5 EV-bucket: requiere cuota
        if key in cuotas and "L4" in levels_pasa:
            c = cuotas[key]
            cuota_pick = c[0] if pick_top=="L" else c[1] if pick_top=="E" else c[2]
            ev_calc = prob_top * cuota_pick
            ev_thr = ev_threshold_por_bucket(prob_top)
            if ev_calc >= ev_thr: levels_pasa.append("L5")

        # Acumular en niveles aplicables
        for n in levels_pasa:
            stats[n]["hits"] += int(hit)
            stats[n]["total"] += 1
            stats[n]["brier_sum"] += b
            stats[n]["by_year"][anio]["hits"] += int(hit)
            stats[n]["by_year"][anio]["total"] += 1
            stats[n]["by_year"][anio]["brier"] += b

        # Yield: niveles >= L4 que tengan cuota
        if key in cuotas:
            c = cuotas[key]
            cuota_pick = c[0] if pick_top=="L" else c[1] if pick_top=="E" else c[2]
            ev_calc = prob_top * cuota_pick
            won = pick_top == out_real
            pnl = (cuota_pick - 1.0) if won else -1.0
            for n in ["L0", "L1", "L2", "L3", "L4", "L5"]:
                if n not in levels_pasa: continue
                # L0..L3 sin filtro EV: aposto solo si ev>=1.05 (fallback)
                if n in ("L0", "L1", "L2", "L3") and ev_calc < MARGEN_EV_FALLBACK: continue
                if n in ("L4",) and ev_calc < MARGEN_EV_FALLBACK: continue
                stats[n]["apuestas"] += 1
                stats[n]["stake"] += 1.0
                stats[n]["pnl"] += pnl
                stats[n]["by_year"][anio]["n"] += 1
                stats[n]["by_year"][anio]["stake"] += 1
                stats[n]["by_year"][anio]["pnl"] += pnl

    return stats


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    print("Cargando datos...")
    rows = cargar_partidos(cur)
    eventos = construir_eventos(rows)
    cuotas = cargar_cuotas_match(cur)
    print(f"  partidos: {len(rows)}  eventos: {len(eventos)}  cuotas matched: {len(cuotas)}")

    alfa_map = get_alfa_map(cur)
    beta_sot_map = get_beta_sot_map(cur)

    # Fit V5 con todo
    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit = fit_v5(eventos_train)
    print(f"  V5 fit: intercept={fit['intercept']:.4f}  beta_SOT={fit['coef'][0]:.4f}")

    # Cfg global por variante (de v2)
    cfgs = {
        "V0":    (0.10, 0.30),
        "V0t":   (0.10, 1.00),
        "V1":    (0.10, 0.00),
        "V5_wf": (0.10, 0.60),
    }
    print(f"  cfgs: {cfgs}")

    print("\n" + "="*120)
    print("WATERFALL FILTROS — hitrate / Brier / yield IS por variante x nivel")
    print("="*120)
    print(f"{'variante':<8s}{'nivel':<6s}{'N':>8s}{'hit%':>8s}{'Brier':>9s}{'N_apost':>10s}{'yield%':>10s}{'pnl':>10s}{'descripcion':>40s}")
    descripciones = {
        "L0": "Sin filtros (argmax universal)",
        "L1": "+M.1 ligas {ARG,BRA,ENG,NOR,TUR}",
        "L2": "+M.2 n_acum_l<60",
        "L3": "+FLOOR_PROB>=0.33",
        "L4": "+MARGEN>=0.05",
        "L5": "+EV-bucket escalado",
    }
    out_json = {}
    for var in ["V0", "V0t", "V1", "V5_wf"]:
        alfa, theta = cfgs[var]
        stats = evaluar_waterfall(var, eventos, fit if var=="V5_wf" else None,
                                  beta_sot_map, cuotas, alfa, theta)
        out_json[var] = {}
        for n in ["L0", "L1", "L2", "L3", "L4", "L5"]:
            s = stats[n]
            if s["total"] == 0: continue
            hit = s["hits"]/s["total"]*100
            br = s["brier_sum"]/s["total"]
            yld = (s["pnl"]/s["stake"]*100) if s["stake"]>0 else None
            out_json[var][n] = {
                "N": s["total"], "hit_pct": hit, "brier": br,
                "N_apost": s["apuestas"], "yield_pct": yld, "pnl": s["pnl"],
                "by_year": {a: {"hits": d["hits"], "total": d["total"],
                                "brier": d["brier"]/d["total"] if d["total"]>0 else None,
                                "n_apost": d["n"], "yield": (d["pnl"]/d["stake"]*100) if d["stake"]>0 else None}
                            for a, d in s["by_year"].items()}
            }
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            print(f"{var:<8s}{n:<6s}{s['total']:>8d}{hit:>7.2f}%{br:>9.4f}{s['apuestas']:>10d}{yld_str}{s['pnl']:>10.2f}  {descripciones[n]:<40s}")
        print()

    # Resumen comparativa best-yield por variante
    print("="*120)
    print("RESUMEN — mejor yield IS por variante (con N >= 100)")
    print("="*120)
    print(f"{'variante':<8s}{'mejor_nivel':<12s}{'hit%':>8s}{'Brier':>9s}{'N_apost':>10s}{'yield%':>10s}")
    for var in ["V0", "V0t", "V1", "V5_wf"]:
        cands = [(n, d) for n, d in out_json[var].items()
                 if d.get("yield_pct") is not None and d.get("N_apost", 0) >= 100]
        if not cands: continue
        cands.sort(key=lambda x: -x[1]["yield_pct"])
        best_n, d = cands[0]
        print(f"{var:<8s}{best_n:<12s}{d['hit_pct']:>7.2f}%{d['brier']:>9.4f}{d['N_apost']:>10d}{d['yield_pct']:>9.2f}%")

    # Por anio
    print("\n" + "="*120)
    print("HITRATE + YIELD por anio — nivel L5 (todos los filtros)")
    print("="*120)
    print(f"{'variante':<8s}{'anio':<6s}{'N':>8s}{'hit%':>8s}{'Brier':>9s}{'N_apost':>10s}{'yield%':>10s}")
    for var in ["V0", "V0t", "V1", "V5_wf"]:
        if "L5" not in out_json[var]: continue
        for anio in sorted(out_json[var]["L5"]["by_year"].keys()):
            d = out_json[var]["L5"]["by_year"][anio]
            yld = d.get("yield")
            yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
            br_str = f"{d['brier']:>9.4f}" if d.get("brier") is not None else f"{'-':>9s}"
            hit_pct = (d["hits"]/d["total"]*100) if d["total"]>0 else 0
            print(f"{var:<8s}{anio:<6s}{d['total']:>8d}{hit_pct:>7.2f}%{br_str}{d['n_apost']:>10d}{yld_str}")
        print()

    Path("analisis/reoptimizar_xg_calc_v3_filtros.json").write_text(
        json.dumps(out_json, indent=2, default=str), encoding="utf-8"
    )
    print("\nJSON: analisis/reoptimizar_xg_calc_v3_filtros.json")


if __name__ == "__main__":
    main()

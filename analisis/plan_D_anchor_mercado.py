"""
Plan D — 2-Stage anchor a mercado.

Stage 1: P_modelo = V5(stats) con DC + rho.
Stage 2: P_apuesta = alpha * P_modelo + (1-alpha) * P_implicita_mercado.

Hipotesis: shrinkage hacia mercado en zona ambigua aumenta N apostable + filtra
picks marginales agresivos. Si P_modelo es genuino edge, anchor preserva direccion
pero atenua magnitud -> EV check anchored es mas conservador.

Logica:
  Pick = argmax(P_modelo)
  Divergencia(pick) = P_modelo[pick] - P_implicita[pick] >= div_thr
  EV_anchored = P_apuesta[pick] * cuota_pick >= EV_MIN
  Si AMBOS pasan -> apostar.

Grid:
  alpha in [0.0, 0.1, ..., 1.0]
  div_thr in [0.00, 0.05, 0.10, 0.15]

Compare contra Plan A (alpha=1.0, V5 puro).
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
LIGAS_M1 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
EV_MIN = 1.03
ALPHAS = [round(i*0.1, 1) for i in range(11)]
DIV_THRS = [0.00, 0.05, 0.10, 0.15]


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


def evaluar(emas, rhos, cuotas, alpha, div_thr):
    """Eval con anchor. Pick=argmax(P_modelo). Anchor solo afecta EV check."""
    stats = {"apuestas": 0, "stake": 0.0, "pnl": 0.0,
             "by_year": defaultdict(lambda: {"n": 0, "stake": 0, "pnl": 0})}
    for key, (lh, lv, hg, ag) in emas.items():
        if lh is None or lv is None: continue
        liga = key[0]
        if liga not in LIGAS_M1: continue
        if key not in cuotas: continue
        rho = rhos.get(liga, -0.05)
        pl, pe, pv = prob_1x2_dc(lh, lv, rho)
        c1, cx, c2 = cuotas[key]
        overround = (1/c1) + (1/cx) + (1/c2)
        pi_l = (1/c1) / overround
        pi_e = (1/cx) / overround
        pi_v = (1/c2) / overround
        # P_apuesta anchored
        pa_l = alpha * pl + (1 - alpha) * pi_l
        pa_e = alpha * pe + (1 - alpha) * pi_e
        pa_v = alpha * pv + (1 - alpha) * pi_v
        # Pick = argmax(P_modelo) (Stage 1)
        opciones_modelo = [(pl, "L", c1, pi_l, pa_l), (pe, "E", cx, pi_e, pa_e), (pv, "V", c2, pi_v, pa_v)]
        opciones_modelo.sort(key=lambda x: -x[0])
        prob_top, pick, cuota_pick, pi_pick, pa_pick = opciones_modelo[0]
        # Filtros
        divergencia = prob_top - pi_pick
        if divergencia < div_thr: continue
        ev_anchored = pa_pick * cuota_pick
        if ev_anchored < EV_MIN: continue
        # Apostamos
        if hg > ag: out = "L"
        elif hg == ag: out = "E"
        else: out = "V"
        stats["apuestas"] += 1; stats["stake"] += 1.0
        won = pick == out
        pnl = (cuota_pick - 1.0) if won else -1.0
        stats["pnl"] += pnl
        d = stats["by_year"][key[1][:4]]
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
    print(f"  partidos: {len(rows)}  cuotas: {len(cuotas)}")

    eventos_train = [ev for ev in eventos if ev["fecha"][:4] < "2026"]
    fit = fit_v5(eventos_train)
    print(f"  V5 fit: intercept={fit['intercept']:.4f}  beta_SOT={fit['coef'][0]:.4f}")

    print("\nConstruyendo EMAs + calibrando rho...")
    emas_v0 = construir_emas("V0", eventos, None, beta_sot_map, ALFA_EMA, THETA_V0)
    emas_v5 = construir_emas("V5", eventos, fit, beta_sot_map, ALFA_EMA, THETA_V5)
    rhos_v0 = calibrar_rho(emas_v0)
    rhos_v5 = calibrar_rho(emas_v5)

    print("\n" + "="*120)
    print("PLAN D — Anchor a mercado, V5 vs V0")
    print("="*120)
    print(f"{'variante':<8s}{'div_thr':<10s}{'alpha':<8s}{'N_apost':>10s}{'yield%':>10s}{'pnl':>10s}")
    out_json = defaultdict(lambda: defaultdict(dict))
    for var, emas, rhos in [("V0", emas_v0, rhos_v0), ("V5", emas_v5, rhos_v5)]:
        for div_thr in DIV_THRS:
            for alpha in ALPHAS:
                s = evaluar(emas, rhos, cuotas, alpha, div_thr)
                yld = (s["pnl"]/s["stake"]*100) if s["stake"]>0 else None
                yld_str = f"{yld:>9.2f}%" if yld is not None else f"{'-':>10s}"
                print(f"{var:<8s}{div_thr:<10.2f}{alpha:<8.1f}{s['apuestas']:>10d}{yld_str}{s['pnl']:>10.2f}")
                out_json[var][f"div={div_thr:.2f}"][f"alpha={alpha:.1f}"] = {
                    "N_apost": s["apuestas"], "yield_pct": yld, "pnl": s["pnl"],
                    "by_year": {a: {"n": d["n"], "yield": (d["pnl"]/d["stake"]*100) if d["stake"]>0 else None}
                                for a, d in s["by_year"].items()}
                }
            print()

    # Mejor (alpha, div) por variante (con N >= 100)
    print("\n" + "="*120)
    print("RESUMEN — mejor anchor (alpha, div_thr) con N >= 100")
    print("="*120)
    print(f"{'variante':<8s}{'div_thr':<10s}{'alpha':<8s}{'N':>8s}{'yield%':>10s}")
    for var in ("V0", "V5"):
        cands = []
        for dk, alphas in out_json[var].items():
            for ak, d in alphas.items():
                if d["yield_pct"] is not None and d["N_apost"] >= 100:
                    cands.append((dk, ak, d["N_apost"], d["yield_pct"]))
        cands.sort(key=lambda x: -x[3])
        for dk, ak, n, y in cands[:5]:
            print(f"{var:<8s}{dk:<10s}{ak:<8s}{n:>8d}{y:>9.2f}%")
        print()

    Path("analisis/plan_D_anchor_mercado.json").write_text(
        json.dumps(out_json, indent=2, default=str), encoding="utf-8"
    )
    print("\nJSON: analisis/plan_D_anchor_mercado.json")


if __name__ == "__main__":
    main()

"""adepor-3ip Analisis V0 vs V13 por momento_bin sobre season 2026 in-progress.

Pregunta usuario: separar 2026 por Q y hacer el mismo analisis OOS pero sobre
in-sample REAL 2026, RECORDANDO que las mediciones varian por season (cada season
tiene su propio rango temporal).

DOS METODOS de momento_bin para 2026:
  A. IN-PROGRESS: pct = (fecha_pick - min_observado_2026_liga) /
                          (max_observado_2026_liga - min_observado_2026_liga)
     Usa el rango observado en historial_equipos_stats. Subestima la duracion
     real (no sabemos cuando termina la temp), todo se concentra en bins
     cercanos al maximo observado.
  B. CALENDARIO TIPICO: pct = (fecha_pick - season_start_typical) /
                                (season_end_typical - season_start_typical)
     Usa duraciones tipicas por liga (EUR top = ago-may ~280d, LATAM Apertura
     mar-jun ~90d, Brasileirao abr-dic ~270d, etc.).

Output:
  - Yield V0 vs V13 por bin (Q1-Q4) con cada metodo.
  - Tabla por liga: Argentina + Inglaterra (TOP-5 V5.1 + V13 elegibles).
  - Resto V13 elegibles (Francia/Italia) en SHADOW (no en TOP-5).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Backtest_Modelo.xlsx"
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "v0_v13_2026_por_q.json"

RHO_FALLBACK = -0.09

# Calendario typical por liga (datetime.date)
# 2025-26: EUR top ago 2025 -> may 2026 (estamos a fines)
# 2026: LATAM Apertura mar-jun, Brasileirao/Eliteserien arranque
SEASON_CAL = {
    # Liga: (inicio_typical_de_la_season_actual, fin_typical)
    "Inglaterra":  (date(2025, 8, 16), date(2026, 5, 24)),    # Premier 25-26
    "Italia":      (date(2025, 8, 17), date(2026, 5, 24)),    # Serie A 25-26
    "Espana":      (date(2025, 8, 15), date(2026, 5, 24)),    # La Liga 25-26
    "Francia":     (date(2025, 8, 15), date(2026, 5, 17)),    # Ligue 1 25-26
    "Alemania":    (date(2025, 8, 22), date(2026, 5, 16)),    # Bundesliga 25-26
    "Turquia":     (date(2025, 8, 8),  date(2026, 5, 24)),    # Super Lig 25-26
    "Argentina":   (date(2026, 3, 14), date(2026, 6, 22)),    # Apertura 2026 (~100d)
    "Brasil":      (date(2026, 3, 29), date(2026, 12, 21)),   # Brasileirao 2026 (~268d)
    "Noruega":     (date(2026, 3, 28), date(2026, 11, 30)),   # Eliteserien 2026 (~248d)
    "Chile":       (date(2026, 1, 25), date(2026, 12, 6)),    # Primera Division
    "Colombia":    (date(2026, 1, 24), date(2026, 6, 1)),     # Apertura Colombia
    "Peru":        (date(2026, 2, 7),  date(2026, 11, 8)),    # Liga 1
    "Ecuador":     (date(2026, 2, 14), date(2026, 12, 8)),    # LigaPro
    "Bolivia":     (date(2026, 2, 1),  date(2026, 11, 30)),
    "Uruguay":     (date(2026, 2, 8),  date(2026, 12, 8)),
    "Venezuela":   (date(2026, 1, 25), date(2026, 11, 8)),
}


# ===== V13 BEST por liga (post grid extended) =====
BEST = {
    "Argentina":  {"feat": "F5_ratio", "reg": "NNLS"},
    "Francia":    {"feat": "F4_disc",  "reg": "RIDGE"},
    "Inglaterra": {"feat": "F5_ratio", "reg": "NNLS"},
    "Italia":     {"feat": "F2_pos",   "reg": "RIDGE"},
}


def parse_fecha(s):
    if not s: return None
    try: return datetime.strptime(str(s), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        try: return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError): return None


def cargar_picks_reales():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None: continue
        fecha = parse_fecha(row[0])
        if fecha is None: continue
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"): continue
        partido = row[1] or ""
        local, visita = None, None
        for sep in [" vs ", " - ", " v ", "-"]:
            if sep in partido:
                parts = partido.split(sep, 1)
                if len(parts) == 2:
                    local, visita = parts[0].strip(), parts[1].strip()
                    break
        picks.append({
            "fecha": fecha, "fecha_str": fecha.isoformat(),
            "local": local, "visita": visita,
            "liga": row[2], "pick": row[3], "cuota": float(row[4] or 0),
            "camino": row[5], "resultado": resultado,
            "stake": float(row[8] or 0), "pl": float(row[9] or 0),
        })
    return picks


def momento_bin_in_progress(fecha, liga, picks_liga):
    """Bin via rango observado de la liga 2026."""
    fechas_liga = [p["fecha"] for p in picks_liga if p["liga"] == liga]
    if not fechas_liga: return None
    f_min, f_max = min(fechas_liga), max(fechas_liga)
    if f_max <= f_min: return None
    pct = (fecha - f_min).days / (f_max - f_min).days
    pct = max(0.0, min(1.0, pct))
    if pct < 0.25: return 0
    elif pct < 0.50: return 1
    elif pct < 0.75: return 2
    else: return 3


def momento_bin_typical(fecha, liga):
    """Bin via calendario tipico (mas realista)."""
    cal = SEASON_CAL.get(liga)
    if not cal: return None
    s, e = cal
    if e <= s: return None
    pct = (fecha - s).days / (e - s).days
    pct = max(0.0, min(1.0, pct))
    if pct < 0.25: return 0
    elif pct < 0.50: return 1
    elif pct < 0.75: return 2
    else: return 3


def momento_pct_typical(fecha, liga):
    cal = SEASON_CAL.get(liga)
    if not cal: return None
    s, e = cal
    if e <= s: return None
    return (fecha - s).days / (e - s).days


# ===== V13 helpers =====
def cargar_v13(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, target, intercept, coefs_json, metodo, feature_set
        FROM v13_coef_por_liga
        WHERE (liga, target, calibrado_en) IN (
            SELECT liga, target, MAX(calibrado_en) FROM v13_coef_por_liga GROUP BY liga, target
        ) AND metodo IS NOT NULL
    """).fetchall()
    out = {}
    for liga, t, ic, cf, m, fs in rows:
        out.setdefault(liga, {})[t] = {"intercept": float(ic), "coefs": json.loads(cf),
                                         "metodo": m, "feature_set": fs}
    return out


_FSETS = {
    "F1_off": ["atk_sots", "atk_shot_pct", "atk_corners", "def_sots_c", "def_shot_pct_c"],
    "F2_pos": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c"],
    "F4_disc": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
                "atk_yellow", "atk_red", "atk_fouls", "def_sots_c", "def_shot_pct_c"],
    "F5_ratio": ["atk_sots_per_shot", "atk_pressure", "atk_set_piece",
                 "atk_red_card_rate", "def_solidez"],
}

_EMA_COLS = ["ema_l_sots", "ema_l_shot_pct", "ema_l_pos", "ema_l_pass_pct",
             "ema_l_corners", "ema_l_yellow", "ema_l_red", "ema_l_fouls",
             "ema_l_shots", "ema_c_sots", "ema_c_shot_pct", "ema_c_tackles",
             "ema_c_blocks"]


def feat_value(name, atk, df):
    try:
        if name == "atk_sots":      return atk["ema_l_sots"]
        if name == "atk_shot_pct":  return atk["ema_l_shot_pct"]
        if name == "atk_pos":       return atk["ema_l_pos"]
        if name == "atk_pass_pct":  return atk["ema_l_pass_pct"]
        if name == "atk_corners":   return atk["ema_l_corners"]
        if name == "atk_yellow":    return atk["ema_l_yellow"]
        if name == "atk_red":       return atk["ema_l_red"]
        if name == "atk_fouls":     return atk["ema_l_fouls"]
        if name == "def_sots_c":    return df["ema_c_sots"]
        if name == "def_shot_pct_c":return df["ema_c_shot_pct"]
        if name == "def_tackles_c": return df["ema_c_tackles"]
        if name == "def_blocks_c":  return df["ema_c_blocks"]
        if name == "atk_sots_per_shot":
            sh = atk.get("ema_l_shots")
            if sh is None or sh == 0: return 0.4
            return float(atk["ema_l_sots"]) / float(sh)
        if name == "atk_pressure":
            return float(atk["ema_l_pos"]) * float(atk["ema_l_shot_pct"]) / 100.0
        if name == "atk_set_piece": return float(atk["ema_l_corners"])
        if name == "atk_red_card_rate":
            f = atk.get("ema_l_fouls")
            if f is None or f == 0: return 0.0
            return float(atk["ema_l_red"]) / float(f)
        if name == "def_solidez": return float(df["ema_c_tackles"]) + float(df["ema_c_blocks"])
        return None
    except: return None


def calcular_xg_v13(coefs, liga, atk, df, target_local=True):
    cf_liga = coefs.get(liga)
    if not cf_liga: return None
    tgt = "local" if target_local else "visita"
    cf = cf_liga.get(tgt)
    if not cf: return None
    fset = _FSETS.get(cf["feature_set"])
    if not fset: return None
    feats = []
    for n in fset:
        v = feat_value(n, atk, df)
        if v is None: return None
        feats.append(float(v))
    coefs_arr = [cf["coefs"].get(n, 0.0) for n in fset]
    return max(0.10, cf["intercept"] + sum(f * c for f, c in zip(feats, coefs_arr)))


def lookup_ema(con, liga, equipo, fecha_str):
    cur = con.cursor()
    cols_sql = ", ".join(_EMA_COLS)
    r = cur.execute(f"""SELECT {cols_sql} FROM historial_equipos_stats
                         WHERE liga=? AND equipo=? AND fecha < ? AND n_acum>=5
                         ORDER BY fecha DESC LIMIT 1""",
                     (liga, equipo, fecha_str)).fetchone()
    if not r: return None
    d = dict(zip(_EMA_COLS, r))
    if any(v is None for v in d.values()): return None
    return d


def poisson(k, lam):
    if lam <= 0: return 0.0 if k > 0 else 1.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def tau(i, j, lam, mu, rho):
    if i == 0 and j == 0: return 1.0 - lam * mu * rho
    if i == 1 and j == 0: return 1.0 + mu * rho
    if i == 0 and j == 1: return 1.0 + lam * rho
    if i == 1 and j == 1: return 1.0 - rho
    return 1.0


def probs_dc(xg_l, xg_v, rho=RHO_FALLBACK, max_g=8):
    if xg_l <= 0 or xg_v <= 0: return 1/3, 1/3, 1/3
    p1 = px = p2 = 0.0
    for i in range(max_g):
        for j in range(max_g):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j: p1 += pb
            elif i == j: px += pb
            else: p2 += pb
    s = p1 + px + p2
    if s <= 0: return 1/3, 1/3, 1/3
    return p1/s, px/s, p2/s


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


PICK_NORM = {"1": "LOCAL", "X": "EMPATE", "2": "VISITA",
              "LOCAL": "LOCAL", "EMPATE": "EMPATE", "VISITA": "VISITA"}


def main():
    print("Cargando picks reales 2026-03/04...")
    picks = cargar_picks_reales()
    print(f"  N total: {len(picks)}")

    con = sqlite3.connect(DB)
    coefs = cargar_v13(con)
    print(f"  Ligas V13 elegibles: {sorted(coefs.keys())}")
    print()

    # Asignar momento_bin a cada pick (ambos métodos)
    for p in picks:
        p["bin_inprog"] = momento_bin_in_progress(p["fecha"], p["liga"], picks)
        p["bin_typical"] = momento_bin_typical(p["fecha"], p["liga"])
        p["pct_typical"] = momento_pct_typical(p["fecha"], p["liga"])

    # Diagnostico: distribucion bins
    print("=== Distribucion picks por momento_bin (TIPICO vs IN-PROGRESS) ===")
    print(f"{'liga':<14} | {'typical bins':<25} | {'inprog bins':<25} | {'pct_typical_avg':>15}")
    by_liga = defaultdict(list)
    for p in picks: by_liga[p["liga"]].append(p)
    for liga in sorted(by_liga.keys()):
        sub = by_liga[liga]
        cnt_typ = defaultdict(int); cnt_ip = defaultdict(int)
        for p in sub:
            cnt_typ[p["bin_typical"]] += 1
            cnt_ip[p["bin_inprog"]] += 1
        typ_str = ", ".join(f"Q{b+1}={cnt_typ.get(b, 0)}" for b in [0,1,2,3])
        ip_str = ", ".join(f"Q{b+1}={cnt_ip.get(b, 0)}" for b in [0,1,2,3])
        pct_avg = np.mean([p["pct_typical"] for p in sub if p["pct_typical"] is not None])
        print(f"{liga:<14} | {typ_str:<25} | {ip_str:<25} | {pct_avg*100:>13.1f}%")

    print()

    # Aplicar V0 y V13 a cada pick (V13 contrafactual)
    print("=== Aplicando V13 contrafactual a cada pick ===")
    n_v13_apostar = 0; n_v13_pasar = 0; n_no_aplica = 0
    for p in picks:
        if not p["liga"] or p["liga"] not in coefs:
            n_no_aplica += 1
            continue
        if not p["local"] or not p["visita"]:
            n_no_aplica += 1
            continue
        atk_l = lookup_ema(con, p["liga"], p["local"], p["fecha_str"])
        atk_v = lookup_ema(con, p["liga"], p["visita"], p["fecha_str"])
        if not atk_l or not atk_v:
            n_no_aplica += 1
            continue
        xg_l = calcular_xg_v13(coefs, p["liga"], atk_l, atk_v, True)
        xg_v = calcular_xg_v13(coefs, p["liga"], atk_v, atk_l, False)
        if xg_l is None or xg_v is None:
            n_no_aplica += 1
            continue
        p1, px, p2 = probs_dc(xg_l, xg_v)
        s = sorted([p1, px, p2], reverse=True)
        if s[0] - s[1] < 0.05:
            p["v13"] = {"decision": "PASAR_margen", "xg_l": xg_l, "xg_v": xg_v}
            n_v13_pasar += 1
            continue
        opts = [("LOCAL", p1), ("EMPATE", px), ("VISITA", p2)]
        label_v13, prob_v13 = max(opts, key=lambda x: x[1])
        cuota = p["cuota"]
        if cuota <= 1.0 or prob_v13 * cuota - 1 < 0.03:
            p["v13"] = {"decision": "PASAR_ev_min", "xg_l": xg_l, "xg_v": xg_v}
            n_v13_pasar += 1
            continue
        stake_v13 = kelly(prob_v13, cuota)
        if stake_v13 <= 0:
            p["v13"] = {"decision": "PASAR_kelly", "xg_l": xg_l, "xg_v": xg_v}
            n_v13_pasar += 1
            continue
        pick_motor_norm = PICK_NORM.get(p["pick"], p["pick"])
        coincide = (label_v13 == pick_motor_norm)
        if coincide:
            gano = (p["resultado"] == "GANADA")
            profit = stake_v13 * (cuota - 1) if gano else -stake_v13
        else:
            if p["resultado"] == "GANADA":
                gano = False
                profit = -stake_v13  # asumir V13 perdió
            else:
                gano = None
                profit = None  # incierto
        p["v13"] = {"decision": "APOSTAR", "label": label_v13, "prob": prob_v13,
                    "stake": stake_v13, "cuota": cuota, "gano": gano, "profit": profit,
                    "xg_l": xg_l, "xg_v": xg_v, "coincide_motor": coincide}
        n_v13_apostar += 1

    print(f"  V13 APOSTAR: {n_v13_apostar}, V13 PASAR: {n_v13_pasar}, no aplica: {n_no_aplica}")
    print()

    # === Yield V0 vs V13 por bin TYPICAL ===
    print("=== YIELD V0 vs V13 por momento_bin TYPICAL (calendario real) ===")
    print(f"{'liga':<14} {'arch':<5} | " + " | ".join(f"Q{q+1}".rjust(15) for q in range(4)))
    print("-" * 100)
    payload_typical = {}
    for liga in ["Argentina", "Brasil", "Inglaterra", "Italia", "Francia", "Noruega", "Turquia"]:
        sub = [p for p in picks if p["liga"] == liga]
        if not sub: continue
        for arch in ["V0", "V13"]:
            row_str = f"{liga:<14} {arch:<5} | "
            payload_typical.setdefault(liga, {})[arch] = {}
            for q in [0, 1, 2, 3]:
                sub_q = [p for p in sub if p["bin_typical"] == q]
                if arch == "V0":
                    sub_q_op = [p for p in sub_q if p["resultado"] in ("GANADA", "PERDIDA")]
                    if not sub_q_op:
                        row_str += f"{'-':>15} | "
                        continue
                    n = len(sub_q_op)
                    g = sum(1 for p in sub_q_op if p["resultado"] == "GANADA")
                    # Unitario yield
                    sum_pl = sum((p["cuota"] - 1) if p["resultado"] == "GANADA" else -1 for p in sub_q_op)
                    yld = sum_pl / n * 100 if n > 0 else 0
                    cell = f"N={n} y={yld:+.0f}%"
                    row_str += f"{cell:>15} | "
                    payload_typical[liga][arch][f"Q{q+1}"] = {"n": n, "hit": round(g/n*100, 1), "yield": round(yld, 1)}
                else:  # V13
                    v13_apost = [p for p in sub_q if p.get("v13", {}).get("decision") == "APOSTAR"
                                  and p["v13"].get("profit") is not None]
                    if not v13_apost:
                        row_str += f"{'-':>15} | "
                        continue
                    n = len(v13_apost)
                    g = sum(1 for p in v13_apost if p["v13"]["gano"])
                    sum_stake = sum(p["v13"]["stake"] for p in v13_apost)
                    sum_pl = sum(p["v13"]["profit"] for p in v13_apost)
                    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
                    cell = f"N={n} y={yld:+.0f}%"
                    row_str += f"{cell:>15} | "
                    payload_typical[liga][arch][f"Q{q+1}"] = {"n": n, "hit": round(g/n*100, 1), "yield": round(yld, 1)}
            print(row_str)

    # === Yield V0 vs V13 por bin IN-PROGRESS (rango observado) ===
    print("\n=== YIELD V0 vs V13 por momento_bin IN-PROGRESS (rango observado 2026) ===")
    print(f"{'liga':<14} {'arch':<5} | " + " | ".join(f"Q{q+1}".rjust(15) for q in range(4)))
    print("-" * 100)
    payload_inprog = {}
    for liga in ["Argentina", "Brasil", "Inglaterra", "Italia", "Francia", "Noruega", "Turquia"]:
        sub = [p for p in picks if p["liga"] == liga]
        if not sub: continue
        for arch in ["V0", "V13"]:
            row_str = f"{liga:<14} {arch:<5} | "
            payload_inprog.setdefault(liga, {})[arch] = {}
            for q in [0, 1, 2, 3]:
                sub_q = [p for p in sub if p["bin_inprog"] == q]
                if arch == "V0":
                    sub_q_op = [p for p in sub_q if p["resultado"] in ("GANADA", "PERDIDA")]
                    if not sub_q_op:
                        row_str += f"{'-':>15} | "
                        continue
                    n = len(sub_q_op)
                    g = sum(1 for p in sub_q_op if p["resultado"] == "GANADA")
                    sum_pl = sum((p["cuota"] - 1) if p["resultado"] == "GANADA" else -1 for p in sub_q_op)
                    yld = sum_pl / n * 100 if n > 0 else 0
                    cell = f"N={n} y={yld:+.0f}%"
                    row_str += f"{cell:>15} | "
                    payload_inprog[liga][arch][f"Q{q+1}"] = {"n": n, "hit": round(g/n*100, 1), "yield": round(yld, 1)}
                else:
                    v13_apost = [p for p in sub_q if p.get("v13", {}).get("decision") == "APOSTAR"
                                  and p["v13"].get("profit") is not None]
                    if not v13_apost:
                        row_str += f"{'-':>15} | "
                        continue
                    n = len(v13_apost)
                    g = sum(1 for p in v13_apost if p["v13"]["gano"])
                    sum_stake = sum(p["v13"]["stake"] for p in v13_apost)
                    sum_pl = sum(p["v13"]["profit"] for p in v13_apost)
                    yld = sum_pl / sum_stake * 100 if sum_stake > 0 else 0
                    cell = f"N={n} y={yld:+.0f}%"
                    row_str += f"{cell:>15} | "
                    payload_inprog[liga][arch][f"Q{q+1}"] = {"n": n, "hit": round(g/n*100, 1), "yield": round(yld, 1)}
            print(row_str)

    payload = {
        "fecha": datetime.now().isoformat(),
        "n_picks_total": len(picks),
        "n_v13_apostar": n_v13_apostar, "n_v13_pasar": n_v13_pasar,
        "n_no_aplica_v13": n_no_aplica,
        "season_calendario_typical": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in SEASON_CAL.items()},
        "yield_por_q_typical": payload_typical,
        "yield_por_q_inprog": payload_inprog,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

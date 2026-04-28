"""¿El yield V4.7 vs sistema actual cambia según altura de temporada?

Pregunta del usuario: al inicio de temp (poca data EMA, equipos no calibrados)
vs final (mucha data acumulada) — ¿hay patrón?

Setup: misma data que yield_por_temp_v47_y_fix6.py (N=7,867 OOS Pinnacle).
Para cada (liga, temp), normalizo fecha del partido a [0, 1] del rango
min-max de fechas en esa liga+temp. Luego agrupo en quintiles Q1..Q5
o cuartiles Q1..Q4 (uso cuartiles, 5 sería ruidoso por liga).

Outputs:
  - Tabla por bin (Q1=arranque, Q4=cierre): yield A, yield D, dY V4.7,
    yield F6 v2, dY F6
  - Tabla por (temp, bin): drill-down ¿el patrón es por temp?
  - Análisis: ¿hay tendencia monótona Q1->Q4?
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT_DIR = Path(__file__).resolve().parent

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025
N_BOOTSTRAP = 2000

FIX5_BUCKET_LO = 0.40
FIX5_BUCKET_HI = 0.50
FIX5_DELTA = 0.042

FIX6_V2_BUCKETS = [
    ("1", 0.25, 0.30, -0.0369), ("1", 0.30, 0.35, -0.0236),
    ("1", 0.35, 0.40, +0.0181), ("1", 0.40, 0.45, +0.0198),
    ("1", 0.50, 0.55, +0.0605), ("1", 0.55, 0.60, +0.1067),
    ("2", 0.20, 0.25, -0.0451), ("2", 0.25, 0.30, -0.0348),
    ("2", 0.30, 0.35, -0.0314), ("2", 0.45, 0.50, +0.0536),
    ("2", 0.50, 0.55, +0.1092),
]


def aplicar_fix6_v2(p1, px, p2):
    p_corr = {"1": p1, "X": px, "2": p2}
    for outcome, prob in [("1", p1), ("X", px), ("2", p2)]:
        for b_out, lo, hi, corr in FIX6_V2_BUCKETS:
            if b_out == outcome and lo <= prob < hi:
                p_corr[outcome] = max(0.001, prob + corr)
                break
    s = p_corr["1"] + p_corr["X"] + p_corr["2"]
    if s <= 0:
        return 1/3, 1/3, 1/3
    return p_corr["1"]/s, p_corr["X"]/s, p_corr["2"]/s


def kelly_fraction(p, cuota):
    if cuota <= 1.0 or p <= 0:
        return 0.0
    f = p - (1 - p) / (cuota - 1)
    return max(0.0, min(f, KELLY_CAP))


def evaluar_partido(p1, px, p2, c1, cx, c2, outcome):
    sorted_p = sorted([p1, px, p2], reverse=True)
    if sorted_p[0] - sorted_p[1] < MARGEN_MIN:
        return 0.0, 0.0
    options = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(options, key=lambda x: x[1])
    if not cuota or cuota <= 1.0:
        return 0.0, 0.0
    if prob * cuota - 1 < EV_MIN:
        return 0.0, 0.0
    stake = kelly_fraction(prob, cuota)
    if stake <= 0:
        return 0.0, 0.0
    if label == outcome:
        return stake, stake * (cuota - 1)
    return stake, -stake


def per_partido_metrics(rows):
    out = np.empty((len(rows), 4))
    for i, (p1, px, p2, c1, cx, c2, outcome) in enumerate(rows):
        stk, prof = evaluar_partido(p1, px, p2, c1, cx, c2, outcome)
        o1 = 1 if outcome == "1" else 0
        ox = 1 if outcome == "X" else 0
        o2 = 1 if outcome == "2" else 0
        br = (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2
        out[i] = (stk, prof, br, 1.0 if stk > 0 else 0.0)
    return out


def yield_de(arr):
    if len(arr) == 0:
        return 0.0
    s = arr[:, 0].sum()
    p = arr[:, 1].sum()
    return (p / s * 100) if s > 0 else 0.0


def hit_de(arr):
    if len(arr) == 0:
        return 0.0
    apostados = arr[arr[:, 3] == 1]
    if len(apostados) == 0:
        return 0.0
    n_gano = (apostados[:, 1] > 0).sum()
    return n_gano / len(apostados) * 100


def paired_bootstrap_delta(arr_a, arr_x, B=N_BOOTSTRAP, seed=42):
    if len(arr_a) == 0 or len(arr_x) == 0:
        return {"delta_yield_obs": 0.0, "delta_yield_ci95_lo": 0.0,
                "delta_yield_ci95_hi": 0.0, "p_delta_positivo": 0.5,
                "delta_yield_mean_boot": 0.0, "p_delta_negativo": 0.5}
    rng = np.random.default_rng(seed)
    n = len(arr_a)
    deltas = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        sa = arr_a[idx, 0].sum()
        pa = arr_a[idx, 1].sum()
        sx = arr_x[idx, 0].sum()
        px = arr_x[idx, 1].sum()
        ya = (pa / sa * 100) if sa > 0 else 0.0
        yx = (px / sx * 100) if sx > 0 else 0.0
        deltas[b] = yx - ya
    return {
        "delta_yield_obs": yield_de(arr_x) - yield_de(arr_a),
        "delta_yield_mean_boot": float(deltas.mean()),
        "delta_yield_ci95_lo": float(np.percentile(deltas, 2.5)),
        "delta_yield_ci95_hi": float(np.percentile(deltas, 97.5)),
        "p_delta_negativo": float((deltas < 0).mean()),
        "p_delta_positivo": float((deltas > 0).mean()),
    }


def parse_fecha(s: str):
    """fecha_partido viene como '2022-08-26T00:00:00:00' o '2022-08-26'."""
    fecha_str = s[:10] if len(s) >= 10 else s
    return datetime.strptime(fecha_str, "%Y-%m-%d")


def cargar_datos():
    """Carga rows_real y rows_pure (cacheable, no depende de n_bins)."""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows_real = cur.execute("""
        SELECT p.temp, p.liga, p.fecha_partido, p.ht, p.at,
               p.prob_1, p.prob_x, p.prob_2,
               q.psch, q.pscd, q.psca, p.outcome
        FROM predicciones_walkforward p
        JOIN cuotas_externas_historico q
          ON p.liga = q.liga
         AND substr(p.fecha_partido, 1, 10) = q.fecha
         AND p.ht = q.ht
         AND p.at = q.at
        WHERE p.fuente='walk_forward_sistema_real'
          AND q.psch IS NOT NULL AND q.pscd IS NOT NULL AND q.psca IS NOT NULL
          AND p.prob_1 IS NOT NULL
    """).fetchall()
    rows_pure = cur.execute("""
        SELECT p.temp, p.liga, p.fecha_partido, p.ht, p.at,
               p.prob_1, p.prob_x, p.prob_2
        FROM predicciones_walkforward p
        WHERE p.fuente='walk_forward_persistente'
          AND p.prob_1 IS NOT NULL
    """).fetchall()
    con.close()
    return rows_real, rows_pure


def run(rows_real, rows_pure, n_bins: int, out_path: Path):
    label_map = {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}
    letter_map = {4: "Q", 8: "O", 12: "D"}
    label_bins = label_map.get(n_bins, f"BIN_{n_bins}")
    bin_letter = letter_map.get(n_bins, "B")
    N_BINS = n_bins

    key_real = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6], r[7], r[8], r[9], r[10], r[11]) for r in rows_real}
    key_pure = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6], r[7]) for r in rows_pure}
    keys = sorted(set(key_real.keys()) & set(key_pure.keys()))

    # Para cada (liga, temp), determinar fecha min y max
    fechas_por_lt = defaultdict(list)
    for k in keys:
        temp, liga, fecha, ht, at = k
        fechas_por_lt[(liga, temp)].append(parse_fecha(fecha))
    rango_lt = {}
    for (liga, temp), fechas in fechas_por_lt.items():
        rango_lt[(liga, temp)] = (min(fechas), max(fechas))

    # Para cada partido, calcular pct_temporada y bin
    print(f"\n{'='*70}")
    print(f"=== Yield por altura de temporada (N={len(keys)}) -- {label_bins} (n_bins={N_BINS}) ===")
    print(f"{'='*70}")
    print(f"{bin_letter}1=arranque, {bin_letter}{N_BINS}=cierre. Cada bin = {100/N_BINS:.1f}% del trayecto.")
    print(f"Filtros: MARGEN>={MARGEN_MIN} EV>={EV_MIN} KELLY={KELLY_CAP}")
    print()

    # Bins por temp (3 temps x 4 bins) y bin agregado (3*4 / 3)
    rows_por_bin = defaultdict(lambda: {"A": [], "D": [], "F6": []})
    rows_por_bin_temp = defaultdict(lambda: {"A": [], "D": [], "F6": []})
    pcts_por_partido = []  # diagnostico distribucion

    for k in keys:
        temp, liga, fecha_str, ht, at = k
        f = parse_fecha(fecha_str)
        f_min, f_max = rango_lt[(liga, temp)]
        if f_max == f_min:
            continue
        pct = (f - f_min).days / max((f_max - f_min).days, 1)
        pct = max(0.0, min(0.999, pct))
        pcts_por_partido.append(pct)
        bin_idx = min(int(pct * N_BINS), N_BINS - 1)  # 0..3

        p1_a, px_a, p2_a, c1, cx, c2, outcome = key_real[k]
        p1_d, px_d, p2_d = key_pure[k]
        p1_f, px_f, p2_f = aplicar_fix6_v2(p1_a, px_a, p2_a)

        rA = (p1_a, px_a, p2_a, c1, cx, c2, outcome)
        rD = (p1_d, px_d, p2_d, c1, cx, c2, outcome)
        rF = (p1_f, px_f, p2_f, c1, cx, c2, outcome)

        rows_por_bin[bin_idx]["A"].append(rA)
        rows_por_bin[bin_idx]["D"].append(rD)
        rows_por_bin[bin_idx]["F6"].append(rF)
        rows_por_bin_temp[(temp, bin_idx)]["A"].append(rA)
        rows_por_bin_temp[(temp, bin_idx)]["D"].append(rD)
        rows_por_bin_temp[(temp, bin_idx)]["F6"].append(rF)

    # === TABLA PRINCIPAL: agregada por bin ===
    print(f"=== AGREGADA POR {label_bins} (todas las temps juntas) ===")
    print(f"{'O':<3} {'pct':>7} {'N':>5} {'NApA':>5} {'YldA%':>7} {'YldD%':>7} {'dY':>7} "
          f"{'CI95':>20} {'sig':>3} | {'BrA':>6} {'BrD':>6} {'dBr':>7}")
    payload = {"agregado_por_bin": {}, "por_temp_bin": {}, "n_bins": N_BINS}
    for bin_idx in range(N_BINS):
        rows = rows_por_bin[bin_idx]
        arrA = per_partido_metrics(rows["A"])
        arrD = per_partido_metrics(rows["D"])
        arrF = per_partido_metrics(rows["F6"])
        pct_lo = bin_idx * 100 / N_BINS
        pct_hi = (bin_idx + 1) * 100 / N_BINS
        bin_label = f"Q{bin_idx+1}"  # mantenemos clave Q para compat con grafico
        n = len(rows["A"])
        nApA = int(arrA[:, 3].sum())
        yA = yield_de(arrA); yD = yield_de(arrD); yF = yield_de(arrF)
        brA = float(arrA[:, 2].mean()) if n > 0 else 0
        brD = float(arrD[:, 2].mean()) if n > 0 else 0
        brF = float(arrF[:, 2].mean()) if n > 0 else 0
        res_DvA = paired_bootstrap_delta(arrA, arrD)
        res_FvA = paired_bootstrap_delta(arrA, arrF)
        sigD = "*" if (res_DvA["delta_yield_ci95_lo"] > 0 or res_DvA["delta_yield_ci95_hi"] < 0) else " "
        ci_str = f"[{res_DvA['delta_yield_ci95_lo']:+.1f},{res_DvA['delta_yield_ci95_hi']:+.1f}]"
        print(f"{bin_letter}{bin_idx+1:<2} {pct_lo:>3.0f}-{pct_hi:>3.0f}% {n:>5} {nApA:>5} "
              f"{yA:>+7.2f} {yD:>+7.2f} {res_DvA['delta_yield_obs']:>+7.2f} "
              f"{ci_str:>20} {sigD:>3} | {brA:>6.4f} {brD:>6.4f} {brD-brA:>+7.4f}")
        payload["agregado_por_bin"][bin_label] = {
            "pct_lo": pct_lo, "pct_hi": pct_hi, "n": n, "n_apost_A": nApA,
            "yield_A": yA, "yield_D": yD, "yield_F6": yF,
            "hit_A": hit_de(arrA), "hit_D": hit_de(arrD), "hit_F6": hit_de(arrF),
            "brier_A": brA, "brier_D": brD, "brier_F6": brF,
            "paired_DvsA": res_DvA, "paired_F6vsA": res_FvA,
        }

    # === DRILL-DOWN: bin x temp ===
    print()
    print(f"=== DRILL-DOWN bin x temp (V4.7 dY) -- N>=30 por celda ===")
    bin_headers = " | ".join(f"{bin_letter}{i+1} dY      CI95         sig" for i in range(N_BINS))
    print(f"{'Temp':<6} {bin_headers}")
    temps_sorted = sorted({t for t, _ in rows_por_bin_temp.keys()})
    for temp in temps_sorted:
        line = f"{temp:<6} "
        for bin_idx in range(N_BINS):
            rows = rows_por_bin_temp.get((temp, bin_idx), {"A": [], "D": [], "F6": []})
            if len(rows["A"]) < 30:
                line += f"{'(N<30)':<8} {'':<13} {'':<4} | "
                continue
            arrA = per_partido_metrics(rows["A"])
            arrD = per_partido_metrics(rows["D"])
            res = paired_bootstrap_delta(arrA, arrD)
            ci = f"[{res['delta_yield_ci95_lo']:+.1f},{res['delta_yield_ci95_hi']:+.1f}]"
            sig = "*" if (res["delta_yield_ci95_lo"] > 0 or res["delta_yield_ci95_hi"] < 0) else " "
            line += f"{res['delta_yield_obs']:>+7.1f} {ci:>14} {sig:>3} | "
            payload["por_temp_bin"][f"{temp}_Q{bin_idx+1}"] = {
                "n": len(rows["A"]),
                "yield_A": yield_de(arrA), "yield_D": yield_de(arrD),
                "paired_DvsA": res,
            }
        print(line.rstrip(" |"))

    # === DRILL-DOWN POR LIGA ===
    print()
    print(f"=== DRILL-DOWN POR LIGA (Y_A% por {label_bins}) -- N>=30 por celda ===")
    rows_por_liga_bin = defaultdict(lambda: defaultdict(lambda: {"A": [], "D": [], "F6": []}))
    for k in keys:
        temp, liga, fecha_str, ht, at = k
        f = parse_fecha(fecha_str)
        f_min, f_max = rango_lt[(liga, temp)]
        if f_max == f_min:
            continue
        pct = (f - f_min).days / max((f_max - f_min).days, 1)
        pct = max(0.0, min(0.999, pct))
        bin_idx = min(int(pct * N_BINS), N_BINS - 1)
        p1_a, px_a, p2_a, c1, cx, c2, outcome = key_real[k]
        rA = (p1_a, px_a, p2_a, c1, cx, c2, outcome)
        rows_por_liga_bin[liga][bin_idx]["A"].append(rA)
    headers_liga = " ".join(f"{f'{bin_letter}{i+1}':>7}" for i in range(N_BINS))
    print(f"{'Liga':<14} {'NTot':>5} {headers_liga}")
    payload["por_liga_bin"] = {}
    for liga in sorted(rows_por_liga_bin.keys()):
        n_tot = sum(len(rows_por_liga_bin[liga][i]["A"]) for i in range(N_BINS))
        cells = []
        liga_payload = {}
        for bin_idx in range(N_BINS):
            rA = rows_por_liga_bin[liga][bin_idx]["A"]
            n_cell = len(rA)
            if n_cell < 30:
                cells.append(f"{'n<30':>7}")
                liga_payload[f"Q{bin_idx+1}"] = {"n": n_cell, "yield_A": None, "hit_A": None}
            else:
                arr = per_partido_metrics(rA)
                y = yield_de(arr)
                cells.append(f"{y:>+7.1f}")
                liga_payload[f"Q{bin_idx+1}"] = {"n": n_cell, "yield_A": y,
                                                  "hit_A": hit_de(arr),
                                                  "brier_A": float(arr[:,2].mean())}
        print(f"{liga:<14} {n_tot:>5} {' '.join(cells)}")
        payload["por_liga_bin"][liga] = liga_payload

    # Tendencia monotonia
    print()
    print(f"=== TENDENCIA AGREGADA POR {label_bins} ===")
    dys_DvA = [payload["agregado_por_bin"][f"Q{i+1}"]["paired_DvsA"]["delta_yield_obs"] for i in range(N_BINS)]
    yAs = [payload["agregado_por_bin"][f"Q{i+1}"]["yield_A"] for i in range(N_BINS)]
    brAs = [payload["agregado_por_bin"][f"Q{i+1}"]["brier_A"] for i in range(N_BINS)]
    hAs = [payload["agregado_por_bin"][f"Q{i+1}"]["hit_A"] for i in range(N_BINS)]
    print(f"  Yield_A:  {' '.join(f'{bin_letter}{i+1}={yAs[i]:+.1f}' for i in range(N_BINS))}")
    print(f"  Brier_A:  {' '.join(f'{bin_letter}{i+1}={brAs[i]:.3f}' for i in range(N_BINS))}")
    print(f"  Hit_A:    {' '.join(f'{bin_letter}{i+1}={hAs[i]:.1f}' for i in range(N_BINS))}")
    print(f"  dY V4.7:  {' '.join(f'{bin_letter}{i+1}={dys_DvA[i]:+.1f}' for i in range(N_BINS))}")
    monotonic_up = all(dys_DvA[i] <= dys_DvA[i+1] for i in range(N_BINS-1))
    monotonic_down = all(dys_DvA[i] >= dys_DvA[i+1] for i in range(N_BINS-1))
    print(f"  V4.7 monotono ascendente: {monotonic_up}, descendente: {monotonic_down}")

    payload["tendencia"] = {
        "dys_DvA_por_bin": dict(zip([f"Q{i+1}" for i in range(N_BINS)], dys_DvA)),
        "monotonic_up": monotonic_up,
        "monotonic_down": monotonic_down,
    }

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] {out_path}")
    return payload


if __name__ == "__main__":
    rows_real, rows_pure = cargar_datos()
    for nb in (4, 8, 12):
        run(rows_real, rows_pure, n_bins=nb,
            out_path=OUT_DIR / f"yield_por_altura_temporada_bin{nb}.json")

"""Analisis Si Hubiera POR LIGA × CUARTOS para inferir comportamiento del sistema.

Cada liga tiene su propia firma temporal. Analisis individual permite:
  - Detectar ligas con yield estable cross-cuarto vs ligas degradantes
  - Identificar cuándo una liga deja de ser apostable
  - Construir un dossier por liga (curva yield + hit rate por Q)

Output:
  - tabla por liga con Q1/Q2/Q3/Q4 hit y yield
  - clasificación: ESTABLE / DEGRADANTE / SIEMPRE_NEG / RUIDO_N_CHICO
  - sugerencia de acción operativa por liga
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl
import numpy as np

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Backtest_Modelo.xlsx"
OUT_DIR = Path(__file__).resolve().parent

N_BOOTSTRAP = 1500


def parse_fecha(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def cargar_picks():
    """Carga picks Excel + JOIN con DB para probs y outcome (Brier)."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    con = sqlite3.connect(DB)
    cur = con.cursor()
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha = parse_fecha(row[0])
        if fecha is None:
            continue
        if row[7] not in ("GANADA", "PERDIDA"):
            continue
        partido = row[1]
        liga = row[2]
        if not partido or " vs " not in partido:
            continue
        local, visita = partido.split(" vs ", 1)
        d = fecha.strftime("%Y-%m-%d")
        db_row = cur.execute("""
            SELECT prob_1, prob_x, prob_2, goles_l, goles_v
            FROM partidos_backtest
            WHERE substr(fecha,1,10)=? AND pais=? AND local=? AND visita=?
        """, (d, liga, local, visita)).fetchone()
        if db_row:
            p1, px, p2, gl, gv = db_row
            outcome = "1" if (gl or 0) > (gv or 0) else ("X" if (gl or 0) == (gv or 0) else "2")
        else:
            p1 = px = p2 = None
            outcome = None
        picks.append({
            "fecha": fecha, "liga": liga, "pick": row[3],
            "cuota": row[4] or 0, "camino": row[5],
            "resultado": row[7], "stake": row[8] or 0, "pl": row[9] or 0,
            "prob_1": p1, "prob_x": px, "prob_2": p2, "outcome_1x2": outcome,
        })
    con.close()
    return picks


def brier_1x2(p):
    if p["prob_1"] is None or p["outcome_1x2"] is None:
        return None
    o = p["outcome_1x2"]
    o1 = 1 if o == "1" else 0
    ox = 1 if o == "X" else 0
    o2 = 1 if o == "2" else 0
    return (p["prob_1"] - o1) ** 2 + (p["prob_x"] - ox) ** 2 + (p["prob_2"] - o2) ** 2


def yield_unit(sub):
    n = len(sub)
    if n == 0:
        return None
    n_g = sum(1 for p in sub if p["resultado"] == "GANADA")
    pls = [(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub]
    briers = [brier_1x2(p) for p in sub]
    briers_v = [b for b in briers if b is not None]
    brier_avg = sum(briers_v) / len(briers_v) if briers_v else None
    return {
        "n": n, "n_gano": n_g, "hit_pct": n_g / n * 100,
        "yield_pct": sum(pls) / n * 100,
        "sum_pl_unit": sum(pls),
        "brier_avg": brier_avg, "n_brier": len(briers_v),
    }


def boot_yield(sub, B=N_BOOTSTRAP, seed=42):
    if not sub:
        return None
    n = len(sub)
    rng = np.random.default_rng(seed)
    pls = np.array([(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0 for p in sub])
    ys = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        ys[b] = pls[idx].mean() * 100
    return {"ci95_lo": float(np.percentile(ys, 2.5)),
            "ci95_hi": float(np.percentile(ys, 97.5))}


def clasificar(qs, n_bins=8):
    """Recibe dict Q1..QN_BINS con hit_pct y yield_pct. Devuelve etiqueta.
    Requiere >= 75% de bins cubiertos para clasificar."""
    yields = [qs[f"Q{i+1}"]["yield_pct"] for i in range(n_bins) if qs.get(f"Q{i+1}")]
    n_cubiertos = len(yields)
    if n_cubiertos < n_bins * 3 // 4:
        return "RUIDO_BINS_INCOMPLETOS"
    pos_ratio = sum(1 for y in yields if y > 5) / n_cubiertos
    neg_ratio = sum(1 for y in yields if y < -5) / n_cubiertos
    # Promedio primer/ultimo tercio para detectar tendencia
    n_third = max(1, n_cubiertos // 3)
    yields_ini = yields[:n_third]
    yields_fin = yields[-n_third:]
    avg_ini = sum(yields_ini) / len(yields_ini)
    avg_fin = sum(yields_fin) / len(yields_fin)
    drop = avg_ini - avg_fin
    if pos_ratio >= 0.75:
        return "ESTABLE_POSITIVA"
    if neg_ratio >= 0.75:
        return "ESTABLE_NEGATIVA"
    if drop > 50 and avg_ini > 0 and avg_fin < 0:
        return "DEGRADANTE_FUERTE"
    if drop > 25:
        return "DEGRADANTE_MODERADA"
    if pos_ratio > 0 and neg_ratio > 0:
        return "INESTABLE"
    return "MIXTA"


def run(picks, n_bins: int, out_path: Path):
    if not picks:
        print("Sin picks")
        return
    label_map = {4: "CUARTOS", 8: "OCTAVOS", 12: "DOZAVOS"}
    letter_map = {4: "Q", 8: "O", 12: "D"}
    label_bins = label_map.get(n_bins, f"BIN_{n_bins}")
    bin_letter = letter_map.get(n_bins, "B")
    n_min = max(8, 2 * n_bins)  # liga necesita al menos 2*n_bins picks para clasificar
    fmin = min(p["fecha"] for p in picks)
    fmax = max(p["fecha"] for p in picks)
    print(f"\n{'='*70}")
    print(f"=== Si Hubiera por LIGA x {label_bins} (n_bins={n_bins}) ===")
    print(f"{'='*70}")
    print(f"Rango: {fmin.strftime('%Y-%m-%d')} a {fmax.strftime('%Y-%m-%d')} ({(fmax-fmin).days} dias)")
    print(f"N total picks: {len(picks)}, N_MIN_PARA_CLASIFICAR={n_min}")
    print()

    por_liga = defaultdict(list)
    for p in picks:
        por_liga[p["liga"]].append(p)

    print(f"=== TABLA POR LIGA x {label_bins} (yield unitario) ===")
    headers_y = " ".join(f"{f'Y{bin_letter}{i+1}':>6}" for i in range(n_bins))
    headers_h = " ".join(f"{f'H{bin_letter}{i+1}':>4}" for i in range(n_bins))
    print(f"{'Liga':<14} {'N':>4} {'Hit%':>6} {'YldGl%':>8} {headers_y} | {headers_h} | {'Etiqueta'}")
    payload = {"fmin": fmin.strftime("%Y-%m-%d"), "fmax": fmax.strftime("%Y-%m-%d"),
                "n_total": len(picks), "n_bins": n_bins, "ligas": {}}
    for liga in sorted(por_liga.keys()):
        sub = por_liga[liga]
        m_glob = yield_unit(sub)
        ci_glob = boot_yield(sub) or {"ci95_lo": 0, "ci95_hi": 0}
        if m_glob["n"] < n_min:
            etiqueta = "RUIDO_N_CHICO"
            qs = {}
        else:
            qs = {}
            for q in range(n_bins):
                f_lo = fmin + (fmax - fmin) * q / n_bins
                f_hi = fmin + (fmax - fmin) * (q + 1) / n_bins
                if q == n_bins - 1:
                    sq = [p for p in sub if p["fecha"] >= f_lo and p["fecha"] <= fmax]
                else:
                    sq = [p for p in sub if p["fecha"] >= f_lo and p["fecha"] < f_hi]
                m = yield_unit(sq)
                ci = boot_yield(sq)
                if m:
                    qs[f"Q{q+1}"] = {**m, **(ci or {"ci95_lo": 0, "ci95_hi": 0})}
            etiqueta = clasificar(qs, n_bins=n_bins)

        def fmt_y(q):
            x = qs.get(f"Q{q+1}")
            return f"{x['yield_pct']:>+6.1f}" if x else "   n/a"
        def fmt_h(q):
            x = qs.get(f"Q{q+1}")
            return f"{x['hit_pct']:>4.0f}" if x else " n/a"

        ys_str = " ".join(fmt_y(q) for q in range(n_bins))
        hs_str = " ".join(fmt_h(q) for q in range(n_bins))
        print(f"{liga:<14} {m_glob['n']:>4} {m_glob['hit_pct']:>6.1f} "
              f"{m_glob['yield_pct']:>+8.2f} {ys_str} | {hs_str} | {etiqueta}")
        payload["ligas"][liga] = {
            "n": m_glob["n"], "hit_pct": m_glob["hit_pct"],
            "yield_pct": m_glob["yield_pct"],
            "ci95_lo": ci_glob["ci95_lo"], "ci95_hi": ci_glob["ci95_hi"],
            "quartiles": qs, "etiqueta": etiqueta,
        }
    print()

    # === SINTESIS POR ETIQUETA ===
    print(f"=== SINTESIS POR ETIQUETA ===")
    por_etiqueta = defaultdict(list)
    for liga, d in payload["ligas"].items():
        por_etiqueta[d["etiqueta"]].append((liga, d["n"], d["yield_pct"]))
    for et, lig_list in sorted(por_etiqueta.items()):
        print(f"  [{et}]:")
        for liga, n, yld in sorted(lig_list, key=lambda x: -x[2]):
            print(f"    {liga:<14} N={n:>3} yield={yld:+.2f}%")
    print()

    # === RECOMENDACION OPERATIVA ===
    print(f"=== RECOMENDACION OPERATIVA POR LIGA ===")
    recomendaciones = {}
    for liga, d in payload["ligas"].items():
        n = d["n"]
        et = d["etiqueta"]
        ci_lo = d["ci95_lo"]
        ci_hi = d["ci95_hi"]
        yld = d["yield_pct"]
        if et == "RUIDO_N_CHICO":
            rec = f"OBSERVAR (N={n}<12, esperar mas data)"
        elif et == "ESTABLE_POSITIVA":
            rec = f"APOSTAR (yield consistente positivo cross-Q)"
        elif et == "ESTABLE_NEGATIVA":
            rec = f"NO APOSTAR (yield siempre negativo)"
        elif et == "DEGRADANTE_FUERTE":
            rec = f"REDUCIR EXPOSICION (Q1->Q4 cae fuerte)"
        elif et == "DEGRADANTE_MODERADA":
            rec = f"VIGILAR (Q1->Q4 cae moderado)"
        elif et == "INESTABLE":
            if ci_lo > 0:
                rec = f"APOSTAR pero conservador (yield neto pos pero variable)"
            elif ci_hi < 0:
                rec = f"NO APOSTAR (yield neto neg sig)"
            else:
                rec = f"OBSERVAR (CI95 cruza 0, no concluyente)"
        else:
            rec = "OBSERVAR"
        recomendaciones[liga] = {"etiqueta": et, "recomendacion": rec,
                                  "n": n, "yield_pct": yld,
                                  "ci95_lo": ci_lo, "ci95_hi": ci_hi}
        print(f"  {liga:<14} N={n:>3} yld={yld:>+7.2f} CI95=[{ci_lo:>+6.2f},{ci_hi:>+6.2f}]  -> {rec}")
    payload["recomendaciones"] = recomendaciones
    print()

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[OK] {out_path}")
    return payload


if __name__ == "__main__":
    picks = cargar_picks()
    for nb in (4, 8, 12):
        run(picks, n_bins=nb, out_path=OUT_DIR / f"si_hubiera_por_liga_bin{nb}.json")

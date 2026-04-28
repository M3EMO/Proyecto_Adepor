"""adepor-0ac TRIANGULACION: aplicar filtros n_acum + momento sobre picks REALES
del motor productivo (N=358 desde Backtest_Modelo.xlsx hoja 'Si Hubiera').

Objetivo: validar que el efecto observado en OOS Pinnacle 2022-24 (N=4584)
se sostiene en in-sample real 2026-03 a 2026-04 (N=358).

Limitacion: ligas LATAM (Bolivia, Ecuador, Uruguay, Paraguay) no estan en
historial_equipos_stats, asi que se excluyen del cruce. Cobertura efectiva:
Argentina, Brasil, Chile, Colombia, Inglaterra, Noruega, Peru, Turquia,
Espana, Italia, Francia, Alemania.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
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
OUT = Path(__file__).resolve().parent / "n_acum_triangulacion_real.json"


def parse_fecha(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


def cargar_picks():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Si Hubiera"]
    picks = []
    for row in ws.iter_rows(min_row=53, max_row=412, values_only=True):
        if not row or row[0] is None:
            continue
        fecha = parse_fecha(row[0])
        if fecha is None:
            continue
        resultado = row[7]
        if resultado not in ("GANADA", "PERDIDA"):
            continue
        partido = row[1] or ""
        # parse "Local vs Visita" o "Local - Visita"
        local, visita = None, None
        for sep in [" vs ", " - ", " v ", "-"]:
            if sep in partido:
                parts = partido.split(sep, 1)
                if len(parts) == 2:
                    local = parts[0].strip()
                    visita = parts[1].strip()
                    break
        picks.append({
            "fecha": fecha, "fecha_str": fecha.isoformat(),
            "partido": partido, "local": local, "visita": visita,
            "liga": row[2], "pick": row[3], "cuota": row[4] or 0,
            "camino": row[5], "resultado": resultado,
            "stake": row[8] or 0, "pl": row[9] or 0,
        })
    return picks


def buscar_n_acum(cur, liga, equipo, fecha_str):
    """Snapshot mas reciente PRE pick_fecha para (liga, equipo)."""
    if not equipo:
        return None
    r = cur.execute("""
        SELECT n_acum FROM historial_equipos_stats
        WHERE liga=? AND equipo=? AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (liga, equipo, fecha_str)).fetchone()
    return r[0] if r else None


def calcular_momento_bin(cur, liga, fecha):
    """Calcular pct_temp y momento_bin_4 desde rango fechas observado en historial."""
    # Encontrar temporada actual: liga + año-fecha
    año = fecha.year
    # Rango fechas de la liga en historial reciente (asumir temp = año)
    r = cur.execute("""
        SELECT MIN(fecha), MAX(fecha) FROM historial_equipos_stats
        WHERE liga=? AND substr(fecha,1,4)=?
    """, (liga, str(año))).fetchone()
    if not r or not r[0] or not r[1]:
        return None, None
    f_min = datetime.strptime(r[0][:10], "%Y-%m-%d").date()
    f_max = datetime.strptime(r[1][:10], "%Y-%m-%d").date()
    if f_max <= f_min:
        return None, None
    pct = (fecha - f_min).days / max(1, (f_max - f_min).days)
    pct = max(0.0, min(1.0, pct))
    if pct < 0.25:
        bin4 = 0
    elif pct < 0.50:
        bin4 = 1
    elif pct < 0.75:
        bin4 = 2
    else:
        bin4 = 3
    return pct, bin4


def yield_metrics(picks, usar_stake=True):
    """Yield, hit% y bootstrap CI95 sobre subset."""
    if usar_stake:
        sub = [p for p in picks if p["stake"] > 0]
    else:
        sub = picks
    if not sub:
        return {"n_pred": 0, "n_apost": 0, "hit_pct": 0, "yield_pct": 0,
                "ci95_lo": None, "ci95_hi": None}
    n = len(sub)
    n_gano = sum(1 for p in sub if p["resultado"] == "GANADA")
    if usar_stake:
        stakes = np.array([p["stake"] for p in sub], dtype=float)
        pls = np.array([p["pl"] for p in sub], dtype=float)
    else:
        stakes = np.ones(n)
        pls = np.array([(p["cuota"] - 1) if p["resultado"] == "GANADA" else -1.0
                        for p in sub])
    sum_s = stakes.sum()
    sum_p = pls.sum()
    yld = sum_p / sum_s * 100 if sum_s > 0 else 0
    hit = n_gano / n * 100
    # bootstrap
    rng = np.random.default_rng(42)
    B = 1000
    yields = []
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        ss = stakes[idx].sum()
        pp = pls[idx].sum()
        if ss > 0:
            yields.append(pp / ss * 100)
    if yields:
        ci_lo = float(np.percentile(yields, 2.5))
        ci_hi = float(np.percentile(yields, 97.5))
    else:
        ci_lo, ci_hi = None, None
    return {"n_pred": n, "n_apost": n, "hit_pct": round(hit, 2),
            "yield_pct": round(yld, 2),
            "ci95_lo": round(ci_lo, 2) if ci_lo is not None else None,
            "ci95_hi": round(ci_hi, 2) if ci_hi is not None else None}


def main():
    print("Cargando picks reales desde Backtest_Modelo.xlsx...")
    picks = cargar_picks()
    print(f"  N picks reales (GANADA/PERDIDA): {len(picks)}")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    print("\nEnriqueciendo con n_acum + momento_bin...")
    enriched = 0
    for p in picks:
        if not p["liga"] or not p["local"] or not p["visita"]:
            continue
        n_l = buscar_n_acum(cur, p["liga"], p["local"], p["fecha_str"])
        n_v = buscar_n_acum(cur, p["liga"], p["visita"], p["fecha_str"])
        pct, bin4 = calcular_momento_bin(cur, p["liga"], p["fecha"])
        p["n_acum_l"] = n_l
        p["n_acum_v"] = n_v
        p["pct_temp"] = pct
        p["momento_bin_4"] = bin4
        if n_l is not None and bin4 is not None:
            enriched += 1
    print(f"  N enriquecidos con n_acum_l+momento: {enriched}/{len(picks)}")
    con.close()

    # Listar ligas no enriquecidas
    no_enriched_ligas = {}
    for p in picks:
        if p.get("n_acum_l") is None:
            no_enriched_ligas[p["liga"]] = no_enriched_ligas.get(p["liga"], 0) + 1
    print(f"\n  Picks NO cubiertos por historial_equipos_stats:")
    for liga, n in sorted(no_enriched_ligas.items(), key=lambda x: -x[1]):
        print(f"    {liga:<15s} N={n}")

    # Filtrar a enriquecidos
    rows_full = [p for p in picks if p.get("n_acum_l") is not None and p.get("momento_bin_4") is not None]
    print(f"\n  N triangulable: {len(rows_full)}")

    payload = {
        "n_total_picks": len(picks),
        "n_triangulable": len(rows_full),
        "ligas_excluidas_no_cobertura": no_enriched_ligas,
        "tests": {},
    }

    # ==========================================
    # TR1. Replica del hallazgo n_acum sobre picks reales
    # ==========================================
    print("\n=== TR1. Yield real por n_acum_l_bucket (stake real) ===")
    print(f"{'bucket':<14} {'N':>4} {'Hit%':>6} {'Stake$':>10} {'P/L $':>10} {'Yield%':>8} {'CI95':>20}")
    tr1 = {}
    for b, lo, hi in [("<10",0,10),("10-29",10,30),("30-59",30,60),(">=60",60,9999)]:
        sub = [p for p in rows_full if lo <= p["n_acum_l"] < hi]
        m = yield_metrics(sub, usar_stake=True)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        sum_s = sum(p["stake"] for p in sub if p["stake"] > 0)
        sum_p = sum(p["pl"] for p in sub if p["stake"] > 0)
        print(f"{b:<14} {m['n_apost']:>4} {m['hit_pct']:>6.1f} {sum_s:>10,.0f} {sum_p:>+10,.0f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        tr1[b] = m
    payload["tests"]["TR1_n_acum_real"] = tr1

    # ==========================================
    # TR2. Yield real por momento_bin_4
    # ==========================================
    print("\n=== TR2. Yield real por momento_bin_4 (stake real) ===")
    print(f"{'momento':<14} {'N':>4} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    tr2 = {}
    for b, label in [(0,"Q1_arr"),(1,"Q2_ini"),(2,"Q3_mit"),(3,"Q4_cie")]:
        sub = [p for p in rows_full if p["momento_bin_4"] == b]
        m = yield_metrics(sub, usar_stake=True)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{label:<14} {m['n_apost']:>4} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        tr2[label] = m
    payload["tests"]["TR2_momento_real"] = tr2

    # ==========================================
    # TR3. Filtros operativos sobre picks reales
    # ==========================================
    print("\n=== TR3. Filtros operativos sobre picks reales (stake real) ===")
    print(f"{'Filtro':<40} {'N':>4} {'Hit%':>6} {'Stake$':>10} {'P/L $':>10} {'Yield%':>8} {'CI95':>20}")
    filtros = {
        "BASELINE (todos triangulables)": rows_full,
        "Excluir n_acum_l>=60": [p for p in rows_full if p["n_acum_l"] < 60],
        "Excluir momento Q4": [p for p in rows_full if p["momento_bin_4"] != 3],
        "Excluir (n_acum>=60 OR Q4)": [p for p in rows_full if p["n_acum_l"] < 60 and p["momento_bin_4"] != 3],
        "TOP-5 ligas (Arg/Bra/Ing/Nor/Tur)": [p for p in rows_full if p["liga"] in {"Argentina","Brasil","Inglaterra","Noruega","Turquia"}],
        "TOP-5 + excluir (n_acum>=60 OR Q4)": [p for p in rows_full
            if p["liga"] in {"Argentina","Brasil","Inglaterra","Noruega","Turquia"}
            and p["n_acum_l"] < 60 and p["momento_bin_4"] != 3],
    }
    tr3 = {}
    for nombre, sub in filtros.items():
        m = yield_metrics(sub, usar_stake=True)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        sum_s = sum(p["stake"] for p in sub if p["stake"] > 0)
        sum_p = sum(p["pl"] for p in sub if p["stake"] > 0)
        print(f"{nombre:<40} {m['n_apost']:>4} {m['hit_pct']:>6.1f} {sum_s:>10,.0f} {sum_p:>+10,.0f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        tr3[nombre] = m
    payload["tests"]["TR3_filtros_reales"] = tr3

    # ==========================================
    # TR4. UNITARIO (sin stake real, todos los GANADA/PERDIDA)
    # ==========================================
    print("\n=== TR4. UNITARIO sin stake (todos los picks GANADA/PERDIDA) ===")
    print(f"{'Filtro':<40} {'N':>4} {'Hit%':>6} {'Yield%':>8} {'CI95':>20}")
    tr4 = {}
    for nombre, sub in filtros.items():
        m = yield_metrics(sub, usar_stake=False)
        ci_str = f"[{m['ci95_lo']:>+5.1f},{m['ci95_hi']:>+5.1f}]" if m['ci95_lo'] is not None else "n/a"
        print(f"{nombre:<40} {m['n_apost']:>4} {m['hit_pct']:>6.1f} {m['yield_pct']:>+8.1f} {ci_str:>20}")
        tr4[nombre] = m
    payload["tests"]["TR4_filtros_unitario"] = tr4

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")


if __name__ == "__main__":
    main()

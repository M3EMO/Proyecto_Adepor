"""adepor-3ip Audit M.2/M.3 IN-SAMPLE 2026 con calendario CORRECTO (post fix).

Pregunta usuario: ¿Como es el cambio in-sample con el fix del calendario?

Comparativa:
  M.2/M.3 OLD: usaba momento_bin via rango observado (in-progress) -> bloqueaba
                Argentina/Brasil/Noruega como Q4 incorrectamente.
  M.2/M.3 NEW: usa liga_calendario_temp -> Argentina Q3, Brasil Q1, etc.

Audit:
  - Para cada pick real 2026-03/04 (Backtest_Modelo.xlsx hoja Si Hubiera):
    1. Computar momento_bin OLD (rango observado).
    2. Computar momento_bin NEW (calendario fix).
    3. Aplicar filtros M.2 + M.3 OLD y M.2 + M.3 NEW.
    4. Comparar: ¿que picks deja pasar cada uno? Yield comparativo.
  - Por liga, mostrar discrepancias OLD vs NEW.
"""
from __future__ import annotations

import json
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
OUT = Path(__file__).resolve().parent / "audit_M2_M3_in_sample_calendario_fix.json"


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


def momento_bin_OLD(con, liga, fecha_str):
    """Metodo viejo: rango observado en historial_equipos_stats por (liga, ano)."""
    cur = con.cursor()
    ano = fecha_str[:4]
    r = cur.execute("""
        SELECT MIN(fecha), MAX(fecha), COUNT(*) FROM historial_equipos_stats
        WHERE liga=? AND substr(fecha,1,4)=?
    """, (liga, ano)).fetchone()
    if not r or r[2] is None or r[2] < 10: return None
    f_min, f_max = r[0][:10], r[1][:10]
    if not f_min or not f_max: return None
    f_max_ef = f_max if fecha_str <= f_max else fecha_str
    r_pct = cur.execute(
        "SELECT julianday(?) - julianday(?), julianday(?) - julianday(?)",
        (fecha_str, f_min, f_max_ef, f_min)).fetchone()
    delta_p, delta_t = r_pct[0], r_pct[1]
    if delta_t is None or delta_t <= 0: return None
    pct = max(0.0, min(1.0, delta_p / delta_t))
    if pct < 0.25: return 0
    if pct < 0.50: return 1
    if pct < 0.75: return 2
    return 3


def momento_bin_NEW(con, liga, fecha_str):
    """Metodo nuevo: calendario individual desde liga_calendario_temp."""
    cur = con.cursor()
    ano = int(fecha_str[:4])
    for temp in (ano, ano + 1):
        r = cur.execute("""
            SELECT fecha_inicio, fecha_fin FROM liga_calendario_temp
            WHERE liga=? AND temp=?
        """, (liga, temp)).fetchone()
        if not r: continue
        if r[0] <= fecha_str <= r[1]:
            f_min, f_max = r[0], r[1]
            r_pct = cur.execute(
                "SELECT julianday(?) - julianday(?), julianday(?) - julianday(?)",
                (fecha_str, f_min, f_max, f_min)).fetchone()
            delta_p, delta_t = r_pct[0], r_pct[1]
            if delta_t and delta_t > 0:
                pct = max(0.0, min(1.0, delta_p / delta_t))
                if pct < 0.25: return 0
                if pct < 0.50: return 1
                if pct < 0.75: return 2
                return 3
    return None


def lookup_n_acum(con, liga, equipo, fecha_str):
    cur = con.cursor()
    r = cur.execute("""
        SELECT n_acum FROM historial_equipos_stats
        WHERE liga=? AND equipo=? AND fecha < ? AND n_acum >= 5
        ORDER BY fecha DESC LIMIT 1
    """, (liga, equipo, fecha_str)).fetchone()
    return r[0] if r else None


LIGAS_TOP5 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}


def main():
    print("Cargando picks reales 2026-03/04...")
    picks = cargar_picks_reales()
    print(f"  N picks total: {len(picks)}")
    con = sqlite3.connect(DB)

    # Enriquecer cada pick con momento_bin OLD/NEW + n_acum_l
    print("\nEnriqueciendo picks con momento_bin OLD/NEW + n_acum...")
    for p in picks:
        if not p["liga"] or not p["local"]:
            continue
        p["bin_OLD"] = momento_bin_OLD(con, p["liga"], p["fecha_str"])
        p["bin_NEW"] = momento_bin_NEW(con, p["liga"], p["fecha_str"])
        p["n_acum_l"] = lookup_n_acum(con, p["liga"], p["local"], p["fecha_str"])

    # Comparativa OLD vs NEW: cuántos picks bloquearia cada filtro
    print("\n=== Comparativa M.3 OLD vs NEW por liga ===")
    print(f"{'liga':<14} | {'N_total':>8} | {'M3 OLD bloq':>12} | {'M3 NEW bloq':>12} | {'discrepancias':>14}")
    print("-" * 80)
    discrepancias = defaultdict(lambda: {"total": 0, "old_bloq": 0, "new_bloq": 0,
                                          "ambos_bloq": 0, "discrep": 0,
                                          "old_si_new_no": 0, "old_no_new_si": 0})
    for p in picks:
        liga = p.get("liga")
        if not liga: continue
        d = discrepancias[liga]
        d["total"] += 1
        old_b = p.get("bin_OLD") == 3
        new_b = p.get("bin_NEW") == 3
        if old_b: d["old_bloq"] += 1
        if new_b: d["new_bloq"] += 1
        if old_b and new_b: d["ambos_bloq"] += 1
        if old_b != new_b:
            d["discrep"] += 1
            if old_b: d["old_si_new_no"] += 1
            else: d["old_no_new_si"] += 1
    for liga in sorted(discrepancias.keys()):
        d = discrepancias[liga]
        print(f"{liga:<14} | {d['total']:>8} | {d['old_bloq']:>12} | {d['new_bloq']:>12} | "
              f"{d['discrep']:>14} (OLD si/NEW no={d['old_si_new_no']}, OLD no/NEW si={d['old_no_new_si']})")

    # Yield real comparativo aplicando los filtros
    print("\n=== Yield real comparativo (M.2 + M.3 con stake real $) ===")
    print(f"{'subset':<55} {'N':>4} {'Hit%':>6} {'Stake$':>10} {'P/L $':>10} {'Yield%':>8}")
    LIGAS_TOP5 = {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"}
    payload_yield = {}
    for nombre, fn in [
        ("BASELINE (todos liquidados con stake>0)",
         lambda p: p["stake"] > 0),
        ("M.1 solo (TOP-5 ligas)",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5),
        ("M.1 + M.2 (TOP-5 + n_acum<60)",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5
                   and (p.get("n_acum_l") is None or p["n_acum_l"] < 60)),
        ("M.1 + M.3 OLD (TOP-5 + bin_OLD!=Q4)",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5
                   and p.get("bin_OLD") != 3),
        ("M.1 + M.3 NEW (TOP-5 + bin_NEW!=Q4)",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5
                   and p.get("bin_NEW") != 3),
        ("M.1 + M.2 + M.3 OLD",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5
                   and (p.get("n_acum_l") is None or p["n_acum_l"] < 60)
                   and p.get("bin_OLD") != 3),
        ("M.1 + M.2 + M.3 NEW",
         lambda p: p["stake"] > 0 and p["liga"] in LIGAS_TOP5
                   and (p.get("n_acum_l") is None or p["n_acum_l"] < 60)
                   and p.get("bin_NEW") != 3),
    ]:
        sub = [p for p in picks if fn(p)]
        n = len(sub)
        g = sum(1 for p in sub if p["resultado"] == "GANADA")
        sum_s = sum(p["stake"] for p in sub)
        sum_pl = sum(p["pl"] for p in sub)
        yld = sum_pl / sum_s * 100 if sum_s > 0 else 0
        hit = g / n * 100 if n > 0 else 0
        print(f"{nombre:<55} {n:>4} {hit:>6.1f} {sum_s:>10,.0f} {sum_pl:>+10,.0f} {yld:>+8.1f}")
        payload_yield[nombre] = {"n": n, "hit_pct": round(hit, 2),
                                   "sum_stake": round(sum_s, 2), "sum_pl": round(sum_pl, 2),
                                   "yield_pct": round(yld, 2)}

    # Por liga TOP-5, ¿que pasa con M.3 OLD vs NEW?
    print("\n=== Por liga TOP-5: efecto M.3 OLD vs NEW (con stake real $) ===")
    for liga in sorted(LIGAS_TOP5):
        sub_total = [p for p in picks if p["liga"] == liga and p["stake"] > 0]
        if not sub_total: continue
        sub_old = [p for p in sub_total if p.get("bin_OLD") != 3]
        sub_new = [p for p in sub_total if p.get("bin_NEW") != 3]

        def metrica(pp):
            n = len(pp); g = sum(1 for p in pp if p["resultado"] == "GANADA")
            s = sum(p["stake"] for p in pp); pl = sum(p["pl"] for p in pp)
            yld = pl / s * 100 if s > 0 else 0
            return {"n": n, "hit_pct": round(g/n*100, 1) if n else 0,
                    "yield_pct": round(yld, 1), "stake": round(s, 0), "pl": round(pl, 0)}

        m_total = metrica(sub_total)
        m_old = metrica(sub_old)
        m_new = metrica(sub_new)
        print(f"  {liga:<14}: BASELINE N={m_total['n']:>3} y={m_total['yield_pct']:+5.1f}% | "
              f"M.3 OLD N={m_old['n']:>3} y={m_old['yield_pct']:+5.1f}% | "
              f"M.3 NEW N={m_new['n']:>3} y={m_new['yield_pct']:+5.1f}%")

    payload = {
        "fecha": datetime.now().isoformat(),
        "n_picks_total": len(picks),
        "discrepancias_por_liga": dict(discrepancias),
        "yield_filtros": payload_yield,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

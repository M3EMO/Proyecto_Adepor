"""Fase 3 (adepor-6kw): analisis posesion x xG x outcome.

Pregunta del usuario: ¿mayor % posesion → mayor xG? Y ¿mejor yield/hit?

Setup: tabla stats_partido_espn (poblada por fase3_scraper_posesion.py)
JOIN con momento_temporada + posicion_tabla + (predicciones_walkforward para
xG modelado y outcome).

Para cada (in-sample, OOS) y cada granularidad (bin4, bin8, bin12):

  1. Correlacion possess_local x xG_local agregada (Pearson, OLS)
  2. Por liga (15 ligas)
  3. Por equipo dentro de su liga (top equipos por N partidos)
  4. Por momento_bin
  5. Por temp (OOS)

Output:
  analisis/fase3_correlacion_pos_xg.json
  analisis/fase3_pos_x_yield_oos_bin{N}.json (3, c/u con agregado + por_temp)
  graficos/fase3_*.png
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
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

# Buckets de posesion
POS_BUCKETS = [
    ("muy_baja", 0, 35),     # vs altura "vis_mucho_mejor"
    ("baja", 35, 45),
    ("media", 45, 55),
    ("alta", 55, 65),
    ("muy_alta", 65, 100),
]


def pos_bucket(pct):
    if pct is None:
        return None
    for name, lo, hi in POS_BUCKETS:
        if lo <= pct < hi:
            return name
    return None


def correlacion_pearson(xs, ys):
    if len(xs) < 5:
        return None
    x = np.array(xs, dtype=float)
    y = np.array(ys, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def ols_simple(xs, ys):
    """Regresion lineal y = beta * x + alfa. Devuelve (beta, alfa, r2)."""
    if len(xs) < 5:
        return None
    x = np.array(xs, dtype=float)
    y = np.array(ys, dtype=float)
    if x.std() == 0:
        return None
    beta, alfa = np.polyfit(x, y, 1)
    y_pred = beta * x + alfa
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {"beta": float(beta), "alfa": float(alfa), "r2": float(r2), "n": len(xs)}


def cargar_data_correlacion(con):
    """Carga partidos con possess + stats reales para correlation analysis.
    Calcula xG proxy desde stats reales (formula del Manifiesto §II.A simplificada):
      xG = 0.10*shots + 0.30*shots_on_target + 0.10*corners
    Esto es xG REAL del partido (no del modelo). Para comparar con possess.
    """
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac,
               h_pos, a_pos
        FROM stats_partido_espn
        WHERE h_pos IS NOT NULL AND a_pos IS NOT NULL
    """).fetchall()
    out = []
    for r in rows:
        liga, temp, fecha, ht, at, hg, ag, hst, ast, hs, as_, hc, ac, h_pos, a_pos = r
        # xG proxy local desde stats reales
        if hst is None or hs is None or hc is None:
            continue
        if ast is None or as_ is None or ac is None:
            continue
        xg_l = 0.10 * (hs or 0) + 0.30 * (hst or 0) + 0.10 * (hc or 0)
        xg_v = 0.10 * (as_ or 0) + 0.30 * (ast or 0) + 0.10 * (ac or 0)
        out.append({
            "liga": liga, "temp": temp, "fecha": fecha,
            "ht": ht, "at": at, "hg": hg, "ag": ag,
            "h_pos": h_pos, "a_pos": a_pos,
            "xg_l_proxy": xg_l, "xg_v_proxy": xg_v,
            "outcome": "1" if (hg or 0) > (ag or 0) else ("X" if (hg or 0) == (ag or 0) else "2"),
        })
    return out


def analisis_correlacion(rows):
    """Analisis correlacion possess vs xG en multiples cortes."""
    payload = {"n_total": len(rows), "buckets_pos": [b[0] for b in POS_BUCKETS]}

    # === GLOBAL ===
    print(f"\n=== GLOBAL: posesion vs xG_proxy ===")
    print(f"N: {len(rows)}")
    pos_l = [r["h_pos"] for r in rows]
    pos_v = [r["a_pos"] for r in rows]
    xg_l = [r["xg_l_proxy"] for r in rows]
    xg_v = [r["xg_v_proxy"] for r in rows]

    # Combinar local + visita (cada partido 2 obs)
    pos_all = pos_l + pos_v
    xg_all = xg_l + xg_v
    corr_global = correlacion_pearson(pos_all, xg_all)
    ols_global = ols_simple(pos_all, xg_all)
    print(f"  Pearson(pos, xG_proxy) global: {corr_global:.4f}")
    if ols_global:
        print(f"  OLS: xG = {ols_global['beta']:.4f} * pos + {ols_global['alfa']:.4f}  R²={ols_global['r2']:.4f}")
    payload["global"] = {"pearson": corr_global, "ols": ols_global,
                          "n_obs": len(pos_all)}

    # Solo local
    corr_l = correlacion_pearson(pos_l, xg_l)
    ols_l = ols_simple(pos_l, xg_l)
    print(f"  LOCAL Pearson: {corr_l:.4f}")
    if ols_l:
        print(f"    OLS: xG_l = {ols_l['beta']:.4f} * pos_l + {ols_l['alfa']:.4f}  R²={ols_l['r2']:.4f}")
    payload["local"] = {"pearson": corr_l, "ols": ols_l, "n_obs": len(pos_l)}

    # Solo visita
    corr_v = correlacion_pearson(pos_v, xg_v)
    ols_v = ols_simple(pos_v, xg_v)
    print(f"  VISITA Pearson: {corr_v:.4f}")
    if ols_v:
        print(f"    OLS: xG_v = {ols_v['beta']:.4f} * pos_v + {ols_v['alfa']:.4f}  R²={ols_v['r2']:.4f}")
    payload["visita"] = {"pearson": corr_v, "ols": ols_v, "n_obs": len(pos_v)}

    # === POR LIGA ===
    print(f"\n=== POR LIGA ===")
    print(f"{'Liga':<14} {'N':>5} {'Pearson':>9} {'beta':>8} {'R²':>6}")
    payload["por_liga"] = {}
    por_liga = defaultdict(list)
    for r in rows:
        por_liga[r["liga"]].append(r)
    for liga in sorted(por_liga.keys()):
        sub = por_liga[liga]
        if len(sub) < 30:
            continue
        pos_all = [r["h_pos"] for r in sub] + [r["a_pos"] for r in sub]
        xg_all = [r["xg_l_proxy"] for r in sub] + [r["xg_v_proxy"] for r in sub]
        corr = correlacion_pearson(pos_all, xg_all)
        ols = ols_simple(pos_all, xg_all)
        if corr is not None and ols:
            print(f"{liga:<14} {len(sub):>5} {corr:>+9.4f} {ols['beta']:>+8.4f} {ols['r2']:>6.4f}")
            payload["por_liga"][liga] = {
                "n_partidos": len(sub), "n_obs": len(pos_all),
                "pearson": corr, "ols": ols,
            }

    # === POR TEMP ===
    print(f"\n=== POR TEMP ===")
    print(f"{'Temp':<6} {'N':>5} {'Pearson':>9} {'beta':>8} {'R²':>6}")
    payload["por_temp"] = {}
    por_temp = defaultdict(list)
    for r in rows:
        por_temp[r["temp"]].append(r)
    for temp in sorted(por_temp.keys()):
        sub = por_temp[temp]
        pos_all = [r["h_pos"] for r in sub] + [r["a_pos"] for r in sub]
        xg_all = [r["xg_l_proxy"] for r in sub] + [r["xg_v_proxy"] for r in sub]
        corr = correlacion_pearson(pos_all, xg_all)
        ols = ols_simple(pos_all, xg_all)
        if corr is not None and ols:
            print(f"{temp:<6} {len(sub):>5} {corr:>+9.4f} {ols['beta']:>+8.4f} {ols['r2']:>6.4f}")
            payload["por_temp"][str(temp)] = {
                "n_partidos": len(sub), "pearson": corr, "ols": ols,
            }

    # === POR EQUIPO (dentro de su liga, top N) ===
    print(f"\n=== POR EQUIPO (top equipos con N>=20 partidos) ===")
    payload["por_equipo"] = {}
    por_equipo = defaultdict(list)  # (liga, equipo) -> [(pos, xG)]
    for r in rows:
        # Local
        por_equipo[(r["liga"], r["ht"])].append((r["h_pos"], r["xg_l_proxy"]))
        # Visita
        por_equipo[(r["liga"], r["at"])].append((r["a_pos"], r["xg_v_proxy"]))
    print(f"{'Liga':<14} {'Equipo':<28} {'N':>4} {'Pearson':>9} {'beta':>8} {'R²':>6} {'pos_avg':>7} {'xG_avg':>6}")
    eq_resultados = []
    for (liga, eq), obs in por_equipo.items():
        if len(obs) < 20:
            continue
        pos_arr = [o[0] for o in obs]
        xg_arr = [o[1] for o in obs]
        corr = correlacion_pearson(pos_arr, xg_arr)
        ols = ols_simple(pos_arr, xg_arr)
        if corr is not None and ols:
            eq_resultados.append({
                "liga": liga, "equipo": eq, "n": len(obs),
                "pearson": corr, "ols": ols,
                "pos_avg": float(np.mean(pos_arr)),
                "xg_avg": float(np.mean(xg_arr)),
            })
    # Ordenar por |pearson| desc
    eq_resultados.sort(key=lambda x: -abs(x["pearson"]))
    for e in eq_resultados[:30]:
        print(f"{e['liga']:<14} {e['equipo'][:26]:<28} {e['n']:>4} "
              f"{e['pearson']:>+9.4f} {e['ols']['beta']:>+8.4f} {e['ols']['r2']:>6.4f} "
              f"{e['pos_avg']:>7.1f} {e['xg_avg']:>6.2f}")
    payload["por_equipo"] = eq_resultados

    return payload


def analisis_pos_buckets_outcome(rows):
    """Analisis: por bucket de posesion, ¿hit local? (cuántas veces gana el local)."""
    print(f"\n=== Por bucket de posesion LOCAL: hit local? ===")
    print(f"{'Bucket':<14} {'N':>5} {'Hit_local%':>11} {'Empate%':>9} {'Hit_visita%':>11}")
    payload = {}
    for name, lo, hi in POS_BUCKETS:
        sub = [r for r in rows if lo <= r["h_pos"] < hi]
        if len(sub) < 20:
            continue
        n = len(sub)
        n_l = sum(1 for r in sub if r["outcome"] == "1")
        n_e = sum(1 for r in sub if r["outcome"] == "X")
        n_v = sum(1 for r in sub if r["outcome"] == "2")
        print(f"{name:<14} {n:>5} {n_l*100/n:>10.1f}% {n_e*100/n:>8.1f}% {n_v*100/n:>10.1f}%")
        payload[name] = {"n": n, "hit_local_pct": n_l*100/n,
                          "empate_pct": n_e*100/n, "hit_visita_pct": n_v*100/n}
    return payload


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    n_stats = cur.execute("SELECT COUNT(*) FROM stats_partido_espn WHERE h_pos IS NOT NULL").fetchone()[0]
    print(f"=== FASE 3 — Analisis posesion x xG x outcome ===")
    print(f"N partidos con posesion en stats_partido_espn: {n_stats}")
    if n_stats < 100:
        print("[FATAL] Insuficientes partidos con posesion. Ejecutar primero:")
        print("  py analisis/fase3_scraper_posesion.py --enriquecer-latam")
        print("  py analisis/fase3_scraper_posesion.py --scrape-eur")
        print("  py analisis/fase3_scraper_posesion.py --persistir-db")
        return

    rows = cargar_data_correlacion(con)
    print(f"Filas con stats completos: {len(rows)}")

    payload = {"n_total": len(rows)}
    payload["correlacion"] = analisis_correlacion(rows)
    payload["pos_buckets_outcome"] = analisis_pos_buckets_outcome(rows)

    # Persistir
    out = OUT_DIR / "fase3_correlacion_pos_xg.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")
    con.close()


if __name__ == "__main__":
    main()

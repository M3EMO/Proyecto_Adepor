"""Fase 3 (parte 2): analisis completo de TODAS las stats ESPN.

Para cada stat (h_*, a_*) evalua:
  1. Correlacion individual con xG_proxy (Pearson, OLS β, R²)
  2. Por liga, por temp
  3. En conjunto: OLS multivariable xG ~ stats[features] (regresion completa)
  4. Importancia relativa via |coef * std(stat) / std(xG)| (semi-standardized)

Tambien: yield del motor por bucket de cada stat (Q1/Q3 percentil).

Output:
  analisis/fase3_stats_correlaciones.json
  analisis/fase3_stats_yield.json
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

MARGEN_MIN = 0.05
EV_MIN = 0.03
KELLY_CAP = 0.025

# Stats a evaluar (key_local, key_visita, label, tipo)
# tipo: "abs" (cantidad), "pct" (porcentaje 0-100 o 0-1)
STATS = [
    ("h_pos", "a_pos", "posesion", "pct"),
    ("h_passes", "a_passes", "pases_total", "abs"),
    ("h_passes_acc", "a_passes_acc", "pases_acertados", "abs"),
    ("h_pass_pct", "a_pass_pct", "pass_pct", "pct"),
    ("h_crosses", "a_crosses", "crosses_total", "abs"),
    ("h_crosses_acc", "a_crosses_acc", "crosses_acertados", "abs"),
    ("h_cross_pct", "a_cross_pct", "cross_pct", "pct"),
    ("h_longballs", "a_longballs", "longballs_total", "abs"),
    ("h_longballs_acc", "a_longballs_acc", "longballs_acertados", "abs"),
    ("h_longball_pct", "a_longball_pct", "longball_pct", "pct"),
    ("hs", "as_v", "shots_total", "abs"),
    ("hst", "ast", "shots_on_target", "abs"),
    ("h_shot_pct", "a_shot_pct", "shot_pct", "pct"),
    ("h_blocks", "a_blocks", "blocks", "abs"),
    ("hc", "ac", "corners", "abs"),
    ("h_pk_goals", "a_pk_goals", "pk_goals", "abs"),
    ("h_pk_shots", "a_pk_shots", "pk_shots", "abs"),
    ("h_fouls", "a_fouls", "fouls", "abs"),
    ("h_yellow", "a_yellow", "yellow", "abs"),
    ("h_red", "a_red", "red", "abs"),
    ("h_offsides", "a_offsides", "offsides", "abs"),
    ("h_saves", "a_saves", "saves", "abs"),
    ("h_tackles", "a_tackles", "tackles", "abs"),
    ("h_tackles_eff", "a_tackles_eff", "tackles_eff", "abs"),
    ("h_tackle_pct", "a_tackle_pct", "tackle_pct", "pct"),
    ("h_interceptions", "a_interceptions", "interceptions", "abs"),
    ("h_clearance", "a_clearance", "clearance", "abs"),
    ("h_clearance_eff", "a_clearance_eff", "clearance_eff", "abs"),
]


def correlacion_pearson(xs, ys):
    if len(xs) < 5:
        return None
    x = np.array(xs, dtype=float)
    y = np.array(ys, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def ols_simple(xs, ys):
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
    return {"beta": float(beta), "alfa": float(alfa), "r2": float(r2),
            "n": len(xs), "x_std": float(x.std()), "y_std": float(y.std())}


def ols_multivariable(X, y, feature_names):
    """OLS multivariable usando numpy.lstsq. Devuelve dict con betas + R²."""
    if len(X) < 30:
        return None
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)
    # Constante
    X_aug = np.column_stack([np.ones(len(X)), X])
    coefs, residuals, rank, sv = np.linalg.lstsq(X_aug, y, rcond=None)
    y_pred = X_aug @ coefs
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    # Importancia semi-standardized: |coef * std(x) / std(y)|
    y_std = y.std() if y.std() > 0 else 1
    importancias = {}
    for i, fname in enumerate(feature_names):
        x_std = X[:, i].std() if X[:, i].std() > 0 else 0
        imp = abs(coefs[i + 1] * x_std / y_std)
        importancias[fname] = {"coef": float(coefs[i + 1]), "importancia": float(imp)}
    return {
        "intercepto": float(coefs[0]),
        "r2": float(r2), "n": len(X),
        "features": importancias,
    }


def cargar_data(con):
    """Carga partidos con stats completas + xG proxy."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT * FROM stats_partido_espn WHERE h_pos IS NOT NULL
    """).fetchall()
    cols = [d[0] for d in cur.description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("hst") is None or d.get("hs") is None or d.get("hc") is None:
            continue
        d["xg_l_proxy"] = 0.10 * (d.get("hs") or 0) + 0.30 * (d.get("hst") or 0) + 0.10 * (d.get("hc") or 0)
        d["xg_v_proxy"] = 0.10 * (d.get("as_v") or 0) + 0.30 * (d.get("ast") or 0) + 0.10 * (d.get("ac") or 0)
        d["outcome"] = "1" if (d.get("hg") or 0) > (d.get("ag") or 0) else \
                        ("X" if (d.get("hg") or 0) == (d.get("ag") or 0) else "2")
        out.append(d)
    return out


def analizar_stat_individual(rows, h_key, a_key, label):
    """Analiza correlacion entre una stat y xG_proxy. Combina local+visita."""
    stat_vals = []
    xg_vals = []
    for r in rows:
        if r.get(h_key) is not None and r.get("xg_l_proxy") is not None:
            stat_vals.append(r[h_key])
            xg_vals.append(r["xg_l_proxy"])
        if r.get(a_key) is not None and r.get("xg_v_proxy") is not None:
            stat_vals.append(r[a_key])
            xg_vals.append(r["xg_v_proxy"])
    if len(stat_vals) < 30:
        return None
    return {
        "n": len(stat_vals),
        "pearson": correlacion_pearson(stat_vals, xg_vals),
        "ols": ols_simple(stat_vals, xg_vals),
        "stat_mean": float(np.mean(stat_vals)),
        "stat_std": float(np.std(stat_vals)),
    }


def main():
    con = sqlite3.connect(DB)
    rows = cargar_data(con)
    print(f"=== FASE 3 STATS COMPLETO ===")
    print(f"N partidos con stats completas: {len(rows)}")
    if len(rows) < 100:
        print("[FATAL] N insuficiente. Esperar scraper.")
        return

    # === 1. Correlacion individual de cada stat ===
    print(f"\n=== 1. CORRELACION INDIVIDUAL stat vs xG_proxy ===")
    print(f"{'Stat':<25} {'N obs':>6} {'Pearson':>9} {'beta':>9} {'R²':>6} {'mean':>8} {'std':>8}")
    payload = {"n_partidos": len(rows), "stats_individuales": {}}
    resultados = []
    for h_key, a_key, label, tipo in STATS:
        r = analizar_stat_individual(rows, h_key, a_key, label)
        if not r:
            continue
        resultados.append((label, r))
        payload["stats_individuales"][label] = r

    # Ordenar por |pearson| desc
    resultados.sort(key=lambda x: -abs(x[1].get("pearson") or 0))
    for label, r in resultados:
        ols = r["ols"]
        beta_str = f"{ols['beta']:>+9.5f}" if ols else "       -"
        r2_str = f"{ols['r2']:>6.4f}" if ols else "     -"
        print(f"{label:<25} {r['n']:>6} {r['pearson']:>+9.4f} {beta_str} {r2_str} "
              f"{r['stat_mean']:>8.2f} {r['stat_std']:>8.2f}")

    # === 2. OLS multivariable: xG ~ stats EXCLUYENDO los componentes del proxy ===
    # Importante: shots, sots, corners definen xG_proxy. Si los incluimos R²=1.0 trivial.
    # Por eso usamos solo features ortogonales para inferir poder predictivo real.
    print(f"\n=== 2. OLS MULTIVARIABLE xG_proxy ~ stats (excl. componentes proxy) ===")
    feature_keys = [(h, a, lbl) for h, a, lbl, _ in STATS if lbl in (
        "posesion", "pass_pct", "blocks", "fouls", "yellow", "red", "saves",
        "tackles", "tackle_pct", "interceptions", "clearance", "longballs_total",
        "longball_pct", "crosses_total", "cross_pct", "offsides", "pk_shots"
    )]
    X = []
    y = []
    for r in rows:
        # Local
        feats_l = []
        ok = True
        for h, _, lbl in feature_keys:
            v = r.get(h)
            if v is None:
                ok = False
                break
            feats_l.append(v)
        if ok:
            X.append(feats_l)
            y.append(r["xg_l_proxy"])
        # Visita
        feats_v = []
        ok = True
        for _, a, lbl in feature_keys:
            v = r.get(a)
            if v is None:
                ok = False
                break
            feats_v.append(v)
        if ok:
            X.append(feats_v)
            y.append(r["xg_v_proxy"])

    feature_names = [lbl for _, _, lbl in feature_keys]
    ols_multi = ols_multivariable(X, y, feature_names)
    if ols_multi:
        print(f"N: {ols_multi['n']}")
        print(f"R² multivariable: {ols_multi['r2']:.4f} (vs R² univariable max: {max(r[1]['ols']['r2'] for r in resultados):.4f})")
        print(f"Intercepto: {ols_multi['intercepto']:+.4f}")
        # Ordenar por importancia
        feats_sorted = sorted(ols_multi["features"].items(),
                                key=lambda kv: -kv[1]["importancia"])
        print(f"\n{'Feature':<25} {'coef':>12} {'importancia':>12}")
        for fname, info in feats_sorted:
            print(f"{fname:<25} {info['coef']:>+12.5f} {info['importancia']:>12.4f}")
    payload["ols_multivariable"] = ols_multi

    # === 3. Por liga ===
    print(f"\n=== 3. CORRELACION TOP STATS por liga ===")
    payload["por_liga"] = {}
    por_liga = defaultdict(list)
    for r in rows:
        por_liga[r["liga"]].append(r)
    # Las top 5 stats globales
    top5 = [r[0] for r in resultados[:5]]
    print(f"Top 5 stats globales: {top5}")
    for liga in sorted(por_liga.keys()):
        sub = por_liga[liga]
        if len(sub) < 50:
            continue
        liga_data = {}
        for h_key, a_key, label, tipo in STATS:
            if label not in top5:
                continue
            r = analizar_stat_individual(sub, h_key, a_key, label)
            if r:
                liga_data[label] = r
        payload["por_liga"][liga] = {"n_partidos": len(sub), "stats": liga_data}
        print(f"\n  {liga} (N={len(sub)}):")
        for label in top5:
            if label in liga_data:
                ld = liga_data[label]
                print(f"    {label:<22} Pearson={ld['pearson']:>+7.4f}  R²={ld['ols']['r2']:>6.4f}")

    # === 4. Por temp ===
    print(f"\n=== 4. CORRELACION TOP STATS por temp ===")
    payload["por_temp"] = {}
    por_temp = defaultdict(list)
    for r in rows:
        por_temp[r["temp"]].append(r)
    for temp in sorted(por_temp.keys()):
        sub = por_temp[temp]
        if len(sub) < 100:
            continue
        temp_data = {}
        for h_key, a_key, label, tipo in STATS:
            r = analizar_stat_individual(sub, h_key, a_key, label)
            if r:
                temp_data[label] = r
        payload["por_temp"][str(temp)] = {"n_partidos": len(sub), "stats": temp_data}
        print(f"\n  Temp {temp} (N={len(sub)}) — top 5 |Pearson|:")
        sorted_temp = sorted(temp_data.items(), key=lambda kv: -abs(kv[1].get("pearson") or 0))[:5]
        for label, r in sorted_temp:
            print(f"    {label:<22} Pearson={r['pearson']:>+7.4f}  R²={r['ols']['r2']:>6.4f}")

    # Persistir
    out = OUT_DIR / "fase3_stats_correlaciones.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")
    con.close()


if __name__ == "__main__":
    main()

"""OLS extendido: goles ~ SoT + shots_off + corners + faltas + tarjetas.

Test empirico: ¿faltas/tarjetas como proxy de "posesion 3/4s" mejora la R²
del modelo xG vs el actual (solo SoT + shots_off + corners)?

Fuente: football-data.co.uk CSV (EUR) descargado on-the-fly.
ESPN cache_espn no tiene faltas (no las extrajo el scraper original).

Si el R² extendido > base por liga: vale la pena PROPOSAL para agregar
beta_faltas + beta_amarillas como features del xg_hibrido.
"""
import csv
import io
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent

# CSVs football-data
FUENTES_CSV = {
    "Inglaterra": ["E0", [2122, 2223, 2324, 2425]],
    "Italia":     ["I1", [2122, 2223, 2324, 2425]],
    "Espana":     ["SP1", [2122, 2223, 2324, 2425]],
    "Francia":    ["F1", [2122, 2223, 2324, 2425]],
    "Alemania":   ["D1", [2122, 2223, 2324, 2425]],
    "Turquia":    ["T1", [2122, 2223, 2324, 2425]],
}


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig", errors="ignore")


def parse_partidos(texto):
    rows = []
    reader = csv.DictReader(io.StringIO(texto))
    for r in reader:
        try:
            hg = int(r.get("FTHG", "") or 0)
            ag = int(r.get("FTAG", "") or 0)
            if not r.get("HomeTeam") or not r.get("AwayTeam"):
                continue
            rows.append({
                "hg": hg, "ag": ag,
                "hst": int(r.get("HST", 0) or 0),
                "ast": int(r.get("AST", 0) or 0),
                "hs": int(r.get("HS", 0) or 0),
                "as": int(r.get("AS", 0) or 0),
                "hc": int(r.get("HC", 0) or 0),
                "ac": int(r.get("AC", 0) or 0),
                "hf": int(r.get("HF", 0) or 0),    # Home Fouls
                "af": int(r.get("AF", 0) or 0),    # Away Fouls
                "hy": int(r.get("HY", 0) or 0),    # Home Yellows
                "ay": int(r.get("AY", 0) or 0),
                "hr": int(r.get("HR", 0) or 0),    # Home Reds
                "ar": int(r.get("AR", 0) or 0),
            })
        except (ValueError, TypeError):
            continue
    return rows


def ols_fit(X, y):
    n, p = X.shape
    Xc = np.hstack([np.ones((n, 1)), X])
    beta, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    intercept = beta[0]
    coefs = beta[1:]
    y_pred = Xc @ beta
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    rmse = np.sqrt(ss_res / n)
    return coefs, intercept, r2, rmse


def main():
    print("=" * 100)
    print("OLS EXTENDIDO: goles ~ SoT + shots_off + corners + faltas + amarillas + rojas")
    print("=" * 100)
    print()

    out_per_liga = {}
    for liga, (codigo, temps) in FUENTES_CSV.items():
        print(f"--- {liga} ---")
        all_rows = []
        for t in temps:
            url = f"https://www.football-data.co.uk/mmz4281/{t}/{codigo}.csv"
            try:
                rows = parse_partidos(fetch_csv(url))
                all_rows.extend(rows)
            except Exception as e:
                print(f"  err temp {t}: {e}")
        if not all_rows:
            print(f"  sin data")
            continue
        # Filter zero-stats (descartados)
        all_rows = [r for r in all_rows if not (r["hs"] == 0 and r["hst"] == 0)]

        # Build X (home + away pooled, dual obs por partido)
        X_base, X_ext, y = [], [], []
        for r in all_rows:
            for side in ["h", "a"]:
                if side == "h":
                    sot = r["hst"]; shots = r["hs"]; corners = r["hc"]
                    fouls = r["hf"]; yellows = r["hy"]; reds = r["hr"]
                    goles = r["hg"]
                else:
                    sot = r["ast"]; shots = r["as"]; corners = r["ac"]
                    fouls = r["af"]; yellows = r["ay"]; reds = r["ar"]
                    goles = r["ag"]
                shots_off = max(0, shots - sot)
                X_base.append([sot, shots_off, corners])
                X_ext.append([sot, shots_off, corners, fouls, yellows, reds])
                y.append(goles)

        X_base = np.array(X_base, dtype=float)
        X_ext = np.array(X_ext, dtype=float)
        y = np.array(y, dtype=float)

        # OLS base (3 features)
        c_b, i_b, r2_b, rmse_b = ols_fit(X_base, y)
        # OLS extendido (6 features)
        c_e, i_e, r2_e, rmse_e = ols_fit(X_ext, y)

        delta_r2 = r2_e - r2_b
        delta_rmse = rmse_b - rmse_e  # > 0 = ext es mejor (menos error)

        # Significance: bootstrap delta_r2 sobre 100 resamples
        # Si CI 95% > 0 -> mejora significativa
        deltas = []
        rng = np.random.default_rng(42)
        for _ in range(100):
            idx = rng.choice(len(y), size=len(y), replace=True)
            try:
                _, _, r2_b_b, _ = ols_fit(X_base[idx], y[idx])
                _, _, r2_e_b, _ = ols_fit(X_ext[idx], y[idx])
                deltas.append(r2_e_b - r2_b_b)
            except Exception:
                continue
        if deltas:
            ci_lo, ci_hi = np.percentile(deltas, [2.5, 97.5])
        else:
            ci_lo = ci_hi = None

        sig = "SIG" if ci_lo is not None and ci_lo > 0.001 else "NS"

        print(f"  N_obs={len(y)}")
        print(f"  R² base   ={r2_b:.4f}  RMSE_base={rmse_b:.4f}")
        print(f"  R² ext    ={r2_e:.4f}  RMSE_ext={rmse_e:.4f}")
        print(f"  Δ R²      ={delta_r2:+.4f}  CI95=[{ci_lo:+.4f},{ci_hi:+.4f}]  {sig}")
        print(f"  Coef ext: SoT={c_e[0]:+.3f} off={c_e[1]:+.3f} corner={c_e[2]:+.3f} "
              f"faltas={c_e[3]:+.4f} amar={c_e[4]:+.3f} rojas={c_e[5]:+.3f}")
        print()
        out_per_liga[liga] = {
            "n": len(y), "r2_base": r2_b, "r2_ext": r2_e,
            "delta_r2": delta_r2, "ci95": [ci_lo, ci_hi], "sig": sig,
            "coef_ext_faltas": c_e[3], "coef_ext_amarillas": c_e[4], "coef_ext_rojas": c_e[5],
        }

    # Pool global
    print("=" * 100)
    print("Pool global (todas ligas)")
    print("=" * 100)
    n_sig = sum(1 for v in out_per_liga.values() if v["sig"] == "SIG")
    n_ns = len(out_per_liga) - n_sig
    print(f"Significativas (Δ R² > 0 con CI 95%): {n_sig} / {len(out_per_liga)}")
    print(f"No significativas: {n_ns}")
    delta_r2_promedio = np.mean([v["delta_r2"] for v in out_per_liga.values()])
    print(f"Δ R² promedio: {delta_r2_promedio:+.4f}")

    # Coef faltas por liga (la pregunta clave)
    print()
    print("Coef faltas (OLS extendido) por liga:")
    for liga, v in out_per_liga.items():
        sign = "+" if v["coef_ext_faltas"] > 0 else "-"
        print(f"  {liga:<12} faltas={v['coef_ext_faltas']:+.4f} (esperado: NEG si faltas correlacionan con menor calidad)")

    # JSON
    import json
    out = ROOT / "analisis" / "ols_xg_extendido_faltas.json"
    out.write_text(json.dumps(out_per_liga, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {out}")


if __name__ == "__main__":
    main()

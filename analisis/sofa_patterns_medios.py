"""
SOFA patterns MEDIOS — A (Periodo 1ST/2ND) + C (Lineup Gini).

A: Parsear statistics_json para stats por periodo.
   Features per equipo:
     - share_1st_pos (% posesion 1ST del total)
     - share_1st_shots
     - fade_pct_pos (1ST - 2ND posesion)
     - fade_pct_shots
   Hipotesis: equipos que "fade" 2ND son apostables anti.

C: Parsear lineups_json para Gini ratings.
   Features per equipo:
     - gini_ratings_titulares (11 titulares)
     - bench_max_rating (top sustituto)
     - star_rating (max rating)
     - n_sustitutos_alta (rating>=7.5)
   Hipotesis: equipos balanceados (Gini bajo) consistentes; star-dependent (Gini alto) volatiles.

Pipeline igual a sofa_patterns_rapidos.py: features lag-3/lag-5 + universo cuotas + bin q4 + bootstrap CI.
"""
from __future__ import annotations
import sqlite3
import json
import math
import re
import unicodedata
import numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)


def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def bootstrap_ci(values, n_boot=1000, alpha=0.05):
    if len(values) < 2: return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    samples = np.random.choice(arr, size=(n_boot, len(arr)), replace=True)
    means = np.sort(samples.mean(axis=1))
    return (float(means[int(alpha/2*n_boot)]), float(means[int((1-alpha/2)*n_boot)]))


def gini(values):
    """Gini coefficient sobre lista de valores positivos."""
    if not values: return None
    arr = sorted(v for v in values if v is not None and v > 0)
    if len(arr) < 2: return None
    n = len(arr)
    cum = sum((i + 1) * v for i, v in enumerate(arr))
    total = sum(arr)
    if total == 0: return None
    return (2 * cum) / (n * total) - (n + 1) / n


def parse_stats_periodo(statistics_json):
    """Devuelve dict con stats per periodo: {'1ST': {ballPossession_h, totalShots_h, ...}, '2ND': {...}}"""
    if not statistics_json: return {}
    try:
        data = json.loads(statistics_json)
    except Exception:
        return {}
    out = {"1ST": {}, "2ND": {}, "ALL": {}}
    items = data.get("statistics", []) if isinstance(data, dict) else data
    for p_block in items:
        if not isinstance(p_block, dict): continue
        period = p_block.get("period")
        if period not in out: continue
        for group in p_block.get("groups", []):
            for st in group.get("statisticsItems", []):
                key = st.get("key")
                if key:
                    out[period][f"{key}_h"] = st.get("homeValue")
                    out[period][f"{key}_a"] = st.get("awayValue")
    return out


def parse_lineup(lineups_json):
    """Devuelve {'home': {gini, max_rating, bench_max, n_alta_bench, keeper_rating},
                 'away': {idem}}"""
    if not lineups_json: return None
    try:
        data = json.loads(lineups_json)
    except Exception:
        return None
    result = {}
    for side, key in [("home", "home"), ("away", "away")]:
        block = data.get(key, {})
        players = block.get("players", [])
        ratings_titulares = []
        ratings_sub = []
        keeper_rating = None
        for p in players:
            sub = p.get("substitute", False)
            stats = p.get("statistics", {})
            r = stats.get("rating")
            pos = p.get("position", "")
            mins = stats.get("minutesPlayed", 0)
            if r is None or mins is None or mins < 1:
                continue
            if pos == "G":
                keeper_rating = r
            if not sub:
                ratings_titulares.append(r)
            else:
                ratings_sub.append(r)
        all_played = ratings_titulares + ratings_sub
        result[side] = {
            "gini_titulares": gini(ratings_titulares),
            "max_rating": max(all_played) if all_played else None,
            "bench_max": max(ratings_sub) if ratings_sub else None,
            "n_alta_bench": sum(1 for r in ratings_sub if r >= 7.5),
            "keeper_rating": keeper_rating,
            "avg_titulares": (sum(ratings_titulares)/len(ratings_titulares)) if ratings_titulares else None,
        }
    return result


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1. Cargar SOFA con statistics_json + lineups_json
    sofa = list(cur.execute("""
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               statistics_json, lineups_json
        FROM sofascore_match_features
        WHERE error IS NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY liga, fecha
    """))
    print(f"SOFA: {len(sofa)}")

    # 2. Parsear y construir histories per equipo
    histories = defaultdict(list)
    n_with_stats = n_with_lineups = 0
    for sid, liga, fecha, ht, at, hg, ag, stats_j, lineup_j in sofa:
        st = parse_stats_periodo(stats_j) if stats_j else {}
        ln = parse_lineup(lineup_j) if lineup_j else None
        if st: n_with_stats += 1
        if ln: n_with_lineups += 1

        # Stats periodo features
        def get_share(period, key):
            try:
                a = st.get(period, {}).get(f"{key}_h", 0) or 0
                a_all = st.get("ALL", {}).get(f"{key}_h", 0) or 0
                return a / a_all if a_all > 0 else None
            except Exception:
                return None

        def get_share_v(period, key):
            try:
                a = st.get(period, {}).get(f"{key}_a", 0) or 0
                a_all = st.get("ALL", {}).get(f"{key}_a", 0) or 0
                return a / a_all if a_all > 0 else None
            except Exception:
                return None

        # Stats per equipo, role-aware
        # Local
        feats_l = {}
        share_pos_1st_l = get_share("1ST", "ballPossession")
        share_pos_2nd_l = get_share("2ND", "ballPossession")
        if share_pos_1st_l is not None and share_pos_2nd_l is not None:
            feats_l["fade_pos"] = share_pos_1st_l - share_pos_2nd_l
            feats_l["share_pos_1st"] = share_pos_1st_l
        share_sh_1st_l = get_share("1ST", "totalShotsOnGoal")
        share_sh_2nd_l = get_share("2ND", "totalShotsOnGoal")
        if share_sh_1st_l is not None and share_sh_2nd_l is not None:
            feats_l["fade_shots"] = share_sh_1st_l - share_sh_2nd_l
            feats_l["share_shots_1st"] = share_sh_1st_l

        if ln and ln.get("home"):
            for k, v in ln["home"].items():
                feats_l[f"lineup_{k}"] = v

        # Visita
        feats_v = {}
        share_pos_1st_v = get_share_v("1ST", "ballPossession")
        share_pos_2nd_v = get_share_v("2ND", "ballPossession")
        if share_pos_1st_v is not None and share_pos_2nd_v is not None:
            feats_v["fade_pos"] = share_pos_1st_v - share_pos_2nd_v
            feats_v["share_pos_1st"] = share_pos_1st_v
        share_sh_1st_v = get_share_v("1ST", "totalShotsOnGoal")
        share_sh_2nd_v = get_share_v("2ND", "totalShotsOnGoal")
        if share_sh_1st_v is not None and share_sh_2nd_v is not None:
            feats_v["fade_shots"] = share_sh_1st_v - share_sh_2nd_v
            feats_v["share_shots_1st"] = share_sh_1st_v
        if ln and ln.get("away"):
            for k, v in ln["away"].items():
                feats_v[f"lineup_{k}"] = v

        if feats_l:
            histories[(norm(liga), norm(ht))].append((fecha[:10], "l", feats_l))
        if feats_v:
            histories[(norm(liga), norm(at))].append((fecha[:10], "v", feats_v))

    print(f"Con statistics_json parsed: {n_with_stats}")
    print(f"Con lineups_json parsed: {n_with_lineups}")

    for k in histories:
        histories[k].sort(key=lambda x: x[0])

    def get_lag_features(liga, equipo, fecha, n_lag=5):
        hist = histories.get((norm(liga), norm(equipo)), [])
        prev = [h for h in hist if h[0] < fecha]
        if len(prev) < 3:
            return None
        last_n = prev[-n_lag:] if n_lag else prev
        col = defaultdict(list)
        for f, role, st in last_n:
            for k, v in st.items():
                if v is not None:
                    col[k].append(v)
        out = {}
        for k, vals in col.items():
            if vals:
                out[f"{k}_ema"] = sum(vals) / len(vals)
        return out

    # 3. Index cuotas (igual a rapidos)
    cuotas_idx = {}
    for r in cur.execute("SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25 FROM partidos_backtest WHERE estado='Liquidado' AND fecha>='2026' AND cuota_1 IS NOT NULL"):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        cuotas_idx[(norm(liga), fecha[:10], norm(ht), norm(at))] = (c1, cx, c2, co25, cu25, "backtest")
    for r in cur.execute("SELECT liga, fecha, equipo_local, equipo_visita, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25 FROM cuotas_historicas_fdco WHERE fecha>='2026' AND cuota_1 IS NOT NULL"):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k not in cuotas_idx:
            cuotas_idx[k] = (c1, cx, c2, co25, cu25, "fdco")
    cuotas_loose = defaultdict(list)
    for k, v in cuotas_idx.items():
        cuotas_loose[(k[1], k[2][:6])].append((k, v))

    def get_cuotas(liga, fecha, ht, at):
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in cuotas_idx: return cuotas_idx[k]
        for kk, vv in cuotas_loose.get((k[1], k[2][:6]), []):
            if kk[3][:5] == k[3][:5]: return vv
        return None

    # 4. Universo eventos
    eventos = []
    for sid, liga, fecha, ht, at, hg, ag, _, _ in sofa:
        feats_l_5 = get_lag_features(liga, ht, fecha, n_lag=5)
        feats_v_5 = get_lag_features(liga, at, fecha, n_lag=5)
        feats_l_3 = get_lag_features(liga, ht, fecha, n_lag=3)
        feats_v_3 = get_lag_features(liga, at, fecha, n_lag=3)
        if not feats_l_5 or not feats_v_5: continue
        cuotas = get_cuotas(liga, fecha, ht, at)
        if not cuotas: continue
        c1, cx, c2, co25, cu25, fuente = cuotas

        if hg > ag: res = "1"
        elif hg < ag: res = "2"
        else: res = "X"

        def yld(p, cu):
            if cu is None or cu <= 1.0: return None
            hit = 1 if p == res else 0
            return (cu - 1.0) if hit else -1.0

        e = {
            "sid": sid, "liga": liga, "fecha": fecha[:10], "ht": ht, "at": at,
            "hg": hg, "ag": ag, "res": res, "fuente": fuente,
            "cuota_1": c1, "cuota_x": cx, "cuota_2": c2, "cuota_o25": co25, "cuota_u25": cu25,
            "yield_local": yld("1", c1),
            "yield_empate": yld("X", cx),
            "yield_visita": yld("2", c2),
            "yield_o25": ((co25-1.0) if co25 and co25>1 and (hg+ag>2) else (-1.0 if co25 and co25>1 else None)),
            "yield_u25": ((cu25-1.0) if cu25 and cu25>1 and (hg+ag<=2) else (-1.0 if cu25 and cu25>1 else None)),
        }

        for prefix, feats in [("l_lag5", feats_l_5), ("v_lag5", feats_v_5),
                              ("l_lag3", feats_l_3), ("v_lag3", feats_v_3)]:
            if feats is None: continue
            for k, v in feats.items():
                e[f"{k}_{prefix}"] = v

        # Diff l - v
        all_keys = set()
        for d in [feats_l_5, feats_v_5]:
            if d: all_keys.update(d.keys())
        for k in all_keys:
            for span in ["lag5", "lag3"]:
                vl = e.get(f"{k}_l_{span}")
                vv = e.get(f"{k}_v_{span}")
                if vl is not None and vv is not None:
                    e[f"diff_{k}_{span}"] = vl - vv

        eventos.append(e)

    print(f"\nUniverso eventos: {len(eventos)}")

    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in eventos if e.get(f"yield_{pick}") is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"  baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    # 5. Identificar todas las features
    features = set()
    for e in eventos:
        for k in e.keys():
            if "_lag" in k and not k.startswith("yield_"):
                features.add(k)
    features = sorted(features)
    print(f"\nFeatures: {len(features)}")

    targets = ["yield_local", "yield_visita", "yield_empate", "yield_o25", "yield_u25"]
    findings = []
    n_tests = 0
    for feat in features:
        for target in targets:
            pick = target.replace("yield_", "")
            base = baselines.get(pick, 0)
            vals = [(e.get(feat), e.get(target)) for e in eventos
                    if e.get(feat) is not None and e.get(target) is not None]
            if len(vals) < 50: continue
            arr = np.array([v[0] for v in vals], dtype=float)
            quantiles = np.unique(np.percentile(arr, np.linspace(0, 100, 5)))
            if len(quantiles) < 2: continue
            for i in range(len(quantiles)-1):
                lo, hi = quantiles[i], quantiles[i+1]
                is_last = (i == len(quantiles)-2)
                if is_last:
                    sub = [v for v in vals if lo <= v[0] <= hi]
                else:
                    sub = [v for v in vals if lo <= v[0] < hi]
                if len(sub) < 30: continue
                n_tests += 1
                ys = np.array([v[1] for v in sub])
                ymean = float(ys.mean())
                lift = ymean - base
                ci_lo, ci_hi = bootstrap_ci(ys)
                if lift > 0.05 and ci_lo > 0:
                    findings.append({
                        "feature": feat, "target": target, "pick": pick,
                        "lo": float(lo), "hi": float(hi), "n": len(sub),
                        "yield_mean": ymean, "ci95_lo": ci_lo, "ci95_hi": ci_hi,
                        "baseline": base, "lift": lift,
                    })

    bonf_alpha = 0.05 / max(1, n_tests)
    print(f"\nTests: {n_tests}  Bonferroni alpha: {bonf_alpha:.7f}")
    print(f"Findings: {len(findings)}")

    findings.sort(key=lambda x: x["lift"], reverse=True)
    print()
    print("=== TOP 30 findings ===")
    print(f"{'feature':<45} {'pick':<8} {'N':>4} {'yield':>8} {'lift':>8} {'CI95_lo':>8} {'CI95_hi':>8}")
    for f in findings[:30]:
        print(f"{f['feature'][:44]:<45} {f['pick']:<8} {f['n']:>4} {f['yield_mean']:>+8.3%} {f['lift']:>+8.3%} {f['ci95_lo']:>+8.3f} {f['ci95_hi']:>+8.3f}")

    # 6. SHADOW persist
    cur.execute("DROP TABLE IF EXISTS picks_shadow_sofa_patterns_medios_v1")
    cur.execute("""
        CREATE TABLE picks_shadow_sofa_patterns_medios_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT, sofa_event_id INTEGER,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT, fuente_cuota TEXT,
            patron TEXT, filtro_id TEXT, filtro_descripcion TEXT,
            filtro_feature TEXT, filtro_lo REAL, filtro_hi REAL,
            pick TEXT, cuota REAL,
            hit_real INTEGER, yield_real REAL,
            n_acum_filtro INTEGER, yield_acum_filtro REAL,
            ci95_lo_pool REAL, yield_pool_validation REAL, n_pool_validation INTEGER,
            bonferroni_alpha REAL, aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    """)
    cur.execute("CREATE INDEX idx_pssprmed_filtro ON picks_shadow_sofa_patterns_medios_v1 (filtro_id)")

    ts_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pick_to_cuota = {"local": "cuota_1", "empate": "cuota_x", "visita": "cuota_2",
                     "o25": "cuota_o25", "u25": "cuota_u25"}
    pick_to_short = {"local": "1", "empate": "X", "visita": "2", "o25": "O25", "u25": "U25"}
    pick_to_hit = {"local": lambda e: 1 if e["res"]=="1" else 0,
                   "empate": lambda e: 1 if e["res"]=="X" else 0,
                   "visita": lambda e: 1 if e["res"]=="2" else 0,
                   "o25": lambda e: 1 if e["hg"]+e["ag"]>2 else 0,
                   "u25": lambda e: 1 if e["hg"]+e["ag"]<=2 else 0}

    rows = []
    for f in findings:
        feat = f["feature"]
        pick = f["pick"]
        if "fade_" in feat or "share_" in feat: patron = "A_periodo_1ST_2ND"
        elif "lineup_" in feat: patron = "C_lineup_gini"
        else: patron = "otro"

        n_acum = 0; yld_sum = 0
        for e in eventos:
            if e.get(feat) is None: continue
            if not (f["lo"] <= e[feat] <= f["hi"]): continue
            cuota = e.get(pick_to_cuota[pick])
            if cuota is None or cuota <= 1.0: continue
            yld = e.get(f"yield_{pick}")
            if yld is None: continue
            hit = pick_to_hit[pick](e)
            n_acum += 1; yld_sum += yld
            yld_acum = yld_sum / n_acum
            filtro_id = f"{patron}|{feat}|q[{f['lo']:.3f},{f['hi']:.3f}]|{pick}"
            rows.append((
                ts_log, e["sid"], e["liga"], e["fecha"], e["ht"], e["at"],
                e["fuente"], patron, filtro_id,
                f"{feat} in [{f['lo']:.3f}, {f['hi']:.3f}] -> {pick}",
                feat, f["lo"], f["hi"],
                pick_to_short[pick], cuota, hit, yld,
                n_acum, yld_acum,
                f["ci95_lo"], f["yield_mean"], f["n"],
                bonf_alpha, 0,
                "shadow_pendiente_n80_y_oos_temporadas_proximas",
            ))

    cur.executemany("""
        INSERT INTO picks_shadow_sofa_patterns_medios_v1 (
            ts_log, sofa_event_id, liga, fecha, ht, at, fuente_cuota,
            patron, filtro_id, filtro_descripcion,
            filtro_feature, filtro_lo, filtro_hi,
            pick, cuota, hit_real, yield_real,
            n_acum_filtro, yield_acum_filtro,
            ci95_lo_pool, yield_pool_validation, n_pool_validation,
            bonferroni_alpha, aplicado_produccion, razon_no_aplicado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    con.commit()

    print(f"\nSHADOW persisted: {len(rows)} picks")
    print()
    summary = list(cur.execute("""
        SELECT patron, COUNT(DISTINCT filtro_id), COUNT(*) AS n_picks,
               AVG(yield_real), AVG(hit_real)
        FROM picks_shadow_sofa_patterns_medios_v1 GROUP BY patron
    """))
    print("Resumen por patron:")
    print(f"{'patron':<25} {'n_filtros':>9} {'n_picks':>8} {'yld_acum':>10} {'hit':>6}")
    for p, nf, n, y, h in summary:
        print(f"{p:<25} {nf:>9} {n:>8} {y:>+10.3%} {h:>6.1%}")

    out = ROOT / "analisis" / "sofa_patterns_medios.json"
    out.write_text(json.dumps({
        "ts_log": ts_log,
        "n_eventos": len(eventos),
        "n_features": len(features),
        "n_tests": n_tests,
        "bonferroni_alpha": bonf_alpha,
        "n_findings": len(findings),
        "findings_top": findings[:50],
        "n_picks_shadow": len(rows),
        "summary_per_patron": [{"patron": p, "n_filtros": nf, "n_picks": n,
                                 "yield_acum": y, "hit_acum": h}
                                for p, nf, n, y, h in summary],
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

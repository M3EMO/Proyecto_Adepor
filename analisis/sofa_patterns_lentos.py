"""
SOFA patterns LENTOS — F: Clustering tactical mismatch (estilo vs estilo).

D (Game state) DESCARTADO: SOFA statistics_json solo expone breakdown por
periodo (1ST/2ND), no por marcador (leading/drawing/trailing).

F: K-means clustering sobre stats SOFA agregadas EMA per equipo.
   - 5 clusters esperados (post-test Silhouette / elbow):
     'posesion-tecnica', 'vertical-rapido', 'fisico-defensivo',
     'set-piece-heavy', 'transicional'
   - Asignacion DINAMICA por temporada (no leakage: cada partido usa cluster
     calculado solo con datos PREVIOS del equipo).
   - Para cada matchup cluster_l x cluster_v, computar yield + N.
   - Si encuentra mismatches con yield significativo, persiste SHADOW.

Pipeline:
1. Construir vectores stats SOFA EMA per (liga, equipo, fecha) sobre histories.
2. K-means con K=[3,4,5] (elbow) sobre vector promedio per equipo.
3. Assign cluster a cada equipo en cada partido (con stats hasta ese partido).
4. Cruzar con cuotas. Computar yield per matchup.
5. SHADOW persist los matchups con lift>5pp Y CI95 lower>0.
"""
from __future__ import annotations
import sqlite3
import json
import re
import unicodedata
import numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]
np.random.seed(42)

# Stats que definen estilo
STATS_ESTILO = [
    "ball_possession_l", "ball_possession_v",
    "shots_total_l", "shots_total_v",
    "shots_on_target_l", "shots_on_target_v",
    "shots_inside_box_l", "shots_inside_box_v",
    "corners_l", "corners_v",
    "fouls_l", "fouls_v",
    "tackles_won_pct_l", "tackles_won_pct_v",
    "duels_pct_l", "duels_pct_v",
]


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


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1. Cargar SOFA con stats partido + outcome
    sofa = list(cur.execute("""
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               ball_possession_l, ball_possession_v,
               shots_total_l, shots_total_v,
               shots_on_target_l, shots_on_target_v,
               shots_inside_box_l, shots_inside_box_v,
               corners_l, corners_v, fouls_l, fouls_v,
               tackles_won_pct_l, tackles_won_pct_v,
               duels_pct_l, duels_pct_v
        FROM sofascore_match_features
        WHERE error IS NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
        ORDER BY liga, fecha
    """))
    print(f"SOFA: {len(sofa)}")

    # 2. Construir vector stats per equipo en cada partido (rolling EMA last 5 partidos previos)
    cols_per_equipo = ["pos", "shots", "sots", "sib", "corners", "fouls", "tackles_pct", "duels_pct"]

    histories = defaultdict(list)
    for row in sofa:
        sid, liga, fecha, ht, at, hg, ag = row[:7]
        pos_l, pos_v = row[7], row[8]
        sh_l, sh_v = row[9], row[10]
        sot_l, sot_v = row[11], row[12]
        sib_l, sib_v = row[13], row[14]
        co_l, co_v = row[15], row[16]
        fo_l, fo_v = row[17], row[18]
        ta_l, ta_v = row[19], row[20]
        du_l, du_v = row[21], row[22]

        stats_l = {"pos": pos_l, "shots": sh_l, "sots": sot_l, "sib": sib_l,
                   "corners": co_l, "fouls": fo_l, "tackles_pct": ta_l, "duels_pct": du_l}
        stats_v = {"pos": pos_v, "shots": sh_v, "sots": sot_v, "sib": sib_v,
                   "corners": co_v, "fouls": fo_v, "tackles_pct": ta_v, "duels_pct": du_v}
        histories[(norm(liga), norm(ht))].append((fecha[:10], "l", stats_l))
        histories[(norm(liga), norm(at))].append((fecha[:10], "v", stats_v))

    for k in histories:
        histories[k].sort(key=lambda x: x[0])

    def get_ema_vector(liga, equipo, fecha, n_lag=5):
        hist = histories.get((norm(liga), norm(equipo)), [])
        prev = [h for h in hist if h[0] < fecha]
        if len(prev) < 3: return None
        last_n = prev[-n_lag:]
        col = defaultdict(list)
        for f, role, st in last_n:
            for k, v in st.items():
                if v is not None:
                    col[k].append(v)
        return {k: (sum(vs)/len(vs)) if vs else None for k, vs in col.items()}

    # 3. Cargar cuotas
    cuotas_idx = {}
    for r in cur.execute("SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25 FROM partidos_backtest WHERE estado='Liquidado' AND fecha>='2026' AND cuota_1 IS NOT NULL"):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        cuotas_idx[(norm(liga), fecha[:10], norm(ht), norm(at))] = (c1, cx, c2, co25, cu25, "backtest")
    for r in cur.execute("SELECT liga, fecha, equipo_local, equipo_visita, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25 FROM cuotas_historicas_fdco WHERE fecha>='2026' AND cuota_1 IS NOT NULL"):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k not in cuotas_idx: cuotas_idx[k] = (c1, cx, c2, co25, cu25, "fdco")
    cuotas_loose = defaultdict(list)
    for k, v in cuotas_idx.items(): cuotas_loose[(k[1], k[2][:6])].append((k, v))

    def get_cuotas(liga, fecha, ht, at):
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in cuotas_idx: return cuotas_idx[k]
        for kk, vv in cuotas_loose.get((k[1], k[2][:6]), []):
            if kk[3][:5] == k[3][:5]: return vv
        return None

    # 4. Construir universo eventos: pre-match EMA vectors local + visita + cuotas
    eventos = []
    for row in sofa:
        sid, liga, fecha, ht, at, hg, ag = row[:7]
        emas_l = get_ema_vector(liga, ht, fecha)
        emas_v = get_ema_vector(liga, at, fecha)
        if not emas_l or not emas_v: continue
        if any(emas_l.get(c) is None or emas_v.get(c) is None for c in cols_per_equipo): continue

        cuotas = get_cuotas(liga, fecha, ht, at)
        if not cuotas: continue
        c1, cx, c2, co25, cu25, fuente = cuotas

        if hg > ag: res = "1"
        elif hg < ag: res = "2"
        else: res = "X"
        def yld(p, cu):
            if cu is None or cu <= 1.0: return None
            return (cu - 1.0) if p == res else -1.0

        eventos.append({
            "sid": sid, "liga": liga, "fecha": fecha[:10], "ht": ht, "at": at,
            "hg": hg, "ag": ag, "res": res, "fuente": fuente,
            "cuota_1": c1, "cuota_x": cx, "cuota_2": c2,
            "cuota_o25": co25, "cuota_u25": cu25,
            "yield_local": yld("1", c1),
            "yield_empate": yld("X", cx),
            "yield_visita": yld("2", c2),
            "yield_o25": ((co25-1.0) if co25 and co25>1 and (hg+ag>2) else (-1.0 if co25 and co25>1 else None)),
            "yield_u25": ((cu25-1.0) if cu25 and cu25>1 and (hg+ag<=2) else (-1.0 if cu25 and cu25>1 else None)),
            "vec_l": [emas_l[c] for c in cols_per_equipo],
            "vec_v": [emas_v[c] for c in cols_per_equipo],
        })

    print(f"Eventos universo: {len(eventos)}")

    # 5. K-means con K=4 (sin leakage temporal: usar primer 60% partidos para fit)
    # Sort por fecha, fit en primer 60%, predict resto
    eventos.sort(key=lambda x: x["fecha"])
    n_fit = int(len(eventos) * 0.6)
    fit_data = []
    for e in eventos[:n_fit]:
        fit_data.append(e["vec_l"])
        fit_data.append(e["vec_v"])
    fit_arr = np.array(fit_data)
    scaler = StandardScaler().fit(fit_arr)
    fit_scaled = scaler.transform(fit_arr)

    K_OPTIONS = [3, 4, 5]
    best_k = None; best_inertia = None
    for k in K_OPTIONS:
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(fit_scaled)
        # Print centroids
        print(f"\n=== K={k} clustering ===")
        cents = scaler.inverse_transform(km.cluster_centers_)
        for c_idx, c in enumerate(cents):
            label = ""
            if c[0] > np.percentile([cents[j][0] for j in range(k)], 70): label += "alta-pos "
            if c[0] < np.percentile([cents[j][0] for j in range(k)], 30): label += "baja-pos "
            if c[1] > np.percentile([cents[j][1] for j in range(k)], 70): label += "ofensivo "
            if c[5] > np.percentile([cents[j][5] for j in range(k)], 70): label += "fisico "
            print(f"  cluster {c_idx} ({label.strip() or 'mid'}): pos={c[0]:.1f} sh={c[1]:.1f} sot={c[2]:.1f} sib={c[3]:.1f} co={c[4]:.1f} fo={c[5]:.1f} ta%={c[6]:.1f} du%={c[7]:.1f}")

    # Usar K=4 por defecto
    K = 4
    km = KMeans(n_clusters=K, random_state=42, n_init=10).fit(fit_scaled)

    # Asignar cluster a cada evento
    for e in eventos:
        e["cluster_l"] = int(km.predict(scaler.transform([e["vec_l"]]))[0])
        e["cluster_v"] = int(km.predict(scaler.transform([e["vec_v"]]))[0])
        e["matchup_cluster"] = f"c{e['cluster_l']}_vs_c{e['cluster_v']}"

    # Distribucion clusters
    print(f"\n=== Distribucion clusters (K={K}) ===")
    from collections import Counter
    dist_l = Counter(e["cluster_l"] for e in eventos)
    dist_v = Counter(e["cluster_v"] for e in eventos)
    for c in range(K):
        print(f"  cluster {c}: local={dist_l[c]:>3}  visita={dist_v[c]:>3}")

    baselines = {}
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [e[f"yield_{pick}"] for e in eventos if e.get(f"yield_{pick}") is not None]
        if ys:
            baselines[pick] = sum(ys) / len(ys)
            print(f"  baseline {pick}: {baselines[pick]:+.3%} N={len(ys)}")

    # 6. Para cada matchup_cluster, computar yields per pick
    findings = []
    n_tests = 0
    for cl in range(K):
        for cv in range(K):
            mu = f"c{cl}_vs_c{cv}"
            sub_events = [e for e in eventos if e["matchup_cluster"] == mu]
            if len(sub_events) < 15: continue
            for pick in ["local", "visita", "empate", "o25", "u25"]:
                target = f"yield_{pick}"
                ys = [e.get(target) for e in sub_events if e.get(target) is not None]
                if len(ys) < 15: continue
                n_tests += 1
                arr = np.array(ys)
                ymean = float(arr.mean())
                lift = ymean - baselines.get(pick, 0)
                ci_lo, ci_hi = bootstrap_ci(arr)
                findings.append({
                    "matchup_cluster": mu,
                    "cluster_l": cl, "cluster_v": cv,
                    "pick": pick, "n": len(ys),
                    "yield_mean": ymean,
                    "ci95_lo": ci_lo, "ci95_hi": ci_hi,
                    "baseline": baselines.get(pick, 0),
                    "lift": lift,
                    "ci95_lo_pos": ci_lo > 0,
                })

    bonf_alpha = 0.05 / max(1, n_tests)
    print(f"\nTests: {n_tests}  Bonferroni alpha: {bonf_alpha:.6f}")
    print(f"Findings (con CI95_lo > 0): {sum(1 for f in findings if f['ci95_lo_pos'])}")

    findings.sort(key=lambda x: x["yield_mean"], reverse=True)
    print()
    print("=== TODAS las matchups cluster x cluster (N>=30) ===")
    print(f"{'matchup':<15} {'pick':<8} {'N':>4} {'yield':>8} {'lift':>8} {'CI95_lo':>8} {'sig':>4}")
    for f in findings[:30]:
        sig = "**" if f["ci95_lo_pos"] else ""
        print(f"{f['matchup_cluster']:<15} {f['pick']:<8} {f['n']:>4} {f['yield_mean']:>+8.3%} {f['lift']:>+8.3%} {f['ci95_lo']:>+8.3f} {sig:>4}")

    # 7. SHADOW persist findings con lift>0.05 Y CI95 lo > 0
    promueven = [f for f in findings if f["lift"] > 0.05 and f["ci95_lo_pos"]]
    cur.execute("DROP TABLE IF EXISTS picks_shadow_sofa_patterns_lentos_v1")
    cur.execute("""
        CREATE TABLE picks_shadow_sofa_patterns_lentos_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT, sofa_event_id INTEGER,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT, fuente_cuota TEXT,
            patron TEXT, filtro_id TEXT, filtro_descripcion TEXT,
            matchup_cluster TEXT, cluster_l INTEGER, cluster_v INTEGER,
            pick TEXT, cuota REAL,
            hit_real INTEGER, yield_real REAL,
            n_acum_filtro INTEGER, yield_acum_filtro REAL,
            ci95_lo_pool REAL, yield_pool_validation REAL, n_pool_validation INTEGER,
            bonferroni_alpha REAL, aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    """)

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
    for f in promueven:
        n_acum = 0; yld_sum = 0
        for e in eventos:
            if e["matchup_cluster"] != f["matchup_cluster"]: continue
            cuota = e.get(pick_to_cuota[f["pick"]])
            if cuota is None or cuota <= 1.0: continue
            yld = e.get(f"yield_{f['pick']}")
            if yld is None: continue
            hit = pick_to_hit[f["pick"]](e)
            n_acum += 1; yld_sum += yld
            yld_acum = yld_sum / n_acum
            filtro_id = f"F_clustering|{f['matchup_cluster']}|{f['pick']}"
            rows.append((
                ts_log, e["sid"], e["liga"], e["fecha"], e["ht"], e["at"],
                e["fuente"], "F_clustering", filtro_id,
                f"matchup_cluster={f['matchup_cluster']} -> {f['pick']}",
                f["matchup_cluster"], f["cluster_l"], f["cluster_v"],
                pick_to_short[f["pick"]], cuota, hit, yld,
                n_acum, yld_acum,
                f["ci95_lo"], f["yield_mean"], f["n"],
                bonf_alpha, 0,
                "shadow_pendiente_n80_y_oos_temporadas_proximas",
            ))

    cur.executemany("""
        INSERT INTO picks_shadow_sofa_patterns_lentos_v1 (
            ts_log, sofa_event_id, liga, fecha, ht, at, fuente_cuota,
            patron, filtro_id, filtro_descripcion,
            matchup_cluster, cluster_l, cluster_v,
            pick, cuota, hit_real, yield_real,
            n_acum_filtro, yield_acum_filtro,
            ci95_lo_pool, yield_pool_validation, n_pool_validation,
            bonferroni_alpha, aplicado_produccion, razon_no_aplicado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    con.commit()

    print(f"\nSHADOW persisted: {len(rows)} picks  ({len(promueven)} matchups distintos)")

    out = ROOT / "analisis" / "sofa_patterns_lentos.json"
    out.write_text(json.dumps({
        "ts_log": ts_log,
        "n_eventos": len(eventos),
        "K_clusters": K,
        "n_tests": n_tests,
        "bonferroni_alpha": bonf_alpha,
        "n_findings": len(findings),
        "n_promueven_lift_5pp_ci_pos": len(promueven),
        "all_findings": findings,
        "n_picks_shadow": len(rows),
        "centroids_K4": [list(scaler.inverse_transform([c])[0])
                         for c in km.cluster_centers_],
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

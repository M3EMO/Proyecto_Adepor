"""
Phase 5 v4: SHADOW persistence con per-liga restriction explicita.

Para cada finding post walk-forward:
- Identifica ligas con yield positivo Y N>=30 (whitelist per-filtro)
- Persiste picks SOLO sobre esas ligas
- Aplicado_produccion=0
- Razon_no_aplicado='shadow_pendiente_n80_per_liga + bonferroni_no_superado'

Tabla: picks_shadow_filtros_ema_v4
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    universo = list(cur.execute("SELECT * FROM universo_filtros_ema_v4").fetchall())
    cols = [d[0] for d in cur.description]

    findings_data = json.load(open(ROOT / "analisis" / "filtros_ema_v4_findings.json", encoding="utf-8"))
    top = findings_data["wf_pass"]
    desglose = findings_data["desglose_11ligas_5anios"]

    cur.execute("DROP TABLE IF EXISTS picks_shadow_filtros_ema_v4")
    cur.execute("""
        CREATE TABLE picks_shadow_filtros_ema_v4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT,
            liga TEXT, temp INTEGER, fecha TEXT, ht TEXT, at TEXT,
            fuente_cuota TEXT,
            filtro_id TEXT, filtro_descripcion TEXT, filtro_feature TEXT,
            filtro_lo REAL, filtro_hi REAL,
            pick TEXT, cuota REAL,
            hit_real INTEGER, yield_real REAL,
            n_acum_filtro INTEGER, yield_acum_filtro REAL,
            ci95_lo_pool REAL, yield_pool_validation REAL, n_pool_validation INTEGER,
            avg_oos_yield REAL, n_pos_oos INTEGER, n_with_oos INTEGER,
            liga_es_whitelist INTEGER, yield_per_liga_estimado REAL, n_per_liga_estimado INTEGER,
            bonferroni_alpha REAL,
            validacion_metodo TEXT,
            aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    """)
    cur.execute("CREATE INDEX idx_psemf4_filtro ON picks_shadow_filtros_ema_v4 (filtro_id)")
    cur.execute("CREATE INDEX idx_psemf4_liga ON picks_shadow_filtros_ema_v4 (liga, filtro_id)")

    ts_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bonf_alpha = findings_data["bonferroni_alpha"]

    rows = []
    n_persist = 0
    summary = []

    for f in top:
        feature = f["feature"]
        target = f["target"]
        pick_short = {"local": "1", "visita": "2", "empate": "X",
                      "o25": "O25", "u25": "U25"}[f["pick"]]
        cuota_field = {"local": "cuota_1", "visita": "cuota_2", "empate": "cuota_x",
                       "o25": "cuota_o25", "u25": "cuota_u25"}[f["pick"]]
        hit_field = f"hit_{f['pick']}"
        yield_field = f"yield_{f['pick']}"
        finding_id = f"{feature}_{f['pick']}"
        lo, hi = f["lo"], f["hi"]

        # Determinar whitelist per-liga: yield_pool > 0 AND n >= 30
        per_liga = desglose.get(finding_id, {}).get("total_per_liga", {})
        whitelist = {liga for liga, info in per_liga.items()
                     if info["n"] >= 30 and info["yield"] is not None and info["yield"] > 0}

        n_acum = 0
        yield_acum_sum = 0
        for row in universo:
            d = dict(zip(cols, row))
            if d.get(feature) is None or d.get(yield_field) is None:
                continue
            if not (lo <= d[feature] <= hi):
                continue
            n_acum += 1
            y = d[yield_field]
            yield_acum_sum += y
            yield_acum = yield_acum_sum / n_acum

            liga_w = 1 if d["liga"] in whitelist else 0
            liga_info = per_liga.get(d["liga"], {})

            rows.append((
                ts_log,
                d["liga"], d["temp"], d["fecha"], d["ht"], d["at"],
                d["fuente"],
                finding_id, f"{feature} in [{lo:.4f}, {hi:.4f}] -> {f['pick']}", feature,
                lo, hi,
                pick_short, d.get(cuota_field),
                d.get(hit_field), y,
                n_acum, yield_acum,
                f["ci95_lo"], f["yield_mean"], f["n"],
                f.get("avg_oos_yield"), f.get("n_pos_oos"), f.get("n_with_oos"),
                liga_w,
                liga_info.get("yield"), liga_info.get("n"),
                bonf_alpha,
                "pool_bootstrap_walkforward_loyo",
                0,
                "shadow_pendiente_n80_y_bonferroni_no_superado",
            ))
            n_persist += 1

        whitelist_yield_avg = (
            sum(per_liga[l]["yield"] * per_liga[l]["n"] for l in whitelist if per_liga[l]["yield"] is not None) /
            sum(per_liga[l]["n"] for l in whitelist) if whitelist else None
        )
        whitelist_n = sum(per_liga[l]["n"] for l in whitelist)
        summary.append({
            "filtro_id": finding_id,
            "feature": feature, "pick": f["pick"],
            "lo": lo, "hi": hi,
            "n_pool": f["n"], "yield_pool": f["yield_mean"],
            "whitelist_ligas": sorted(list(whitelist)),
            "whitelist_n": whitelist_n,
            "whitelist_yield_estimado": whitelist_yield_avg,
            "ligas_descartadas": [l for l, info in per_liga.items()
                                  if info["yield"] is not None and info["yield"] <= 0
                                  and info["n"] >= 30],
            "ligas_n_pequeno": [l for l, info in per_liga.items() if info["n"] < 30 and info["n"] > 0],
        })

    cur.executemany("""
        INSERT INTO picks_shadow_filtros_ema_v4 (
            ts_log, liga, temp, fecha, ht, at, fuente_cuota,
            filtro_id, filtro_descripcion, filtro_feature, filtro_lo, filtro_hi,
            pick, cuota, hit_real, yield_real, n_acum_filtro, yield_acum_filtro,
            ci95_lo_pool, yield_pool_validation, n_pool_validation,
            avg_oos_yield, n_pos_oos, n_with_oos,
            liga_es_whitelist, yield_per_liga_estimado, n_per_liga_estimado,
            bonferroni_alpha, validacion_metodo, aplicado_produccion, razon_no_aplicado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    con.commit()

    print(f"Picks SHADOW persistidos: {n_persist}")
    print()
    print("=== Whitelist per-filtro ===")
    for s in summary:
        print(f"\n{s['filtro_id']}")
        print(f"  Pool: yield {s['yield_pool']:+.3%} N={s['n_pool']}")
        print(f"  Whitelist (yield>0 AND n>=30): {s['whitelist_ligas']}")
        print(f"    yield_estimado_whitelist {s['whitelist_yield_estimado']:+.3%} N={s['whitelist_n']}" if s['whitelist_yield_estimado'] is not None else "    sin whitelist")
        print(f"  Descartadas (yield<=0 N>=30): {s['ligas_descartadas']}")
        if s['ligas_n_pequeno']:
            print(f"  N pequeño (<30): {s['ligas_n_pequeno']}")

    out = ROOT / "analisis" / "filtros_ema_v4_shadow_summary.json"
    out.write_text(json.dumps({
        "n_picks_persistidos": n_persist,
        "filtros": summary,
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

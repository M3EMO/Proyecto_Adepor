"""
Fase 5 - Crear tabla SHADOW + backfill picks logueados.

Tabla: picks_shadow_filtros_sofa_v1
Filtros a persistir:
- Top 5 combinaciones que pasaron walk-forward LOYO
- Top filtros individuales que pasaron Bonferroni-soft (CI95 lo > 0)

Cada pick logueado se etiqueta con:
- filtro_id, filtro_descripcion
- pick (1, X, 2, O25, U25)
- cuota, hit_real, yield_real
- n_acum_evento (cumulative cuenta dentro del filtro)
- ci95_lower (de validacion pool)
- bonferroni_alpha
- validacion_metodo: 'pool_bootstrap' | 'walkforward_loyo'
- aplicado_produccion = 0 (SHADOW MODE)
- razon_no_aplicado: 'esperando_n80_y_oos_2027'
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from filtros_sofa_v1_ml_importance import cargar_universo_enriquecido, features_numericos
from filtros_sofa_v1_validation import construir_filtros_hipotesis

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    universo = cargar_universo_enriquecido()
    for e in universo:
        gl, gv = e.get("hg"), e.get("ag")
        if gl is not None and gv is not None and e.get("cuota_o25"):
            e["hit_o25"] = 1 if gl + gv > 2 else 0
            e["yield_o25"] = (e["cuota_o25"] - 1) if e["hit_o25"] else -1
        if gl is not None and gv is not None and e.get("cuota_u25"):
            e["hit_u25"] = 1 if gl + gv <= 2 else 0
            e["yield_u25"] = (e["cuota_u25"] - 1) if e["hit_u25"] else -1
        feats = features_numericos(e)
        for k, v in feats.items():
            if k not in e:
                e[k] = v

    hyp_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_hipotesis.json", encoding="utf-8"))
    filtros_p13 = construir_filtros_hipotesis(hyp_data)
    by_id = {f["id"]: f for f in filtros_p13}

    val_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_validation.json", encoding="utf-8"))
    wf_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_walkforward.json", encoding="utf-8"))

    # Filtros individuales que pasaron Phase 2
    filtros_a_loggear = []
    for r in val_data["filtros_validados"]:
        if r["promociona_shadow"]:
            f_obj = by_id.get(r["id"])
            if f_obj:
                filtros_a_loggear.append({
                    "filtro_id": r["id"],
                    "tipo_filtro": "individual_p2",
                    "desc": r["desc"],
                    "pick_field": r["pick_field"],
                    "condition": f_obj["condition"],
                    "ci95_lo_pool": r["ci95_lo"],
                    "yield_pool": r["yield_pool"],
                    "n_pool": r["n_pool"],
                    "consistencia_temporal": r["consistencia_temporal"],
                    "validacion_metodo": "pool_bootstrap_temporal_cv",
                })

    # Combinaciones que pasaron WF
    combos_data = json.load(open(ROOT / "analisis" / "filtros_sofa_v1_combinaciones.json", encoding="utf-8"))
    by_combo_id = {c["id"]: c for c in combos_data["combinaciones"]}
    promueven_wf_ids = wf_data["promueven_walkforward_ids"]

    for cid in promueven_wf_ids:
        c_data = by_combo_id.get(cid)
        if not c_data:
            continue
        # Reconstruir condition
        tipo = c_data["tipo"]
        rest = cid[len(tipo) + 1:]
        f1_id, f2_id = rest.split("__", 1)
        if f1_id not in by_id or f2_id not in by_id:
            continue
        f1, f2 = by_id[f1_id], by_id[f2_id]
        if tipo == "AND":
            cond = (lambda c1, c2: lambda e: c1(e) and c2(e))(f1["condition"], f2["condition"])
        else:
            cond = (lambda c1, c2: lambda e: c1(e) or c2(e))(f1["condition"], f2["condition"])

        wf_record = next((c for c in wf_data["combos_evaluados"] if c["id"] == cid), None)
        filtros_a_loggear.append({
            "filtro_id": cid,
            "tipo_filtro": "combinacion_wf",
            "desc": c_data["desc"],
            "pick_field": c_data["pick_field"],
            "condition": cond,
            "ci95_lo_pool": c_data["ci95_lo"],
            "yield_pool": c_data["yield_pool"],
            "n_pool": c_data["n_pool"],
            "consistencia_temporal": c_data["consistencia_temporal"],
            "avg_test_yield_loyo": (wf_record["avg_test_yield_loyo"] if wf_record else None),
            "validacion_metodo": "walkforward_loyo_3buckets",
        })

    print(f"Filtros a loggear SHADOW: {len(filtros_a_loggear)}")

    con = sqlite3.connect(DB)
    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS picks_shadow_filtros_sofa_v1")
    cur.execute("""
        CREATE TABLE picks_shadow_filtros_sofa_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT NOT NULL,
            sofa_event_id INTEGER,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT,
            filtro_id TEXT, filtro_descripcion TEXT,
            tipo_filtro TEXT,
            pick TEXT, cuota REAL,
            prob_modelo REAL, ev REAL,
            hit_real INTEGER, yield_real REAL,
            n_acum_filtro INTEGER,
            yield_acum_filtro REAL,
            ci95_lo_pool REAL,
            yield_pool_validation REAL,
            n_pool_validation INTEGER,
            consistencia_temporal REAL,
            avg_test_yield_loyo REAL,
            bonferroni_alpha REAL,
            validacion_metodo TEXT,
            aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    """)

    cur.execute("CREATE INDEX idx_psf_filtro ON picks_shadow_filtros_sofa_v1 (filtro_id)")
    cur.execute("CREATE INDEX idx_psf_event ON picks_shadow_filtros_sofa_v1 (sofa_event_id, filtro_id)")

    ts_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_total_test = 101 + 34
    bonferroni_alpha = 0.05 / n_total_test
    rows_to_insert = []

    for f in filtros_a_loggear:
        events_filt = [e for e in universo if f["condition"](e)]
        n_acum = 0
        sum_yield = 0
        for e in events_filt:
            pick_short = f["pick_field"].replace("yield_", "")
            cuota = None
            if pick_short == "local":
                cuota = e.get("cuota_1")
                pick_short = "1"
            elif pick_short == "visita":
                cuota = e.get("cuota_2")
                pick_short = "2"
            elif pick_short == "empate":
                cuota = e.get("cuota_x")
                pick_short = "X"
            elif pick_short == "o25":
                cuota = e.get("cuota_o25")
            elif pick_short == "u25":
                cuota = e.get("cuota_u25")

            yld = e.get(f["pick_field"])
            hit_field = f["pick_field"].replace("yield_", "hit_")
            hit_real = e.get(hit_field)

            if yld is None:
                continue
            n_acum += 1
            sum_yield += yld
            yield_acum = sum_yield / n_acum

            rows_to_insert.append((
                ts_log, e.get("sofa_event_id"),
                e.get("liga"), e.get("fecha"), e.get("ht"), e.get("at"),
                f["filtro_id"], f["desc"][:200], f["tipo_filtro"],
                pick_short, cuota,
                None, None,  # prob_modelo, ev (no calculado per filtro)
                hit_real, yld,
                n_acum, yield_acum,
                f["ci95_lo_pool"], f["yield_pool"], f["n_pool"],
                f["consistencia_temporal"],
                f.get("avg_test_yield_loyo"),
                bonferroni_alpha,
                f["validacion_metodo"],
                0, "esperando_n80_y_oos_temporadas_proximas",
            ))

    cur.executemany("""
        INSERT INTO picks_shadow_filtros_sofa_v1 (
            ts_log, sofa_event_id, liga, fecha, ht, at,
            filtro_id, filtro_descripcion, tipo_filtro,
            pick, cuota, prob_modelo, ev, hit_real, yield_real,
            n_acum_filtro, yield_acum_filtro,
            ci95_lo_pool, yield_pool_validation, n_pool_validation,
            consistencia_temporal, avg_test_yield_loyo,
            bonferroni_alpha, validacion_metodo,
            aplicado_produccion, razon_no_aplicado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)

    con.commit()

    # Resumen
    print(f"Filas SHADOW persistidas: {len(rows_to_insert)}")
    print()
    summary = cur.execute("""
        SELECT filtro_id, COUNT(*) as n, AVG(yield_real) as y, AVG(hit_real) as h
        FROM picks_shadow_filtros_sofa_v1
        GROUP BY filtro_id
        ORDER BY y DESC
    """).fetchall()

    print(f"{'filtro_id':<60} {'N':>4} {'yield':>8} {'hit':>6}")
    for fid, n, y, h in summary:
        print(f"{fid[:59]:<60} {n:>4} {(y or 0):>+8.3%} {(h or 0):>6.1%}")

    out = ROOT / "analisis" / "filtros_sofa_v1_shadow_summary.json"
    out.write_text(json.dumps({
        "n_filtros_loggeados": len(filtros_a_loggear),
        "n_picks_shadow": len(rows_to_insert),
        "bonferroni_alpha_total": bonferroni_alpha,
        "filtros_summary": [{"filtro_id": fid, "n": n, "yield": y, "hit": h}
                            for fid, n, y, h in summary],
    }, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

"""
Universo EMA: para cada partido_backtest 2026, traer snapshot EMA pre-partido
de local y visita desde historial_equipos_stats.

Features generadas (4 metodos):
- M_A_propio_l: ema_l_<stat>_l (lo que el local hace en sus partidos)
- M_A_propio_v: ema_l_<stat>_v (lo que el visita hace en sus partidos)
- M_A_propio_diff: ema_l_<stat>_l - ema_l_<stat>_v
- M_B_contra_l: ema_c_<stat>_l (lo que recibe el local)
- M_B_contra_v: ema_c_<stat>_v (lo que recibe el visita)
- M_B_contra_diff: ema_c_<stat>_l - ema_c_<stat>_v
- M_C_asim_atk_l_def_v: ema_l_<stat>_l - ema_c_<stat>_v (ataque local vs defensa visita)
- M_C_asim_atk_v_def_l: ema_l_<stat>_v - ema_c_<stat>_l (ataque visita vs defensa local)
- M_D_ratio_propio: ema_l_<stat>_l / ema_l_<stat>_v
- M_D_ratio_contra: ema_c_<stat>_l / ema_c_<stat>_v

Stats EMA disponibles (47 cols en historial_equipos_stats):
pos, passes, pass_pct, crosses, longballs, shots, sots, shot_pct, blocks,
corners, fouls, yellow, red, offsides, saves, tackles, interceptions, clearance.

Output: tabla `universo_filtros_ema_v1` + JSON metricas.
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]

EMA_STATS = [
    "pos", "passes", "pass_pct", "crosses", "cross_pct", "longballs", "longball_pct",
    "shots", "sots", "shot_pct", "blocks", "corners", "fouls", "yellow", "red",
    "offsides", "saves", "tackles", "tackle_pct", "interceptions", "clearance",
]


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cargar partidos_backtest 2026 liquidados con cuotas
    backtest = cur.execute(
        """
        SELECT id_partido, fecha, pais, local, visita,
               cuota_1, cuota_x, cuota_2, apuesta_1x2, goles_l, goles_v,
               cuota_o25, cuota_u25
        FROM partidos_backtest
        WHERE estado = 'Liquidado' AND fecha >= '2026'
              AND cuota_1 IS NOT NULL AND cuota_2 IS NOT NULL
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        """
    ).fetchall()

    print(f"Backtest 2026 liquidados: {len(backtest)}")

    # Build EMA snapshot lookup (pre-fecha, mismo equipo)
    cur.execute("DROP TABLE IF EXISTS universo_filtros_ema_v1")

    # Generar columnas dinamicamente
    ema_cols_l = []
    for stat in EMA_STATS:
        ema_cols_l.append(f"ema_l_{stat}_local REAL")
        ema_cols_l.append(f"ema_c_{stat}_local REAL")
        ema_cols_l.append(f"ema_l_{stat}_visita REAL")
        ema_cols_l.append(f"ema_c_{stat}_visita REAL")
        # Diffs
        ema_cols_l.append(f"diff_propio_{stat} REAL")  # ema_l_X_local - ema_l_X_visita
        ema_cols_l.append(f"diff_contra_{stat} REAL")  # ema_c_X_local - ema_c_X_visita
        ema_cols_l.append(f"asim_atk_l_def_v_{stat} REAL")  # ema_l_X_local - ema_c_X_visita
        ema_cols_l.append(f"asim_atk_v_def_l_{stat} REAL")  # ema_l_X_visita - ema_c_X_local
        ema_cols_l.append(f"ratio_propio_{stat} REAL")
        ema_cols_l.append(f"ratio_contra_{stat} REAL")

    create_sql = f"""
        CREATE TABLE universo_filtros_ema_v1 (
            id_partido TEXT PRIMARY KEY,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT,
            n_acum_local INTEGER, n_acum_visita INTEGER,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            cuota_o25 REAL, cuota_u25 REAL,
            apuesta_1x2 TEXT,
            hg INTEGER, ag INTEGER,
            res_1x2 TEXT,
            hit_local INTEGER, yield_local REAL,
            hit_empate INTEGER, yield_empate REAL,
            hit_visita INTEGER, yield_visita REAL,
            hit_o25 INTEGER, yield_o25 REAL,
            hit_u25 INTEGER, yield_u25 REAL,
            {', '.join(ema_cols_l)}
        )
    """
    cur.execute(create_sql)

    rows = []
    n_with_both = 0
    n_with_only_l = 0
    n_with_neither = 0

    for id_p, fecha, pais, local, visita, c1, cx, c2, ap, gl, gv, co25, cu25 in backtest:
        # Snapshot LOCAL pre-fecha
        snap_l = cur.execute("""
            SELECT n_acum, """ + ", ".join([f"ema_l_{s}, ema_c_{s}" for s in EMA_STATS]) + """
            FROM historial_equipos_stats
            WHERE liga=? AND equipo=? AND fecha < ?
            ORDER BY fecha DESC LIMIT 1
        """, (pais, local, fecha[:10])).fetchone()

        snap_v = cur.execute("""
            SELECT n_acum, """ + ", ".join([f"ema_l_{s}, ema_c_{s}" for s in EMA_STATS]) + """
            FROM historial_equipos_stats
            WHERE liga=? AND equipo=? AND fecha < ?
            ORDER BY fecha DESC LIMIT 1
        """, (pais, visita, fecha[:10])).fetchone()

        if snap_l is None and snap_v is None:
            n_with_neither += 1
            continue
        if snap_l is None or snap_v is None:
            n_with_only_l += 1
            continue
        n_with_both += 1

        n_acum_l = snap_l[0]
        n_acum_v = snap_v[0]

        # Skip warmup (< 5 partidos previos)
        if n_acum_l < 5 or n_acum_v < 5:
            continue

        # Compute features per stat
        feats = {}
        for i, stat in enumerate(EMA_STATS):
            ema_l_l = snap_l[1 + 2*i]
            ema_c_l = snap_l[1 + 2*i + 1]
            ema_l_v = snap_v[1 + 2*i]
            ema_c_v = snap_v[1 + 2*i + 1]
            feats[f"ema_l_{stat}_local"] = ema_l_l
            feats[f"ema_c_{stat}_local"] = ema_c_l
            feats[f"ema_l_{stat}_visita"] = ema_l_v
            feats[f"ema_c_{stat}_visita"] = ema_c_v
            if ema_l_l is not None and ema_l_v is not None:
                feats[f"diff_propio_{stat}"] = ema_l_l - ema_l_v
                feats[f"ratio_propio_{stat}"] = ema_l_l / max(ema_l_v, 0.001) if ema_l_v else None
            else:
                feats[f"diff_propio_{stat}"] = None
                feats[f"ratio_propio_{stat}"] = None
            if ema_c_l is not None and ema_c_v is not None:
                feats[f"diff_contra_{stat}"] = ema_c_l - ema_c_v
                feats[f"ratio_contra_{stat}"] = ema_c_l / max(ema_c_v, 0.001) if ema_c_v else None
            else:
                feats[f"diff_contra_{stat}"] = None
                feats[f"ratio_contra_{stat}"] = None
            if ema_l_l is not None and ema_c_v is not None:
                feats[f"asim_atk_l_def_v_{stat}"] = ema_l_l - ema_c_v
            else:
                feats[f"asim_atk_l_def_v_{stat}"] = None
            if ema_l_v is not None and ema_c_l is not None:
                feats[f"asim_atk_v_def_l_{stat}"] = ema_l_v - ema_c_l
            else:
                feats[f"asim_atk_v_def_l_{stat}"] = None

        # Pick parsing
        ap_short = None
        if ap:
            ap_up = ap.upper()
            if "LOCAL" in ap_up: ap_short = "1"
            elif "VISITA" in ap_up: ap_short = "2"
            elif "EMPATE" in ap_up: ap_short = "X"

        if gl > gv: res = "1"
        elif gl < gv: res = "2"
        else: res = "X"

        def yld(pick: str, cuota: float | None):
            if cuota is None or cuota <= 1.0:
                return (None, None)
            hit = 1 if pick == res else 0
            return (hit, (cuota - 1.0) if hit else -1.0)

        h1, y1 = yld("1", c1)
        hX, yX = yld("X", cx)
        h2, y2 = yld("2", c2)
        total = gl + gv
        if co25 and co25 > 1.0:
            ho25 = 1 if total > 2 else 0
            yo25 = (co25 - 1.0) if ho25 else -1.0
        else:
            ho25, yo25 = None, None
        if cu25 and cu25 > 1.0:
            hu25 = 1 if total <= 2 else 0
            yu25 = (cu25 - 1.0) if hu25 else -1.0
        else:
            hu25, yu25 = None, None

        # Row tuple in order of CREATE TABLE
        row = [id_p, pais, fecha[:10], local, visita, n_acum_l, n_acum_v,
               c1, cx, c2, co25, cu25, ap_short,
               gl, gv, res,
               h1, y1, hX, yX, h2, y2, ho25, yo25, hu25, yu25]
        # Append features in same order as create
        for stat in EMA_STATS:
            for col_suffix in ["ema_l_", "ema_c_", "ema_l_", "ema_c_",
                                "diff_propio_", "diff_contra_",
                                "asim_atk_l_def_v_", "asim_atk_v_def_l_",
                                "ratio_propio_", "ratio_contra_"]:
                if col_suffix == "ema_l_" and "_local" not in (col_suffix + stat) and not row[-1]:
                    pass  # placeholder to track order
        # Actually we need to track columns precisely
        for stat in EMA_STATS:
            row.append(feats[f"ema_l_{stat}_local"])
            row.append(feats[f"ema_c_{stat}_local"])
            row.append(feats[f"ema_l_{stat}_visita"])
            row.append(feats[f"ema_c_{stat}_visita"])
            row.append(feats[f"diff_propio_{stat}"])
            row.append(feats[f"diff_contra_{stat}"])
            row.append(feats[f"asim_atk_l_def_v_{stat}"])
            row.append(feats[f"asim_atk_v_def_l_{stat}"])
            row.append(feats[f"ratio_propio_{stat}"])
            row.append(feats[f"ratio_contra_{stat}"])

        rows.append(tuple(row))

    if rows:
        placeholders = ",".join("?" * len(rows[0]))
        cur.executemany(f"INSERT INTO universo_filtros_ema_v1 VALUES ({placeholders})", rows)

    con.commit()

    # Metricas
    metricas = {
        "n_backtest_2026": len(backtest),
        "n_universo_final": len(rows),
        "n_with_both_snapshots_pre_warmup": n_with_both,
        "n_warmup_skipped": n_with_both - len(rows),
        "n_only_one_snapshot": n_with_only_l,
        "n_neither": n_with_neither,
    }
    # Cobertura per liga
    cobertura = {}
    for liga, n in cur.execute("SELECT liga, COUNT(*) FROM universo_filtros_ema_v1 GROUP BY liga ORDER BY 2 DESC"):
        cobertura[liga] = n
    metricas["cobertura_por_liga"] = cobertura

    # Baselines yield
    for pick in ["local", "visita", "empate", "o25", "u25"]:
        ys = [r[0] for r in cur.execute(f"SELECT yield_{pick} FROM universo_filtros_ema_v1 WHERE yield_{pick} IS NOT NULL").fetchall()]
        if ys:
            metricas[f"baseline_pool_{pick}"] = sum(ys) / len(ys)
            metricas[f"baseline_pool_{pick}_n"] = len(ys)

    out = ROOT / "analisis" / "filtros_ema_v1_universo.json"
    out.write_text(json.dumps(metricas, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metricas, indent=2, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()

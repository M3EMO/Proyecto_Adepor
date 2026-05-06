"""
Universo EMA EXPANDIDO: cuotas_historicas_fdco 2022-2026 (~16,000 partidos potencial) +
snapshot EMA pre-partido de local y visita desde historial_equipos_stats.

Permite walk-forward TRUE-OOS:
- train ≤ 2024 / test 2025
- train ≤ 2025 / test 2026

Mismas 4 metodos features que filtros_ema_v1.

Output: tabla `universo_filtros_ema_v2` + JSON metricas.
"""
from __future__ import annotations
import sqlite3
import json
import re
import unicodedata
from pathlib import Path

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]

EMA_STATS = [
    "pos", "passes", "pass_pct", "crosses", "cross_pct", "longballs", "longball_pct",
    "shots", "sots", "shot_pct", "blocks", "corners", "fouls", "yellow", "red",
    "offsides", "saves", "tackles", "tackle_pct", "interceptions", "clearance",
]


def norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Cuotas + stats fdco 2022-2026 con resultado
    fdco = cur.execute(
        """
        SELECT liga, temp, fecha, equipo_local, equipo_visita,
               goles_l, goles_v,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM cuotas_historicas_fdco
        WHERE temp >= 2022
              AND cuota_1 IS NOT NULL AND cuota_2 IS NOT NULL AND cuota_x IS NOT NULL
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        """
    ).fetchall()

    print(f"fdco 2022-2026 con cuotas: {len(fdco)}")

    # Index historial_equipos_stats por (liga, equipo_norm) ordenado por fecha
    ema_stats_data = cur.execute(
        f"""SELECT liga, equipo, fecha, n_acum,
            {', '.join([f'ema_l_{s}, ema_c_{s}' for s in EMA_STATS])}
            FROM historial_equipos_stats
            ORDER BY liga, equipo, fecha"""
    ).fetchall()

    # Build dict {(liga_norm, equipo_norm): [(fecha, n_acum, ema_l_x..., ema_c_x...), ...]}
    from collections import defaultdict
    by_team = defaultdict(list)
    for row in ema_stats_data:
        liga, equipo, fecha = row[0], row[1], row[2]
        n_acum = row[3]
        emas = row[4:]
        key = (norm(liga), norm(equipo))
        by_team[key].append((fecha, n_acum, emas))

    # Each team list is already sorted by fecha (SQL ORDER BY)
    # Build lookup: (liga, equipo, fecha_evento) -> last snapshot pre-fecha
    def get_pre_snapshot(liga: str, equipo: str, fecha_evento: str):
        key = (norm(liga), norm(equipo))
        history = by_team.get(key, [])
        if not history:
            return None
        # Binary search would be faster, but linear OK for moderate sizes
        prev = None
        for f, n_a, em in history:
            if f < fecha_evento:
                prev = (f, n_a, em)
            else:
                break
        return prev

    cur.execute("DROP TABLE IF EXISTS universo_filtros_ema_v2")
    ema_cols_l = []
    for stat in EMA_STATS:
        ema_cols_l.append(f"ema_l_{stat}_local REAL")
        ema_cols_l.append(f"ema_c_{stat}_local REAL")
        ema_cols_l.append(f"ema_l_{stat}_visita REAL")
        ema_cols_l.append(f"ema_c_{stat}_visita REAL")
        ema_cols_l.append(f"diff_propio_{stat} REAL")
        ema_cols_l.append(f"diff_contra_{stat} REAL")
        ema_cols_l.append(f"asim_atk_l_def_v_{stat} REAL")
        ema_cols_l.append(f"asim_atk_v_def_l_{stat} REAL")
        ema_cols_l.append(f"ratio_propio_{stat} REAL")
        ema_cols_l.append(f"ratio_contra_{stat} REAL")

    create_sql = f"""
        CREATE TABLE universo_filtros_ema_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            liga TEXT, temp INTEGER, fecha TEXT, ht TEXT, at TEXT,
            n_acum_local INTEGER, n_acum_visita INTEGER,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            cuota_o25 REAL, cuota_u25 REAL,
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
    n_warmup_skipped = 0
    n_no_snap = 0

    for r in fdco:
        liga, temp, fecha, local, visita, gl, gv, c1, cx, c2, co25, cu25 = r
        snap_l = get_pre_snapshot(liga, local, fecha)
        snap_v = get_pre_snapshot(liga, visita, fecha)
        if snap_l is None or snap_v is None:
            n_no_snap += 1
            continue
        n_with_both += 1
        n_a_l = snap_l[1]
        n_a_v = snap_v[1]
        if n_a_l < 5 or n_a_v < 5:
            n_warmup_skipped += 1
            continue

        emas_l = snap_l[2]
        emas_v = snap_v[2]

        feats = {}
        for i, stat in enumerate(EMA_STATS):
            ema_l_l = emas_l[2*i]
            ema_c_l = emas_l[2*i + 1]
            ema_l_v = emas_v[2*i]
            ema_c_v = emas_v[2*i + 1]
            feats[f"ema_l_{stat}_local"] = ema_l_l
            feats[f"ema_c_{stat}_local"] = ema_c_l
            feats[f"ema_l_{stat}_visita"] = ema_l_v
            feats[f"ema_c_{stat}_visita"] = ema_c_v
            feats[f"diff_propio_{stat}"] = (ema_l_l - ema_l_v) if (ema_l_l is not None and ema_l_v is not None) else None
            feats[f"diff_contra_{stat}"] = (ema_c_l - ema_c_v) if (ema_c_l is not None and ema_c_v is not None) else None
            feats[f"asim_atk_l_def_v_{stat}"] = (ema_l_l - ema_c_v) if (ema_l_l is not None and ema_c_v is not None) else None
            feats[f"asim_atk_v_def_l_{stat}"] = (ema_l_v - ema_c_l) if (ema_l_v is not None and ema_c_l is not None) else None
            feats[f"ratio_propio_{stat}"] = (ema_l_l / ema_l_v) if (ema_l_l is not None and ema_l_v not in (None, 0)) else None
            feats[f"ratio_contra_{stat}"] = (ema_c_l / ema_c_v) if (ema_c_l is not None and ema_c_v not in (None, 0)) else None

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

        row = [None, liga, temp, fecha, local, visita, n_a_l, n_a_v,
               c1, cx, c2, co25, cu25,
               gl, gv, res,
               h1, y1, hX, yX, h2, y2, ho25, yo25, hu25, yu25]
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
        cur.executemany(f"INSERT INTO universo_filtros_ema_v2 VALUES ({placeholders})", rows)
    con.commit()

    metricas = {
        "n_fdco_2022_2026": len(fdco),
        "n_with_both_snapshots": n_with_both,
        "n_warmup_skipped": n_warmup_skipped,
        "n_no_snapshot": n_no_snap,
        "n_universo_final": len(rows),
    }

    cobertura = {}
    for liga, n in cur.execute("SELECT liga, COUNT(*) FROM universo_filtros_ema_v2 GROUP BY liga ORDER BY 2 DESC").fetchall():
        cobertura[liga] = n
    metricas["cobertura_por_liga"] = cobertura

    por_temp = {}
    for temp, n in cur.execute("SELECT temp, COUNT(*) FROM universo_filtros_ema_v2 GROUP BY temp").fetchall():
        por_temp[str(temp)] = n
    metricas["cobertura_por_temp"] = por_temp

    for pick in ["local", "visita", "empate", "o25", "u25"]:
        n_yp = cur.execute(f"SELECT COUNT(yield_{pick}), AVG(yield_{pick}) FROM universo_filtros_ema_v2").fetchone()
        metricas[f"baseline_pool_{pick}"] = n_yp[1]
        metricas[f"baseline_pool_{pick}_n"] = n_yp[0]

    out = ROOT / "analisis" / "filtros_ema_v2_universo_expandido.json"
    out.write_text(json.dumps(metricas, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metricas, indent=2, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()

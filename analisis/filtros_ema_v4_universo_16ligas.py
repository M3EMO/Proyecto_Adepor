"""
Universo v4: expandido a 16 ligas via UNION de cuotas_historicas_fdco +
cuotas_externas_historico + partidos_backtest.

Cobertura esperada por liga (intersect con historial_equipos_stats EMA):
- 8 EU + ARG/BRA: fdco 2022-2026 (~4,000+) + cuotas_externas 2021-2024 (~3,000)
- Noruega: cuotas_externas 2021-2024 (~1,000) + backtest 2026 (~50)
- LATAM exoticas (BOL/PER/VEN/ECU/URU/CHI/COL): solo backtest 2026 (~250 total)

Output: tabla `universo_filtros_ema_v4` + JSON metricas + flag fuente_cuota.
"""
from __future__ import annotations
import sqlite3
import json
import re
import unicodedata
from pathlib import Path
from collections import defaultdict

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

    # --- 1. UNION de fuentes de cuotas ---
    universal = []
    seen = set()  # (liga_norm, fecha, ht_norm, at_norm)

    # Fuente A: fdco
    for r in cur.execute("""
        SELECT liga, temp, fecha, equipo_local, equipo_visita,
               goles_l, goles_v, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM cuotas_historicas_fdco
        WHERE temp >= 2022 AND cuota_1 IS NOT NULL AND cuota_2 IS NOT NULL
              AND cuota_x IS NOT NULL AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """).fetchall():
        liga, temp, fecha, ht, at, gl, gv, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in seen:
            continue
        seen.add(k)
        universal.append({
            "liga": liga, "temp": temp, "fecha": fecha[:10],
            "ht": ht, "at": at, "gl": gl, "gv": gv,
            "c1": c1, "cx": cx, "c2": c2, "co25": co25, "cu25": cu25,
            "fuente": "fdco",
        })

    # Fuente B: cuotas_externas_historico (b365 priority)
    for r in cur.execute("""
        SELECT liga, temp, fecha, ht, at, hg, ag,
               b365h, b365d, b365a, b365_25o, b365_25u,
               psh, psd, psa, p_25o, p_25u
        FROM cuotas_externas_historico
        WHERE temp >= 2021 AND hg IS NOT NULL AND ag IS NOT NULL
    """).fetchall():
        liga, temp, fecha, ht, at, gl, gv, b1, bx, b2, bo25, bu25, p1, px, p2, po25, pu25 = r
        c1 = b1 or p1
        cx_ = bx or px
        c2 = b2 or p2
        if not bo25:
            bo25 = po25
        if not bu25:
            bu25 = pu25
        if not c1 or not cx_ or not c2:
            continue
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in seen:
            continue
        seen.add(k)
        universal.append({
            "liga": liga, "temp": temp, "fecha": fecha[:10],
            "ht": ht, "at": at, "gl": gl, "gv": gv,
            "c1": c1, "cx": cx_, "c2": c2, "co25": bo25, "cu25": bu25,
            "fuente": "externas",
        })

    # Fuente C: partidos_backtest 2026
    for r in cur.execute("""
        SELECT pais, fecha, local, visita, goles_l, goles_v,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM partidos_backtest
        WHERE estado='Liquidado' AND fecha>='2026' AND cuota_1 IS NOT NULL AND cuota_2 IS NOT NULL
              AND cuota_x IS NOT NULL AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    """).fetchall():
        liga, fecha, ht, at, gl, gv, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in seen:
            continue
        seen.add(k)
        universal.append({
            "liga": liga, "temp": 2026, "fecha": fecha[:10],
            "ht": ht, "at": at, "gl": gl, "gv": gv,
            "c1": c1, "cx": cx, "c2": c2, "co25": co25, "cu25": cu25,
            "fuente": "backtest",
        })

    print(f"Total partidos union (deduplicado): {len(universal)}")

    # --- 2. Cargar EMA + posicion (igual a v3) ---
    ema_data = cur.execute(
        f"""SELECT liga, equipo, fecha, n_acum,
            {', '.join([f'ema_l_{s}, ema_c_{s}' for s in EMA_STATS])}
            FROM historial_equipos_stats
            ORDER BY liga, equipo, fecha"""
    ).fetchall()
    by_team = defaultdict(list)
    for r in ema_data:
        by_team[(norm(r[0]), norm(r[1]))].append((r[2], r[3], r[4:]))

    def get_ema(liga, equipo, fecha):
        hist = by_team.get((norm(liga), norm(equipo)), [])
        prev = None
        for f, n_a, em in hist:
            if f < fecha: prev = (f, n_a, em)
            else: break
        return prev

    pos_data = cur.execute("""
        SELECT liga, equipo, fecha_snapshot, formato, posicion, puntos, pj, gf, gc
        FROM posiciones_tabla_snapshot
        WHERE formato IN ('liga', 'anual')
        ORDER BY liga, equipo, fecha_snapshot
    """).fetchall()
    pos_by_team = defaultdict(list)
    for r in pos_data:
        pos_by_team[(norm(r[0]), norm(r[1]))].append((r[2], r[4], r[5], r[6], r[7], r[8]))

    def get_pos(liga, equipo, fecha):
        hist = pos_by_team.get((norm(liga), norm(equipo)), [])
        prev = None
        for r in hist:
            if r[0] < fecha: prev = r
            else: break
        return prev

    max_pos_per_liga = {}
    for liga, mx in cur.execute("""
        SELECT liga, MAX(posicion) FROM posiciones_tabla_snapshot
        WHERE formato IN ('liga', 'anual') GROUP BY liga
    """).fetchall():
        max_pos_per_liga[norm(liga)] = mx

    # --- 3. Crear tabla v4 ---
    cur.execute("DROP TABLE IF EXISTS universo_filtros_ema_v4")
    ema_cols = []
    for stat in EMA_STATS:
        for col_t in ["ema_l_{}_local", "ema_c_{}_local", "ema_l_{}_visita", "ema_c_{}_visita",
                       "diff_propio_{}", "diff_contra_{}",
                       "asim_atk_l_def_v_{}", "asim_atk_v_def_l_{}",
                       "ratio_propio_{}", "ratio_contra_{}"]:
            ema_cols.append(f"{col_t.format(stat)} REAL")

    pos_cols = [
        "pos_local INTEGER", "pos_visita INTEGER",
        "puntos_local INTEGER", "puntos_visita INTEGER",
        "pj_local INTEGER", "pj_visita INTEGER",
        "gf_local INTEGER", "gf_visita INTEGER",
        "gc_local INTEGER", "gc_visita INTEGER",
        "pos_norm_local REAL", "pos_norm_visita REAL",
        "pos_diff INTEGER", "pos_diff_norm REAL",
        "puntos_diff INTEGER", "ratio_pos REAL",
        "bin_pos_local TEXT", "bin_pos_visita TEXT",
        "mismatch_pos TEXT",
        "puntos_per_pj_local REAL", "puntos_per_pj_visita REAL",
        "gf_per_pj_local REAL", "gf_per_pj_visita REAL",
        "gc_per_pj_local REAL", "gc_per_pj_visita REAL",
    ]

    create_sql = f"""
        CREATE TABLE universo_filtros_ema_v4 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fuente TEXT,
            liga TEXT, temp INTEGER, fecha TEXT, ht TEXT, at TEXT,
            n_acum_local INTEGER, n_acum_visita INTEGER,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            cuota_o25 REAL, cuota_u25 REAL,
            hg INTEGER, ag INTEGER, res_1x2 TEXT,
            hit_local INTEGER, yield_local REAL,
            hit_empate INTEGER, yield_empate REAL,
            hit_visita INTEGER, yield_visita REAL,
            hit_o25 INTEGER, yield_o25 REAL,
            hit_u25 INTEGER, yield_u25 REAL,
            {', '.join(ema_cols)},
            {', '.join(pos_cols)}
        )
    """
    cur.execute(create_sql)

    rows = []
    n_no_ema = n_warm = n_full = 0
    for u in universal:
        ema_l = get_ema(u["liga"], u["ht"], u["fecha"])
        ema_v = get_ema(u["liga"], u["at"], u["fecha"])
        if ema_l is None or ema_v is None:
            n_no_ema += 1
            continue
        if ema_l[1] < 5 or ema_v[1] < 5:
            n_warm += 1
            continue

        pos_l = get_pos(u["liga"], u["ht"], u["fecha"])
        pos_v = get_pos(u["liga"], u["at"], u["fecha"])
        pos_local = pos_visita = None
        puntos_local = puntos_visita = None
        pj_local = pj_visita = None
        gf_local = gf_visita = None
        gc_local = gc_visita = None
        pos_norm_local = pos_norm_visita = None
        pos_diff = pos_diff_norm = None
        puntos_diff = ratio_pos = None
        bin_l = bin_v = mismatch = None
        ppj_l = ppj_v = gfpj_l = gfpj_v = gcpj_l = gcpj_v = None

        if pos_l and pos_v:
            pos_local, puntos_local, pj_local, gf_local, gc_local = pos_l[1], pos_l[2], pos_l[3], pos_l[4], pos_l[5]
            pos_visita, puntos_visita, pj_visita, gf_visita, gc_visita = pos_v[1], pos_v[2], pos_v[3], pos_v[4], pos_v[5]
            mx = max_pos_per_liga.get(norm(u["liga"]), 20)
            if pos_local: pos_norm_local = pos_local / mx
            if pos_visita: pos_norm_visita = pos_visita / mx
            if pos_local and pos_visita:
                pos_diff = pos_visita - pos_local
                pos_diff_norm = pos_diff / mx
                ratio_pos = pos_local / pos_visita if pos_visita else None
            if puntos_local is not None and puntos_visita is not None:
                puntos_diff = puntos_local - puntos_visita

            def bp(p, mx_):
                if p is None or mx_ is None or mx_ < 3: return None
                if p <= mx_ / 3: return "top"
                elif p <= 2 * mx_ / 3: return "mid"
                else: return "bot"
            bin_l = bp(pos_local, mx)
            bin_v = bp(pos_visita, mx)
            if bin_l and bin_v:
                mismatch = f"{bin_l}_vs_{bin_v}"
            if pj_local and pj_local > 0:
                ppj_l = puntos_local / pj_local if puntos_local is not None else None
                gfpj_l = gf_local / pj_local if gf_local is not None else None
                gcpj_l = gc_local / pj_local if gc_local is not None else None
            if pj_visita and pj_visita > 0:
                ppj_v = puntos_visita / pj_visita if puntos_visita is not None else None
                gfpj_v = gf_visita / pj_visita if gf_visita is not None else None
                gcpj_v = gc_visita / pj_visita if gc_visita is not None else None

        n_full += 1
        emas_l = ema_l[2]
        emas_v = ema_v[2]
        feats = {}
        for i, stat in enumerate(EMA_STATS):
            ell, ecl, elv, ecv = emas_l[2*i], emas_l[2*i+1], emas_v[2*i], emas_v[2*i+1]
            feats[f"ema_l_{stat}_local"] = ell
            feats[f"ema_c_{stat}_local"] = ecl
            feats[f"ema_l_{stat}_visita"] = elv
            feats[f"ema_c_{stat}_visita"] = ecv
            feats[f"diff_propio_{stat}"] = (ell - elv) if (ell is not None and elv is not None) else None
            feats[f"diff_contra_{stat}"] = (ecl - ecv) if (ecl is not None and ecv is not None) else None
            feats[f"asim_atk_l_def_v_{stat}"] = (ell - ecv) if (ell is not None and ecv is not None) else None
            feats[f"asim_atk_v_def_l_{stat}"] = (elv - ecl) if (elv is not None and ecl is not None) else None
            feats[f"ratio_propio_{stat}"] = (ell / elv) if (ell is not None and elv not in (None, 0)) else None
            feats[f"ratio_contra_{stat}"] = (ecl / ecv) if (ecl is not None and ecv not in (None, 0)) else None

        gl, gv = u["gl"], u["gv"]
        c1, cx, c2, co25, cu25 = u["c1"], u["cx"], u["c2"], u["co25"], u["cu25"]
        if gl > gv: res = "1"
        elif gl < gv: res = "2"
        else: res = "X"
        def yld(p, cu):
            if cu is None or cu <= 1.0: return (None, None)
            hit = 1 if p == res else 0
            return (hit, (cu - 1.0) if hit else -1.0)
        h1, y1 = yld("1", c1)
        hX, yX = yld("X", cx)
        h2, y2 = yld("2", c2)
        total = gl + gv
        ho25 = (1 if total > 2 else 0) if (co25 and co25 > 1) else None
        yo25 = ((co25 - 1.0) if ho25 else -1.0) if ho25 is not None else None
        hu25 = (1 if total <= 2 else 0) if (cu25 and cu25 > 1) else None
        yu25 = ((cu25 - 1.0) if hu25 else -1.0) if hu25 is not None else None

        row = [None, u["fuente"], u["liga"], u["temp"], u["fecha"], u["ht"], u["at"],
               ema_l[1], ema_v[1], c1, cx, c2, co25, cu25, gl, gv, res,
               h1, y1, hX, yX, h2, y2, ho25, yo25, hu25, yu25]
        for stat in EMA_STATS:
            for col_t in ["ema_l_{}_local", "ema_c_{}_local", "ema_l_{}_visita", "ema_c_{}_visita",
                           "diff_propio_{}", "diff_contra_{}",
                           "asim_atk_l_def_v_{}", "asim_atk_v_def_l_{}",
                           "ratio_propio_{}", "ratio_contra_{}"]:
                row.append(feats[col_t.format(stat)])
        row.extend([pos_local, pos_visita, puntos_local, puntos_visita,
                    pj_local, pj_visita, gf_local, gf_visita, gc_local, gc_visita,
                    pos_norm_local, pos_norm_visita, pos_diff, pos_diff_norm,
                    puntos_diff, ratio_pos, bin_l, bin_v, mismatch,
                    ppj_l, ppj_v, gfpj_l, gfpj_v, gcpj_l, gcpj_v])
        rows.append(tuple(row))

    if rows:
        ph = ",".join("?" * len(rows[0]))
        cur.executemany(f"INSERT INTO universo_filtros_ema_v4 VALUES ({ph})", rows)
    con.commit()

    # Metricas
    metricas = {
        "n_universal_union": len(universal),
        "n_no_ema": n_no_ema,
        "n_warmup_skipped": n_warm,
        "n_universo_final": len(rows),
    }
    por_liga = {}
    for liga, n_t, n_p, fuentes in cur.execute("""
        SELECT liga, COUNT(*),
               SUM(CASE WHEN pos_local IS NOT NULL THEN 1 ELSE 0 END),
               GROUP_CONCAT(DISTINCT fuente)
        FROM universo_filtros_ema_v4 GROUP BY liga ORDER BY 2 DESC
    """).fetchall():
        por_liga[liga] = {"total": n_t, "con_pos": n_p, "fuentes": fuentes}
    metricas["por_liga"] = por_liga

    por_temp = {}
    for temp, n in cur.execute("SELECT temp, COUNT(*) FROM universo_filtros_ema_v4 GROUP BY temp ORDER BY temp"):
        por_temp[str(temp)] = n
    metricas["por_temp"] = por_temp

    out = ROOT / "analisis" / "filtros_ema_v4_universo_16ligas.json"
    out.write_text(json.dumps(metricas, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metricas, indent=2, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()

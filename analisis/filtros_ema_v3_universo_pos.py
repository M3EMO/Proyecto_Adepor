"""
Universo v3: EMA expandido + posicion en tabla pre-partido.

Suma a v2:
- pos_local, pos_visita (rango 1-N)
- puntos_local, puntos_visita
- pos_norm_local = pos / (max_pos_de_liga_temp) -> [0, 1]
- pos_diff = pos_visita - pos_local (positive = local mejor en tabla)
- puntos_diff = puntos_local - puntos_visita
- bin_pos_local = 'top'/'mid'/'bot' (terciles por liga-temp)
- bin_pos_visita = idem
- mismatch_pos: bin_local x bin_visita (9 combos)
- ratio_pos = pos_local / pos_visita

Output: tabla `universo_filtros_ema_v3` + JSON metricas.
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

    # 1) Cuotas + stats
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
    print(f"fdco: {len(fdco)}")

    # 2) Index EMA stats por (liga_norm, equipo_norm)
    ema_data = cur.execute(
        f"""SELECT liga, equipo, fecha, n_acum,
            {', '.join([f'ema_l_{s}, ema_c_{s}' for s in EMA_STATS])}
            FROM historial_equipos_stats
            ORDER BY liga, equipo, fecha"""
    ).fetchall()
    by_team = defaultdict(list)
    for r in ema_data:
        liga, equipo, fecha = r[0], r[1], r[2]
        by_team[(norm(liga), norm(equipo))].append((fecha, r[3], r[4:]))

    def get_ema(liga: str, equipo: str, fecha: str):
        hist = by_team.get((norm(liga), norm(equipo)), [])
        prev = None
        for f, n_a, em in hist:
            if f < fecha:
                prev = (f, n_a, em)
            else:
                break
        return prev

    # 3) Index posicion tabla por (liga_norm, equipo_norm) + fecha
    # Tomamos TODOS los formatos pero priorizamos 'liga' (EU) o 'anual' (LATAM)
    pos_data = cur.execute("""
        SELECT liga, equipo, fecha_snapshot, formato, posicion, puntos, pj, gf, gc
        FROM posiciones_tabla_snapshot
        ORDER BY liga, equipo, fecha_snapshot
    """).fetchall()
    pos_by_team = defaultdict(list)
    for r in pos_data:
        liga, equipo, fecha, formato, posicion, puntos, pj, gf, gc = r
        # Skip Apertura/Clausura para no duplicar — usamos solo 'liga' o 'anual'
        if formato not in ("liga", "anual"):
            continue
        pos_by_team[(norm(liga), norm(equipo))].append((fecha, posicion, puntos, pj, gf, gc))

    def get_pos(liga: str, equipo: str, fecha: str):
        hist = pos_by_team.get((norm(liga), norm(equipo)), [])
        prev = None
        for r in hist:
            if r[0] < fecha:
                prev = r
            else:
                break
        return prev

    # 4) Index max_pos por (liga_norm, fecha) para normalizar
    # Por simplicidad: max_pos_per_liga = max histórico de posicion en esa liga
    max_pos_per_liga = {}
    for liga, mx in cur.execute("""
        SELECT liga, MAX(posicion) FROM posiciones_tabla_snapshot
        WHERE formato IN ('liga', 'anual') GROUP BY liga
    """).fetchall():
        max_pos_per_liga[norm(liga)] = mx

    # 5) Construir universo
    cur.execute("DROP TABLE IF EXISTS universo_filtros_ema_v3")
    ema_cols = []
    for stat in EMA_STATS:
        ema_cols.extend([
            f"ema_l_{stat}_local REAL", f"ema_c_{stat}_local REAL",
            f"ema_l_{stat}_visita REAL", f"ema_c_{stat}_visita REAL",
            f"diff_propio_{stat} REAL", f"diff_contra_{stat} REAL",
            f"asim_atk_l_def_v_{stat} REAL", f"asim_atk_v_def_l_{stat} REAL",
            f"ratio_propio_{stat} REAL", f"ratio_contra_{stat} REAL",
        ])

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
        CREATE TABLE universo_filtros_ema_v3 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    n_with_ema = n_with_pos = n_full = n_warm_skip = 0

    for r in fdco:
        liga, temp, fecha, local, visita, gl, gv, c1, cx, c2, co25, cu25 = r
        ema_l = get_ema(liga, local, fecha)
        ema_v = get_ema(liga, visita, fecha)
        if ema_l is None or ema_v is None:
            continue
        n_with_ema += 1
        if ema_l[1] < 5 or ema_v[1] < 5:
            n_warm_skip += 1
            continue

        pos_l = get_pos(liga, local, fecha)
        pos_v = get_pos(liga, visita, fecha)

        # Posicion features
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
            n_with_pos += 1
            pos_local = pos_l[1]
            puntos_local = pos_l[2]
            pj_local = pos_l[3]
            gf_local = pos_l[4]
            gc_local = pos_l[5]
            pos_visita = pos_v[1]
            puntos_visita = pos_v[2]
            pj_visita = pos_v[3]
            gf_visita = pos_v[4]
            gc_visita = pos_v[5]

            mx = max_pos_per_liga.get(norm(liga), 20)
            if pos_local: pos_norm_local = pos_local / mx
            if pos_visita: pos_norm_visita = pos_visita / mx
            if pos_local and pos_visita:
                pos_diff = pos_visita - pos_local  # positive = local mejor (menor posicion)
                pos_diff_norm = (pos_visita - pos_local) / mx
                ratio_pos = pos_local / pos_visita if pos_visita else None
            if puntos_local is not None and puntos_visita is not None:
                puntos_diff = puntos_local - puntos_visita

            # Bins por liga-temp (terciles)
            def bin_pos(p, mx_):
                if p is None or mx_ is None or mx_ < 3:
                    return None
                if p <= mx_ / 3: return "top"
                elif p <= 2 * mx_ / 3: return "mid"
                else: return "bot"

            bin_l = bin_pos(pos_local, mx)
            bin_v = bin_pos(pos_visita, mx)
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
        # Si no hay posicion, todos None - igual incluimos partido para filtros que no la requieren
        n_full += 1

        # EMA features
        emas_l = ema_l[2]
        emas_v = ema_v[2]
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

        # Yields
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

        row = [None, liga, temp, fecha, local, visita, ema_l[1], ema_v[1],
               c1, cx, c2, co25, cu25, gl, gv, res,
               h1, y1, hX, yX, h2, y2, ho25, yo25, hu25, yu25]
        for stat in EMA_STATS:
            for col in ["ema_l_{}_local", "ema_c_{}_local", "ema_l_{}_visita", "ema_c_{}_visita",
                        "diff_propio_{}", "diff_contra_{}",
                        "asim_atk_l_def_v_{}", "asim_atk_v_def_l_{}",
                        "ratio_propio_{}", "ratio_contra_{}"]:
                row.append(feats[col.format(stat)])
        # Pos cols (24 fields)
        row.extend([pos_local, pos_visita, puntos_local, puntos_visita,
                    pj_local, pj_visita, gf_local, gf_visita, gc_local, gc_visita,
                    pos_norm_local, pos_norm_visita, pos_diff, pos_diff_norm,
                    puntos_diff, ratio_pos, bin_l, bin_v, mismatch,
                    ppj_l, ppj_v, gfpj_l, gfpj_v, gcpj_l, gcpj_v])

        rows.append(tuple(row))

    if rows:
        placeholders = ",".join("?" * len(rows[0]))
        cur.executemany(f"INSERT INTO universo_filtros_ema_v3 VALUES ({placeholders})", rows)
    con.commit()

    metricas = {
        "n_fdco": len(fdco),
        "n_with_ema_both": n_with_ema,
        "n_warmup_skipped": n_warm_skip,
        "n_with_pos": n_with_pos,
        "n_universo_final": len(rows),
    }

    cobertura_pos = cur.execute("""
        SELECT 'with_pos' as tipo, COUNT(*) FROM universo_filtros_ema_v3 WHERE pos_local IS NOT NULL
        UNION ALL
        SELECT 'no_pos', COUNT(*) FROM universo_filtros_ema_v3 WHERE pos_local IS NULL
    """).fetchall()
    metricas["cobertura_pos"] = dict(cobertura_pos)

    por_liga = {}
    for liga, n_t, n_p in cur.execute("""
        SELECT liga, COUNT(*),
               SUM(CASE WHEN pos_local IS NOT NULL THEN 1 ELSE 0 END)
        FROM universo_filtros_ema_v3 GROUP BY liga ORDER BY 2 DESC
    """).fetchall():
        por_liga[liga] = {"total": n_t, "con_pos": n_p}
    metricas["por_liga"] = por_liga

    out = ROOT / "analisis" / "filtros_ema_v3_universo_pos.json"
    out.write_text(json.dumps(metricas, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metricas, indent=2, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()

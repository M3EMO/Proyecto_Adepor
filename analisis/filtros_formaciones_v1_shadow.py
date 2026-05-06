"""
SHADOW persistence formaciones matchup.

Tabla: picks_shadow_formaciones_v1
- 1 fila por partido SOFA con formacion_l, formacion_v + outcome real
- Cruza con cuotas (partidos_backtest -> fdco -> sofa-only) para yield disponible
- Para cada partido, calcula 'pick_implicito' segun el matchup pattern (lift_max sobre baseline)
- Loggea hit_real + yield_real para auditoria incremental
- aplicado_produccion = 0
- razon: 'shadow_pendiente_n50_per_matchup_y_z>1.96'

Tambien persiste:
- universo SOFA con formacion + cuotas (universo_formaciones_v1) para futura re-evaluacion
- findings JSON estructurado con N, %1/%X/%2, xG, lift, z, criterio promocion
"""
from __future__ import annotations
import sqlite3
import json
import math
import re
import unicodedata
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1. Cargar partidos SOFA con formacion
    sofa = list(cur.execute("""
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               formation_l, formation_v, xg_shotmap_l, xg_shotmap_v
        FROM sofascore_match_features
        WHERE error IS NULL
              AND formation_l IS NOT NULL AND formation_v IS NOT NULL
              AND hg IS NOT NULL AND ag IS NOT NULL
    """))
    print(f"SOFA con formacion + resultado: {len(sofa)}")

    # 2. Index cuotas (priority: backtest > fdco)
    cuotas_idx = {}
    for r in cur.execute("""
        SELECT pais, fecha, local, visita, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM partidos_backtest WHERE estado='Liquidado' AND fecha>='2026'
              AND cuota_1 IS NOT NULL
    """):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        cuotas_idx[k] = (c1, cx, c2, co25, cu25, "backtest")

    for r in cur.execute("""
        SELECT liga, fecha, equipo_local, equipo_visita,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25
        FROM cuotas_historicas_fdco WHERE fecha>='2026' AND cuota_1 IS NOT NULL
    """):
        liga, fecha, ht, at, c1, cx, c2, co25, cu25 = r
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k not in cuotas_idx:
            cuotas_idx[k] = (c1, cx, c2, co25, cu25, "fdco")

    # Loose match
    cuotas_loose = defaultdict(list)
    for k, v in cuotas_idx.items():
        cuotas_loose[(k[1], k[2][:6])].append((k, v))

    def get_cuotas(liga, fecha, ht, at):
        k = (norm(liga), fecha[:10], norm(ht), norm(at))
        if k in cuotas_idx:
            return cuotas_idx[k]
        for kk, vv in cuotas_loose.get((k[1], k[2][:6]), []):
            if kk[3][:5] == k[3][:5]:
                return vv
        return None

    # 3. Computar baseline + per matchup stats
    n_total = len(sofa)
    baseline_1 = sum(1 for r in sofa if r[5] > r[6]) / n_total
    baseline_x = sum(1 for r in sofa if r[5] == r[6]) / n_total
    baseline_2 = sum(1 for r in sofa if r[5] < r[6]) / n_total
    print(f"Baseline: %1={baseline_1:.1%} %X={baseline_x:.1%} %2={baseline_2:.1%}")

    matchup_stats = defaultdict(lambda: {"n": 0, "1": 0, "X": 0, "2": 0,
                                          "xg_l_sum": 0, "xg_v_sum": 0, "n_xg": 0,
                                          "g_l_sum": 0, "g_v_sum": 0})
    for sid, liga, fecha, ht, at, hg, ag, fl, fv, xgl, xgv in sofa:
        if hg > ag: r = "1"
        elif hg < ag: r = "2"
        else: r = "X"
        d = matchup_stats[(fl, fv)]
        d["n"] += 1; d[r] += 1
        d["g_l_sum"] += hg; d["g_v_sum"] += ag
        if xgl is not None and xgv is not None:
            d["xg_l_sum"] += xgl; d["xg_v_sum"] += xgv; d["n_xg"] += 1

    # Determinar pick implicito por matchup: outcome con mayor lift positivo Y |z|>1
    def matchup_pick(fl, fv):
        d = matchup_stats.get((fl, fv))
        if not d or d["n"] < 10:
            return None, None, None, None
        p1 = d["1"]/d["n"]; px = d["X"]/d["n"]; p2 = d["2"]/d["n"]
        candidatos = []
        for outcome, p, base in [("1", p1, baseline_1), ("X", px, baseline_x), ("2", p2, baseline_2)]:
            lift = p - base
            se = math.sqrt(base * (1 - base) / d["n"])
            z = lift / se if se > 0 else 0
            candidatos.append((outcome, lift, z, p))
        candidatos.sort(key=lambda x: x[1], reverse=True)
        best = candidatos[0]
        if best[1] > 0.05:
            return best[0], best[1], best[2], best[3]
        return None, None, None, None

    # 4. Crear tabla SHADOW
    cur.execute("DROP TABLE IF EXISTS picks_shadow_formaciones_v1")
    cur.execute("""
        CREATE TABLE picks_shadow_formaciones_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_log TEXT,
            sofa_event_id INTEGER,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT,
            formation_l TEXT, formation_v TEXT,
            matchup_id TEXT,
            hg INTEGER, ag INTEGER, res_1x2 TEXT,
            xg_shotmap_l REAL, xg_shotmap_v REAL,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            cuota_o25 REAL, cuota_u25 REAL,
            fuente_cuota TEXT,
            pick_implicito TEXT, cuota_pick REAL,
            hit_real INTEGER, yield_real REAL,
            n_matchup INTEGER,
            lift_pick_implicito REAL,
            z_pick_implicito REAL,
            p_observed_pick REAL,
            baseline_pick REAL,
            criterio_promocion TEXT,
            aplicado_produccion INTEGER DEFAULT 0,
            razon_no_aplicado TEXT
        )
    """)
    cur.execute("CREATE INDEX idx_psformv1_matchup ON picks_shadow_formaciones_v1 (matchup_id)")
    cur.execute("CREATE INDEX idx_psformv1_event ON picks_shadow_formaciones_v1 (sofa_event_id)")

    # Tambien tabla universo formaciones para auditoria
    cur.execute("DROP TABLE IF EXISTS universo_formaciones_v1")
    cur.execute("""
        CREATE TABLE universo_formaciones_v1 (
            sofa_event_id INTEGER PRIMARY KEY,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT,
            formation_l TEXT, formation_v TEXT,
            matchup_id TEXT,
            hg INTEGER, ag INTEGER, res_1x2 TEXT,
            xg_shotmap_l REAL, xg_shotmap_v REAL,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            cuota_o25 REAL, cuota_u25 REAL,
            fuente_cuota TEXT
        )
    """)

    ts_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_shadow = []
    rows_universo = []
    n_pick = n_no_pick = n_no_cuota = 0

    for sid, liga, fecha, ht, at, hg, ag, fl, fv, xgl, xgv in sofa:
        if hg > ag: res = "1"
        elif hg < ag: res = "2"
        else: res = "X"

        cuota_data = get_cuotas(liga, fecha, ht, at)
        if cuota_data:
            c1, cx, c2, co25, cu25, fuente = cuota_data
        else:
            c1 = cx = c2 = co25 = cu25 = None
            fuente = None
            n_no_cuota += 1

        matchup_id = f"{fl}_vs_{fv}"
        rows_universo.append((
            sid, liga, fecha[:10], ht, at, fl, fv, matchup_id,
            hg, ag, res, xgl, xgv, c1, cx, c2, co25, cu25, fuente,
        ))

        # Solo persistir SHADOW si hay matchup pick + cuota
        pick, lift, z, p_obs = matchup_pick(fl, fv)
        if pick is None:
            n_no_pick += 1
            continue
        cuota_pick = {"1": c1, "X": cx, "2": c2}.get(pick)
        if cuota_pick is None or cuota_pick <= 1.0:
            n_no_cuota += 1
            continue
        n_pick += 1
        hit = 1 if pick == res else 0
        yld = (cuota_pick - 1.0) if hit else -1.0
        baseline = {"1": baseline_1, "X": baseline_x, "2": baseline_2}[pick]
        n_matchup = matchup_stats[(fl, fv)]["n"]

        # Criterio promocion: |z|>1.96 AND N_matchup>=50 AND lift>10pp
        criterio = []
        if abs(z) >= 1.96: criterio.append("z_sig")
        if n_matchup >= 50: criterio.append("n50")
        if abs(lift) >= 0.10: criterio.append("lift10pp")
        criterio_str = "_".join(criterio) if criterio else "ninguno"

        rows_shadow.append((
            ts_log, sid, liga, fecha[:10], ht, at, fl, fv, matchup_id,
            hg, ag, res, xgl, xgv,
            c1, cx, c2, co25, cu25, fuente,
            pick, cuota_pick, hit, yld,
            n_matchup, lift, z, p_obs, baseline,
            criterio_str,
            0, "shadow_pendiente_n50_y_z_sig_y_lift_10pp_y_oos_temporadas_proximas",
        ))

    cur.executemany("""
        INSERT INTO universo_formaciones_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_universo)
    cur.executemany("""
        INSERT INTO picks_shadow_formaciones_v1 (
            ts_log, sofa_event_id, liga, fecha, ht, at,
            formation_l, formation_v, matchup_id,
            hg, ag, res_1x2, xg_shotmap_l, xg_shotmap_v,
            cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, fuente_cuota,
            pick_implicito, cuota_pick, hit_real, yield_real,
            n_matchup, lift_pick_implicito, z_pick_implicito,
            p_observed_pick, baseline_pick,
            criterio_promocion, aplicado_produccion, razon_no_aplicado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_shadow)
    con.commit()

    # 5. Resumen
    print(f"\n=== Persistencia ===")
    print(f"universo_formaciones_v1: {len(rows_universo)} filas")
    print(f"picks_shadow_formaciones_v1: {len(rows_shadow)} filas (con pick implicito + cuota)")
    print(f"Sin pick implicito (lift<5pp): {n_no_pick}")
    print(f"Sin cuotas: {n_no_cuota}")

    # Resumen per matchup en SHADOW
    print()
    print("=== Picks SHADOW por matchup (top 25 por |z|) ===")
    summary = list(cur.execute("""
        SELECT matchup_id, pick_implicito,
               COUNT(*) AS n_picks,
               AVG(yield_real) AS yield_real_acum,
               AVG(hit_real) AS hit_real_acum,
               MAX(n_matchup) AS n_matchup,
               MAX(lift_pick_implicito) AS lift,
               MAX(z_pick_implicito) AS z,
               MAX(p_observed_pick) AS p_obs,
               MAX(baseline_pick) AS baseline
        FROM picks_shadow_formaciones_v1
        GROUP BY matchup_id, pick_implicito
        ORDER BY ABS(MAX(z_pick_implicito)) DESC
    """).fetchall())
    print(f"{'matchup_id':<32} {'pick':<5} {'n':>3} {'yld_acum':>9} {'hit':>5} {'N_mu':>4} {'lift':>7} {'z':>5} {'crit':>20}")
    for m, pk, n, y, h, nm, lf, z, p_obs, b in summary[:25]:
        crit = []
        if abs(z) >= 1.96: crit.append("z*")
        if nm >= 50: crit.append("N50")
        if abs(lf) >= 0.10: crit.append("L10")
        crit_s = "+".join(crit) if crit else "-"
        print(f"{m[:31]:<32} {pk:<5} {n:>3} {y:>+9.3%} {h:>5.1%} {nm:>4} {lf:>+7.1%} {z:>+5.2f} {crit_s:>20}")

    out_data = {
        "ts_log": ts_log,
        "n_total_sofa": len(sofa),
        "baseline": {"p1": baseline_1, "px": baseline_x, "p2": baseline_2},
        "n_universo_persistido": len(rows_universo),
        "n_picks_shadow": len(rows_shadow),
        "n_sin_pick_implicito": n_no_pick,
        "n_sin_cuotas": n_no_cuota,
        "matchups": [
            {"matchup_id": m, "pick": pk, "n_picks_logueados": n,
             "yield_acum_realizado": y, "hit_acum_realizado": h,
             "n_matchup_total": nm,
             "lift_observado_pool": lf, "z_observado_pool": z,
             "p_observed_pool": p_obs, "baseline": b}
            for m, pk, n, y, h, nm, lf, z, p_obs, b in summary
        ],
    }
    out = ROOT / "analisis" / "filtros_formaciones_v1_shadow_summary.json"
    out.write_text(json.dumps(out_data, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

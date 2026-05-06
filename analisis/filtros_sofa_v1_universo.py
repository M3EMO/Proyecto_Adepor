"""
Construye universo eventos: SOFA × cuotas (partidos_backtest + fdco) con normalizacion robusta.

Output:
- Tabla `universo_filtros_sofa_v1` con (liga, fecha, ht, at, sofa_event_id, id_partido_backtest,
  liga_fdco, cuota_1, cuota_x, cuota_2, apuesta_1x2, hit_real, yield_real, hg, ag,
  features SOFA core).
- JSON metricas universo.
"""
from __future__ import annotations
import sqlite3
import json
import re
import unicodedata
from pathlib import Path

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def norm_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|club|deportivo|cd|atletico|atletico de|de|la|el|los|the)\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()

    sofa = cur.execute(
        """
        SELECT sofa_event_id, liga, fecha, ht, at, hg, ag,
               ball_possession_l, ball_possession_v,
               big_chances_l, big_chances_v, big_chances_missed_l, big_chances_missed_v,
               shots_total_l, shots_total_v, shots_on_target_l, shots_on_target_v,
               shots_inside_box_l, shots_inside_box_v, shots_outside_box_l, shots_outside_box_v,
               touches_penalty_area_l, touches_penalty_area_v,
               corners_l, corners_v, fouls_l, fouls_v, saves_l, saves_v,
               recoveries_l, recoveries_v, errors_lead_to_shot_l, errors_lead_to_shot_v,
               formation_l, formation_v, manager_l, manager_v,
               avg_rating_l, avg_rating_v, max_rating_l, max_rating_v,
               xg_shotmap_l, xg_shotmap_v,
               referee_name, referee_id, referee_yellows, referee_reds, referee_games,
               keeper_save_value_l, keeper_save_value_v
        FROM sofascore_match_features WHERE error IS NULL
        """
    ).fetchall()

    backtest = cur.execute(
        """
        SELECT id_partido, pais, fecha, local, visita,
               cuota_1, cuota_x, cuota_2, apuesta_1x2, goles_l, goles_v,
               cuota_o25, cuota_u25, apuesta_ou,
               prob_1, prob_x, prob_2,
               ev_local, ev_empate, ev_visita
        FROM partidos_backtest
        WHERE estado IS NOT NULL AND apuesta_1x2 IS NOT NULL
              AND goles_l IS NOT NULL AND goles_v IS NOT NULL
        """
    ).fetchall()

    fdco = cur.execute(
        """
        SELECT liga, fecha, equipo_local, equipo_visita,
               equipo_local_norm, equipo_visita_norm,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               goles_l, goles_v
        FROM cuotas_historicas_fdco
        WHERE fecha >= '2026'
        """
    ).fetchall()

    bt_idx = {}
    for r in backtest:
        k = (r[2][:10], norm_name(r[3]), norm_name(r[4]))
        bt_idx.setdefault(k, []).append(r)

    fdco_idx = {}
    for r in fdco:
        k = (r[1][:10], norm_name(r[2]), norm_name(r[3]))
        fdco_idx.setdefault(k, []).append(r)

    bt_loose = {}
    for r in backtest:
        k = (r[2][:10], norm_name(r[3])[:6])
        bt_loose.setdefault(k, []).append(r)

    fdco_loose = {}
    for r in fdco:
        k = (r[1][:10], norm_name(r[2])[:6])
        fdco_loose.setdefault(k, []).append(r)

    cur.execute("DROP TABLE IF EXISTS universo_filtros_sofa_v1")
    cur.execute(
        """
        CREATE TABLE universo_filtros_sofa_v1 (
            sofa_event_id INTEGER PRIMARY KEY,
            liga TEXT, fecha TEXT, ht TEXT, at TEXT,
            id_partido_backtest TEXT, fuente_match TEXT,
            cuota_1 REAL, cuota_x REAL, cuota_2 REAL,
            apuesta_1x2 TEXT, apostado_v0 INTEGER,
            cuota_pick REAL, prob_modelo REAL, ev_pick REAL,
            cuota_o25 REAL, cuota_u25 REAL,
            hg INTEGER, ag INTEGER,
            res_1x2 TEXT, hit_pick INTEGER, yield_pick REAL,
            hit_local INTEGER, yield_local REAL,
            hit_visita INTEGER, yield_visita REAL,
            hit_empate INTEGER, yield_empate REAL,
            ball_possession_l REAL, ball_possession_v REAL,
            big_chances_l INTEGER, big_chances_v INTEGER,
            big_chances_missed_l INTEGER, big_chances_missed_v INTEGER,
            shots_total_l INTEGER, shots_total_v INTEGER,
            shots_on_target_l INTEGER, shots_on_target_v INTEGER,
            shots_inside_box_l INTEGER, shots_inside_box_v INTEGER,
            shots_outside_box_l INTEGER, shots_outside_box_v INTEGER,
            touches_penalty_area_l INTEGER, touches_penalty_area_v INTEGER,
            corners_l INTEGER, corners_v INTEGER,
            fouls_l INTEGER, fouls_v INTEGER,
            saves_l INTEGER, saves_v INTEGER,
            recoveries_l INTEGER, recoveries_v INTEGER,
            errors_lead_to_shot_l INTEGER, errors_lead_to_shot_v INTEGER,
            formation_l TEXT, formation_v TEXT,
            manager_l TEXT, manager_v TEXT,
            avg_rating_l REAL, avg_rating_v REAL,
            max_rating_l REAL, max_rating_v REAL,
            xg_shotmap_l REAL, xg_shotmap_v REAL,
            referee_name TEXT, referee_id INTEGER,
            referee_yellows INTEGER, referee_reds INTEGER, referee_games INTEGER,
            keeper_save_value_l REAL, keeper_save_value_v REAL
        )
        """
    )

    matched_exact = matched_loose = unmatched = 0
    rows_to_insert = []
    SOFA_KEYS_END = 50

    for s in sofa:
        sid, liga, fecha, ht, at, hg, ag = s[0:7]
        feats = s[7:]
        kx = (fecha[:10], norm_name(ht), norm_name(at))

        bt_match = None
        fuente = None
        if kx in bt_idx:
            bt_match = bt_idx[kx][0]
            matched_exact += 1
            fuente = "backtest_exact"
        else:
            kl = (fecha[:10], norm_name(ht)[:6])
            cands = bt_loose.get(kl, [])
            for c in cands:
                if norm_name(c[4])[:5] == norm_name(at)[:5]:
                    bt_match = c
                    matched_loose += 1
                    fuente = "backtest_loose"
                    break

        fdco_match = None
        if kx in fdco_idx:
            fdco_match = fdco_idx[kx][0]
            if fuente is None:
                fuente = "fdco_exact"
        elif fuente is None:
            kl = (fecha[:10], norm_name(ht)[:6])
            cands = fdco_loose.get(kl, [])
            for c in cands:
                if norm_name(c[3])[:5] == norm_name(at)[:5]:
                    fdco_match = c
                    fuente = "fdco_loose"
                    break

        if bt_match is None and fdco_match is None:
            unmatched += 1
            continue

        if bt_match is not None:
            id_p, _, _, _, _, c1, cx, c2, ap, gl, gv = bt_match[:11]
            co25 = bt_match[11]
            cu25 = bt_match[12]
            prob_1, prob_x, prob_2 = bt_match[14], bt_match[15], bt_match[16]
            ev_l, ev_e, ev_v = bt_match[17], bt_match[18], bt_match[19]
        else:
            id_p = None
            ap = None
            c1, cx, c2 = fdco_match[6], fdco_match[7], fdco_match[8]
            co25, cu25 = fdco_match[9], fdco_match[10]
            gl, gv = fdco_match[11], fdco_match[12]
            prob_1 = prob_x = prob_2 = None
            ev_l = ev_e = ev_v = None

        if gl is None or gv is None:
            gl, gv = hg, ag
        if gl is None or gv is None:
            unmatched += 1
            continue

        if gl > gv:
            res = "1"
        elif gl < gv:
            res = "2"
        else:
            res = "X"

        def yld(pick: str) -> tuple[int, float | None, float | None]:
            cuota = {"1": c1, "X": cx, "2": c2}.get(pick)
            if cuota is None or cuota <= 1.0:
                return (0, None, None)
            hit = 1 if pick == res else 0
            yld = (cuota - 1.0) if hit else -1.0
            return (hit, yld, cuota)

        hit1, yld1, _ = yld("1")
        hitX, yldX, _ = yld("X")
        hit2, yld2, _ = yld("2")

        ap_short = None
        if ap:
            ap_up = ap.upper()
            if "LOCAL" in ap_up:
                ap_short = "1"
            elif "VISITA" in ap_up:
                ap_short = "2"
            elif "EMPATE" in ap_up:
                ap_short = "X"
            elif ap_up.strip() in ("1", "X", "2"):
                ap_short = ap_up.strip()

        if ap_short and ("APOSTAR" in (ap or "") or "GANADA" in (ap or "") or "PERDIDA" in (ap or "")):
            hit_p, yld_p, cuota_p = yld(ap_short)
            prob_pick = {"1": prob_1, "X": prob_x, "2": prob_2}.get(ap_short)
            ev_pick = {"1": ev_l, "X": ev_e, "2": ev_v}.get(ap_short)
            apostado_v0 = 1
        else:
            hit_p, yld_p, cuota_p = (None, None, None)
            prob_pick = None
            ev_pick = None
            apostado_v0 = 0

        rows_to_insert.append(
            (sid, liga, fecha[:10], ht, at, id_p, fuente,
             c1, cx, c2, ap_short, apostado_v0, cuota_p, prob_pick, ev_pick,
             co25, cu25, gl, gv, res,
             hit_p, yld_p, hit1, yld1, hit2, yld2, hitX, yldX,
             *feats)
        )

    placeholders = ",".join("?" * len(rows_to_insert[0])) if rows_to_insert else ""
    if rows_to_insert:
        cur.executemany(
            f"INSERT INTO universo_filtros_sofa_v1 VALUES ({placeholders})",
            rows_to_insert,
        )

    con.commit()

    metricas = {
        "n_sofa_total": len(sofa),
        "n_backtest_2026": len(backtest),
        "n_fdco_2026": len(fdco),
        "matched_exact": matched_exact,
        "matched_loose": matched_loose,
        "unmatched": unmatched,
        "universo_final": len(rows_to_insert),
    }

    cobertura_liga = {}
    for liga, n_sofa in cur.execute(
        "SELECT liga, COUNT(*) FROM sofascore_match_features WHERE error IS NULL GROUP BY liga"
    ).fetchall():
        n_universo = cur.execute(
            "SELECT COUNT(*) FROM universo_filtros_sofa_v1 WHERE liga=?", (liga,)
        ).fetchone()[0]
        cobertura_liga[liga] = {"sofa": n_sofa, "universo": n_universo}
    metricas["cobertura_por_liga"] = cobertura_liga

    n_con_apuesta = cur.execute(
        "SELECT COUNT(*) FROM universo_filtros_sofa_v1 WHERE apuesta_1x2 IS NOT NULL"
    ).fetchone()[0]
    n_con_o25 = cur.execute(
        "SELECT COUNT(*) FROM universo_filtros_sofa_v1 WHERE cuota_o25 IS NOT NULL"
    ).fetchone()[0]
    metricas["con_apuesta_v0"] = n_con_apuesta
    metricas["con_cuota_o25"] = n_con_o25

    if n_con_apuesta:
        yld_pool = cur.execute(
            "SELECT AVG(yield_pick) FROM universo_filtros_sofa_v1 WHERE yield_pick IS NOT NULL"
        ).fetchone()[0]
        hit_pool = cur.execute(
            "SELECT AVG(hit_pick) FROM universo_filtros_sofa_v1 WHERE hit_pick IS NOT NULL"
        ).fetchone()[0]
        metricas["baseline_v0_yield_pool"] = yld_pool
        metricas["baseline_v0_hit_pool"] = hit_pool

    yld_local = cur.execute("SELECT AVG(yield_local) FROM universo_filtros_sofa_v1 WHERE yield_local IS NOT NULL").fetchone()[0]
    yld_empate = cur.execute("SELECT AVG(yield_empate) FROM universo_filtros_sofa_v1 WHERE yield_empate IS NOT NULL").fetchone()[0]
    yld_visita = cur.execute("SELECT AVG(yield_visita) FROM universo_filtros_sofa_v1 WHERE yield_visita IS NOT NULL").fetchone()[0]
    metricas["baseline_pool_apostar_local"] = yld_local
    metricas["baseline_pool_apostar_empate"] = yld_empate
    metricas["baseline_pool_apostar_visita"] = yld_visita

    out = ROOT / "analisis" / "filtros_sofa_v1_universo.json"
    out.write_text(json.dumps(metricas, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metricas, indent=2, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""adepor-a1v: ¿V13 xG ya captura calidad estructural (pos_backward)?

Test:
  Para cada (liga, temp, equipo) en OOS 2022/2023/2024:
    - pos_backward = posicion FINAL en posiciones_tabla_snapshot
    - V13_xG_avg = xG_v13 promedio del equipo en sus partidos OOS
    - EMA_xG_v6_avg = ema_xg_v6_favor del equipo
    - delta_EMA_struct = ema_l_sots_avg - ema_c_sots_avg (proxy simple)

  Calcular:
    - Pearson r(pos_backward, proxy)
    - Si r < -0.3 -> proxy capta calidad estructural (mejor pos = lower number)

Output: tabla por liga + (temp) + correlaciones.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "proxy_pos_backward_correlacion.json"

LIGAS_TOP5 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]
LIGAS_V13 = ["Argentina", "Francia", "Italia", "Inglaterra"]


def cargar_v13_coefs(con):
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, target, intercept, coefs_json, metodo, feature_set
        FROM v13_coef_por_liga
        WHERE (liga, target, calibrado_en) IN (
            SELECT liga, target, MAX(calibrado_en) FROM v13_coef_por_liga GROUP BY liga, target
        ) AND metodo IS NOT NULL
    """).fetchall()
    out = {}
    for liga, t, ic, cj, m, fs in rows:
        out.setdefault(liga, {})[t] = {"intercept": float(ic), "coefs": json.loads(cj),
                                         "metodo": m, "feature_set": fs}
    return out


_FSETS = {
    "F1_off": ["atk_sots", "atk_shot_pct", "atk_corners", "def_sots_c", "def_shot_pct_c"],
    "F2_pos": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
               "def_sots_c", "def_shot_pct_c"],
    "F4_disc": ["atk_sots", "atk_shot_pct", "atk_pos", "atk_pass_pct", "atk_corners",
                "atk_yellow", "atk_red", "atk_fouls", "def_sots_c", "def_shot_pct_c"],
    "F5_ratio": ["atk_sots_per_shot", "atk_pressure", "atk_set_piece",
                 "atk_red_card_rate", "def_solidez"],
}


def feat_value(name, atk, df):
    try:
        if name == "atk_sots":      return atk["ema_l_sots"]
        if name == "atk_shot_pct":  return atk["ema_l_shot_pct"]
        if name == "atk_pos":       return atk["ema_l_pos"]
        if name == "atk_pass_pct":  return atk["ema_l_pass_pct"]
        if name == "atk_corners":   return atk["ema_l_corners"]
        if name == "atk_yellow":    return atk["ema_l_yellow"]
        if name == "atk_red":       return atk["ema_l_red"]
        if name == "atk_fouls":     return atk["ema_l_fouls"]
        if name == "def_sots_c":    return df["ema_c_sots"]
        if name == "def_shot_pct_c":return df["ema_c_shot_pct"]
        if name == "def_tackles_c": return df["ema_c_tackles"]
        if name == "def_blocks_c":  return df["ema_c_blocks"]
        if name == "atk_sots_per_shot":
            sh = atk.get("ema_l_shots")
            if sh is None or sh == 0: return 0.4
            return float(atk["ema_l_sots"]) / float(sh)
        if name == "atk_pressure":
            return float(atk["ema_l_pos"]) * float(atk["ema_l_shot_pct"]) / 100.0
        if name == "atk_set_piece": return float(atk["ema_l_corners"])
        if name == "atk_red_card_rate":
            f = atk.get("ema_l_fouls")
            if f is None or f == 0: return 0.0
            return float(atk["ema_l_red"]) / float(f)
        if name == "def_solidez": return float(df["ema_c_tackles"]) + float(df["ema_c_blocks"])
        return None
    except: return None


def calcular_xg_v13(coefs, liga, atk, df, target_local=True):
    cf_liga = coefs.get(liga)
    if not cf_liga: return None
    tgt = "local" if target_local else "visita"
    cf = cf_liga.get(tgt)
    if not cf: return None
    fset = _FSETS.get(cf["feature_set"])
    if not fset: return None
    feats = []
    for n in fset:
        v = feat_value(n, atk, df)
        if v is None: return None
        feats.append(float(v))
    coefs_arr = [cf["coefs"].get(n, 0.0) for n in fset]
    return max(0.10, cf["intercept"] + sum(f * c for f, c in zip(feats, coefs_arr)))


def cargar_pos_backward(con):
    """Para cada (liga, temp, equipo): pos final en posiciones_tabla_snapshot
    formato anual (o liga para EUR top)."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT pts.liga, pts.temp, pts.formato, pts.equipo, pts.posicion
        FROM posiciones_tabla_snapshot pts
        WHERE pts.fecha_snapshot = (
            SELECT MAX(fecha_snapshot) FROM posiciones_tabla_snapshot
            WHERE liga = pts.liga AND temp = pts.temp AND formato = pts.formato
        )
    """).fetchall()
    out = {}
    for liga, temp, fm, eq, pos in rows:
        if fm in ("anual", "liga"):
            out[(liga, temp, eq)] = pos
    return out


def calcular_promedios_xg_por_equipo(con, coefs_v13):
    """Para cada (liga, temp, equipo): promedio xG_v13 cuando juega de local."""
    cur = con.cursor()
    rows = cur.execute("""
        SELECT p.liga, p.temp, p.local, p.visita, substr(p.fecha,1,10) as fecha
        FROM predicciones_oos_con_features p
    """).fetchall()
    promedios = defaultdict(list)
    for liga, temp, local, visita, fecha in rows:
        # Lookup EMA local + visita
        cols_sql = "ema_l_sots, ema_l_shot_pct, ema_l_pos, ema_l_pass_pct, ema_l_corners, " \
                   "ema_l_yellow, ema_l_red, ema_l_fouls, ema_l_shots, ema_c_sots, " \
                   "ema_c_shot_pct, ema_c_tackles, ema_c_blocks"
        EMA_COLS = ["ema_l_sots", "ema_l_shot_pct", "ema_l_pos", "ema_l_pass_pct",
                    "ema_l_corners", "ema_l_yellow", "ema_l_red", "ema_l_fouls",
                    "ema_l_shots", "ema_c_sots", "ema_c_shot_pct", "ema_c_tackles", "ema_c_blocks"]
        r_l = cur.execute(f"""SELECT {cols_sql} FROM historial_equipos_stats
                                 WHERE liga=? AND equipo=? AND fecha < ? AND n_acum>=5
                                 ORDER BY fecha DESC LIMIT 1""", (liga, local, fecha)).fetchone()
        r_v = cur.execute(f"""SELECT {cols_sql} FROM historial_equipos_stats
                                 WHERE liga=? AND equipo=? AND fecha < ? AND n_acum>=5
                                 ORDER BY fecha DESC LIMIT 1""", (liga, visita, fecha)).fetchone()
        if not r_l or not r_v: continue
        atk = dict(zip(EMA_COLS, r_l)); df = dict(zip(EMA_COLS, r_v))
        if any(v is None for v in atk.values()) or any(v is None for v in df.values()):
            continue
        # V13 xG_local
        xg_l = calcular_xg_v13(coefs_v13, liga, atk, df, target_local=True)
        if xg_l is None: continue
        # Acumular para ese equipo (liga, temp, local)
        promedios[(liga, temp, local)].append({
            "xg_v13": xg_l,
            "ema_sots": atk["ema_l_sots"],
            "ema_shot_pct": atk["ema_l_shot_pct"],
            "ema_pos": atk["ema_l_pos"],
            "ema_diff_sots": atk["ema_l_sots"] - atk.get("ema_c_sots", 0),
        })
    return promedios


def main():
    con = sqlite3.connect(DB)
    print("=" * 80)
    print("Audit: ¿V13 xG ya capta pos_backward (calidad estructural)?")
    print("=" * 80)

    print("\nCargando coefs V13...")
    coefs = cargar_v13_coefs(con)
    print(f"  Ligas V13: {sorted(coefs.keys())}")

    print("Cargando pos_backward...")
    pos_back = cargar_pos_backward(con)
    print(f"  Tuples (liga, temp, equipo): {len(pos_back):,}")

    print("Calculando xG V13 promedio por (liga, temp, equipo)...")
    promedios = calcular_promedios_xg_por_equipo(con, coefs)
    print(f"  Equipos con datos: {len(promedios):,}")

    print("\n=== Correlacion pos_backward vs proxies (esperamos r < -0.3) ===")
    print(f"  (Pearson r negativo = mejor pos final correlaciona con mayor xG/EMA)")
    print()
    print(f"{'liga':<14} {'temp':<5} {'N':>4} {'r(xg_v13)':>11} {'r(ema_sots)':>12} {'r(shot_pct)':>12} {'r(diff_sots)':>13}")
    print("-" * 85)
    payload = {"fecha": datetime.now().isoformat(), "correlaciones": defaultdict(dict)}

    for liga in LIGAS_TOP5 + ["Italia", "Francia", "Espana", "Alemania"]:
        for temp in [2022, 2023, 2024]:
            equipos = [eq for (l, t, eq) in promedios.keys() if l == liga and t == temp]
            if len(equipos) < 6: continue
            x_pos = []
            y_xgv13, y_sots, y_shotpct, y_diff_sots = [], [], [], []
            for eq in equipos:
                pos = pos_back.get((liga, temp, eq))
                if pos is None: continue
                stats_partidos = promedios[(liga, temp, eq)]
                if not stats_partidos: continue
                x_pos.append(float(pos))
                y_xgv13.append(float(np.mean([s["xg_v13"] for s in stats_partidos])))
                y_sots.append(float(np.mean([s["ema_sots"] for s in stats_partidos])))
                y_shotpct.append(float(np.mean([s["ema_shot_pct"] for s in stats_partidos])))
                y_diff_sots.append(float(np.mean([s["ema_diff_sots"] for s in stats_partidos])))
            if len(x_pos) < 6: continue
            x = np.array(x_pos)
            r_xgv13 = float(np.corrcoef(x, y_xgv13)[0, 1]) if len(set(y_xgv13)) > 1 else None
            r_sots = float(np.corrcoef(x, y_sots)[0, 1]) if len(set(y_sots)) > 1 else None
            r_shotpct = float(np.corrcoef(x, y_shotpct)[0, 1]) if len(set(y_shotpct)) > 1 else None
            r_diff = float(np.corrcoef(x, y_diff_sots)[0, 1]) if len(set(y_diff_sots)) > 1 else None

            def fmt(r):
                if r is None: return "n/a"
                marker = "*" if r is not None and abs(r) > 0.5 else ""
                return f"{r:+.3f}{marker}"

            print(f"{liga:<14} {temp:<5} {len(x_pos):>4} {fmt(r_xgv13):>11} {fmt(r_sots):>12} "
                  f"{fmt(r_shotpct):>12} {fmt(r_diff):>13}")
            payload["correlaciones"][liga][str(temp)] = {
                "n_equipos": len(x_pos),
                "r_xg_v13": round(r_xgv13, 4) if r_xgv13 is not None else None,
                "r_ema_sots": round(r_sots, 4) if r_sots is not None else None,
                "r_ema_shot_pct": round(r_shotpct, 4) if r_shotpct is not None else None,
                "r_diff_sots": round(r_diff, 4) if r_diff is not None else None,
            }

    # Veredicto
    print(f"\n=== VEREDICTO ===")
    print("  Buscar correlacion r < -0.3 (consistente y multiples temps).")
    print("  Si V13 r < -0.3 cross-temp -> V13 ya capta calidad estructural -> bead cierra.")
    print("  Si NO -> bead queda abierto, construir feature explicito.")
    todas_v13 = [v["r_xg_v13"] for liga_data in payload["correlaciones"].values()
                 for v in liga_data.values() if v.get("r_xg_v13") is not None]
    if todas_v13:
        avg_v13 = float(np.mean(todas_v13))
        print(f"  Promedio r(xg_v13, pos_backward) cross-(liga,temp): {avg_v13:+.3f}")
        if avg_v13 < -0.3:
            veredicto = "V13 captura calidad estructural - bead a1v puede cerrar"
        elif avg_v13 < -0.1:
            veredicto = "V13 captura parcialmente - construir feature mejorado"
        else:
            veredicto = "V13 NO captura calidad estructural - feature explicito necesario"
        print(f"  Veredicto: {veredicto}")
        payload["veredicto"] = {"avg_r_v13": round(avg_v13, 3), "interpretacion": veredicto}

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()

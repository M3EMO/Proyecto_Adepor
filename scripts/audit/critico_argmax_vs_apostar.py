"""Critico extension: analyze how argmax predictions interact with motor's existing filters.

The walk-forward measures argmax hit rate, NOT [APOSTAR] yield. The motor has many
layers (FLOOR_PROB_MIN, EV filter, MARGEN_PREDICTIVO already at 0.03, divergencia,
Caminos 1-4, etc.) that already filter most picks out.

This script examines: among the predictions where argmax wins, how many would
make it through the FLOOR_PROB_MIN=0.33 filter and the existing 0.03 margen filter?
And what's the gap between current 0.03 and proposed 0.05?
"""
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "fondo_quant.db"
CACHE = ROOT / "analisis" / "cache_espn"

ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
RANGO_POISSON = 10
EMA_INIT = 1.4
TEMPS_TRAIN = [2022, 2023]
TEMP_PREDICT = 2024


def poisson(k, lam):
    if lam <= 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (ValueError, OverflowError):
        return 0.0


def tau(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return max(0.0, 1.0 - lam * mu * rho)
    if i == 0 and j == 1:
        return max(0.0, 1.0 + lam * rho)
    if i == 1 and j == 0:
        return max(0.0, 1.0 + mu * rho)
    if i == 1 and j == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def calcular_probs_1x2(xg_l, xg_v, rho):
    p1 = px = p2 = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
    total = p1 + px + p2
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p1/total, px/total, p2/total


def xg_hibrido(sot, shots, corners, goles, coef_c):
    shots_off = max(0, shots - sot)
    xg_calc = (sot * BETA_SOT) + (shots_off * BETA_SHOTS_OFF) + (corners * coef_c)
    if xg_calc == 0 and goles > 0:
        return float(goles)
    return xg_calc * 0.70 + goles * 0.30


def init_estado():
    return {
        "fav_home": EMA_INIT, "con_home": EMA_INIT, "p_home": 0,
        "fav_away": EMA_INIT, "con_away": EMA_INIT, "p_away": 0,
    }


def actualizar_estado(estado, equipo, xg_f, xg_c, is_home, prom):
    if equipo not in estado:
        estado[equipo] = init_estado()
    e = estado[equipo]
    if is_home:
        ema_f = xg_f * ALFA_EMA + e["fav_home"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_home"] * (1 - ALFA_EMA)
        N = e["p_home"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_home"] = w_ema * ema_f + w_liga * prom
        e["con_home"] = w_ema * ema_c + w_liga * prom
        e["p_home"] += 1
    else:
        ema_f = xg_f * ALFA_EMA + e["fav_away"] * (1 - ALFA_EMA)
        ema_c = xg_c * ALFA_EMA + e["con_away"] * (1 - ALFA_EMA)
        N = e["p_away"]
        w_liga = N0_ANCLA / (N0_ANCLA + N) if (N0_ANCLA + N) > 0 else 1.0
        w_ema = 1.0 - w_liga
        e["fav_away"] = w_ema * ema_f + w_liga * prom
        e["con_away"] = w_ema * ema_c + w_liga * prom
        e["p_away"] += 1


def get_rho_y_corner(liga):
    con = sqlite3.connect(DB)
    r = con.execute(
        "SELECT rho_calculado, coef_corner_calculado FROM ligas_stats WHERE liga = ?",
        (liga,),
    ).fetchone()
    con.close()
    rho = r[0] if r else -0.09
    coef_c = r[1] if r and r[1] is not None else 0.02
    return rho, coef_c


def cargar_partidos_liga(liga, temps):
    todos = []
    for t in temps:
        f = CACHE / f"{liga}_{t}.json"
        if f.exists():
            partidos = json.loads(f.read_text(encoding="utf-8"))
            for p in partidos:
                p["temp"] = t
                fe = p.get("fecha", "")
                if isinstance(fe, str) and "T" in fe:
                    p["fecha"] = fe.replace("T", " ").replace("Z", "")
            todos.extend(partidos)
    if not todos:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        rows = cur.execute(
            """
            SELECT fecha, ht, at, hg, ag, hst, ast, hs, as_, hc, ac, temp
            FROM partidos_historico_externo
            WHERE liga = ? AND temp IN (2022, 2023, 2024) AND has_full_stats = 1
            ORDER BY fecha
            """,
            (liga,),
        ).fetchall()
        todos = [{
            "fecha": r[0], "ht": r[1], "at": r[2], "hg": r[3], "ag": r[4],
            "hst": r[5] or 0, "ast": r[6] or 0, "hs": r[7] or 0,
            "as": r[8] or 0, "hc": r[9] or 0, "ac": r[10] or 0,
            "temp": r[11],
        } for r in rows]
        con.close()
    if not todos:
        return []

    def parse_fecha(p):
        try:
            return datetime.fromisoformat(p["fecha"][:19].replace(" ", "T"))
        except (ValueError, KeyError):
            return datetime.min

    todos.sort(key=parse_fecha)
    return todos


def correr_liga(liga, partidos):
    rho, coef_c = get_rho_y_corner(liga)
    prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
    estado = {}
    predicciones = []
    for p in partidos:
        try:
            year = datetime.fromisoformat(p["fecha"][:19].replace(" ", "T")).year
        except (ValueError, KeyError):
            continue
        es_target = year == TEMP_PREDICT or p.get("temp") == TEMP_PREDICT

        if es_target:
            el = estado.get(p["ht"], init_estado())
            ev = estado.get(p["at"], init_estado())
            xg_l = (el["fav_home"] + ev["con_away"]) / 2.0
            xg_v = (ev["fav_away"] + el["con_home"]) / 2.0
            p1, px, p2 = calcular_probs_1x2(xg_l, xg_v, rho)
            sorted_probs = sorted([p1, px, p2], reverse=True)
            margen = sorted_probs[0] - sorted_probs[1]
            p_max = sorted_probs[0]
            p_2nd = sorted_probs[1]
            if p["hg"] > p["ag"]:
                outcome = "1"
            elif p["hg"] == p["ag"]:
                outcome = "X"
            else:
                outcome = "2"
            argmax = max([("1", p1), ("X", px), ("2", p2)], key=lambda x: x[1])[0]
            hit = argmax == outcome
            predicciones.append({
                "liga": liga, "p_max": p_max, "p_2nd": p_2nd, "argmax": argmax,
                "outcome": outcome, "hit": int(hit), "margen": margen,
            })

        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        else:
            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        actualizar_estado(estado, p["ht"], xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, p["at"], xg_real_v, xg_real_l, False, prom)

    return predicciones


def main():
    LIGAS = ["Inglaterra", "Italia", "Espana", "Francia", "Alemania", "Turquia",
             "Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
             "Ecuador", "Peru", "Uruguay", "Venezuela"]

    # Get current per-liga margen settings
    con = sqlite3.connect(DB)
    cur = con.cursor()
    margen_actual_por_liga = {}
    for liga in LIGAS + ["Noruega"]:
        r = cur.execute(
            "SELECT valor_real FROM config_motor_valores WHERE clave='margen_predictivo_1x2' AND scope=?",
            (liga,),
        ).fetchone()
        margen_actual_por_liga[liga] = r[0] if r else 0.03
    con.close()

    print("=" * 80)
    print("Audit critico: argmax vs aplicado al motor real")
    print("=" * 80)
    print()
    print("Margen actual por liga (config_motor_valores):")
    for liga, m in margen_actual_por_liga.items():
        print(f"  {liga:<13}: {m:.3f}")
    print()

    all_preds = []
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, TEMPS_TRAIN + [TEMP_PREDICT])
        if not partidos:
            continue
        preds = correr_liga(liga, partidos)
        all_preds.extend(preds)

    n_total = len(all_preds)
    print(f"Total predictions: {n_total}")
    print()

    # Analyze: how many pass FLOOR=0.33, EMPATE block, and various margen thresholds?
    # FILTRO 1: FLOOR_PROB_MIN=0.33 + APUESTA_EMPATE_PERMITIDA=False
    n_pass_floor_no_empate = 0
    n_pass_floor_no_empate_hit = 0
    for p in all_preds:
        if p["argmax"] == "X":
            continue  # block empates
        if p["p_max"] < 0.33:
            continue
        n_pass_floor_no_empate += 1
        n_pass_floor_no_empate_hit += p["hit"]
    print(f"After FLOOR=0.33 + no_empates:  N={n_pass_floor_no_empate} ({100*n_pass_floor_no_empate/n_total:.1f}%)  hit={n_pass_floor_no_empate_hit/n_pass_floor_no_empate:.4f}")

    # Now apply existing per-liga margen
    n_pass_actual_margen = 0
    n_hit_actual_margen = 0
    for p in all_preds:
        if p["argmax"] == "X":
            continue
        if p["p_max"] < 0.33:
            continue
        m_liga = margen_actual_por_liga.get(p["liga"], 0.03)
        if p["margen"] < m_liga:
            continue
        n_pass_actual_margen += 1
        n_hit_actual_margen += p["hit"]
    print(f"After actual per-liga margen:    N={n_pass_actual_margen} ({100*n_pass_actual_margen/n_total:.1f}%)  hit={n_hit_actual_margen/n_pass_actual_margen:.4f}")

    # Apply proposed 0.05 globally
    n_pass_proposed = 0
    n_hit_proposed = 0
    for p in all_preds:
        if p["argmax"] == "X":
            continue
        if p["p_max"] < 0.33:
            continue
        if p["margen"] < 0.05:
            continue
        n_pass_proposed += 1
        n_hit_proposed += p["hit"]
    print(f"After PROPOSED margen 0.05:      N={n_pass_proposed} ({100*n_pass_proposed/n_total:.1f}%)  hit={n_hit_proposed/n_pass_proposed:.4f}")

    print()
    print("DIFERENCIAL del cambio (actual_per_liga -> proposed_0.05):")
    delta_n = n_pass_actual_margen - n_pass_proposed
    print(f"  N que pierden con upgrade:  {delta_n} (de {n_pass_actual_margen} -> {n_pass_proposed})")
    print(f"  Hit en zona actual:         {n_hit_actual_margen / n_pass_actual_margen:.4f}")
    print(f"  Hit en zona proposed:       {n_hit_proposed / n_pass_proposed:.4f}")
    delta_hit = n_hit_proposed/n_pass_proposed - n_hit_actual_margen/n_pass_actual_margen
    print(f"  delta_hit incremental:      {delta_hit:+.4f}")
    # Picks bloqueados nuevos: cuanto hit teniann?
    bloqueados = []
    for p in all_preds:
        if p["argmax"] == "X":
            continue
        if p["p_max"] < 0.33:
            continue
        m_liga = margen_actual_por_liga.get(p["liga"], 0.03)
        if p["margen"] < m_liga:
            continue
        if p["margen"] < 0.05:
            bloqueados.append(p)
    if bloqueados:
        hit_bloqueados = sum(b["hit"] for b in bloqueados) / len(bloqueados)
        print(f"  Picks bloqueados (en gap):  N={len(bloqueados)} hit_rate={hit_bloqueados:.4f}")
        print(f"     Si hit_rate < ~50%, bloquearlos MEJORA el sistema (filtro positivo)")

    # Per-liga breakdown of zona [actual_margen, 0.05)
    print()
    print("Per-liga: hit rate en zona bloqueada por la propuesta")
    print(f"{'Liga':<13}  {'margen_actual':>13}  {'N_zona_bloqueada':>17}  {'hit_zona':>9}")
    for liga in LIGAS:
        m_liga = margen_actual_por_liga.get(liga, 0.03)
        zona_blocked = [p for p in all_preds
                        if p["liga"] == liga
                        and p["argmax"] != "X"
                        and p["p_max"] >= 0.33
                        and p["margen"] >= m_liga
                        and p["margen"] < 0.05]
        if not zona_blocked:
            continue
        hit_blocked = sum(b["hit"] for b in zona_blocked) / len(zona_blocked)
        n_blocked = len(zona_blocked)
        print(f"{liga:<13}  {m_liga:>13.3f}  {n_blocked:>17}  {hit_blocked:>9.4f}")


if __name__ == "__main__":
    main()

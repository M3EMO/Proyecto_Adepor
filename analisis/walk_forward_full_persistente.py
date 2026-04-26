"""Walk-forward COMPLETO con persistencia de TODAS las predicciones.

A diferencia de walk_forward_full_stats.py (que solo guarda agregados), este
graba CADA prediccion en partidos_historico_externo.predicciones_walkforward.

Para cada liga y temp en (2022, 2023, 2024):
  - Train: temps anteriores (warmup)
  - Predict: temp actual (cada partido)

Asi acumulamos ~12k predicciones cross-liga (vs 434 actuales en partidos_backtest)
para usar como train set de calibracion.

Setup:
  - Walk-forward CADA temp (no solo target=2024). Para temp 2022, train con 2022 partial.
  - Goal: maximizar N de predicciones training set.
"""
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
CACHE = ROOT / "analisis" / "cache_espn"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Constantes idem motor
ALFA_EMA = 0.18
N0_ANCLA = 5
BETA_SOT = 0.352
BETA_SHOTS_OFF = 0.010
RANGO_POISSON = 10
EMA_INIT = 1.4

# Warmup: cuantos partidos antes de empezar a predecir (para que EMA tenga senal)
N_WARMUP_PER_TEAM = 3


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
        (liga,)
    ).fetchone()
    con.close()
    rho = r[0] if r else -0.09
    coef_c = r[1] if r and r[1] is not None else 0.02
    return rho, coef_c


def cargar_partidos_liga(liga, temps):
    """Carga partidos: priorizar cache_espn, fallback a partidos_historico_externo."""
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
            """, (liga,)
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


def correr_liga_persistente(liga, partidos, fecha_run):
    """Walk-forward, prediciendo CADA partido despues de N_WARMUP por equipo.
    Persiste predicciones a DB.
    """
    rho, coef_c = get_rho_y_corner(liga)
    prom = sum(p["hg"] + p["ag"] for p in partidos) / (len(partidos) * 2)
    estado = {}

    con = sqlite3.connect(DB)
    cur = con.cursor()

    n_predict = 0
    n_skip = 0
    for p in partidos:
        ht = p["ht"]; at = p["at"]
        # Verificar warmup
        e_l = estado.get(ht); e_v = estado.get(at)
        warmup_ok = (
            e_l is not None and e_v is not None
            and (e_l["p_home"] + e_l["p_away"]) >= N_WARMUP_PER_TEAM
            and (e_v["p_home"] + e_v["p_away"]) >= N_WARMUP_PER_TEAM
        )

        if warmup_ok:
            # Predecir
            xg_l_pred = (e_l["fav_home"] + e_v["con_away"]) / 2.0
            xg_v_pred = (e_v["fav_away"] + e_l["con_home"]) / 2.0
            p1, px, p2 = calcular_probs_1x2(xg_l_pred, xg_v_pred, rho)
            sorted_probs = sorted([p1, px, p2], reverse=True)
            margen = sorted_probs[0] - sorted_probs[1]
            if p["hg"] > p["ag"]:
                outcome = "1"
            elif p["hg"] == p["ag"]:
                outcome = "X"
            else:
                outcome = "2"

            try:
                cur.execute("""
                    INSERT INTO predicciones_walkforward
                    (fecha_run, liga, temp, fecha_partido, ht, at, hg, ag,
                     outcome, xg_l_pred, xg_v_pred, prob_1, prob_x, prob_2, margen, fuente)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (fecha_run, liga, p["temp"], p["fecha"], ht, at, p["hg"], p["ag"],
                      outcome, xg_l_pred, xg_v_pred, p1, px, p2, margen,
                      "walk_forward_persistente"))
                n_predict += 1
            except sqlite3.IntegrityError:
                n_skip += 1
        else:
            # No warmup, no predecir
            n_skip += 1

        # Update estado
        if p.get("hs", 0) == 0 and p.get("hst", 0) == 0:
            xg_real_l = float(p["hg"])
            xg_real_v = float(p["ag"])
        else:
            xg_real_l = xg_hibrido(p["hst"], p["hs"], p["hc"], p["hg"], coef_c)
            xg_real_v = xg_hibrido(p["ast"], p["as"], p["ac"], p["ag"], coef_c)
        actualizar_estado(estado, ht, xg_real_l, xg_real_v, True, prom)
        actualizar_estado(estado, at, xg_real_v, xg_real_l, False, prom)

    con.commit()
    con.close()
    return n_predict, n_skip


def main():
    fecha_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LIGAS = [
        "Inglaterra", "Italia", "Espana", "Francia", "Alemania", "Turquia",
        "Argentina", "Brasil", "Bolivia", "Chile", "Colombia",
        "Ecuador", "Peru", "Uruguay", "Venezuela",
    ]
    print(f"=== Walk-forward COMPLETO persistente — {fecha_run} ===\n")

    total_predict = 0
    total_skip = 0
    for liga in LIGAS:
        partidos = cargar_partidos_liga(liga, [2022, 2023, 2024])
        if not partidos:
            print(f"  {liga}: SIN DATOS")
            continue
        n_p, n_s = correr_liga_persistente(liga, partidos, fecha_run)
        print(f"  {liga:<13} N_input={len(partidos):>5}  predicciones={n_p:>5}  skip(warmup/dup)={n_s}")
        total_predict += n_p
        total_skip += n_s

    print()
    print(f"=== TOTAL ===")
    print(f"  Predicciones nuevas: {total_predict}")
    print(f"  Skip (warmup/duplicados): {total_skip}")

    # Verificar
    con = sqlite3.connect(DB)
    n_db = con.execute("SELECT COUNT(*) FROM predicciones_walkforward").fetchone()[0]
    print(f"  Total en DB: {n_db}")
    con.close()


if __name__ == "__main__":
    main()

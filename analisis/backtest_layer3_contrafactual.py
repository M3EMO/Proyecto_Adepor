"""
Paso 2 — Backtest contrafactual Layer 3 sobre in-sample 2026 LIQUIDADOS.

Recorre partidos_backtest in-sample 2026 ARG+ITA+ING+ALE con estado=LIQUIDADO,
aplica logica Layer 3 hipotetica, y calcula:
- N por branch (APLICA, SKIP_TOP3, SKIP_CANSADOS, etc.)
- Yield V0 vs override X sobre APLICA liquidados
- Yield filtrado por M.1 (solo ligas apostables: ARG+ING)
- Hit rate, ROI, delta CI95

Output: analisis/backtest_layer3_contrafactual.json
"""
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.nucleo.motor_calculadora import (  # noqa: E402
    _calcular_probs_v12_lr,
    _get_pos_local_forward,
    _get_gap_dias_no_liga,
    _get_xg_v6_para_partido,
)
from src.comun.gestor_nombres import limpiar_texto  # noqa: E402

DB_PATH = "fondo_quant.db"
LIGAS = ["Argentina", "Italia", "Inglaterra", "Alemania"]
LIGAS_M1 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]


def ci95(yields):
    """Wilson CI95 sobre yield/sample. Aprox: media +/- 1.96*sd/sqrt(n)."""
    if not yields:
        return None, None, None
    n = len(yields)
    media = sum(yields) / n
    var = sum((y - media) ** 2 for y in yields) / max(1, n - 1)
    se = math.sqrt(var / n)
    return media, media - 1.96 * se, media + 1.96 * se


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    h4_thresh_map = json.loads(conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='h4_x_rescue_threshold' AND scope='global'"
    ).fetchone()[0])
    arch_json = conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='arch_decision_per_liga' AND scope='global'"
    ).fetchone()
    arch_map = json.loads(arch_json[0]) if arch_json and arch_json[0] else {}
    print(f"Layer 3 config: {h4_thresh_map}")
    print(f"Layer 2 config: {arch_map}\n")

    placeholders = ",".join("?" * len(LIGAS))
    rows = conn.execute(
        f"""
        SELECT id_partido, fecha, pais, local, visita,
               cuota_1, cuota_x, cuota_2, estado, goles_l, goles_v
        FROM partidos_backtest
        WHERE pais IN ({placeholders})
          AND fecha >= '2026-01-01'
          AND estado = 'Liquidado'
        ORDER BY fecha
        """,
        LIGAS,
    ).fetchall()
    print(f"Partidos LIQUIDADOS analizados: {len(rows)}\n")

    counts = Counter()
    counts_por_liga = defaultdict(Counter)
    aplica_picks = []  # info por pick para yield calc
    skip_picks = defaultdict(list)

    for row in rows:
        (idp, fecha, pais, local, visita,
         c1, cx, c2, estado, gl, gv) = row
        thresh = h4_thresh_map.get(pais)
        if not thresh:
            counts["NO_LIGA"] += 1
            continue
        if arch_map.get(pais) == "V12":
            counts["LAYER2_BLOCKED"] += 1
            continue

        loc_norm = limpiar_texto(local) if local else None
        vis_norm = limpiar_texto(visita) if visita else None
        xg_l, xg_v = _get_xg_v6_para_partido(loc_norm, vis_norm, conn)
        if xg_l is None or xg_v is None:
            counts["XG_V6_FAIL"] += 1
            continue
        try:
            p1_v12, px_v12, p2_v12 = _calcular_probs_v12_lr(
                xg_l, xg_v, loc_norm, vis_norm, pais, fecha, conn)
        except Exception:
            counts["V12_FAIL"] += 1
            continue

        argmax = "X" if px_v12 == max(p1_v12, px_v12, p2_v12) else \
                 ("1" if p1_v12 >= p2_v12 else "2")
        if argmax != "X":
            counts["NO_X"] += 1
            counts_por_liga[pais]["NO_X"] += 1
            continue
        if px_v12 <= thresh:
            counts["NO_THRESH"] += 1
            counts_por_liga[pais]["NO_THRESH"] += 1
            continue

        pos_l = _get_pos_local_forward(pais, loc_norm, fecha, conn)
        gap_l = _get_gap_dias_no_liga(loc_norm, fecha, conn)
        gap_v = _get_gap_dias_no_liga(vis_norm, fecha, conn)
        local_top3 = pos_l is not None and pos_l <= 3
        ambos_cansados = (gap_l is not None and gap_l <= 14
                          and gap_v is not None and gap_v <= 14)

        if local_top3 and ambos_cansados:
            branch = "SKIP_AMBOS"
        elif local_top3:
            branch = "SKIP_TOP3"
        elif ambos_cansados:
            branch = "SKIP_CANSADOS"
        else:
            branch = "APLICA_CON_NULL" if (
                pos_l is None or gap_l is None or gap_v is None) else "APLICA"

        counts[branch] += 1
        counts_por_liga[pais][branch] += 1

        info = {
            "id": idp, "fecha": fecha, "pais": pais,
            "local": local, "visita": visita,
            "px_v12": px_v12, "thresh": thresh,
            "p1_v12": p1_v12, "p2_v12": p2_v12,
            "pos_l": pos_l, "gap_l": gap_l, "gap_v": gap_v,
            "c1": c1, "cx": cx, "c2": c2,
            "gl": gl, "gv": gv, "estado": estado,
            "pasa_m1": pais in LIGAS_M1,
        }
        if branch.startswith("APLICA"):
            aplica_picks.append({**info, "branch": branch})
        else:
            skip_picks[branch].append(info)

    conn.close()

    # Yield V0 vs override sobre APLICA
    def calc_yield(picks, filtro_m1=False):
        yields_v0 = []
        yields_x = []
        for p in picks:
            if filtro_m1 and not p["pasa_m1"]:
                continue
            if p["gl"] is None or p["gv"] is None:
                continue
            argmax_v0_p = ("X" if (1.0 - p["p1_v12"] - p["p2_v12"]) > max(p["p1_v12"], p["p2_v12"])
                          else ("1" if p["p1_v12"] >= p["p2_v12"] else "2"))
            # V0 picks: para sanity uso V12 mismo argmax NO X (porque p_V0 raw no esta en log)
            # Aproximacion: V0 elegiria 1 o 2 (lo que tenga mas prob entre p1 y p2)
            if p["p1_v12"] >= p["p2_v12"]:
                argmax_v0 = "1"
                cuota_v0 = p["c1"]
            else:
                argmax_v0 = "2"
                cuota_v0 = p["c2"]
            # Si V0 tambien hubiera elegido X (no comun), no tenemos cuota distinta
            if cuota_v0:
                res_v0 = ((p["gl"] > p["gv"] and argmax_v0 == "1")
                          or (p["gl"] < p["gv"] and argmax_v0 == "2"))
                yields_v0.append((cuota_v0 - 1) if res_v0 else -1)
            if p["cx"]:
                res_x = (p["gl"] == p["gv"])
                yields_x.append((p["cx"] - 1) if res_x else -1)
        return yields_v0, yields_x

    print("=" * 70)
    print(f"COUNTS POR BRANCH")
    print("=" * 70)
    for b in ["APLICA", "APLICA_CON_NULL", "SKIP_TOP3", "SKIP_CANSADOS", "SKIP_AMBOS",
              "NO_X", "NO_THRESH", "NO_LIGA", "LAYER2_BLOCKED", "XG_V6_FAIL", "V12_FAIL"]:
        n = counts.get(b, 0)
        if n:
            print(f"  {b:<20s} {n:>5d}")

    print("\nPOR LIGA (solo APLICA/SKIP):")
    for liga in LIGAS:
        sub = counts_por_liga[liga]
        relevant = {b: sub.get(b, 0) for b in ["APLICA", "APLICA_CON_NULL", "SKIP_TOP3", "SKIP_CANSADOS", "SKIP_AMBOS"] if sub.get(b, 0)}
        if relevant:
            print(f"  {liga}: {relevant}")

    # Yield TODOS APLICA
    yields_v0_all, yields_x_all = calc_yield(aplica_picks, filtro_m1=False)
    print("\n" + "=" * 70)
    print(f"YIELD APLICA TODOS (sin filtro M.1)")
    print("=" * 70)
    if yields_v0_all:
        m, lo, hi = ci95(yields_v0_all)
        hits = sum(1 for y in yields_v0_all if y > 0)
        print(f"  V0  N={len(yields_v0_all)} hit={hits/len(yields_v0_all):.3f} yield={m:+.3f} CI95=[{lo:+.3f},{hi:+.3f}]")
    if yields_x_all:
        m, lo, hi = ci95(yields_x_all)
        hits = sum(1 for y in yields_x_all if y > 0)
        print(f"  X   N={len(yields_x_all)} hit={hits/len(yields_x_all):.3f} yield={m:+.3f} CI95=[{lo:+.3f},{hi:+.3f}]")
    if yields_v0_all and yields_x_all:
        delta = (sum(yields_x_all) / len(yields_x_all)) - (sum(yields_v0_all) / len(yields_v0_all))
        print(f"  Delta (X - V0): {delta:+.3f}")

    # Yield filtrado M.1
    yields_v0_m1, yields_x_m1 = calc_yield(aplica_picks, filtro_m1=True)
    print("\n" + "=" * 70)
    print(f"YIELD APLICA con filtro M.1 (solo ligas apostables: ARG/ING)")
    print("=" * 70)
    if yields_v0_m1:
        m, lo, hi = ci95(yields_v0_m1)
        hits = sum(1 for y in yields_v0_m1 if y > 0)
        print(f"  V0  N={len(yields_v0_m1)} hit={hits/len(yields_v0_m1):.3f} yield={m:+.3f} CI95=[{lo:+.3f},{hi:+.3f}]")
    if yields_x_m1:
        m, lo, hi = ci95(yields_x_m1)
        hits = sum(1 for y in yields_x_m1 if y > 0)
        print(f"  X   N={len(yields_x_m1)} hit={hits/len(yields_x_m1):.3f} yield={m:+.3f} CI95=[{lo:+.3f},{hi:+.3f}]")
    if yields_v0_m1 and yields_x_m1:
        delta = (sum(yields_x_m1) / len(yields_x_m1)) - (sum(yields_v0_m1) / len(yields_v0_m1))
        print(f"  Delta (X - V0): {delta:+.3f}")

    # Detalle picks APLICA
    print("\n" + "=" * 70)
    print(f"DETALLE APLICA ({len(aplica_picks)} picks)")
    print("=" * 70)
    for p in aplica_picks:
        res = "X" if p["gl"] == p["gv"] else ("1" if p["gl"] > p["gv"] else "2")
        m1_mark = "" if p["pasa_m1"] else " [NO-M1]"
        null_mark = " [NULLs]" if p["branch"] == "APLICA_CON_NULL" else ""
        print(f"  {p['fecha']} {p['pais']:<11s} {p['local']:<22s} vs {p['visita']:<22s} | "
              f"P_v12(X)={p['px_v12']:.3f} pos_l={p['pos_l']} gap_l={p['gap_l']} gap_v={p['gap_v']} | "
              f"cx={p['cx']} | resultado={p['gl']}-{p['gv']} ({res}){m1_mark}{null_mark}")

    out = {
        "config_layer3": h4_thresh_map,
        "n_partidos_evaluados": len(rows),
        "counts": dict(counts),
        "counts_por_liga": {k: dict(v) for k, v in counts_por_liga.items()},
        "n_aplica": len(aplica_picks),
        "yield_v0_all": (sum(yields_v0_all) / len(yields_v0_all)) if yields_v0_all else None,
        "yield_x_all": (sum(yields_x_all) / len(yields_x_all)) if yields_x_all else None,
        "yield_v0_m1": (sum(yields_v0_m1) / len(yields_v0_m1)) if yields_v0_m1 else None,
        "yield_x_m1": (sum(yields_x_m1) / len(yields_x_m1)) if yields_x_m1 else None,
        "n_v0_all": len(yields_v0_all),
        "n_v0_m1": len(yields_v0_m1),
        "aplica_picks": aplica_picks,
    }
    Path("analisis/backtest_layer3_contrafactual.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/backtest_layer3_contrafactual.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: analisis/backtest_layer3_contrafactual.json")


if __name__ == "__main__":
    main()

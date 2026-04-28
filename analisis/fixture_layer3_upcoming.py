"""
Paso 5 — Fixture upcoming Layer 3.

Recorre partidos_backtest con fecha >= hoy en ligas ARG+ITA+ING+ALE proximos
14 dias y reporta cuales DISPARARIAN override Layer 3 (APLICA, APLICA_CON_NULL,
SKIP_TOP3, SKIP_CANSADOS) cuando lleguen al motor.

Output: analisis/fixture_layer3_upcoming.json
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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
DIAS_ADELANTE = 14


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    h4_thresh_map = json.loads(conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='h4_x_rescue_threshold' AND scope='global'"
    ).fetchone()[0])
    print(f"Layer 3 config: {h4_thresh_map}\n")
    if not h4_thresh_map:
        print("Layer 3 INACTIVO. Nada que reportar.")
        return

    arch_json = conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='arch_decision_per_liga' AND scope='global'"
    ).fetchone()
    arch_map = json.loads(arch_json[0]) if arch_json and arch_json[0] else {}

    fecha_max = (datetime.now() + timedelta(days=DIAS_ADELANTE)).strftime("%Y-%m-%d")
    placeholders = ",".join("?" * len(LIGAS))
    rows = conn.execute(
        f"""
        SELECT id_partido, fecha, pais, local, visita, cuota_1, cuota_x, cuota_2, estado
        FROM partidos_backtest
        WHERE pais IN ({placeholders})
          AND fecha >= date('now','localtime')
          AND fecha <= ?
        ORDER BY fecha
        """,
        (*LIGAS, fecha_max),
    ).fetchall()
    print(f"Fixture upcoming proximo {DIAS_ADELANTE}d: {len(rows)} partidos\n")

    counts = Counter()
    counts_por_liga = defaultdict(Counter)
    overrides_predichos = []
    skips_predichos = []
    no_x_count = []

    for row in rows:
        idp, fecha, pais, local, visita, c1, cx, c2, estado = row
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
            counts_por_liga[pais]["XG_V6_FAIL"] += 1
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
            no_x_count.append((fecha, pais, local, visita))
            continue
        if px_v12 <= thresh:
            counts["NO_THRESH"] += 1
            counts_por_liga[pais]["NO_THRESH"] += 1
            continue

        # Pasa thresh — evaluar filtros
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
            branch = "APLICA"

        if branch == "APLICA" and (pos_l is None or gap_l is None or gap_v is None):
            branch = "APLICA_CON_NULL"

        counts[branch] += 1
        counts_por_liga[pais][branch] += 1

        info = {
            "id": idp, "fecha": fecha, "pais": pais,
            "local": local, "visita": visita,
            "px_v12": round(px_v12, 3), "thresh": thresh,
            "pos_local": pos_l, "gap_l": gap_l, "gap_v": gap_v,
            "p1_v12": round(p1_v12, 3), "p2_v12": round(p2_v12, 3),
            "cuota_x": cx, "estado": estado,
        }
        if branch.startswith("APLICA"):
            overrides_predichos.append(info)
        else:
            skips_predichos.append((branch, info))

    conn.close()

    # Reporte
    print("=" * 70)
    print("RESUMEN FIXTURE UPCOMING")
    print("=" * 70)
    for b in ["APLICA", "APLICA_CON_NULL", "SKIP_TOP3", "SKIP_CANSADOS",
              "SKIP_AMBOS", "NO_X", "NO_THRESH", "XG_V6_FAIL", "V12_FAIL"]:
        n = counts.get(b, 0)
        if n:
            print(f"  {b:<20s} {n:>4d}")

    print("\nPOR LIGA:")
    for liga, sub in counts_por_liga.items():
        print(f"  {liga}:")
        for b, n in sub.items():
            print(f"    {b:<20s} {n:>4d}")

    if overrides_predichos:
        print("\n" + "=" * 70)
        print(f"OVERRIDES PREDICHOS ({len(overrides_predichos)})")
        print("=" * 70)
        for o in overrides_predichos:
            null_marker = " [WITH NULLS]" if (o["pos_local"] is None or o["gap_l"] is None or o["gap_v"] is None) else ""
            print(f"  {o['fecha']} {o['pais']:<11s} {o['local']:<24s} vs {o['visita']:<24s} | "
                  f"P_v12(X)={o['px_v12']} pos_l={o['pos_local']} gap_l={o['gap_l']} gap_v={o['gap_v']} | "
                  f"cuota_X={o['cuota_x']}{null_marker}")

    if skips_predichos:
        print("\n" + "=" * 70)
        print(f"SKIPS PREDICHOS ({len(skips_predichos)})")
        print("=" * 70)
        for branch, o in skips_predichos:
            print(f"  [{branch:<14s}] {o['fecha']} {o['pais']:<11s} {o['local']:<24s} vs {o['visita']:<24s} | "
                  f"P_v12(X)={o['px_v12']} pos_l={o['pos_local']} gap_l={o['gap_l']} gap_v={o['gap_v']}")

    out = {
        "config": h4_thresh_map,
        "fecha_corrida": datetime.now().isoformat(),
        "n_partidos_evaluados": len(rows),
        "counts": dict(counts),
        "counts_por_liga": {k: dict(v) for k, v in counts_por_liga.items()},
        "overrides_predichos": overrides_predichos,
        "skips_predichos": [{"branch": b, **info} for b, info in skips_predichos],
    }
    with open("analisis/fixture_layer3_upcoming.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: analisis/fixture_layer3_upcoming.json")


if __name__ == "__main__":
    main()

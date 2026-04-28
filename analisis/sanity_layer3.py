"""
Sanity test Layer 3 V5.2 (paso 1 + 5 combinado).

Ejercita los helpers reales (_calcular_probs_v12_lr, _get_pos_local_forward,
_get_gap_dias_no_liga) sobre partidos in-sample 2026 ARG+ING+ITA+ALE para:
1. Verificar que el código path no rompe con datos reales (paso 1).
2. Clasificar cada partido por branch del decisor Layer 3 (paso 5):
   - APLICA  : override habria disparado
   - SKIP_TOP3 : local en TOP3 bloquea
   - SKIP_CANSADOS : ambos cansados (gap<=14d) bloquea
   - SKIP_AMBOS    : ambos filtros bloquean
   - NO_X    : argmax_v12 != 'X' (no candidato)
   - NO_THRESH : argmax='X' pero P_v12(X) < thresh
   - LOOKUP_FAIL : helper retorna None (riesgo silencioso)
3. Detectar cuantos overrides "pasarian" por LOOKUP_FAIL (NULL en pos o gap)
   vs. por filtro legitimo.

NO toca DB. Solo lectura.
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Path a raiz proyecto (motor usa imports tipo `from src.comun.config_sistema import ...`)
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.nucleo.motor_calculadora import (  # noqa: E402
    _calcular_probs_v12_lr,
    _get_pos_local_forward,
    _get_gap_dias_no_liga,
    _get_xg_v6_para_partido,
)
from src.comun.gestor_nombres import limpiar_texto  # noqa: E402

DB_PATH = "fondo_quant.db"
LIGAS_OBJETIVO = ["Argentina", "Italia", "Inglaterra", "Alemania"]


def normalize_equipo(s):
    """Aplica gestor_nombres.limpiar_texto, mismo path que motor real."""
    return limpiar_texto(s) if s else s


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    # Cargar config Layer 3
    h4_thresh_json = conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='h4_x_rescue_threshold' AND scope='global'"
    ).fetchone()[0]
    h4_thresh_map = json.loads(h4_thresh_json)
    print(f"Layer 3 config: {h4_thresh_map}\n")

    # Cargar Layer 2 arch_decision_per_liga
    arch_json = conn.execute(
        "SELECT valor_texto FROM config_motor_valores "
        "WHERE clave='arch_decision_per_liga' AND scope='global'"
    ).fetchone()
    arch_map = json.loads(arch_json[0]) if arch_json and arch_json[0] else {}
    print(f"Layer 2 config: {arch_map}\n")

    # Recolectar partidos in-sample 2026 ARG+ING+ITA+ALE
    placeholders = ",".join("?" * len(LIGAS_OBJETIVO))
    rows = conn.execute(
        f"""
        SELECT id_partido, fecha, pais, local, visita, xg_local, xg_visita,
               apuesta_1x2, estado, goles_l, goles_v
        FROM partidos_backtest
        WHERE pais IN ({placeholders})
          AND fecha >= '2026-01-01'
        ORDER BY fecha
        """,
        LIGAS_OBJETIVO,
    ).fetchall()
    print(f"Partidos analizados: {len(rows)} (ARG+ING+ITA+ALE in-sample 2026)\n")

    # Clasificar cada partido
    counts = Counter()
    counts_por_liga = defaultdict(Counter)
    ejemplos_por_branch = defaultdict(list)

    fail_path = Counter()  # helpers que retornan None

    for row in rows:
        idp, fecha, pais, local, visita, xg_l, xg_v, pick, estado, gl, gv = row
        thresh_liga = h4_thresh_map.get(pais)
        layer2_aplicado = arch_map.get(pais) == "V12"

        # Branch 0: liga no en JSON Layer 3 → no se evaluaria
        if not thresh_liga:
            counts["NO_LIGA"] += 1
            counts_por_liga[pais]["NO_LIGA"] += 1
            continue
        if layer2_aplicado:
            counts["LAYER2_BLOCKED"] += 1
            counts_por_liga[pais]["LAYER2_BLOCKED"] += 1
            continue

        # Calcular V12 probs (mismo path que motor)
        loc_norm = normalize_equipo(local)
        vis_norm = normalize_equipo(visita)
        xg6_l, xg6_v = _get_xg_v6_para_partido(loc_norm, vis_norm, conn)
        if xg6_l is None or xg6_v is None:
            counts["XG_V6_FAIL"] += 1
            counts_por_liga[pais]["XG_V6_FAIL"] += 1
            ejemplos_por_branch["XG_V6_FAIL"].append(
                f"{fecha} {pais}: {local} vs {visita} (id={idp})"
            )
            continue
        try:
            p1_v12, px_v12, p2_v12 = _calcular_probs_v12_lr(
                xg6_l, xg6_v, loc_norm, vis_norm, pais, fecha, conn
            )
        except Exception as e:
            counts["V12_FAIL"] += 1
            counts_por_liga[pais]["V12_FAIL"] += 1
            ejemplos_por_branch["V12_FAIL"].append(
                f"{fecha} {pais}: {local} vs {visita} ({e})"
            )
            continue

        p_max = max(p1_v12, px_v12, p2_v12)
        argmax_v12 = "X" if px_v12 == p_max else ("1" if p1_v12 >= p2_v12 else "2")

        # Branch: argmax != X
        if argmax_v12 != "X":
            counts["NO_X"] += 1
            counts_por_liga[pais]["NO_X"] += 1
            continue

        # Branch: argmax=X pero por debajo de thresh
        if px_v12 <= thresh_liga:
            counts["NO_THRESH"] += 1
            counts_por_liga[pais]["NO_THRESH"] += 1
            continue

        # Pasa thresh — evalua filtros
        pos_local = _get_pos_local_forward(pais, loc_norm, fecha, conn)
        gap_l = _get_gap_dias_no_liga(loc_norm, fecha, conn)
        gap_v = _get_gap_dias_no_liga(vis_norm, fecha, conn)

        if pos_local is None:
            fail_path["pos_local_NULL"] += 1
        if gap_l is None:
            fail_path["gap_l_NULL"] += 1
        if gap_v is None:
            fail_path["gap_v_NULL"] += 1

        local_es_top3 = pos_local is not None and pos_local <= 3
        ambos_cansados = (
            gap_l is not None and gap_l <= 14
            and gap_v is not None and gap_v <= 14
        )

        if local_es_top3 and ambos_cansados:
            branch = "SKIP_AMBOS"
        elif local_es_top3:
            branch = "SKIP_TOP3"
        elif ambos_cansados:
            branch = "SKIP_CANSADOS"
        else:
            branch = "APLICA"

        # Sub-clasificacion: APLICA con NULLs es riesgoso
        if branch == "APLICA" and (pos_local is None or gap_l is None or gap_v is None):
            branch = "APLICA_CON_NULL"

        counts[branch] += 1
        counts_por_liga[pais][branch] += 1
        ejemplos_por_branch[branch].append({
            "id": idp, "fecha": fecha, "pais": pais,
            "local": local, "visita": visita,
            "px_v12": round(px_v12, 3), "thresh": thresh_liga,
            "pos_local": pos_local, "gap_l": gap_l, "gap_v": gap_v,
            "pick_motor": pick, "estado": estado,
            "resultado": (gl, gv) if estado == "LIQUIDADO" else None,
        })

    conn.close()

    # Reporte
    print("=" * 70)
    print("RESUMEN POR BRANCH")
    print("=" * 70)
    branches_orden = ["APLICA", "APLICA_CON_NULL", "SKIP_TOP3", "SKIP_CANSADOS",
                      "SKIP_AMBOS", "NO_X", "NO_THRESH", "NO_LIGA",
                      "LAYER2_BLOCKED", "XG_V6_FAIL", "V12_FAIL"]
    total = sum(counts.values())
    for b in branches_orden:
        n = counts.get(b, 0)
        pct = 100.0 * n / total if total else 0
        print(f"  {b:<20s} {n:>5d}  ({pct:5.1f}%)")
    print(f"  {'TOTAL':<20s} {total:>5d}")

    print("\n" + "=" * 70)
    print("POR LIGA")
    print("=" * 70)
    for liga in LIGAS_OBJETIVO:
        sub = counts_por_liga[liga]
        if not sub:
            continue
        print(f"\n  {liga}:")
        for b in branches_orden:
            n = sub.get(b, 0)
            if n:
                print(f"    {b:<20s} {n:>4d}")

    print("\n" + "=" * 70)
    print("LOOKUP NULLs (riesgo silencioso)")
    print("=" * 70)
    for k, v in fail_path.items():
        print(f"  {k:<20s} {v:>4d}")

    # Ejemplos APLICA (override habria disparado)
    print("\n" + "=" * 70)
    print("EJEMPLOS APLICA (Layer 3 habria disparado override)")
    print("=" * 70)
    for ej in ejemplos_por_branch.get("APLICA", [])[:10]:
        print(f"  {ej['fecha']} {ej['pais']:<11s} {ej['local']:<25s} vs {ej['visita']:<25s} | "
              f"P_v12(X)={ej['px_v12']} pos_l={ej['pos_local']} "
              f"gap_l={ej['gap_l']} gap_v={ej['gap_v']} pick={ej['pick_motor']} "
              f"res={ej['resultado']}")

    print("\n" + "=" * 70)
    print("EJEMPLOS APLICA_CON_NULL (override SI dispararia, pero con datos parciales)")
    print("=" * 70)
    for ej in ejemplos_por_branch.get("APLICA_CON_NULL", [])[:10]:
        print(f"  {ej['fecha']} {ej['pais']:<11s} {ej['local']:<25s} vs {ej['visita']:<25s} | "
              f"P_v12(X)={ej['px_v12']} pos_l={ej['pos_local']} "
              f"gap_l={ej['gap_l']} gap_v={ej['gap_v']} pick={ej['pick_motor']} "
              f"res={ej['resultado']}")

    print("\n" + "=" * 70)
    print("EJEMPLOS SKIP_TOP3 (filtro local-TOP3 bloqueo override)")
    print("=" * 70)
    for ej in ejemplos_por_branch.get("SKIP_TOP3", [])[:5]:
        print(f"  {ej['fecha']} {ej['pais']:<11s} {ej['local']:<25s} vs {ej['visita']:<25s} | "
              f"P_v12(X)={ej['px_v12']} pos_l={ej['pos_local']}")

    print("\n" + "=" * 70)
    print("EJEMPLOS SKIP_CANSADOS (filtro ambos-cansados bloqueo override)")
    print("=" * 70)
    for ej in ejemplos_por_branch.get("SKIP_CANSADOS", [])[:5]:
        print(f"  {ej['fecha']} {ej['pais']:<11s} {ej['local']:<25s} vs {ej['visita']:<25s} | "
              f"P_v12(X)={ej['px_v12']} gap_l={ej['gap_l']}d gap_v={ej['gap_v']}d")

    # Persistir reporte
    out = {
        "config_layer3": h4_thresh_map,
        "config_layer2": arch_map,
        "n_partidos": total,
        "counts_global": dict(counts),
        "counts_por_liga": {k: dict(v) for k, v in counts_por_liga.items()},
        "lookup_nulls": dict(fail_path),
        "ejemplos": {
            k: v[:20] for k, v in ejemplos_por_branch.items() if k != "XG_V6_FAIL"
        },
    }
    Path("analisis/sanity_layer3.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/sanity_layer3.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: analisis/sanity_layer3.json")


if __name__ == "__main__":
    main()

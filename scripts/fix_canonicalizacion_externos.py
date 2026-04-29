"""
[adepor-a7p] Fix canonicalización equipos en partidos_historico_externo +
partidos_no_liga (filas viejas insertadas pre-F1 fix).

Estrategia conservadora: solo aplica UPDATE cuando gestor_nombres.son_equivalentes()
confirma que dos variantes son el mismo equipo via diccionario v5. Esto evita
falsos positivos como 'Independiente' vs 'Independiente Rivadavia' (distintos
clubes que comparten substring).

[REF: docs/papers/elo_calibracion.md Q1 — sparse network problem por equipos
duplicados; bead adepor-a7p].

Fix:
- Para cada cluster (contexto, [variantes...]):
  - Pivotal = display con mayor N
  - Para cada otro variant V:
    - if son_equivalentes(V, Pivotal, dict, liga=ctx) → UPDATE filas con V→Pivotal
- Re-popula _norm via limpiar_texto(Pivotal).

USO:
    py scripts/fix_canonicalizacion_externos.py            # dry-run
    py scripts/fix_canonicalizacion_externos.py --apply    # APLICA + snapshot
"""
from __future__ import annotations
import sqlite3
import sys
import json
import shutil
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
APPLY = "--apply" in sys.argv

sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import (  # noqa
    cargar_diccionario, limpiar_texto, obtener_nombre_estandar
)

SIM_TH = 0.80


def son_equivalentes_estricto(disp1, disp2, diccionario, contexto):
    """[Refinado adepor-a7p 2026-04-28] Solo confirma equivalencia si ambos
    nombres resuelven al MISMO nombre oficial via diccionario (no fuzzy).

    son_equivalentes() de gestor_nombres usa SequenceMatcher>0.85 como fallback,
    lo que produce falsos positivos como 'Winchester City' -> 'Manchester City',
    'Angers' -> 'Rangers'. Aquí solo se acepta match si ambos display
    pasan por obtener_nombre_estandar(modo_interactivo=False) y devuelven el
    MISMO oficial CONOCIDO en el diccionario (no el input mismo).
    """
    if not disp1 or not disp2 or disp1 == disp2:
        return disp1 == disp2

    of1 = obtener_nombre_estandar(disp1, liga=contexto, modo_interactivo=False)
    of2 = obtener_nombre_estandar(disp2, liga=contexto, modo_interactivo=False)

    # Si gestor_nombres no mapeó (devolvió el input crudo), NO es match seguro
    norm1 = limpiar_texto(disp1); norm2 = limpiar_texto(disp2)
    norm_of1 = limpiar_texto(of1); norm_of2 = limpiar_texto(of2)
    of1_known = norm_of1 != norm1
    of2_known = norm_of2 != norm2

    # Caso A: ambos resuelven al mismo oficial conocido → match
    if of1_known and of2_known and norm_of1 == norm_of2:
        return True
    # Caso B: uno resuelve al otro (alias directo)
    if of1_known and norm_of1 == norm2:
        return True
    if of2_known and norm_of2 == norm1:
        return True
    return False


def collect_pairs(conn):
    """Retorna list de (contexto, display, _norm, n_filas, tabla_origen)."""
    cur = conn.cursor()
    out = []
    # partidos_historico_externo
    for col_eq, col_norm in [("ht", "ht_norm"), ("at", "at_norm")]:
        rows = cur.execute(f"""
            SELECT liga AS ctx, {col_eq} AS disp, {col_norm} AS norm, COUNT(*) AS n
            FROM partidos_historico_externo
            WHERE {col_eq} IS NOT NULL AND {col_norm} IS NOT NULL
            GROUP BY liga, {col_eq}, {col_norm}
        """).fetchall()
        for ctx, disp, norm, n in rows:
            out.append((ctx, disp, norm, n, "phe", col_eq))

    # partidos_no_liga
    for col_eq, col_norm in [
        ("equipo_local", "equipo_local_norm"),
        ("equipo_visita", "equipo_visita_norm"),
    ]:
        rows = cur.execute(f"""
            SELECT competicion AS ctx, {col_eq} AS disp, {col_norm} AS norm, COUNT(*) AS n
            FROM partidos_no_liga
            WHERE {col_eq} IS NOT NULL AND {col_norm} IS NOT NULL
            GROUP BY competicion, {col_eq}, {col_norm}
        """).fetchall()
        for ctx, disp, norm, n in rows:
            out.append((ctx, disp, norm, n, "pnl", col_eq))
    return out


def detectar_clusters(pairs, diccionario):
    """Retorna list de fix operations: [(contexto, canon_display, variant_display)]."""
    # Agregar (ctx, norm) -> {display: n}
    by_ctx_norm = defaultdict(lambda: defaultdict(int))
    for ctx, disp, norm, n, _, _ in pairs:
        by_ctx_norm[(ctx, norm)][disp] += n
    # Display dominante por (ctx, norm)
    canon_disp_per_norm = {
        (ctx, norm): max(disps.items(), key=lambda x: x[1])[0]
        for (ctx, norm), disps in by_ctx_norm.items()
    }
    # Counts agregados por (ctx, norm)
    n_per_ctx_norm = {k: sum(v.values()) for k, v in by_ctx_norm.items()}

    # Por contexto, comparar pares de norms con SIM_TH
    by_ctx = defaultdict(list)
    for (ctx, norm), n in n_per_ctx_norm.items():
        by_ctx[ctx].append((norm, n))

    operations = []
    for ctx, norms_list in by_ctx.items():
        norms_sorted = sorted(norms_list, key=lambda x: -x[1])
        used = set()
        for i, (n1, c1) in enumerate(norms_sorted):
            if n1 in used:
                continue
            for n2, c2 in norms_sorted[i+1:]:
                if n2 in used or n1 == n2:
                    continue
                sim = SequenceMatcher(None, n1, n2).ratio()
                shorter = min(len(n1), len(n2))
                if sim < SIM_TH and not (shorter >= 5 and (n1 in n2 or n2 in n1)):
                    continue
                # Test con gestor_nombres
                disp_canon = canon_disp_per_norm[(ctx, n1)]
                disp_var = canon_disp_per_norm[(ctx, n2)]
                if son_equivalentes_estricto(disp_canon, disp_var, diccionario, ctx):
                    operations.append({
                        "contexto": ctx,
                        "canon_display": disp_canon,
                        "canon_norm": n1,
                        "canon_n": c1,
                        "variant_display": disp_var,
                        "variant_norm": n2,
                        "variant_n": c2,
                    })
                    used.add(n2)
    return operations


def aplicar_op(conn, op):
    """UPDATE filas con variant -> canon en ambas tablas."""
    cur = conn.cursor()
    ctx = op["contexto"]
    canon = op["canon_display"]
    var = op["variant_display"]
    canon_norm_new = limpiar_texto(canon)
    n_phe = n_pnl = 0
    # phe (ht/at)
    for col_eq, col_norm in [("ht", "ht_norm"), ("at", "at_norm")]:
        cur.execute(f"""
            UPDATE partidos_historico_externo
            SET {col_eq}=?, {col_norm}=?
            WHERE liga=? AND {col_eq}=?
        """, (canon, canon_norm_new, ctx, var))
        n_phe += cur.rowcount
    # pnl
    for col_eq, col_norm in [
        ("equipo_local", "equipo_local_norm"),
        ("equipo_visita", "equipo_visita_norm"),
    ]:
        cur.execute(f"""
            UPDATE partidos_no_liga
            SET {col_eq}=?, {col_norm}=?
            WHERE competicion=? AND {col_eq}=?
        """, (canon, canon_norm_new, ctx, var))
        n_pnl += cur.rowcount
    return n_phe, n_pnl


def main():
    snap = None
    if APPLY:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = f"snapshots/fondo_quant_{ts}_pre_a7p_canonicalizacion.db"
        Path(snap).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DB, snap)
        print(f"[SNAPSHOT] {snap}\n")

    conn = sqlite3.connect(DB); conn.text_factory = str
    diccionario = cargar_diccionario()

    print("STEP 1: Cargar pairs (ctx, display, norm, n)...")
    pairs = collect_pairs(conn)
    print(f"  Total pairs: {len(pairs)}")

    print("\nSTEP 2: Detectar clusters validados por gestor_nombres...")
    ops = detectar_clusters(pairs, diccionario)
    print(f"  Operations validas: {len(ops)}")

    if ops:
        print("\nMuestra (top 20 ops por variant_n):")
        for op in sorted(ops, key=lambda o: -o["variant_n"])[:20]:
            print(f"  [{op['contexto']:<22s}] '{op['variant_display']:<28s}' -> '{op['canon_display']:<28s}' "
                  f"(canon_n={op['canon_n']}, var_n={op['variant_n']})")

    out_path = "analisis/fix_canonicalizacion_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"apply": APPLY, "snapshot": snap, "operations": ops},
                   f, indent=2, ensure_ascii=False)
    print(f"\nPlan: {out_path}")

    if not APPLY:
        print("\nDRY-RUN. Para aplicar: --apply")
        return

    print("\nSTEP 3: Aplicar updates...")
    try:
        conn.execute("BEGIN")
        total_phe = total_pnl = 0
        for op in ops:
            n_phe, n_pnl = aplicar_op(conn, op)
            total_phe += n_phe
            total_pnl += n_pnl
        conn.commit()
        print(f"  Updates phe: {total_phe}, pnl: {total_pnl}")
    except Exception as e:
        conn.rollback()
        print(f"  [ROLLBACK] {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

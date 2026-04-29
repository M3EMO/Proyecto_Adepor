"""
[adepor-a7p] Diagnóstico variantes _norm en partidos_historico_externo +
partidos_no_liga + equipo_nivel_elo.

Detecta:
- Equipos con N_norm distinto pero alta similitud (PSG: 'parissaintgermain' vs 'parissg')
- Equipos con _norm distinto que gestor_nombres podría unificar via dict.

Output: docs/diagnostic_canonicalizacion.md con:
- Top clusters de variantes por (liga, similitud)
- Recomendación de UPDATE (canónica = mayor N + acento)
- Gap analysis: qué pares NO están en diccionario gestor_nombres v5.

NO modifica nada. Solo lectura.
"""
from __future__ import annotations
import sqlite3
import sys
import json
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))

from src.comun.gestor_nombres import (  # noqa
    cargar_diccionario, son_equivalentes, obtener_nombre_estandar
)


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # Cargar todos los equipos únicos por (liga|comp, _norm) con counts
    print("Cargando equipos historicos...")
    rows_phe = cur.execute("""
        SELECT liga AS contexto, ht_norm AS norm, ht AS display, COUNT(*) AS n
        FROM partidos_historico_externo
        WHERE ht_norm IS NOT NULL AND ht_norm != ''
        GROUP BY liga, ht_norm
        UNION ALL
        SELECT liga, at_norm, at, COUNT(*)
        FROM partidos_historico_externo
        WHERE at_norm IS NOT NULL AND at_norm != ''
        GROUP BY liga, at_norm
    """).fetchall()

    rows_pnl = cur.execute("""
        SELECT competicion AS contexto, equipo_local_norm AS norm,
               equipo_local AS display, COUNT(*) AS n
        FROM partidos_no_liga
        WHERE equipo_local_norm IS NOT NULL AND equipo_local_norm != ''
        GROUP BY competicion, equipo_local_norm
        UNION ALL
        SELECT competicion, equipo_visita_norm, equipo_visita, COUNT(*)
        FROM partidos_no_liga
        WHERE equipo_visita_norm IS NOT NULL AND equipo_visita_norm != ''
        GROUP BY competicion, equipo_visita_norm
    """).fetchall()

    # Agregar por (contexto, norm) sumando counts entre tablas + ida/vuelta
    agregado = defaultdict(int)
    display_canon = {}  # (contexto, norm) -> display más frecuente
    display_count = defaultdict(int)
    for ctx, norm, disp, n in list(rows_phe) + list(rows_pnl):
        key = (ctx, norm)
        agregado[key] += n
        display_count[(ctx, norm, disp)] += n

    # Determinar display dominante por (ctx, norm)
    for ctx, norm in agregado.keys():
        candidates = [(d, display_count[(ctx, norm, d)])
                       for (c, n, d) in display_count if c == ctx and n == norm]
        if candidates:
            display_canon[(ctx, norm)] = max(candidates, key=lambda x: x[1])[0]

    # Por contexto, detectar pares de norms con alta similitud (≥0.80)
    SIM_TH = 0.80
    contextos_norms = defaultdict(list)
    for (ctx, norm), n in agregado.items():
        contextos_norms[ctx].append((norm, n))

    print(f"Contextos: {len(contextos_norms)}")
    print(f"Total (contexto, norm) únicos: {sum(len(v) for v in contextos_norms.values())}")

    diccionario = cargar_diccionario()
    clusters_por_ctx = defaultdict(list)
    for ctx, norms_list in contextos_norms.items():
        # Ordenar por n desc
        norms_sorted = sorted(norms_list, key=lambda x: -x[1])
        used = set()
        for i, (n1, c1) in enumerate(norms_sorted):
            if n1 in used:
                continue
            cluster = [(n1, c1)]
            for n2, c2 in norms_sorted[i+1:]:
                if n2 in used:
                    continue
                if n1 == n2:
                    continue
                # Similaridad de strings
                sim = SequenceMatcher(None, n1, n2).ratio()
                # ¿Comparten substring largo?
                shorter = min(len(n1), len(n2))
                if sim >= SIM_TH or (shorter >= 5 and (n1 in n2 or n2 in n1)):
                    cluster.append((n2, c2))
                    used.add(n2)
            if len(cluster) > 1:
                clusters_por_ctx[ctx].append(cluster)

    # Reporte top clusters por contexto
    print(f"\n{'='*70}\nTOP CLUSTERS DETECTADOS (sim>={SIM_TH} o substring)\n{'='*70}")
    total_clusters = sum(len(v) for v in clusters_por_ctx.values())
    print(f"Clusters totales detectados: {total_clusters}\n")

    out_data = {"clusters_por_contexto": {}}
    for ctx in sorted(clusters_por_ctx.keys()):
        clusters = clusters_por_ctx[ctx]
        if not clusters:
            continue
        # Sortear clusters por sum(n) desc
        clusters.sort(key=lambda c: -sum(x[1] for x in c))
        print(f"\n--- {ctx} ({len(clusters)} clusters) ---")
        ctx_data = []
        for cluster in clusters[:8]:  # top 8 por contexto
            cluster.sort(key=lambda x: -x[1])
            canon_norm, canon_n = cluster[0]
            canon_disp = display_canon.get((ctx, canon_norm), canon_norm)
            variants_data = []
            for norm, n in cluster:
                disp = display_canon.get((ctx, norm), norm)
                # Test gestor_nombres equivalencia con canon_disp
                eq = son_equivalentes(disp, canon_disp, diccionario, liga=ctx)
                variants_data.append({
                    "norm": norm, "display": disp, "n": n,
                    "matches_canonical_via_gestor": eq,
                })
            print(f"  CANONICAL: '{canon_disp}' (norm={canon_norm}, n={canon_n})")
            for v in variants_data[1:]:
                mark = "OK" if v["matches_canonical_via_gestor"] else "GAP"
                print(f"    [{mark}] '{v['display']}' (norm={v['norm']}, n={v['n']})")
            ctx_data.append({
                "canonical": {"display": canon_disp, "norm": canon_norm, "n": canon_n},
                "variants": variants_data,
            })
        out_data["clusters_por_contexto"][ctx] = ctx_data

    with open("analisis/diagnostic_canonicalizacion_externos.json", "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/diagnostic_canonicalizacion_externos.json")
    conn.close()


if __name__ == "__main__":
    main()

"""
Diagnóstico bead adepor-z0e — variantes/duplicados de equipos cross-tabla.

Hallazgo redefinido (2026-04-28): NO es mojibake clásico (bytes corruptos).
Los bytes UTF-8 están bien codificados (`c3 b3` = `ó`). El bug es duplicación
por **inconsistencia de capitalización + presencia/ausencia de acento** entre
pipelines de scraping distintos.

Tablas inspeccionadas:
- historial_equipos_stats (input EMA stats avanzadas + filtro M.2 n_acum)
- posiciones_tabla_snapshot (helper Layer 3 _get_pos_local_forward)
- historial_equipos_v6_shadow (input V13 SHADOW)
- partidos_backtest (validación OOS)
- historial_equipos (legacy EMA xG)

Output: analisis/diagnostic_mojibake_equipos.json con clusters por liga +
filas afectadas por tabla.

NO modifica nada. Solo lectura.
"""
import sqlite3
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

DB_PATH = "fondo_quant.db"
OUT_PATH = "analisis/diagnostic_mojibake_equipos.json"


def normalizar(s: str) -> str:
    """Lower + sin acentos + sin parentesis + sin espacios extra. Forma canonica
    para clustering."""
    if not s:
        return ""
    # NFKD decompone acentos: 'á' -> 'a' + combining acute
    nfkd = unicodedata.normalize("NFKD", s)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def buscar_clusters_tabla(conn, tabla: str, col_liga: str, col_equipo: str,
                          extra_select: str = "", extra_group: str = ""):
    """Detecta clusters de variantes en una tabla.

    Retorna dict {liga: [{canonico, variantes: [{nombre, n_filas}], total_filas}]}.
    Solo retorna clusters con > 1 variante.
    """
    # Query con count por equipo
    query = f"""
        SELECT {col_liga} AS liga, {col_equipo} AS equipo, COUNT(*) AS n {extra_select}
        FROM {tabla}
        WHERE {col_liga} IS NOT NULL AND {col_equipo} IS NOT NULL
        GROUP BY {col_liga}, {col_equipo} {extra_group}
    """
    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        return {"error": str(e)}

    # Cluster por (liga, normalize(equipo))
    clusters_raw = defaultdict(list)
    for liga, equipo, n in rows:
        if liga is None or equipo is None:
            continue
        clusters_raw[(liga, normalizar(equipo))].append({"nombre": equipo, "n_filas": n})

    # Filtrar solo > 1 variante + estructurar por liga
    out = defaultdict(list)
    for (liga, _), variantes in clusters_raw.items():
        if len(variantes) > 1:
            variantes_sorted = sorted(variantes, key=lambda x: -x["n_filas"])
            canonico = variantes_sorted[0]["nombre"]  # mayor N = canonico tentativo
            out[liga].append({
                "canonico_tentativo": canonico,
                "n_variantes": len(variantes),
                "variantes": variantes_sorted,
                "total_filas": sum(v["n_filas"] for v in variantes),
            })
    # Ordenar clusters por total_filas desc dentro de cada liga
    for liga in out:
        out[liga].sort(key=lambda c: -c["total_filas"])
    return dict(out)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str  # asegurar str (no bytes)

    resultado = {
        "metodo": "fuzzy clustering por (liga, NFKD-lower-sin_acentos)",
        "tablas": {},
    }

    tablas_config = [
        # (tabla, col_liga, col_equipo, alias_opcional)
        ("historial_equipos_stats", "liga", "equipo", None),
        ("posiciones_tabla_snapshot", "liga", "equipo", None),
        ("historial_equipos_v6_shadow", "liga", "equipo_real", None),
        ("historial_equipos", "liga", "equipo_real", None),
        ("partidos_backtest", "pais", "local", "partidos_backtest [local]"),
        ("partidos_backtest", "pais", "visita", "partidos_backtest [visita]"),
    ]

    for tabla, col_liga, col_equipo, alias in tablas_config:
        clusters = buscar_clusters_tabla(conn, tabla, col_liga, col_equipo)
        tabla_key = alias if alias else tabla

        if "error" in clusters:
            resultado["tablas"][tabla_key] = {"error": clusters["error"]}
            continue

        n_clusters = sum(len(c) for c in clusters.values())
        n_filas_afectadas = sum(
            c["total_filas"] for ligas in clusters.values() for c in ligas
        )
        resultado["tablas"][tabla_key] = {
            "n_clusters_con_duplicados": n_clusters,
            "n_filas_afectadas_total": n_filas_afectadas,
            "clusters_por_liga": clusters,
        }

    conn.close()

    # Guardar output
    Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    # Resumen consola
    print(f"Output: {OUT_PATH}\n")
    print("=" * 70)
    print("RESUMEN POR TABLA")
    print("=" * 70)
    for tabla, info in resultado["tablas"].items():
        if "error" in info:
            print(f"\n[{tabla}] ERROR: {info['error']}")
            continue
        print(f"\n[{tabla}]")
        print(f"  Clusters con duplicados: {info['n_clusters_con_duplicados']}")
        print(f"  Filas afectadas total:   {info['n_filas_afectadas_total']}")
        for liga, clusters in info["clusters_por_liga"].items():
            if not clusters:
                continue
            print(f"  -- {liga}: {len(clusters)} clusters")
            for c in clusters[:5]:  # top 5 por liga
                vars_str = " | ".join(
                    f"'{v['nombre']}' (N={v['n_filas']})" for v in c["variantes"][:3]
                )
                print(f"    [{c['n_variantes']}var, total={c['total_filas']}] {vars_str}")


if __name__ == "__main__":
    main()

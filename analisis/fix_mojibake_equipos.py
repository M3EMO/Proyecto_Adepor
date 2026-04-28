"""
Fix bead adepor-z0e — fusiona variantes de equipos a forma canónica GLOBAL.

Regla decidida (Opción B-corregida): "ACENTOS SIEMPRE CANONICO + MAYOR UPPERCASE EN ASCII".
Para cada cluster (liga, normalize(equipo)) con variantes cross-tabla:
- Si hay >=1 variante con caracteres no-ASCII (acentos): canónica = la variante con
  acento que tenga mayor N agregado.
- Si todas las variantes son ASCII: canónica = la variante con mayor cantidad de
  caracteres uppercase (favorece sufijos como 'FK', 'BK', 'MG' bien capitalizados);
  desempate por mayor N agregado.

Tablas con equipo en PK (posiciones_tabla_snapshot, historial_equipos_stats):
- Si fila minoritaria tiene mismo PK que canónica existente → DELETE minoritaria
  (canónica gana — datos previos confiables).
- Si no hay conflicto → UPDATE renombra a canónica.

Tablas sin equipo en PK (partidos_backtest):
- UPDATE directo (PK = id_partido, equipo no es PK).

USO:
    py analisis/fix_mojibake_equipos.py            # dry-run (default)
    py analisis/fix_mojibake_equipos.py --apply    # APLICA cambios + snapshot DB

NO toca historial_equipos_v6_shadow ni historial_equipos (0 duplicados).
"""
import sqlite3
import json
import sys
import shutil
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

DB_PATH = "fondo_quant.db"
PLAN_OUT = "analisis/fix_mojibake_plan.json"
APPLY = "--apply" in sys.argv


def normalizar(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def tiene_acento(s: str) -> bool:
    return any(ord(c) > 127 for c in s)


def construir_clusters_global(conn, tablas_inspeccion):
    """Para cada (liga, normalize(equipo)), suma counts cross-tabla.

    Retorna dict {(liga, norm): {"liga", "canonico", "variantes": [{nombre, n_total}]}}.
    Solo retorna clusters con > 1 variante.
    """
    variantes_globales = defaultdict(lambda: defaultdict(int))
    for tabla, col_liga, col_equipo in tablas_inspeccion:
        rows = conn.execute(
            f"SELECT {col_liga}, {col_equipo}, COUNT(*) FROM {tabla} "
            f"WHERE {col_liga} IS NOT NULL AND {col_equipo} IS NOT NULL "
            f"GROUP BY {col_liga}, {col_equipo}"
        ).fetchall()
        for liga, equipo, n in rows:
            key = (liga, normalizar(equipo))
            variantes_globales[key][equipo] += n

    out = {}
    for key, variantes_dict in variantes_globales.items():
        if len(variantes_dict) <= 1:
            continue
        variantes = [{"nombre": k, "n_total": v} for k, v in variantes_dict.items()]
        con_acento = [v for v in variantes if tiene_acento(v["nombre"])]
        if con_acento:
            canonico = max(con_acento, key=lambda v: v["n_total"])["nombre"]
            regla = "acento_mayor_N"
        else:
            # B-corregida: en ASCII puro, prioriza mayor count uppercase (FK, BK, MG bien
            # capitalizados); desempate por N total
            canonico = max(
                variantes,
                key=lambda v: (sum(1 for c in v["nombre"] if c.isupper()), v["n_total"]),
            )["nombre"]
            regla = "ascii_uppercase_N"
        out[key] = {
            "liga": key[0],
            "canonico": canonico,
            "regla_aplicada": regla,
            "variantes": sorted(variantes, key=lambda v: -v["n_total"]),
        }
    return out


def plan_tabla_pk(conn, tabla, col_liga, col_equipo, pk_extra, clusters_globales):
    operaciones = []
    where_extra = " AND ".join(f"{c}=?" for c in pk_extra)
    select_pk = ", ".join(pk_extra)
    for (liga, _), cluster in clusters_globales.items():
        canonico = cluster["canonico"]
        # Variantes que realmente existen en esta tabla y son != canonico
        nombres_variantes = [v["nombre"] for v in cluster["variantes"] if v["nombre"] != canonico]
        for minoritario in nombres_variantes:
            min_rows = conn.execute(
                f"SELECT {select_pk} FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=?",
                (liga, minoritario),
            ).fetchall()
            if not min_rows:
                continue
            n_conflict = 0
            n_update = 0
            for pk_vals in min_rows:
                exists = conn.execute(
                    f"SELECT 1 FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=? AND {where_extra}",
                    (liga, canonico, *pk_vals),
                ).fetchone()
                if exists:
                    n_conflict += 1
                else:
                    n_update += 1
            operaciones.append({
                "liga": liga,
                "canonico": canonico,
                "minoritario": minoritario,
                "n_filas_min": len(min_rows),
                "n_delete_conflict": n_conflict,
                "n_update_ok": n_update,
            })
    return operaciones


def plan_tabla_simple(conn, tabla, col_liga, col_equipo, clusters_globales):
    operaciones = []
    for (liga, _), cluster in clusters_globales.items():
        canonico = cluster["canonico"]
        nombres_variantes = [v["nombre"] for v in cluster["variantes"] if v["nombre"] != canonico]
        for minoritario in nombres_variantes:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=?",
                (liga, minoritario),
            ).fetchone()[0]
            if n > 0:
                operaciones.append({
                    "liga": liga,
                    "canonico": canonico,
                    "minoritario": minoritario,
                    "n_filas_min": n,
                    "n_delete_conflict": 0,
                    "n_update_ok": n,
                })
    return operaciones


def aplicar_pk(conn, tabla, col_liga, col_equipo, pk_extra, ops):
    n_upd, n_del = 0, 0
    where_extra = " AND ".join(f"{c}=?" for c in pk_extra)
    select_pk = ", ".join(pk_extra)
    for op in ops:
        liga, canonico, minoritario = op["liga"], op["canonico"], op["minoritario"]
        min_rows = conn.execute(
            f"SELECT {select_pk} FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=?",
            (liga, minoritario),
        ).fetchall()
        for pk_vals in min_rows:
            exists = conn.execute(
                f"SELECT 1 FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=? AND {where_extra}",
                (liga, canonico, *pk_vals),
            ).fetchone()
            if exists:
                conn.execute(
                    f"DELETE FROM {tabla} WHERE {col_liga}=? AND {col_equipo}=? AND {where_extra}",
                    (liga, minoritario, *pk_vals),
                )
                n_del += 1
            else:
                conn.execute(
                    f"UPDATE {tabla} SET {col_equipo}=? "
                    f"WHERE {col_liga}=? AND {col_equipo}=? AND {where_extra}",
                    (canonico, liga, minoritario, *pk_vals),
                )
                n_upd += 1
    return n_upd, n_del


def aplicar_simple(conn, tabla, col_liga, col_equipo, ops):
    n = 0
    for op in ops:
        r = conn.execute(
            f"UPDATE {tabla} SET {col_equipo}=? WHERE {col_liga}=? AND {col_equipo}=?",
            (op["canonico"], op["liga"], op["minoritario"]),
        )
        n += r.rowcount
    return n


def main():
    snap_path = None
    if APPLY:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap_path = f"snapshots/fondo_quant_{ts}_pre_z0e_fix.db"
        Path(snap_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DB_PATH, snap_path)
        print(f"[SNAPSHOT] {snap_path}\n")

    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = str

    # Tablas a inspeccionar (incluyendo backtest local + visita por separado)
    tablas_inspeccion = [
        ("posiciones_tabla_snapshot", "liga", "equipo"),
        ("historial_equipos_stats", "liga", "equipo"),
        ("partidos_backtest", "pais", "local"),
        ("partidos_backtest", "pais", "visita"),
    ]
    clusters_globales = construir_clusters_global(conn, tablas_inspeccion)

    print("=" * 70)
    print(f"CLUSTERS GLOBALES (regla Opcion B: acento siempre canonico)")
    print("=" * 70)
    for (liga, _), cl in sorted(clusters_globales.items()):
        marker = "[ACC]" if tiene_acento(cl["canonico"]) else "[asc]"
        print(f"\n{marker} {liga} canonico='{cl['canonico']}' ({cl['regla_aplicada']})")
        for v in cl["variantes"]:
            mark = " <-- canonico" if v["nombre"] == cl["canonico"] else ""
            print(f"      '{v['nombre']:<45s}' N_total={v['n_total']}{mark}")

    # Plans por tabla
    plans = {}
    config_pk = [
        ("posiciones_tabla_snapshot", "liga", "equipo", ["temp", "formato", "fecha_snapshot"]),
        ("historial_equipos_stats", "liga", "equipo", ["fecha"]),
    ]
    config_simple = [
        ("partidos_backtest", "pais", "local"),
        ("partidos_backtest", "pais", "visita"),
    ]

    todas_pk = []
    todas_simple = []
    for tabla, cl, ce, pk in config_pk:
        ops = plan_tabla_pk(conn, tabla, cl, ce, pk, clusters_globales)
        plans[tabla] = ops
        todas_pk.append((tabla, cl, ce, pk, ops))
    for tabla, cl, ce in config_simple:
        ops = plan_tabla_simple(conn, tabla, cl, ce, clusters_globales)
        plans[f"{tabla} [{ce}]"] = ops
        todas_simple.append((tabla, cl, ce, ops))

    print("\n" + "=" * 70)
    print(f"PLAN POR TABLA ({'APPLY' if APPLY else 'DRY-RUN'})")
    print("=" * 70)
    for nombre_tabla, ops in plans.items():
        if not ops:
            print(f"\n[{nombre_tabla}] sin cambios")
            continue
        total_upd = sum(o["n_update_ok"] for o in ops)
        total_del = sum(o["n_delete_conflict"] for o in ops)
        print(f"\n[{nombre_tabla}] updates={total_upd}, deletes={total_del}, ops={len(ops)}")
        for op in ops:
            print(f"  {op['liga']:<11s} '{op['minoritario']:<42s}' "
                  f"-> '{op['canonico']:<42s}' "
                  f"upd={op['n_update_ok']}, del={op['n_delete_conflict']}")

    # Persistir plan
    plan_total = {
        "apply": APPLY,
        "snapshot": snap_path,
        "regla": "Opcion B: acento siempre canonico",
        "clusters_globales": [
            {"liga": cl["liga"], "canonico": cl["canonico"],
             "regla_aplicada": cl["regla_aplicada"], "variantes": cl["variantes"]}
            for cl in clusters_globales.values()
        ],
        "plans": plans,
    }
    Path(PLAN_OUT).parent.mkdir(parents=True, exist_ok=True)
    with open(PLAN_OUT, "w", encoding="utf-8") as f:
        json.dump(plan_total, f, indent=2, ensure_ascii=False)
    print(f"\nPlan persistido: {PLAN_OUT}")

    if not APPLY:
        conn.close()
        print("\nDRY-RUN. Para aplicar: py analisis/fix_mojibake_equipos.py --apply")
        return

    # APPLY transaccional
    try:
        conn.execute("BEGIN")
        total_u, total_d = 0, 0
        for tabla, cl, ce, pk, ops in todas_pk:
            u, d = aplicar_pk(conn, tabla, cl, ce, pk, ops)
            print(f"[APPLY {tabla}] updates={u}, deletes={d}")
            total_u += u
            total_d += d
        for tabla, cl, ce, ops in todas_simple:
            n = aplicar_simple(conn, tabla, cl, ce, ops)
            print(f"[APPLY {tabla}.{ce}] updates={n}")
            total_u += n
        conn.commit()
        print(f"\n[OK] Total: updates={total_u}, deletes={total_d}")
        # Verificacion post
        print("\nVERIFICACION POST:")
        clusters_resid = construir_clusters_global(conn, tablas_inspeccion)
        if not clusters_resid:
            print("  [OK] 0 clusters residuales con duplicados.")
        else:
            print(f"  [WARN] {len(clusters_resid)} clusters residuales:")
            for (liga, _), cl in clusters_resid.items():
                print(f"    {liga}: canonico='{cl['canonico']}' variantes={[v['nombre'] for v in cl['variantes']]}")
    except Exception as e:
        conn.rollback()
        print(f"\n[ROLLBACK] {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

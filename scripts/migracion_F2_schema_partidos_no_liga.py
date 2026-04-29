"""
[F2 — adepor-5y0.11 enrichment schema] Migración partidos_no_liga.

Agrega columnas para soportar motor copa fundamentado en literatura:
- liga_local, liga_visita: cuantificar nivel cross-liga (Q3 papers)
- competicion_formato: discriminar single vs two-leg knockouts (Q2 papers)
- id_serie_eliminatoria, numero_partido_serie, agregado_*_pre: tracking 2-legs

[REF: docs/papers/copa_modelado.md Q1+Q2+Q3]

Backfill:
- liga_local/liga_visita via gestor_nombres.obtener_liga_home()
- competicion_formato via heurística por competicion + fase
- id_serie_eliminatoria + numero_partido_serie: detección 2-legs por (par_equipos,
  competicion, fase) cuando hay 2 partidos en distintas fechas
- agregado_*_pre: solo poblado si numero_partido_serie=2 (ronda vuelta)

Snapshot pre-cambio obligatorio antes de correr.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

sys.path.insert(0, str(ROOT))
from src.comun.gestor_nombres import obtener_liga_home  # noqa: E402

# Heurística competicion_formato según competicion + fase
COMPETICION_FORMATO_MAP = {
    # Single-leg knockout (copas nacionales)
    'Copa Argentina': 'copa_knockout_single',
    'Copa do Brasil': 'copa_knockout_single',
    'FA Cup': 'copa_knockout_single',
    'EFL Cup': 'copa_knockout_single',
    'Coppa Italia': 'copa_knockout_single',
    'DFB-Pokal': 'copa_knockout_single',
    'Copa del Rey': 'copa_knockout_single',
    'Coupe de France': 'copa_knockout_single',
    # Two-leg knockout en fase eliminatoria (con fase grupos previa)
    'Libertadores': 'copa_knockout_two_leg',
    'Sudamericana': 'copa_knockout_two_leg',
    'Champions': 'copa_knockout_two_leg',
    'Europa': 'copa_knockout_two_leg',
    'Conference': 'copa_knockout_two_leg',
}

# Fases que indican fase de grupos (override formato)
FASES_GRUPO = ['grupo', 'group', 'fase de grupos', 'group stage']
# Fases que indican final (single-leg)
FASES_FINAL = ['final', 'final única', 'finale']


def determinar_formato(competicion, fase):
    base = COMPETICION_FORMATO_MAP.get(competicion, 'copa_otro')
    if not fase:
        return base
    fase_lower = fase.lower()
    if any(w in fase_lower for w in FASES_GRUPO):
        return 'copa_grupo'
    # Final UCL/UEL/Libertadores son single-leg en formato actual
    if base == 'copa_knockout_two_leg' and any(w in fase_lower for w in FASES_FINAL):
        return 'copa_knockout_single'
    return base


def main():
    if not DB.exists():
        print(f"DB no existe: {DB}")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    conn.text_factory = str
    cur = conn.cursor()

    print("=== STEP 1: ALTER TABLE add columns ===")
    new_cols = [
        ('liga_local', 'TEXT'),
        ('liga_visita', 'TEXT'),
        ('competicion_formato', 'TEXT'),
        ('id_serie_eliminatoria', 'TEXT'),
        ('numero_partido_serie', 'INTEGER'),
        ('agregado_local_pre', 'INTEGER'),
        ('agregado_visita_pre', 'INTEGER'),
    ]
    for col, tipo in new_cols:
        try:
            cur.execute(f"ALTER TABLE partidos_no_liga ADD COLUMN {col} {tipo}")
            print(f"  ADDED {col} {tipo}")
        except sqlite3.OperationalError as e:
            print(f"  SKIP {col}: {e}")

    print("\n=== STEP 2: Backfill liga_local + liga_visita + competicion_formato ===")
    rows = cur.execute("""
        SELECT rowid, equipo_local, equipo_visita, competicion, fase
        FROM partidos_no_liga
    """).fetchall()
    n_total = len(rows)
    print(f"  Total filas a procesar: {n_total}")
    n_liga_l_ok = n_liga_v_ok = 0
    for rid, eq_l, eq_v, comp, fase in rows:
        liga_l = obtener_liga_home(eq_l, contexto_liga=comp) if eq_l else None
        liga_v = obtener_liga_home(eq_v, contexto_liga=comp) if eq_v else None
        formato = determinar_formato(comp, fase)
        cur.execute("""
            UPDATE partidos_no_liga
            SET liga_local = ?, liga_visita = ?, competicion_formato = ?
            WHERE rowid = ?
        """, (liga_l, liga_v, formato, rid))
        if liga_l: n_liga_l_ok += 1
        if liga_v: n_liga_v_ok += 1
    print(f"  liga_local resuelta: {n_liga_l_ok}/{n_total}")
    print(f"  liga_visita resuelta: {n_liga_v_ok}/{n_total}")

    print("\n=== STEP 3: Backfill id_serie_eliminatoria + numero_partido_serie ===")
    # Detectar pares ida/vuelta: mismas (equipo_local, equipo_visita, competicion, fase) + (visita,local,...) en fechas distintas
    rows = cur.execute("""
        SELECT rowid, fecha, equipo_local, equipo_visita, competicion, fase, competicion_formato,
               equipo_local_norm, equipo_visita_norm, goles_l, goles_v
        FROM partidos_no_liga
        WHERE competicion_formato = 'copa_knockout_two_leg'
          AND fase IS NOT NULL
        ORDER BY competicion, fase, fecha
    """).fetchall()
    # Group by (competicion, fase, frozenset(par_equipos_norm))
    groups = defaultdict(list)
    for r in rows:
        rid, fecha, eq_l, eq_v, comp, fase, fmt, eq_l_n, eq_v_n, gl, gv = r
        if not eq_l_n or not eq_v_n:
            continue
        key = (comp, fase, frozenset([eq_l_n, eq_v_n]))
        groups[key].append((rid, fecha, eq_l_n, eq_v_n, gl, gv))

    n_series = 0
    for key, partidos in groups.items():
        if len(partidos) != 2:
            continue
        # Ordenar por fecha
        partidos.sort(key=lambda x: x[1])
        comp, fase, _ = key
        # Generar id_serie estable
        id_serie = f"{comp}_{fase}_{'_'.join(sorted(key[2]))}"[:80]
        # Asignar numero_partido_serie
        for n, (rid, fecha, eq_l_n, eq_v_n, gl, gv) in enumerate(partidos, 1):
            cur.execute("""
                UPDATE partidos_no_liga
                SET id_serie_eliminatoria = ?, numero_partido_serie = ?
                WHERE rowid = ?
            """, (id_serie, n, rid))
        n_series += 1

        # Si vuelta, calcular agregados pre-partido
        ida = partidos[0]
        vuelta = partidos[1]
        rid_v, _, eq_l_n_v, eq_v_n_v, _, _ = vuelta
        rid_i, _, eq_l_n_i, eq_v_n_i, gl_i, gv_i = ida
        if gl_i is not None and gv_i is not None:
            # Agregado pre-partido para vuelta = goles ida (el equipo local de vuelta es visita en ida)
            if eq_l_n_v == eq_v_n_i:  # local de vuelta = visita de ida
                agg_local_pre = gv_i
                agg_visita_pre = gl_i
            else:
                agg_local_pre = gl_i
                agg_visita_pre = gv_i
            cur.execute("""
                UPDATE partidos_no_liga
                SET agregado_local_pre = ?, agregado_visita_pre = ?
                WHERE rowid = ?
            """, (agg_local_pre, agg_visita_pre, rid_v))
    print(f"  Series 2-legs detectadas: {n_series}")

    print("\n=== STEP 4: CREATE INDEX ===")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pnl_liga_local_fecha
        ON partidos_no_liga(liga_local, fecha)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pnl_liga_visita_fecha
        ON partidos_no_liga(liga_visita, fecha)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_pnl_serie
        ON partidos_no_liga(id_serie_eliminatoria, numero_partido_serie)
    """)
    print("  3 indices creados")

    conn.commit()

    print("\n=== STEP 5: Verification ===")
    distrib = cur.execute("""
        SELECT competicion_formato, COUNT(*)
        FROM partidos_no_liga
        GROUP BY competicion_formato
        ORDER BY COUNT(*) DESC
    """).fetchall()
    for fmt, n in distrib:
        print(f"  {fmt or '(NULL)'}: {n}")

    n_series = cur.execute("""
        SELECT COUNT(DISTINCT id_serie_eliminatoria) FROM partidos_no_liga
        WHERE id_serie_eliminatoria IS NOT NULL
    """).fetchone()[0]
    print(f"\n  Series 2-legs: {n_series}")

    n_agg = cur.execute("""
        SELECT COUNT(*) FROM partidos_no_liga
        WHERE agregado_local_pre IS NOT NULL
    """).fetchone()[0]
    print(f"  Vueltas con agregado pre-poblado: {n_agg}")

    cross_liga = cur.execute("""
        SELECT COUNT(*) FROM partidos_no_liga
        WHERE liga_local IS NOT NULL AND liga_visita IS NOT NULL
          AND liga_local != liga_visita
    """).fetchone()[0]
    print(f"  Partidos cross-liga (liga_local != liga_visita): {cross_liga}")

    conn.close()
    print("\nMigracion completada.")


if __name__ == "__main__":
    main()

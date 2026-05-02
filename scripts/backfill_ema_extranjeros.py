"""
[adepor — Opción A] Backfill EMA V6 SHADOW para equipos extranjeros usando
goles_l/goles_v de partidos_no_liga como proxy de xG.

JUSTIFICACIÓN: equipos de países NO en LIGAS_ESPN (Paraguay, Holanda, Bélgica,
Portugal, etc.) que aparecen SOLO en copas internacionales no tienen EMA.
Sin EMA → _get_xg_v6_para_partido retorna (None,None) → Layer 3 + V14 NO se
ejecutan en esos partidos → predicción genérica usando default 1.4.

ESTRATEGIA:
- Para cada equipo_norm extranjero (no en historial_equipos_v6_shadow), iterar
  cronológicamente sus partidos en partidos_no_liga.
- EMA goles proxy:
    ema_favor_home  = EMA(goles_l) sobre partidos donde fue local
    ema_contra_home = EMA(goles_v) sobre idem
    ema_favor_away  = EMA(goles_v) sobre partidos donde fue visita
    ema_contra_away = EMA(goles_l) sobre idem
- alfa = 0.15 (default global del manifesto)
- Persistir en historial_equipos_v6_shadow con liga='copa_internacional'.

LIMITACIÓN OPCIÓN A: usa goles directos como proxy xG. Ruido alto vs xG real
(no penaliza chances no convertidas, no premia tiros peligrosos).
Opción B (backfill via ESPN summary stats + xG OLS) en sub-bead siguiente.

USO:
    py scripts/backfill_ema_extranjeros.py            # dry-run
    py scripts/backfill_ema_extranjeros.py --apply    # SNAPSHOT + INSERT
"""
from __future__ import annotations
import sqlite3
import sys
import shutil
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
APPLY = "--apply" in sys.argv

ALFA = 0.15  # estandar Adepor global (manifesto config_motor_valores)
N_MIN_PARTIDOS = 5  # mínimo para crear EMA confiable


def main():
    snap = None
    if APPLY:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = f"snapshots/fondo_quant_{ts}_pre_ema_extranjeros.db"
        Path(snap).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DB, snap)
        print(f"[SNAPSHOT] {snap}\n")

    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    # Equipos en v6_shadow ya existentes
    existentes = {r[0] for r in cur.execute(
        "SELECT equipo_norm FROM historial_equipos_v6_shadow"
    ).fetchall()}
    print(f"Equipos ya en v6_shadow: {len(existentes)}")

    # Identificar equipos extranjeros (con partidos liquidados pero sin EMA)
    cur.execute("""
        WITH eq_copas AS (
            SELECT DISTINCT equipo_local_norm AS eq_norm, equipo_local AS display
            FROM partidos_no_liga
            WHERE goles_l IS NOT NULL AND equipo_local_norm IS NOT NULL
            UNION
            SELECT DISTINCT equipo_visita_norm, equipo_visita
            FROM partidos_no_liga
            WHERE goles_l IS NOT NULL AND equipo_visita_norm IS NOT NULL
        )
        SELECT eq_norm, display,
               (SELECT COUNT(*) FROM partidos_no_liga p
                WHERE (p.equipo_local_norm=eq_norm OR p.equipo_visita_norm=eq_norm)
                  AND p.goles_l IS NOT NULL) AS n_partidos
        FROM eq_copas
        WHERE n_partidos >= ?
        ORDER BY n_partidos DESC
    """, (N_MIN_PARTIDOS,))

    candidatos = []
    for eq_norm, display, n in cur.fetchall():
        if eq_norm in existentes:
            continue  # Skip los que ya tienen EMA (por su liga doméstica)
        # Display canon: el más frecuente entre las variantes con mismo norm
        candidatos.append((eq_norm, display, n))

    # Dedup por norm (algunos tienen varias display variants — mantener el más frecuente)
    seen = {}
    for eq_norm, display, n in candidatos:
        if eq_norm not in seen or seen[eq_norm][1] < n:
            seen[eq_norm] = (display, n)
    candidatos = [(k, v[0], v[1]) for k, v in seen.items()]
    candidatos.sort(key=lambda x: -x[2])
    print(f"Equipos extranjeros candidatos a backfill: {len(candidatos)}")
    print(f"Total partidos cubribles: {sum(c[2] for c in candidatos)}")

    print(f"\nTop 10:")
    for eq_norm, display, n in candidatos[:10]:
        try: print(f"  {display:<35s} norm={eq_norm:<28s} N={n}")
        except UnicodeEncodeError: print(f"  ?? norm={eq_norm} N={n}")

    if not APPLY:
        print(f"\nDRY-RUN. Para aplicar: --apply")
        return

    # APPLY: para cada candidato, calcular EMA y persistir
    n_inserts = 0
    n_skipped = 0
    ts_now = time.strftime("%Y-%m-%dT%H:%M:%S")

    for eq_norm, display, n_total in candidatos:
        # Recolectar partidos cronológicos donde participó
        partidos = cur.execute("""
            SELECT fecha, equipo_local_norm, equipo_visita_norm, goles_l, goles_v,
                   equipo_local, equipo_visita
            FROM partidos_no_liga
            WHERE (equipo_local_norm=? OR equipo_visita_norm=?)
              AND goles_l IS NOT NULL
            ORDER BY fecha
        """, (eq_norm, eq_norm)).fetchall()

        if len(partidos) < N_MIN_PARTIDOS:
            n_skipped += 1
            continue

        # EMA recursiva
        ema_favor_home = ema_contra_home = None
        ema_favor_away = ema_contra_away = None
        n_home = n_away = 0
        ultimo_fecha = None

        for fecha, eq_l_n, eq_v_n, gl, gv, eq_l, eq_v in partidos:
            if eq_l_n == eq_norm:
                # Es local
                if ema_favor_home is None:
                    ema_favor_home = float(gl); ema_contra_home = float(gv)
                else:
                    ema_favor_home = ALFA * gl + (1-ALFA) * ema_favor_home
                    ema_contra_home = ALFA * gv + (1-ALFA) * ema_contra_home
                n_home += 1
            elif eq_v_n == eq_norm:
                # Es visita: gv = goles del equipo, gl = goles rival
                if ema_favor_away is None:
                    ema_favor_away = float(gv); ema_contra_away = float(gl)
                else:
                    ema_favor_away = ALFA * gv + (1-ALFA) * ema_favor_away
                    ema_contra_away = ALFA * gl + (1-ALFA) * ema_contra_away
                n_away += 1
            ultimo_fecha = fecha

        # Defaults si no hay datos en algún side
        if ema_favor_home is None: ema_favor_home = 1.4
        if ema_contra_home is None: ema_contra_home = 1.4
        if ema_favor_away is None: ema_favor_away = 1.0  # menor en visita
        if ema_contra_away is None: ema_contra_away = 1.6  # mayor en visita
        # Clip floor 0.10 (mismo que motor)
        ema_favor_home = max(0.10, ema_favor_home)
        ema_contra_home = max(0.10, ema_contra_home)
        ema_favor_away = max(0.10, ema_favor_away)
        ema_contra_away = max(0.10, ema_contra_away)

        try:
            cur.execute("""
                INSERT OR REPLACE INTO historial_equipos_v6_shadow
                (equipo_norm, equipo_real, liga,
                 ema_xg_v6_favor_home, ema_xg_v6_contra_home, partidos_v6_home,
                 ema_xg_v6_favor_away, ema_xg_v6_contra_away, partidos_v6_away,
                 ultima_actualizacion, ultimo_partido_procesado)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (eq_norm, display, "copa_internacional",
                  ema_favor_home, ema_contra_home, n_home,
                  ema_favor_away, ema_contra_away, n_away,
                  ts_now, ultimo_fecha))
            n_inserts += 1
        except Exception as e:
            print(f"  [FAIL] {eq_norm}: {e}")
            n_skipped += 1

    conn.commit()
    print(f"\n[OK] inserts={n_inserts}, skipped={n_skipped}")

    # Verificación: Olimpia debería tener EMA ahora
    print("\n=== Verificacion Olimpia ===")
    r = cur.execute("""
        SELECT equipo_norm, equipo_real, liga,
               round(ema_xg_v6_favor_home,3), round(ema_xg_v6_contra_home,3), partidos_v6_home,
               round(ema_xg_v6_favor_away,3), round(ema_xg_v6_contra_away,3), partidos_v6_away
        FROM historial_equipos_v6_shadow
        WHERE equipo_norm='clubolimpia'
    """).fetchone()
    if r:
        print(f"  {r[1]:<25s} liga={r[2]}")
        print(f"    HOME: favor={r[3]} contra={r[4]} N={r[5]}")
        print(f"    AWAY: favor={r[6]} contra={r[7]} N={r[8]}")
    conn.close()


if __name__ == "__main__":
    main()

"""
[adepor-141 V14 v2 SHADOW logger] Hook SHADOW puro para V14 v2 motor copa.

Ejecuta predicciones V14 v2 sobre partidos copa LIQUIDADOS sin pick productivo.
NO afecta motor productivo. Loggea a tabla `picks_shadow_v14_copa` con
`aplicado_produccion=0` siempre. Idempotente (PK fecha+eq_l+eq_v evita duplicados).

Workflow:
1. Lee coefs + scaler params persistidos en config_motor_valores.lr_v14_v2_weights
2. Identifica partidos copa de v_partidos_unificado en ventana especificada
3. Calcula features V14 v2 (delta_elo, dummies, log1p(n)) — sin xG
4. Aplica scaler + LR multinomial → probs (p_L, p_X, p_V)
5. Persiste a picks_shadow_v14_copa con outcome real (si liquidado)

Para promoción a producción (post N>=200 picks SHADOW):
- Crear bead [PROPOSAL: MANIFESTO CHANGE] con yield/Brier/CI95
- Esperar approval lead
- Hook integrado a motor productivo (futura sub-tarea)

[REF: docs/papers/v14_feature_scaling.md]
[REF: docs/papers/v14_train_coverage.md]
[REF: docs/papers/v14_regime_changes.md]
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path
import datetime as _dt

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS picks_shadow_v14_copa (
    fecha_log TEXT NOT NULL,
    fecha_partido TEXT NOT NULL,
    equipo_local_norm TEXT NOT NULL,
    equipo_visita_norm TEXT NOT NULL,
    competicion_tipo TEXT,
    competicion TEXT,
    -- Features
    elo_local_pre REAL,
    elo_visita_pre REAL,
    delta_elo_pre REAL,
    n_acum_local INTEGER,
    n_acum_visita INTEGER,
    -- Predicciones V14 v2
    prob_1_v14_v2 REAL,
    prob_x_v14_v2 REAL,
    prob_2_v14_v2 REAL,
    argmax_v14_v2 TEXT,
    p_max_v14_v2 REAL,
    -- Outcome (NULL si futuro)
    goles_l INTEGER,
    goles_v INTEGER,
    outcome_real TEXT,  -- '1' / 'X' / '2' / NULL
    hit INTEGER,        -- 1 si argmax==outcome, 0 else, NULL si futuro
    -- Filtro apostable (rules drill SHADOW 2026-04-29, hit 69.4%)
    pick_apostable_v14_v2 INTEGER DEFAULT 0,
    -- Metadata
    shadow_version TEXT NOT NULL DEFAULT 'v14_v2',
    aplicado_produccion INTEGER NOT NULL DEFAULT 0,
    razon_no_aplicado TEXT DEFAULT 'shadow_puro_pendiente_n200',
    weights_fecha TEXT,  -- fecha_calibrado del lr_v14_v2_weights usado
    PRIMARY KEY (fecha_partido, equipo_local_norm, equipo_visita_norm)
);

CREATE INDEX IF NOT EXISTS idx_pkv14_fecha ON picks_shadow_v14_copa(fecha_partido);
CREATE INDEX IF NOT EXISTS idx_pkv14_outcome ON picks_shadow_v14_copa(outcome_real);
CREATE INDEX IF NOT EXISTS idx_pkv14_hit ON picks_shadow_v14_copa(hit);
CREATE INDEX IF NOT EXISTS idx_pkv14_apostable ON picks_shadow_v14_copa(pick_apostable_v14_v2);
"""

# [REF: docs/papers/v14_v2_copa_nacional_filtro_apostable.md]
TURKIYE = "Türkiye Kupası"  # Türkiye Kupası


def _es_apostable_copa_nacional(competicion, argmax, p_max, delta_elo):
    """Aplica rules SHADOW drill 2026-04-29 (subset hit 69.4%, wilson_lo 65.7%)."""
    # Exclusiones (override)
    if competicion == "Coupe de France" and argmax == "1" and p_max < 0.55: return 0
    if competicion == "Copa del Rey" and argmax == "1" and p_max < 0.65: return 0
    if competicion == "Copa Argentina" and argmax == "1" and p_max < 0.55: return 0
    # Inclusiones
    if argmax == "1" and p_max >= 0.55 and delta_elo >= 200: return 1
    if competicion == "Copa del Rey" and argmax == "2" and p_max >= 0.45: return 1
    if competicion == TURKIYE and argmax == "1" and p_max >= 0.45: return 1
    if competicion == "Coppa Italia" and argmax == "1" and p_max >= 0.45: return 1
    if p_max >= 0.65: return 1
    return 0


def crear_tabla(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def cargar_weights(conn):
    r = conn.execute("""
        SELECT valor_texto FROM config_motor_valores
        WHERE clave='lr_v14_v2_weights' AND scope='global'
    """).fetchone()
    if not r:
        raise RuntimeError(
            "lr_v14_v2_weights NO encontrado en config_motor_valores. "
            "Correr scripts/calibrar_motor_copa_v14_v2.py primero."
        )
    j = json.loads(r[0])
    return {
        "feature_names": j["feature_names"],
        "classes": j["classes"],
        "coefs": np.array(j["coefs"]),
        "intercepts": np.array(j["intercepts"]),
        "scaler_mean": np.array(j["scaler_mean"]),
        "scaler_scale": np.array(j["scaler_scale"]),
        "metadata": j.get("metadata", {}),
    }


def lookup_elo(conn, eq_norm, fecha):
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm=? AND fecha<? ORDER BY fecha DESC LIMIT 1
    """, (eq_norm, fecha)).fetchone()
    return (r[0], r[1]) if r else (None, 0)


def predict_v14_v2(weights, delta_elo, d_int, d_nac, log1p_n):
    """Aplica scaler + LR multinomial. Returns (p_L, p_X, p_V, argmax, p_max)."""
    x_raw = np.array([delta_elo, d_int, d_nac, log1p_n])
    x_scaled = (x_raw - weights["scaler_mean"]) / weights["scaler_scale"]
    # Logits = X @ coefs.T + intercepts
    logits = weights["coefs"] @ x_scaled + weights["intercepts"]  # shape (3,)
    # Softmax
    e = np.exp(logits - logits.max())
    probs = e / e.sum()
    p_L, p_X, p_V = float(probs[0]), float(probs[1]), float(probs[2])
    am_idx = int(probs.argmax())
    am = ["1", "X", "2"][am_idx]
    return p_L, p_X, p_V, am, float(probs.max())


def loggear(conn, weights, fecha_min, fecha_max, dry_run=False):
    """Procesa partidos copa en [fecha_min, fecha_max). Loggea SHADOW."""
    rows = conn.execute("""
        SELECT v.fecha, v.equipo_local_norm, v.equipo_visita_norm,
               v.competicion_tipo, v.competicion, v.goles_l, v.goles_v
        FROM v_partidos_unificado v
        WHERE v.competicion_tipo IN ('copa_internacional', 'copa_nacional')
          AND v.equipo_local_norm IS NOT NULL AND v.equipo_visita_norm IS NOT NULL
          AND v.fecha >= ? AND v.fecha < ?
        ORDER BY v.fecha
    """, (fecha_min, fecha_max)).fetchall()

    HOME_ADV = 100
    weights_fecha = weights["metadata"].get("fecha_calibrado", "?")
    log_ts = _dt.datetime.now().isoformat(timespec="seconds")
    inserts = []
    skip_no_elo = 0

    for fecha, eq_l, eq_v, ct, comp, gl, gv in rows:
        elo_l, n_l = lookup_elo(conn, eq_l, fecha)
        elo_v, n_v = lookup_elo(conn, eq_v, fecha)
        if elo_l is None or elo_v is None or n_l < 1 or n_v < 1:
            skip_no_elo += 1
            continue
        delta_elo = (elo_l + HOME_ADV) - elo_v
        d_int = 1.0 if ct == "copa_internacional" else 0.0
        d_nac = 1.0 if ct == "copa_nacional" else 0.0
        log1p_n = float(np.log1p(n_l + n_v))

        p_L, p_X, p_V, am, p_max = predict_v14_v2(weights, delta_elo, d_int, d_nac, log1p_n)

        outcome = None
        hit = None
        if gl is not None and gv is not None:
            outcome = "1" if gl > gv else ("X" if gl == gv else "2")
            hit = int(am == outcome)

        # Pick apostable: solo evaluado en copa_nacional (rules 2026-04-29 drill)
        pick_ap = 0
        if ct == "copa_nacional":
            pick_ap = _es_apostable_copa_nacional(comp, am, p_max, delta_elo)

        inserts.append((
            log_ts, fecha, eq_l, eq_v, ct, comp,
            elo_l, elo_v, delta_elo, n_l, n_v,
            p_L, p_X, p_V, am, p_max,
            gl, gv, outcome, hit,
            pick_ap,
            "v14_v2", 0, "shadow_puro_pendiente_n200", weights_fecha,
        ))

    print(f"  Partidos elegibles V14 v2 SHADOW: {len(inserts)} (skip cold-start: {skip_no_elo})")

    if dry_run:
        print(f"  [DRY-RUN] No se persiste. Sample primeros 5:")
        for ins in inserts[:5]:
            print(f"    {ins[1]} {ins[2][:20]:20s} vs {ins[3][:20]:20s} "
                  f"P=({ins[11]:.3f},{ins[12]:.3f},{ins[13]:.3f}) AM={ins[14]} OUT={ins[18]} HIT={ins[19]}")
        return 0

    conn.executemany("""
        INSERT OR REPLACE INTO picks_shadow_v14_copa (
            fecha_log, fecha_partido, equipo_local_norm, equipo_visita_norm,
            competicion_tipo, competicion,
            elo_local_pre, elo_visita_pre, delta_elo_pre, n_acum_local, n_acum_visita,
            prob_1_v14_v2, prob_x_v14_v2, prob_2_v14_v2, argmax_v14_v2, p_max_v14_v2,
            goles_l, goles_v, outcome_real, hit,
            pick_apostable_v14_v2,
            shadow_version, aplicado_produccion, razon_no_aplicado, weights_fecha
        ) VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?, ?,?,?,?)
    """, inserts)
    conn.commit()
    print(f"  Persistido: {len(inserts)} filas en picks_shadow_v14_copa.")
    return len(inserts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-min", default="2025-01-01",
                    help="Fecha inicio (default 2025-01-01 OOS test).")
    ap.add_argument("--fecha-max", default=None,
                    help="Fecha fin (default hoy + 30 días).")
    ap.add_argument("--dry-run", action="store_true",
                    help="No persistir, solo simular.")
    ap.add_argument("--backfill-all", action="store_true",
                    help="Backfill desde 2022-01-01 (full historical SHADOW).")
    args = ap.parse_args()

    if args.backfill_all:
        args.fecha_min = "2022-01-01"
    if args.fecha_max is None:
        args.fecha_max = (_dt.date.today() + _dt.timedelta(days=30)).isoformat()

    conn = sqlite3.connect(DB); conn.text_factory = str

    print(f"=== STEP 1: Crear tabla picks_shadow_v14_copa ===")
    crear_tabla(conn)

    print(f"\n=== STEP 2: Cargar weights V14 v2 ===")
    weights = cargar_weights(conn)
    md = weights["metadata"]
    print(f"  Calibrado: {md.get('fecha_calibrado')} N_train={md.get('n_train')} "
          f"Brier_test={md.get('brier_test')} Hit_test={md.get('hit_test')}")

    print(f"\n=== STEP 3: Loggear ventana [{args.fecha_min}, {args.fecha_max}) ===")
    n = loggear(conn, weights, args.fecha_min, args.fecha_max, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n=== STEP 4: Resumen tabla SHADOW ===")
        total = conn.execute("SELECT COUNT(*) FROM picks_shadow_v14_copa").fetchone()[0]
        liquidados = conn.execute("SELECT COUNT(*) FROM picks_shadow_v14_copa WHERE outcome_real IS NOT NULL").fetchone()[0]
        hits = conn.execute("SELECT COUNT(*) FROM picks_shadow_v14_copa WHERE hit=1").fetchone()[0]
        print(f"  Total filas SHADOW: {total}")
        print(f"  Liquidados (con outcome): {liquidados}")
        if liquidados > 0:
            print(f"  Hit rate SHADOW: {hits}/{liquidados} = {100.0*hits/liquidados:.1f}%")
        # Por competicion_tipo
        print(f"\n  Distribución por competicion_tipo (liquidados):")
        for r in conn.execute("""
            SELECT competicion_tipo, COUNT(*) as n,
                   SUM(CASE WHEN hit=1 THEN 1 ELSE 0 END) as h
            FROM picks_shadow_v14_copa
            WHERE outcome_real IS NOT NULL
            GROUP BY competicion_tipo
        """):
            ct, n, h = r
            print(f"    {ct:25s} N={n:>5d} hit={100.0*h/n:.1f}%")

    conn.close()


if __name__ == "__main__":
    main()

"""[adepor-d7h F3] Drift detector para Brier rolling.

Diariamente:
  1. Para cada arch (V0, V6, V12) y cada liga + global:
     - Brier rolling 30 dias sobre picks_shadow_arquitecturas
     - Comparar con baseline (in-sample del entrenamiento batch)
     - Si rolling > baseline + 2*sigma: alerta
  2. Persistir en drift_alerts.

Llamado por bd schedule diariamente o cron del sistema.
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "fondo_quant.db"
WINDOW_DAYS = 30
MIN_N_WINDOW = 30           # min N en ventana para emitir alerta
SIGMA_FACTOR = 2.0          # umbral = baseline + 2*sigma
MIN_DAYS_GAP = 14           # min dias entre alertas mismo (arch, liga)

# Baselines (Brier in-sample) — puede leerse de config si se persiste
BASELINES = {
    'V0': {'mean': 0.658, 'sigma': 0.020},   # OOS observado
    'V6': {'mean': 0.602, 'sigma': 0.018},
    'V12': {'mean': 0.587, 'sigma': 0.020},
}


def init_drift_table():
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drift_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_deteccion TEXT NOT NULL,
            arch TEXT NOT NULL,
            liga TEXT NOT NULL,
            n_window INTEGER,
            brier_rolling REAL,
            brier_baseline REAL,
            brier_2sigma REAL,
            severity TEXT,
            accion_sugerida TEXT,
            bead_creado TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_drift_arch_liga ON drift_alerts(arch, liga)")
    con.commit(); con.close()


def compute_brier(p1, px, p2, real):
    y1 = 1 if real == "1" else 0
    yx = 1 if real == "X" else 0
    y2 = 1 if real == "2" else 0
    return (p1-y1)**2 + (px-yx)**2 + (p2-y2)**2


def get_real_outcome(cur, id_partido):
    """Lookup outcome real desde partidos_backtest."""
    row = cur.execute("""
        SELECT goles_l, goles_v FROM partidos_backtest WHERE id_partido=?
    """, (id_partido,)).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    if row[0] > row[1]: return "1"
    if row[0] < row[1]: return "2"
    return "X"


def detect_drift(window_days=WINDOW_DAYS, dry_run=False):
    init_drift_table()
    con = sqlite3.connect(DB); cur = con.cursor()
    fecha_corte = (datetime.now() - timedelta(days=window_days)).isoformat()

    print(f"=== Drift detector (ventana {window_days}d desde {fecha_corte[:10]}) ===")

    # Iterar arquitecturas
    arch_cols = {
        'V0': ('prob_1_actual', 'prob_x_actual', 'prob_2_actual'),
        'V6': ('prob_1_v6_recal', 'prob_x_v6_recal', 'prob_2_v6_recal'),
        'V12': ('prob_1_v12_lr', 'prob_x_v12_lr', 'prob_2_v12_lr'),
    }
    alertas = []

    for arch, (c1, cx, c2) in arch_cols.items():
        baseline = BASELINES[arch]
        threshold = baseline['mean'] + SIGMA_FACTOR * baseline['sigma']

        rows = cur.execute(f"""
            SELECT pais, id_partido, {c1}, {cx}, {c2}
            FROM picks_shadow_arquitecturas
            WHERE fecha_log >= ? AND {c1} IS NOT NULL AND {cx} IS NOT NULL AND {c2} IS NOT NULL
        """, (fecha_corte,)).fetchall()

        if not rows:
            print(f"  {arch}: sin datos en ventana — skip")
            continue

        # Bucket por liga
        buckets = defaultdict(list)
        for pais, id_p, p1, px, p2 in rows:
            real = get_real_outcome(cur, id_p)
            if real:
                br = compute_brier(p1, px, p2, real)
                buckets[pais].append(br)
                buckets['__global__'].append(br)

        for liga, brs in buckets.items():
            n = len(brs)
            if n < MIN_N_WINDOW:
                continue
            avg_br = sum(brs) / n
            severity = None
            if avg_br > threshold:
                severity = 'critical' if avg_br > baseline['mean'] + 3 * baseline['sigma'] else 'warning'
                # Cooldown: skip si hay alerta misma arch/liga en los ultimos MIN_DAYS_GAP
                last = cur.execute("""
                    SELECT MAX(fecha_deteccion) FROM drift_alerts WHERE arch=? AND liga=?
                """, (arch, liga)).fetchone()
                if last and last[0]:
                    last_dt = datetime.fromisoformat(last[0].split(' ')[0] if ' ' in last[0] else last[0])
                    if (datetime.now() - last_dt).days < MIN_DAYS_GAP:
                        severity = None  # cooldown activo

            line = f"  {arch} {liga:<14s} N={n:<4d} Brier={avg_br:.4f} (baseline={baseline['mean']:.3f}, 2sigma={threshold:.3f})"
            if severity:
                line += f"  -> {severity.upper()}"
                alertas.append((arch, liga, n, avg_br, baseline['mean'], threshold, severity))
            print(line)

    if alertas:
        print(f"\n=== {len(alertas)} ALERTAS ===")
        for a in alertas:
            print(f"  {a[6].upper()}: {a[0]} {a[1]} Brier={a[3]:.4f} (umbral={a[5]:.4f}, +{(a[3]-a[4])*100:.1f}pp vs baseline)")
            if not dry_run:
                accion = f"Re-entrenar {a[0]} batch (rolling Brier supera 2sigma del baseline)"
                cur.execute("""
                    INSERT INTO drift_alerts
                        (fecha_deteccion, arch, liga, n_window, brier_rolling,
                         brier_baseline, brier_2sigma, severity, accion_sugerida, bead_creado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """, (datetime.now().isoformat(), a[0], a[1], a[2], a[3], a[4], a[5], a[6], accion))
        if not dry_run:
            con.commit()
            print(f"\n[PERSIST] {len(alertas)} alertas registradas en drift_alerts")
    else:
        print("\n[OK] Sin drift detectado — todas las arquitecturas dentro de baseline + 2sigma")

    con.close()
    return alertas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drift detector para Adepor")
    parser.add_argument('--window-days', type=int, default=WINDOW_DAYS)
    parser.add_argument('--dry-run', action='store_true', help='Sin persistir')
    args = parser.parse_args()
    detect_drift(args.window_days, args.dry_run)

"""Persiste resultados walk-forward (iter1/2/3) en xg_calibration_history.

Lee los JSON outputs y poblar la tabla DB para consulta en futuras sesiones.
Idempotente: borra entries previas con mismo (bead_id, iter, liga) antes de insertar.
"""
import datetime
import json
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
ANALISIS = ROOT / "analisis"

INPUTS = [
    {
        "json": ANALISIS / "walk_forward_multiliga.json",
        "iter": 1,
        "fuente": "football-data.co.uk",
        "temp_train": "2021-22,2022-23,2023-24",
        "temp_predict": 2024,
        "scope": "EUR full stats CSV",
    },
    {
        "json": ANALISIS / "walk_forward_latam.json",
        "iter": 2,
        "fuente": "api-football",
        "temp_train": "2021,2022,2023",
        "temp_predict": 2024,
        "scope": "LATAM goals-only API",
    },
    {
        "json": ANALISIS / "walk_forward_full_stats.json",
        "iter": 3,
        "fuente": "espn-core",
        "temp_train": "2022,2023",
        "temp_predict": 2024,
        "scope": "LATAM full stats ESPN",
    },
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    inserted = 0
    for inp in INPUTS:
        if not inp["json"].exists():
            print(f"[SKIP] {inp['json'].name} no existe")
            continue
        data = json.loads(inp["json"].read_text(encoding="utf-8"))
        bead_id = data.get("bead_id", "adepor-bgt")
        ligas = data.get("ligas", {})

        for liga, info in ligas.items():
            m = info.get("metricas", {})
            if not m:
                continue
            cfg = info.get("config", {})

            # Limpiar entries previas mismo (bead, iter, liga)
            cur.execute(
                "DELETE FROM xg_calibration_history WHERE bead_id=? AND iter=? AND liga=?",
                (bead_id, inp["iter"], liga),
            )

            n_zero_stats = info.get("n_zero_stats", 0)
            n_total_input = info.get("n_total_input")

            edge_pp = (m["hit_rate"] - m["base_rate_local"]) * 100

            cur.execute(
                """
                INSERT INTO xg_calibration_history
                (fecha_corrida, bead_id, iter, fuente, liga, temp_train, temp_predict,
                 n_total, n_predict, n_zero_stats, promedio_liga, rho_usado,
                 hit_rate, base_rate_local, edge_pp, brier_mean,
                 xg_mse_local, xg_mse_visita, xg_bias_local, xg_bias_visita,
                 calibracion_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fecha, bead_id, inp["iter"], inp["fuente"], liga,
                    inp["temp_train"], inp["temp_predict"],
                    n_total_input,
                    m.get("n"),
                    n_zero_stats,
                    cfg.get("promedio_liga"),
                    cfg.get("rho"),
                    m.get("hit_rate"),
                    m.get("base_rate_local"),
                    round(edge_pp, 4),
                    m.get("brier_mean"),
                    m.get("xg_mse_local"),
                    m.get("xg_mse_visita"),
                    m.get("xg_bias_local"),
                    m.get("xg_bias_visita"),
                    json.dumps(m.get("calibracion_por_bucket", {}), ensure_ascii=False),
                    inp["scope"],
                ),
            )
            inserted += 1
            print(f"  insertado: iter{inp['iter']} {liga} hit={m['hit_rate']:.4f} edge={edge_pp:+.2f}pp")

    con.commit()

    # Verifica
    print(f"\n[OK] {inserted} filas insertadas/actualizadas")
    cur.execute("SELECT iter, COUNT(*), AVG(hit_rate), AVG(edge_pp) FROM xg_calibration_history GROUP BY iter")
    print("\nResumen por iter:")
    for r in cur.fetchall():
        print(f"  iter{r[0]}: N_ligas={r[1]}, hit_avg={r[2]:.4f}, edge_avg={r[3]:.2f}pp")

    con.close()


if __name__ == "__main__":
    main()

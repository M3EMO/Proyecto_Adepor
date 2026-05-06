"""Fix bug match Alemania (6.8% → target 80%+).

ESPN incluye prefijos (Borussia, Bayer, FC, VfL, etc.) que fdco quita.
Mapping ESPN_normalizado → fdco_norm.
"""
import sqlite3

DB = "fondo_quant.db"

# Mapping ESPN→fdco_norm para Alemania (descubierto via inspección)
MAPPING_ALE = {
    "1. FC Heidenheim 1846": "heidenheim",
    "1. FC Union Berlin": "unionberlin",
    "Bayer Leverkusen": "leverkusen",
    "Bayern Munich": "bayernmunich",
    "Borussia Dortmund": "dortmund",
    "Borussia Mönchengladbach": "m'gladbach",
    "Eintracht Frankfurt": "einfrankfurt",
    "FC Augsburg": "augsburg",
    "FC Cologne": "fckoln",
    "Hamburg SV": "hamburg",
    "Hertha Berlin": "hertha",
    "Holstein Kiel": "holsteinkiel",
    "Mainz": "mainz",
    "RB Leipzig": "rbleipzig",
    "SC Freiburg": "freiburg",
    "SV Darmstadt 98": "darmstadt",
    "Schalke 04": "schalke04",
    "St. Pauli": "stpauli",
    "TSG Hoffenheim": "hoffenheim",
    "VfB Stuttgart": "stuttgart",
    "VfL Bochum": "bochum",
    "VfL Wolfsburg": "wolfsburg",
    "Werder Bremen": "werderbremen",
}


def normalize_simple(s):
    return ''.join(c for c in s.lower() if c.isalnum())


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    print("Pre-fix match Alemania:")
    n_pre = cur.execute("""
        SELECT COUNT(*) FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha=f.fecha
         AND LOWER(REPLACE(REPLACE(REPLACE(s.ht,' ',''),'-',''),'.','')) = f.equipo_local_norm
         AND LOWER(REPLACE(REPLACE(REPLACE(s.at,' ',''),'-',''),'.','')) = f.equipo_visita_norm
        WHERE s.liga='Alemania' AND f.cuota_1 IS NOT NULL
    """).fetchone()[0]
    n_total = cur.execute("SELECT COUNT(*) FROM stats_partido_espn WHERE liga='Alemania'").fetchone()[0]
    print(f"  matched: {n_pre} / {n_total} = {n_pre/n_total*100:.1f}%")

    # Crear tabla de mapping (o agregar cols ht_fdco_norm/at_fdco_norm)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(stats_partido_espn)").fetchall()]
    if 'ht_fdco_norm' not in cols:
        cur.execute("ALTER TABLE stats_partido_espn ADD COLUMN ht_fdco_norm TEXT")
    if 'at_fdco_norm' not in cols:
        cur.execute("ALTER TABLE stats_partido_espn ADD COLUMN at_fdco_norm TEXT")

    # Aplicar mapping a Alemania
    print("\nAplicando mapping ALE...")
    n_updated = 0
    for ht_espn, fdco_norm in MAPPING_ALE.items():
        r = cur.execute("UPDATE stats_partido_espn SET ht_fdco_norm=? WHERE liga='Alemania' AND ht=?",
                         (fdco_norm, ht_espn))
        n_updated += r.rowcount
        cur.execute("UPDATE stats_partido_espn SET at_fdco_norm=? WHERE liga='Alemania' AND at=?",
                     (fdco_norm, ht_espn))
    conn.commit()
    print(f"  rows actualizadas (HT solo): {n_updated}")

    # Para no-Alemania, usar normalize_simple como fallback
    cur.execute("""
        UPDATE stats_partido_espn SET ht_fdco_norm = LOWER(REPLACE(REPLACE(REPLACE(ht,' ',''),'-',''),'.',''))
        WHERE ht_fdco_norm IS NULL
    """)
    cur.execute("""
        UPDATE stats_partido_espn SET at_fdco_norm = LOWER(REPLACE(REPLACE(REPLACE(at,' ',''),'-',''),'.',''))
        WHERE at_fdco_norm IS NULL
    """)
    conn.commit()

    # Re-medir
    print("\nPost-fix match Alemania:")
    n_post = cur.execute("""
        SELECT COUNT(*) FROM stats_partido_espn s
        JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha=f.fecha
         AND s.ht_fdco_norm = f.equipo_local_norm
         AND s.at_fdco_norm = f.equipo_visita_norm
        WHERE s.liga='Alemania' AND f.cuota_1 IS NOT NULL
    """).fetchone()[0]
    print(f"  matched: {n_post} / {n_total} = {n_post/n_total*100:.1f}%")
    print(f"  Δ: +{n_post - n_pre} partidos ALE recuperados")

    # Re-medir match-rate global
    print("\nMatch-rate por liga (post-fix):")
    print(f"{'liga':<14s}{'stats':>8s}{'matched':>10s}{'pct':>7s}")
    n_global_total = 0; n_global_match = 0
    for liga, in cur.execute("SELECT DISTINCT liga FROM stats_partido_espn ORDER BY liga").fetchall():
        n_stats = cur.execute("SELECT COUNT(*) FROM stats_partido_espn WHERE liga=?", (liga,)).fetchone()[0]
        n_match = cur.execute("""
            SELECT COUNT(*) FROM stats_partido_espn s
            JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha=f.fecha
             AND s.ht_fdco_norm = f.equipo_local_norm
             AND s.at_fdco_norm = f.equipo_visita_norm
            WHERE s.liga=? AND f.cuota_1 IS NOT NULL
        """, (liga,)).fetchone()[0]
        pct = n_match/n_stats*100 if n_stats else 0
        n_global_total += n_stats; n_global_match += n_match
        print(f"{liga:<14s}{n_stats:>8d}{n_match:>10d}{pct:>6.1f}%")
    print(f"\nGLOBAL: {n_global_match}/{n_global_total} = {n_global_match/n_global_total*100:.1f}%")


if __name__ == "__main__":
    main()

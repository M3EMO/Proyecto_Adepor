"""
[adepor — pre-paso a backfill EMA extranjeros] Whitelist unificación de norms
en partidos_no_liga para equipos con EMA armada que aparecen con norm distinto
en copas internacionales.

VALIDADOS MANUALMENTE 2026-05-02 — son MISMO club, distinto display:
- 1. FC Köln <-> FC Koln (Alemania)
- 1. FC Heidenheim <-> Heidenheim (Alemania)
- Hamburger SV <-> Hamburg SV (Alemania)
- FC Schalke 04 <-> Schalke 04 (Alemania)
- Friburgo <-> Freiburg (alias español/alemán)
- Saint Etienne <-> St Etienne (Francia)
- Celta de Vigo <-> Celta Vigo (España)
- Granada CF <-> Granada (España)
- Adana Demirspor <-> Ad. Demirspor (Turquía abrev.)
- Kasmpasa <-> Kasimpasa (Turquía typo)
- Genclerbirligi SK <-> Genclerbirligi (Turquía)
- Argentinos JRS <-> Argentinos Juniors
- Independ. Rivadavia <-> Independiente Rivadavia
- Corinthian <-> Corinthians (Brasil)
- Carabobo FC <-> Carabobo (Venezuela)
- Estudiantes de Merida FC <-> Estudiantes de Merida (Venezuela)
- Deportivo Tachira FC <-> Deportivo Tachira (Venezuela)
- Delfin SC <-> Delfin (Ecuador)
- Viking <-> Viking fk (Noruega)

EXCLUIDOS por verificación manual (clubes DISTINTOS):
- Angers != Rangers, Manchester != Winchester City, Napoli != Anapolis,
- Botafogo != Botafogo SP/PB, Liverpool != AFC Liverpool,
- Banfield != Binfield, Sheffield != Harefield, Nacional URU != El Nacional ECU,
- Fluminense != Fluminense PI, Portuguesa VEN != Portuguesa RJ.

USO:
    py scripts/fix_unify_norm_copas.py            # dry-run
    py scripts/fix_unify_norm_copas.py --apply    # SNAPSHOT + UPDATE
"""
from __future__ import annotations
import sqlite3
import sys
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
APPLY = "--apply" in sys.argv

# (norm_variante_en_copa, norm_canonico_con_EMA, display_canonico, comentario)
UNIFICACIONES = [
    ("1fckoln",                "fckoln",                  "FC Koln",                 "Alemania prefijo 1. FC"),
    ("1fcheidenheim",          "heidenheim",              "Heidenheim",              "Alemania prefijo 1. FC"),
    ("hamburgersv",            "hamburgsv",               "Hamburg SV",              "Alemania alias"),
    ("fcschalke04",            "schalke04",               "Schalke 04",              "Alemania prefijo FC"),
    ("friburgo",               "freiburg",                "Freiburg",                "Alemania alias español"),
    ("saintetienne",           "stetienne",               "St Etienne",              "Francia alias"),
    ("celtadevigo",            "celtavigo",               "Celta Vigo",              "España alias"),
    ("granadacf",              "granada",                 "Granada",                 "España sufijo CF"),
    ("adanademirspor",         "addemirspor",             "Ad. Demirspor",           "Turquía alias largo"),
    ("kasmpasa",               "kasimpasa",               "Kasimpasa",               "Turquía typo"),
    ("genclerbirligisk",       "genclerbirligi",          "Genclerbirligi",          "Turquía sufijo SK"),
    ("argentinosjrs",          "argentinosjuniors",       "Argentinos Juniors",      "Argentina abrev"),
    ("independrivadavia",      "independienterivadavia",  "Independiente Rivadavia", "Argentina abrev"),
    ("corinthian",             "corinthians",             "Corinthians",             "Brasil typo singular"),
    ("carabobofc",             "carabobo",                "Carabobo",                "Venezuela sufijo FC"),
    ("estudiantesdemeridafc",  "estudiantesdemerida",     "Estudiantes de Merida",   "Venezuela sufijo FC"),
    ("deportivotachirafc",     "deportivotachira",        "Deportivo Tachira",       "Venezuela sufijo FC"),
    ("delfinsc",               "delfin",                  "Delfin",                  "Ecuador sufijo SC"),
    ("viking",                 "vikingfk",                "Viking FK",               "Noruega sufijo FK"),
]


def main():
    snap = None
    if APPLY:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = f"snapshots/fondo_quant_{ts}_pre_unify_norm_copas.db"
        Path(snap).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DB, snap)
        print(f"[SNAPSHOT] {snap}\n")

    conn = sqlite3.connect(DB); conn.text_factory=str
    cur = conn.cursor()

    print(f"{'APPLY' if APPLY else 'DRY-RUN'} unificación norms copas:\n")
    print(f"  {'variant_norm':<28s} -> {'canon_norm':<28s} display              N_local  N_visita")

    total_l = total_v = 0
    for var_norm, canon_norm, canon_disp, comment in UNIFICACIONES:
        # Validar que canon_norm tiene EMA
        ema_exists = cur.execute(
            "SELECT 1 FROM historial_equipos_v6_shadow WHERE equipo_norm=?", (canon_norm,)
        ).fetchone()
        if not ema_exists:
            print(f"  [SKIP] canon_norm={canon_norm} no tiene EMA. Omito {var_norm}.")
            continue

        # Counts
        n_l = cur.execute("""SELECT COUNT(*) FROM partidos_no_liga
            WHERE equipo_local_norm=?""", (var_norm,)).fetchone()[0]
        n_v = cur.execute("""SELECT COUNT(*) FROM partidos_no_liga
            WHERE equipo_visita_norm=?""", (var_norm,)).fetchone()[0]

        try:
            print(f"  {var_norm:<28s} -> {canon_norm:<28s} {canon_disp:<22s} {n_l:>7d}  {n_v:>7d}")
        except UnicodeEncodeError:
            print(f"  ?? variant->{canon_norm} L={n_l} V={n_v}")
        total_l += n_l; total_v += n_v

        if APPLY:
            # Manejar UNIQUE constraint: identificar filas variantes que colidan
            # con canónica existente (misma fecha/contraparte/competicion).
            # Si colide → DELETE variante (canónica gana). Si no → UPDATE.
            for col_eq, col_norm, col_other, col_other_norm in [
                ("equipo_local", "equipo_local_norm", "equipo_visita", "equipo_visita_norm"),
                ("equipo_visita", "equipo_visita_norm", "equipo_local", "equipo_local_norm"),
            ]:
                # Filas con la variante en este lado
                rows_var = cur.execute(f"""
                    SELECT rowid, fecha, {col_other_norm}, competicion
                    FROM partidos_no_liga WHERE {col_norm}=?
                """, (var_norm,)).fetchall()
                for rid, fecha, other_norm, comp in rows_var:
                    # ¿Existe fila canónica con misma combinación?
                    exists = cur.execute(f"""
                        SELECT rowid FROM partidos_no_liga
                        WHERE {col_norm}=? AND {col_other_norm}=?
                          AND fecha=? AND competicion=?
                    """, (canon_norm, other_norm, fecha, comp)).fetchone()
                    if exists:
                        cur.execute("DELETE FROM partidos_no_liga WHERE rowid=?", (rid,))
                    else:
                        cur.execute(f"""
                            UPDATE partidos_no_liga
                            SET {col_eq}=?, {col_norm}=?
                            WHERE rowid=?
                        """, (canon_disp, canon_norm, rid))

    print(f"\nTOTAL filas UPDATE: local={total_l}, visita={total_v}, total={total_l+total_v}")

    if APPLY:
        conn.commit()
        print("[OK] commit aplicado")
    else:
        print("\nDRY-RUN. Para aplicar: --apply")
    conn.close()


if __name__ == "__main__":
    main()

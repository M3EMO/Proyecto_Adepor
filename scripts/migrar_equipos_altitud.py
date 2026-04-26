"""Migracion equipos_altitud — agrega equipos andinos faltantes (adepor-om4).

Solo INSERT equipos con altitud_estadio > 1500m (los que activan multiplicador
ALTITUD_NIVELES). Equipos sea-level NO se agregan (defaults a altitud=0
implicitamente cuando no estan en el catalogo).

Idempotente: INSERT OR IGNORE por equipo_norm (PRIMARY KEY).

Fuentes de altitud: Wikipedia + Soccerway + sitio oficial del club.
"""
import sqlite3
import sys
import unicodedata
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "fondo_quant.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def normalizar_extremo(texto):
    if not texto:
        return ""
    sin_tildes = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto).lower().strip())
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'[^a-z0-9]', '', sin_tildes)


# (equipo_real, altitud_m, ciudad/justificacion)
EQUIPOS_NUEVOS = [
    # === BOLIVIA ===
    ("Real Tomayapo", 1875, "Tarija (1875m)"),
    ("Real Potosí", 3885, "Potosi (3885m, Zona Muerte)"),
    ("Real Oruro", 3735, "Oruro (3735m, Zona Muerte)"),
    ("Universitario de Vinto", 2470, "Vinto, Cochabamba (2470m)"),
    ("Independiente Petrolero", 2810, "Sucre, Estadio Patria (2810m)"),
    ("GV San José", 3735, "Oruro (3735m, Zona Muerte). GV = Gualberto Villarroel"),
    ("Aurora", 2558, "Cochabamba (2558m)"),

    # === PERU ===
    ("UTC", 2750, "Cajamarca (2750m). Mismo club que UTC Cajamarca - normalizacion duplicada"),
    ("Los Chankas", 2845, "Andahuaylas, Apurimac (2845m)"),
    ("Comerciantes Unidos", 2649, "Cutervo, Cajamarca (2649m)"),
    ("ADT", 3050, "Tarma, Junin (3050m, Extremo). ADT = Asociacion Deportiva Tarma"),
    ("Melgar", 2335, "Arequipa (2335m). Mismo club que FBC Melgar - normalizacion duplicada"),
    ("FC Cajamarca", 2750, "Cajamarca (2750m)"),
    ("Cienciano del Cusco", 3399, "Cusco (3399m). Mismo club que Cienciano - normalizacion duplicada"),

    # === ECUADOR ===
    ("Universidad Católica (Quito)", 2850, "Quito (2850m). Mismo club que Universidad Catolica (Ecu)"),
    ("Libertad (Ecuador)", 2060, "Loja (2060m)"),
    ("Aucas", 2850, "Quito, Estadio Gonzalo Pozo Ripalda (2850m)"),
    ("Liga de Quito", 2850, "Quito (2850m). Mismo club que LDU Quito - normalizacion duplicada"),

    # === COLOMBIA ===
    ("Fortaleza CEIF", 2630, "Cota, Cundinamarca (2630m)"),
    ("Once Caldas", 2150, "Manizales (2150m)"),
    ("Internacional de Bogotá", 2640, "Bogota (2640m)"),
    ("Boyacá Chicó", 2810, "Tunja (2810m)"),
    ("Águilas Doradas", 2125, "Rionegro, Antioquia (2125m)"),
]

# Equipos faltantes evaluados pero NO agregados (sea-level o copa internacional o data insuficiente)
EQUIPOS_OMITIDOS = {
    # Bolivia low/sea-level:
    "San Antonio Bulo Bulo": "Bulo Bulo, Cochabamba ~250m",
    "Oriente Petrolero": "Santa Cruz ~416m",
    "Guabirá": "Montero, Santa Cruz ~302m",
    "Blooming": "Santa Cruz ~416m",
    "ABB": "Identidad/altitud no verificable con confianza — SKIP, requerir investigacion separada",

    # Peru low/sea-level:
    "Universitario": "Lima ~154m",
    "Sport Boys": "Callao ~10m",
    "Sporting Cristal": "Lima ~154m",
    "Juan Pablo II": "Chongoyape, Lambayeque ~150m",
    "Alianza Lima": "Lima ~154m",
    "Alianza Atlético": "Sullana ~60m",
    "Atlético-mg": "Brasileño (Belo Horizonte ~852m) - copa context, no aplica",
    "Deportivo Moquegua": "Moquegua ~1410m (justo bajo el threshold 1500)",

    # Ecuador low/sea-level:
    "Orense": "Machala ~6m",
    "Manta F.C.": "Manta ~12m",
    "Guayaquil City FC": "Guayaquil ~6m",
    "Emelec": "Guayaquil ~6m",
    "Delfín": "Manta ~12m",
    "Barcelona SC": "Guayaquil ~6m",
    "Leones": "Identidad ambigua (Leones del Norte? Leones FC?) — SKIP, requerir investigacion",

    # Colombia low/sea-level:
    "Jaguares de Córdoba": "Monteria ~13m",
    "Deportivo Cali": "Cali ~995m",
    "Bucaramanga": "Bucaramanga ~959m",
    "Atlético Junior": "Barranquilla ~18m",
    "América de Cali": "Cali ~995m",
    "Alianza FC": "Valledupar ~169m",
    "Llaneros": "Villavicencio ~467m",
    "Cúcuta Deportivo": "Cucuta ~320m",
    "Atlético Nacional": "Medellin ~1495m (justo bajo el threshold 1500)",
    "Deportes Limache": "Chileno (Limache ~140m) - copa context",
    "Deportivo Riestra": "Argentino (Buenos Aires ~25m) - copa context",
}


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Pre-conteo
    n_pre = cur.execute("SELECT COUNT(*) FROM equipos_altitud").fetchone()[0]
    print(f"equipos_altitud antes: {n_pre} entries")
    print()

    # INSERT con OR IGNORE (idempotente)
    inserted = []
    skipped_existing = []
    for equipo_real, altitud, justif in EQUIPOS_NUEVOS:
        equipo_norm = normalizar_extremo(equipo_real)
        before = cur.execute(
            "SELECT 1 FROM equipos_altitud WHERE equipo_norm = ?", (equipo_norm,)
        ).fetchone()
        cur.execute(
            "INSERT OR IGNORE INTO equipos_altitud (equipo_norm, equipo_real, altitud) VALUES (?, ?, ?)",
            (equipo_norm, equipo_real, altitud),
        )
        if cur.rowcount > 0:
            inserted.append((equipo_norm, equipo_real, altitud, justif))
        else:
            skipped_existing.append((equipo_norm, equipo_real))

    con.commit()
    n_post = cur.execute("SELECT COUNT(*) FROM equipos_altitud").fetchone()[0]

    # Reporte
    print(f"=== INSERTED ({len(inserted)}) ===")
    for eq_norm, eq_real, alt, justif in inserted:
        print(f"  +{alt:>4}m  {eq_real:<35} ({eq_norm})  -- {justif}")

    if skipped_existing:
        print(f"\n=== YA EXISTIAN, skipped ({len(skipped_existing)}) ===")
        for eq_norm, eq_real in skipped_existing:
            print(f"  ={eq_real} ({eq_norm})")

    print(f"\n=== EQUIPOS OMITIDOS DEL CATALOGO ({len(EQUIPOS_OMITIDOS)}) ===")
    print("(estos equipos aparecen como LOCAL en partidos_backtest pero NO se agregan)")
    print("(sea-level o sub-1500m o ambiguos — no activan ALTITUD_NIVELES)")
    for eq, just in EQUIPOS_OMITIDOS.items():
        print(f"  -{eq:<35} -- {just}")

    print(f"\n=== RESUMEN ===")
    print(f"  Pre:  {n_pre} entries")
    print(f"  Post: {n_post} entries")
    print(f"  Delta: +{n_post - n_pre}")

    con.close()


if __name__ == "__main__":
    main()

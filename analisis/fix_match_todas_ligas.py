"""Fix bug match para todas las ligas con cobertura fdco.

Mappings ESPN→fdco_norm derivados de inspección. Aplica fix.
"""
import sqlite3

DB = "fondo_quant.db"

# Mappings ESPN→fdco_norm — claves son nombres ESPN exactos (con acentos)
MAPPINGS = {
    "Alemania": {
        "1. FC Heidenheim 1846": "heidenheim", "1. FC Union Berlin": "unionberlin",
        "Bayer Leverkusen": "leverkusen", "Bayern Munich": "bayernmunich",
        "Borussia Dortmund": "dortmund", "Borussia Mönchengladbach": "m'gladbach",
        "Eintracht Frankfurt": "einfrankfurt", "FC Augsburg": "augsburg",
        "FC Cologne": "fckoln", "Hamburg SV": "hamburg",
        "Hertha Berlin": "hertha", "Holstein Kiel": "holsteinkiel",
        "Mainz": "mainz", "RB Leipzig": "rbleipzig",
        "SC Freiburg": "freiburg", "SV Darmstadt 98": "darmstadt",
        "Schalke 04": "schalke04", "St. Pauli": "stpauli",
        "TSG Hoffenheim": "hoffenheim", "VfB Stuttgart": "stuttgart",
        "VfL Bochum": "bochum", "VfL Wolfsburg": "wolfsburg",
        "Werder Bremen": "werderbremen",
    },
    "Argentina": {
        "Argentinos Juniors": "argentinosjrs", "Atletico Tucuman": "atl.tucuman", "Atlético Tucumán": "atl.tucuman",
        "Belgrano (Cordoba)": "belgrano", "Belgrano (córdoba)": "belgrano", "Belgrano (Córdoba)": "belgrano",
        "Central Cordoba (Santiago del Estero)": "centralcordoba",
        "Central Córdoba (Santiago del Estero)": "centralcordoba",
        "Central Córdoba (santiago del Estero)": "centralcordoba",
        "Colón (Santa Fe)": "colonsantafe", "Colon (Santa Fe)": "colonsantafe",
        "Deportivo Riestra": "dep.riestra",
        "Estudiantes de La Plata": "estudiantesl.p.", "Estudiantes de la Plata": "estudiantesl.p.",
        "Estudiantes de Rio Cuarto": "estudiantesriocuarto", "Estudiantes de Río Cuarto": "estudiantesriocuarto",
        "Gimnasia La Plata": "gimnasial.p.", "Gimnasia (La Plata)": "gimnasial.p.",
        "Gimnasia (Mendoza)": "gimnasiamendoza",
        "Independiente Rivadavia": "ind.rivadavia",
        "Newell's Old Boys": "newellsoldboys",
        "San Martin de San Juan": "sanmartins.j.", "San Martín de San Juan": "sanmartins.j.",
        "San Martin (Tucuman)": "sanmartint.", "San Martín (Tucumán)": "sanmartint.",
        "Sarmiento de Junin": "sarmientojunin", "Sarmiento de Junín": "sarmientojunin",
        "Talleres (Cordoba)": "tallerescordoba", "Talleres (Córdoba)": "tallerescordoba",
        "Union Santa Fe": "uniondesantafe", "Unión Santa Fe": "uniondesantafe",
        "Velez Sarsfield": "velezsarsfield", "Vélez Sarsfield": "velezsarsfield",
            'Lanús': 'lanus',
        'Huracán': 'huracan',
        'Godoy Cruz Antonio Tomba': 'godoycruz',
        'Sarmiento (Junín)': 'sarmientojunin',
        'Sarmiento (Junin)': 'sarmientojunin',
        'Sarmiento (junín)': 'sarmientojunin',
        'Sarmiento (junin)': 'sarmientojunin',
        'Unión (Santa Fe)': 'uniondesantafe',
        'Union (Santa Fe)': 'uniondesantafe',
        'Union (santa Fe)': 'uniondesantafe',
        'Instituto (Córdoba)': 'instituto',
        'Instituto (Cordoba)': 'instituto',
        'Instituto (córdoba)': 'instituto',
        'Instituto (cordoba)': 'instituto',
        'Gimnasia la Plata': 'gimnasial.p.',
        'Belgrano (cordoba)': 'belgrano',
        'Talleres (córdoba)': 'tallerescordoba',
        'Talleres (cordoba)': 'tallerescordoba',
        'Unión (santa Fe)': 'uniondesantafe',
        'Huracan': 'huracan',
},
    "Brasil": {
        "America Mineiro": "americamg", "América Mineiro": "americamg",
        "Athletico Paranaense": "athletico-pr", "Atletico Paranaense": "athletico-pr",
        "Atletico Goianiense": "atleticogo", "Atlético Goianiense": "atleticogo",
        "Atletico-MG": "atletico-mg", "Atlético-MG": "atletico-mg", "Atlético-mg": "atletico-mg",
        "Avai": "avai", "Avaí": "avai",
        "Botafogo": "botafogorj",
        "Ceara": "ceara", "Ceará": "ceara",
        "Chapecoense": "chapecoense-sc",
        "Criciuma": "criciuma", "Criciúma": "criciuma",
        "Cuiaba": "cuiaba", "Cuiabá": "cuiaba",
        "Flamengo": "flamengorj",
        "Goias": "goias", "Goiás": "goias",
        "Gremio": "gremio", "Grêmio": "gremio",
        "Sao Paulo": "saopaulo", "São Paulo": "saopaulo",
            'Red Bull Bragantino': 'bragantino',
        'Vasco da Gama': 'vasco',
        'Vitória': 'vitoria',
        'Vitoria': 'vitoria',
},
    "Inglaterra": {
        "AFC Bournemouth": "bournemouth",
        "Brighton & Hove Albion": "brighton",
        "Ipswich Town": "ipswich",
        "Leeds United": "leeds",
        "Leicester City": "leicester",
        "Luton Town": "luton",
        "Manchester City": "mancity",
        "Manchester United": "manunited",
        "Newcastle United": "newcastle",
        "Nottingham Forest": "nott'mforest",
        "Tottenham Hotspur": "tottenham",
        "West Ham United": "westham",
        "Wolverhampton Wanderers": "wolves",
    },
    "Espana": {
        "Alavés": "alaves", "Alaves": "alaves",
        "Almería": "almeria", "Almeria": "almeria",
        "Athletic Club": "athbilbao",
        "Atlético Madrid": "athmadrid", "Atletico Madrid": "athmadrid",
        "Celta Vigo": "celta",
        "Cádiz": "cadiz", "Cadiz": "cadiz",
        "Espanyol": "espanol",
        "Leganés": "leganes", "Leganes": "leganes",
        "Rayo Vallecano": "vallecano",
        "Real Betis": "betis",
        "Real Oviedo": "oviedo",
        "Real Sociedad": "sociedad",
        "Real Valladolid": "valladolid",
    },
    "Francia": {
        "AC Ajaccio": "ajaccio", "Ajaccio": "ajaccio",
        "AJ Auxerre": "auxerre",
        "AS Monaco": "monaco",
        "Clermont Foot": "clermont",
        "Le Havre AC": "lehavre", "Le Havre": "lehavre",
        "Paris Saint-Germain": "parissg", "Paris SG": "parissg",
        "Saint-Étienne": "stetienne", "Saint-etienne": "stetienne", "Saint-Etienne": "stetienne",
        "Stade Rennais": "rennes",
        "Stade de Reims": "reims",
        "Stade Brestois 29": "brest", "Brest": "brest",
        "FC Lorient": "lorient",
        "FC Metz": "metz",
        "FC Nantes": "nantes",
        "OGC Nice": "nice",
        "Olympique Marseille": "marseille", "Marseille": "marseille",
        "Olympique Lyonnais": "lyon", "Lyon": "lyon",
        "RC Lens": "lens", "Lens": "lens",
        "Lille": "lille", "LOSC Lille": "lille",
        "Montpellier HSC": "montpellier", "Montpellier": "montpellier",
        "RC Strasbourg": "strasbourg", "Strasbourg": "strasbourg",
        "Toulouse FC": "toulouse", "Toulouse": "toulouse",
    },
    "Italia": {
        "AC Milan": "milan",
        "AS Roma": "roma",
        "Hellas Verona": "verona",
        "Internazionale": "inter",
    },
    "Turquia": {
        "Adana Demirspor": "ad.demirspor",
        "Bodrum FK": "bodrumspor",
        "Caykur Rizespor": "rizespor", "Çaykur Rizespor": "rizespor",
        "Fatih Karagümrük": "karagumruk", "Fatih Karagumruk": "karagumruk",
        "Gaziantep FK": "gaziantep",
        "Goztepe": "goztep", "Göztepe": "goztep",
        "Istanbul Basaksehir": "buyuksehyr", "İstanbul Başakşehir": "buyuksehyr",
        "Yeni Malatyaspor": "yenimalatyaspor",
    },
}


def normalize_simple(s):
    return ''.join(c for c in s.lower() if c.isalnum())


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Asegurar columna fecha_fdco
    cols = [r[1] for r in cur.execute("PRAGMA table_info(stats_partido_espn)").fetchall()]
    if "fecha_fdco" not in cols:
        cur.execute("ALTER TABLE stats_partido_espn ADD COLUMN fecha_fdco TEXT")

    # Reset cols
    cur.execute("UPDATE stats_partido_espn SET ht_fdco_norm=NULL, at_fdco_norm=NULL, fecha_fdco=NULL")

    # Aplicar mappings por liga
    for liga, mp in MAPPINGS.items():
        for n, fnorm in mp.items():
            cur.execute("UPDATE stats_partido_espn SET ht_fdco_norm=? WHERE liga=? AND ht=?", (fnorm, liga, n))
            cur.execute("UPDATE stats_partido_espn SET at_fdco_norm=? WHERE liga=? AND at=?", (fnorm, liga, n))
    conn.commit()

    # Fallback normalize_simple
    cur.execute("UPDATE stats_partido_espn SET ht_fdco_norm = LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ht,' ',''),'-',''),'.',''),'(',''),')','')) WHERE ht_fdco_norm IS NULL")
    cur.execute("UPDATE stats_partido_espn SET at_fdco_norm = LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(at,' ',''),'-',''),'.',''),'(',''),')','')) WHERE at_fdco_norm IS NULL")
    conn.commit()

    # fecha_fdco exact match
    cur.execute("UPDATE stats_partido_espn SET fecha_fdco = fecha WHERE EXISTS (SELECT 1 FROM cuotas_historicas_fdco f WHERE f.liga = stats_partido_espn.liga AND f.fecha = stats_partido_espn.fecha AND f.equipo_local_norm = stats_partido_espn.ht_fdco_norm AND f.equipo_visita_norm = stats_partido_espn.at_fdco_norm AND f.cuota_1 IS NOT NULL)")
    conn.commit()

    # LATAM ventana ±1 día
    LATAM = ("Argentina", "Brasil")
    placeholders = "(" + ",".join(["?"]*len(LATAM)) + ")"
    cur.execute(f"UPDATE stats_partido_espn SET fecha_fdco = (SELECT f.fecha FROM cuotas_historicas_fdco f WHERE f.liga = stats_partido_espn.liga AND ABS(julianday(f.fecha) - julianday(stats_partido_espn.fecha)) <= 1 AND f.equipo_local_norm = stats_partido_espn.ht_fdco_norm AND f.equipo_visita_norm = stats_partido_espn.at_fdco_norm AND f.cuota_1 IS NOT NULL LIMIT 1) WHERE fecha_fdco IS NULL AND liga IN {placeholders}", LATAM)
    conn.commit()

    # Re-medir (usar fecha_fdco como join key)
    print("Match-rate post-fix v2 todas ligas (fecha_fdco):")
    print(f"{'liga':<14s}{'stats':>8s}{'matched':>10s}{'pct':>7s}")
    n_total = n_match = 0
    for liga, in cur.execute("SELECT DISTINCT liga FROM stats_partido_espn ORDER BY liga").fetchall():
        ns = cur.execute("SELECT COUNT(*) FROM stats_partido_espn WHERE liga=?", (liga,)).fetchone()[0]
        nm = cur.execute("SELECT COUNT(*) FROM stats_partido_espn s JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha_fdco=f.fecha AND s.ht_fdco_norm=f.equipo_local_norm AND s.at_fdco_norm=f.equipo_visita_norm WHERE s.liga=? AND f.cuota_1 IS NOT NULL", (liga,)).fetchone()[0]
        pct = nm/ns*100 if ns else 0
        n_total += ns; n_match += nm
        print(f"{liga:<14s}{ns:>8d}{nm:>10d}{pct:>6.1f}%")
    print(f"GLOBAL: {n_match}/{n_total} = {n_match/n_total*100:.1f}%")


if __name__ == "__main__":
    main()

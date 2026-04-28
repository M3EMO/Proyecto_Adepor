"""[adepor-5y0] Normaliza nombres de equipos en partidos_no_liga -> historial_equipos_stats canonical.

API-Football devuelve nombres con variantes (sin acentos, sufijos truncados, guiones).
historial_equipos_stats usa nombres canonicos ESPN-style con acentos completos.

Sin esto, el cross-link gap_dias entre fuente liga (ESPN) y fuente copas (API-Football)
falla silenciosamente. Antes de normalizar: 6.5% match. Esperado post-normalizacion: ~95%.

Idempotente: aplica UPDATE solo donde difieren nombres.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'

# --- Aliases por liga ---
# key: nombre que usa API-Football (sin acentos, truncado, etc.)
# value: nombre canonico que usa historial_equipos_stats (ESPN-style)
ALIASES = {
    # ====== ENGLAND ======
    'Tottenham':                 'Tottenham Hotspur',
    'Newcastle':                 'Newcastle United',
    'Brighton':                  'Brighton & Hove Albion',
    'Wolves':                    'Wolverhampton Wanderers',
    'Bournemouth':               'AFC Bournemouth',
    'West Ham':                  'West Ham United',
    'Leicester':                 'Leicester City',
    'Nottingham Forest':         "Nott'm Forest",  # ESPN apostrofe
    'Sheffield Utd':             'Sheffield United',
    'Sheffield Wednesday':       'Sheffield Wednesday',
    'West Brom':                 'West Bromwich Albion',
    'Norwich':                   'Norwich City',
    'Crystal Palace':            'Crystal Palace',
    'Leeds':                     'Leeds United',
    'Aston Villa':               'Aston Villa',
    'Fulham':                    'Fulham',
    'Brentford':                 'Brentford',
    'Everton':                   'Everton',
    'Burnley':                   'Burnley',
    'Southampton':               'Southampton',
    'Watford':                   'Watford',
    'Ipswich':                   'Ipswich Town',

    # ====== ITALY ======
    'Inter':                     'Internazionale',
    'Hellas Verona':             'Verona',
    'Roma':                      'Roma',
    'Lazio':                     'Lazio',
    'AC Milan':                  'AC Milan',  # match
    'Juventus':                  'Juventus',
    'Napoli':                    'Napoli',
    'Atalanta':                  'Atalanta',
    'Fiorentina':                'Fiorentina',
    'Torino':                    'Torino',
    'Bologna':                   'Bologna',
    'Sassuolo':                  'Sassuolo',
    'Udinese':                   'Udinese',
    'Genoa':                     'Genoa',
    'Empoli':                    'Empoli',
    'Lecce':                     'Lecce',
    'Cagliari':                  'Cagliari',
    'Salernitana':               'Salernitana',
    'Frosinone':                 'Frosinone',
    'Spezia':                    'Spezia',
    'Sampdoria':                 'Sampdoria',
    'Cremonese':                 'Cremonese',
    'Monza':                     'Monza',
    'Como':                      'Como',
    'Parma':                     'Parma',
    'Venezia':                   'Venezia',

    # ====== SPAIN ======
    'Atletico Madrid':           'Atlético Madrid',
    'Athletic Club':             'Athletic Bilbao',
    'Real Sociedad':             'Real Sociedad',
    'Sevilla':                   'Sevilla',
    'Valencia':                  'Valencia',
    'Villarreal':                'Villarreal',
    'Real Betis':                'Real Betis',
    'Celta Vigo':                'Celta Vigo',
    'Espanyol':                  'Espanyol',
    'Mallorca':                  'Mallorca',
    'Cadiz':                     'Cádiz',
    'Almeria':                   'Almería',
    'Getafe':                    'Getafe',
    'Osasuna':                   'Osasuna',
    'Granada':                   'Granada',
    'Las Palmas':                'Las Palmas',
    'Alaves':                    'Alavés',
    'Rayo Vallecano':            'Rayo Vallecano',
    'Girona':                    'Girona',
    'Leganes':                   'Leganés',
    'Real Valladolid':           'Real Valladolid',

    # ====== GERMANY ======
    'Bayern München':            'Bayern Munich',  # internal duplicate API
    'Borussia Dortmund':         'Borussia Dortmund',
    'RB Leipzig':                'RB Leipzig',
    'Bayer Leverkusen':          'Bayer Leverkusen',
    'VfB Stuttgart':             'VfB Stuttgart',
    'Borussia Monchengladbach':  'Borussia Mönchengladbach',
    'Eintracht Frankfurt':       'Eintracht Frankfurt',
    'Wolfsburg':                 'Wolfsburg',
    'Hoffenheim':                'Hoffenheim',
    'SC Freiburg':               'Freiburg',
    'Werder Bremen':             'Werder Bremen',
    'Mainz':                     'Mainz 05',
    'FC Augsburg':               'Augsburg',
    'FC Koln':                   'FC Köln',
    'Heidenheim':                'Heidenheim',
    '1. FC Union Berlin':        'Union Berlin',
    '1. FSV Mainz 05':           'Mainz 05',
    'Bochum':                    'Bochum',
    'Hertha Berlin':             'Hertha Berlin',
    'Schalke 04':                'Schalke 04',
    'Darmstadt':                 'Darmstadt',
    'Holstein Kiel':             'Holstein Kiel',
    'St. Pauli':                 'St. Pauli',

    # ====== FRANCE ======
    'Paris Saint Germain':       'Paris Saint-Germain',
    'AS Monaco':                 'Monaco',
    'Marseille':                 'Marseille',
    'Lyon':                      'Lyon',
    'Lille':                     'Lille',
    'Stade Rennais':             'Rennes',
    'Stade de Reims':            'Reims',
    'Brest':                     'Brest',
    'Nice':                      'Nice',
    'Lens':                      'Lens',
    'Nantes':                    'Nantes',
    'Strasbourg':                'Strasbourg',
    'Toulouse':                  'Toulouse',
    'Montpellier':               'Montpellier',
    'Angers':                    'Angers',
    'Auxerre':                   'Auxerre',
    'Le Havre':                  'Le Havre',
    'St Etienne':                'Saint-Étienne',
    'Clermont':                  'Clermont Foot',
    'Lorient':                   'Lorient',
    'Metz':                      'Metz',
    'Troyes':                    'Troyes',

    # ====== TURKEY ======
    'Galatasaray':               'Galatasaray',
    'Fenerbahçe':                'Fenerbahce',
    'Besiktas':                  'Besiktas',
    'Trabzonspor':               'Trabzonspor',
    'Konyaspor':                 'Konyaspor',
    'Antalyaspor':               'Antalyaspor',
    'Basaksehir':                'Istanbul Basaksehir',
    'Adana Demirspor':           'Adana Demirspor',
    'Goztepe':                   'Goztepe',
    'Sivasspor':                 'Sivasspor',
    'Kayserispor':               'Kayserispor',
    'Alanyaspor':                'Alanyaspor',
    'Gaziantep':                 'Gaziantep FK',
    'Hatayspor':                 'Hatayspor',
    'Rizespor':                  'Caykur Rizespor',
    'Pendikspor':                'Pendikspor',
    'Samsunspor':                'Samsunspor',
    'Bodrumspor':                'Bodrum',
    'Eyupspor':                  'Eyupspor',

    # ====== ARGENTINA ======
    # ESPN convention typically uses long names with parens
    # API-Football has variants without:
    'CA River Plate':            'River Plate',  # collapse duplicate
    'Argentinos Jrs':            'Argentinos Juniors',
    'Estudiantes':               'Estudiantes de La Plata',
    'Gimnasia LP':               'Gimnasia La Plata',
    'Independiente':             'Independiente',  # base
    'Racing Club':               'Racing Club',
    'San Lorenzo':               'San Lorenzo',
    'Velez Sarsfield':           'Vélez Sarsfield',
    'Talleres Cordoba':          'Talleres (Córdoba)',
    'Central Cordoba SdE':       'Central Córdoba (Santiago del Estero)',
    'Atletico Tucuman':          'Atlético Tucumán',
    'Union Santa Fe':            'Unión (Santa Fe)',
    'Belgrano Cordoba':          'Belgrano (Córdoba)',
    'Sarmiento Junin':           'Sarmiento (Junín)',
    'Newells Old Boys':          "Newell's Old Boys",
    'Godoy Cruz':                'Godoy Cruz Antonio Tomba',
    'Independiente Rivadavia':   'Independiente Rivadavia',
    'Deportivo Riestra':         'Deportivo Riestra',
    'Instituto Cordoba':         'Instituto (Córdoba)',
    'Banfield':                  'Banfield',
    'Lanus':                     'Lanús',
    'Huracan':                   'Huracán',
    'Defensa y Justicia':        'Defensa y Justicia',
    'Boca Juniors':              'Boca Juniors',
    'River Plate':               'River Plate',
    'Tigre':                     'Tigre',
    'Rosario Central':           'Rosario Central',
    'Platense':                  'Platense',
    'Barracas Central':          'Barracas Central',

    # ====== BRAZIL ======
    'Sao Paulo':                 'São Paulo',
    'Athletico Paranaense':      'Athletico Paranaense',  # con H ESPN
    'Atletico Paranaense':       'Athletico Paranaense',  # API alias
    'Atletico-MG':               'Atlético-MG',
    'Atletico-PR':               'Athletico Paranaense',
    'Cuiaba':                    'Cuiabá',
    'Goias':                     'Goiás',
    'Internacional':             'Internacional',
    'Gremio':                    'Grêmio',
    'Flamengo':                  'Flamengo',
    'Palmeiras':                 'Palmeiras',
    'Corinthians':               'Corinthians',
    'Cruzeiro':                  'Cruzeiro',
    'Bahia':                     'Bahia',
    'Vasco DA Gama':             'Vasco da Gama',
    'Vitoria':                   'Vitória',
    'Botafogo':                  'Botafogo',
    'Ceara':                     'Ceará',
    'Fortaleza EC':              'Fortaleza',
    'Fluminense':                'Fluminense',
    'America Mineiro':           'América-MG',
    'Coritiba':                  'Coritiba',
    'Juventude':                 'Juventude',
    'Bragantino':                'Red Bull Bragantino',
    'Red Bull Bragantino':       'Red Bull Bragantino',
}


def main():
    if not DB.exists():
        print(f"DB no existe: {DB}"); sys.exit(1)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Antes
    n_pre = cur.execute("""
        SELECT COUNT(DISTINCT eq) FROM (
            SELECT equipo_local AS eq FROM partidos_no_liga
            WHERE equipo_local IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
            UNION SELECT equipo_visita FROM partidos_no_liga
            WHERE equipo_visita IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
        )
    """).fetchone()[0]
    n_total = cur.execute("""
        SELECT COUNT(DISTINCT eq) FROM (
            SELECT equipo_local AS eq FROM partidos_no_liga
            UNION SELECT equipo_visita FROM partidos_no_liga
        )
    """).fetchone()[0]
    n_hist = cur.execute("SELECT COUNT(DISTINCT equipo) FROM historial_equipos_stats").fetchone()[0]
    print(f"PRE-norm: {n_pre} matches / {n_total} total ({100*n_pre/n_total:.1f}%)")
    print(f"  vs {n_hist} equipos en historial_equipos_stats")
    print()

    # Aplicar aliases
    print("Aplicando aliases...")
    n_updates_l = 0; n_updates_v = 0
    for src, dst in ALIASES.items():
        if src == dst: continue
        r1 = cur.execute("UPDATE partidos_no_liga SET equipo_local=? WHERE equipo_local=?", (dst, src))
        n_updates_l += r1.rowcount
        r2 = cur.execute("UPDATE partidos_no_liga SET equipo_visita=? WHERE equipo_visita=?", (dst, src))
        n_updates_v += r2.rowcount
    conn.commit()
    print(f"  UPDATE local:   {n_updates_l} filas")
    print(f"  UPDATE visita:  {n_updates_v} filas")
    print()

    # Despues
    n_post = cur.execute("""
        SELECT COUNT(DISTINCT eq) FROM (
            SELECT equipo_local AS eq FROM partidos_no_liga
            WHERE equipo_local IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
            UNION SELECT equipo_visita FROM partidos_no_liga
            WHERE equipo_visita IN (SELECT DISTINCT equipo FROM historial_equipos_stats)
        )
    """).fetchone()[0]
    print(f"POST-norm: {n_post} matches / {n_total} total ({100*n_post/n_total:.1f}%)")
    print(f"  Delta: +{n_post - n_pre} matches")
    print()

    # Cobertura por liga: ¿de los equipos de cada liga, cuantos tienen al menos 1 partido en partidos_no_liga?
    print("Cobertura por liga (equipos con ≥1 partido en copa):")
    rows = cur.execute("""
        SELECT h.liga, COUNT(DISTINCT h.equipo) AS n_total,
               COUNT(DISTINCT CASE WHEN h.equipo IN (
                   SELECT equipo_local FROM partidos_no_liga
                   UNION SELECT equipo_visita FROM partidos_no_liga
               ) THEN h.equipo END) AS n_match
        FROM historial_equipos_stats h
        GROUP BY h.liga ORDER BY h.liga
    """).fetchall()
    for liga, nt, nm in rows:
        pct = 100*nm/nt if nt else 0
        print(f"  {liga:<14} {nm:>3} / {nt:>3} ({pct:>5.1f}%)")

    # Equipos del historial NO matcheados aun (top 30 por # de fechas)
    print()
    print("Top equipos historial SIN match en partidos_no_liga (revisar aliases):")
    rows = cur.execute("""
        SELECT h.equipo, h.liga, COUNT(*) FROM historial_equipos_stats h
        WHERE h.equipo NOT IN (SELECT equipo_local FROM partidos_no_liga)
          AND h.equipo NOT IN (SELECT equipo_visita FROM partidos_no_liga)
        GROUP BY h.equipo, h.liga ORDER BY 3 DESC LIMIT 30
    """).fetchall()
    for eq, l, n in rows: print(f"  {l:<14} {eq:<35} n_fechas={n}")

    conn.close()


if __name__ == "__main__":
    main()

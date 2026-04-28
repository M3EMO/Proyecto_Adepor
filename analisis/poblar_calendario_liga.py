"""adepor-3ip: poblar tabla liga_calendario_temp con calendarios reales
individuales por liga (no template generico).

Cada liga tiene su propio calendario por temporada (formato distinto: anual,
semestral, agost-mayo, etc.). Los rangos son aproximados al inicio/fin oficial
del torneo principal de cada liga.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

CALENDARIOS = [
    # === EUR top: temp ago-may. La 'temp' del motor es el AÑO de cierre. ===
    ("Inglaterra", 2022, "2021-08-13", "2022-05-22", "ago-may", "Premier 21-22"),
    ("Inglaterra", 2023, "2022-08-05", "2023-05-28", "ago-may", "Premier 22-23"),
    ("Inglaterra", 2024, "2023-08-11", "2024-05-19", "ago-may", "Premier 23-24"),
    ("Inglaterra", 2025, "2024-08-16", "2025-05-25", "ago-may", "Premier 24-25"),
    ("Inglaterra", 2026, "2025-08-15", "2026-05-24", "ago-may", "Premier 25-26 en curso"),
    ("Italia", 2022, "2021-08-21", "2022-05-22", "ago-may", "Serie A 21-22"),
    ("Italia", 2023, "2022-08-13", "2023-06-04", "ago-may", "Serie A 22-23"),
    ("Italia", 2024, "2023-08-19", "2024-05-26", "ago-may", "Serie A 23-24"),
    ("Italia", 2025, "2024-08-17", "2025-05-25", "ago-may", "Serie A 24-25"),
    ("Italia", 2026, "2025-08-23", "2026-05-24", "ago-may", "Serie A 25-26 en curso"),
    ("Espana", 2022, "2021-08-13", "2022-05-22", "ago-may", "La Liga 21-22"),
    ("Espana", 2023, "2022-08-12", "2023-06-04", "ago-may", "La Liga 22-23"),
    ("Espana", 2024, "2023-08-11", "2024-05-26", "ago-may", "La Liga 23-24"),
    ("Espana", 2025, "2024-08-15", "2025-05-25", "ago-may", "La Liga 24-25"),
    ("Espana", 2026, "2025-08-15", "2026-05-24", "ago-may", "La Liga 25-26 en curso"),
    ("Francia", 2022, "2021-08-06", "2022-05-21", "ago-may", "Ligue 1 21-22"),
    ("Francia", 2023, "2022-08-05", "2023-06-03", "ago-may", "Ligue 1 22-23"),
    ("Francia", 2024, "2023-08-11", "2024-05-19", "ago-may", "Ligue 1 23-24"),
    ("Francia", 2025, "2024-08-16", "2025-05-17", "ago-may", "Ligue 1 24-25"),
    ("Francia", 2026, "2025-08-15", "2026-05-17", "ago-may", "Ligue 1 25-26 en curso"),
    ("Alemania", 2022, "2021-08-13", "2022-05-14", "ago-may", "Bundesliga 21-22"),
    ("Alemania", 2023, "2022-08-05", "2023-05-27", "ago-may", "Bundesliga 22-23"),
    ("Alemania", 2024, "2023-08-18", "2024-05-18", "ago-may", "Bundesliga 23-24"),
    ("Alemania", 2025, "2024-08-23", "2025-05-17", "ago-may", "Bundesliga 24-25"),
    ("Alemania", 2026, "2025-08-22", "2026-05-16", "ago-may", "Bundesliga 25-26 en curso"),
    ("Turquia", 2022, "2021-08-13", "2022-05-22", "ago-may", "Super Lig 21-22"),
    ("Turquia", 2023, "2022-08-05", "2023-06-04", "ago-may", "Super Lig 22-23"),
    ("Turquia", 2024, "2023-08-11", "2024-05-19", "ago-may", "Super Lig 23-24"),
    ("Turquia", 2025, "2024-08-09", "2025-05-25", "ago-may", "Super Lig 24-25"),
    ("Turquia", 2026, "2025-08-08", "2026-05-24", "ago-may", "Super Lig 25-26 en curso"),

    # === LATAM individual ===
    # Argentina LPF (anual ene/feb-dic). 2026 actual: Apertura empieza ene-feb.
    ("Argentina", 2022, "2022-02-04", "2022-10-25", "feb-oct", "LPF 2022"),
    ("Argentina", 2023, "2023-01-27", "2023-12-04", "ene-dic", "LPF 2023"),
    ("Argentina", 2024, "2024-02-23", "2024-12-08", "feb-dic", "LPF 2024"),
    ("Argentina", 2025, "2025-01-23", "2025-12-14", "ene-dic", "LPF 2025"),
    ("Argentina", 2026, "2026-01-23", "2026-06-22", "ene-jun", "Apertura 2026 en curso"),

    # Brasil Brasileirao (anual abr-dic)
    ("Brasil", 2022, "2022-04-09", "2022-11-13", "abr-nov", "Brasileirao 2022"),
    ("Brasil", 2023, "2023-04-15", "2023-12-06", "abr-dic", "Brasileirao 2023"),
    ("Brasil", 2024, "2024-04-13", "2024-12-08", "abr-dic", "Brasileirao 2024"),
    ("Brasil", 2025, "2025-03-29", "2025-12-21", "mar-dic", "Brasileirao 2025"),
    ("Brasil", 2026, "2026-03-29", "2026-12-21", "mar-dic", "Brasileirao 2026 en curso"),

    # Noruega Eliteserien (mar-nov)
    ("Noruega", 2022, "2022-04-02", "2022-11-13", "abr-nov", "Eliteserien 2022"),
    ("Noruega", 2023, "2023-04-09", "2023-12-03", "abr-dic", "Eliteserien 2023"),
    ("Noruega", 2024, "2024-04-01", "2024-12-01", "abr-dic", "Eliteserien 2024"),
    ("Noruega", 2025, "2025-03-29", "2025-11-30", "mar-nov", "Eliteserien 2025"),
    ("Noruega", 2026, "2026-03-28", "2026-11-30", "mar-nov", "Eliteserien 2026 en curso"),

    # Chile Primera (anual feb-dic)
    ("Chile", 2022, "2022-02-04", "2022-12-04", "feb-dic", "Primera 2022"),
    ("Chile", 2023, "2023-01-22", "2023-12-09", "ene-dic", "Primera 2023"),
    ("Chile", 2024, "2024-02-08", "2024-12-08", "feb-dic", "Primera 2024"),
    ("Chile", 2025, "2025-01-25", "2025-12-06", "ene-dic", "Primera 2025"),
    ("Chile", 2026, "2026-01-25", "2026-12-06", "ene-dic", "Primera 2026 en curso"),

    # Colombia Apertura (ene-jun, semestral)
    ("Colombia", 2022, "2022-01-21", "2022-06-19", "ene-jun", "Apertura 2022"),
    ("Colombia", 2023, "2023-01-27", "2023-06-25", "ene-jun", "Apertura 2023"),
    ("Colombia", 2024, "2024-01-26", "2024-06-23", "ene-jun", "Apertura 2024"),
    ("Colombia", 2025, "2025-01-24", "2025-06-15", "ene-jun", "Apertura 2025"),
    ("Colombia", 2026, "2026-01-24", "2026-06-15", "ene-jun", "Apertura 2026 en curso"),

    # Peru Liga 1 (feb-nov)
    ("Peru", 2022, "2022-01-29", "2022-11-13", "ene-nov", "Liga 1 2022"),
    ("Peru", 2023, "2023-01-21", "2023-11-12", "ene-nov", "Liga 1 2023"),
    ("Peru", 2024, "2024-02-09", "2024-11-10", "feb-nov", "Liga 1 2024"),
    ("Peru", 2025, "2025-02-07", "2025-11-08", "feb-nov", "Liga 1 2025"),
    ("Peru", 2026, "2026-02-07", "2026-11-08", "feb-nov", "Liga 1 2026 en curso"),

    # Ecuador LigaPro (feb-dic)
    ("Ecuador", 2022, "2022-02-25", "2022-12-04", "feb-dic", "LigaPro 2022"),
    ("Ecuador", 2023, "2023-02-17", "2023-12-09", "feb-dic", "LigaPro 2023"),
    ("Ecuador", 2024, "2024-02-23", "2024-12-08", "feb-dic", "LigaPro 2024"),
    ("Ecuador", 2025, "2025-02-14", "2025-12-08", "feb-dic", "LigaPro 2025"),
    ("Ecuador", 2026, "2026-02-14", "2026-12-08", "feb-dic", "LigaPro 2026 en curso"),

    # Bolivia (feb-nov)
    ("Bolivia", 2022, "2022-02-04", "2022-11-30", "feb-nov", "Bolivia 2022"),
    ("Bolivia", 2023, "2023-02-04", "2023-11-30", "feb-nov", "Bolivia 2023"),
    ("Bolivia", 2024, "2024-02-04", "2024-11-30", "feb-nov", "Bolivia 2024"),
    ("Bolivia", 2025, "2025-02-01", "2025-11-30", "feb-nov", "Bolivia 2025"),
    ("Bolivia", 2026, "2026-02-01", "2026-11-30", "feb-nov", "Bolivia 2026 en curso"),

    # Uruguay (feb-dic)
    ("Uruguay", 2022, "2022-02-04", "2022-12-04", "feb-dic", "Uruguay 2022"),
    ("Uruguay", 2023, "2023-02-04", "2023-12-09", "feb-dic", "Uruguay 2023"),
    ("Uruguay", 2024, "2024-02-04", "2024-12-08", "feb-dic", "Uruguay 2024"),
    ("Uruguay", 2025, "2025-02-08", "2025-12-08", "feb-dic", "Uruguay 2025"),
    ("Uruguay", 2026, "2026-02-08", "2026-12-08", "feb-dic", "Uruguay 2026 en curso"),

    # Venezuela (ene-nov)
    ("Venezuela", 2022, "2022-01-22", "2022-11-15", "ene-nov", "Venezuela 2022"),
    ("Venezuela", 2023, "2023-01-21", "2023-11-12", "ene-nov", "Venezuela 2023"),
    ("Venezuela", 2024, "2024-01-26", "2024-11-08", "ene-nov", "Venezuela 2024"),
    ("Venezuela", 2025, "2025-01-25", "2025-11-08", "ene-nov", "Venezuela 2025"),
    ("Venezuela", 2026, "2026-01-25", "2026-11-08", "ene-nov", "Venezuela 2026 en curso"),
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS liga_calendario_temp (
            liga TEXT NOT NULL,
            temp INTEGER NOT NULL,
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT NOT NULL,
            formato TEXT,
            notas TEXT,
            PRIMARY KEY (liga, temp)
        )
    """)
    n = 0
    for c in CALENDARIOS:
        cur.execute("""
            INSERT OR REPLACE INTO liga_calendario_temp
            (liga, temp, fecha_inicio, fecha_fin, formato, notas)
            VALUES (?, ?, ?, ?, ?, ?)
        """, c)
        n += 1
    con.commit()
    print(f"Insertadas {n} entradas")
    print("\n2026 (en curso):")
    for r in cur.execute("SELECT liga, fecha_inicio, fecha_fin, formato FROM liga_calendario_temp WHERE temp=2026 ORDER BY liga"):
        print(f"  {r[0]:<14s} {r[1]} -> {r[2]}  ({r[3]})")
    con.close()


if __name__ == "__main__":
    main()

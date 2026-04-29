"""
[adepor-04p] Cross-validation Elo Adepor vs ClubElo.

Para cada club en mi equipo_nivel_elo con n_partidos>=20, busca su rating ClubElo
en una fecha cercana. Calcula correlation + bias + RMSE.

Si correlation EUR >= 0.85: Adepor Elo razonable.
Si bias sistemático (Adepor < ClubElo en magnitud): K-factor o home_adv requieren
calibración.

[REF: docs/papers/elo_calibracion.md Q3 — ClubElo como ground truth EUR]
"""
from __future__ import annotations
import sqlite3
import sys
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"

# Mapping nombre Adepor (display) -> nombre ClubElo
# ClubElo usa nombres standardizados, distintos al diccionario Adepor
NAME_MAP = {
    "Paris Saint-Germain": "Paris SG",
    "Atlético Madrid": "Atletico",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "AFC Bournemouth": "Bournemouth",
    "Bayern Munich": "Bayern",
    "Bayer Leverkusen": "Leverkusen",
    "Brighton & Hove Albion": "Brighton",
    "Newcastle United": "Newcastle",
    "Tottenham Hotspur": "Tottenham",
    "Real Sociedad": "Sociedad",
    "Borussia Dortmund": "Dortmund",
    "Hellas Verona": "Verona",
    "AS Roma": "Roma",
    "AC Milan": "Milan",
    "Olympique Marsella": "Marseille",
    "Olympique Lyon": "Lyon",
    "Real Betis": "Betis",
    "Athletic Club": "Athletic",
    "Atalanta BC": "Atalanta",
    "Inter": "Inter",  # OK
}


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str

    # Top equipos Adepor (más recientes)
    rows = conn.execute("""
        SELECT equipo_norm, MAX(fecha) as last_fecha
        FROM equipo_nivel_elo
        WHERE n_partidos_acumulados >= 20
        GROUP BY equipo_norm
    """).fetchall()
    print(f"Equipos Adepor con n>=20: {len(rows)}")

    # Para cada uno, buscar Elo final + ClubElo en snapshot 2026
    pairs = []
    for eq_norm, last_fecha in rows:
        elo_adepor = conn.execute("""
            SELECT elo_post FROM equipo_nivel_elo
            WHERE equipo_norm = ? AND fecha = ?
        """, (eq_norm, last_fecha)).fetchone()
        if not elo_adepor:
            continue
        elo_a = elo_adepor[0]

        # Buscar match en clubelo: probar variantes de display
        # Adepor norm 'manchestercity' -> display 'Manchester City' -> clubelo 'Man City'
        # Heurística: buscar clubelo cuyo norm coincida con eq_norm o mappeo manual
        candidatos = list(conn.execute("""
            SELECT club, elo_clubelo, country FROM clubelo_ratings
            WHERE fecha_from >= '2026-04-01'
        """).fetchall())

        # Match por norm
        eq_match = None
        for club, elo_ce, country in candidatos:
            from_norm = "".join(c.lower() for c in club if c.isalnum())
            if from_norm == eq_norm:
                eq_match = (club, elo_ce, country)
                break
        if not eq_match:
            # Probar via NAME_MAP inverso
            for adepor_name, clubelo_name in NAME_MAP.items():
                adepor_norm = "".join(c.lower() for c in adepor_name if c.isalnum())
                if adepor_norm == eq_norm:
                    for club, elo_ce, country in candidatos:
                        if club == clubelo_name:
                            eq_match = (club, elo_ce, country)
                            break
                    break
        if not eq_match:
            continue
        clubelo_name, elo_ce, country = eq_match
        pairs.append({
            "adepor_norm": eq_norm,
            "clubelo_name": clubelo_name,
            "country": country,
            "elo_adepor": round(elo_a, 1),
            "elo_clubelo": round(elo_ce, 1),
            "diff": round(elo_a - elo_ce, 1),
        })

    pairs.sort(key=lambda p: -p["elo_clubelo"])
    print(f"Pares matcheados: {len(pairs)}")

    # Correlation por country
    by_country = defaultdict(list)
    for p in pairs:
        by_country[p["country"]].append(p)

    def corr(xs, ys):
        n = len(xs)
        if n < 3:
            return None
        mx = sum(xs) / n; my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        return num / (dx * dy) if dx > 0 and dy > 0 else None

    print("\n" + "=" * 70)
    print("CORRELATION ADEPOR ELO vs CLUBELO POR PAÍS")
    print("=" * 70)
    for country, ps in sorted(by_country.items(), key=lambda x: -len(x[1])):
        if len(ps) < 3:
            continue
        xs = [p["elo_adepor"] for p in ps]
        ys = [p["elo_clubelo"] for p in ps]
        c = corr(xs, ys)
        bias = sum(p["diff"] for p in ps) / len(ps)
        rmse = math.sqrt(sum(p["diff"] ** 2 for p in ps) / len(ps))
        print(f"  {country:<5s} N={len(ps):>3d}  corr={c:.3f}  bias={bias:+.1f}  RMSE={rmse:.1f}")

    # Top 20 detalle
    print("\nTOP 20 POR ELO CLUBELO:")
    print(f"  {'club_clubelo':<25s} {'pais':<5s} {'adepor':>7s} {'clubelo':>8s} {'diff':>7s}")
    for p in pairs[:20]:
        print(f"  {p['clubelo_name']:<25s} {p['country']:<5s} "
              f"{p['elo_adepor']:>7.1f} {p['elo_clubelo']:>8.1f} {p['diff']:>+7.1f}")

    # Save
    out = {
        "n_pairs": len(pairs),
        "pairs": pairs,
        "by_country": {
            country: {
                "n": len(ps),
                "corr": corr([p["elo_adepor"] for p in ps], [p["elo_clubelo"] for p in ps]),
                "bias": sum(p["diff"] for p in ps) / len(ps),
                "rmse": math.sqrt(sum(p["diff"] ** 2 for p in ps) / len(ps)),
            }
            for country, ps in by_country.items() if len(ps) >= 3
        },
    }
    with open("analisis/comparar_elo_propio_vs_clubelo.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/comparar_elo_propio_vs_clubelo.json")
    conn.close()


if __name__ == "__main__":
    main()

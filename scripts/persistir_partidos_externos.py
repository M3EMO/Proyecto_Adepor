"""Persiste partidos historicos crudos en partidos_historico_externo.

Lee:
  - analisis/cache_espn/*.json (LATAM scrapeado por scraper_espn_historico.py)
  - football-data.co.uk CSVs (EUR, descarga on-the-fly)

Inserta en DB con UPSERT por (liga, temp, fecha, ht, at).
Idempotente: re-correr solo agrega nuevos.
"""
import csv
import io
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
CACHE_ESPN = ROOT / "analisis" / "cache_espn"

# === Fuentes football-data.co.uk para EUR ===
FUENTES_CSV = {
    "Inglaterra": [("2122","E0"),("2223","E0"),("2324","E0"),("2425","E0")],
    "Italia":     [("2122","I1"),("2223","I1"),("2324","I1"),("2425","I1")],
    "Espana":     [("2122","SP1"),("2223","SP1"),("2324","SP1"),("2425","SP1")],
    "Francia":    [("2122","F1"),("2223","F1"),("2324","F1"),("2425","F1")],
    "Alemania":   [("2122","D1"),("2223","D1"),("2324","D1"),("2425","D1")],
    "Turquia":    [("2122","T1"),("2223","T1"),("2324","T1"),("2425","T1")],
    # NORUEGA EXCLUIDO temp 2026-04-26: bug adepor-a0i.
    # football-data.co.uk N1 = Eredivisie holandesa, NO Noruega.
    # Reactivar cuando se identifique codigo correcto Noruega (NN1? o usar API-Football arg.1=103).
    # "Noruega":    [("2223","N1"),("2324","N1"),("2425","N1")],  # WRONG, era Eredivisie
}


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig", errors="ignore")


def parse_csv_temp(texto, codigo):
    """codigo: '2425' -> temp 2024."""
    temp = 2000 + int(codigo[:2])
    rows = []
    reader = csv.DictReader(io.StringIO(texto))
    for r in reader:
        try:
            f = r.get("Date", "")
            if not f:
                continue
            try:
                d = datetime.strptime(f, "%d/%m/%Y")
            except ValueError:
                d = datetime.strptime(f, "%d/%m/%y")
            ht = r.get("HomeTeam", "").strip()
            at = r.get("AwayTeam", "").strip()
            hg, ag = r.get("FTHG", ""), r.get("FTAG", "")
            if not ht or not at or hg == "" or ag == "":
                continue
            rows.append({
                "fecha": d.isoformat() + ":00",
                "ht": ht, "at": at,
                "hg": int(hg), "ag": int(ag),
                "hst": int(r.get("HST", 0) or 0),
                "ast": int(r.get("AST", 0) or 0),
                "hs": int(r.get("HS", 0) or 0),
                "as": int(r.get("AS", 0) or 0),
                "hc": int(r.get("HC", 0) or 0),
                "ac": int(r.get("AC", 0) or 0),
                # Legacy historico extendido (2026-04-26): faltas + tarjetas
                "hf": int(r.get("HF", 0) or 0),
                "af": int(r.get("AF", 0) or 0),
                "hy": int(r.get("HY", 0) or 0),
                "ay": int(r.get("AY", 0) or 0),
                "hr": int(r.get("HR", 0) or 0),
                "ar": int(r.get("AR", 0) or 0),
                "evt_id": None,
                "temp": temp,
            })
        except (ValueError, TypeError):
            continue
    return rows


def insert_partidos(con, liga, fuente, partidos):
    cur = con.cursor()
    inserted = 0
    updated = 0
    skipped = 0
    for p in partidos:
        has_stats = 1 if (p["hs"] != 0 or p["hst"] != 0 or p["hc"] != 0) else 0
        # Faltas/tarjetas (None si no provistas — ej ESPN cache antiguo)
        hf = p.get("hf")
        af = p.get("af")
        hy = p.get("hy")
        ay = p.get("ay")
        hr = p.get("hr")
        ar = p.get("ar")
        try:
            cur.execute("""
                INSERT INTO partidos_historico_externo
                (liga, temp, fecha, fuente, ht, at, hg, ag, hst, ast, hs, as_, hc, ac,
                 has_full_stats, evt_id_externo, hf, af, hy, ay, hr, ar)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (liga, p["temp"], p["fecha"], fuente,
                  p["ht"], p["at"], p["hg"], p["ag"],
                  p["hst"], p["ast"], p["hs"], p["as"],
                  p["hc"], p["ac"], has_stats, p.get("evt_id"),
                  hf, af, hy, ay, hr, ar))
            inserted += 1
        except sqlite3.IntegrityError:
            # Ya existe — UPDATE faltas/tarjetas si las nuevas son no-None y la fila existente las tiene NULL
            if any(x is not None for x in [hf, af, hy, ay, hr, ar]):
                cur.execute("""
                    UPDATE partidos_historico_externo
                    SET hf = COALESCE(hf, ?), af = COALESCE(af, ?),
                        hy = COALESCE(hy, ?), ay = COALESCE(ay, ?),
                        hr = COALESCE(hr, ?), ar = COALESCE(ar, ?)
                    WHERE liga = ? AND temp = ? AND fecha = ? AND ht = ? AND at = ?
                """, (hf, af, hy, ay, hr, ar, liga, p["temp"], p["fecha"], p["ht"], p["at"]))
                if cur.rowcount > 0:
                    updated += 1
                else:
                    skipped += 1
            else:
                skipped += 1
    return inserted, skipped, updated


def main():
    con = sqlite3.connect(DB)
    total_inserted = 0
    total_skipped = 0

    # === 1. ESPN cache (LATAM) ===
    print("=== ESPN cache (LATAM) ===")
    if CACHE_ESPN.exists():
        for f in sorted(CACHE_ESPN.glob("*.json")):
            try:
                liga, temp_str = f.stem.rsplit("_", 1)
                temp = int(temp_str)
            except (ValueError, IndexError):
                continue
            partidos = json.loads(f.read_text(encoding="utf-8"))
            for p in partidos:
                p["temp"] = temp
                # Format fecha: ESPN gives ISO with Z timezone
                fe = p.get("fecha", "")
                if isinstance(fe, str) and "T" in fe:
                    p["fecha"] = fe.replace("T", " ").replace("Z", "")
            ins, skp, upd = insert_partidos(con, liga, "espn-core", partidos)
            print(f"  {liga} {temp}: insertados={ins} updated={upd} duplicados={skp}")
            total_inserted += ins
            total_skipped += skp
        con.commit()
    else:
        print("  cache_espn/ no existe, skipping")

    # === 2. football-data.co.uk CSVs (EUR) ===
    print("\n=== football-data.co.uk CSVs (EUR) ===")
    for liga, urls_codigos in FUENTES_CSV.items():
        for codigo, division_code in urls_codigos:
            url = f"https://www.football-data.co.uk/mmz4281/{codigo}/{division_code}.csv"
            try:
                texto = fetch_csv(url)
            except Exception as e:
                print(f"  [ERROR] {liga} {codigo}: {e}")
                continue
            partidos = parse_csv_temp(texto, codigo)
            ins, skp, upd = insert_partidos(con, liga, "football-data.co.uk", partidos)
            print(f"  {liga} {codigo}: N_csv={len(partidos)} insertados={ins} updated={upd} duplicados={skp}")
            total_inserted += ins
            total_skipped += skp
    con.commit()

    # === Resumen ===
    print(f"\n[OK] Total insertados: {total_inserted}, duplicados ignorados: {total_skipped}")
    cur = con.cursor()
    print("\nResumen por liga:")
    print(f"{'Liga':<13} {'Temps':<10} {'N':>5} {'Stats%':>7}")
    for r in cur.execute("""
        SELECT liga, GROUP_CONCAT(DISTINCT temp) AS temps, COUNT(*) AS n,
               ROUND(100.0 * SUM(has_full_stats) / COUNT(*), 1) AS pct_stats
        FROM partidos_historico_externo
        GROUP BY liga
        ORDER BY liga
    """):
        print(f"{r[0]:<13} {r[1]:<10} {r[2]:>5} {r[3]:>6.1f}%")
    con.close()


if __name__ == "__main__":
    main()

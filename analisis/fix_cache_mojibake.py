"""Arregla mojibake en cache_espn/*.json (UTF-8 mal codificado como Latin-1).
Detecta strings con patrones tipo 'Ã©' (é doble-encoded) y los re-decodifica.
También arregla la tabla stats_partido_espn afectada.
"""
from __future__ import annotations

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
CACHE = ROOT / "analisis" / "cache_espn"
DB = ROOT / "fondo_quant.db"


def fix_mojibake(s: str) -> str:
    """UTF-8 doble-encoded → UTF-8 correcto. Idempotente."""
    if not isinstance(s, str):
        return s
    if "Ã" not in s:
        return s
    try:
        fixed = s.encode("latin-1").decode("utf-8")
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def fix_dict(d: dict) -> dict:
    """Recursivo: arregla todos los strings en dict/list."""
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = fix_mojibake(v)
        elif isinstance(v, dict):
            out[k] = fix_dict(v)
        elif isinstance(v, list):
            out[k] = [fix_dict(x) if isinstance(x, dict) else fix_mojibake(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


def main():
    print("=== Fix mojibake en cache_espn/*.json ===")
    n_files = 0
    n_fixed = 0
    for f in sorted(CACHE.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        # Detectar si tiene mojibake (chars típicos)
        text_blob = json.dumps(data, ensure_ascii=False)
        had_mojibake = "Ã" in text_blob
        fixed_data = [fix_dict(d) if isinstance(d, dict) else d for d in data]
        new_str = json.dumps(fixed_data, ensure_ascii=False, indent=1)
        # Verificar que el fix no haya empeorado las cosas
        new_text_blob = new_str
        new_had_mojibake = "Ã" in new_text_blob
        if had_mojibake and not new_had_mojibake:
            f.write_text(new_str, encoding="utf-8")
            n_fixed += 1
            print(f"  [FIXED] {f.name}")
        elif had_mojibake and new_had_mojibake:
            print(f"  [WARN] {f.name}: still has mojibake after fix")
        n_files += 1
    print(f"\nTotal archivos: {n_files}, fixed: {n_fixed}")

    # Fix DB stats_partido_espn
    print("\n=== Fix mojibake en stats_partido_espn (ht, at) ===")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT liga, temp, fecha, ht, at FROM stats_partido_espn
        WHERE ht LIKE '%Ã%' OR at LIKE '%Ã%'
    """).fetchall()
    print(f"Filas afectadas: {len(rows)}")
    n_db_fixed = 0
    for r in rows:
        liga, temp, fecha, ht, at = r
        ht_new = fix_mojibake(ht)
        at_new = fix_mojibake(at)
        if ht_new != ht or at_new != at:
            # Update PK requires delete + insert
            try:
                cur.execute("""
                    UPDATE stats_partido_espn
                    SET ht=?, at=?
                    WHERE liga=? AND temp=? AND fecha=? AND ht=? AND at=?
                """, (ht_new, at_new, liga, temp, fecha, ht, at))
                n_db_fixed += 1
            except sqlite3.IntegrityError:
                # PK collision (otra fila con los nombres correctos ya existe)
                cur.execute("""
                    DELETE FROM stats_partido_espn
                    WHERE liga=? AND temp=? AND fecha=? AND ht=? AND at=?
                """, (liga, temp, fecha, ht, at))
                n_db_fixed += 1
    con.commit()
    con.close()
    print(f"DB filas fixed/deleted: {n_db_fixed}")


if __name__ == "__main__":
    main()

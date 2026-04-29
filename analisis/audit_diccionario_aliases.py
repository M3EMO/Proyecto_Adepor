"""
[adepor-bug-critico] Audit del diccionario_equipos.json para detectar aliases
auto-aprendidos por la rama fuzzy de gestor_nombres.obtener_nombre_estandar
que mapean equipos DISTINTOS al mismo oficial.

Heurística sospechosos:
1. Alias != normalizar(oficial) (es alias real, no identidad).
2. Similarity(alias, normalizar(oficial)) entre 0.70 y 0.95 (fuzzy zone).
3. Oficial existe en _meta.equipo_a_liga_home con liga DISTINTA a donde está
   el alias persistido (cross-country mapping = sospechoso fuerte).

Output: tabla de aliases sospechosos para review manual.
"""
import json
import difflib
import unicodedata
import re
from pathlib import Path

DIC_PATH = Path("diccionario_equipos.json")


def norm(s):
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFD", str(s).lower().strip())
    sin = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", sin)


def main():
    dic = json.loads(DIC_PATH.read_text(encoding="utf-8"))
    meta = dic.get("_meta", {})
    eq_a_liga = meta.get("equipo_a_liga_home", {})

    sospechosos_fuerte = []  # cross-country o sim baja
    sospechosos_medio = []    # sim 0.70-0.85
    legítimos = []            # sim alta + mismo país

    for liga_key, sub in dic.items():
        if liga_key.startswith("_") or not isinstance(sub, dict):
            continue
        for alias, oficial in sub.items():
            n_alias = norm(alias)
            n_of = norm(oficial)
            if n_alias == n_of:
                # identidad, skip
                continue
            sim = difflib.SequenceMatcher(None, n_alias, n_of).ratio()

            # Verificar liga del oficial via _meta
            liga_oficial = eq_a_liga.get(oficial)
            if isinstance(liga_oficial, list):
                liga_oficial_set = set(liga_oficial)
            elif liga_oficial:
                liga_oficial_set = {liga_oficial}
            else:
                liga_oficial_set = set()

            cross_country = bool(liga_oficial_set) and (liga_key not in liga_oficial_set)

            entry = {
                "liga_persistida": liga_key,
                "alias": alias,
                "oficial": oficial,
                "sim": round(sim, 3),
                "liga_oficial_meta": list(liga_oficial_set),
                "cross_country": cross_country,
            }
            if cross_country and 0.70 <= sim < 0.95:
                sospechosos_fuerte.append(entry)
            elif 0.70 <= sim < 0.85:
                sospechosos_medio.append(entry)
            else:
                legítimos.append(entry)

    print("=" * 70)
    print(f"SOSPECHOSOS FUERTES (cross-country + sim 0.70-0.95): {len(sospechosos_fuerte)}")
    print("=" * 70)
    for s in sorted(sospechosos_fuerte, key=lambda x: -x["sim"])[:30]:
        print(f"  [{s['liga_persistida']:<13s}] '{s['alias']:<25s}' -> '{s['oficial']:<25s}' "
              f"sim={s['sim']}  liga_oficial={s['liga_oficial_meta']}")

    print(f"\nSOSPECHOSOS MEDIOS (sim 0.70-0.85, mismo país): {len(sospechosos_medio)}")
    for s in sorted(sospechosos_medio, key=lambda x: -x["sim"])[:30]:
        print(f"  [{s['liga_persistida']:<13s}] '{s['alias']:<25s}' -> '{s['oficial']:<25s}' "
              f"sim={s['sim']}")

    print(f"\nLEGITIMOS (sim>=0.85 mismo país O sim<0.70 alias verdaderos): {len(legítimos)}")

    # Save
    out = {
        "sospechosos_fuerte": sospechosos_fuerte,
        "sospechosos_medio": sospechosos_medio,
        "n_legitimos": len(legítimos),
    }
    with open("analisis/audit_diccionario_aliases.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/audit_diccionario_aliases.json")


if __name__ == "__main__":
    main()

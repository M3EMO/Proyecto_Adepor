"""
[adepor — audit profundo diccionario v5] Dictamen automático por mapping
basado en heurísticas Q2 de docs/papers/entity_resolution_sports.md.

REGLAS:
1. KEEP: alias claro de oficial conocido (Inter↔Internazionale, AFC Bournemouth↔Bournemouth,
   sufijos comunes FC/AFC/CF/etc).
2. DELETE-cross-country: alias persistido en liga A, oficial está en _meta como liga B!=A.
3. DELETE-discriminator-conflict: alias y oficial tienen DISCRIMINADORES distintos
   (United/City, Tucuman/Huracan, MG/SP, Cordoba/Quito).
4. INVESTIGATE: ambiguo, requiere review humano.

Output: tabla con dictamen por mapping + agrega listado de DELETEs aplicables.

[REF: docs/papers/entity_resolution_sports.md Q2]
"""
import json
import re
import unicodedata
from pathlib import Path

DIC_PATH = Path("diccionario_equipos.json")

# Sufijos/prefijos NO discriminantes (lista del paper Q2)
NON_DISCRIMINANT_TOKENS = {
    "fc", "afc", "ac", "cf", "cd", "sc", "bk", "fk", "ks", "ik", "ofi",
    "club", "athletic", "atletico", "atlético", "real", "deportivo",
    "sporting", "internacional", "calcio", "kf", "ks", "fk", "vfb", "vfl",
    "tsv", "fv", "fortuna", "borussia", "rasen", "ssc", "uc", "us", "rsc",
    "psg", "1899", "1860", "1909", "1903", "fk", "ud",
}

# Discriminadores fuertes (si alias o oficial tiene uno y el otro NO el mismo, pueden ser distintos)
# (esto es heurística: token único en uno pero no en el otro = posible discriminador)
DISCRIMINATING_KEYWORDS = {
    # Ciudades / regiones
    "cordoba", "tucuman", "junin", "mendoza", "corrientes", "rosario",
    "santiagodelestero", "lp", "laplata", "riocuarto",
    "sp", "rj", "mg", "pr", "rs", "pb", "ce", "ba", "go",
    "quito", "guayaquil", "lima", "asuncion", "santiago", "valparaiso",
    "north", "south", "east", "west", "central", "norte", "sur",
    # Sufijos identidad clubes
    "united", "city", "town", "rovers", "wanderers", "albion",
    "munchen", "berlin", "hamburg", "stuttgart", "frankfurt",
    "milan", "milano", "rome", "roma", "torino", "turin",
}


def normalizar_token(s):
    nfkd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def tokens(s):
    """Tokeniza string en palabras alfanuméricas (sin tildes, lower)."""
    s_norm = normalizar_token(s)
    return [t for t in re.split(r"[^a-z0-9]+", s_norm) if t]


def es_alias_de_sufijo(alias, oficial):
    """True si alias y oficial difieren SOLO en tokens no-discriminantes.
    Ej: 'Bournemouth' ↔ 'AFC Bournemouth' (FC quita), 'Inter' ↔ 'Internazionale' (alias)."""
    t_alias = set(tokens(alias))
    t_of = set(tokens(oficial))
    # Diferencia simétrica
    diff = t_alias.symmetric_difference(t_of)
    # Si toda la diff son tokens no-discriminantes → es alias del mismo equipo
    if not diff:
        return True
    return all(t in NON_DISCRIMINANT_TOKENS for t in diff)


def tiene_discriminador_conflicto(alias, oficial):
    """True si alias y oficial tienen discriminadores distintos en la diferencia.
    Ej: 'Atletico Tucuman' vs 'Atletico Huracan' → 'tucuman' vs 'huracan' es conflicto.
    Ej: 'Botafogo SP' vs 'Botafogo' → 'sp' es discriminador en alias, no en oficial."""
    t_alias = set(tokens(alias))
    t_of = set(tokens(oficial))
    only_alias = t_alias - t_of
    only_of = t_of - t_alias
    disc_alias = {t for t in only_alias if t in DISCRIMINATING_KEYWORDS}
    disc_of = {t for t in only_of if t in DISCRIMINATING_KEYWORDS}
    # Si ambos lados tienen discriminadores distintos -> CONFLICTO
    if disc_alias and disc_of and disc_alias != disc_of:
        return True
    # Si solo uno tiene discriminador (otro lado es subnombre) -> POSIBLE conflicto
    if disc_alias and not disc_of:
        return True
    if disc_of and not disc_alias:
        return True
    return False


def main():
    dic = json.loads(DIC_PATH.read_text(encoding="utf-8"))
    meta = dic.get("_meta", {})
    eq_a_liga = meta.get("equipo_a_liga_home", {})

    dictamen = {"KEEP": [], "DELETE_cross_country": [], "DELETE_disc_conflict": [], "INVESTIGATE": []}

    for liga_key, sub in dic.items():
        if liga_key.startswith("_") or not isinstance(sub, dict):
            continue
        for alias, oficial in sub.items():
            n_alias = normalizar_token(alias).replace(" ", "")
            n_of = normalizar_token(oficial).replace(" ", "")
            if n_alias == n_of:
                continue  # identidad, skip

            entry = {
                "liga_persistida": liga_key,
                "alias": alias,
                "oficial": oficial,
            }

            # 1) Cross-country check
            liga_oficial = eq_a_liga.get(oficial)
            if isinstance(liga_oficial, list):
                liga_set = set(liga_oficial)
            elif liga_oficial:
                liga_set = {liga_oficial}
            else:
                liga_set = set()
            if liga_set and liga_key not in liga_set:
                # cross-country
                entry["razon"] = f"oficial pertenece a {liga_set} != {liga_key}"
                dictamen["DELETE_cross_country"].append(entry)
                continue

            # 2) Sufijo común alias → KEEP
            if es_alias_de_sufijo(alias, oficial):
                entry["razon"] = "diff solo en tokens no-discriminantes (FC/AFC/Real/etc.)"
                dictamen["KEEP"].append(entry)
                continue

            # 3) Discriminador conflict
            if tiene_discriminador_conflicto(alias, oficial):
                entry["razon"] = "discriminadores distintos (sufijos region/identidad)"
                dictamen["DELETE_disc_conflict"].append(entry)
                continue

            # 4) Else INVESTIGATE
            entry["razon"] = "no clasifica en KEEP/DELETE auto - review humano"
            dictamen["INVESTIGATE"].append(entry)

    # Reporte
    print("=" * 70)
    print("DICTAMEN POR MAPPING")
    print("=" * 70)
    for cat, items in dictamen.items():
        print(f"\n{cat}: {len(items)}")
        for it in items[:30]:
            print(f"  [{it['liga_persistida']:<13s}] '{it['alias']:<28s}' -> '{it['oficial']:<28s}'  ({it['razon']})")
        if len(items) > 30:
            print(f"  ... ({len(items)-30} más)")

    # Persist
    out = {cat: items for cat, items in dictamen.items()}
    out["_summary"] = {cat: len(items) for cat, items in dictamen.items()}
    Path("analisis/audit_diccionario_dictamen.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/audit_diccionario_dictamen.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/audit_diccionario_dictamen.json")


if __name__ == "__main__":
    main()

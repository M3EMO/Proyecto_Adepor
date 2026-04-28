"""Normalizacion + aliases nombres equipo motor (partidos_backtest) -> ESPN.

Problema: motor escribe nombres en cp1252 sin acentos y lowercase
("Atl�tico-mg", "Uni�n (santa Fe)") mientras ESPN devuelve UTF-8 con
acentos y Title Case ("Atlético-MG", "Unión (Santa Fe)").

Solucion:
  1. normalize_name(s) -> sin acentos, lowercase, espacios colapsados.
  2. ALIASES por liga -> mapping explicito de casos no-resolvibles.

Uso:
  from analisis.aliases_espn import normalize_name, alias_motor_a_espn

  # Match en cache_espn:
  if normalize_name(p_motor.local) == normalize_name(p_espn.ht):
    ...

  # O usar alias explicito si la normalizacion no alcanza:
  espn_name = alias_motor_a_espn(liga, motor_name)
"""
from __future__ import annotations

import re
import sys
import unicodedata

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def normalize_name(s: str) -> str:
    """Devuelve forma canonica: sin acentos, lowercase, espacios colapsados."""
    if not s:
        return ""
    # El char � (U+FFFD replacement) aparece cuando motor escribe cp1252 mal.
    # Reemplazo a '?' para representarlo como wildcard en match flexible.
    s = s.replace("�", "?")
    # Aplicar NFD + filtrar diacritics
    nfkd = unicodedata.normalize("NFKD", s)
    no_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase + colapsar whitespace
    out = no_acentos.lower().strip()
    out = re.sub(r"\s+", " ", out)
    return out


def names_match(motor_name: str, espn_name: str) -> bool:
    """Match flexible motor vs ESPN. True si normalizados coinciden, o si
    motor tiene wildcards `?` (chars no decodificados) que matchean cualquier letra.
    """
    a = normalize_name(motor_name)
    b = normalize_name(espn_name)
    if a == b:
        return True
    if "?" not in a and "?" not in b:
        return False
    # Una de los dos tiene wildcard. Construir regex desde el que tiene `?`.
    if "?" in a:
        pattern, target = a, b
    else:
        pattern, target = b, a
    # Escapar regex chars excepto `?`. El ? va a reemplazar 1 char (Latin extra).
    escaped = re.escape(pattern).replace(r"\?", "[a-zA-Z]")
    return re.fullmatch(escaped, target) is not None


# Aliases POR LIGA: motor_normalizado -> ESPN_canonico (UTF-8 acentos)
# Solo necesario cuando normalize() no alcanza (ej. nombres genuinamente distintos)
ALIASES = {
    "Argentina": {
        # Si el nombre normalizado del motor no matchea con el normalizado de ESPN,
        # mapear explicitamente.
        # Ejemplo: motor='Atletico Tucuman' -> ESPN='Atlético Tucumán' (ya cubierto por normalize)
        # Casos raros que requieren alias explicito:
        "gimnasia mendoza": "Independiente Rivadavia",  # podria ser Gimnasia y Esgrima Mendoza
    },
    "Brasil": {
        "atletico-mg": "Atlético-MG",
        "atletico paranaense": "Athletico Paranaense",
    },
    "Espana": {},
    "Francia": {},
    "Italia": {},
    "Inglaterra": {
        "afc bournemouth": "AFC Bournemouth",  # case
    },
    "Alemania": {},
    "Turquia": {
        "fatih karagumruk": "Fatih Karagumruk",
    },
    "Noruega": {},
    "Bolivia": {}, "Chile": {}, "Colombia": {}, "Ecuador": {},
    "Peru": {}, "Uruguay": {}, "Venezuela": {},
}


def alias_motor_a_espn(liga: str, motor_name: str) -> str | None:
    """Devuelve nombre ESPN canonico para un nombre motor (post-normalize).
    None si no hay alias y la normalizacion debe ser suficiente."""
    n = normalize_name(motor_name)
    return ALIASES.get(liga, {}).get(n)


def _fecha_pm(fecha: str, dias: int) -> str:
    """Devuelve fecha YYYY-MM-DD desplazada en `dias`."""
    from datetime import datetime, timedelta
    d = datetime.strptime(fecha[:10], "%Y-%m-%d")
    return (d + timedelta(days=dias)).strftime("%Y-%m-%d")


def _normalize_no_parens(s: str) -> str:
    """Normalize y remueve TODO contenido en paréntesis. Para fallback laxo."""
    return re.sub(r"\s*\([^)]*\)\s*", "", normalize_name(s)).strip()


def match_partido(liga: str, fecha: str, ht_motor: str, at_motor: str,
                    candidatos_espn: list) -> dict | None:
    """Busca un partido ESPN que matchee con (fecha, ht_motor, at_motor) del motor.

    Estrategia (cascada):
      1. Match exacto fecha + nombres normalizados (con wildcards ?)
      2. Match fecha ±1 dia (zona horaria) + nombres normalizados
      3. Match alias explicito
      4. Match laxo sin paréntesis (Gimnasia Mendoza == Gimnasia (Mendoza))
      5. Match por tokens similares
    """
    fecha_motor = fecha[:10]
    fechas_validas = {fecha_motor, _fecha_pm(fecha_motor, 1), _fecha_pm(fecha_motor, -1)}

    # Aplicar alias si existe
    ht_alias = alias_motor_a_espn(liga, ht_motor)
    at_alias = alias_motor_a_espn(liga, at_motor)

    # Candidatos en fechas ±1 dia
    en_fecha = [c for c in candidatos_espn if (c.get("fecha", "")[:10] in fechas_validas)]

    # 1+2: Match flexible por nombres (incluye wildcards ?)
    for c in en_fecha:
        if names_match(ht_motor, c.get("ht", "")) and names_match(at_motor, c.get("at", "")):
            return c

    # 3: Match con alias
    for c in en_fecha:
        if ht_alias and at_alias:
            if names_match(ht_alias, c.get("ht", "")) and names_match(at_alias, c.get("at", "")):
                return c
        if ht_alias and names_match(ht_alias, c.get("ht", "")) and names_match(at_motor, c.get("at", "")):
            return c
        if at_alias and names_match(ht_motor, c.get("ht", "")) and names_match(at_alias, c.get("at", "")):
            return c

    # 4: Match laxo sin paréntesis
    ht_np = _normalize_no_parens(ht_motor)
    at_np = _normalize_no_parens(at_motor)
    for c in en_fecha:
        ht_e_np = _normalize_no_parens(c.get("ht", ""))
        at_e_np = _normalize_no_parens(c.get("at", ""))
        if ht_np and ht_e_np and ht_np == ht_e_np and at_np == at_e_np:
            return c

    # 5: Fallback tokens similares
    ht_norm = normalize_name(ht_motor)
    at_norm = normalize_name(at_motor)
    for c in en_fecha:
        ht_e = normalize_name(c.get("ht", ""))
        at_e = normalize_name(c.get("at", ""))
        if _tokens_similares(ht_e, ht_norm) and _tokens_similares(at_e, at_norm):
            return c
    return None


def _tokens_similares(a: str, b: str) -> bool:
    """Heuristic: a y b comparten al menos 1 token de >=4 chars."""
    if a == b:
        return True
    tokens_a = {t for t in a.replace("(", " ").replace(")", " ").split() if len(t) >= 4}
    tokens_b = {t for t in b.replace("(", " ").replace(")", " ").split() if len(t) >= 4}
    return len(tokens_a & tokens_b) >= 1


if __name__ == "__main__":
    # Self-test
    cases = [
        ("Atl�tico-mg", "Atlético-MG"),
        ("Uni�n (santa Fe)", "Unión (Santa Fe)"),
        ("Instituto (c�rdoba)", "Instituto (Córdoba)"),
        ("Atletico Tucuman", "Atlético Tucumán"),
        ("San Lorenzo", "San Lorenzo"),
        ("Estudiantes de la Plata", "Estudiantes de La Plata"),
        ("AFC Bournemouth", "AFC Bournemouth"),
        ("Atl�tico Tucum�n", "Atlético Tucumán"),
    ]
    for a, b in cases:
        na = normalize_name(a)
        nb = normalize_name(b)
        m = names_match(a, b)
        print(f"  {a:<35s} -> {na}")
        print(f"  {b:<35s} -> {nb}")
        print(f"    flex_match: {m}")
        print()

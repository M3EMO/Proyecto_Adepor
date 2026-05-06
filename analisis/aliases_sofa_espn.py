"""
Aliases SOFA -> ESPN consolidados y validados manualmente.

Filtros aplicados:
  - Excluido false positive: "mineiro" -> "vitoria" (Brasil) | mineiro = Atlético Mineiro
  - Excluido false positive: "grau" -> "comerciantes unidos" (Perú) | grau = Atlético Grau
  - Excluido false positive: "universidad tecnica de cajamarca" -> "los chankas" | equipos distintos
  - Excluido false positive: "olympique lyonnais" -> "nantes" (Francia) | son distintos
"""
import unicodedata
import re

ALIASES_SOFA_TO_ESPN = {
    'Argentina': {
        'gimnasia y esgrima': 'gimnasia la plata',
        'gimnasia y esgrima mendoza': 'gimnasia mendoza',
        'union de santa fe': 'union',
        'union santa fe': 'union',
        'central cordoba': 'central cordoba santiago del estero',
        'instituto de cordoba': 'instituto',
        'instituto cordoba': 'instituto',
    },
    'Brasil': {
        'athletico': 'athletico paranaense',
    },
    'Bolivia': {
        'cdt real oruro': 'real oruro',
        'universitario': 'universitario de vinto',
        'fc universitario': 'universitario de vinto',
        'club fc universitario': 'universitario de vinto',
        'san antonio': 'san antonio bulo bulo',
        'cd san antonio': 'san antonio bulo bulo',
        'club independiente': 'independiente petrolero',
        'independiente': 'independiente petrolero',
    },
    'Inglaterra': {
        'liverpool fc': 'liverpool',
        'wolverhampton': 'wolverhampton wanderers',
        'bournemouth': 'afc bournemouth',
    },
    'Espana': {
        'deportivo alaves': 'alaves',
        'girona fc': 'girona',
        'levante ud': 'levante',
    },
    'Italia': {
        'milan': 'ac milan',
        'roma': 'as roma',
        'ssc napoli': 'napoli',
    },
    'Alemania': {
        '1. fc heidenheim': '1. fc heidenheim 1846',
        '1. fc koln': 'cologne',
        '1. fsv mainz 05': 'mainz',
        'bayer 04 leverkusen': 'bayer leverkusen',
        'bayern munchen': 'bayern munich',
        "borussia m'gladbach": 'borussia monchengladbach',
        'hamburger sv': 'hamburg sv',
        'sv werder bremen': 'werder bremen',
    },
    'Francia': {
        'le havre': 'le havre ac',
        'olympique de marseille': 'marseille',
        'rc lens': 'lens',
        'rc strasbourg': 'strasbourg',
        'stade brestois': 'brest',
    },
    'Turquia': {
        'basaksehir fk': 'istanbul basaksehir',
        'besiktas jk': 'besiktas',
        'kasmpasa': 'kasimpasa',
    },
    'Noruega': {
        'aalesunds fk': 'aalesund',
        'bod/glimt': 'bodo/glimt',
        'fredrikstad fk': 'fredrikstad',
        'lillestrm sk': 'lillestrom',
        'molde fk': 'molde',
        'rosenborg bk': 'rosenborg',
        'sandefjord fotball': 'sandefjord',
        'sarpsborg 08': 'sarpsborg fk',
        'troms il': 'tromso',
        'valerenga if': 'valerenga',
    },
    'Uruguay': {
        'liverpool uy': 'liverpool',
        'racing de montevideo': 'racing',
        'racing montevideo': 'racing',
        'juventud de las piedras': 'juventud',
        'central espanol': 'central espanol futbol club',
    },
    'Peru': {
        'universitario de deportes': 'universitario',
        'adc juan pablo ii': 'juan pablo ii',
        'ad juan pablo ii': 'juan pablo ii',
        'cd moquegua': 'deportivo moquegua',
        'asociacion deportiva tarma': 'adt',
        'alianza atletico de sullana': 'alianza atletico',
        'los chankas cyc': 'los chankas',
        'cienciano': 'cienciano del cusco',
        'club atletico grau': 'atletico grau',
        'club sporting cristal': 'sporting cristal',
        'moquegua': 'deportivo moquegua',
    },
    'Ecuador': {
        'universidad catolica del ecuador': 'universidad catolica',
        'liga deportiva universitaria de quito': 'liga de quito',
        'ldu': 'liga de quito',
        'leones del norte': 'leones',
        'mushuc runa sc': 'mushuc runa',
        'orense sc': 'orense',
        'manta fc': 'manta',
        'manta': 'manta f.c.',
        'guayaquil city': 'guayaquil city fc',
        'barcelona sc guayaquil': 'barcelona sc',
    },
    'Venezuela': {
        'caracas f.c.': 'caracas fc',
        'caracas fc': 'caracas',
        'trujillanos fc': 'trujillanos',
        'monagas': 'monagas sc',
        'metropolitanos': 'metropolitanos fc',
        'anzoategui fc': 'academia anzoategui',
        'carabobo': 'carabobo fc',
        'portuguesa fc': 'portuguesa',
    },
    'Chile': {},
    'Colombia': {},
}


def norm_team_name(s, liga=None):
    """Normalización agresiva con aliases per liga."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', errors='ignore').decode().lower().strip()
    for prefix in ('club atletico ', 'ca ', 'cd ', 'club ', 'fc ', 'sc ', 'atletico ', 'atl ', 'atl. '):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = re.sub(r'\([^)]*\)', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    if liga and liga in ALIASES_SOFA_TO_ESPN:
        return ALIASES_SOFA_TO_ESPN[liga].get(s, s)
    return s


def get_match_key(liga, fecha, ht, at):
    """Devuelve key tuple para matching SOFA <-> ESPN."""
    return (liga, fecha, norm_team_name(ht, liga), norm_team_name(at, liga))


def buscar_match_robusto(liga, fecha, sht, sat, espn_idx, espn_by_liga_fecha,
                         tol_dias=2, fuzzy_thr=0.70):
    """Match robusto SOFA -> ESPN con fallbacks:
      1. Strict por (liga, fecha, ht_norm, at_norm)
      2. Fechas ±N días (zona horaria)
      3. Fuzzy: misma fecha+liga, similarity > thr en ambos nombres
    Devuelve ESPN row o None.
    """
    from datetime import datetime, timedelta
    from difflib import SequenceMatcher

    sht_n = norm_team_name(sht, liga)
    sat_n = norm_team_name(sat, liga)

    # 1. Strict
    if (liga, fecha, sht_n, sat_n) in espn_idx:
        return espn_idx[(liga, fecha, sht_n, sat_n)]

    # 2. ±tol_dias
    try:
        d0 = datetime.fromisoformat(fecha).date()
        for delta in range(-tol_dias, tol_dias + 1):
            if delta == 0:
                continue
            f_alt = (d0 + timedelta(days=delta)).isoformat()
            if (liga, f_alt, sht_n, sat_n) in espn_idx:
                return espn_idx[(liga, f_alt, sht_n, sat_n)]
    except (ValueError, TypeError):
        pass

    # 3. Fuzzy fallback: misma fecha (±tol_dias), liga, fuzzy thr
    try:
        d0 = datetime.fromisoformat(fecha).date()
        candidatos = []
        for delta in range(-tol_dias, tol_dias + 1):
            f_alt = (d0 + timedelta(days=delta)).isoformat()
            candidatos.extend(espn_by_liga_fecha.get((liga, f_alt), []))
        if candidatos:
            best = None
            best_sim = 0
            for ec in candidatos:
                sim = (SequenceMatcher(None, sht_n, norm_team_name(ec[2], liga)).ratio() +
                       SequenceMatcher(None, sat_n, norm_team_name(ec[3], liga)).ratio()) / 2
                if sim > best_sim:
                    best_sim = sim
                    best = ec
            if best and best_sim >= fuzzy_thr:
                return best
    except (ValueError, TypeError):
        pass
    return None

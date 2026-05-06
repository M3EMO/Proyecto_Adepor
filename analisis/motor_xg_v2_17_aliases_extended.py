"""
Aliases SOFA->ESPN extended + re-test matching.

Cubre: Brasil, Argentina, Inglaterra, Bolivia, Uruguay, Peru, Ecuador, Venezuela.
"""
import sqlite3
import sys
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timedelta

DB = 'fondo_quant.db'

ALIASES_SOFA_TO_ESPN = {
    'Argentina': {
        'gimnasia y esgrima': 'gimnasia la plata',
        'gimnasia y esgrima mendoza': 'gimnasia mendoza',
        'union de santa fe': 'union santa fe',
        'union santa fe': 'union',
        'central cordoba': 'central cordoba santiago del estero',
        'instituto de cordoba': 'instituto',
        'instituto cordoba': 'instituto',
    },
    'Brasil': {
        'athletico': 'athletico paranaense',
        'atletico mineiro': 'atletico mg',
    },
    'Inglaterra': {
        'liverpool fc': 'liverpool',
        'wolverhampton': 'wolverhampton wanderers',
        'bournemouth': 'afc bournemouth',
    },
    'Bolivia': {
        'cdt real oruro': 'real oruro',
        'cdt real oruro': 'real oruro',
        'universitario': 'universitario de vinto',
        'fc universitario': 'universitario de vinto',
        'club fc universitario': 'universitario de vinto',
        'san antonio': 'san antonio bulo bulo',
        'cd san antonio': 'san antonio bulo bulo',
        'club independiente': 'independiente petrolero',
        'independiente': 'independiente petrolero',
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
        'sport boys': 'sport boys',  # already same
        'club sporting cristal': 'sporting cristal',
    },
    'Ecuador': {
        'universidad catolica del ecuador': 'universidad catolica',
        'liga deportiva universitaria de quito': 'liga de quito',
        'ldu': 'liga de quito',
        'leones del norte': 'leones',
        'mushuc runa sc': 'mushuc runa',
        'orense sc': 'orense',
        'manta fc': 'manta f.c.',
        'manta fc': 'manta',
        'guayaquil city': 'guayaquil city fc',
        'guayaquil city fc': 'guayaquil city',
        'barcelona sc guayaquil': 'barcelona sc',
        'libertad': 'libertad',
    },
    'Venezuela': {
        'caracas f.c.': 'caracas fc',
        'caracas fc': 'caracas',
        'trujillanos fc': 'trujillanos',
        'monagas': 'monagas sc',
        'monagas sc': 'monagas',
        'estudiantes de merida': 'estudiantes de merida',
        'metropolitanos': 'metropolitanos fc',
        'metropolitanos fc': 'metropolitanos',
        'anzoategui fc': 'academia anzoategui',
        'academia anzoategui': 'anzoategui',
        'carabobo': 'carabobo fc',
        'carabobo fc': 'carabobo',
    },
}


def norm(s, liga=None):
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


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    espn = cur.execute('SELECT liga, fecha, ht, at FROM stats_partido_espn').fetchall()
    sofa = cur.execute('SELECT liga, fecha, ht, at FROM sofascore_match_features WHERE error IS NULL').fetchall()

    # Index ESPN both directions (with and without aliases)
    espn_idx = {}
    espn_by_liga_fecha = defaultdict(list)
    for r in espn:
        liga, fecha, ht, at = r
        ht_n = norm(ht, liga)
        at_n = norm(at, liga)
        espn_idx[(liga, fecha, ht_n, at_n)] = r
        espn_by_liga_fecha[(liga, fecha)].append(r)

    print('='*80)
    print('MATCHING SOFA vs ESPN — con aliases EXTENDED')
    print('='*80)

    matched = defaultdict(int)
    matched_by_alias = defaultdict(int)
    matched_by_date_tol = defaultdict(int)
    no_match = defaultdict(int)
    total = defaultdict(int)

    for s in sofa:
        liga, fecha, sht, sat = s
        total[liga] += 1
        sht_n = norm(sht, liga)
        sat_n = norm(sat, liga)
        # Strict
        if (liga, fecha, sht_n, sat_n) in espn_idx:
            matched[liga] += 1
            matched_by_alias[liga] += 1
            continue
        # ±1 día
        try:
            d0 = datetime.fromisoformat(fecha).date()
            for delta in (-1, 1, -2, 2):
                f_alt = (d0 + timedelta(days=delta)).isoformat()
                if (liga, f_alt, sht_n, sat_n) in espn_idx:
                    matched[liga] += 1
                    matched_by_date_tol[liga] += 1
                    break
            else:
                no_match[liga] += 1
        except (ValueError, TypeError):
            no_match[liga] += 1

    print(f'{"liga":<12s} {"sofa_N":>7s} {"matched":>8s} {"strict":>7s} {"date_tol":>9s} {"sin_match":>10s} {"tasa":>7s}')
    total_sofa = 0
    total_match = 0
    for liga in sorted(total.keys(), key=lambda l: -total[l]):
        t = total[liga]
        m = matched[liga]
        ma = matched_by_alias[liga]
        md = matched_by_date_tol[liga]
        nm = no_match[liga]
        total_sofa += t
        total_match += m
        print(f'{liga:<12s} {t:>7d} {m:>8d} {ma:>7d} {md:>9d} {nm:>10d} {100*m/max(t,1):>6.1f}%')
    print(f'{"-"*60}')
    print(f'{"TOTAL":<12s} {total_sofa:>7d} {total_match:>8d} {"":>7s} {"":>9s} {"":>10s} {100*total_match/max(total_sofa,1):>6.1f}%')


if __name__ == '__main__':
    main()

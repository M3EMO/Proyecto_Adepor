"""
Diagnostico del matching SofaScore <-> stats_partido_espn.

Para cada liga:
  1. Listar partidos SOFA sin match con ESPN (key estricto + ±1 día tolerancia)
  2. Para cada uno, encontrar candidato ESPN más cercano por (liga, fecha ±3, fuzzy nombres)
  3. Output: tabla de pares "SOFA vs ESPN candidato" para que humano valide aliases

Causas posibles del low match:
  A) Diferencia de fechas (zona horaria ESPN vs SOFA)
  B) Aliases nombres no en diccionario
  C) ESPN simplemente no scrapeó esos partidos
"""

import sqlite3
import sys
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher

DB = 'fondo_quant.db'

ALIASES_SOFA_TO_ESPN = {
    'Argentina': {
        'gimnasia y esgrima': 'gimnasia la plata',
        'gimnasia y esgrima mendoza': 'gimnasia mendoza',
        'union de santa fe': 'union santa fe',
        'central cordoba': 'central cordoba santiago del estero',
        'instituto de cordoba': 'instituto cordoba',
    },
    'Brasil': {},
    'Peru': {},
    'Bolivia': {},
    'Venezuela': {},
    'Ecuador': {},
    'Uruguay': {},
    'Inglaterra': {},
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


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    espn_all = cur.execute('SELECT liga, fecha, ht, at FROM stats_partido_espn').fetchall()
    sofa_all = cur.execute('SELECT liga, fecha, ht, at FROM sofascore_match_features WHERE error IS NULL').fetchall()

    # Index ESPN
    espn_by_liga_fecha = defaultdict(list)
    espn_idx_strict = {}
    for r in espn_all:
        liga, fecha, ht, at = r
        espn_by_liga_fecha[(liga, fecha)].append(r)
        espn_idx_strict[(liga, fecha, norm(ht, liga), norm(at, liga))] = r

    print('='*100)
    print('DIAGNOSTICO MATCHING SOFA vs ESPN')
    print('='*100)

    aliases_sugeridos = defaultdict(list)
    sin_overlap = defaultdict(list)

    for liga in ('Brasil', 'Argentina', 'Inglaterra', 'Bolivia', 'Uruguay', 'Peru', 'Ecuador', 'Venezuela'):
        print(f'\n[{liga}]')
        sofa_liga = [r for r in sofa_all if r[0] == liga]
        no_match = []
        for s in sofa_liga:
            l, f, sht, sat = s
            sht_n = norm(sht, l)
            sat_n = norm(sat, l)
            # 1. Strict match
            if (l, f, sht_n, sat_n) in espn_idx_strict:
                continue
            # 2. ±1 día
            try:
                d0 = datetime.fromisoformat(f).date()
                fuente = None
                for delta in (-1, 1):
                    f_alt = (d0 + timedelta(days=delta)).isoformat()
                    if (l, f_alt, sht_n, sat_n) in espn_idx_strict:
                        fuente = f_alt
                        break
                if fuente:
                    continue
            except (ValueError, TypeError):
                pass
            # No match — buscar candidato ESPN cercano (±3 días, fuzzy)
            try:
                d0 = datetime.fromisoformat(f).date()
                espn_candidates = []
                for delta in range(-3, 4):
                    f_alt = (d0 + timedelta(days=delta)).isoformat()
                    espn_candidates.extend(espn_by_liga_fecha.get((l, f_alt), []))
                if not espn_candidates:
                    sin_overlap[liga].append(s)
                    no_match.append((s, None, 0))
                    continue
                # Best match by sim
                best = None
                best_sim = 0
                for ec in espn_candidates:
                    sim = (similarity(sht_n, norm(ec[2], l)) + similarity(sat_n, norm(ec[3], l))) / 2
                    if sim > best_sim:
                        best_sim = sim
                        best = ec
                no_match.append((s, best, best_sim))
            except (ValueError, TypeError):
                sin_overlap[liga].append(s)
                no_match.append((s, None, 0))

        # Mostrar top 5 candidates plausibles (sim > 0.6)
        no_match_with_cand = [n for n in no_match if n[1] and n[2] > 0.6]
        no_match_no_cand = [n for n in no_match if not n[1] or n[2] <= 0.6]
        n_no_match = len(no_match)
        n_overlap_zero = len(sin_overlap[liga])
        print(f'  Sofa={len(sofa_liga)} | sin_match={n_no_match} | sin_overlap_temporal={n_overlap_zero}')
        if no_match_with_cand:
            print(f'  -- Posibles aliases (sim > 0.6) --')
            mostrados = set()
            for s, ec, sim in no_match_with_cand[:10]:
                key = (norm(s[2], liga), norm(ec[2], liga), norm(s[3], liga), norm(ec[3], liga))
                if key in mostrados:
                    continue
                mostrados.add(key)
                print(f'    [sim {sim:.2f}] SOFA "{s[2]}" vs "{s[3]}" ({s[1]})')
                print(f'                  ESPN "{ec[2]}" vs "{ec[3]}" ({ec[1]})')
                # Sugerir alias
                if norm(s[2], liga) != norm(ec[2], liga):
                    aliases_sugeridos[liga].append((norm(s[2], liga), norm(ec[2], liga)))
                if norm(s[3], liga) != norm(ec[3], liga):
                    aliases_sugeridos[liga].append((norm(s[3], liga), norm(ec[3], liga)))

    # === Resumen aliases sugeridos ===
    print('\n' + '='*100)
    print('ALIASES SUGERIDOS (consolidado)')
    print('='*100)
    for liga, pairs in aliases_sugeridos.items():
        if not pairs:
            continue
        unique = list(set(pairs))
        print(f'\n[{liga}] {len(unique)} aliases sugeridos:')
        for sn, en in unique[:20]:
            print(f'  "{sn}" -> "{en}"')

    # === Sin overlap temporal ===
    print('\n' + '='*100)
    print('SIN OVERLAP TEMPORAL (ESPN no tiene fechas cercanas)')
    print('='*100)
    for liga, evs in sin_overlap.items():
        print(f'\n[{liga}] {len(evs)} partidos SOFA sin overlap ESPN ±3 días:')
        for e in evs[:5]:
            print(f'  {e[1]} {e[2]} vs {e[3]}')


if __name__ == '__main__':
    main()

"""
Diagnóstico exhaustivo matching SOFA <-> ESPN para subir a 70%+.

Análisis de los unmatched restantes:
  1. Por qué no matchea (alias missing? gap temporal ESPN? formato fecha?)
  2. Sugerir aliases nuevos
"""
import sqlite3
import sys
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher

sys.path.insert(0, '.')

DB = 'fondo_quant.db'

# Aliases v2 - los que ya teníamos
ALIASES_SOFA_TO_ESPN = {
    'Argentina': {'gimnasia y esgrima':'gimnasia la plata','gimnasia y esgrima mendoza':'gimnasia mendoza','union de santa fe':'union','union santa fe':'union','central cordoba':'central cordoba santiago del estero','instituto de cordoba':'instituto','instituto cordoba':'instituto'},
    'Brasil': {'athletico':'athletico paranaense'},
    'Inglaterra': {'liverpool fc':'liverpool','wolverhampton':'wolverhampton wanderers','bournemouth':'afc bournemouth'},
    'Bolivia': {'cdt real oruro':'real oruro','universitario':'universitario de vinto','san antonio':'san antonio bulo bulo','cd san antonio':'san antonio bulo bulo','club independiente':'independiente petrolero','independiente':'independiente petrolero'},
    'Uruguay': {'liverpool uy':'liverpool','racing de montevideo':'racing','juventud de las piedras':'juventud','central espanol':'central espanol futbol club'},
    'Peru': {'universitario de deportes':'universitario','adc juan pablo ii':'juan pablo ii','cd moquegua':'deportivo moquegua','asociacion deportiva tarma':'adt','alianza atletico de sullana':'alianza atletico','los chankas cyc':'los chankas','cienciano':'cienciano del cusco','club atletico grau':'atletico grau','club sporting cristal':'sporting cristal'},
    'Ecuador': {'universidad catolica del ecuador':'universidad catolica','liga deportiva universitaria de quito':'liga de quito','ldu':'liga de quito','leones del norte':'leones','mushuc runa sc':'mushuc runa','orense sc':'orense','manta fc':'manta','barcelona sc guayaquil':'barcelona sc'},
    'Venezuela': {'caracas f.c.':'caracas fc','caracas fc':'caracas','trujillanos fc':'trujillanos','monagas':'monagas sc','metropolitanos':'metropolitanos fc','anzoategui fc':'academia anzoategui','carabobo':'carabobo fc'},
}


def norm(s, liga=None):
    if not s: return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', errors='ignore').decode().lower().strip()
    for prefix in ('club atletico ', 'ca ', 'cd ', 'club ', 'fc ', 'sc ', 'atletico ', 'atl ', 'atl. '):
        if s.startswith(prefix): s = s[len(prefix):]
    s = re.sub(r'\([^)]*\)', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    if liga and liga in ALIASES_SOFA_TO_ESPN:
        return ALIASES_SOFA_TO_ESPN[liga].get(s, s)
    return s


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    espn_all = cur.execute('SELECT liga, fecha, ht, at FROM stats_partido_espn').fetchall()
    sofa_all = cur.execute('SELECT liga, fecha, ht, at FROM sofascore_match_features WHERE error IS NULL').fetchall()

    espn_by_liga_fecha = defaultdict(list)
    espn_idx = {}
    for r in espn_all:
        liga, fecha, ht, at = r
        espn_by_liga_fecha[(liga, fecha)].append(r)
        espn_idx[(liga, fecha, norm(ht, liga), norm(at, liga))] = r

    print('='*80)
    print('DIAGNOSTICO EXHAUSTIVO matching')
    print('='*80)

    NEW_ALIASES = defaultdict(set)

    for liga in sorted({r[0] for r in sofa_all}):
        sofa_liga = [r for r in sofa_all if r[0] == liga]
        no_match = []
        for s in sofa_liga:
            l, f, sht, sat = s
            sht_n = norm(sht, l)
            sat_n = norm(sat, l)
            # Strict match
            if (l, f, sht_n, sat_n) in espn_idx:
                continue
            # +/-2 dias
            try:
                d0 = datetime.fromisoformat(f).date()
                found = False
                for delta in range(-2, 3):
                    f_alt = (d0 + timedelta(days=delta)).isoformat()
                    if (l, f_alt, sht_n, sat_n) in espn_idx:
                        found = True
                        break
                if found: continue
                # No match — buscar fuzzy +/-3 dias
                cands = []
                for delta in range(-3, 4):
                    f_alt = (d0 + timedelta(days=delta)).isoformat()
                    cands.extend(espn_by_liga_fecha.get((l, f_alt), []))
                if cands:
                    best = None; best_sim = 0
                    for ec in cands:
                        sim = (SequenceMatcher(None, sht_n, norm(ec[2], l)).ratio() +
                               SequenceMatcher(None, sat_n, norm(ec[3], l)).ratio()) / 2
                        if sim > best_sim:
                            best_sim = sim
                            best = ec
                    if best and best_sim > 0.60:
                        # Sugerir aliases
                        if norm(s[2], l) != norm(best[2], l):
                            NEW_ALIASES[l].add((norm(s[2], l), norm(best[2], l)))
                        if norm(s[3], l) != norm(best[3], l):
                            NEW_ALIASES[l].add((norm(s[3], l), norm(best[3], l)))
                        no_match.append((s, best, best_sim))
                else:
                    no_match.append((s, None, 0))  # gap temporal ESPN
            except (ValueError, TypeError):
                no_match.append((s, None, 0))

        gap_temporal = sum(1 for _, c, _ in no_match if c is None)
        sin_alias = sum(1 for _, c, sim in no_match if c is not None and sim > 0.60)

        n_match_ahora = len(sofa_liga) - len(no_match)
        print(f'\n[{liga}] sofa={len(sofa_liga)} match_actual={n_match_ahora} ({100*n_match_ahora/len(sofa_liga):.0f}%) | gap_temporal={gap_temporal} | aliases_pendientes={sin_alias}')

    # ===== Aliases consolidados =====
    print('\n' + '='*80)
    print('NUEVOS ALIASES SUGERIDOS (consolidado)')
    print('='*80)
    for liga, pairs in NEW_ALIASES.items():
        if not pairs: continue
        print(f'\n[{liga}] {len(pairs)} aliases adicionales:')
        for sn, en in sorted(pairs):
            print(f'    "{sn}" -> "{en}",')


if __name__ == '__main__':
    main()

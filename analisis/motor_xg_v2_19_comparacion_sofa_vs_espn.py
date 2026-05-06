"""
Comparación cuantitativa xG SOFA vs xG ESPN V0 productivo.

Para cada partido en sofascore_match_features:
  - xG_SOFA: suma del shotmap calculada por nuestro xG model (motor_xg_v2_14)
  - xG_ESPN_V0: β·SOT + 0.010·shots_off + coef_c·corners (motor productivo)

Comparar:
  - Por equipo: avg xG_SOFA vs avg xG_ESPN
  - Por liga: avg + diferencia
  - Por país (= liga acá)
  - Distribución de la diferencia
  - Correlación entre ambas
"""

import sqlite3
import sys
import unicodedata
import re
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np

DB = 'fondo_quant.db'

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

    # Beta_sot per liga
    beta_sot = {'global': 0.352}
    for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='beta_sot' AND tipo='float'"):
        beta_sot[r[0]] = float(r[1])
    coef_corner = {}
    for r in cur.execute("SELECT liga, coef_corner_calculado FROM ligas_stats"):
        if r[1] is not None: coef_corner[r[0]] = float(r[1])

    # SOFA con xg_shotmap
    sofa = cur.execute('''
        SELECT liga, fecha, ht, at, hg, ag, xg_shotmap_l, xg_shotmap_v
        FROM sofascore_match_features
        WHERE error IS NULL AND xg_shotmap_l IS NOT NULL
    ''').fetchall()
    print(f'Partidos SOFA con xg_shotmap: {len(sofa)}')

    # ESPN index
    espn_rows = cur.execute('''
        SELECT liga, fecha, ht, at, hg, ag, hst, ast, hs, as_v, hc, ac
        FROM stats_partido_espn
        WHERE hst IS NOT NULL AND ast IS NOT NULL
    ''').fetchall()
    espn_idx = {}
    for r in espn_rows:
        liga, fecha, ht, at = r[0], r[1], r[2], r[3]
        espn_idx[(liga, fecha, norm(ht, liga), norm(at, liga))] = r

    # Match
    matched = []
    for s in sofa:
        liga, fecha, sht, sat, hg, ag, xg_l, xg_v = s
        sht_n = norm(sht, liga)
        sat_n = norm(sat, liga)
        # Try fechas ±1
        for delta in (0, -1, 1):
            try:
                f = (datetime.fromisoformat(fecha) + timedelta(days=delta)).date().isoformat()
                key = (liga, f, sht_n, sat_n)
                if key in espn_idx:
                    e = espn_idx[key]
                    matched.append((s, e))
                    break
            except (ValueError, TypeError):
                pass

    print(f'Matched con ESPN: {len(matched)}')

    # ========== Calcular xG ESPN V0 + xG SOFA por evento ==========
    eventos = []  # (liga, equipo, xg_espn, xg_sofa, goles_real)
    for s, e in matched:
        liga = s[0]
        beta = beta_sot.get(liga, beta_sot['global'])
        coef_c = coef_corner.get(liga, 0.03)
        # Local
        sot_l = e[6] or 0
        shots_off_l = max(0, (e[8] or 0) - (e[6] or 0))
        corners_l = e[10] or 0
        xg_espn_l = beta * sot_l + 0.010 * shots_off_l + coef_c * corners_l
        eventos.append({'liga':liga, 'equipo':e[2], 'xg_espn':xg_espn_l, 'xg_sofa':s[6], 'goles':e[4]})
        # Visita
        sot_v = e[7] or 0
        shots_off_v = max(0, (e[9] or 0) - (e[7] or 0))
        corners_v = e[11] or 0
        xg_espn_v = beta * sot_v + 0.010 * shots_off_v + coef_c * corners_v
        eventos.append({'liga':liga, 'equipo':e[3], 'xg_espn':xg_espn_v, 'xg_sofa':s[7], 'goles':e[5]})

    print(f'Eventos: {len(eventos)}')

    # ========== Por liga ==========
    print('\n[1] xG promedios por liga (SOFA vs ESPN V0)')
    print(f'{"liga":<12s} {"N_eve":>6s} {"avg_xg_sofa":>12s} {"avg_xg_espn":>12s} {"avg_goles":>10s} {"diff_sofa-espn":>15s} {"corr_sofa_espn":>15s} {"corr_sofa_g":>12s} {"corr_espn_g":>12s}')
    by_liga = defaultdict(list)
    for ev in eventos:
        by_liga[ev['liga']].append(ev)
    by_liga_stats = {}
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        evs = by_liga[liga]
        if len(evs) < 10: continue
        xg_sofa = np.array([e['xg_sofa'] for e in evs])
        xg_espn = np.array([e['xg_espn'] for e in evs])
        goles = np.array([e['goles'] for e in evs])
        avg_sofa = xg_sofa.mean()
        avg_espn = xg_espn.mean()
        avg_g = goles.mean()
        diff = avg_sofa - avg_espn
        corr_se = np.corrcoef(xg_sofa, xg_espn)[0,1]
        corr_sg = np.corrcoef(xg_sofa, goles)[0,1]
        corr_eg = np.corrcoef(xg_espn, goles)[0,1]
        print(f'{liga:<12s} {len(evs):>6d} {avg_sofa:>12.3f} {avg_espn:>12.3f} {avg_g:>10.3f} {diff:>+15.3f} {corr_se:>+15.3f} {corr_sg:>+12.3f} {corr_eg:>+12.3f}')
        by_liga_stats[liga] = {'n':len(evs), 'avg_sofa':float(avg_sofa), 'avg_espn':float(avg_espn), 'avg_goles':float(avg_g), 'diff':float(diff), 'corr_se':float(corr_se), 'corr_sg':float(corr_sg), 'corr_eg':float(corr_eg)}

    # ========== Calidad predictiva: |xg - goles| ==========
    print('\n[2] Error absoluto promedio (sin EMA, partido individual): SOFA vs ESPN')
    print(f'{"liga":<12s} {"N":>5s} {"MAE_sofa":>10s} {"MAE_espn":>10s} {"D":>8s} {"sofa_better%":>14s}')
    for liga in sorted(by_liga.keys(), key=lambda l: -len(by_liga[l])):
        evs = by_liga[liga]
        if len(evs) < 10: continue
        mae_sofa = np.mean([abs(e['xg_sofa']-e['goles']) for e in evs])
        mae_espn = np.mean([abs(e['xg_espn']-e['goles']) for e in evs])
        sofa_better = sum(1 for e in evs if abs(e['xg_sofa']-e['goles']) < abs(e['xg_espn']-e['goles'])) / len(evs)
        d = mae_sofa - mae_espn
        flag = '*' if d < -0.005 else ' '
        print(f'  {liga:<10s} {len(evs):>5d} {mae_sofa:>10.3f} {mae_espn:>10.3f} {d:>+8.3f} {100*sofa_better:>13.1f}%')

    # ========== Top equipos diferencia más grande ==========
    print('\n[3] Equipos con MAYOR diferencia |xg_sofa - xg_espn| (top 15)')
    by_eq = defaultdict(list)
    for ev in eventos:
        by_eq[(ev['liga'], ev['equipo'])].append(ev)
    eq_stats = []
    for (liga, eq), evs in by_eq.items():
        if len(evs) < 3: continue
        avg_sofa = np.mean([e['xg_sofa'] for e in evs])
        avg_espn = np.mean([e['xg_espn'] for e in evs])
        avg_g = np.mean([e['goles'] for e in evs])
        eq_stats.append({'liga':liga,'equipo':eq,'n':len(evs),'avg_sofa':avg_sofa,'avg_espn':avg_espn,'diff':avg_sofa-avg_espn,'avg_goles':avg_g})
    eq_stats.sort(key=lambda x: -abs(x['diff']))
    print(f'{"liga":<12s} {"equipo":<28s} {"N":>3s} {"sofa":>6s} {"espn":>6s} {"diff":>7s} {"goles":>6s}')
    for s in eq_stats[:15]:
        print(f'{s["liga"]:<12s} {s["equipo"][:28]:<28s} {s["n"]:>3d} {s["avg_sofa"]:>6.3f} {s["avg_espn"]:>6.3f} {s["diff"]:>+7.3f} {s["avg_goles"]:>6.3f}')

    # ========== Save JSON ==========
    import json
    with open('analisis/motor_xg_v2_19_comparacion_sofa_vs_espn.json', 'w') as f:
        json.dump({
            'n_matched': len(matched),
            'n_eventos': len(eventos),
            'by_liga': by_liga_stats,
            'top_equipos_diff': eq_stats[:30],
        }, f, indent=2, default=lambda o: float(o) if hasattr(o, 'item') else str(o))
    print('\nGuardado analisis/motor_xg_v2_19_comparacion_sofa_vs_espn.json')


if __name__ == '__main__':
    main()

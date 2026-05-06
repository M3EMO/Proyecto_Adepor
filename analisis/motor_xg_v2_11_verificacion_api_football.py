"""
ETAPA 0 - Verificacion empirica gratis cobertura API-Football.

Objetivo: ANTES de comprometer scraping masivo, verificar empirically que las 16 ligas
target tengan referee + formation + lineup poblados en sample.

Plan calls (presupuesto 100/dia/key, 4 keys = 400 dia):
  1. /leagues?id=X&season=2024 - coverage flags por liga (16 calls)
  2. /fixtures?league=X&season=2024&from=2024-08-01&to=2024-08-31 - sample fixtures (16 calls)
     -> verificar `referee` field populado en cada fixture
  3. /fixtures/lineups?fixture=Y - 1 lineup sample por liga top 5 mainstream (5 calls)
  4. /injuries?league=X&season=2024 - 1 sample por 5 ligas (5 calls)

Total: ~42 calls. Bien dentro de budget.

Gate de decision al final:
  - Si >=70% ligas tienen referee populated AND >=50% lineups -> proceder
  - Si <70% referee O <50% lineup -> abandonar features pre-match, ir a Opcion C baseline
"""

import sys
import json
import time
from collections import defaultdict
import urllib.request
import urllib.error

sys.path.insert(0, '.')
from src.comun.config_sistema import API_KEYS_FOOTBALL, MAPA_LIGAS_API_FOOTBALL

OUT_JSON = 'analisis/motor_xg_v2_11_verificacion_api_football.json'
BASE_URL = 'https://v3.football.api-sports.io'


def api_call(path, key_idx=0):
    """Devuelve (json_response, headers). None si falla."""
    key = API_KEYS_FOOTBALL[key_idx % len(API_KEYS_FOOTBALL)]
    url = f'{BASE_URL}{path}'
    req = urllib.request.Request(url, headers={
        'x-apisports-key': key,
        'User-Agent': 'Adepor-research/1.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        print(f'  HTTP error {e.code}: {url}')
        if e.code == 429:
            print('  RATE LIMIT - usar otra key')
        return None, None
    except Exception as e:
        print(f'  Error: {e}')
        return None, None


def main():
    print('=== ETAPA 0: VERIFICACION GRATIS API-Football ===\n')
    print(f'Keys disponibles: {len(API_KEYS_FOOTBALL)}')
    print(f'Ligas a verificar: {len(MAPA_LIGAS_API_FOOTBALL)}\n')

    results = {'leagues': {}, 'sample_fixtures': {}, 'sample_lineups': {}, 'sample_injuries': {}}
    call_idx = 0

    # PASO 1: Coverage por liga (1 call por liga)
    print('--- PASO 1: coverage por liga ---')
    for liga, league_id in MAPA_LIGAS_API_FOOTBALL.items():
        path = f'/leagues?id={league_id}&season=2024'
        data, hdrs = api_call(path, key_idx=call_idx)
        call_idx += 1
        if data is None or not data.get('response'):
            print(f'  {liga:<14s} (id={league_id}) NO RESPONSE')
            results['leagues'][liga] = {'status': 'no_response'}
            continue
        league_obj = data['response'][0]
        seasons = league_obj.get('seasons', [])
        coverage_2024 = next((s.get('coverage', {}) for s in seasons if s.get('year') == 2024), {})
        fixtures_cov = coverage_2024.get('fixtures', {})
        out = {
            'league_id': league_id,
            'league_name': league_obj.get('league', {}).get('name'),
            'country': league_obj.get('country', {}).get('name'),
            'cov_events': fixtures_cov.get('events'),
            'cov_lineups': fixtures_cov.get('lineups'),
            'cov_statistics_fixtures': fixtures_cov.get('statistics_fixtures'),
            'cov_statistics_players': fixtures_cov.get('statistics_players'),
            'cov_injuries': coverage_2024.get('injuries'),
            'cov_predictions': coverage_2024.get('predictions'),
            'cov_odds': coverage_2024.get('odds'),
            'cov_standings': coverage_2024.get('standings'),
        }
        flag_lineup = '+' if out['cov_lineups'] else '-'
        flag_inj = '+' if out['cov_injuries'] else '-'
        print(f'  {liga:<14s} (id={league_id}) lineups={flag_lineup} injuries={flag_inj} events={"+" if out["cov_events"] else "-"}')
        results['leagues'][liga] = out
        time.sleep(0.5)  # rate limit cortesia

    # PASO 2: Sample 1 fixture por liga - check referee
    print('\n--- PASO 2: sample fixture por liga - check referee ---')
    sample_fixture_ids = {}  # liga -> fixture_id
    for liga, league_id in MAPA_LIGAS_API_FOOTBALL.items():
        path = f'/fixtures?league={league_id}&season=2024&from=2024-08-01&to=2024-08-15'
        data, hdrs = api_call(path, key_idx=call_idx)
        call_idx += 1
        if data is None or not data.get('response'):
            results['sample_fixtures'][liga] = {'status': 'no_fixtures', 'referee_populated': False}
            print(f'  {liga:<14s} no fixtures en ventana')
            continue
        # Tomar 1er fixture
        fix = data['response'][0]
        fix_id = fix['fixture']['id']
        ref = fix['fixture'].get('referee')
        sample_fixture_ids[liga] = fix_id
        ref_str = ref if ref else 'NULL'
        flag = '+' if ref else '-'
        print(f'  {liga:<14s} fixture {fix_id} referee=[{flag}] "{ref_str}"')
        results['sample_fixtures'][liga] = {
            'fixture_id': fix_id, 'referee': ref, 'referee_populated': bool(ref),
            'date': fix['fixture'].get('date'),
            'home': fix['teams']['home']['name'],
            'away': fix['teams']['away']['name'],
        }
        time.sleep(0.3)

    # PASO 3: Sample lineups - 6 ligas mainstream + 4 LATAM exoticas
    print('\n--- PASO 3: sample lineups - check formation ---')
    lineup_sample_ligas = ['Inglaterra', 'Espana', 'Italia', 'Argentina', 'Brasil',
                           'Bolivia', 'Venezuela', 'Peru', 'Ecuador', 'Uruguay']
    for liga in lineup_sample_ligas:
        fix_id = sample_fixture_ids.get(liga)
        if not fix_id:
            print(f'  {liga:<14s} sin fixture sample')
            continue
        path = f'/fixtures/lineups?fixture={fix_id}'
        data, hdrs = api_call(path, key_idx=call_idx)
        call_idx += 1
        if data is None or not data.get('response'):
            print(f'  {liga:<14s} fixture {fix_id} NO LINEUPS')
            results['sample_lineups'][liga] = {'status': 'no_lineups', 'formation_populated': False}
            continue
        formations = []
        startxi_counts = []
        for team_lineup in data['response']:
            formations.append(team_lineup.get('formation'))
            startxi_counts.append(len(team_lineup.get('startXI', [])))
        f1, f2 = formations[0], formations[1] if len(formations) > 1 else (None, None)
        flag = '+' if f1 and f2 else '-'
        print(f'  {liga:<14s} fixture {fix_id} formation=[{flag}] {f1}/{f2} startXI={startxi_counts}')
        results['sample_lineups'][liga] = {
            'fixture_id': fix_id, 'formacion_local': f1, 'formacion_visita': f2,
            'startxi_counts': startxi_counts,
            'formation_populated': bool(f1 and f2),
        }
        time.sleep(0.3)

    # PASO 4: Sample injuries - 5 ligas mix
    print('\n--- PASO 4: sample injuries por liga ---')
    inj_sample_ligas = ['Inglaterra', 'Argentina', 'Bolivia', 'Venezuela', 'Peru']
    for liga in inj_sample_ligas:
        league_id = MAPA_LIGAS_API_FOOTBALL[liga]
        path = f'/injuries?league={league_id}&season=2024'
        data, hdrs = api_call(path, key_idx=call_idx)
        call_idx += 1
        if data is None:
            results['sample_injuries'][liga] = {'status': 'error', 'count': 0}
            continue
        n = len(data.get('response', []))
        flag = '+' if n > 0 else '-'
        print(f'  {liga:<14s} injuries[{flag}] N={n}')
        results['sample_injuries'][liga] = {'count': n, 'has_data': n > 0}
        time.sleep(0.3)

    # GATE DE DECISION
    print('\n=== GATE DE DECISION ===')
    n_referee_ok = sum(1 for v in results['sample_fixtures'].values() if v.get('referee_populated'))
    n_total_ref = len(results['sample_fixtures'])
    pct_ref = 100 * n_referee_ok / n_total_ref if n_total_ref else 0

    n_form_ok = sum(1 for v in results['sample_lineups'].values() if v.get('formation_populated'))
    n_total_form = len(results['sample_lineups'])
    pct_form = 100 * n_form_ok / n_total_form if n_total_form else 0

    n_inj_ok = sum(1 for v in results['sample_injuries'].values() if v.get('has_data'))
    n_total_inj = len(results['sample_injuries'])

    print(f'Referee populated:  {n_referee_ok}/{n_total_ref} ligas ({pct_ref:.0f}%)')
    print(f'Formation populated: {n_form_ok}/{n_total_form} ligas sample ({pct_form:.0f}%)')
    print(f'Injuries con data: {n_inj_ok}/{n_total_inj} ligas sample')
    print()

    # Decision logic
    if pct_ref >= 70 and pct_form >= 50:
        decision = 'PROCEED: API-Football tiene cobertura aceptable. Consider POC backfill 2024.'
    elif pct_ref >= 50:
        decision = 'PARTIAL: cobertura parcial. Reduce alcance a top-EU + ARG/BRA.'
    else:
        decision = 'ABORT: cobertura insuficiente. NO scraping. Ir a Opcion C baseline Bayesian.'
    print(f'>>> DECISION: {decision}\n')

    # Save
    results['_meta'] = {
        'calls_realizadas': call_idx,
        'pct_referee_ok': pct_ref,
        'pct_formation_ok': pct_form,
        'decision': decision,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f'Guardado {OUT_JSON}')


if __name__ == '__main__':
    main()

"""
Adaptadores de eventos crudos de The-Odds-API al formato interno.

IMPORTANTE: dos funciones distintas, semántica diferente.

- `adaptar_fixture_odds_api`: consumida por motor_fixture durante failover ESPN.
  Produce una estructura minima tipo scoreboard ESPN (date + competitors)
  para continuar el pipeline de ingesta. No toca goles ni marcador.

- `adaptar_resultado_odds_api`: consumida por motor_backtest al liquidar.
  Produce un dict con goles y flag `completed` para el match vs partidos_backtest.
  Devuelve None si el evento no esta finalizado o carece de scores.
"""

from src.comun.tipos import safe_int


def adaptar_fixture_odds_api(evento_api):
    """Convierte un evento de The-Odds-API al formato scoreboard (fixture)."""
    return {
        'date': evento_api['commence_time'],
        'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'displayName': evento_api['home_team']}},
            {'homeAway': 'away', 'team': {'displayName': evento_api['away_team']}}
        ]}]
    }


def adaptar_resultado_odds_api(evento_api):
    """Convierte un evento finalizado de The-Odds-API al formato de resultado."""
    if not evento_api.get('completed', False) or not evento_api.get('scores'):
        return None

    loc_score = next((s['score'] for s in evento_api['scores'] if s['name'] == evento_api['home_team']), '0')
    vis_score = next((s['score'] for s in evento_api['scores'] if s['name'] == evento_api['away_team']), '0')

    return {
        'completed': True,
        'home_team': evento_api['home_team'],
        'away_team': evento_api['away_team'],
        'goles_l': safe_int(loc_score),
        'goles_v': safe_int(vis_score),
    }

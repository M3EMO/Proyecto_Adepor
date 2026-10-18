from scripts.research.fotmob_explorar import arbol, fila, partidos

DET = {
    'general': {'matchId': 1, 'leagueName': 'Premier League', 'leagueId': 47,
                'matchTimeUTCDate': '2026-10-17T11:30:00.000Z', 'finished': True},
    'header': {'teams': [{'id': 10, 'name': 'Everton', 'score': 0},
                         {'id': 20, 'name': 'Chelsea', 'score': 2}]},
    'content': {
        'stats': {'Periods': {'All': {'stats': [{'key': 'top_stats', 'stats': [
            {'key': 'expected_goals', 'title': 'Expected goals (xG)', 'stats': ['0.81', '1.95']},
            {'key': 'total_shots', 'title': 'Total shots', 'stats': [9, 14]},
            {'key': 'ShotsOnTarget', 'title': 'Shots on target', 'stats': [2, 6]},
            {'key': 'corners', 'title': 'Corners', 'stats': [4, 5]},
            {'key': 'titulo', 'title': 'Sin valores', 'stats': None},
        ]}]}}},
        'shotmap': {'shots': [{'teamId': 10, 'expectedGoals': 0.3}, {'teamId': 20, 'expectedGoals': 0.5},
                              {'teamId': 20, 'expectedGoals': 0.25}, {'teamId': 20, 'expectedGoals': None}]},
    },
}


def test_fila_mapea_local_y_visita():
    f = fila(DET)
    assert (f['ht'], f['at'], f['hg'], f['ag']) == ('Everton', 'Chelsea', 0, 2)
    assert (f['xg_l'], f['xg_v']) == (0.81, 1.95)
    assert (f['shots_total_l'], f['shots_on_target_v'], f['corners_l']) == (9, 6, 4)
    assert (f['xg_shotmap_l'], f['xg_shotmap_v']) == (0.3, 0.75)


def test_fila_sin_stats_devuelve_none_por_columna():
    f = fila({'header': DET['header']})
    assert f['xg_l'] is None and f['corners_v'] is None and f['xg_shotmap_l'] == 0.0
    assert fila({'header': {'teams': []}}) is None


def test_partidos_y_arbol():
    cal = {'leagues': [{'name': 'Premier League', 'matches': [
        {'id': 1, 'home': {'name': 'Everton'}, 'away': {'name': 'Chelsea'}, 'status': {'finished': True}}]}]}
    assert partidos(cal) == [(1, 'Premier League', 'Everton', 'Chelsea', True)]
    assert arbol({'a': [1, 2]}, 3) == ['$: dict[1]', '  a: list[2]', "    [0]: int = '1'"]

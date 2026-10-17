import src.comun.gestor_nombres as gn


def test_es_conocido(monkeypatch):
    monkeypatch.setattr(gn, 'cargar_diccionario', lambda: {'riverplate': 'River Plate'})
    assert gn.es_conocido('River Plate', liga='Argentina')
    assert gn.es_conocido('River  Plate!', liga='Argentina')
    assert not gn.es_conocido('Club Inventado', liga='Argentina')


def test_sin_tty_no_pide_input(monkeypatch):
    monkeypatch.setattr(gn, 'cargar_diccionario', lambda: {'riverplate': 'River Plate'})
    monkeypatch.setattr('builtins.input', lambda *a: (_ for _ in ()).throw(AssertionError('input')))
    assert gn.obtener_nombre_estandar('Club Inventado', liga='Argentina') == 'Club Inventado'


def test_nombre_equipo_valido():
    for ok in ('Venezia', '1. FC Köln', 'Brighton & Hove Albion', 'Atlético-MG', "Newell's Old Boys",
               'Deportes Tolima (COL)', 'Bodo/Glimt'):
        assert gn.nombre_equipo_valido(ok), ok
    for malo in ('./iniciar_dashboard.sh', 'sudo libinput debug-events --device /dev/input/event19',
                 'rm -rf /', 'x', 'a;b', '$(whoami)', '/dev/sda'):
        assert not gn.nombre_equipo_valido(malo), malo


def test_prompt_rechaza_comando(monkeypatch):
    monkeypatch.setattr(gn, 'cargar_diccionario', lambda: {'_meta': {}, 'Italia': {'torino': 'Torino'}})
    monkeypatch.setattr(gn, '_es_formato_v5', lambda d: True)
    guardado = []
    monkeypatch.setattr(gn, 'guardar_diccionario', lambda d: guardado.append(d))
    import io
    class _Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr('sys.stdin', _Tty())
    respuestas = iter(['./iniciar_dashboard.sh'])
    monkeypatch.setattr('builtins.input', lambda *a: next(respuestas))
    assert gn.obtener_nombre_estandar('Venezia FC', liga='Italia') == 'Venezia FC'
    assert next(respuestas, None) is None      # el prompt si se ejecuto
    assert guardado == []

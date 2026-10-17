import sys
import textwrap

import ejecutar_proyecto as ep


def _script(tmp_path, cuerpo):
    p = tmp_path / 'hijo.py'
    p.write_text(textwrap.dedent(cuerpo))
    return str(p)


def test_hijo_con_mucho_stderr_no_bloquea(tmp_path):
    # Antes: stderr=PIPE sin drenar -> deadlock con >64KB en stderr.
    s = _script(tmp_path, """
        import sys
        sys.stderr.write('x' * 300000)
        print('fin')
    """)
    assert ep.ejecutar_motor(s, 'stderr grande') is True


def test_hijo_que_falla_devuelve_false(tmp_path):
    s = _script(tmp_path, "raise SystemExit(3)")
    assert ep.ejecutar_motor(s, 'falla') is False


def test_rebuild_aborta_si_falla_un_paso(monkeypatch):
    llamados = []
    monkeypatch.setattr(ep, 'ejecutar_motor', lambda s, d, i=False: llamados.append(s) or False)
    monkeypatch.setattr(sys, 'argv', ['ejecutar_proyecto.py', '--rebuild'])
    try:
        ep.main()
    except SystemExit as e:
        assert e.code == 1
    assert llamados == ['importador_gold.py']  # no purga tablas derivadas tras el fallo

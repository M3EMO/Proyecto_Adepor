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


def test_cascada_diaria_solo_corre_motores_v2():
    # D-022: el v1 salio del camino diario; el v2 solo necesita fixture, cuotas y liquidacion.
    assert [m['archivo'] for m in ep.MOTORES_DIARIOS] == [
        'motor_backtest.py', 'motor_liquidador.py', 'motor_fixture.py', 'motor_cuotas.py',
        '-m src.ingesta.motor_oddspapi', 'motor_backtest.py', 'motor_liquidador.py']

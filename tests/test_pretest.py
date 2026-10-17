"""El auto-flip a LIVE (dinero real) debe mirar cuotas, no solo el hit."""
from scripts import evaluar_pretest as ep


def _cargar(db, pais, n, ganadas, cuota):
    for i in range(n):
        tok = '[GANADA] LOCAL' if i < ganadas else '[PERDIDA] LOCAL'
        db.execute("INSERT INTO partidos_backtest (id_partido, pais, apuesta_1x2, cuota_1, estado) "
                   "VALUES (?, ?, ?, ?, 'Liquidado')", (f'{pais}{i}', pais, tok, cuota))
    db.commit()


def test_hit_55_con_cuota_baja_no_flipea(db):
    _cargar(db, 'Perdedora', 40, 22, 1.70)   # hit 55%, yield -6.5%
    flips = ep._evaluar_mercado(db.cursor(), '1X2', 'apuesta_1x2', 'apuestas_live',
                                15, 0.55, 0.30, 'test')
    assert flips == []


def test_yield_positivo_significativo_flipea(db):
    _cargar(db, 'Ganadora', 40, 30, 1.70)    # hit 75% vs break-even 58.8%
    flips = ep._evaluar_mercado(db.cursor(), '1X2', 'apuesta_1x2',
                                'apuestas_live', 15, 0.55, 0.30, 'test')
    assert [f[0] for f in flips] == ['Ganadora'] and flips[0][4] == 'TRUE'


def _flag(db, pais):
    r = db.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='apuestas_live' "
                   "AND scope=?", (pais,)).fetchone()
    return r[0] if r else None


def test_evaluar_sin_aprobacion_no_pasa_a_live(db):
    _cargar(db, 'Ganadora', 40, 30, 1.70)
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) "
               "VALUES ('apuestas_live', 'Ganadora', 'FALSE', 'bool')")
    db.commit()
    ep.evaluar()
    assert _flag(db, 'Ganadora') == 'FALSE'
    ep.evaluar(aprobar_live=True)
    assert _flag(db, 'Ganadora') == 'TRUE'


def test_evaluar_revierte_a_pretest_sin_aprobacion(db):
    _cargar(db, 'Perdedora', 40, 15, 1.70)   # yield negativo
    db.execute("INSERT INTO config_motor_valores (clave, scope, valor_texto, tipo) "
               "VALUES ('apuestas_live', 'Perdedora', 'TRUE', 'bool')")
    db.commit()
    ep.evaluar()
    assert _flag(db, 'Perdedora') == 'FALSE'

from src.persistencia.motor_liquidador import main


def _insertar(db, id_p, ap_1x2, stk_1x2, ap_ou="pendiente", stk_ou=0):
    # Resultado 2-1: LOCAL gana, VISITA pierde.
    db.execute("""
        INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita,
            cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
            apuesta_1x2, apuesta_ou, stake_1x2, stake_ou, goles_l, goles_v, estado)
        VALUES (?, '2026-03-10 20:00', 'Argentina', 'A', 'B', 2.0, 3.0, 4.0, 1.8, 2.0,
                ?, ?, ?, ?, 2, 1, 'Finalizado')
    """, (id_p, ap_1x2, ap_ou, stk_1x2, stk_ou))


def _estado(db, id_p):
    return db.execute("SELECT estado FROM partidos_backtest WHERE id_partido = ?", (id_p,)).fetchone()[0]


def test_liquida_pick_resoluble(db, capsys):
    _insertar(db, "ok", "[APOSTAR] LOCAL", 10)
    db.commit()
    main()
    assert _estado(db, "ok") == "Liquidado"
    assert "[WARN]" not in capsys.readouterr().out


def test_stake_sin_token_queda_finalizado_con_warning(db, capsys):
    _insertar(db, "sin_token", "[APOSTAR] HANDICAP", 10)
    db.commit()
    main()
    assert _estado(db, "sin_token") == "Finalizado"
    assert "sin_token" in capsys.readouterr().out


def test_ou_con_stake_sin_token_queda_finalizado(db):
    _insertar(db, "ou_malo", "[APOSTAR] LOCAL", 10, ap_ou="[APOSTAR] HANDICAP", stk_ou=5)
    db.commit()
    main()
    assert _estado(db, "ou_malo") == "Finalizado"


def test_sin_stake_no_bloquea_liquidacion(db):
    _insertar(db, "stake_cero", "[APOSTAR] HANDICAP", 0)
    db.commit()
    main()
    assert _estado(db, "stake_cero") == "Liquidado"


def test_token_ya_liquidado_no_bloquea(db):
    # Liquidacion previa dejo '[GANADA]' en la columna: no es un [APOSTAR] sin token.
    _insertar(db, "ya_liq", "[GANADA] LOCAL", 10)
    db.commit()
    main()
    assert _estado(db, "ya_liq") == "Liquidado"

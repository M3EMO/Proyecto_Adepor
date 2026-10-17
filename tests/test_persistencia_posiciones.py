from src.persistencia import actualizar_posiciones as ap


def test_partido_liquidado_tarde_del_ultimo_dia_se_detecta(db):
    db.execute("CREATE TABLE partidos_historico_externo (id TEXT, liga TEXT, temp INTEGER, "
               "fecha TEXT, ht TEXT, at TEXT, hg INTEGER, ag INTEGER)")
    ap.crear_tabla_si_no_existe(db)
    cols = [r[1] for r in db.execute("PRAGMA table_info(posiciones_tabla_snapshot)")]
    fila = {c: None for c in cols}
    fila.update(liga='Brasil', temp=2026, fecha_snapshot='2026-04-05', formato='anual',
                equipo='Bahia', posicion=1)
    db.execute(f"INSERT INTO posiciones_tabla_snapshot ({','.join(fila)}) "
               f"VALUES ({','.join('?' * len(fila))})", list(fila.values()))
    db.execute("INSERT INTO partidos_backtest (id_partido, fecha, pais, local, visita, goles_l, "
               "goles_v, estado) VALUES ('x', '2026-04-05 21:00', 'Brasil', 'A', 'B', 1, 0, 'Liquidado')")
    db.commit()
    assert ('Brasil', 2026, '2026-04-05') in ap.detectar_grupos_pendientes(db)


def test_tabla_vieja_sin_equipo_norm_se_migra(db):
    db.execute("""CREATE TABLE posiciones_tabla_snapshot (liga TEXT NOT NULL, temp INTEGER NOT NULL,
        formato TEXT NOT NULL, fecha_snapshot TEXT NOT NULL, equipo TEXT NOT NULL, posicion INTEGER,
        pj INTEGER, pg INTEGER, pe INTEGER, pp INTEGER, gf INTEGER, gc INTEGER, dif_gol INTEGER,
        puntos INTEGER, PRIMARY KEY (liga, temp, formato, fecha_snapshot, equipo))""")
    ap.crear_tabla_si_no_existe(db)
    assert 'equipo_norm' in [r[1] for r in db.execute("PRAGMA table_info(posiciones_tabla_snapshot)")]

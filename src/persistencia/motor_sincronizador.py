"""
MOTOR SINCRONIZADOR V10.0 — Orquestador delgado de exportacion a Excel.

Responsabilidad unica: leer la DB y llamar a los modulos especializados
para armar las 4 hojas del workbook (Backtest, Resumen, Dashboard, Sombra).

Modularizacion fase 4 (2026-04-21): el monolitico V9.2 tenia 1090 LOC
mezclando estilos, formulas, metricas y 4 hojas. Ahora esta en:
  - excel_estilos.py        (fills, fonts, schema COL/HEADERS)
  - excel_formulas.py       (formulas Excel + helpers cuota_*)
  - excel_metricas.py       (Python KPIs para Dashboard)
  - excel_hoja_backtest.py  (hoja Backtest + hoja Resumen por liga)
  - excel_hoja_dashboard.py (hoja Dashboard KPIs)
  - excel_hoja_sombra.py    (hoja Sombra Op1 vs Op4)
"""
import os
import sqlite3

from openpyxl import Workbook

from src.persistencia.excel_hoja_backtest import poblar_backtest, crear_hoja_resumen
from src.persistencia.excel_hoja_dashboard import crear_hoja_dashboard
from src.persistencia.excel_hoja_resimulacion import crear_hoja_resimulacion
from src.persistencia.excel_hoja_sombra import crear_hoja_sombra
from src.persistencia.excel_metricas import calcular_metricas_dashboard


DB_NAME    = 'fondo_quant.db'
EXCEL_FILE = 'Backtest_Modelo.xlsx'


def _resucitar_liquidados_sin_goles(cursor):
    """Partidos con estado=Liquidado pero sin goles => volver a Calculado.
    Esto puede pasar si un motor_liquidador corrio antes del motor_backtest."""
    cursor.execute("""
        SELECT id_partido FROM partidos_backtest
        WHERE estado = 'Liquidado' AND (goles_l IS NULL OR goles_v IS NULL)
    """)
    resurrecciones = [r[0] for r in cursor.fetchall()]
    if resurrecciones:
        cursor.executemany(
            "UPDATE partidos_backtest SET estado = 'Calculado' WHERE id_partido = ?",
            [(i,) for i in resurrecciones],
        )
        print(f"[INFO] {len(resurrecciones)} partidos resucitados.")
    return len(resurrecciones)


def _leer_configuracion(cursor):
    """Lee bankroll operativo (dinamico o fijo) y fraccion_kelly de configuracion."""
    try:
        from src.nucleo.motor_calculadora import obtener_bankroll_operativo
        bankroll = obtener_bankroll_operativo(cursor)
    except Exception:
        try:
            cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
            bankroll = float(cursor.fetchone()[0])
        except (TypeError, IndexError):
            bankroll = 100000.00

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'fraccion_kelly'")
        row_fk = cursor.fetchone()
        fraccion_kelly = float(row_fk[0]) if row_fk else 0.50
    except Exception:
        fraccion_kelly = 0.50

    return bankroll, fraccion_kelly


def _cargar_apuestas_live(cursor):
    """Lee apuestas_live por liga desde config_motor_valores.
    Devuelve dict pais -> bool (True=LIVE, False=pretest)."""
    try:
        rows = cursor.execute(
            "SELECT scope, valor_texto FROM config_motor_valores WHERE clave='apuestas_live'"
        ).fetchall()
    except Exception:
        return {}
    out = {}
    for scope, val in rows:
        out[scope] = str(val).upper() in ('TRUE', '1', 'T', 'YES')
    return out


def _cargar_partidos(cursor):
    """Lee partidos en estado Calculado o Liquidado, ordenados por id_partido.
    Cols 26/27 son xg_local/xg_visita (al final para no romper otras hojas
    que consumen los datos por indice posicional)."""
    cursor.execute("""
        SELECT id_partido, fecha, local, visita, pais,
               prob_1, prob_x, prob_2, prob_o25, prob_u25,
               apuesta_1x2, apuesta_ou, stake_1x2, stake_ou,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               estado, goles_l, goles_v, incertidumbre, auditoria,
               apuesta_shadow_1x2, stake_shadow_1x2,
               xg_local, xg_visita
        FROM partidos_backtest
        WHERE estado IN ('Calculado', 'Liquidado')
        ORDER BY id_partido ASC
    """)
    return cursor.fetchall()


def main():
    print("[SISTEMA] Iniciando Motor Sincronizador V10.0 (Excel Local, modular)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    _resucitar_liquidados_sin_goles(cursor)
    conn.commit()

    bankroll, fraccion_kelly = _leer_configuracion(cursor)
    apuestas_live = _cargar_apuestas_live(cursor)

    datos = _cargar_partidos(cursor)
    conn.close()

    if not datos:
        print("[INFO] No hay partidos para sincronizar.")
        return

    print(f"[INFO] {len(datos)} partidos a sincronizar. Bankroll: ${bankroll:,.2f}")

    # --- Armar Excel ---
    wb = Workbook()

    # 1) Hoja Backtest (+ recolecta stats por liga) — la activa por defecto
    stats_liga = poblar_backtest(wb, datos, bankroll)

    # 2) Dashboard (como primera pestana)
    metricas = calcular_metricas_dashboard(datos, fraccion_kelly)
    crear_hoja_dashboard(wb, metricas, bankroll, apuestas_live)

    # 3) Sombra (auditoria Op1 vs Op4)
    crear_hoja_sombra(wb, datos, bankroll)

    # 4) Resumen por liga
    crear_hoja_resumen(wb, stats_liga, bankroll)

    # 5) Si Hubiera (resimulacion in-sample con reglas actuales + compounding)
    # Usa bankroll BASE (no dinamico) para tener un punto de partida estable.
    try:
        cursor2 = sqlite3.connect(DB_NAME).cursor()
        row_bk = cursor2.execute(
            "SELECT valor FROM configuracion WHERE clave='bankroll'").fetchone()
        bankroll_base = float(row_bk[0]) if row_bk else bankroll
        cursor2.connection.close()
        crear_hoja_resimulacion(wb, datos, bankroll_base)
    except Exception as e:
        print(f"[AVISO] No se pudo generar la hoja 'Si Hubiera': {e}")

    # Guardado
    wb.calculation.fullCalcOnLoad = True
    wb.save(EXCEL_FILE)
    print(f"[EXITO] Excel generado: {os.path.abspath(EXCEL_FILE)}")
    print(f"[INFO] {len(datos)} partidos escritos. {len(stats_liga)} ligas resumidas.")
    print("[SISTEMA] Motor Sincronizador V10.0 ha finalizado su ejecucion.")


if __name__ == "__main__":
    main()

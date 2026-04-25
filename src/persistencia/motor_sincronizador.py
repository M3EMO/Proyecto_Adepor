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
from src.persistencia.excel_hoja_live import crear_hoja_live
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
    """Lee bankroll BASE, bankroll OPERATIVO (dinamico/fijo) y fraccion_kelly.

    Devuelve (bankroll_base, bankroll_operativo, fraccion_kelly).
    bankroll_base: punto de partida fijo del Equity Curve (configuracion.bankroll).
    bankroll_operativo: el que usa Kelly (= base + aportes + P/L si dinamico).
    """
    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        bankroll_base = float(cursor.fetchone()[0])
    except (TypeError, IndexError, ValueError):
        bankroll_base = 100000.00

    try:
        from src.nucleo.motor_calculadora import obtener_bankroll_operativo
        bankroll_operativo = obtener_bankroll_operativo(cursor)
    except Exception:
        bankroll_operativo = bankroll_base

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'fraccion_kelly'")
        row_fk = cursor.fetchone()
        fraccion_kelly = float(row_fk[0]) if row_fk else 0.50
    except Exception:
        fraccion_kelly = 0.50

    return bankroll_base, bankroll_operativo, fraccion_kelly


def _cargar_aportes(cursor):
    """Lee la lista de aportes/retiros de capital ordenada por fecha asc.
    Devuelve [(fecha_str, monto_float), ...] o [] si la tabla no existe."""
    try:
        rows = cursor.execute(
            "SELECT fecha, monto FROM aportes_capital ORDER BY fecha ASC, id ASC"
        ).fetchall()
    except Exception:
        return []
    return [(str(f), float(m)) for f, m in rows]


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

    bankroll_base, bankroll_operativo, fraccion_kelly = _leer_configuracion(cursor)
    apuestas_live = _cargar_apuestas_live(cursor)
    aportes = _cargar_aportes(cursor)

    datos = _cargar_partidos(cursor)
    conn.close()

    if not datos:
        print("[INFO] No hay partidos para sincronizar.")
        return

    print(f"[INFO] {len(datos)} partidos a sincronizar. "
          f"Bankroll base: ${bankroll_base:,.2f} · operativo: ${bankroll_operativo:,.2f} · "
          f"aportes: {len(aportes)}")

    # --- Armar Excel ---
    wb = Workbook()

    # 1) Hoja Backtest: equity curve arranca en bankroll BASE (fix double-counting)
    #    + inyecta aportes en la fila correspondiente a su fecha.
    stats_liga = poblar_backtest(wb, datos, bankroll_base, aportes=aportes)

    # 2) Dashboard usa bankroll OPERATIVO (vista actual del capital).
    metricas = calcular_metricas_dashboard(datos, fraccion_kelly)
    crear_hoja_dashboard(wb, metricas, bankroll_operativo, apuestas_live)

    # 3) Sombra (auditoria Op1 vs Op4) — usa el operativo como referencia.
    crear_hoja_sombra(wb, datos, bankroll_operativo)

    # 4) Resumen por liga (operativo).
    crear_hoja_resumen(wb, stats_liga, bankroll_operativo)

    # 5) Si Hubiera (resimulacion): bankroll BASE (compounding desde el inicio).
    try:
        crear_hoja_resimulacion(wb, datos, bankroll_base)
    except Exception as e:
        print(f"[AVISO] No se pudo generar la hoja 'Si Hubiera': {e}")

    # 6) LIVE (solo apuestas futuras con stake>0, dividido por liga). Se inserta
    # como PRIMERA pestana del workbook para que sea la vista por defecto.
    try:
        crear_hoja_live(wb, datos, apuestas_live)
    except Exception as e:
        print(f"[AVISO] No se pudo generar la hoja 'LIVE': {e}")

    # Guardado
    wb.calculation.fullCalcOnLoad = True
    wb.active = 0  # pestana LIVE visible al abrir
    wb.save(EXCEL_FILE)
    print(f"[EXITO] Excel generado: {os.path.abspath(EXCEL_FILE)}")
    print(f"[INFO] {len(datos)} partidos escritos. {len(stats_liga)} ligas resumidas.")
    print("[SISTEMA] Motor Sincronizador V10.0 ha finalizado su ejecucion.")


if __name__ == "__main__":
    main()

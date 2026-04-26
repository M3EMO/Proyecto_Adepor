"""Pobla pipeline_motores con inventario exhaustivo de la cascada diaria.

Source de verdad: ejecutar_proyecto.py MOTORES_DIARIOS list.
Cada motor: orden, fase, archivo, descripcion, criticidad, inputs/outputs, archivos.

Idempotente: borra y re-inserta.
"""
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

MOTORES = [
    # FASE 0: MANTENIMIENTO
    {
        "orden": 0, "fase": "0_MANTENIMIENTO",
        "motor": "motor_purga", "archivo": "motor_purga.py",
        "descripcion": "Optimizador de Memoria: limpia datos derivados obsoletos pre-cascada.",
        "critico": 0,
        "inputs": "partidos_backtest, historial_equipos",
        "outputs": "partidos_backtest (clean), tablas derivadas borradas",
        "archivos_externos": None,
    },
    # FASE 1: LIQUIDACION + RECALIBRACION
    {
        "orden": 1, "fase": "1_LIQUIDACION",
        "motor": "motor_backtest", "archivo": "motor_backtest.py",
        "descripcion": "Liquidador de Goles: busca resultados ESPN para partidos pasados, llena goles_l/goles_v, marca estado='Liquidado'.",
        "critico": 1,
        "inputs": "partidos_backtest WHERE estado IN (Pendiente,Calculado), ESPN scoreboard",
        "outputs": "partidos_backtest.goles_l, goles_v, estado='Liquidado'",
        "archivos_externos": "ESPN site.api.espn.com",
    },
    {
        "orden": 1.5, "fase": "1_LIQUIDACION",
        "motor": "motor_liquidador", "archivo": "motor_liquidador.py",
        "descripcion": "Liquidador de Apuestas: calcula GANO/PERDIO/VOID + CLV (Closing Line Value) para los Liquidados.",
        "critico": 1,
        "inputs": "partidos_backtest.{cuota_*, apuesta_*, cuota_cierre_*}",
        "outputs": "partidos_backtest.{resultado_1x2, resultado_ou, clv_pct_1x2, clv_pct_ou}",
        "archivos_externos": None,
    },
    {
        "orden": 1.6, "fase": "1_LIQUIDACION",
        "motor": "evaluar_pretest", "archivo": "scripts/evaluar_pretest.py",
        "descripcion": "Pretest Monitor: auto-flip LIVE/PRETEST por liga segun stability del motor.",
        "critico": 0,
        "inputs": "configuracion (pretest mode flags)",
        "outputs": "configuracion (mode flips)",
        "archivos_externos": None,
    },
    {
        "orden": 2, "fase": "1_LIQUIDACION",
        "motor": "motor_arbitro", "archivo": "motor_arbitro.py",
        "descripcion": "El Inquisidor: auditoria de tarjetas y eventos arbitrales por partido.",
        "critico": 0,
        "inputs": "partidos_backtest, ESPN events",
        "outputs": "partidos_backtest.{tarjetas_amarillas_l/v, tarjetas_rojas_l/v}",
        "archivos_externos": "ESPN events endpoint",
    },
    {
        "orden": 3, "fase": "1_LIQUIDACION",
        "motor": "motor_data", "archivo": "motor_data.py",
        "descripcion": "Regresion Bayesiana: scrapea ESPN historico, calcula xG hibrido, actualiza EMA + Bayesian shrinkage en historial_equipos. Tambien EMA dual SHADOW (corto).",
        "critico": 1,
        "inputs": "ESPN scoreboard rango profundidad, historial_equipos (estado previo)",
        "outputs": "historial_equipos (full update), partidos_backtest (sot_l/v, shots_l/v, corners_l/v)",
        "archivos_externos": "ESPN site.api.espn.com",
    },
    # FASE 2: HORIZONTE FUTURO
    {
        "orden": 4, "fase": "2_HORIZONTE",
        "motor": "motor_fixture", "archivo": "motor_fixture.py",
        "descripcion": "El Arquitecto: proyecta calendario de partidos proximos via ESPN + API-Football.",
        "critico": 1,
        "inputs": "ESPN scoreboard fecha futura",
        "outputs": "partidos_backtest INSERT estado='Pendiente'",
        "archivos_externos": "ESPN scoreboard, API-Football fixtures",
    },
    {
        "orden": 5, "fase": "2_HORIZONTE",
        "motor": "motor_tactico", "archivo": "motor_tactico.py",
        "descripcion": "El Analista: formaciones esperadas y vida de DTs por equipo (placeholder en algunas ligas).",
        "critico": 0,
        "inputs": "partidos_backtest WHERE estado='Pendiente'",
        "outputs": "tabla tactica/dt-related (depending on liga)",
        "archivos_externos": "API-Football, ESPN team rosters",
    },
    {
        "orden": 6, "fase": "2_HORIZONTE",
        "motor": "motor_cuotas", "archivo": "motor_cuotas.py",
        "descripcion": "El Oraculo: extrae cuotas 1X2 + O/U 2.5 de The-Odds-API. Captura cuota_cierre 0-2h pre-kickoff (V9.3 CLV).",
        "critico": 1,
        "inputs": "partidos_backtest WHERE estado='Pendiente'",
        "outputs": "partidos_backtest.{cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, cuota_cierre_*}",
        "archivos_externos": "The-Odds-API.com",
    },
    {
        "orden": 6.5, "fase": "2_HORIZONTE",
        "motor": "motor_cuotas_apifootball", "archivo": "src/ingesta/motor_cuotas_apifootball.py",
        "descripcion": "Oraculo Sudamericano: cuotas via API-Football para ligas LATAM no cubiertas por The-Odds-API.",
        "critico": 0,
        "inputs": "partidos_backtest WHERE pais IN LATAM",
        "outputs": "partidos_backtest.{cuota_*} (LATAM)",
        "archivos_externos": "v3.football.api-sports.io",
    },
    # FASE 3: DECISIONES
    {
        "orden": 7, "fase": "3_DECISIONES",
        "motor": "motor_calculadora", "archivo": "motor_calculadora.py",
        "descripcion": "Cerebro Cuantitativo: Poisson + tau Dixon-Coles + Fix5 + Hallazgo G + 4 Caminos + Kelly. Aplica todos los filtros del motor (consultar motor_filtros_activos).",
        "critico": 1,
        "inputs": "partidos_backtest WHERE estado IN (Pendiente,Calculado), historial_equipos, ligas_stats, config_motor_valores, equipos_altitud",
        "outputs": "partidos_backtest.{xg_local, xg_visita, prob_*, apuesta_*, stake_*, ev_*, shadow_xg_*}",
        "archivos_externos": None,
    },
    # FASE 4: REDUNDANCIA + EXCEL
    {
        "orden": 8, "fase": "4_EXCEL",
        "motor": "motor_backtest_2", "archivo": "motor_backtest.py",
        "descripcion": "Liquidador de Ultimo Minuto: doble barrido tras motor_calculadora (caches partidos cuyo resultado llego entre fases).",
        "critico": 0,
        "inputs": "ESPN, partidos_backtest",
        "outputs": "idem motor_backtest fase 1",
        "archivos_externos": "ESPN",
    },
    {
        "orden": 8.5, "fase": "4_EXCEL",
        "motor": "motor_liquidador_2", "archivo": "motor_liquidador.py",
        "descripcion": "Liquidador de Apuestas: barrido final post-doble.",
        "critico": 0,
        "inputs": "partidos_backtest",
        "outputs": "partidos_backtest.{resultado_*, clv_*}",
        "archivos_externos": None,
    },
    {
        "orden": 9, "fase": "4_EXCEL",
        "motor": "motor_sincronizador", "archivo": "src/persistencia/motor_sincronizador.py",
        "descripcion": "Sincronizador Excel: lee DB y arma Backtest_Modelo.xlsx con 6 hojas via excel_hoja_*.py modulos.",
        "critico": 1,
        "inputs": "partidos_backtest, historial_equipos, configuracion, ligas_stats",
        "outputs": "Backtest_Modelo.xlsx (6 hojas: Backtest, Resumen, Dashboard, Live, Sombra, Resimulacion)",
        "archivos_externos": "Backtest_Modelo.xlsx (output)",
    },
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("DELETE FROM pipeline_motores")
    for m in MOTORES:
        cur.execute(
            """INSERT INTO pipeline_motores
               (orden, fase, motor, archivo, descripcion, critico,
                inputs, outputs, archivos_externos)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (m["orden"], m["fase"], m["motor"], m["archivo"], m["descripcion"],
             m["critico"], m["inputs"], m["outputs"], m["archivos_externos"]),
        )
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM pipeline_motores").fetchone()[0]
    print(f"pipeline_motores poblado: {n} motores")
    print()
    print(f"{'#':>4} {'Fase':<16} {'Motor':<24} {'Critico':<8} Descripcion")
    print("-" * 110)
    for r in cur.execute("""
        SELECT orden, fase, motor, critico, substr(descripcion, 1, 60)
        FROM pipeline_motores ORDER BY orden
    """):
        crit = "SI" if r[3] == 1 else "no"
        print(f"{r[0]:>4} {r[1]:<16} {r[2]:<24} {crit:<8} {r[4]}...")
    con.close()


if __name__ == "__main__":
    main()

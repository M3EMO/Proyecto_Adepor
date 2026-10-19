"""
PIPELINE CENTRAL ADEPOR V8.0 (Orquestador Cuantitativo)
========================================================
Punto de entrada unico para todo el sistema. Ejecuta la cascada diaria
por defecto o uno de los subcomandos via argumentos CLI.

Uso:
    py ejecutar_proyecto.py                # Pipeline diario completo
    py ejecutar_proyecto.py --help         # Lista de comandos
    py ejecutar_proyecto.py --status       # Estado del sistema (sin tocar DB)
    py ejecutar_proyecto.py --summary      # Resumen post-ultima-corrida
    py ejecutar_proyecto.py --audit-names  # Auditoria interactiva de nombres
    py ejecutar_proyecto.py --aporte <monto> [--fecha YYYY-MM-DD] [--desc "..."]  # Aporte o retiro
    py ejecutar_proyecto.py --aportes-list # Lista de aportes y retiros
"""
import subprocess
import time
import sys
import os
from datetime import datetime, timedelta

# Los motores usan paths relativos (diccionario_equipos.json, scripts/...): fijar CWD a la raiz.
RAIZ = os.path.dirname(os.path.abspath(__file__))
os.chdir(RAIZ)
sys.path.insert(0, RAIZ)
from src.comun.config_sistema import DB_NAME  # noqa: E402

# Forzar UTF-8 en stdout/stderr (Windows default cp1252 rompe con caracteres turcos/sudamericanos)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


# ==========================================================================
# CASCADA DIARIA (orden canonico)
# ==========================================================================
MOTORES_DIARIOS = [
    # v1 retirado (D-022, D-023): el v2 decide con Pinnacle sin margen y no lee EMAs, stats ni xG.

    # --- FASE 1: LIQUIDACION ---
    {"archivo": "motor_backtest.py",         "desc": "1. Liquidador de Goles (Cierre de Resultados)",          "critico": True,  "interactivo": False},
    {"archivo": "motor_liquidador.py",       "desc": "1.5. Liquidador de Apuestas (Auditoria de Resultados)",  "critico": True,  "interactivo": False},

    # --- FASE 2: HORIZONTE FUTURO ---
    # API-Football retirado (decision usuario 2026-10-13): fuentes = ESPN + The Odds API.
    {"archivo": "motor_fixture.py",          "desc": "4. El Arquitecto (Proyeccion de Calendario)",            "critico": True,  "interactivo": True},
    {"archivo": "motor_cuotas.py",           "desc": "6. El Oraculo (Cuotas Pinnacle previas y de cierre)",    "critico": True,  "interactivo": False},

    # --- FASE 4: REDUNDANCIA ---
    {"archivo": "motor_backtest.py",         "desc": "8. Liquidador de Ultimo Minuto (Doble Barrido)",         "critico": False, "interactivo": False},
    {"archivo": "motor_liquidador.py",       "desc": "8.5. Liquidador de Apuestas (Barrido Final)",            "critico": False, "interactivo": False},
]


# ==========================================================================
# HELPERS DE LOGGING
# ==========================================================================
def log_terminal(mensaje, nivel="INFO"):
    colores = {
        "INFO":   "\033[94m",  # Azul
        "EXITO":  "\033[92m",  # Verde
        "ALERTA": "\033[93m",  # Amarillo
        "ERROR":  "\033[91m",  # Rojo
        "END":    "\033[0m",
    }
    hora = datetime.now().strftime("%H:%M:%S")
    color = colores.get(nivel, colores["END"])
    print(f"{color}[{hora}] {nivel} - {mensaje}{colores['END']}")


def _imprimir_banner(titulo, ancho=70, char='='):
    print(char * ancho)
    print(f"[*] {titulo}")
    print(char * ancho)


# ==========================================================================
# EJECUCION DE MOTORES INDIVIDUALES
# ==========================================================================
def ejecutar_motor(script_name, descripcion, interactivo=False):
    print(f"\n> INICIANDO: {descripcion}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    inicio = time.time()

    # Soportar comando con args: "script.py --flag"
    cmd_parts = script_name.split()
    cmd_full = [sys.executable, '-u'] + cmd_parts

    try:
        if interactivo:
            proceso = subprocess.run(cmd_full, env=env)
            if proceso.returncode != 0:
                raise subprocess.CalledProcessError(proceso.returncode, script_name)
        else:
            proceso = subprocess.Popen(
                # stderr fusionado en stdout: con dos PIPEs y solo stdout drenado,
                # un hijo que escribe >64KB a stderr bloquea el pipeline.
                cmd_full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', env=env,
            )
            full_stdout = ""
            for linea in proceso.stdout:
                full_stdout += linea
                print(f"   | {linea.rstrip()}")
            proceso.wait()
            if proceso.returncode != 0:
                raise subprocess.CalledProcessError(
                    proceso.returncode, proceso.args, output=full_stdout,
                )

        log_terminal(f"COMPLETADO en {round(time.time() - inicio, 2)}s", "EXITO")
        return True
    except subprocess.CalledProcessError as e:
        log_terminal(f"FALLO en {script_name}", "ERROR")
        stderr_txt = getattr(e, 'stderr', None)
        stdout_txt = getattr(e, 'output', None)
        print("\n--- TRAZA DE ERROR ---")
        print(stderr_txt if stderr_txt else (stdout_txt or "(sin salida)")[-4000:])
        print("----------------------\n")
        return False
    except FileNotFoundError:
        log_terminal(f"Archivo no encontrado: {script_name}", "ERROR")
        return False


# ==========================================================================
# PRE-FLIGHT CHECKS (validaciones antes del pipeline diario)
# ==========================================================================
def _preflight_checks():
    """Valida que la DB exista, config.json tenga keys y modulos esten accesibles.
    Retorna lista de warnings (strings). Vacia = todo OK."""
    warnings = []

    if not os.path.exists(DB_NAME) or os.path.getsize(DB_NAME) == 0:
        warnings.append("fondo_quant.db NO existe. Correr con --rebuild para crearla desde CSV.")

    if not os.path.exists('config.json'):
        warnings.append("config.json NO existe. Copiar config.example.json y completar keys.")
    else:
        try:
            import json
            with open('config.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if not cfg.get('api_keys_odds'):
                warnings.append("config.json: api_keys_odds esta vacio (motor_cuotas fallara).")
        except (ValueError, IOError) as e:
            warnings.append(f"config.json corrupto: {e}")

    return warnings


# ==========================================================================
# SUBCOMANDO: --status (snapshot del sistema)
# ==========================================================================
def cmd_status():
    """Muestra estado del sistema sin tocar DB."""
    _imprimir_banner(f"STATUS ADEPOR — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # 1. Pre-flight
    warns = _preflight_checks()
    if warns:
        for w in warns:
            log_terminal(w, "ALERTA")
    else:
        log_terminal("Pre-flight OK: DB, config, motores accesibles", "EXITO")

    # 2. DB snapshot
    try:
        import sqlite3
        con = sqlite3.connect(DB_NAME)
        cur = con.cursor()

        print()
        print("--- APUESTAS ---")
        # REALES = apuestas confirmadas (stake>0). Liquidadas = apuesta evaluada GANADA|PERDIDA.
        reales_vivas_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_1x2>0 AND estado!='Liquidado'"
        ).fetchone()[0]
        reales_vivas_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_ou>0 AND estado!='Liquidado'"
        ).fetchone()[0]
        reales_liq_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_1x2>0 AND estado='Liquidado' "
            "AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')"
        ).fetchone()[0]
        reales_liq_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_ou>0 AND estado='Liquidado' "
            "AND (apuesta_ou LIKE '[GANADA]%' OR apuesta_ou LIKE '[PERDIDA]%')"
        ).fetchone()[0]
        reales_g_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_1x2>0 AND apuesta_1x2 LIKE '[GANADA]%'"
        ).fetchone()[0]
        reales_g_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE stake_ou>0 AND apuesta_ou LIKE '[GANADA]%'"
        ).fetchone()[0]
        reales_vivas = reales_vivas_1x2 + reales_vivas_ou
        reales_liq = reales_liq_1x2 + reales_liq_ou
        reales_g = reales_g_1x2 + reales_g_ou
        hit_real = 100 * reales_g / reales_liq if reales_liq else None

        print(f"  REALES (stake>0):")
        print(f"    Vivas:            {reales_vivas:>4d}   (1X2:{reales_vivas_1x2}  O/U:{reales_vivas_ou})")
        print(f"    Liquidadas:       {reales_liq:>4d}   (1X2:{reales_liq_1x2}  O/U:{reales_liq_ou})")
        if hit_real is not None:
            print(f"    Hit real:        {hit_real:>4.1f}%   (ganadas {reales_g})")
        else:
            print(f"    Hit real:         N/A   (sin liquidaciones con stake>0 aun)")

        print()
        print("--- CONFIG V2 ---")
        from src.comun.config_motor import get_param
        for clave, default in (('umbral_ev_v2', 0.02), ('fraccion_kelly_v2', 0.25), ('tope_stake_v2', 0.005)):
            print(f"  {clave:<25s} = {get_param(clave, default=default)}")

        # Bankroll operativo (base + P/L acumulado si modo=dinamico, clampeado)
        print()
        print("--- BANKROLL ---")
        try:
            from src.persistencia.bankroll import obtener_bankroll_operativo
            base  = cur.execute("SELECT valor FROM configuracion WHERE clave='bankroll'").fetchone()
            modo  = cur.execute("SELECT valor FROM configuracion WHERE clave='bankroll_modo'").fetchone()
            corte = cur.execute("SELECT valor FROM configuracion WHERE clave='bankroll_fecha_corte'").fetchone()
            piso  = cur.execute("SELECT valor FROM configuracion WHERE clave='bankroll_piso'").fetchone()
            techo = cur.execute("SELECT valor FROM configuracion WHERE clave='bankroll_techo'").fetchone()
            bk_op = obtener_bankroll_operativo(cur)
            base_f = float(base[0]) if base else 0
            print(f"  base                = ${base_f:>12,.2f}")
            print(f"  modo                = {modo[0] if modo else 'fijo'}")
            if modo and str(modo[0]).lower() == 'dinamico':
                print(f"  fecha corte         = {corte[0] if corte else 'n/a'}")
                print(f"  piso / techo        = ${float(piso[0]):,.0f} / ${float(techo[0]):,.0f}")
                pl = bk_op - base_f
                print(f"  P/L acumulado       = ${pl:>+12,.2f}")
            print(f"  OPERATIVO           = ${bk_op:>12,.2f}")
        except Exception as e:
            print(f"  (error leyendo bankroll: {e})")

        con.close()
    except Exception as e:
        log_terminal(f"Error leyendo DB: {e}", "ERROR")


# ==========================================================================
# SUBCOMANDO: --summary (resumen tras ultima corrida)
# ==========================================================================
def cmd_summary():
    """Stats desde el cierre de DB (post-ultima corrida)."""
    _imprimir_banner(f"SUMMARY DEL ULTIMO RUN — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        import sqlite3
        con = sqlite3.connect(DB_NAME)
        cur = con.cursor()

        # Ventana de hoy a pasado manana
        ayer = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        hoy = datetime.now().strftime('%Y-%m-%d')
        manana = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        pasado = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')

        print("\n--- PARTIDOS CON CUOTA PINNACLE (proximas 72h) ---")
        # motor_cuotas agrega las columnas pin_* en su primera corrida.
        if 'pin_1' not in {r[1] for r in cur.execute("PRAGMA table_info(partidos_backtest)")}:
            print("  (la base no tiene cuotas Pinnacle: correr el pipeline diario)")
            con.close()
            return
        for d in (hoy, manana, pasado):
            n = cur.execute("SELECT COUNT(*) FROM partidos_backtest WHERE fecha LIKE ? AND pin_1 > 0",
                            (f'{d}%',)).fetchone()[0]
            if n:
                print(f"  {d}: {n} partidos")

        # Liquidados en las ultimas 24h
        print(f"\n--- LIQUIDADOS EN ULTIMAS 24H ---")
        rows = cur.execute(f"""
            SELECT pais, COUNT(*), SUM(CASE WHEN apuesta_1x2 LIKE '[GANADA]%' THEN 1 ELSE 0 END)
            FROM partidos_backtest
            WHERE estado='Liquidado' AND fecha >= ?
              AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')
            GROUP BY pais ORDER BY pais
        """, (ayer,)).fetchall()
        if not rows:
            print("  (ninguno)")
        for pais, n, g in rows:
            print(f"  {pais:<12s} N={n} ganadas={g or 0} hit={100*(g or 0)/n:.0f}%")

        # Cobertura de cuotas
        print("\n--- COBERTURA PINNACLE (partidos vivos) ---")
        rows = cur.execute("""
            SELECT pais, COUNT(*) tot, SUM(CASE WHEN pin_1 > 0 THEN 1 ELSE 0 END) con
            FROM partidos_backtest
            WHERE estado != 'Liquidado' GROUP BY pais ORDER BY pais
        """).fetchall()
        for pais, tot, con_ in rows:
            pct = 100 * (con_ or 0) / tot if tot else 0
            bar = '#' * int(pct / 10)
            print(f"  {pais:<12s} {(con_ or 0):>3d}/{tot:<3d} ({pct:>5.1f}%) {bar}")

        con.close()
    except Exception as e:
        log_terminal(f"Error: {e}", "ERROR")


# ==========================================================================
# SUBCOMANDO: --aporte / --aportes-list
# ==========================================================================
def cmd_aporte():
    """Registra un aporte (positivo) o retiro (negativo) de capital.

    Uso:
        py ejecutar_proyecto.py --aporte <monto> [--fecha YYYY-MM-DD] [--desc "..."]

    Ejemplos:
        py ejecutar_proyecto.py --aporte 100000 --desc "Capital adicional Mateo"
        py ejecutar_proyecto.py --aporte -25000 --fecha 2026-04-30 --desc "Retiro mensual"
    """
    args = sys.argv[2:]
    if not args:
        log_terminal("Uso: --aporte <monto> [--fecha YYYY-MM-DD] [--desc \"...\"]", "ERROR")
        sys.exit(1)
    try:
        monto = float(args[0])
    except (ValueError, IndexError):
        log_terminal("Monto invalido. Debe ser un numero (positivo aporte / negativo retiro).", "ERROR")
        sys.exit(1)

    fecha = datetime.now().strftime('%Y-%m-%d')
    desc = ""
    i = 1
    while i < len(args):
        if args[i] == '--fecha' and i + 1 < len(args):
            fecha = args[i + 1].strip()
            i += 2
        elif args[i] == '--desc' and i + 1 < len(args):
            desc = args[i + 1].strip()
            i += 2
        else:
            log_terminal(f"Argumento desconocido: {args[i]}", "ERROR")
            sys.exit(1)

    # Validacion fecha
    try:
        datetime.strptime(fecha, '%Y-%m-%d')
    except ValueError:
        log_terminal(f"Fecha invalida '{fecha}'. Formato YYYY-MM-DD.", "ERROR")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Asegurar que la tabla exista
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aportes_capital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            descripcion TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(
        "INSERT INTO aportes_capital (fecha, monto, descripcion) VALUES (?, ?, ?)",
        (fecha, monto, desc),
    )
    conn.commit()

    # Mostrar bankroll resultante
    try:
        from src.persistencia.bankroll import obtener_bankroll_operativo
        nuevo_bk = obtener_bankroll_operativo(cur)
    except Exception:
        nuevo_bk = None
    conn.close()

    signo = "APORTE" if monto >= 0 else "RETIRO"
    log_terminal(
        f"{signo} registrado: ${abs(monto):,.2f} en {fecha}" + (f" — {desc}" if desc else ""),
        "EXITO",
    )
    if nuevo_bk is not None:
        log_terminal(f"Bankroll operativo actual: ${nuevo_bk:,.2f}", "INFO")


def cmd_aportes_list():
    """Lista los aportes/retiros registrados."""
    import sqlite3
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    try:
        rows = cur.execute(
            "SELECT id, fecha, monto, descripcion FROM aportes_capital ORDER BY fecha ASC, id ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        log_terminal("Tabla aportes_capital no existe. Crear con: py scripts/crear_tabla_aportes_capital.py", "ALERTA")
        conn.close()
        return

    _imprimir_banner("APORTES DE CAPITAL")
    if not rows:
        print("  (sin movimientos registrados)")
        conn.close()
        return

    total = 0.0
    print(f"  {'ID':<5}{'Fecha':<12}{'Monto':>14}  Descripcion")
    print("  " + "-" * 70)
    for rid, fecha, monto, desc in rows:
        total += monto
        print(f"  {rid:<5}{fecha:<12}{monto:>14,.2f}  {desc or ''}")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<5}{'':<12}{total:>14,.2f}")
    conn.close()


# ==========================================================================
# SUBCOMANDO: --help
# ==========================================================================
def cmd_help():
    print(__doc__)
    print("\nMotores en la cascada diaria:")
    for m in MOTORES_DIARIOS:
        marca = ' [CRITICO]' if m['critico'] else ''
        print(f"  {m['archivo']:<42s} {m['desc']}{marca}")


# ==========================================================================
# PIPELINE DIARIO (default)
# ==========================================================================
def cmd_pipeline_diario():
    # Pre-flight
    warns = _preflight_checks()
    if warns:
        log_terminal("PRE-FLIGHT WARNINGS:", "ALERTA")
        for w in warns:
            log_terminal(f"  {w}", "ALERTA")
        print()
    # Sin DB los motores crean un archivo vacio y fallan en cascada: abortar antes.
    if not os.path.exists(DB_NAME) or os.path.getsize(DB_NAME) == 0:
        log_terminal(f"ABORTO: no existe la DB {DB_NAME}.", "ERROR")
        sys.exit(1)

    _imprimir_banner(f"PIPELINE CUANTITATIVO V8.0 INICIADO - {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    inicio_total = time.time()
    fallados = []
    for motor in MOTORES_DIARIOS:
        exito = ejecutar_motor(motor["archivo"], motor["desc"], motor.get("interactivo", False))
        if not exito:
            fallados.append(motor["archivo"])
            if motor["critico"]:
                log_terminal("ABORTO DE EMERGENCIA (motor critico fallo).", "ERROR")
                sys.exit(1)
            else:
                log_terminal("Continuando ejecucion degradada (motor satelite fallo)...", "ALERTA")

    total_seg = round(time.time() - inicio_total, 2)
    print("\n" + "=" * 70)
    log_terminal(f"PIPELINE COMPLETADO en {total_seg}s.", "EXITO")
    if fallados:
        log_terminal(f"Motores satelites que fallaron: {fallados}", "ALERTA")
    print("=" * 70)

    # Resumen post-run: invocar cmd_summary inline
    print()
    cmd_summary()


# ==========================================================================
# MAIN DISPATCHER
# ==========================================================================
def main():
    if sys.stdout.isatty():  # bajo cron 'clear' ensucia el log
        os.system('cls' if os.name == 'nt' else 'clear')

    if len(sys.argv) <= 1:
        cmd_pipeline_diario()
        return

    comando = sys.argv[1]

    # Subcomandos read-only
    if comando in ('--help', '-h'):
        cmd_help()
        return
    if comando == '--status':
        cmd_status()
        return
    if comando == '--summary':
        cmd_summary()
        return
    if comando == '--audit-names':
        log_terminal("MODO AUDITORIA INTERACTIVA DE NOMBRES", "ALERTA")
        ejecutar_motor('auditor/auditor_espn.py', 'Auditoria Interactiva de Nombres (ESPN vs. Diccionario)')
        log_terminal("Auditoria finalizada.", "EXITO")
        return

    if comando == '--aporte':
        cmd_aporte()
        return
    if comando == '--aportes-list':
        cmd_aportes_list()
        return

    # Comando desconocido
    log_terminal(f"Comando desconocido: {comando}", "ERROR")
    cmd_help()
    sys.exit(1)


if __name__ == "__main__":
    main()

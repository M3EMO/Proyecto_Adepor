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
    py ejecutar_proyecto.py --analisis N   # Scripts de analisis puntual
    py ejecutar_proyecto.py --rebuild      # Reconstruccion desde Gold Standard
    py ejecutar_proyecto.py --unlock       # Desbloqueo matriz
    py ejecutar_proyecto.py --purge-history # Purga tablas derivadas
    py ejecutar_proyecto.py --audit-names  # Auditoria interactiva de nombres

Ejemplos:
    py ejecutar_proyecto.py --analisis         # lista analisis disponibles
    py ejecutar_proyecto.py --analisis volumen # corre analisis_volumen_yield.py
    py ejecutar_proyecto.py --analisis pretest # corre evaluar_pretest dry-run
"""
import subprocess
import time
import sys
import os
from datetime import datetime, timedelta

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
    # --- FASE 0: MANTENIMIENTO ---
    {"archivo": "motor_purga.py",            "desc": "0. Optimizador de Memoria (Purga de Obsoletos)",         "critico": False, "interactivo": False},

    # --- FASE 1: LIQUIDACION Y RECALIBRACION ---
    {"archivo": "motor_backtest.py",         "desc": "1. Liquidador de Goles (Cierre de Resultados)",          "critico": True,  "interactivo": False},
    {"archivo": "motor_liquidador.py",       "desc": "1.5. Liquidador de Apuestas (Auditoria de Resultados)",  "critico": True,  "interactivo": False},
    {"archivo": "scripts/evaluar_pretest.py", "desc": "1.6. Pretest Monitor (auto-flip LIVE/PRETEST por liga)", "critico": False, "interactivo": False},
    {"archivo": "motor_arbitro.py",          "desc": "2. El Inquisidor (Auditoria Arbitral y Tarjetas)",       "critico": False, "interactivo": False},
    {"archivo": "motor_data.py",             "desc": "3. Regresion Bayesiana (Actualizacion de Poderio)",      "critico": True,  "interactivo": False},

    # --- FASE 2: HORIZONTE FUTURO ---
    {"archivo": "motor_fixture.py",          "desc": "4. El Arquitecto (Proyeccion de Calendario)",            "critico": True,  "interactivo": True},
    {"archivo": "motor_tactico.py",          "desc": "5. El Analista (Formaciones y Vida de DTs)",             "critico": False, "interactivo": False},
    {"archivo": "motor_cuotas.py",           "desc": "6. El Oraculo (Extraccion de Precios y CLV)",            "critico": True,  "interactivo": False},
    {"archivo": "-m src.ingesta.motor_cuotas_apifootball", "desc": "6.5. Oraculo Sudamericano (API-Football)",     "critico": False, "interactivo": False},

    # --- FASE 3: DECISIONES ---
    {"archivo": "motor_calculadora.py",      "desc": "7. Cerebro Cuantitativo (Poisson, EV y Kelly)",          "critico": True,  "interactivo": False},

    # --- FASE 4: REDUNDANCIA + EXCEL ---
    {"archivo": "motor_backtest.py",         "desc": "8. Liquidador de Ultimo Minuto (Doble Barrido)",         "critico": False, "interactivo": False},
    {"archivo": "motor_liquidador.py",       "desc": "8.5. Liquidador de Apuestas (Barrido Final)",            "critico": False, "interactivo": False},
    {"archivo": "motor_sincronizador.py",    "desc": "9. Sincronizador Excel (Backtest + Dashboard + Sombra)", "critico": True,  "interactivo": False},
]


# ==========================================================================
# CATALOGO DE SCRIPTS DE ANALISIS PUNTUAL
# ==========================================================================
ANALISIS_DISPONIBLES = {
    'volumen':      ('scripts/analisis_volumen_yield.py', 'Train/test split + threshold test en filtros (busca oportunidades de volumen)'),
    'determinismo': ('scripts/analisis_determinismo.py',  'Testea temperature scaling sobre probs Poisson'),
    'ablation':     ('scripts/ablation_filtros.py',       'Ablation study: que pasa si quitamos cada filtro'),
    'ablation-liga':('scripts/ablation_por_liga.py',      'Ablation por liga (impacto de cada filtro por pais)'),
    'pretest':      ('scripts/evaluar_pretest.py --dry-run', 'Estado pretest mode por liga (dry-run, no cambia DB)'),
}


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
                cmd_full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', env=env,
            )
            full_stdout = ""
            while True:
                linea = proceso.stdout.readline()
                if not linea and proceso.poll() is not None:
                    break
                if linea:
                    full_stdout += linea
                    print(f"   | {linea.rstrip()}")
            stdout_resto, stderr = proceso.communicate()
            full_stdout += stdout_resto
            if proceso.returncode != 0:
                raise subprocess.CalledProcessError(
                    proceso.returncode, proceso.args,
                    output=full_stdout, stderr=stderr,
                )

        log_terminal(f"COMPLETADO en {round(time.time() - inicio, 2)}s", "EXITO")
        return True
    except subprocess.CalledProcessError as e:
        log_terminal(f"FALLO en {script_name}", "ERROR")
        stderr_txt = getattr(e, 'stderr', None)
        stdout_txt = getattr(e, 'output', None)
        print("\n--- TRAZA DE ERROR ---")
        print(stderr_txt if stderr_txt else stdout_txt or "(sin salida)")
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

    if not os.path.exists('fondo_quant.db'):
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
            if not cfg.get('api_key_football') and not cfg.get('api_keys_football'):
                warnings.append("config.json: no hay API key de api-football.com.")
        except (ValueError, IOError) as e:
            warnings.append(f"config.json corrupto: {e}")

    if not os.path.exists('motor_calculadora.py'):
        warnings.append("motor_calculadora.py no esta en raiz (shim roto?).")

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
        con = sqlite3.connect('fondo_quant.db')
        cur = con.cursor()

        print()
        print("--- APUESTAS ---")
        # Dos capas de metricas, porque el pipeline corre pretest (stake=0 para
        # recolectar hit rate antes de flipear a LIVE) + apuestas reales (stake>0):
        #   REALES   = stake_1x2>0 o stake_ou>0 (solo ligas en LIVE).
        #   PICKS    = apuesta LIKE '[APOSTAR]%' (incluye pretest).
        # Liquidadas = estado='Liquidado' + apuesta evaluada GANADA|PERDIDA.
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
        picks_vivos_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE apuesta_1x2 LIKE '[APOSTAR]%'"
        ).fetchone()[0]
        picks_vivos_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE apuesta_ou LIKE '[APOSTAR]%'"
        ).fetchone()[0]
        picks_eval_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE estado='Liquidado' "
            "AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')"
        ).fetchone()[0]
        picks_eval_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE estado='Liquidado' "
            "AND (apuesta_ou LIKE '[GANADA]%' OR apuesta_ou LIKE '[PERDIDA]%')"
        ).fetchone()[0]
        picks_g_1x2 = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE apuesta_1x2 LIKE '[GANADA]%'"
        ).fetchone()[0]
        picks_g_ou = cur.execute(
            "SELECT COUNT(*) FROM partidos_backtest WHERE apuesta_ou LIKE '[GANADA]%'"
        ).fetchone()[0]

        reales_vivas = reales_vivas_1x2 + reales_vivas_ou
        reales_liq = reales_liq_1x2 + reales_liq_ou
        reales_g = reales_g_1x2 + reales_g_ou
        hit_real = 100 * reales_g / reales_liq if reales_liq else None

        picks_vivos = picks_vivos_1x2 + picks_vivos_ou
        picks_eval = picks_eval_1x2 + picks_eval_ou
        picks_g = picks_g_1x2 + picks_g_ou
        hit_pick = 100 * picks_g / picks_eval if picks_eval else 0

        print(f"  REALES (stake>0):")
        print(f"    Vivas:            {reales_vivas:>4d}   (1X2:{reales_vivas_1x2}  O/U:{reales_vivas_ou})")
        print(f"    Liquidadas:       {reales_liq:>4d}   (1X2:{reales_liq_1x2}  O/U:{reales_liq_ou})")
        if hit_real is not None:
            print(f"    Hit real:        {hit_real:>4.1f}%   (ganadas {reales_g})")
        else:
            print(f"    Hit real:         N/A   (sin liquidaciones con stake>0 aun)")
        print(f"  PICKS (incluye pretest stake=0):")
        print(f"    Vivos:            {picks_vivos:>4d}   (1X2:{picks_vivos_1x2}  O/U:{picks_vivos_ou})")
        print(f"    Evaluados:        {picks_eval:>4d}   (1X2:{picks_eval_1x2}  O/U:{picks_eval_ou})")
        print(f"    Hit pretest:     {hit_pick:>4.1f}%   (ganados {picks_g})")

        print()
        print("--- PRETEST POR LIGA ---")
        rows = cur.execute("""
            SELECT pais, COUNT(*) n,
                SUM(CASE WHEN apuesta_1x2 LIKE '[GANADA]%' THEN 1 ELSE 0 END) g
            FROM partidos_backtest
            WHERE estado='Liquidado' AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%')
            GROUP BY pais ORDER BY n DESC
        """).fetchall()
        for pais, n, g in rows:
            hit_liga = 100 * g / n if n else 0
            # estado live?
            r = cur.execute(
                "SELECT valor_texto FROM config_motor_valores WHERE clave='apuestas_live' AND scope=?",
                (pais,)
            ).fetchone()
            live = (r and str(r[0]).upper() in ('TRUE', '1')) if r else False
            tag = "LIVE" if live else "pretest"
            print(f"  {pais:<12s} N={n:>3d}  hit={hit_liga:>5.1f}%  estado={tag}")

        print()
        print("--- CONFIG ACTUAL ---")
        for clave in ['floor_prob_min', 'margen_predictivo_1x2', 'consenso_prob_min',
                      'consenso_cuota_min', 'consenso_cuota_max',
                      'pretest_hit_threshold', 'pretest_n_minimo', 'pretest_p_max']:
            r = cur.execute(
                "SELECT valor_real FROM config_motor_valores WHERE clave=? AND scope='global'",
                (clave,)
            ).fetchone()
            print(f"  {clave:<25s} = {r[0] if r else '(default)'}")

        # Bankroll operativo (base + P/L acumulado si modo=dinamico, clampeado)
        print()
        print("--- BANKROLL ---")
        try:
            sys.path.insert(0, '.')
            from src.nucleo.motor_calculadora import obtener_bankroll_operativo
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

    # 3. Quota API-Football
    print()
    print("--- API-FOOTBALL QUOTA ---")
    try:
        sys.path.insert(0, '.')
        from src.comun.config_sistema import API_KEYS_FOOTBALL
        import requests
        total_restante = 0
        for i, key in enumerate(API_KEYS_FOOTBALL, 1):
            try:
                r = requests.get('https://v3.football.api-sports.io/status',
                                 headers={'x-apisports-key': key}, timeout=6)
                data = r.json().get('response', {})
                errs = r.json().get('errors', {})
                if errs:
                    print(f"  Key #{i}: ERROR {errs}")
                    continue
                req = data.get('requests', {})
                cur_ = req.get('current', 0)
                lim  = req.get('limit_day', 100)
                rest = lim - cur_
                total_restante += rest
                print(f"  Key #{i}: {cur_}/{lim}  ({rest} restantes hoy)")
            except Exception as e:
                print(f"  Key #{i}: sin respuesta ({e.__class__.__name__})")
        print(f"  TOTAL restante hoy: {total_restante} requests")
    except Exception as e:
        log_terminal(f"No pude chequear quota: {e}", "ALERTA")

    # 4. Ultima corrida (ver Excel modtime)
    print()
    if os.path.exists('Backtest_Modelo.xlsx'):
        mt = os.path.getmtime('Backtest_Modelo.xlsx')
        edad = datetime.now() - datetime.fromtimestamp(mt)
        horas = edad.total_seconds() / 3600
        print(f"--- ULTIMA CORRIDA ---")
        print(f"  Backtest_Modelo.xlsx: hace {horas:.1f}h ({datetime.fromtimestamp(mt).strftime('%d/%m/%Y %H:%M')})")
        if horas > 24:
            log_terminal("  Ultima corrida >24h. Considera ejecutar el pipeline.", "ALERTA")


# ==========================================================================
# SUBCOMANDO: --summary (resumen tras ultima corrida)
# ==========================================================================
def cmd_summary():
    """Stats desde el cierre de DB (post-ultima corrida)."""
    _imprimir_banner(f"SUMMARY DEL ULTIMO RUN — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        import sqlite3
        con = sqlite3.connect('fondo_quant.db')
        cur = con.cursor()

        # Picks nuevos de la ventana (hoy y manana)
        ayer = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        hoy = datetime.now().strftime('%Y-%m-%d')
        manana = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        pasado = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')

        print("\n--- PICKS VIVOS (proximas 72h) ---")
        for d in (hoy, manana, pasado):
            rows = cur.execute("""
                SELECT pais, apuesta_1x2, stake_1x2
                FROM partidos_backtest
                WHERE fecha LIKE ? AND apuesta_1x2 LIKE '[APOSTAR]%'
                ORDER BY pais, fecha
            """, (f'{d}%',)).fetchall()
            if rows:
                stake_dia = sum(r[2] or 0 for r in rows)
                live_dia = sum(1 for r in rows if (r[2] or 0) > 0)
                print(f"  {d}: {len(rows)} picks ({live_dia} LIVE con stake>0, stake total ${stake_dia:.2f})")

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
        print("\n--- COBERTURA CUOTAS (partidos vivos) ---")
        rows = cur.execute("""
            SELECT pais, COUNT(*) tot, SUM(CASE WHEN cuota_1 > 0 THEN 1 ELSE 0 END) con
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
# SUBCOMANDO: --analisis [nombre]
# ==========================================================================
def cmd_analisis(nombre=None):
    """Dispara un script de analisis puntual del catalogo ANALISIS_DISPONIBLES."""
    if not nombre:
        _imprimir_banner("ANALISIS DISPONIBLES")
        for key, (script, desc) in ANALISIS_DISPONIBLES.items():
            print(f"  --analisis {key:<15s} {desc}")
            print(f"  {'':<15s} -> {script}")
            print()
        print("Uso: py ejecutar_proyecto.py --analisis <nombre>")
        return

    if nombre not in ANALISIS_DISPONIBLES:
        log_terminal(f"Analisis '{nombre}' no existe. Opciones: {list(ANALISIS_DISPONIBLES.keys())}", "ERROR")
        sys.exit(1)

    script, desc = ANALISIS_DISPONIBLES[nombre]
    _imprimir_banner(f"ANALISIS: {nombre} — {desc}")
    ejecutar_motor(script, desc, interactivo=False)


# ==========================================================================
# SUBCOMANDO: --help
# ==========================================================================
def cmd_help():
    print(__doc__)
    print("\nMotores en la cascada diaria:")
    for m in MOTORES_DIARIOS:
        marca = ' [CRITICO]' if m['critico'] else ''
        print(f"  {m['archivo']:<42s} {m['desc']}{marca}")
    print("\nAnalisis disponibles:")
    for k, (s, d) in ANALISIS_DISPONIBLES.items():
        print(f"  --analisis {k:<15s} {d}")


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
    if comando == '--analisis':
        nombre = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_analisis(nombre)
        return

    # Subcomandos de mantenimiento (disparan sub-pipelines y luego cascada)
    if comando == '--rebuild':
        log_terminal("MODO RECONSTRUCCION MAESTRA DESDE CSV", "ALERTA")
        ejecutar_motor('importador_gold.py',       '1/3: Reconstruccion desde Gold Standard')
        ejecutar_motor('-m src.persistencia.reset_tablas_derivadas', '2/3: Purga de Tablas Derivadas')
        ejecutar_motor('-m src.nucleo.desbloquear_matriz',          '3/3: Desbloqueo de Matriz de Partidos')
        log_terminal("Fase de reconstruccion finalizada. Iniciando pipeline principal.", "EXITO")
        cmd_pipeline_diario()
        return
    if comando == '--unlock':
        log_terminal("MODO DESBLOQUEO DE MATRIZ", "ALERTA")
        ejecutar_motor('-m src.nucleo.desbloquear_matriz', 'Desbloqueo de Matriz de Partidos')
        log_terminal("Matriz desbloqueada. Iniciando pipeline principal.", "EXITO")
        cmd_pipeline_diario()
        return
    if comando == '--purge-history':
        log_terminal("MODO PURGA DE HISTORIAL", "ALERTA")
        ejecutar_motor('-m src.persistencia.reset_tablas_derivadas', 'Purga de Tablas Derivadas')
        log_terminal("Tablas derivadas purgadas. Iniciando pipeline principal.", "EXITO")
        cmd_pipeline_diario()
        return
    if comando == '--audit-names':
        log_terminal("MODO AUDITORIA INTERACTIVA DE NOMBRES", "ALERTA")
        ejecutar_motor('auditor/auditor_espn.py', 'Auditoria Interactiva de Nombres (ESPN vs. Diccionario)')
        log_terminal("Auditoria finalizada.", "EXITO")
        return

    # Comando desconocido
    log_terminal(f"Comando desconocido: {comando}", "ERROR")
    cmd_help()
    sys.exit(1)


if __name__ == "__main__":
    main()

import subprocess
import time
import sys
import os
from datetime import datetime

# Forzar UTF-8 en stdout/stderr del orquestador. Sin esto, Windows default cp1252
# rompe con cualquier caracter no latino-1 (turco 'ş', emojis, flechas Unicode, etc.)
# leido del subprocess al re-imprimir cada linea capturada (linea ~84).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ==========================================
# ORQUESTADOR CUANTITATIVO V7.0 (MODOS DE EJECUCIÓN INTEGRADOS)
# Responsabilidad: Ejecución en Cascada, Aislamiento y Control por Argumentos.
# ==========================================

MOTORES_DIARIOS = [
    # --- FASE 0: MANTENIMIENTO Y OPTIMIZACIÓN ---
    {"archivo": "motor_purga.py",        "desc": "0. Optimizador de Memoria (Purga de Obsoletos)",          "critico": False, "interactivo": False},

    # --- FASE 1: LIQUIDACIÓN Y RECALIBRACIÓN (PASADO) ---
    {"archivo": "motor_backtest.py",     "desc": "1. Liquidador de Goles (Cierre de Resultados)",           "critico": True,  "interactivo": False},
    {"archivo": "motor_liquidador.py",   "desc": "1.5. Liquidador de Apuestas (Auditoría de Resultados)",   "critico": True,  "interactivo": False},
    {"archivo": "motor_arbitro.py",      "desc": "2. El Inquisidor (Auditoría Arbitral y Tarjetas)",        "critico": False, "interactivo": False},
    {"archivo": "motor_data.py",         "desc": "3. Regresión Bayesiana (Actualización de Poderío)",       "critico": True,  "interactivo": False},

    # --- FASE 2: CONSTRUCCIÓN DEL HORIZONTE (FUTURO) ---
    # interactivo=True: motor_fixture puede pedir al usuario que nombre equipos nuevos
    {"archivo": "motor_fixture.py",      "desc": "4. El Arquitecto (Proyección de Calendario)",             "critico": True,  "interactivo": True},
    {"archivo": "motor_tactico.py",      "desc": "5. El Analista (Formaciones y Vida de DTs)",              "critico": False, "interactivo": False},
    {"archivo": "motor_cuotas.py",       "desc": "6. El Oráculo (Extracción de Precios y CLV)",             "critico": True,  "interactivo": False},

    # --- FASE 3: TOMA DE DECISIONES ---
    {"archivo": "motor_calculadora.py",  "desc": "7. Cerebro Cuantitativo (Poisson, EV y Kelly)",           "critico": True,  "interactivo": False},

    # --- FASE 4: REDUNDANCIA Y PROYECCIÓN VISUAL ---
    {"archivo": "motor_backtest.py",     "desc": "8. Liquidador de Último Minuto (Doble Barrido)",          "critico": False, "interactivo": False},
    {"archivo": "motor_liquidador.py",   "desc": "8.5. Liquidador de Apuestas (Barrido Final)",             "critico": False, "interactivo": False},
    {"archivo": "motor_sincronizador.py","desc": "9. Sincronizador de Alta Velocidad",                      "critico": True,  "interactivo": False},
]

def log_terminal(mensaje, nivel="INFO"):
    colores = {
        "INFO": "\033[94m",     # Azul
        "EXITO": "\033[92m",    # Verde
        "ALERTA": "\033[93m",   # Amarillo
        "ERROR": "\033[91m",    # Rojo
        "END": "\033[0m"
    }
    hora = datetime.now().strftime("%H:%M:%S")
    color = colores.get(nivel, colores["END"])
    print(f"{color}[{hora}] {nivel} - {mensaje}{colores['END']}")

def ejecutar_motor(script_name, descripcion, interactivo=False):
    print(f"\n> INICIANDO: {descripcion}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    inicio = time.time()

    try:
        if interactivo:
            # Modo interactivo: stdout/stderr/stdin van directo a la terminal.
            # El usuario puede responder preguntas (nombres de equipos nuevos, etc.)
            proceso = subprocess.run(
                [sys.executable, '-u', script_name],
                env=env
            )
            fin = time.time()
            if proceso.returncode != 0:
                raise subprocess.CalledProcessError(proceso.returncode, script_name)
        else:
            # Modo normal: capturamos stdout en tiempo real y mostramos cada linea.
            proceso = subprocess.Popen(
                [sys.executable, '-u', script_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env
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
            fin = time.time()

            if proceso.returncode != 0:
                raise subprocess.CalledProcessError(
                    proceso.returncode, proceso.args,
                    output=full_stdout, stderr=stderr
                )

        log_terminal(f"COMPLETADO en {round(time.time() - inicio, 2)}s", "EXITO")
        return True

    except subprocess.CalledProcessError as e:
        log_terminal(f"FALLO CRITICO en {script_name}", "ERROR")
        stderr_txt = getattr(e, 'stderr', None)
        stdout_txt = getattr(e, 'output', None)
        print("\n--- TRAZA DE ERROR DEL MOTOR ---")
        print(stderr_txt if stderr_txt else stdout_txt or "(sin salida)")
        print("--------------------------------\n")
        return False
    except FileNotFoundError:
        log_terminal(f"Archivo no encontrado: {script_name}. Verifica tu directorio.", "ERROR")
        return False

def main():
    # Limpieza visual de la consola según el sistema operativo
    os.system('cls' if os.name == 'nt' else 'clear')

    # --- FASE -1: PROCESAMIENTO DE ARGUMENTOS DE LÍNEA DE COMANDOS ---
    if len(sys.argv) > 1:
        comando = sys.argv[1]
        if comando == '--rebuild':
            log_terminal("MODO RECONSTRUCCIÓN MAESTRA DESDE CSV", "ALERTA")
            ejecutar_motor('importador_gold.py', '1/3: Reconstrucción desde Gold Standard')
            ejecutar_motor('reset_tablas_derivadas.py', '2/3: Purga de Tablas Derivadas')
            ejecutar_motor('desbloquear_matriz.py', '3/3: Desbloqueo de Matriz de Partidos')
            log_terminal("Fase de reconstrucción finalizada. Iniciando pipeline principal.", "EXITO")
        elif comando == '--unlock':
            log_terminal("MODO DESBLOQUEO DE MATRIZ", "ALERTA")
            ejecutar_motor('desbloquear_matriz.py', 'Desbloqueo de Matriz de Partidos')
            log_terminal("Matriz desbloqueada. Iniciando pipeline principal.", "EXITO")
        elif comando == '--purge-history':
            log_terminal("MODO PURGA DE HISTORIAL", "ALERTA")
            ejecutar_motor('reset_tablas_derivadas.py', 'Purga de Tablas Derivadas')
            log_terminal("Tablas derivadas purgadas. Iniciando pipeline principal.", "EXITO")
        elif comando == '--audit-names':
            log_terminal("MODO AUDITORÍA INTERACTIVA DE NOMBRES", "ALERTA")
            ejecutar_motor('auditor_espn.py', 'Auditoría Interactiva de Nombres (ESPN vs. Diccionario)')
            log_terminal("Auditoría de nombres finalizada. El pipeline principal NO se ejecutará.", "EXITO")
            sys.exit(0)
    
    print("="*70)
    print(f"[*] PIPELINE CUANTITATIVO V7.0 INICIADO - {datetime.now().strftime('%d/%m/%Y')}")
    print("="*70)
    
    inicio_total = time.time()

    for motor in MOTORES_DIARIOS:
        exito = ejecutar_motor(motor["archivo"], motor["desc"], motor.get("interactivo", False))
        
        if not exito:
            if motor["critico"]:
                log_terminal("ABORTO DE EMERGENCIA: Se ha detenido la cascada para proteger el capital.", "ERROR")
                sys.exit(1)
            else:
                log_terminal("Continuando ejecución degradada (un motor satélite falló)...", "ALERTA")

    total_seg = round(time.time() - inicio_total, 2)
    print("\n" + "="*70)
    log_terminal(f"OPERACIÓN EXITOSA. Pipeline completado en {total_seg} segundos.", "EXITO")
    print("="*70)

if __name__ == "__main__":
    main()
import subprocess
import time
import sys 
import os
from datetime import datetime

# ==========================================
# ORQUESTADOR CUANTITATIVO V7.0 (MODOS DE EJECUCIÓN INTEGRADOS)
# Responsabilidad: Ejecución en Cascada, Aislamiento y Control por Argumentos.
# ==========================================

MOTORES_DIARIOS = [
    # --- FASE 0: MANTENIMIENTO Y OPTIMIZACIÓN ---
    {"archivo": "motor_purga.py", "desc": "0. Optimizador de Memoria (Purga de Obsoletos)", "critico": False},

    # --- FASE 1: LIQUIDACIÓN Y RECALIBRACIÓN (PASADO) ---
    {"archivo": "motor_backtest.py", "desc": "1. Liquidador de Goles (Cierre de Resultados)", "critico": True},
    {"archivo": "motor_liquidador.py", "desc": "1.5. Liquidador de Apuestas (Auditoría de Resultados)", "critico": True},
    {"archivo": "motor_arbitro.py", "desc": "2. El Inquisidor (Auditoría Arbitral y Tarjetas)", "critico": False},
    {"archivo": "motor_data.py", "desc": "3. Regresión Bayesiana (Actualización de Poderío)", "critico": True},
    
    # --- FASE 2: CONSTRUCCIÓN DEL HORIZONTE (FUTURO) ---
    {"archivo": "motor_fixture.py", "desc": "4. El Arquitecto (Proyección de Calendario)", "critico": True},
    {"archivo": "motor_tactico.py", "desc": "5. El Analista (Formaciones y Vida de DTs)", "critico": False},
    {"archivo": "motor_cuotas.py", "desc": "6. El Oráculo (Extracción de Precios y CLV)", "critico": True},
    
    # --- FASE 3: TOMA DE DECISIONES ---
    {"archivo": "motor_calculadora.py", "desc": "7. Cerebro Cuantitativo (Poisson, EV y Kelly)", "critico": True},
    
    # --- FASE 4: REDUNDANCIA Y PROYECCIÓN VISUAL ---
    {"archivo": "motor_backtest.py", "desc": "8. Liquidador de Último Minuto (Doble Barrido)", "critico": False},
    {"archivo": "motor_liquidador.py", "desc": "8.5. Liquidador de Apuestas (Barrido Final)", "critico": False},
    {"archivo": "motor_sincronizador.py", "desc": "9. Sincronizador de Alta Velocidad", "critico": True}
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

def ejecutar_motor(script_name, descripcion):
    print(f"\n➤ INICIANDO: {descripcion}")
    try:
        # Forzamos codificación UTF-8 para evitar errores con tildes o caracteres de equipos
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        inicio = time.time()
        # Usamos Popen para capturar la salida en tiempo real. El flag -u es crucial.
        proceso = subprocess.Popen(
            [sys.executable, '-u', script_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        # Leemos y mostramos la salida de progreso línea por línea
        full_stdout = ""
        while True:
            linea_stdout = proceso.stdout.readline()
            if not linea_stdout and proceso.poll() is not None:
                break
            if linea_stdout:
                full_stdout += linea_stdout
                linea_strip = linea_stdout.strip()
                if (linea_strip.startswith("[SISTEMA]") or
                    linea_strip.startswith("[PROCESO]") or
                    linea_strip.startswith("[INFO]") or
                    linea_strip.startswith("[ALERTA]") or
                    linea_strip.startswith("[EXITO]") or
                    linea_strip.startswith("[ERROR]")):
                    print(f"   ↳ {linea_strip}")
        
        # Esperamos a que termine y capturamos cualquier salida restante (especialmente errores)
        stdout_resto, stderr = proceso.communicate()
        full_stdout += stdout_resto

        fin = time.time()
        
        if proceso.returncode != 0:
            raise subprocess.CalledProcessError(proceso.returncode, proceso.args, output=full_stdout, stderr=stderr)

        log_terminal(f"COMPLETADO en {round(fin - inicio, 2)}s", "EXITO")
        return True
        
    except subprocess.CalledProcessError as e:
        log_terminal(f"FALLO CRÍTICO en {script_name}", "ERROR")
        print("\n--- TRAZA DE ERROR DEL MOTOR ---")
        print(e.stderr if e.stderr else e.stdout)
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
    print(f"⚙️ PIPELINE CUANTITATIVO V7.0 INICIADO - {datetime.now().strftime('%d/%m/%Y')}")
    print("="*70)
    
    inicio_total = time.time()

    for motor in MOTORES_DIARIOS:
        exito = ejecutar_motor(motor["archivo"], motor["desc"])
        
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
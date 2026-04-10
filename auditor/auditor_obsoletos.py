import ast
import os
import sys
import re
from pathlib import Path

# ==========================================
# AUDITOR DE OBSOLETOS V1.0
# Detecta archivos Python y funciones sin referencias activas en el proyecto.
# NO borra nada - solo reporta con justificacion para revision manual.
# Uso: .venv\Scripts\python.exe auditor\auditor_obsoletos.py
# ==========================================

RAIZ = Path(__file__).parent.parent

# Archivos que son puntos de entrada o utilidades de emergencia -- nunca se importan
# directamente pero tienen proposito legitimo. Excluirlos del analisis de huerfanos.
WHITELIST_ARCHIVOS = {
    "ejecutar_proyecto",       # orquestador principal (entry point)
    "importador_gold",         # utilidad de emergencia --rebuild
    "reset_tablas_derivadas",  # utilidad de emergencia --rebuild
    "desbloquear_matriz",      # utilidad de emergencia --unlock
    "calibrar_rho",            # calibracion manual, se corre a demanda
    "adepor_guard",            # proteccion DB, se corre a demanda
    "gestor_nombres",          # importado por varios motores
    "config_sistema",          # importado por todos, siempre activo
}

# Patrones en comentarios/docstrings que indican codigo intencionalmente retenido
PATRONES_RETENIDO = [
    r"REVERTID",
    r"NO se aplica",
    r"referencia historica",
    r"puede activar",
    r"grupo de control",
    r"SHADOW",
]

# Funciones con proposito documentado aunque no se llamen externamente
WHITELIST_FUNCIONES = {
    "corregir_ventaja_local",  # revertida pero retenida como referencia (Manifiesto C3)
    "main",                    # entry point estandar
    "procesar_tactica",        # llamada por ejecutar_proyecto via subprocess
}


def obtener_archivos_py(raiz):
    """Todos los .py del proyecto excepto __pycache__ y .venv."""
    return [
        p for p in raiz.rglob("*.py")
        if ".venv" not in p.parts and "__pycache__" not in p.parts
    ]


def extraer_nombres_definidos(filepath):
    """Devuelve set de funciones y clases definidas en un archivo."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def extraer_imports(filepath):
    """Devuelve set de modulos importados (nombre base sin extension)."""
    imports = set()
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def extraer_llamadas(filepath):
    """Devuelve set de nombres de funciones/metodos llamados en un archivo."""
    llamadas = set()
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return llamadas
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                llamadas.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                llamadas.add(node.func.attr)
    return llamadas


def tiene_patron_retenido(filepath, nombre_funcion):
    """Verifica si hay comentario/docstring cercano que justifique retener la funcion."""
    contenido = filepath.read_text(encoding="utf-8", errors="replace")
    lineas = contenido.splitlines()
    for i, linea in enumerate(lineas):
        if f"def {nombre_funcion}" in linea:
            contexto = "\n".join(lineas[max(0, i - 2):i + 15])
            for patron in PATRONES_RETENIDO:
                if re.search(patron, contexto, re.IGNORECASE):
                    return True
    return False


def auditar():
    archivos = obtener_archivos_py(RAIZ)
    archivos_raiz = [a for a in archivos if a.parent == RAIZ]

    # --- 1. ARCHIVOS HUERFANOS (no importados por nadie) ---
    todos_los_imports = set()
    for arch in archivos:
        todos_los_imports |= extraer_imports(arch)

    # Tambien capturar referencias como strings en ejecutar_proyecto (subprocess)
    ep = RAIZ / "ejecutar_proyecto.py"
    if ep.exists():
        stems_ep = re.findall(r"['\"](\w+)\.py['\"]", ep.read_text(encoding="utf-8", errors="replace"))
        todos_los_imports |= set(stems_ep)

    huerfanos = []
    for arch in archivos_raiz:
        nombre_mod = arch.stem
        if nombre_mod in WHITELIST_ARCHIVOS or nombre_mod.startswith("_"):
            continue
        if nombre_mod not in todos_los_imports:
            huerfanos.append(arch)

    # --- 2. FUNCIONES SIN REFERENCIAS EXTERNAS (en motores activos) ---
    todas_las_llamadas = set()
    for arch in archivos:
        todas_las_llamadas |= extraer_llamadas(arch)

    funciones_muertas = []
    MOTORES_ACTIVOS = {
        "motor_calculadora", "motor_data", "motor_backtest", "motor_fixture",
        "motor_cuotas", "motor_sincronizador", "motor_arbitro", "motor_tactico",
        "motor_liquidador", "motor_purga", "utilidades",
    }
    for arch in archivos_raiz:
        if arch.stem not in MOTORES_ACTIVOS:
            continue
        definidas = extraer_nombres_definidos(arch)
        for nombre in definidas:
            if nombre in WHITELIST_FUNCIONES:
                continue
            if nombre.startswith("_"):
                continue  # helpers internos por convencion
            if nombre not in todas_las_llamadas:
                if not tiene_patron_retenido(arch, nombre):
                    funciones_muertas.append((arch.name, nombre))

    # --- 3. REPORTE ---
    SEP = "=" * 65
    sep = "-" * 65

    print(SEP)
    print("  AUDITOR DE OBSOLETOS V1.0 - Proyecto Adepor")
    print(SEP)

    print(f"\n{sep}")
    print("  [1] ARCHIVOS HUERFANOS  (no importados por ningun motor)")
    print(sep)
    if huerfanos:
        for arch in huerfanos:
            print(f"  [!] {arch.name}")
        print(f"\n  -> {len(huerfanos)} archivo(s) sin referencias detectados.")
        print("  -> Verificar proposito antes de eliminar.")
    else:
        print("  [OK] Ninguno.")

    print(f"\n{sep}")
    print("  [2] FUNCIONES SIN REFERENCIAS EXTERNAS")
    print(sep)
    if funciones_muertas:
        archivo_actual = None
        for archivo, funcion in sorted(funciones_muertas):
            if archivo != archivo_actual:
                print(f"\n  {archivo}")
                archivo_actual = archivo
            print(f"     [!] def {funcion}()")
        print(f"\n  -> {len(funciones_muertas)} funcion(es) sin llamadas externas detectadas.")
        print("  -> Pueden ser helpers internos sin prefijo '_' o codigo muerto.")
    else:
        print("  [OK] Ninguna.")

    print(f"\n{sep}")
    print("  NOTA: Este auditor NO borra nada.")
    print("  Revisa cada item antes de eliminar manualmente.")
    print(f"{sep}\n")


if __name__ == "__main__":
    auditar()

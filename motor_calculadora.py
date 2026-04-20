# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/nucleo/motor_calculadora.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.nucleo.motor_calculadora`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.nucleo.motor_calculadora import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.nucleo.motor_calculadora import main
    main()

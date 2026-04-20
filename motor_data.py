# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/ingesta/motor_data.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.ingesta.motor_data`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.ingesta.motor_data import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.ingesta.motor_data import main
    main()

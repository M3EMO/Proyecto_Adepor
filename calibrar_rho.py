# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/nucleo/calibrar_rho.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.nucleo.calibrar_rho`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.nucleo.calibrar_rho import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.nucleo.calibrar_rho import main
    main()

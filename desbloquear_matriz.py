# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/nucleo/desbloquear_matriz.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.nucleo.desbloquear_matriz`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.nucleo.desbloquear_matriz import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.nucleo.desbloquear_matriz import main
    main()

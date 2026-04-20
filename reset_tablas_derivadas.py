# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/persistencia/reset_tablas_derivadas.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.persistencia.reset_tablas_derivadas`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.persistencia.reset_tablas_derivadas import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.persistencia.reset_tablas_derivadas import main
    main()

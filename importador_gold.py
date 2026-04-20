# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/persistencia/importador_gold.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.persistencia.importador_gold`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.persistencia.importador_gold import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.persistencia.importador_gold import main
    main()

# SHIM DE RETROCOMPATIBILIDAD — retirar tras auditar callers en auditor/, analisis/, archivo/. TODO: fase 2.
# Fuente canónica: src/comun/config_sistema.py
# Inventario de callers externos en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.comun.config_sistema import *  # noqa: F401,F403

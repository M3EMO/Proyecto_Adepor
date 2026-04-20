"""
Mapas derivados compartidos entre motores.

MAPA_LIGAS_ESPN: inverso de LIGAS_ESPN (pais -> codigo ESPN).
Derivado una sola vez al importar este módulo.
"""

from src.comun.config_sistema import LIGAS_ESPN


def obtener_mapa_espn():
    """Invierte LIGAS_ESPN a {pais: codigo_espn}."""
    return {pais: codigo for codigo, pais in LIGAS_ESPN.items()}


MAPA_LIGAS_ESPN = obtener_mapa_espn()

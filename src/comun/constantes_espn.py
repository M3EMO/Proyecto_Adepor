"""
Constantes de estados ESPN API (literales del endpoint scoreboard).

Strings bloqueados: corresponden a valores devueltos por ESPN en
events[].status.type.name, no pueden modificarse sin actualizar la API.
"""

STATUS_FINAL = 'STATUS_FINAL'
STATUS_FULL_TIME = 'STATUS_FULL_TIME'

ESTADOS_ESPN_FINALIZADO = (STATUS_FINAL, STATUS_FULL_TIME)

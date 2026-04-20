"""
Resolución de apuestas: tres variantes de firma según el consumidor.

Cada motor históricamente implementaba su propia versión por necesidades
distintas de tipo de retorno. Se centralizan acá sin unificar: los tres
formatos conviven porque cada uno tiene caller-sites que dependen del
shape exacto del valor retornado.

- `determinar_resultado_string` (motor_calculadora): "GANADA"/"PERDIDA"/"INDETERMINADO".
  Requiere apuesta con `[APOSTAR]` pendiente; devuelve resultado de la apuesta.

- `determinar_resultado_token` (motor_liquidador): "[GANADA]"/"[PERDIDA]"/None.
  Produce el token bracketed que reemplaza a `[APOSTAR]` al liquidar.
  None si la apuesta no es evaluable o no está pendiente.

- `determinar_resultado_entero` (motor_sincronizador): 1/-1/0.
  Acepta apuestas ya liquidadas (detecta `[GANADA]/[PERDIDA]` previos)
  o pendientes (`[APOSTAR]` + goles). Fallback 0 para indeterminado.

Palabras clave soportadas en los tres: LOCAL, EMPATE, VISITA, OVER 2.5, UNDER 2.5.
"""


def determinar_resultado_string(apuesta, gl, gv):
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"
    if "LOCAL" in apuesta: return "GANADA" if gl > gv else "PERDIDA"
    if "EMPATE" in apuesta: return "GANADA" if gl == gv else "PERDIDA"
    if "VISITA" in apuesta: return "GANADA" if gl < gv else "PERDIDA"
    if "OVER 2.5" in apuesta: return "GANADA" if (gl + gv) > 2.5 else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl + gv) < 2.5 else "PERDIDA"
    return "INDETERMINADO"


def determinar_resultado_token(apuesta, gl, gv):
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return None
    if "LOCAL" in apuesta: return "[GANADA]" if gl > gv else "[PERDIDA]"
    if "EMPATE" in apuesta: return "[GANADA]" if gl == gv else "[PERDIDA]"
    if "VISITA" in apuesta: return "[GANADA]" if gl < gv else "[PERDIDA]"
    if "OVER 2.5" in apuesta: return "[GANADA]" if (gl + gv) > 2.5 else "[PERDIDA]"
    if "UNDER 2.5" in apuesta: return "[GANADA]" if (gl + gv) < 2.5 else "[PERDIDA]"
    return None


def determinar_resultado_entero(apuesta, gl, gv):
    ap = str(apuesta or "")
    if "[GANADA]"  in ap: return  1
    if "[PERDIDA]" in ap: return -1
    if "[APOSTAR]" in ap and gl is not None and gv is not None:
        if "LOCAL"  in ap: return  1 if gl > gv  else -1
        if "EMPATE" in ap: return  1 if gl == gv else -1
        if "VISITA" in ap: return  1 if gl < gv  else -1
        total = gl + gv
        if "OVER"  in ap: return  1 if total > 2.5 else -1
        if "UNDER" in ap: return  1 if total < 2.5 else -1
    return 0

"""Helpers canonicos para mapear pick-token -> cuota.

Origen: refactor adepor-6ph. Antes habia dos helpers casi-identicos en
motor_cuotas.py (_seleccionar_cuota_cierre) y motor_liquidador.py
(_cuota_apostada_para_pick) con estilos distintos. Esta version unifica
la logica en un solo punto.

Tokens reconocidos (despues del prefijo):
    reales (DB):  'LOCAL', 'EMPATE', 'VISITA', 'OVER 2.5', 'UNDER 2.5'
    legacy:       '1', 'X', '2', 'OVER', 'UNDER'
Prefijos reconocidos: '[APOSTAR]' (pendiente), '[GANADA]' y '[PERDIDA]' (liquidado).

Si el string no tiene prefijo conocido o el pick no esta en el set
reconocido, retorna 0.0 (no romper).
"""

PICKS_VALIDOS = ("1", "X", "2", "OVER", "UNDER")
_PREFIJOS = ("[APOSTAR]", "[GANADA]", "[PERDIDA]")
_CANONICO = {
    "LOCAL": "1", "EMPATE": "X", "VISITA": "2", "OVER 2.5": "OVER", "UNDER 2.5": "UNDER",
    "1": "1", "X": "X", "2": "2", "OVER": "OVER", "UNDER": "UNDER",
}


def _pick_canonico(apuesta_str):
    """Token DB -> '1'/'X'/'2'/'OVER'/'UNDER'. None si no aplica o no reconocido."""
    if not apuesta_str:
        return None
    s = str(apuesta_str).strip().upper()
    prefijo = next((p for p in _PREFIJOS if s.startswith(p)), None)
    if prefijo is None:
        return None
    return _CANONICO.get(s[len(prefijo):].strip())


def cuota_para_pick(apuesta_str, c1, cx, c2, co, cu):
    """Mapea apuesta token -> cuota correspondiente.

    Args:
        apuesta_str: string tipo '[APOSTAR] LOCAL', '[GANADA] OVER 2.5', etc.; None / vacio OK
        c1, cx, c2: cuotas 1X2 (None tolerable, retorna 0.0)
        co, cu: cuotas Over/Under 2.5 (None tolerable, retorna 0.0)

    Returns:
        float: cuota correspondiente al pick, 0.0 si no aplica o no reconocido.
    """
    pick = _pick_canonico(apuesta_str)
    if pick == "1":
        return c1 or 0.0
    if pick == "X":
        return cx or 0.0
    if pick == "2":
        return c2 or 0.0
    if pick == "OVER":
        return co or 0.0
    if pick == "UNDER":
        return cu or 0.0
    return 0.0


def es_pick_valido(apuesta_str):
    """True si el string representa un pick activo y reconocido."""
    return _pick_canonico(apuesta_str) in PICKS_VALIDOS

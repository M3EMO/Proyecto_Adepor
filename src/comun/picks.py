"""Helpers canonicos para mapear pick-token -> cuota.

Origen: refactor adepor-6ph. Antes habia dos helpers casi-identicos en
motor_cuotas.py (_seleccionar_cuota_cierre) y motor_liquidador.py
(_cuota_apostada_para_pick) con estilos distintos. Esta version unifica
la logica en un solo punto.

Tokens reconocidos: '[APOSTAR] 1', '[APOSTAR] X', '[APOSTAR] 2',
                    '[APOSTAR] OVER', '[APOSTAR] UNDER'.

Si el string no empieza con '[APOSTAR]' o el pick no esta en el set
reconocido, retorna 0.0 (no romper).
"""

PICKS_VALIDOS = ("1", "X", "2", "OVER", "UNDER")


def cuota_para_pick(apuesta_str, c1, cx, c2, co, cu):
    """Mapea apuesta token -> cuota correspondiente.

    Args:
        apuesta_str: string tipo '[APOSTAR] X' o similar; None / vacio OK
        c1, cx, c2: cuotas 1X2 (None tolerable, retorna 0.0)
        co, cu: cuotas Over/Under 2.5 (None tolerable, retorna 0.0)

    Returns:
        float: cuota correspondiente al pick, 0.0 si no aplica o no reconocido.
    """
    if not apuesta_str:
        return 0.0
    s = str(apuesta_str).strip().upper()
    if not s.startswith("[APOSTAR]"):
        return 0.0
    pick = s.replace("[APOSTAR]", "").strip()

    # Mapping canonico
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
    if not apuesta_str:
        return False
    s = str(apuesta_str).strip().upper()
    if not s.startswith("[APOSTAR]"):
        return False
    pick = s.replace("[APOSTAR]", "").strip()
    return pick in PICKS_VALIDOS

#!/usr/bin/env python3
"""
Hook TaskCreated para Claude Code agent teams.

Bloquea creacion de tasks que tocan archivos del Manifiesto sin tag aprobado.

Inputs (stdin JSON, shape segun doc Claude Code):
  - task.title / task.description / task.acceptance_criteria
  - se inspeccionan TODOS los campos textuales para safety

Reglas:
  1. Si menciona "Reglas_IA.txt", el body debe incluir
     MANIFESTO-CHANGE-APPROVED:<bead_id> o exit 2.
  2. Si menciona modificacion de constantes del nucleo (motor_calculadora.py
     constantes ALFA_*, RHO_*, FACTOR_CORR_*, FLOOR_PROB_MIN, etc.), idem.

Exit code:
  0  = OK, dejar pasar.
  2  = bloquear, mensaje al stderr (Claude muestra al usuario).
  1+ = error inesperado, NO bloquea por seguridad (fail-open).
"""
import json
import re
import sys


# Patrones que disparan validacion estricta
PATRONES_MANIFIESTO = [
    re.compile(r'\bReglas_IA\.txt\b', re.IGNORECASE),
    re.compile(r'\bmanifest', re.IGNORECASE),
    re.compile(r'\bmotor_calculadora\.py\b', re.IGNORECASE),
]

CONSTANTES_PROTEGIDAS = [
    'ALFA_EMA', 'N0_ANCLA', 'RHO_FALLBACK', 'FACTOR_CORR_XG_OU',
    'FLOOR_PROB_MIN', 'MARGEN_PREDICTIVO_1X2', 'CORR_VISITA',
    'MAX_KELLY_PCT_NORMAL', 'MAX_KELLY_PCT_DRAWDOWN',
]

TAG_APROBADO = re.compile(r'MANIFESTO-CHANGE-APPROVED\s*:\s*(bd-[\w-]+|HUMAN)', re.IGNORECASE)


def _texto_de_task(payload):
    """Concatena TODO el texto relevante de la task (defensivo ante cambios de shape)."""
    pieces = []
    task = payload.get('task') or payload  # shape variable; fallback a top-level
    for key in ('title', 'description', 'body', 'content', 'acceptance_criteria',
                'spec', 'notes'):
        val = task.get(key) if isinstance(task, dict) else None
        if isinstance(val, str):
            pieces.append(val)
        elif isinstance(val, list):
            pieces.extend(str(x) for x in val)
    # Concat tambien el JSON entero como fallback (cualquier campo nuevo pasa)
    pieces.append(json.dumps(payload, ensure_ascii=False))
    return '\n'.join(pieces)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Fail-open: no bloqueamos por error de parsing
        sys.stderr.write("[hook validate_task_created] WARN: stdin no es JSON valido, dejando pasar.\n")
        return 0

    texto = _texto_de_task(payload)

    # Disparadores
    dispara_manifiesto = any(p.search(texto) for p in PATRONES_MANIFIESTO)
    constantes_mencionadas = [c for c in CONSTANTES_PROTEGIDAS if c in texto]

    if not dispara_manifiesto and not constantes_mencionadas:
        return 0  # nada que validar

    # Hay algo sensible: requerir tag aprobado
    if not TAG_APROBADO.search(texto):
        razones = []
        if dispara_manifiesto:
            razones.append("la task menciona Reglas_IA.txt o motor_calculadora.py")
        if constantes_mencionadas:
            razones.append(f"menciona constantes protegidas: {', '.join(constantes_mencionadas)}")
        msg = (
            "[BLOQUEADO] TaskCreated rechazada por hook validate_task_created.\n"
            f"Motivo: {'; '.join(razones)}.\n"
            "Para tareas que tocan el Manifiesto Cuantitativo, primero crear bead "
            "[PROPOSAL: MANIFESTO CHANGE], esperar autorizacion humana, y luego incluir "
            "en la descripcion de esta task el tag:\n"
            "  MANIFESTO-CHANGE-APPROVED:bd-<id>\n"
            "(o MANIFESTO-CHANGE-APPROVED:HUMAN si el Lead recibio aprobacion verbal explicita)."
        )
        sys.stderr.write(msg + "\n")
        return 2

    # Tag presente: log y dejar pasar
    sys.stderr.write("[hook validate_task_created] tag APPROVED detectado, autorizando task sensible.\n")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        sys.stderr.write(f"[hook validate_task_created] ERROR: {e}. Fail-open.\n")
        rc = 0
    sys.exit(rc)

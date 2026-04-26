#!/usr/bin/env python3
"""
Hook TaskCompleted para Claude Code agent teams.

Cuando un teammate (especialmente Optimizador o DataOps) intenta cerrar una
task que propone cambios al modelo o a la DB, valida que la evidencia
adjunta tenga las metricas minimas requeridas. Si falta algo -> exit 2 y
la task no se cierra.

Reglas:
  1. Si la task tiene label/title con "calibrar", "RHO", "backtest",
     "calibracion", "optimizar" → es propuesta del Optimizador y debe
     incluir en evidence/body:
       - EV_total_horizonte (numero antes y despues)
       - N (sample size, idealmente N>=50)
       - snapshot_db_sha256 (hash del DB sobre el que se hizo el backtest)
       - delta_brier y delta_yield
  2. Si la task involucra DataOps (onboarding liga, ALTER TABLE, schema):
       - SQL aplicado + rollback plan
       - snapshot_db_sha256 pre-cambio
  3. Para tasks operativas comunes (auditoria, fix bug, doc) no requiere nada.

Exit code:
  0  = OK, dejar cerrar.
  2  = bloquear con feedback al teammate.
  1+ = error inesperado, fail-open (no bloquea).
"""
import json
import re
import sys


METRICS_OPTIMIZADOR = [
    'EV_total_horizonte',
    'N',
    'snapshot_db_sha256',
    'delta_brier',
    'delta_yield',
]

METRICS_DATAOPS = [
    'snapshot_db_sha256',
]

PATRONES_OPTIMIZADOR = re.compile(
    r'\b(calibrar|calibraci[oó]n|backtest|optimiz(ar|aci[oó]n)|RHO|ALFA|FLOOR|kelly)\b',
    re.IGNORECASE,
)

PATRONES_DATAOPS = re.compile(
    r'\b(onboard(ing)?|ALTER\s+TABLE|schema\s+(change|migration)|migrar)\b',
    re.IGNORECASE,
)


def _texto_de_task(payload):
    pieces = []
    task = payload.get('task') or payload
    for key in ('title', 'description', 'body', 'content', 'acceptance_criteria',
                'evidence', 'spec', 'notes', 'comments'):
        val = task.get(key) if isinstance(task, dict) else None
        if isinstance(val, str):
            pieces.append(val)
        elif isinstance(val, list):
            pieces.extend(str(x) for x in val)
    pieces.append(json.dumps(payload, ensure_ascii=False))
    return '\n'.join(pieces)


def _faltantes(texto, metricas):
    return [m for m in metricas if m.lower() not in texto.lower()]


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("[hook validate_task_completed] WARN: stdin no es JSON valido, dejando pasar.\n")
        return 0

    texto = _texto_de_task(payload)

    es_optimizador = bool(PATRONES_OPTIMIZADOR.search(texto))
    es_dataops = bool(PATRONES_DATAOPS.search(texto))

    if not es_optimizador and not es_dataops:
        return 0  # task operativa comun, sin requerimientos

    faltantes = []
    if es_optimizador:
        faltantes.extend(f"  - {m}" for m in _faltantes(texto, METRICS_OPTIMIZADOR))
    if es_dataops:
        faltantes.extend(f"  - {m}" for m in _faltantes(texto, METRICS_DATAOPS))

    # Dedup preservando orden
    seen = set()
    faltantes = [x for x in faltantes if not (x in seen or seen.add(x))]

    if not faltantes:
        sys.stderr.write("[hook validate_task_completed] metricas OK, autorizando cierre.\n")
        return 0

    rol = "Optimizador/DataOps"
    if es_optimizador and not es_dataops:
        rol = "Optimizador"
    elif es_dataops and not es_optimizador:
        rol = "DataOps"

    msg = (
        f"[BLOQUEADO] TaskCompleted rechazada por hook validate_task_completed.\n"
        f"Esta task tiene perfil de {rol} y requiere las siguientes metricas en su\n"
        f"evidence/body antes de poder cerrarse:\n"
        + '\n'.join(faltantes) + "\n\n"
        "Adjuntar los valores explicitamente en el cuerpo del bead o en el\n"
        "comment final. Volver a intentar el cierre cuando esten todos.\n"
        "(Si esta task NO es realmente del Optimizador/DataOps, ajustar el\n"
        "title/description para no disparar los patrones del hook.)"
    )
    sys.stderr.write(msg + "\n")
    return 2


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as e:
        sys.stderr.write(f"[hook validate_task_completed] ERROR: {e}. Fail-open.\n")
        rc = 0
    sys.exit(rc)

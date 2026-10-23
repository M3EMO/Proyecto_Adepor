#!/usr/bin/env bash
# Equivalente Linux de ejecutar_robot.bat: pipeline diario, log con fecha.
# Cron sugerido: 0 9,17 * * * /ruta/BetDeportivo/ejecutar_robot.sh
# Contrato, regla 8: snapshot antes de tocar la base. Si falla, set -e frena el pipeline.
set -euo pipefail
cd "$(dirname "$0")"
PY="${ADEPOR_PYTHON:-.venv/bin/python}"
mkdir -p data/logs
LOG="data/logs/pipeline_$(date +%Y%m%d).log"
"$PY" adepor_guard.py snapshot >> "$LOG" 2>&1
"$PY" ejecutar_proyecto.py >> "$LOG" 2>&1

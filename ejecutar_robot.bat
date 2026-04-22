@echo off
cd /d "%~dp0"
python ejecutar_proyecto.py >> log_diario.txt 2>&1

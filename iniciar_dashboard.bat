@echo off
REM Levanta streamlit + ngrok tunnel para compartir el dashboard con amigos.
REM Requisitos: streamlit instalado (py -m pip install streamlit) y ngrok
REM autenticado (ngrok config add-authtoken <tu_token>).
REM
REM Uso:  doble click o `iniciar_dashboard.bat` desde una terminal.
REM Cerrar: Ctrl+C en cada ventana o cerrarlas.

cd /d %~dp0
echo [Adepor] Iniciando Streamlit en localhost:8501...
start "Adepor Dashboard (Streamlit)" /MIN cmd /k "py -m streamlit run dashboard.py --server.headless true --server.port 8501 --browser.gatherUsageStats false"

echo [Adepor] Esperando 5s para que arranque Streamlit...
timeout /t 5 /nobreak > nul

echo [Adepor] Abriendo tunel ngrok al puerto 8501...
start "Adepor Ngrok Tunnel" cmd /k "ngrok http 8501"

echo.
echo [OK] Ventanas abiertas. La URL publica sale en la ventana de ngrok
echo      (ej: https://xxx-xxx-xxx.ngrok-free.dev). Compartila con amigos.
echo.
echo Para frenar: cerra las dos ventanas o Ctrl+C en cada una.
pause

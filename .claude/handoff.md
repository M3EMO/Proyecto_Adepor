# Handoff — 2026-10-23 (cierre de sesión)

## Goal
Producto de apuestas listo para deploy (calculadora + medición honesta). El `/goal` sigue ACTIVO y no se cumple:
exige edge demostrado y P8 (50 apuestas liquidadas con CLV) está en 0. Decidir con el usuario: `/goal clear`,
redefinir como "producto técnico listo", o esperar apuestas reales.

## State
- Rama `audit/prod-ready-2026-10`. Todo commiteado en local, SIN push (último: `7055b4c`). Sin commitear a propósito:
  `diccionario_equipos.json` (lo cambia el pipeline) y `.claude/launch.json`.
- Producto técnico listo y probado: suite en verde (`.venv/bin/python -m pytest -q -p no:warnings`, esperado exit 0).
  - Cron (3 líneas): pipeline 9 y 17 h, cierre cada 15 min, salud cada hora. Copia previa en `~/.cache/crontab/crontab.bak`.
  - `ejecutar_robot.sh` hace snapshot antes del pipeline (verificado en el cron real de las 9:00 del 2026-10-23).
  - `scripts/ops/salud.py` escribe `data/logs/salud_estado.json`; el dashboard muestra un error rojo si falla.
  - `scripts/ops/informe_medicion.py`: yield, CLV y calibración; hoy N=0.
  - Instalación limpia verificada (clon, venv, `pip install -r requirements.txt`, `inicializar_db.py`, `pytest`).
- E1 conectado a la cascada como paso 6.6 (`ejecutar_proyecto.py`, no crítico). Su PRIMERA corrida en producción es la de las 17:00 del 2026-10-23.
  - ¿Corrió?: `grep -c "6.6" data/logs/pipeline_20261023.log`, esperado >= 1.
  - ¿Guardó filas?: `.venv/bin/python -I -c "import sqlite3;c=sqlite3.connect('file:fondo_quant.db?mode=ro',uri=True);print(c.execute(\"select casa,count(*) from cuotas_forward where fixture_id like 'fm:%' group by casa\").fetchall())"`, esperado `pinnacle_pb` y `1xbet_argentina_fm` con filas.
  - Dato de la prueba: 1xBet Argentina tiene margen 2.4% (las demás casas 5%-9%).
- Estudios cerrados en negativo (D-026 a D-036 en `docs/decisiones/registro.md`; protocolos en specs 11 y 13): xG de FotMob, selección de divisiones,
  cruce Pinnacle/Bet365/promedio, oddspoll, porcentaje de victorias, rachas h2h y por localía, jugadores (ausencias, disciplina, descanso).
  Ninguna señal supera al cierre de Pinnacle. E3 (proxy de xG, R² 0.73) cumple, pero no es un edge.
- Hipótesis abierta: rachas h2h de 4 o más victorias rinden +6.0% en 2024/25 y 2025/26 (z=+3.0, IC95 [−1.6%, +13.6%]) y no en 2019-2023 (z=+0.92). Seguir hacia adelante, sin tocar el motor.
- Blocked: P8 y el edge dependen de apuestas reales (unos 6 meses a 2 apuestas por semana en las 5 ligas grandes).

## Next
1. Verificar la corrida de E1 de las 17:00 (comandos arriba). Si falló, mirar `data/logs/pipeline_20261023.log` y `salud.log`.
2. E5 cuando haya 40 partidos terminados en `cuotas_forward` (el primero empieza 2026-10-23 18:30Z):
   - ¿Cuántos hay?: `.venv/bin/python -I -c "import sqlite3;c=sqlite3.connect('file:fondo_quant.db?mode=ro',uri=True);print(c.execute(\"select count(distinct fixture_id) from cuotas_forward where fixture_id not like 'fm:%' and inicio_utc < strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 hours')\").fetchone())"`, esperado >= 40.
   - Bajar: `.venv/bin/python -I analisis/trayectoria_lineas.py bajar --max 40` (1 pedido OddsPapi por partido, ~12 MB cada uno).
   - Medir: `.venv/bin/python -I analisis/trayectoria_lineas.py medir`; escribir D-037 con el resultado, sea cual sea.
3. Con unas semanas de E1: medir el CLV de 1xBet Argentina contra el cierre de Pinnacle con `clv_apuestas` (`src/ingesta/motor_cuotas_fotmob.py`). Criterio en spec 13, E1: IC95 inferior > 0 y al menos 80 apuestas simuladas.

## Decisions
- Spec-driven: el protocolo y el criterio de éxito se escriben ANTES de correr cada estudio (specs 11, 12 y 13).
- No entra nada al motor sin bead `[PROPOSAL: MANIFESTO CHANGE]` con `approved-by-lead` y shadow primero.
- No se commitea ni se hace push sin pedido del usuario; esta sesión pidió commits, no push.
- NO se recopilan datos de vida privada de jugadores (perfiles de personas con nombre desde redes o prensa). Se cubre con datos deportivos (tarjetas, capitanía, rotación). Está escrito en spec 13, E7.
- `data/fotmob/` (1.4 GB) y `data/oddspapi_hist/` van en `.gitignore`.
- FotMob `matchOdds` da UNA casa por partido y país (`ARG`: 1xBet o Mostbet AR; `GBR`: casas UK rotativas). Solo partidos con cobertura; sin históricos.
- Idioma de las respuestas: ETS (oraciones de 20 palabras o menos, un ítem de lista = una oración).

## Open questions
- ¿Cerrar o redefinir el `/goal`?
- ¿Cuánto cupo OddsPapi queda este mes (plan gratis 250)? La captura diaria usa hasta 6 por día y E5 necesita 40.
- ¿Aviso activo (mail o notificación) para `salud.py`? Hoy solo log y dashboard.
- Perú, Uruguay, Ecuador, Colombia, Bolivia y Venezuela no tienen cuotas en The Odds API; OddsPapi forward podría cubrirlas.
- P8: el usuario debe confirmar apuestas con la cuota real en la pestaña "Valor v2".

## Read first
- `docs/specs/12-producto-deploy.md` (criterios P1-P8, simulaciones) y `docs/specs/13-estudios-forward.md` (E1-E7, resultados).
- `docs/decisiones/registro.md` (D-026 a D-036) y el `CLAUDE.md` del proyecto (ETS, gobierno de cambios, beads).

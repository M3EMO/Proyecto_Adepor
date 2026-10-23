# Handoff — 2026-10-23

## Goal
Producto de apuestas listo para deploy (calculadora + medición honesta). El `/goal` sigue ACTIVO y no se cumple:
exige edge demostrado y P8 (50 apuestas liquidadas con CLV) está en 0. Decidir con el usuario: `/goal clear`,
redefinir como "producto técnico listo", o esperar apuestas reales.

## State
- Done (commiteado en local, SIN push): 8 commits de `7fb08f8` a `6a765a2` en `audit/prod-ready-2026-10`.
  - Specs nuevas `docs/specs/07-fotmob.md`, `11-evaluacion-xg.md`, `12-producto-deploy.md`, `13-estudios-forward.md`.
  - `scripts/ops/salud.py` (cron horario) + aviso rojo en `dashboard.py`; `scripts/ops/informe_medicion.py`.
  - `ejecutar_robot.sh` hace snapshot antes del pipeline (verificado en el cron real de las 9:00 del 2026-10-23).
  - `scripts/research/fotmob_pedir.py` (curl_cffi, sin proxy), `src/ingesta/motor_cuotas_fotmob.py` (E1).
  - `analisis/`: `fotmob_xg_vs_pinnacle.py`, `simular_apuestas_ev.py`, `seleccion_divisiones_ev.py`, `cruce_casas_pinnacle.py`, `trayectoria_lineas.py`.
- Resultados negativos registrados en `docs/decisiones/registro.md`: D-029 (xG FotMob), D-030 (selección de divisiones), D-031 (cruce Pinnacle/Bet365/promedio).
  Junto con D-026 y D-028: ninguna señal probada supera al cierre de Pinnacle.
- Cron instalado (3 líneas): pipeline 9 y 17 h, cierre cada 15 min, salud cada hora. Copia previa en `~/.cache/crontab/crontab.bak`.
- E1 listo en prueba (sobre COPIA de la base, no producción): 87 partidos con Pinnacle, 67 emparejados con FotMob, 201 filas por corrida.
  Casas capturadas: 1xBet Argentina, Mostbet AR, Bet365 UK, Betfair, Paddy Power, Betfred, Sky Bet. Una corrida tarda unos 6 minutos.
  Verificación: `ADEPOR_DB=<copia> .venv/bin/python -u -m src.ingesta.motor_cuotas_fotmob`, esperado `[EXITO] cuotas_forward (FotMob): ~200 filas`.
  Aún NO está en la cascada ni en el cron. Corrida real en producción pendiente de visto bueno (hacer snapshot antes: `adepor_guard.py snapshot`).
- Blocked: nada técnico. P8 y el edge dependen de apuestas reales (unos 6 meses a 2 apuestas por semana en las 5 ligas grandes).

## Next
1. E1 ya funciona en prueba. Pedir visto bueno para CONECTAR `motor_cuotas_fotmob` a la cascada diaria
   (cambia el pipeline: actualizar `docs/specs/01-ingesta.md` anexo y `06-operacion.md`).
2. E5 cuando haya 40 partidos terminados en `cuotas_forward`:
   - ¿Cuántos hay?: `.venv/bin/python -I -c "import sqlite3;c=sqlite3.connect('file:fondo_quant.db?mode=ro',uri=True);print(c.execute(\"select count(distinct fixture_id) from cuotas_forward where fixture_id not like 'fm:%' and inicio_utc < strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 hours')\").fetchone())"`, esperado >= 40 (hoy 0; el primero empieza 2026-10-23 18:30Z).
   - Bajar: `.venv/bin/python -I analisis/trayectoria_lineas.py bajar --max 40` (gasta 1 pedido OddsPapi por partido; pesa ~12 MB cada uno).
   - Medir: `.venv/bin/python -I analisis/trayectoria_lineas.py medir` -> `analisis/trayectoria_lineas.json`; escribir D-032 con el resultado, sea cual sea.

## Decisions
- Protocolo SIEMPRE antes de correr (spec-driven): cada estudio tiene su sección en las specs 11, 12 o 13 con criterio de éxito fijado.
- El xG de FotMob NO entra al modelo (D-029). El v2 sigue con la prob justa solo de Pinnacle.
- No se commitea ni se hace push sin pedido explícito del usuario; esta vez pidió commit, no push.
- `data/fotmob/` (1.4 GB) y `data/oddspapi_hist/` van en `.gitignore`.
- FotMob `matchOdds` devuelve UNA casa por partido y país (`ARG`: 1xBet Argentina o Mostbet AR; `GBR`: casas UK rotativas). Solo partidos con cobertura; no sirve para históricos.
- `oddspoll` de FotMob no son votos: son frases de rachas. No hay "sabiduría de la gente" ahí.

## Open questions
- ¿Cuánto cupo OddsPapi queda este mes (plan gratis 250)? La captura diaria usa hasta 6 por día. E5 necesita 40.
- ¿Cerrar o redefinir el `/goal`?
- ¿Conectar E1 a la cascada? ¿Y un aviso activo (mail o notificación) para `salud.py`? Hoy solo log y dashboard.
- Perú, Uruguay, Ecuador, Colombia, Bolivia y Venezuela no tienen cuotas en The Odds API; OddsPapi forward podría cubrirlas.
- P8: el usuario debe confirmar apuestas con la cuota real en la pestaña "Valor v2".

## Read first
- `docs/specs/12-producto-deploy.md` (criterios P1-P8, simulaciones), `docs/specs/13-estudios-forward.md` (E1-E5).
- `docs/decisiones/registro.md` (D-026 a D-031), `CLAUDE.md` del proyecto (idioma ETS, gobierno de cambios, beads).
- Sin commitear a propósito: `diccionario_equipos.json` (lo cambia el pipeline), `.claude/launch.json`.

# Auditoría prod-ready — 2026-10-12

Bead épica: `adepor-thv`. Alcance: bugs, números y preparación para producción.
Regla aplicada: ningún número se acepta sin recomputarlo desde datos crudos.

## 1. Limitación de datos

- `fondo_quant.db` de producción no existe en esta máquina.
- Los únicos datos disponibles son 9 snapshots de abril 2026 (175 partidos) y `analisis/_liq_2026_picks.csv`.
- Las conclusiones sobre producción se marcan como verificables solo con la DB real.

## 2. Números verificados

Fuente: `analisis/_liq_2026_picks.csv` (281 filas). Recomputado dos veces de forma independiente.

| Población | N | Hit | Yield | IC95 bootstrap |
|---|---|---|---|---|
| Apuestas con dinero real (stake > 0), ponderado por stake | 52 | 42.3% | **−12.5%** | [−42%, +19%] |
| Apuestas con dinero real, stake plano | 52 | 42.3% | −17.2% | [−45%, +14%] |
| Todas las filas, incluido pretest con stake 0 | 281 | 51.2% | +30.0% | [+13%, +47%] |

- El dinero real perdió 33.447 sobre 266.814 apostados.
- El "+30%" proviene de 229 picks sin stake.
- Esos picks pueden estar contaminados por la fuga descripta en §4.1.
- Ninguna de las 281 filas tiene CLV, por el bug de §4.4.

## 2b. Validación walk-forward con cuotas reales de Pinnacle (2026-10-13)

Script: `analisis/validacion_fdco_walkforward.py` (resultado en `analisis/validacion_fdco_walkforward.json`).
Datos: football-data.co.uk, Inglaterra, España, Italia y Alemania. 2023-24 calienta las EMAs; 2024-25 se evalúa (1445 partidos).
Sin parámetros ajustados a estos datos. Las decisiones usan las funciones reales de `motor_calculadora`.

| Métrica | Motor viejo | Motor nuevo | Mercado (cierre Pinnacle) |
|---|---|---|---|
| k = goles / λ | 0.577 | 0.928 | — |
| P(empate) medio | 0.184 | 0.262 | (real ≈ 0.25) |
| Brier 1X2 | 0.649 | 0.637 | **0.572** |
| Log-loss 1X2 | 1.080 | 1.056 | **0.961** |
| Picks | 491 | 175 | — |
| Hit / break-even | 26.1% / 31.1% | 26.3% / 31.4% | — |
| Yield plano | **−17.0%** [−29.8%, −3.8%] | −15.8% [−36.4%, +4.0%] | — |
| CLV medio | −0.65% | −0.92% | — |

Conclusiones:
- El k=0.577 del motor viejo reproduce con datos reales el bug del prior: coincide con `gamma_1x2=0.59`.
- El motor nuevo corrige la escala y el empate, y mejora Brier y log-loss.
- Ninguno de los dos se acerca al mercado: el Brier del modelo está a 0.065 del de Pinnacle.
- Todos los picks son underdogs (cuota media 3.2–3.4). El modelo sobrevalora a quien el mercado ve débil.
- El CLV es negativo: el mercado se mueve en contra de los picks.
- **El modelo no tiene edge contra un mercado sharp. No debe apostar dinero real.** El pretest (yield > 0 significativo + `--aprobar-live`) lo impide.
- **Pesos xG dinámicos (motor `nuevo_dinamico`)**: ajustan mejor los goles de cada partido (k=0.989; log-verosimilitud +0.035 por observación, z=7.7). Pero empeoran el pronóstico 1X2 (Brier 0.6393 vs 0.6366) y el yield (−23.7%). Veredicto: no se promueven; siguen en shadow.
- **¿El modelo agrega información a Pinnacle?** Mezcla p ∝ q_apertura^(1−w) · p_modelo^w, con w elegido en la 1ra mitad de 2024-25. El óptimo es w=0 y la log-loss crece con w. En la 2da mitad: mercado 0.965, modelo solo 1.054. El modelo no aporta información en estas ligas.

## 3. Veredicto sobre las afirmaciones documentadas

| Afirmación | Veredicto | Motivo |
|---|---|---|
| H4 X-rescue: hit 0.520, yield +0.246, N=127 | NO SOSTENIDA | El walk-forward del propio repo da +0.011, IC [−0.040, +0.060]. |
| Layer 3: Δ +0.426 [+0.07, +0.78], N=160 | NO SOSTENIDA | Se eligió 1 de 4 filtros post-hoc; sin el filtro de descanso el IC cruza 0. |
| Subset apostable V14: hit 69.4% | DÉBIL | Las reglas se ajustaron sobre el mismo pool, sin split y sin cuotas. |
| Bucket n_acum ≥ 60: yield +61.6% | NO VERIFICABLE | Ningún script del repo lo produce; otro doc asigna el mismo número a n_acum < 60. |
| Umbral M.2 n_acum < 60 calibrado | NO SOSTENIDA | 60 es un borde de bin; descubrimiento y validación usan la misma muestra. |
| Layer 2 V12 Turquía: yield +0.116 [+0.003, +0.242] | DÉBIL | Es 1 liga de 16 probadas; P(≥1 falso positivo) ≈ 56%. Además el SGD diario cambia los pesos validados. |

## 4. Bugs corregidos

### 4.1 Integridad del track record (P0)

- `motor_calculadora` recalculaba todo partido `Pendiente`/`Calculado`, sin filtro de fecha ni de goles.
- En el snapshot hay 23 picks con stake sobre partidos con resultado conocido; 19 ya estaban absorbidos en las EMAs.
- `motor_cuotas` sobrescribía cuotas de partidos en juego; The Odds API devuelve eventos in-play.
- Corrección: solo se calculan partidos futuros, sin goles y sin alerta enviada.
- Corrección: las cuotas no se sobrescriben tras el kickoff ni tras la alerta; `commenceTimeFrom` excluye in-play.
- Corrección: `motor_live` no envía picks de partidos empezados.

### 4.2 Escala de las lambdas del Poisson (P0, migración pendiente)

- `motor_data` y `rebuild_ema_v2` anclaban la EMA de cada equipo al promedio de goles por partido (~2.6).
- La escala correcta es por equipo (~1.3).
- Una réplica independiente muestra EMA 2.25 tras 20 partidos y 1.86 tras 60, con media real 1.35.
- En una liga sintética, el prior viejo da k = goles/λ = 0.594; el valor coincide con `gamma_1x2 = 0.59` del proyecto.
- Con prior por equipo, k = 1.015; Brier 1X2 baja de 0.6572 a 0.6536; P(X) pasa de 0.208 a 0.288 (real 0.259).
- Corrección detrás del flag `ema_prior_por_equipo` (default FALSE).
- `scripts/evaluar_prior_ema.py --aplicar` activa el flag y recalibra `factor_corr_xg_ou` y `gamma_1x2` en la misma corrida.
- El 1X2 seguía usando lambdas sin escalar. El flag por liga `escalar_lambda_1x2` aplica el mismo factor que el O/U.

### 4.3 Controles de riesgo muertos

- `detectar_drawdown` buscaba `[APOSTAR]` en filas liquidadas; en el snapshot devuelve INDETERMINADO en 24 de 24 apuestas. Nunca reducía Kelly.
- El filtro M.2 comparaba `riverplate` contra `River Plate`; nunca bloqueó en vivo.

### 4.4 Liquidación y métricas

- `cuota_para_pick` esperaba `1/X/2`; la DB guarda `LOCAL/VISITA/OVER 2.5`. CLV y cuota de cierre nunca se guardaban.
- `motor_backtest` emparejaba resultados solo por nombres; un partido de copa podía liquidar uno de liga. Ahora exige liga igual y fecha ±1 día.
- Un score ausente se liquidaba como 0-0 en `motor_backtest` y entraba como 0-0 a las EMAs en `motor_data`.
- `motor_liquidador` marcaba `Liquidado` aunque no resolviera la apuesta.
- El dashboard sumaba P/L de filas `Calculado`; el bankroll no. Ahora ambos usan solo `Liquidado`.
- Una apuesta ganada sin cuota se contaba como pérdida total.

### 4.5 Decisiones del motor retiradas del camino de decisión

Estos cambios alteran picks. Requieren aprobación del lead (ver §6).

- **Hallazgo G**: compara la frecuencia local de la liga contra el p1 de cada partido. Un local con p1=0.25 sube a 0.36. El OOS propio midió −1.2pp hit y +0.0044 Brier.
- **Fix #5**: no es monótono; p1=0.499 sale 0.519 y p1=0.500 sale 0.500. El OOS propio midió impacto nulo.
- **Hallazgo C**: multiplicaba stake ×1.30 con evidencia de 5 aciertos sobre 5.
- **Layer 3 H4**: con `APUESTA_EMPATE_PERMITIDA=False` el evaluador excluye EMPATE. El override nunca apostó X; apostaba LOCAL/VISITA con probabilidades V12. Queda en shadow.
- **M.2**: lookup corregido, pero ahora requiere `m2_activo: true` en `filtro_picks_v51`.
- **Pretest auto-flip**: activaba dinero real con hit ≥ 55% contra p0=0.5. Con cuota 1.80 el break-even es 55.6%. Ahora exige yield plano > 0, binomial contra el break-even y N ≥ 15. El flip a LIVE requiere `--aprobar-live`; el auto-revert a PRETEST sigue automático.

- **Bankroll bajo el piso**: antes se clampeaba a `bankroll_piso` y Kelly dimensionaba con capital inexistente. Ahora usa el capital real y avisa.

### 4.5b Cuotas local/visita invertidas (P0)

- En el snapshot hay 8 partidos donde el mercado da <25% al favorito del modelo y <2.0 al rival.
- El favorito del modelo ganó 8 de 8. Con cuotas correctas, esa probabilidad es ≤ 1.5e−5.
- Ejemplo: Palmeiras local contra Grêmio a 6.03, y Grêmio a 1.54. El pick LOCAL "ganó" pagando la cuota del rival.
- En el CSV 2026, 25 picks 1X2 con cuota ≥ 4 tienen hit 48% contra break-even 21%. Aportan +36.8 u, el 44% del profit.
- El mecanismo exacto no se pudo aislar sin la DB real. El matching de cuotas conserva la orientación.
- Corrección: guarda `RATIO_MIN_IMPLICITA=0.5`. Si 1/cuota del favorito del modelo es menor que la mitad de su prob, el pick pasa.
- Consecuencia: el camino C3 "Alta Convicción" (EV ≥ 100%) queda inalcanzable. También corta el extremo de C2B.
- Pendiente: auditar en la DB real qué fuente escribió cuotas invertidas y corregir esas filas.

### 4.6 Operación y robustez

- Hora de referencia: `ahora_art()` (UTC−3 fijo) reemplaza `datetime.now()` en calculadora, cuotas, backtest y live. Ya no depende de la zona de la máquina.
- Layer 3: el lookup de posición usaba el snapshot del mismo día, que ya incluye resultados de ese día. Ahora usa días previos.
- `importador_gold` degradaba filas `Liquidado` y borraba goles y cuotas con un CSV viejo.
- `motor_tactico` pedía la temporada por año calendario en España, Italia, Alemania y Francia.
- `motor_fixture` omite equipos sin mapear cuando no hay TTY; antes perdía el partido por `EOFError` en silencio.
- `motor_arbitro` audita solo los últimos 21 días; con el fix de fecha habría consultado todo el histórico.
- `motor_calculadora` escribía `xg_local_corto` sin crear la columna: en una DB sin ella calculaba todo y fallaba al guardar. Detectado con una corrida de punta a punta sobre el snapshot real.
- Excel: la tabla por liga suma O/U además de 1X2. La curva de equity incluye aportes posteriores al último partido.
- `actualizar_posiciones` omitía partidos del último día liquidados después del snapshot.
- `motor_tactico` asumía la alineación del local primero; ahora ordena por `team.id`.
- `gestor_nombres` generaba candidatos en orden de hash; ahora el orden es fijo.
- `scripts/db/esquema.py` exporta el esquema real a `docs/db_schema.sql` y crea una DB vacía desde ese archivo.
- `evaluar_prior_ema --aplicar` reescala también los equipos sin stats (cociente nuevo/viejo por liga) y guarda el backup junto a la DB. `backfill_ema_scoped` usa el mismo prior.

- Orquestador: stderr y stdout en dos pipes podían bloquear el pipeline; `--rebuild` purgaba tablas aunque el import fallara.
- Paths: `DB_NAME` es absoluto y acepta `ADEPOR_DB`; el pipeline aborta si la DB falta en vez de crear un archivo vacío.
- `calibrar_rho` pisaba rhos calibrados con el fallback ante un corte de red.
- `motor_adaptativo` usaba la fecha como watermark; perdía partidos del mismo minuto y reaplicaba pasos tras un crash.
- `online_sgd_v12.py` en modo "test" escribía outcomes aleatorios en pesos de producción.
- Snapshots con `shutil.copy2` perdían páginas del WAL; ahora usan la API de backup.
- `motor_arbitro` nunca corrió: parseaba fechas ISO con `%d/%m/%Y`.
- `motor_data` armaba el `id_partido` con la fecha local; los partidos de 21:00+ ART no recibían stats.
- `gestor_nombres` llamaba `input()` bajo cron; el partido se perdía en silencio.
- Cuotas 1X2: Pinnacle primero y las tres cuotas del mismo libro.
- Hooks de Claude Code usaban `py`; en Linux no corrían. El chequeo de la métrica `N` aceptaba cualquier letra "n".
- `requirements.txt`, `requirements-analisis.txt`, `pytest.ini` y `ejecutar_robot.sh` nuevos.

## 5. Seguridad (acción del usuario)

- El repo `M3EMO/Proyecto_Adepor` es **público**.
- `token.json` contiene un refresh token de Google con scopes `drive` y `spreadsheets`. Revocar en https://myaccount.google.com/permissions.
- `config.json` estuvo trackeado entre `b7bf9d9` y `5d141cb` con 6 keys de The Odds API y 1 de API-Football. Rotarlas.
- El token de Telegram estaba hardcodeado en `motor_live.py`. Ahora se lee de `config.json` (`telegram_token`, `telegram_chat_id`) o de `ADEPOR_TELEGRAM_TOKEN`/`ADEPOR_TELEGRAM_CHAT_ID`.
- Se quitaron del índice `credentials.json`, `token.json`, `.claude/settings.local.json` y `snapshots/`. Siguen en el historial; reescribirlo exige force-push.

## 6. Pasos para desplegar (base nueva, 2026-10-13)

La base de producción se perdió. El sistema arranca desde cero.

1. Revocá el token de Google y rotá las API keys (§5).
2. Instalá dependencias: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. Creá `config.json` desde `config.example.json` con tus `api_keys_odds`.
4. Corré los tests: `.venv/bin/python -m pytest`.
5. Creá la base: `.venv/bin/python scripts/db/inicializar_db.py`.
6. Mapeá equipos nuevos: `.venv/bin/python ejecutar_proyecto.py --audit-names` (en la prueba faltaron 69 partidos por nombres).
7. Corré el pipeline: `./ejecutar_robot.sh`. La primera corrida baja 365 días de ESPN por liga.
8. Abrí el dashboard: `./iniciar_dashboard.sh` y entrá a http://127.0.0.1:8501.
9. Congelá el esquema: `.venv/bin/python scripts/db/esquema.py --exportar` y commiteá `docs/db_schema.sql`.
10. Programá `ejecutar_robot.sh` en cron.
11. Operá en pretest. Pasá una liga a dinero real solo con `scripts/evaluar_pretest.py --aprobar-live` cuando muestre yield positivo significativo.

## 7. Pendientes

Resueltos en la ronda del 2026-10-13:
- `drift_detector`: el baseline sale de la historia previa a la ventana, con error estándar real.
- `validate_task_created`: con `bd-<id>` verifica que el bead tenga `approved-by-lead`.
- Hook Sofa: toma pendientes de `partidos_backtest`; antes leía una tabla que el pipeline nunca actualizaba.
- Anti-filtro shotmap: comparaba fecha con hora contra fecha sin hora; nunca liquidaba sus logs.
- `rebuild_ema_v2` diario: solo corre con xG Sofa activo; si no, pisaba la historia de `motor_data`.
- Pipeline completo verificado sobre base nueva con ESPN real hasta el paso de cuotas.

Abiertos:
- Origen de las cuotas invertidas en la base perdida (`adepor-thv.18`): sin la base no se puede aislar.
- Pesos xG dinámicos por liga (`adepor-thv.21`): esperan decisión del usuario.
- Sin migraciones versionadas: `esquema.py` congela el estado actual, no la historia de cambios.
- Decisión aceptada: sin stats ESPN (LATAM) el xG proxy usa goles reales; es un modelo de goles, no un bug.
- Decisión aceptada: pasos 3.15 y 3.16 siguen en `analisis/`; mover archivos requiere permiso de borrado.

## 8. Decisiones del usuario 2026-10-13

- PROPOSAL `adepor-thv.12` (puntos a–g): **aprobada**. El cambio de bankroll sin clamp al piso queda pendiente de confirmación.
- Telegram: **se retira**. `ejecutar_robot.sh`, `config.example.json` y `CLAUDE.md` ya no lo usan.
- Falta borrar a mano `motor_live.py`, `ejecutar_live.bat`, `archivo/motor_live.py` y `tests/test_live.py`; el permiso de borrado está bloqueado para el agente.
- SofaScore como fuente única: la primera llamada desde esta máquina devolvió **403**. Sofa bloquea clientes automáticos y no se intentó evadirlo.
- Fuentes de datos: **ESPN + The Odds API** (opción B). Se sacaron del pipeline los pasos de API-Football (`motor_tactico`, `motor_cuotas_apifootball`). Sofa queda como enriquecimiento opcional.
- Presentación: **Streamlit local único**. Las vistas del Excel se migran a pestañas. "Confirmar apuesta" (`src/persistencia/confirmaciones.py`) reemplaza a Telegram: guarda cuota tomada y stake real, y congela el pick.
- Base nueva: `scripts/db/inicializar_db.py` crea un esquema completo con prior por equipo, factor O/U 1.0 y O/U en pretest. Corrida real contra ESPN: 193 partidos procesados, EMA media 1.358 por equipo.
- Arranque en frío: ningún pick pasa si local o visita tienen menos de 5 partidos en su EMA (`n_min_partidos_equipo`).
- `motor_cuotas` termina con error si no hay `api_keys_odds`; antes informaba "EXITO" con 0 cuotas.
- Pesos xG dinámicos por liga: **implementados en shadow** (`src/nucleo/xg_pesos_dinamicos.py`, paso 3.4). Filtro de Kalman con olvido 0.995 y prior en los coeficientes estáticos. No afecta picks. Se promueven solo si la log-verosimilitud walk-forward supera a los pesos estáticos con datos reales.

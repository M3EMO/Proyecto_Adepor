# PLAN — Programador Senior / Tech Lead (Fase 2)

> Entregable del primer ciclo (Fase 2.0). **Solo propuesta**, nada se ejecuta hasta autorización del usuario via Lead.
> Restricciones honradas: Reglas_IA.txt §II/§IV bloqueadas, strings exactos intactos (`'GANADA'`/`'PERDIDA'`/`'ANULADA'`/`'OPERAR LOCAL'`/`'OPERAR VISITA'`/`'PASAR'`/`'OVER'`/`'UNDER'`/`'Calculado'`/`'Liquidado'`/`'Finalizado'`/`'Pendiente'`), `adepor_eval_review.html` fuera de scope.

---

## 0. RESUMEN EJECUTIVO

- 9 motores `.py` revisados (`src/{comun,ingesta,nucleo,persistencia}/`). El más grande es `motor_sincronizador.py` (1.100 LOC). El más cargado de matemática bloqueada: `motor_calculadora.py` (955 LOC, **NO se modulariza** salvo separación cosmética del main).
- Inventariadas **~62 constantes hardcoded** distribuidas en 9 archivos. ~28 son candidatas a migrar a `config_motor_valores` (resto son strings exactos protegidos o claves API).
- Identificadas **6 redundancias inter-motor** claras candidatas a `src/comun/` (derivación `MAPA_LIGAS_ESPN`, `safe_int`/`safe_float`, parser fechas ESPN, `normalizar_evento_api_secundaria`, lógica de `determinar_resultado_apuesta`, fallback Bankroll/Fracción Kelly desde DB).
- **2 modularizaciones grandes propuestas**: `motor_sincronizador.py` se parte en 4 archivos (Excel layout + formula generators + dashboard/sombra/resumen + writer), y `motor_calculadora.py` solo separa el `main()` orquestador (no la matemática).
- **Plan de delegación**: junior-1 = redundancias `src/comun/`, junior-2 = migración hardcodes a DB (coordinando con analista-datos primero el schema).

---

## 1. INVENTARIO DE HARDCODES POR MOTOR

Leyenda: **(M)** = candidato a migrar a `config_motor_valores`. **(C)** = candidato a `src/comun/` como constante compartida. **(P)** = string protegido por Reglas_IA / Excel — NO TOCAR. **(K)** = clave API o secreto, NO va a DB pública (queda en `config.json`).

### 1.1 `src/comun/config_sistema.py` (87 LOC)

| Constante | Valor / forma | Acción |
|---|---|---|
| `DB_NAME` | `'fondo_quant.db'` | Mantener aquí (canon). |
| `LIGAS_ESPN` | dict 12 entradas (codigo→pais) | **(M)** mover a tabla `ligas_canonicas` (analista-datos). |
| `MAPA_LIGAS_ODDS` | dict 12 entradas (pais→key odds-api) | **(M)** ídem `ligas_canonicas`. |
| `MAPA_LIGAS_API_FOOTBALL` | dict 12 entradas | **(M)** ídem. |
| `ESTADO_PENDIENTE/CALCULADO/FINALIZADO/LIQUIDADO` | strings | **(P)** quedan como constantes Python. |
| `API_KEYS_ODDS`, `API_KEY_FOOTBALL` | leídas de `config.json` | **(K)** OK como está. |

### 1.2 `src/ingesta/motor_data.py` (479 LOC)

| Constante | Valor | Acción |
|---|---|---|
| `ALFA_EMA_POR_LIGA` | dict 12 ligas | **BLOQUEADO** Reglas_IA §II.B. NO migrar (matemático). |
| `N0_ANCLA` | 5 | **BLOQUEADO** Reglas_IA §II.B. |
| `UMBRAL_PARTIDOS_MINIMOS` | 15 | **(M)** umbral operativo, no fórmula. |
| `UMBRAL_RECIEN_ASCENDIDO` | 10 | **(M)** ídem. |
| `PROFUNDIDAD_INICIAL` | 365 | **(M)** parámetro de scraping. |
| `PROFUNDIDAD_PROFUNDA` | 140 | **(M)** ídem. |
| `PROFUNDIDAD_MANTENIMIENTO` | 7 | **(M)** ídem. |
| `PROFUNDIDAD_PROFUNDA_POR_LIGA` | `{"Noruega":365}` | **(M)** override por liga. |
| `ESQUINAS_POR_GOL_GLOBAL` | 4.0 | **(M)** parámetro operativo (no entra a la fórmula xG bloqueada). |
| `safe_int`, `safe_float` | helpers | **(C)** mover a `src/comun/utils_numericos.py`. |
| `actualizar_estado` | función nested ~50 LOC dentro de `main()` | Refactor: subir al módulo (no es delegable a junior, va con tech-lead). |
| `timeout=5` línea 344 | timeout ESPN | **(M)** `TIMEOUT_ESPN_SEG=5`. |

### 1.3 `src/ingesta/motor_arbitro.py` (156 LOC)

| Constante | Valor | Acción |
|---|---|---|
| `LAMBDA_EMA` | 0.15 | **BLOQUEADO** (es coef EMA). NO migrar. |
| `MAPA_LIGAS_ESPN` | derivación inline desde `LIGAS_ESPN` | **(C)** mover a `src/comun/mapas_ligas.py` (compartido con motor_backtest). |
| `timeout=10` líneas 69, 93 | timeout ESPN summary | **(M)** `TIMEOUT_ESPN_SEG=10` — **nota**: ESPN summary tolera timeout mayor que ESPN scoreboard; evaluar si van en misma constante o separadas. |

### 1.4 `src/ingesta/motor_fixture.py` (155 LOC)

| Constante | Valor | Acción |
|---|---|---|
| `KEY_INDEX` | 0 (global) | Mantener (estado de rotación). |
| `range(-1, 6)` | rango fechas escaneo | **(M)** parametrizar (`scan_dias_atras=-1`, `scan_dias_adelante=6`). |
| `timedelta(hours=3)` | offset hora local AR | **(M)** `tz_offset_horas` por liga. |
| Loop parser fechas | `for fmt in [...]: try datetime.strptime(...)` | **(C)** mover a `src/comun/parser_fechas.py`. |
| `normalizar_evento_api_secundaria` | función | **(C)** mover (duplicado en motor_backtest — ver §5 fila #4: no unificar, renombrar). |
| `timeout=5` (línea 59, ESPN) / `timeout=10` (línea 73, odds-api) | timeouts HTTP | **(M)** `TIMEOUT_ESPN_SEG=5`, `TIMEOUT_ODDS_API_SEG=10`. |

### 1.4b `src/ingesta/motor_tactico.py` (155 LOC) — **agregado post-audit junior-2**

| Constante | Valor | Acción |
|---|---|---|
| `BASE_URL` + `HEADERS` API-Football | strings | **(M)** endpoint + headers en config. |
| `ligas_temporada_dividida = {"Inglaterra", "Turquia"}` línea 37 | set hardcoded | **(M)** mover a `ligas_canonicas.tipo_calendario` (`'unica'`/`'dividida'`). |
| `fechas_api = [fecha_ayer, fecha_hoy]` línea 79 | ventana 2 días | **(M)** `TACTICA_VENTANA_DIAS_ATRAS=1`, `TACTICA_VENTANA_DIAS_ADELANTE=0`. |
| `timeout=10` (líneas 95, 108) | timeout API-Football | **(M)** `TIMEOUT_API_FOOTBALL_SEG=10`. |
| `"Desconocido"` (líneas 25, 114, 116, 133) | default + fallbacks DT | **(C)** `DT_DESCONOCIDO = 'Desconocido'` en `src/comun/config_sistema.py`. Mismo string, solo darle nombre. |
| ALTER TABLE runtime líneas 21-25 | DDL emulado | **Deuda coordinación con analista-datos**: cuando el DDL maestro lo publique, estos ALTER salen del código productivo. NO es bloque de juniors. |

### 1.5 `src/ingesta/motor_cuotas.py` (212 LOC) — recién verificado

| Constante | Valor | Acción |
|---|---|---|
| `MODO_INTERACTIVO` | env var `PROYECTO_MODO_INTERACTIVO` | OK. |
| `DICCIONARIO_FILE` | `'diccionario_equipos.json'` (cwd-relative) | **(M)** path absoluto via config. |
| URL odds-api `regions=eu,us,uk,au&markets=h2h,totals&bookmakers=...` | string | **(M)** dejar regiones/bookmakers en DB para añadir/quitar sin tocar código. |
| `ORDEN_OU` | `['pinnacle','bet365','1xbet','betfair_ex_eu','draftkings']` | **(M)** prioridad de bookmakers configurable. |
| `0.75` | umbral fuzzy match | **(M)** `umbral_fuzzy_equipos`. |
| `2.5` (línea OU) | `abs(punto_f - 2.5) < 0.01` | **(P)** estratégico — Reglas_IA §IV. |
| `timeout=10` línea 37 | timeout odds-api | **(M)** `TIMEOUT_ODDS_API_SEG=10` (compartido con motor_fixture). |

### 1.6 `src/nucleo/motor_calculadora.py` (955 LOC)

**TODO** lo matemático queda **BLOQUEADO** Reglas_IA §II/§IV. Inventario solo de no-matemático:

| Constante | Valor | Acción |
|---|---|---|
| `BANKROLL` fallback | 100000.00 | **(M)** ya está en DB `parametros_kelly`, queda solo el fallback in-code. |
| `FRACCION_KELLY` fallback | 0.50 | **(M)** ídem. |
| `MAX_KELLY_PCT` (drawdown) | 1% | **BLOQUEADO** Reglas_IA §II.I. |
| `ALTITUD_NIVELES` | lista hardcoded | **BLOQUEADO** Reglas_IA §II.G. |
| Resto (`min_ev_escalado`, `aplicar_hallazgo_g`, `corregir_calibracion`, `multiplicador_delta_stake`, `evaluar_mercado_*`, `tau`, `poisson`, `detectar_drawdown`, `ajustar_stakes_por_covarianza`) | funciones | **BLOQUEADO**. |
| `main()` línea 644, ~310 LOC | orquestador | Refactor: separar en sub-helpers SIN tocar matemática (separación cosmética). |
| `determinar_resultado_apuesta` | función | **(C)** candidato a `src/comun/resultados_apuesta.py` (duplicado en sincronizador y liquidador). |

### 1.7 `src/persistencia/motor_sincronizador.py` (1.100 LOC)

| Elemento | Acción |
|---|---|
| `DB_NAME` línea 14 | borrar — usar import desde `config_sistema`. |
| `EXCEL_FILE='Backtest_Modelo.xlsx'` línea 15 | **(M)** parametrizar via config. |
| `BANKROLL=100000.00` fallback | **(M)** leer de `parametros_kelly` (duplicado con calculadora). |
| `FRACCION_KELLY=0.50` fallback | **(M)** ídem. |
| `COL` dict (28 keys) | **(P)** headers Excel — disenador-excel manda. |
| `HEADERS` dict | **(P)** ídem. |
| `PAISES_CF` lista | **(M)** mover a DB. |
| `COL_WIDTHS` dict | layout Excel — disenador-excel. |
| `FILL_*` PatternFill | layout Excel — disenador-excel. |
| `_resultado_1x2`, `_resultado_ou`, `_cuota_1x2`, `_cuota_ou` | **(C)** duplican `determinar_resultado_apuesta` de calculadora. |
| `f_apuesta_1x2`, `f_apuesta_ou`, `f_acierto`, `f_pl_neto`, `f_equity`, `f_brier`, `f_brier_casa` | generadores fórmulas Excel — disenador-excel. |
| `calcular_metricas_dashboard` (línea 200, ~100 LOC) | divisible. |
| `crear_hoja_dashboard` (línea 329, ~225 LOC) | divisible (un archivo). |
| `crear_hoja_sombra` (línea 561, ~270 LOC) | divisible (un archivo). |
| `main()` (línea 829, ~270 LOC) | divisible. |

### 1.8 `src/persistencia/motor_backtest.py` (126 LOC)

| Elemento | Acción |
|---|---|
| `MAPA_LIGAS_ESPN` derivación inline | **(C)** duplicado con motor_arbitro. |
| `KEY_INDEX = 0` | global de rotación, mantener. |
| `safe_int` | **(C)** duplicado con motor_data. |
| `normalizar_evento_api_secundaria` | **(C)** duplicado con motor_fixture. |
| Strings `'STATUS_FINAL'`, `'STATUS_FULL_TIME'` | constantes ESPN, **(C)** a `src/comun/estados_espn.py`. |
| Estados `'Calculado'`, `'Finalizado'` | **(P)**. |

### 1.9 `src/persistencia/motor_liquidador.py` (83 LOC)

| Elemento | Acción |
|---|---|
| `DB_NAME` línea 8 | borrar — usar import. |
| Strings `'[APOSTAR]'`, `'[GANADA]'`, `'[PERDIDA]'`, `'LOCAL'`, `'VISITA'`, `'OVER 2.5'`, `'UNDER 2.5'` | **(P)** todos protegidos. |
| Lógica resolución apuestas inline | **(C)** debe usar el helper unificado `determinar_resultado_apuesta`. |

### 1.10 `src/persistencia/motor_purga.py` (55 LOC)

| Elemento | Acción |
|---|---|
| `DB_NAME` línea 9 | borrar — usar import. |
| `INACTIVITY_MONTHS = 6` | **(M)** parámetro operativo. |

---

## 2. PROPUESTA DE BLOQUES MODULARES POR MOTOR

### 2.1 `motor_sincronizador.py` (1.100 LOC) → 4 archivos

> Coordinar con `disenador-excel` (boundary §1D PLAN). El bloque "Excel layout/styles" es de él.

```
src/persistencia/sincronizador/
├── __init__.py
├── sincronizador.py        (orquestador `main()` ~270 LOC, lectura DB, escritura Excel)
├── excel_layout.py         (COL, HEADERS, COL_WIDTHS, FILL_*, ~75 LOC) ← disenador-excel
├── excel_formulas.py       (f_apuesta_1x2/ou, f_acierto, f_pl_neto, f_equity, f_brier, ~65 LOC)
├── dashboard.py            (calcular_metricas_dashboard + _semaforo + crear_hoja_dashboard, ~325 LOC)
└── sombra.py               (crear_hoja_sombra + métricas asociadas, ~275 LOC)
```

Shim raíz `motor_sincronizador.py` se preserva (importa `from src.persistencia.sincronizador.sincronizador import main`).

### 2.2 `motor_calculadora.py` (955 LOC) — separación cosmética del `main()`

> **NO se parte la matemática.** Solo el `main()` orquestador (líneas 644-955) se divide en helpers internos del mismo archivo. Cero modificación a constantes, cero modificación a fórmulas.

Bloques internos del `main()` actual a extraer como funciones del mismo archivo:
- `_cargar_inputs_partido(cursor, partido)` — lee historial/EMA/cuotas/contexto.
- `_aplicar_pipeline_xg(inputs)` — encadena fatiga, altitud, momentum (todos los cálculos van a funciones existentes, sin tocar fórmulas).
- `_aplicar_pipeline_decision(xg_final, cuotas)` — Dixon-Coles, evaluar 1X2, evaluar OU, ajustar covarianza, calcular stakes.
- `_persistir_decision(cursor, partido, resultado)` — UPDATE partidos_backtest.
- `_calcular_shadow(inputs, decision)` — Op1 sin Fix#5/Hallazgo G/Hallazgo C (Reglas_IA §IV.K).

Resultado: `main()` queda en ~80 LOC orquestando estas 5 funciones, mucho más auditable. **NINGUNA fórmula cambia.**

### 2.3 `motor_data.py` (479 LOC) — extracción de helper anidado

- Subir `actualizar_estado` (anidada en `main()`) al módulo.
- `safe_int`/`safe_float` salen a `src/comun/utils_numericos.py`.
- `main()` queda ~150 LOC, suficientemente legible. **No requiere división mayor.**

### 2.4 Resto de motores

`motor_data`, `motor_fixture`, `motor_arbitro`, `motor_cuotas`, `motor_backtest`, `motor_liquidador`, `motor_purga` — **no requieren modularización adicional** una vez extraídas las redundancias a `src/comun/`. Quedan entre 50-220 LOC cada uno.

---

## 3. PLAN DE COORDINACIÓN CON `analista-datos`

### 3.1 DM a enviar (cuando Lead autorice)

> Hola analista-datos. Para Fase 2 necesito proponer una tabla `config_motor_valores` que centralice ~28 hardcodes operativos (no matemáticos — Reglas_IA §II/§IV queda fuera). Schema sugerido:
>
> ```sql
> CREATE TABLE config_motor_valores (
>     clave TEXT PRIMARY KEY,
>     valor TEXT NOT NULL,           -- siempre texto, casteo en lectura
>     tipo TEXT NOT NULL,            -- 'int' | 'float' | 'json' | 'str'
>     scope TEXT NOT NULL,           -- 'data' | 'fixture' | 'cuotas' | 'sincronizador' | 'global'
>     liga TEXT,                     -- NULL = global; sino override por liga
>     descripcion TEXT,
>     editable_sin_codigo INTEGER DEFAULT 1,
>     fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
> );
> CREATE UNIQUE INDEX ix_cfg_clave_liga ON config_motor_valores(clave, COALESCE(liga, ''));
> ```
>
> Helper de lectura (a vivir en `src/comun/config_db.py`): `obtener_config(clave, liga=None, default=None)` con cache en memoria.
>
> Tabla complementaria `ligas_canonicas` (sustituye los 3 dicts `LIGAS_ESPN` / `MAPA_LIGAS_ODDS` / `MAPA_LIGAS_API_FOOTBALL` de `config_sistema.py`):
>
> ```sql
> CREATE TABLE ligas_canonicas (
>     pais TEXT PRIMARY KEY,
>     codigo_espn TEXT NOT NULL,
>     key_odds_api TEXT NOT NULL,
>     id_api_football INTEGER,
>     tipo_calendario TEXT NOT NULL DEFAULT 'unica',  -- 'unica' | 'dividida' (reemplaza ligas_temporada_dividida en motor_tactico)
>     activa INTEGER DEFAULT 1,
>     orden_visualizacion INTEGER
> );
> ```
>
> Pregunta abierta: ¿la migración la hacés vos en `scripts/db/` o querés que junior-2 la implemente bajo tu spec? Yo voto opción 2 (vos definís schema + script seed; junior-2 ejecuta y verifica).
>
> **Tema adicional detectado por junior-2 a coordinar**: `motor_tactico.py:21-25` hace `ALTER TABLE equipos_stats ADD COLUMN ...` con try/except en runtime (emulación de IF NOT EXISTS). Cuando vos publiques el DDL maestro, esos ALTER deberían salir del código productivo y vivir en tu script de schema. Flag para la discusión — no requiere acción de juniors.
>
> **Inventario actualizado post-audit**: ~35 valores operativos (no ~28), divididos así:
> - Globales: `DB_NAME`, `EXCEL_FILE`, `CSV_GOLD_STANDARD`, `DT_DESCONOCIDO`, `BANKROLL`/`FRACCION_KELLY` fallbacks.
> - Scraping: `UMBRAL_PARTIDOS_MINIMOS`, `UMBRAL_RECIEN_ASCENDIDO`, `PROFUNDIDAD_INICIAL/PROFUNDA/MANTENIMIENTO`, `PROFUNDIDAD_PROFUNDA_POR_LIGA`, `ESQUINAS_POR_GOL_GLOBAL`.
> - Fixture/táctica: `SCAN_DIAS_ATRAS=-1`, `SCAN_DIAS_ADELANTE=6`, `TZ_OFFSET_HORAS`, `TACTICA_VENTANA_DIAS_ATRAS=1`, `TACTICA_VENTANA_DIAS_ADELANTE=0`.
> - Cuotas: `DICCIONARIO_FILE_PATH`, `UMBRAL_FUZZY_EQUIPOS=0.75`, `ORDEN_BOOKMAKERS`, `REGIONES_ODDS`.
> - Purga: `INACTIVITY_MONTHS=6`.
> - Sincronizador: `PAISES_CF`.
> - **HTTP timeouts** (nuevos): `TIMEOUT_ESPN_SEG=5`, `TIMEOUT_ODDS_API_SEG=10`, `TIMEOUT_API_FOOTBALL_SEG=10`, `TIMEOUT_SCRAPING_SEG=30`. **Caveat**: `motor_arbitro` usa 10 para ESPN summary mientras `motor_fixture/data/backtest` usan 5 para ESPN scoreboard. Discutir si son una sola constante con override por endpoint o dos constantes separadas.

### 3.2 Dependencia de bloqueo

- `junior-2` no arranca migración hasta que `analista-datos` confirme schema final.
- `disenador-excel` puede trabajar en paralelo (su scope es Excel + sincronizador.excel_*).

---

## 4. PLAN DE DELEGACIÓN A JUNIORS

### 4.1 `junior-1` — Redundancias a `src/comun/`

**Bloque asignado**: extraer 6 piezas duplicadas a `src/comun/`. NO toca matemática, NO toca DB.

Tareas concretas:
1. `src/comun/utils_numericos.py` — `safe_int`, `safe_float` (origen: motor_data, motor_backtest).
2. `src/comun/mapas_ligas.py` — `obtener_mapa_espn()` (derivación de `LIGAS_ESPN` invertido). Origen: motor_arbitro + motor_backtest.
3. `src/comun/parser_fechas.py` — `parse_fecha_espn(raw)` con la lista de formatos actual. Origen: motor_fixture (loop interno) + posibles otros.
4. `src/comun/normalizador_eventos.py` — `normalizar_evento_api_secundaria(evento)` (consolidar las 2 firmas existentes en motor_fixture y motor_backtest).
5. `src/comun/resultados_apuesta.py` — extraer `determinar_resultado_apuesta` desde `motor_calculadora.py` y reemplazar usos en `motor_sincronizador._resultado_1x2/_resultado_ou` y la lógica inline de `motor_liquidador`. **Verificar bit-a-bit que el resultado es idéntico** (test diff antes/después con DB de snapshot).
6. `src/comun/estados_espn.py` — constantes `'STATUS_FINAL'`, `'STATUS_FULL_TIME'` (para que sea trivial agregar nuevos sin grep).

**Restricciones explícitas a recordarle**:
- Cero cambios a Reglas_IA.txt §II/§IV.
- Cero cambios a strings exactos `'GANADA'`/`'PERDIDA'`/`'ANULADA'`/`'OPERAR LOCAL'`/`'OPERAR VISITA'`/`'PASAR'`/`'OVER'`/`'UNDER'`/`'Calculado'`/`'Liquidado'`/`'Finalizado'`/`'Pendiente'`.
- Validar contra snapshot de `fondo_quant.db` que cero filas cambian de estado o resultado tras refactor.
- Si encuentra un caso ambiguo donde dos firmas duplicadas no son bit-a-bit equivalentes (ej. `normalizar_evento_api_secundaria`) → STOP, DM a tech-lead, no decide solo.

### 4.2 `junior-2` — Migración hardcodes a `config_motor_valores`

**Bloque asignado**: migrar los ~28 valores marcados `(M)` arriba a la tabla `config_motor_valores` + `ligas_canonicas`. Bloqueado hasta que `analista-datos` apruebe schema.

Tareas concretas (en orden):
1. **Esperar** schema confirmado por `analista-datos`.
2. Implementar `src/comun/config_db.py` con `obtener_config(clave, liga=None, default=None)` + cache LRU.
3. Script seed `scripts/db/seed_config_motor_valores.py` con los 28 valores actuales (tomados literales del código). Verificar idempotencia.
4. Refactor archivo por archivo (en este orden, con commit por motor):
   - `motor_data.py` → leer `umbral_partidos_minimos`, `umbral_recien_ascendido`, `profundidad_*`, `esquinas_por_gol_global` desde DB.
   - `motor_fixture.py` → `scan_dias_atras`, `scan_dias_adelante`, `tz_offset_horas`.
   - `motor_cuotas.py` → `umbral_fuzzy_equipos`, `orden_bookmakers`, `regiones_odds`, `path_diccionario_equipos`.
   - `motor_purga.py` → `inactivity_months`.
   - `motor_sincronizador.py` → `excel_file_name`, `bankroll_fallback`, `fraccion_kelly_fallback`, `paises_cf`.
   - `motor_calculadora.py` → SOLO los dos fallbacks (`bankroll`, `fraccion_kelly`). Cero cambios a constantes matemáticas.
5. Migrar `LIGAS_ESPN`/`MAPA_LIGAS_ODDS`/`MAPA_LIGAS_API_FOOTBALL` de `config_sistema.py` a leer desde `ligas_canonicas`. **Mantener los nombres de variable como exports del módulo para compatibilidad** (los motores siguen importando `from src.comun.config_sistema import LIGAS_ESPN`).
6. Verificación: `python -m src.persistencia.motor_sincronizador` corre y produce Excel idéntico (diff binario aceptable solo en timestamps).

**Restricciones explícitas a recordarle**:
- Cero cambios a Reglas_IA.txt §II/§IV (las constantes matemáticas NO se migran a DB en esta fase — esa es decisión de usuario futura).
- Cero modificación de strings exactos.
- Si el seed falla en producir el mismo comportamiento → revertir y DM a tech-lead.
- No tocar `adepor_eval_review.html`.

### 4.3 Coordinación entre juniors

- Trabajan en archivos disjuntos: junior-1 crea `src/comun/*` nuevos; junior-2 modifica los `motor_*.py` existentes para leer de DB. **El cruce está en el orden**: junior-1 primero (helpers comunes), junior-2 después (puede usar los helpers).
- Si hay conflicto de imports → tech-lead resuelve.

### 4.4 DMs borrador (NO ENVIAR — mostrar al Lead primero)

> **Borrador DM → junior-1**:
> Hola junior-1. Tu bloque para Fase 2.2 (cuando se autorice ejecución): extraer 6 piezas duplicadas a `src/comun/`. Detalle completo en `docs/fase2/PLAN_tech_lead.md` §4.1. Restricciones críticas: cero cambios a Reglas_IA.txt §II/§IV, cero cambios a strings exactos (`'GANADA'`, `'PERDIDA'`, `'OPERAR LOCAL'`, etc.), validar bit-a-bit contra snapshot de DB. **De momento solo leé el plan y respondé con preguntas o ajustes — no ejecutes nada hasta que el Lead lo autorice.**

> **Borrador DM → junior-2**:
> Hola junior-2. Tu bloque para Fase 2.2 (cuando se autorice ejecución): migrar ~28 hardcodes operativos a tabla `config_motor_valores` + `ligas_canonicas`. Detalle completo en `docs/fase2/PLAN_tech_lead.md` §4.2. Estás **bloqueado** hasta que `analista-datos` confirme schema final. Restricciones críticas: cero migración de constantes matemáticas (Reglas_IA §II/§IV), cero modificación de strings exactos, mantener compatibilidad de imports en `config_sistema.py`. **De momento solo leé el plan y respondé con preguntas o ajustes — no ejecutes nada hasta que el Lead lo autorice.**

---

## 5. REDUNDANCIAS INTER-MOTOR → `src/comun/`

Resumen consolidado (detalle por archivo en §1):

| # | Pieza | Origen actual | Destino propuesto | Tamaño | Riesgo |
|---|---|---|---|---|---|
| 1 | `safe_int`, `safe_float` | motor_data, motor_backtest | `src/comun/utils_numericos.py` | ~10 LOC | Bajo. |
| 2 | `MAPA_LIGAS_ESPN` derivación | motor_arbitro, motor_backtest | `src/comun/mapas_ligas.py` | ~5 LOC | Bajo. |
| 3 | Loop parser fechas ESPN | motor_fixture (+ posibles) | `src/comun/parser_fechas.py` | ~15 LOC | Medio (varios formatos). |
| 4 | `normalizar_evento_api_secundaria` | motor_fixture, motor_backtest | `src/comun/adaptadores_odds_api.py` con **2 funciones distintas** | ~25 LOC | **CONFIRMADO por junior-1 (diff 2026-04-16): NO son idénticas**. Fixture produce shape ESPN-like anidado (pre-partido, nunca None); Backtest produce shape plano `{completed, home_team, away_team, goles_l, goles_v}` (post-partido, con guard None). Campos opuestos. Nombre compartido es deuda histórica. **Acción**: NO unificar. Renombrar a `adaptar_fixture_odds_api(evento)` y `adaptar_resultado_odds_api(evento)` + docstrings explicando la fase del pipeline. Refactor semántico, no sintáctico — previene que alguien intente DRYficar y rompa el pipeline. |
| 5 | `determinar_resultado_apuesta` | motor_calculadora (canónica) + duplicados en sincronizador (`_resultado_1x2`/`_resultado_ou`) + lógica inline en motor_liquidador | `src/comun/resultados_apuesta.py` | ~40 LOC | **Alto**: aquí pasan los strings `'GANADA'`/`'PERDIDA'`/`'ANULADA'` — bit-a-bit obligatorio. Esto va a junior-1 con verificación contra snapshot. |
| 6 | Constantes ESPN `STATUS_FINAL`/`STATUS_FULL_TIME` | motor_backtest | `src/comun/estados_espn.py` | ~3 LOC | Bajo. |
| 7 | Helper `obtener_bankroll_y_kelly()` | motor_calculadora + motor_sincronizador (fallbacks duplicados 100000/0.50) | `src/comun/parametros_kelly.py` | ~15 LOC | Bajo (lectura DB). |

**Nota sobre #5 (lógica de resolución de apuestas)**: la canónica es `determinar_resultado_apuesta` en `motor_calculadora.py`. Las duplicaciones en sincronizador y liquidador deben quedar como wrappers que llaman a la versión canónica. **Antes** de junior-1 tocar esto, tech-lead debe validar manualmente que los 3 implementaciones actuales producen output idéntico para todos los casos en una snapshot reciente — si no, hay un bug que debemos reportar al Lead antes de "unificar" (porque unificar a la versión incorrecta sería peor).

---

## 6. RIESGOS Y BLOQUEOS

1. **Riesgo principal**: redundancia #5 (resolución apuestas) puede esconder un bug histórico. Antes de unificar, validar las 3 implementaciones contra snapshot. Si difieren → STOP y reportar al Lead, no decidir nivel-tech-lead.
2. **Bloqueo junior-2**: depende de schema confirmado por `analista-datos`. Pipeline serial: analista-datos (schema) → junior-2 (migración). En paralelo: junior-1 (helpers) puede arrancar inmediatamente.
3. **Bloqueo `disenador-excel` cruzado**: la modularización de `motor_sincronizador.py` toca su territorio (`COL`/`HEADERS`/`FILL_*`/formula generators). Coordinar antes de partir el archivo.
4. **Riesgo silencioso de matemática**: cualquier modificación a `motor_calculadora.py`, aún cosmética, debe validarse con backtest comparando salidas pre/post. Política propuesta: corrida de `python -m src.persistencia.motor_backtest` + diff de Excel antes/después de la separación cosmética del `main()`.
5. **`config.json` con secrets**: el refactor NO debe filtrar API keys a la DB pública (`fondo_quant.db` se commitea). Las keys quedan en `config.json` (gitignored).

---

## 7. SECUENCIA SUGERIDA (post-aprobación usuario)

```
[Fase 2.2 — orden ejecución sugerido]

T0  analista-datos  → confirma schema config_motor_valores + ligas_canonicas
T0  disenador-excel → mockup layout dashboard mejorado (paralelo)
T0  experto-deportivo + experto-apuestas → audit con datos reales (paralelo)

T1  junior-1        → src/comun/* (utils_numericos, mapas_ligas, parser_fechas,
                       normalizador_eventos, estados_espn, parametros_kelly)
                       NOTA: resultados_apuesta queda para T2 (depende de validación tech-lead)

T2  tech-lead       → validar resolución apuestas en 3 sitios (snapshot diff)
T2  junior-1        → src/comun/resultados_apuesta.py + reemplazos
T2  junior-2        → seed config_motor_valores + config_db.py + migración motor_data/fixture/cuotas/purga

T3  tech-lead       → modularizar motor_sincronizador.py (4 archivos) coordinando con disenador-excel
T3  junior-2        → migración motor_sincronizador hardcodes + ligas_canonicas

T4  tech-lead       → separación cosmética main() de motor_calculadora.py
                       (sin tocar fórmulas, validación con backtest)

T5  validación end-to-end: ejecutar pipeline completo, diff Excel vs baseline
```

---

## 8. ESTADO ACTUAL DEL TECH-LEAD

- Plan entregado en este archivo. No he ejecutado ninguna modificación.
- Junior-1 y Junior-2 NO despertados (DMs en §4.4 son borradores para revisión del Lead).
- Coordinación con analista-datos NO iniciada (DM en §3.1 es borrador).
- Próximo paso: enviar este path al Lead, quedar IDLE esperando autorización del usuario.

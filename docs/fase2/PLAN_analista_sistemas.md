# PLAN — Analista de Sistemas (Fase 2)

> Autor: `analista-sistemas` · Ciclo: 2.0 · Fecha: 2026-04-16
> Restriccion: READ-ONLY sobre codigo. Solo escribo en `docs/fase2/`.
> Fuente: lectura completa de `Reglas_IA.txt`, `PLAN.md` (fase 2), `DEPENDENCIAS.md`,
> `ejecutar_proyecto.py` y los 14 motores en `src/`. Snapshot de metricas:
> `snapshots/metricas_20260413_010048.json`.

---

## 1. Diagrama textual del flujo (ASCII)

### 1.1 Pipeline de ejecucion (orden secuencial del orquestador)

```
                     ejecutar_proyecto.py
                              |
                              v
+-----------------------------+------------------------------+
| FASE 0  motor_purga                                        |  no I/O externo
| FASE 1  motor_backtest -> motor_liquidador                 |  ESPN (resultados)
|         motor_arbitro                                      |  ESPN (boxscore)
|         motor_data                                         |  ESPN (scoreboard 7-365 dias)
| FASE 2  motor_fixture                                      |  ESPN + The-Odds-API failover
|         motor_tactico                                      |  API-Football
|         motor_cuotas                                       |  The-Odds-API
| FASE 3  motor_calculadora                                  |  CPU pura, lee SQLite
| FASE 4  motor_backtest (2da pasada) -> motor_liquidador    |  ESPN (segundo barrido)
|         motor_sincronizador                                |  escribe Backtest_Modelo.xlsx
+------------------------------------------------------------+
```

Comunicacion inter-motor: **exclusivamente por SQLite** (`fondo_quant.db`).
Ningun motor importa a otro motor (confirmado en `DEPENDENCIAS.md` seccion 1).

### 1.2 Mapa "motor -> tabla" (R = lee, W = escribe)

```
TABLA / MOTOR             | data | calc | fix | cuot | arb | tact | bt  | liq | sinc | purga | rho |
--------------------------+------+------+-----+------+-----+------+-----+-----+------+-------+-----+
historial_equipos         |  RW  |  R   |     |      |     |      |  R  |     |      |       |  R  |
ema_procesados            |  RW  |      |     |      |     |      |     |     |      |  W*   |     |
ligas_stats               |  RW  |  R   |     |      |     |      |     |     |      |       |  RW |
equipos_stats             |  RW  |  R   |     |      |     |  RW  |     |     |      |  W*   |     |
equipos_altitud           |      |  R   |     |      |     |      |     |     |      |       |     |
arbitros_stats            |      |      |     |      | RW  |      |     |     |      |       |     |
arbitros_historial        |      |  R   |     |      | RW  |      |     |     |      |       |     |
partidos_backtest         |      |  RW  | RW  |  RW  |  W  |  RW  | RW  | RW  |  R   |  W*   |     |
configuracion (bankroll)  |      |  R   |     |      |     |      |     |     |  R   |       |     |
diccionario_equipos.json  |  R   |      |  RW |  RW  |  R  |  R   |  R  |     |      |       |     |
Backtest_Modelo.xlsx      |      |      |     |      |     |      |     |     |  W   |       |     |

* purga: RESET destructivo (--rebuild / --purge-history), no escritura normal.
```

### 1.3 Mapa "motor -> API externa"

```
+----------------+  ESPN scoreboard       +-----------------+
| motor_data     |  +EMA recursivo        | site.api.espn   |  hasta 365 dias x 12 ligas (PROFUNDIDAD_INICIAL)
| motor_fixture  |---scoreboard 7 dias--> | .com/apis/.../  |  failover -> The-Odds-API si timeout
| motor_arbitro  |  +summary boxscore     | sports/soccer/  |  1 call por (fecha,liga) + 1 por evento
| motor_backtest |  scoreboard fechas     |                 |  V7.3 limita a fechas con pendientes
+----------------+  unicas con pendientes +-----------------+

+----------------+  totals/h2h Pinnacle   +------------------+
| motor_cuotas   |---odds api------------>| api.the-odds-api |  1 call por liga (12 max), key rotation
| motor_fixture  |  scores secundario     | .com/v4/sports/  |  failover si ESPN cae
| motor_backtest |  scores secundario     |                  |
+----------------+                        +------------------+

+----------------+  fixtures + lineups    +------------------+
| motor_tactico  |---API-Football-------->| v3.football.api- |  2 calls por liga x 2 fechas (ayer+hoy)
+----------------+                        | sports.io        |  + 1 call por fixture matched
```

### 1.4 Ciclo de vida de `partidos_backtest`

```
Pendiente --(motor_calculadora)--> Calculado --(motor_backtest)--> Finalizado --(motor_liquidador)--> Liquidado
   ^                                    |                              |                                    |
   |                                    |                              |                                    |
motor_fixture INSERT       cuotas, formacion, arbitro       goles_l/goles_v          apuesta_*=GANADA/PERDIDA
                                                                                     auditoria='SI' (arbitro)
```

---

## 2. Cuellos de botella detectados (run de ~556s)

> No tengo logs cronometrados por motor en el repo. Las estimaciones son
> O(N) extrapoladas desde el codigo. Si necesitan numeros reales, marco
> donde instrumentar (puntos `[T]` abajo) y se lo paso a `tech-lead`.

### 2.1 motor_data — DOMINANTE (~60-70% del tiempo total estimado)

- **Bucle dias x ligas serial**: para cada liga en su grupo de profundidad,
  recorre `dias_a_escanear` dias y por cada dia hace UN GET sincrono a ESPN
  con `timeout=5s`. Cuando una liga entra al grupo `PROFUNDIDAD_INICIAL=365`
  o `PROFUNDIDAD_PROFUNDA=140`, son **365 x 12 = 4380 GETs** worst case.
  En modo MANTENIMIENTO=7 baja a 84 GETs. Punto critico:
  `src/ingesta/motor_data.py:335-345`. **No hay paralelismo** ni async.
- **GET sincrono con `requests.get`** sin sesion persistente -> nuevo TCP
  handshake por request. Cambiando a `requests.Session()` + `requests.adapters`
  con pool conectores se ahorra ~30-40% de latencia por llamada.
- **Cuello de SQLite WAL**: `motor_data` no activa `PRAGMA journal_mode=WAL`
  (solo `motor_fixture`, `motor_arbitro`, `motor_tactico` lo hacen). En modo
  default, el commit final con miles de UPSERTs serializa I/O del disco.
- **Update fila por fila**: `UPDATE partidos_backtest SET sot_l=?...`
  dentro del bucle de eventos (`src/ingesta/motor_data.py:404-407`).
  Deberia agregarse a `executemany` final, no inline por evento.

### 2.2 motor_arbitro — pesado por API-call N+1

- Por cada partido pendiente: **1 GET scoreboard + 1 GET summary** por evento.
  El agrupamiento por (fecha, pais) corta el primer GET (linea 56-67), pero
  el segundo (`/summary?event=...`) sigue siendo 1 por partido.
- Si hay 60 liquidados nuevos (escenario tipico de un dia), son ~60 GETs
  secuenciales con `timeout=10s`. Worst case ~10 min si la red empeora.

### 2.3 motor_calculadora — CPU O(N x 100)

- Por cada partido `Pendiente` o `Calculado`: doble loop Poisson
  `RANGO_POISSON x RANGO_POISSON = 10x10 = 100 iters` (1X2) + otro 100
  para O/U calibrado (`src/nucleo/motor_calculadora.py:765-794`).
- 175 partidos x 200 iter = 35k operaciones float -> < 1s en Python puro.
  **No es el cuello**, pero al escalar a 12 ligas con 30 partidos cada una
  pasaria a 360 x 200 = 72k iters. Sigue trivial.
- `obtener_ema` hace fallback con `difflib.get_close_matches` cada vez que
  un equipo no matchea exacto (`motor_calculadora.py:411-420`). Si hay
  30 equipos huerfanos en DB legacy ("Desconocido", etc.), eso es 30 x O(M)
  fuzzy matches por partido. Ya documentado como deuda heredada de fase 1.

### 2.4 motor_backtest — V7.3 ya optimizado pero pendiente prueba

- V7.3 (commit 2026-04-17 en `DEPENDENCIAS.md`) recorta el escaneo de 8
  dias fijos x 12 ligas a "fechas unicas con pendientes". Pasa de
  `8 x 12 = 96 GETs` a `len(fechas_unicas) x 12` (tipicamente 1-3 x 12 = 12-36).
- Pendiente: validar empiricamente que `partidos_liquidados` se mantiene
  o sube (no debe bajar) y medir delta de tiempo. Sospecha mia: faltaba
  control de zona horaria al hacer `p[3][:10].replace('-', '')` -- la fecha
  en DB esta en UTC-3 (Argentina) pero la API ESPN responde por dates UTC,
  por lo que un partido nocturno en Argentina (22h UTC-3 = 01h UTC siguiente)
  podria buscarse en el dia equivocado. **Verificar con `tech-lead`.**

### 2.5 motor_cuotas — barrido OK, pero matching fuzzy O(N x M)

- Por cada partido pendiente y por cada evento de la API, hace 2 ratios
  `difflib.SequenceMatcher` (linea 170-174). Es N partidos x M eventos x 2 ratios.
  Para 30 partidos x 30 eventos = 1800 ratios -- aceptable, pero crece cuadratico.
  Con la incorporacion de 7 ligas sudamericanas (sin cobertura Odds-API), el
  bucle no se ejecuta para ellas (linea 126: `if pais in MAPA_LIGAS_ODDS`),
  asi que no hay impacto inmediato.

### 2.6 motor_sincronizador — write-once a Excel local

- Ya migrado a openpyxl local (no gspread celda por celda, MAXIMA III).
- Riesgo: re-escribe el workbook completo en cada run. Si `partidos_backtest`
  pasa de 175 filas (snapshot 13/04) a >1000 al acumular historial, openpyxl
  empieza a tomar varios segundos. No es bottleneck **hoy**, monitorear.

### 2.7 API calls redundantes detectadas

| Donde | Qué pasa | Fix sugerido |
|---|---|---|
| motor_data + motor_backtest | Ambos hacen `scoreboard?dates=...` para las MISMAS fechas+ligas en cada run | Cachear respuesta JSON en `data_cache/<liga>/<fecha>.json` con TTL=1h |
| motor_fixture + motor_data | `motor_fixture` usa fechas `[-1, 5]` futuras; `motor_data` hasta `-365`. Cero overlap - OK. | — |
| motor_arbitro: scoreboard + summary | Doble GET por partido (scoreboard solo para conseguir `id_espn`, luego summary) | Si `motor_data` ya proceso ese evento, persistir `id_espn` en `partidos_backtest` y saltarse el primer GET |
| motor_tactico: fixtures + lineups | 1 GET por liga + 1 GET por fixture matched. Razonable, pero podria batchearse via API-Football "fixtures with lineups=true" si existe ese flag | Verificar API-Football docs |

### 2.8 Queries ineficientes

- `motor_calculadora.py:711-719` SELECT con `WHERE estado='Pendiente' OR estado='Calculado'` sin
  indice. Tabla pequeña hoy, pero al escalar añadir `CREATE INDEX idx_estado ON partidos_backtest(estado)`.
- `motor_backtest.py:48-53` SELECT con `WHERE estado='Calculado' AND fecha <= ?` -- mismo problema. Indice
  compuesto `(estado, fecha)` ayudaria.
- `motor_arbitro.py:30-34` SELECT con `WHERE estado='Liquidado' AND (auditoria IS NULL OR auditoria != 'SI')`.
  Idem.
- `motor_calculadora.py:693-701` GROUP BY pais sobre tabla completa. Aceptable hoy, sospechoso a largo plazo.

---

## 3. Hallazgos heredados de fase 1 (insumo prioritario)

### 3.1 motor_backtest V7.3 — pendiente validacion

- Estado: implementado (`src/persistencia/motor_backtest.py:39-117`), no probado
  aun en run completo segun `PLAN.md` seccion 0.
- Riesgo: si la conversion `p[3][:10].replace('-', '')` interpreta mal la
  fecha-hora local UTC-3, podria perder partidos nocturnos. Necesita 1 run
  controlado con DB snapshot antes/despues para validar.

### 3.2 Sesgo EMA Argentina

- Confirmado en `metricas_20260413_010048.json`:
  - Argentina: `avg_fav_h=1.82`, `avg_fav_a=1.75` (los **mas bajos** del dataset).
  - Inglaterra: 2.49 / 2.46. Brasil: 2.35 / 2.24. Noruega: 2.65 / 2.72.
- Causa probable (segun `Reglas_IA.txt` y `PLAN.md` seccion 0):
  - ESPN sub-reporta tiros en partidos argentinos (no validado empiricamente).
  - `coef_corner_calculado=0.02` default cuando `total_corners=0` para esa liga.
- Esto es deuda matematica -> **la dispara `experto-deportivo` o `analista-datos`**,
  yo solo la documento en el flujo. Si toca corregir el xG, debe ir a
  `motor_data.py` (no `motor_calculadora.py`) por la leccion FIX A REVERTIDO.

### 3.3 corners=0 en todas las ligas

- `motor_data.py:373-417` calcula `coef_c` solo si `total_goles>50 AND total_corners>0`.
- En la DB, `total_corners=0` global -> `coef_c` queda en default 0.02 -> el componente
  `corners * 0.02` aporta < 0.05 al xG, irrelevante.
- Causa raiz que veo en codigo: ESPN devuelve `cornerKicks` correctamente en `stats_loc`/
  `stats_vis` (linea 397-398), pero el `estado_ligas[pais]["corners"]` solo se incrementa
  en el flujo "evento nuevo procesado". Si `id_unico in procesados` (linea 366), se hace
  `continue` antes de sumar corners. Despues del primer `--rebuild`, los corners deberian
  acumular bien -- **verificar con `analista-datos`** que la columna `total_corners`
  realmente este en cero o si es un bug de visualizacion.

### 3.4 equipos_stats legacy con `liga='Desconocido'`

- Documentado en `PLAN.md` seccion 0 (21 equipos). No afecta el cerebro
  `motor_calculadora` (consulta `historial_equipos`, no `equipos_stats`),
  pero **si afecta `motor_tactico`**: `motor_tactico.py:128-141` hace
  `INSERT INTO equipos_stats` con `liga=pais`, no actualiza la liga en filas
  existentes. Si un equipo "zombi" ya existe con `liga='Desconocido'`, queda asi.
- Es deuda de schema -> compete a `analista-datos`, no toco.

---

## 4. Propuesta de pipeline optimizado

### 4.1 Cambios de orden / paralelismo (sin tocar matematica)

**Hoy:** las fases 1 y 2 son secuenciales total. **Propuesta:**

```
FASE 0  motor_purga                                                     (1s)
FASE 1A motor_backtest                                                  (5-10s tras V7.3)
FASE 1B motor_liquidador                                                (1s)
FASE 1C [PARALELO]                                                      (~80s, antes ~250s)
        +-- motor_arbitro    (CPU + I/O ESPN summary)
        +-- motor_data       (CPU + I/O ESPN scoreboard)  <-- cuello principal
FASE 2  [PARALELO]                                                      (~30s, antes ~80s)
        +-- motor_fixture    (I/O ESPN + Odds-API failover)
        +-- motor_cuotas     (I/O Odds-API)
        +-- motor_tactico    (I/O API-Football)
FASE 3  motor_calculadora                                               (1-2s)
FASE 4  motor_backtest (2da pasada) -> motor_liquidador                 (5s)
        motor_sincronizador                                              (3-5s)
```

Dependencias respetadas:
- `motor_arbitro` lee `partidos_backtest WHERE estado='Liquidado'` -> NO depende
  de `motor_data` ni de `motor_fixture` para esa lectura. Compatible con paralelo.
- `motor_data` solo escribe en `historial_equipos`/`ligas_stats`/`ema_procesados`
  -> NO toca `partidos_backtest`. Compatible con paralelo respecto a `motor_arbitro`.
- `motor_fixture`, `motor_cuotas`, `motor_tactico` leen/escriben columnas DISTINTAS
  de `partidos_backtest`. Riesgo: SQLite SERIALIZADO en escrituras -> hay que activar
  `PRAGMA journal_mode=WAL` en TODOS los motores que paralelicen escritura. Hoy solo
  `motor_fixture`, `motor_arbitro`, `motor_tactico` lo activan.

**Prerrequisito**: validar que las escrituras a `partidos_backtest` no colisionen
en la misma fila al mismo tiempo. Sospecho que NO colisionan (cada motor escribe
columnas distintas: fixture inserta filas, cuotas updatea cuotas, tactico updatea
formaciones), pero requiere confirmacion de `analista-datos` mirando el schema.

### 4.2 Caching de respuestas ESPN

Crear `data_cache/espn/<liga>/<YYYYMMDD>.json` con TTL=1h. `motor_data`,
`motor_backtest` y `motor_arbitro` lo leen primero; si miss, hacen GET y graban.
Estimacion: ahorra 50-70% de GETs cuando se ejecuta el pipeline 2 veces el mismo dia
(escenario comun en testing).

### 4.3 Indices SQLite faltantes

```sql
CREATE INDEX IF NOT EXISTS idx_pb_estado_fecha ON partidos_backtest(estado, fecha);
CREATE INDEX IF NOT EXISTS idx_pb_pais         ON partidos_backtest(pais);
CREATE INDEX IF NOT EXISTS idx_he_liga         ON historial_equipos(liga);
CREATE INDEX IF NOT EXISTS idx_pb_auditoria    ON partidos_backtest(estado, auditoria);
```

Ganancia: marginal hoy (~175 filas), pero a 5000+ partidos historicos
empieza a notarse. Coordinar con `analista-datos` antes de aplicar.

### 4.4 Sesion HTTP persistente

Reemplazar `requests.get(...)` por una `requests.Session()` por motor.
Ahorra el TCP+TLS handshake en cada request (~50-150ms ganados por GET
sobre 4380 GETs worst case = potencialmente 3-10 min ahorrados en motor_data
modo PROFUNDIDAD_INICIAL).

---

## 5. Dependencias criticas con otros agentes

### Lo que pido a `analista-datos`:

1. **Schema canonico de `partidos_backtest`**: ¿que columnas escribe que motor?
   Quiero un mapa columna -> motor unico (o lista de motores) para validar mi
   hipotesis de paralelismo seguro en FASE 2.
2. **Estado real de `total_corners` en `ligas_stats`**: ¿esta realmente en 0
   para todas las ligas? Si si, ¿es bug de motor_data o de visualizacion?
3. **Conteo de filas legacy en `equipos_stats`**: confirmar las 21 zombi y
   evaluar impacto en `motor_tactico`.
4. **Tabla `configuracion`**: schema y valores actuales (bankroll, otros).
   No la veo creada en ningun motor, debe estar en alguna migracion vieja.
5. **Recomendar si los indices propuestos en 4.3 son seguros** (no romper
   uniqueness, no duplicar indices implicitos).

### Lo que pido a `tech-lead`:

1. **Validar V7.3 de motor_backtest** con un run controlado (DB snapshot
   antes/despues, contar `Calculado` -> `Finalizado` y comparar contra
   pre-V7.3 sobre el mismo dataset).
2. **Confirmar que motor_data no toca `partidos_backtest` excepto el UPDATE
   de `sot_l/shots_l/...`** -- si ese UPDATE puede mover a un `executemany`
   final, la paralelizacion FASE 1C es viable.
3. **Implementar `requests.Session()` y caching** SOLO si lo aprobamos
   con el Lead. Yo no lo toco.
4. **Coordinar instrumentacion `[T]`**: agregar `time.perf_counter()` por
   motor para medir wall-clock real y confirmar mis estimaciones.

### Lo que NO toco (por restriccion):

- Formulas matematicas (Reglas_IA.txt bloqueado, fix A REVERTIDO documentado).
- Strings exactos (`'GANADA'`, `'PERDIDA'`, `'Calculado'`, etc.).
- Constantes/dicts bloqueados (DEPENDENCIAS.md seccion 6).
- Codigo (read-only de mi rol). Solo redacto en `docs/fase2/`.

---

## 6. Riesgos identificados

| # | Riesgo | Probabilidad | Mitigacion |
|---|---|---|---|
| 1 | Paralelizar FASE 1C/2 produce SQLite locks intermitentes | Media | Activar WAL en TODOS los motores antes de paralelizar; ejecutar 5 runs de validacion |
| 2 | V7.3 motor_backtest pierde liquidaciones por bug TZ | Baja-Media | Run controlado pre/post con snapshot; auditar 1 partido nocturno argentino |
| 3 | Caching ESPN sirve datos stale para "in_progress" matches | Media | TTL=1h es agresivo; partidos en juego -> bypass cache (ej: `?nocache=1` interno) |
| 4 | `requests.Session()` mantiene conexion zombie si ESPN cuelga | Baja | Configurar timeout y `Adapter(max_retries=2)` |
| 5 | Indices nuevos rompen migracion existente | Baja | `IF NOT EXISTS` + correr en `--rebuild` controlado |
| 6 | El fix de paralelismo enmascara bugs por race condition que aparecen en prod | Media | Logs detallados con timestamp ms en el primer run paralelo |

---

## 7. Lista de tareas ordenadas (con esfuerzo)

| # | Tarea | Esfuerzo | Bloqueo |
|---|---|---|---|
| 1 | Instrumentar `time.perf_counter()` en cada motor para medir wall-clock real | S (2h) | tech-lead |
| 2 | Validar motor_backtest V7.3 con DB snapshot antes/despues | S (1h) | tech-lead |
| 3 | Confirmar schema `partidos_backtest` con `analista-datos` y mapear columna->motor | S (1h) | analista-datos |
| 4 | Diseñar layout de cache `data_cache/espn/...` y politica TTL | M (3h) | OK del Lead |
| 5 | Implementar `requests.Session()` + caching en motor_data, motor_backtest, motor_arbitro | M (4h) | tech-lead |
| 6 | Activar `PRAGMA journal_mode=WAL` en motor_data, motor_calculadora, motor_purga | XS (30 min) | tech-lead |
| 7 | Crear indices SQL propuestos en 4.3 | XS (30 min) | analista-datos |
| 8 | Refactor a paralelismo FASE 1C (motor_data + motor_arbitro concurrentes) | L (6h) | items 5+6 |
| 9 | Refactor a paralelismo FASE 2 (motor_fixture + motor_cuotas + motor_tactico) | L (6h) | items 5+6 |
| 10 | Documentar el flujo paralelizado en `docs/fase2/DATA_FLOW_optimizado.md` | S (2h) | items 8+9 |

Esfuerzo total estimado: **~26h ingenieria + ~4h validacion**, incremental y reversible.

---

## 8. Hallazgos no urgentes para anotar

- `motor_purga` borra equipos por `ultima_actualizacion < cutoff`, pero NO
  limpia `equipos_stats` (solo `historial_equipos`). Crea desincronizacion
  entre tablas. Documentado en deuda heredada -> compete a `analista-datos`.
- `motor_liquidador` y `motor_purga` hardcodean `DB_NAME='fondo_quant.db'`
  -- el resto del refactor de fase 1 los respeto. Documentar en deuda menor.
- `MAPA_LIGAS_ESPN = {pais: codigo for codigo, pais in LIGAS_ESPN.items()}`
  se reconstruye en runtime en 2 motores (`motor_arbitro:17`, `motor_backtest:18`).
  Si en algun momento alguien duplica un valor en `LIGAS_ESPN`, esto colapsa
  silenciosamente. Mover el inverso a `config_sistema.py` es 5 min de trabajo
  defensivo.
- `motor_sincronizador.py` hardcodea `DB_NAME` y `EXCEL_FILE` -- consistente
  con la nota de DEPENDENCIAS.md.

---

## 9. Estado final

Plan listo para revision del Lead. Ningun motor ejecutado en este ciclo.
Ningun archivo `.py` modificado. **IDLE** despues del DM al Lead.

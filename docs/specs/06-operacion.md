# Orquestador (ejecutar_proyecto.py)

## Propósito

Es el punto de entrada único del sistema. Corre la cascada diaria y los subcomandos de mantenimiento. Cada motor corre como proceso hijo.

## Entradas

- Argumentos de línea de comandos (`ejecutar_proyecto.py:638-710`).
- `config.json` en la raíz, solo para el preflight (`ejecutar_proyecto.py:175-183`).
- Base `DB_NAME` (`ejecutar_proyecto.py:34`).
- Scripts de `MOTORES_DIARIOS` (`ejecutar_proyecto.py:47-77`).

## Salidas (tablas y columnas que escribe)

El orquestador escribe solo por medio de sus hijos y de algunos subcomandos:

| Comando | Qué hace | Escribe en la base | Línea |
|---|---|---|---|
| (sin argumentos) | Corre la cascada completa y el resumen | Sí, vía motores | `ejecutar_proyecto.py:596-632` |
| `--status` | Muestra estado sin tocar la base | No. Llama a la API de API-Football | `ejecutar_proyecto.py:196-381` |
| `--summary` | Resumen de picks y liquidaciones | No | `ejecutar_proyecto.py:387-442` |
| `--analisis [nombre]` | Corre un script del catálogo | Depende del script | `ejecutar_proyecto.py:448-465` |
| `--rebuild` | Importa CSV, purga y desbloquea, luego corre la cascada | Sí | `ejecutar_proyecto.py:664-675` |
| `--unlock` | Pone estados en Pendiente tras confirmar RESET, luego corre la cascada | Sí | `ejecutar_proyecto.py:677-683` |
| `--purge-history` | Vacía tablas derivadas, luego corre la cascada | Sí | `ejecutar_proyecto.py:684-690` |
| `--audit-names` | Auditoría interactiva de nombres | Depende del script | `ejecutar_proyecto.py:691-695` |
| `--aporte MONTO` | Inserta un aporte o retiro | Sí: tabla `aportes_capital` | `ejecutar_proyecto.py:471-545` |
| `--aportes-list` | Lista aportes y su total | No | `ejecutar_proyecto.py:548-576` |
| `--exportar-excel` | Genera el Excel (ver Exportación Excel) | Sí, en `estado` de `partidos_backtest` | `ejecutar_proyecto.py:700-702` |
| `--help` | Muestra comandos y cascada | No | `ejecutar_proyecto.py:582-590` |

La tabla `aportes_capital` tiene columnas `id`, `fecha`, `monto`, `descripcion` y `fecha_creacion` (`ejecutar_proyecto.py:516-524`).

Cascada diaria (`MOTORES_DIARIOS`, 19 motores, en este orden):

| # | Archivo | Crítico | Interactivo | Línea |
|---|---|---|---|---|
| 0 | `motor_purga.py` | No | No | 49 |
| 1 | `motor_backtest.py` | Sí | No | 52 |
| 1.5 | `motor_liquidador.py` | Sí | No | 53 |
| 1.6 | `scripts/evaluar_pretest.py` | No | No | 54 |
| 2 | `motor_arbitro.py` | No | No | 55 |
| 3 | `motor_data.py` | Sí | No | 56 |
| 3.1 | `scripts/scrape_sofa_post_liquidacion.py --dias 7 --max 30` | No | No | 57 |
| 3.15 | `analisis/motor_xg_v2_14_xg_from_shotmap.py` | No | No | 58 |
| 3.16 | `analisis/xg_v3_hibrido_sofa_custom.py` | No | No | 59 |
| 3.17 | `scripts/rebuild_ema_v2.py` | No | No | 60 |
| 3.2 | `-m src.persistencia.actualizar_posiciones` | No | No | 61 |
| 3.4 | `scripts/xg_pesos_dinamicos_shadow.py` | No | No | 62 |
| 3.5 | `motor_adaptativo.py` | No | No | 63 |
| 4 | `motor_fixture.py` | Sí | Sí | 67 |
| 6 | `motor_cuotas.py` | Sí | No | 68 |
| 7 | `motor_calculadora.py` | Sí | No | 71 |
| 7.5 | `scripts/aplicar_antifiltro_shotmap_f4b.py` | No | No | 72 |
| 8 | `motor_backtest.py` | No | No | 75 |
| 8.5 | `motor_liquidador.py` | No | No | 76 |

## Comportamiento (reglas exactas, en orden, con path:line)

Reglas de arranque:

1. Cambia el directorio de trabajo a la raíz del repo (`ejecutar_proyecto.py:31-32`).
2. Agrega la raíz a `sys.path` (`ejecutar_proyecto.py:33`).
3. Fuerza UTF-8 en stdout y stderr (`ejecutar_proyecto.py:37-41`).
4. Limpia la pantalla solo si la salida es una terminal (`ejecutar_proyecto.py:639-640`).

Reglas de la cascada diaria:

5. Corre preflight: DB, `config.json` y módulos (`ejecutar_proyecto.py:598`, `:167-190`).
6. Aborta sin DB si el archivo no existe o pesa 0 bytes (`ejecutar_proyecto.py:604-607`).
7. Ejecuta cada motor en orden, en un subproceso `python -u` (`ejecutar_proyecto.py:613-614`, `:125`).
8. Fusiona stderr en stdout para que no bloquee el pipe (`ejecutar_proyecto.py:136`).
9. Imprime cada línea del hijo con prefijo `   | ` (`ejecutar_proyecto.py:142`).
10. Marca fallo si el código de salida no es 0 (`ejecutar_proyecto.py:144-147`).
11. Si un motor crítico falla, imprime ABORTO y sale con código 1 (`ejecutar_proyecto.py:617-619`).
12. Si un motor satélite falla, lo anota y sigue (`ejecutar_proyecto.py:616`, `:620-621`).
13. Al final imprime los satélites fallidos y el resumen (`ejecutar_proyecto.py:623-632`).
14. Sale con código 0 aunque haya satélites fallidos (`ejecutar_proyecto.py:623-629`).

Reglas de subcomandos:

15. `--rebuild` corre importador, purga y desbloqueo. Si un paso falla, aborta antes de los siguientes (`ejecutar_proyecto.py:664-675`).
16. `--unlock` corre el desbloqueo y luego la cascada. Si falla, sale con código 1 (`ejecutar_proyecto.py:677-683`).
17. `--purge-history` corre la purga y luego la cascada (`ejecutar_proyecto.py:684-690`).
18. `--aporte` valida monto y fecha antes de insertar (`ejecutar_proyecto.py:485-510`).
19. Un comando desconocido imprime la ayuda y sale con código 1 (`ejecutar_proyecto.py:707-710`).

## Invariantes (lo que nunca debe pasar)

- Ningún motor posterior corre si un motor crítico falla (`ejecutar_proyecto.py:617-619`).
- La cascada nunca corre sin una base existente y no vacía (`ejecutar_proyecto.py:604-607`).
- `--rebuild` nunca purga tablas derivadas si la importación falla (`ejecutar_proyecto.py:666`, `tests/test_orquestador.py:28-36`).
- `--unlock` nunca resetea la base sin escribir RESET (`src/nucleo/desbloquear_matriz.py:18-22`).
- Todo cambio manual de datos o de esquema debe tener respaldo previo (ver Respaldos). El pipeline diario no crea respaldo.

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| `ADEPOR_DB` (variable de entorno) | Vacía. Usa `fondo_quant.db` en la raíz (`src/comun/config_sistema.py:15`) | Cambia la base que usan todos los motores |
| Campo `critico` por motor | Ver tabla de cascada | Decide si el fallo aborta el pipeline |
| Campo `interactivo` por motor | Solo `motor_fixture.py` | Hereda la terminal en vez de capturar la salida |
| Argumentos de SofaScore | `--dias 7 --max 30` (`ejecutar_proyecto.py:57`) | Ventana y tope del scraper post liquidación |
| `api_keys_odds` en `config.json` | Lista vacía | Si está vacía, el preflight avisa que `motor_cuotas` fallará |
| `INACTIVITY_MONTHS` en `src/persistencia/motor_purga.py` | 6 meses | Antigüedad para purgar equipos |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

Tests existentes (`tests/test_orquestador.py`):

- `test_hijo_con_mucho_stderr_no_bloquea` (`:13`): stderr grande no bloquea el hijo.
- `test_hijo_que_falla_devuelve_false` (`:23`): un hijo con error devuelve False.
- `test_rebuild_aborta_si_falla_un_paso` (`:28`): `--rebuild` no sigue tras un fallo.

Huecos sin test:

- No hay test de la regla de motor crítico en `cmd_pipeline_diario` (`ejecutar_proyecto.py:617-619`).
- No hay test del preflight ni del aborto sin base (`ejecutar_proyecto.py:167`, `:604-607`).
- No hay test del orden ni de las banderas de `MOTORES_DIARIOS` (`ejecutar_proyecto.py:47-77`).
- No hay test de `--status`, `--summary`, `--aporte` ni `--aportes-list`.
- No hay test del código de salida final con satélites fallidos.

## Limitaciones conocidas

- Sale con código 0 aunque fallen motores satélite (`ejecutar_proyecto.py:623-629`). `ejecutar_robot.sh` no detecta esos fallos.
- `--status` llama a la API de API-Football (`ejecutar_proyecto.py:343-370`). Esa API está retirada según el comentario de `ejecutar_proyecto.py:66`.
- El preflight revisa `api_keys_odds` pero no `api_keys_football` (`ejecutar_proyecto.py:182-183`).
- `ejecutar_motor` no tiene timeout (`ejecutar_proyecto.py:117-158`). Un motor colgado detiene la cascada.
- En `--unlock` y `--rebuild`, el prompt de RESET se escribe sin salto de línea. El subproceso captura stdout, así que el prompt no se ve (`src/nucleo/desbloquear_matriz.py:19`, `ejecutar_proyecto.py:140`).
- `--purge-history` no pide confirmación (`src/persistencia/reset_tablas_derivadas.py`).
- `--rebuild` falla en el primer paso si falta `modelo_estable.csv` (`src/persistencia/importador_gold.py:16`). El archivo no está en el repo.
- `motor_fixture.py` figura como interactivo (`ejecutar_proyecto.py:67`). El módulo no usa `input()` (`src/ingesta/motor_fixture.py:10-11`).

# Ejecución programada (ejecutar_robot.sh)

## Propósito

Corre el pipeline diario desde cron. Guarda la salida en un log por fecha.

## Entradas

- Variable `ADEPOR_PYTHON`. Default: `.venv/bin/python` (`ejecutar_robot.sh:6`).
- Script `ejecutar_proyecto.py` (`ejecutar_robot.sh:9`).

## Salidas (tablas y columnas que escribe)

- Archivo `data/logs/pipeline_YYYYMMDD.log`, con modo append (`ejecutar_robot.sh:7-9`).
- Ninguna tabla. Los motores hijos escriben en la base.

## Comportamiento (reglas exactas, en orden, con path:line)

1. Activa `set -euo pipefail` (`ejecutar_robot.sh:4`).
2. Cambia al directorio del script (`ejecutar_robot.sh:5`).
3. Elige el intérprete con `ADEPOR_PYTHON` o el default (`ejecutar_robot.sh:6`).
4. Crea `data/logs` si no existe (`ejecutar_robot.sh:7`).
5. Fija el nombre del log con la fecha del día (`ejecutar_robot.sh:8`).
6. Corre `ejecutar_proyecto.py` y agrega stdout y stderr al log (`ejecutar_robot.sh:9`).
7. Termina con el código de salida de Python (`ejecutar_robot.sh:4`, `:9`).

Horario sugerido en el comentario: `0 9,17 * * *` (`ejecutar_robot.sh:3`).

## Invariantes (lo que nunca debe pasar)

- El log nunca se sobrescribe. Se usa `>>` (`ejecutar_robot.sh:9`).
- Un fallo de Python nunca pasa en silencio. Corta el script por `set -e` (`ejecutar_robot.sh:4`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| `ADEPOR_PYTHON` | `.venv/bin/python` | Intérprete que corre el pipeline |
| Horario de cron | `0 9,17 * * *` (solo sugerido) | Frecuencia de ejecución |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- No hay test del script.
- Hueco: no hay prueba de que el log se crea con la fecha correcta.
- Hueco: no hay prueba del código de salida ante un fallo crítico.

## Limitaciones conocidas

- Depende de bash. En Windows se usa `ejecutar_robot.bat`.
- El log crece sin rotación.
- Cron no activa el entorno virtual. Por eso usa la ruta directa al intérprete.
- La zona horaria es la del sistema. El script no la fija.
- El exit code no refleja fallos satélite (ver Orquestador).

# Configuración (src/comun/config_sistema.py)

## Propósito

Centraliza constantes del sistema: base, ligas, mapas de APIs, estados y claves. Es la única fuente de estas constantes.

## Entradas

- Variable de entorno `ADEPOR_DB` (`src/comun/config_sistema.py:15`).
- Archivo `config.json` en la raíz del repo (`src/comun/config_sistema.py:157-158`).

## Salidas (tablas y columnas que escribe)

- Ninguna. Solo expone constantes en memoria.
- Constantes principales: `DB_NAME`, `LIGAS_ESPN`, `MAPA_LIGAS_ODDS`, `MAPA_LIGAS_API_FOOTBALL`, `API_KEYS_ODDS`, `API_KEYS_FOOTBALL`, `LIGAS_SOFA_PRIMARY`.

## Comportamiento (reglas exactas, en orden, con path:line)

1. Calcula la raíz del repo a partir del archivo (`src/comun/config_sistema.py:14`).
2. Usa `ADEPOR_DB` si existe. Si no, usa `fondo_quant.db` en la raíz (`src/comun/config_sistema.py:15`).
3. Lee `config.json` de la raíz (`src/comun/config_sistema.py:157-161`).
4. Toma `api_keys_odds` como lista (`src/comun/config_sistema.py:162`).
5. Toma `api_keys_football` como lista. Si está vacía, usa `api_key_football` (`src/comun/config_sistema.py:167-169`).
6. Si falta `config.json` o es JSON inválido, imprime advertencia y usa listas vacías (`src/comun/config_sistema.py:170-175`).
7. Define las ligas activas en `LIGAS_ESPN` (`src/comun/config_sistema.py:21-57`).
8. Define el mapa de The Odds API. Varias ligas tienen `None` (`src/comun/config_sistema.py:87-122`).
9. `LIGAS_SOFA_PRIMARY` es solo un andamiaje inactivo (`src/comun/config_sistema.py:74-84`).

## Invariantes (lo que nunca debe pasar)

- Las claves de API nunca van a git. `config.json` está en `.gitignore` (`.gitignore:25`).
- Las claves de API nunca se escriben en el código. Se leen de `config.json` (`src/comun/config_sistema.py:162-167`).
- Según su docstring, agregar una liga solo requiere editar `config_sistema.py` (`src/comun/config_sistema.py:5`). No se verificó en otros módulos.

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Fuente | Default | Efecto |
|---|---|---|---|
| `ADEPOR_DB` | Variable de entorno | Vacía | Cambia la base que usan todos los módulos |
| `api_keys_odds` | `config.json` | Lista vacía | Claves de The Odds API, rotativas |
| `api_key_football` | `config.json` | Cadena vacía | Clave legacy de API-Football |
| `api_keys_football` | `config.json` | Lista vacía | Claves de API-Football, con fallback a la legacy |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- `tests/test_smoke_import.py:1-6`: importa el motor con base vacía. Comprueba que `get_param` no crea la base.
- `tests/conftest.py:9`: fija `ADEPOR_DB` antes de importar.
- Hueco: no hay test del fallback de `config.json` corrupto (`src/comun/config_sistema.py:170-175`).
- Hueco: no hay test del fallback de `api_key_football` a la lista (`src/comun/config_sistema.py:167-169`).

## Limitaciones conocidas

- Si `ADEPOR_DB` es relativa, `config_motor.py` la une a la raíz (`src/comun/config_motor.py:21`). La ruta queda mal.
- La advertencia de config se imprime al importar (`src/comun/config_sistema.py:171`).
- Varias ligas no tienen cuotas: su mapa es `None` (`src/comun/config_sistema.py:94-98`, `:111-121`).

# Inicialización de base (scripts/db/inicializar_db.py)

## Propósito

Crea una base nueva y operable desde cero. Es la ruta de instalación. Nunca toca una base existente.

## Entradas

- Ruta opcional en `argv[1]`. Si falta, usa `DB_NAME` (`scripts/db/inicializar_db.py:116`).
- Semillas de `scripts/db/crear_config_motor.py` (`seed_rows`, 50 filas).

## Salidas (tablas y columnas que escribe)

Tablas creadas:

| Tabla | Origen |
|---|---|
| `config_motor_valores` (con índice y trigger) | `scripts/db/crear_config_motor.py:33-60`, `scripts/db/inicializar_db.py:103-105` |
| `partidos_backtest` | `scripts/db/inicializar_db.py:29-47` |
| `historial_equipos` | `scripts/db/inicializar_db.py:49-59` |
| `ema_procesados` | `scripts/db/inicializar_db.py:60` |
| `partidos_historico_externo` | `scripts/db/inicializar_db.py:63-65` |
| `arbitros_stats` | `scripts/db/inicializar_db.py:66-69` |
| `configuracion` | `scripts/db/inicializar_db.py:70` |
| `ligas_stats` | `scripts/db/inicializar_db.py:71-74` |
| `equipos_altitud` | `scripts/db/inicializar_db.py:75` |
| `apuestas_confirmadas` | `scripts/db/inicializar_db.py:76-79` |

Semillas con valor distinto al manifiesto:

| Clave | Scope | Valor | Línea |
|---|---|---|---|
| `factor_corr_xg_ou` | global | 1.0 | `scripts/db/inicializar_db.py:23`, `:86-88` |
| `gamma_1x2` | global | 1.0 | `scripts/db/inicializar_db.py:23`, `:89` |
| `apuesta_ou_live` | global | FALSE | `scripts/db/inicializar_db.py:91-92` |
| `ema_prior_por_equipo` | global | TRUE | `scripts/db/inicializar_db.py:93` |

## Comportamiento (reglas exactas, en orden, con path:line)

1. Si la ruta existe y pesa más de 0 bytes, lanza FileExistsError (`scripts/db/inicializar_db.py:98-99`).
2. Abre la conexión (`scripts/db/inicializar_db.py:100`).
3. Activa el modo WAL (`scripts/db/inicializar_db.py:102`).
4. Crea `config_motor_valores`, su índice y su trigger (`scripts/db/inicializar_db.py:103-105`).
5. Inserta las semillas con `INSERT OR IGNORE` (`scripts/db/inicializar_db.py:106-108`).
6. Crea las tablas base (`scripts/db/inicializar_db.py:109`).
7. Confirma y cierra la conexión (`scripts/db/inicializar_db.py:110-112`).

## Invariantes (lo que nunca debe pasar)

- Una base existente nunca se sobrescribe (`scripts/db/inicializar_db.py:98-99`).
- Una base nueva nunca arranca con O/U en LIVE (`scripts/db/inicializar_db.py:91-92`).
- Una base nueva nunca arranca con 1X2 en LIVE. El default de `apuestas_live` es FALSE (`src/nucleo/motor_calculadora.py:2199`).
- Cada par (clave, scope) aparece una sola vez (clave primaria de `config_motor_valores`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Clave | Default de la semilla | Efecto |
|---|---|---|
| `ema_prior_por_equipo` | TRUE | Las EMAs nacen en escala de goles por equipo |
| `factor_corr_xg_ou` | 1.0 | Sin compensación del prior por partido |
| `gamma_1x2` | 1.0 | Sin compensación del prior por partido |
| `apuesta_ou_live` | FALSE | O/U arranca en pretest, con stake 0 |
| Resto de claves | Ver `scripts/db/crear_config_motor.py` | Parámetros del manifiesto |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- `tests/test_flujo_dinero_real.py:10,22`: usa `inicializar` para crear la base de la prueba de punta a punta.
- `tests/test_prior_ema.py:52,61,70,97`: prueban el prior por equipo y el flag.
- Hueco: no hay test de `FileExistsError` en `inicializar`.
- Hueco: no hay test de que la base nueva tenga todas las tablas que leen los motores.

## Limitaciones conocidas

- La semilla no crea `apuestas_live` (`scripts/db/inicializar_db.py:91-92` solo trata `apuesta_ou_live`). La promoción automática de 1X2 no tiene filas que actualizar (`scripts/evaluar_pretest.py:195-196`).
- Lo mismo pasa en la base actual `fondo_quant.db`: no tiene filas `apuestas_live`.
- `crear_config_motor.py` exige que la base exista (`scripts/db/crear_config_motor.py:186-188`). Para crear desde cero se usa `inicializar_db.py`.

# Esquema versionado (scripts/db/esquema.py)

## Propósito

Exporta el esquema de la base actual a SQL. También crea bases vacías a partir de ese SQL.

## Entradas

- Base `DB_NAME` en modo `--exportar` (`scripts/db/esquema.py:21`, `:56`).
- Archivo `docs/db_schema.sql` en modo `--crear` (`scripts/db/esquema.py:23`, `:41`).

## Salidas (tablas y columnas que escribe)

- `--exportar` escribe `docs/db_schema.sql`, con tablas, índices y vistas en ese orden (`scripts/db/esquema.py:26-38`).
- `--crear` crea la base nueva con el SQL ejecutado (`scripts/db/esquema.py:41-46`).

## Comportamiento (reglas exactas, en orden, con path:line)

1. `--exportar` abre la base en modo solo lectura (`scripts/db/esquema.py:29`).
2. Lee `sqlite_master` y excluye objetos `sqlite_*` (`scripts/db/esquema.py:31-35`).
3. Escribe cada objeto con su `;` y una línea en blanco (`scripts/db/esquema.py:37`).
4. `--crear` rechaza una base existente y no vacía (`scripts/db/esquema.py:42-43`).
5. `--crear` ejecuta el SQL completo con `executescript` (`scripts/db/esquema.py:44-45`).

## Invariantes (lo que nunca debe pasar)

- `--crear` nunca sobrescribe una base existente (`scripts/db/esquema.py:42-43`).
- `--exportar` nunca escribe en la base origen (`scripts/db/esquema.py:29`, modo `ro`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| Ruta del esquema | `docs/db_schema.sql` (`scripts/db/esquema.py:23`) | Archivo que lee `--crear` y escribe `--exportar` |
| Base de origen | `DB_NAME` | Base que se exporta |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- `tests/test_db_esquema.py:9-23`: exporta, crea y compara los objetos. Comprueba que `crear` rechaza una base existente.
- Hueco: no hay test del archivo `docs/db_schema.sql` real.

## Limitaciones conocidas

- `docs/db_schema.sql` no existe en el repo. `--crear` falla con FileNotFoundError hasta correr `--exportar`.
- El docstring dice que el esquema queda congelado en git (`scripts/db/esquema.py:4-6`). El archivo no está.
- Exporta solo el esquema. No exporta datos.
- La ruta del esquema está fija. No acepta argumentos.

# Respaldos y estado (adepor_guard.py)

## Propósito

Crea respaldos de la base y métricas JSON. Compara el estado actual contra un respaldo. Restaura la base. Es el mecanismo de respaldo previo a cambios de datos.

## Entradas

- Base `DB_NAME` (`adepor_guard.py:27`).
- Directorio `snapshots/` relativo al directorio actual (`adepor_guard.py:29`).
- Argumentos de línea de comandos (`adepor_guard.py:346-372`).

## Salidas (tablas y columnas que escribe)

| Comando | Archivo que escribe | Línea |
|---|---|---|
| `snapshot` | `snapshots/fondo_quant_TS.db` | `adepor_guard.py:165-166` |
| `snapshot` | `snapshots/metricas_TS.json` | `adepor_guard.py:179-181` |
| `shadow` | `fondo_quant_shadow.db` (relativo al directorio actual) | `adepor_guard.py:30`, `:276` |
| `restore` | `snapshots/pre_restore_TS.db` y luego sobrescribe `DB_NAME` | `adepor_guard.py:295-297`, `:306` |
| `compare` | Nada. Solo imprime | `adepor_guard.py:195-260` |
| `status` | Nada. Solo imprime | `adepor_guard.py:311-339` |

## Comportamiento (reglas exactas, en orden, con path:line)

1. `snapshot` crea `snapshots/` si no existe (`adepor_guard.py:161`).
2. `snapshot` copia la base con la API de backup de SQLite (`adepor_guard.py:166`, `:33-47`).
3. `snapshot` extrae métricas: estados, liquidados, rho, EMA, últimas apuestas (`adepor_guard.py:170`, `:54-152`).
4. `snapshot` escribe el JSON con bloque `_meta` (`adepor_guard.py:173-181`).
5. `compare` sin argumento usa el último `metricas_*.json` (`adepor_guard.py:197-203`).
6. `compare` marca cambios de estado y cambios de rho (`adepor_guard.py:214-236`).
7. `compare` marca drift de EMA mayor a 0.05 (`adepor_guard.py:247`).
8. `shadow` pide confirmación si la sombra ya existe (`adepor_guard.py:269-274`).
9. `restore` copia la base actual a `pre_restore_TS.db` antes de todo (`adepor_guard.py:293-297`).
10. `restore` pide confirmación con "s" (`adepor_guard.py:301-304`).
11. `restore` sobrescribe `DB_NAME` desde el respaldo (`adepor_guard.py:306`).
12. `status` lista snapshots y la sombra (`adepor_guard.py:311-339`).

## Invariantes (lo que nunca debe pasar)

- Un restore nunca ocurre sin copia de seguridad previa (`adepor_guard.py:295-297`).
- Un snapshot nunca omite datos del archivo WAL (`adepor_guard.py:34-35`, prueba en `tests/test_ops_guard.py:9-29`).
- Un restore nunca ocurre sin confirmación interactiva (`adepor_guard.py:301-304`).
- Las rutas de respaldo nunca deben depender del directorio actual. Hoy dependen (ver Limitaciones).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| `SNAPSHOTS_DIR` | `snapshots` (`adepor_guard.py:29`) | Carpeta de respaldos |
| `SHADOW_DB` | `fondo_quant_shadow.db` (`adepor_guard.py:30`) | Nombre de la base sombra |
| Umbral de drift EMA | 0.05 (`adepor_guard.py:247`) | Marca cambios grandes en EMA |
| Umbral de cambio de estado | 50 filas (`adepor_guard.py:223`) | Marca cambios grandes en estados |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- `tests/test_ops_guard.py:9-29`: el snapshot incluye commits que están en el WAL.
- Hueco: `compare`, `shadow`, `restore` y `status` no tienen test.
- Hueco: no hay test de que `restore` deje una copia previa.

## Limitaciones conocidas

- `SNAPSHOTS_DIR` y `SHADOW_DB` son relativos al directorio actual (`adepor_guard.py:29-30`). Correr desde otra carpeta crea respaldos en otro lugar.
- `compare` solo compara conteos y promedios. No detecta cambios de contenido.
- `restore` acepta cualquier archivo SQLite. No valida que sea una base de Adepor (`adepor_guard.py:306`).
- `shadow` y `restore` piden confirmación con `input()`. No corren sin terminal (`adepor_guard.py:271`, `:301`).
- Los respaldos no van a git (`.gitignore:19`).

# Dependencias y pruebas (requirements, pytest.ini, conftest)

## Propósito

Fija las versiones de dependencias. Aísla la base de las pruebas.

## Entradas

- `requirements.txt` con siete paquetes fijados (`requirements.txt:1-7`).
- `requirements-analisis.txt`, que incluye `requirements.txt` y agrega paquetes de análisis y pruebas (`requirements-analisis.txt:1-8`).
- `pytest.ini` (`pytest.ini:1-3`).
- `tests/conftest.py` (`tests/conftest.py:1-72`).

## Salidas (tablas y columnas que escribe)

- Entorno Python en `.venv`. Ninguna tabla.
- Pruebas usan un archivo temporal, no `fondo_quant.db`.

## Comportamiento (reglas exactas, en orden, con path:line)

1. `requirements.txt` fija requests, openpyxl, numpy, scikit-learn, curl_cffi, streamlit y altair (`requirements.txt:1-7`).
2. `requirements-analisis.txt` incluye el anterior y agrega pandas, scipy, beautifulsoup4, pytest, matplotlib y xgboost (`requirements-analisis.txt:1-8`).
3. `pytest.ini` busca pruebas en `tests` y usa `-q` (`pytest.ini:1-3`).
4. `conftest.py` crea un directorio temporal y fija `ADEPOR_DB` antes de importar `src` (`tests/conftest.py:8-10`).
5. El fixture `db` borra y recrea el archivo de prueba en cada test (`tests/conftest.py:55-65`).
6. Al importarse, `conftest.py` crea el esquema mínimo (`tests/conftest.py:70-72`).

## Invariantes (lo que nunca debe pasar)

- Las pruebas nunca abren `fondo_quant.db` (`tests/conftest.py:9`).
- El pipeline diario no debería importar paquetes de análisis. Una búsqueda de importaciones de nivel superior no encontró scipy, xgboost, matplotlib ni sklearn en `src/` ni en los motores raíz.

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Valor | Efecto |
|---|---|---|
| `testpaths` | `tests` (`pytest.ini:2`) | Carpeta donde busca pruebas |
| `addopts` | `-q` (`pytest.ini:3`) | Salida corta |
| `ADEPOR_DB` en pruebas | Archivo temporal (`tests/conftest.py:9`) | Aísla la base de prueba |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- Hay 29 archivos `test_*.py` y unas 114 funciones de prueba.
- Hueco: no hay prueba de que `requirements.txt` instale sin `pytest`.
- Hueco: no hay prueba de que el directorio temporal se limpie.

## Limitaciones conocidas

- `pytest` no está en `requirements.txt`. Solo está en `requirements-analisis.txt` (`requirements-analisis.txt:5`).
- `conftest.py` crea un directorio temporal y no lo borra (`tests/conftest.py:8`).
- `tests/test_orquestador.py` importa `ejecutar_proyecto`, que cambia el directorio al importarse (`ejecutar_proyecto.py:32`).
- `xgboost` y `matplotlib` tienen cota inferior, no versión fija (`requirements-analisis.txt:7-8`).

# Hooks de tareas (scripts/hooks, .claude/settings.json)

## Propósito

Bloquea tareas que tocan el manifiesto sin aprobación. Exige métricas al cerrar tareas de optimización o de datos.

## Entradas

- JSON de la tarea por stdin, según el formato de Claude Code (`scripts/hooks/validate_task_created.py:86`, `scripts/hooks/validate_task_completed.py:96`).
- Consulta a `bd show <id> --json` para ver labels (`scripts/hooks/validate_task_created.py:59-69`).

## Salidas (tablas y columnas que escribe)

- Código de salida 0 (permite) o 2 (bloquea).
- Mensaje en stderr.
- Ninguna escritura en la base ni en beads.

## Comportamiento (reglas exactas, en orden, con path:line)

Configuración (`.claude/settings.json`):

1. `PreCompact` corre `bd prime` (`.claude/settings.json:3-13`).
2. `SessionStart` corre `bd prime` (`.claude/settings.json:14-24`).
3. `TaskCreated` corre `python3 scripts/hooks/validate_task_created.py` (`.claude/settings.json:25-35`).
4. `TaskCompleted` corre `python3 scripts/hooks/validate_task_completed.py` (`.claude/settings.json:36-46`).

`validate_task_created.py`:

5. Lee stdin. Si el JSON es inválido, deja pasar (`scripts/hooks/validate_task_created.py:74-81`).
6. Busca `Reglas_IA.txt`, `manifest` o `motor_calculadora.py` (`scripts/hooks/validate_task_created.py:28-32`, `:86`).
7. Busca constantes protegidas (`scripts/hooks/validate_task_created.py:34-38`, `:87`).
8. Si no hay coincidencias, deja pasar (`scripts/hooks/validate_task_created.py:89-90`).
9. Si hay coincidencias y falta el tag `MANIFESTO-CHANGE-APPROVED:bd-<id>` o `HUMAN`, bloquea con código 2 (`scripts/hooks/validate_task_created.py:93-109`).
10. Si hay tag `bd-<id>`, consulta el label `approved-by-lead` (`scripts/hooks/validate_task_created.py:112-117`).
11. Si `bd` no responde, avisa y deja pasar (`scripts/hooks/validate_task_created.py:118-119`).
12. Ante error inesperado, deja pasar (`scripts/hooks/validate_task_created.py:127-129`).

`validate_task_completed.py`:

13. Clasifica la tarea como optimizador por palabras clave (`scripts/hooks/validate_task_completed.py:45-48`, `:100`).
14. Clasifica la tarea como DataOps por palabras clave (`scripts/hooks/validate_task_completed.py:50-53`, `:101`).
15. Si no clasifica, deja pasar (`scripts/hooks/validate_task_completed.py:103-104`).
16. Un optimizador debe incluir `EV_total_horizonte`, `N`, `snapshot_db_sha256`, `delta_brier` y `delta_yield` (`scripts/hooks/validate_task_completed.py:33-39`).
17. DataOps debe incluir `snapshot_db_sha256` (`scripts/hooks/validate_task_completed.py:41-43`).
18. Si faltan métricas, bloquea con código 2 (`scripts/hooks/validate_task_completed.py:116-137`).
19. Ante error inesperado, deja pasar (`scripts/hooks/validate_task_completed.py:143-145`).

## Invariantes (lo que nunca debe pasar)

- Un cambio al manifiesto nunca pasa sin label `approved-by-lead`. Excepción: si `bd` no responde (`scripts/hooks/validate_task_created.py:118-119`).
- Un hook nunca escribe en la base.
- Los hooks nunca llaman a un intérprete distinto de `python3` (`tests/test_ops_hooks.py:55-62`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Valor | Efecto |
|---|---|---|
| `CONSTANTES_PROTEGIDAS` | `ALFA_EMA`, `N0_ANCLA`, `RHO_FALLBACK`, `FACTOR_CORR_XG_OU`, `FLOOR_PROB_MIN`, `MARGEN_PREDICTIVO_1X2`, `CORR_VISITA`, `MAX_KELLY_PCT_NORMAL`, `MAX_KELLY_PCT_DRAWDOWN` (`scripts/hooks/validate_task_created.py:34-38`) | Disparan validación estricta |
| Timeout de `bd show` | 15 s (`scripts/hooks/validate_task_created.py:64`) | Tiempo máximo de consulta |
| Métricas de optimizador | Cinco campos (`scripts/hooks/validate_task_completed.py:33-39`) | Requisitos de cierre |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

`tests/test_ops_hooks.py` tiene nueve pruebas:

- `:23` tarea operativa pasa.
- `:27` optimizador sin métricas bloquea. `N` suelta no cuenta.
- `:33` métricas completas en texto pasan.
- `:38` métricas en un diccionario de evidencia pasan.
- `:45` DataOps exige SHA-256.
- `:51` JSON inválido deja pasar.
- `:55` `settings.json` usa `python3`.
- `:64` payload real con `task_description`.
- `:75` `TaskCreated` exige label en el bead.

Huecos sin test:

- No hay test del caso `bd` caído (fail-open).
- No hay test de `TaskCompleted` ante error inesperado.

## Limitaciones conocidas

- `validate_task_completed.py` solo busca palabras. No valida que los valores sean correctos (`scripts/hooks/validate_task_completed.py:78-79`).
- Los hooks dejan pasar ante errores. Un fallo del hook no bloquea la tarea (`scripts/hooks/validate_task_created.py:128-129`, `scripts/hooks/validate_task_completed.py:143-145`).
- El tag puede escribirlo el mismo agente. Por eso `TaskCreated` consulta el bead (`scripts/hooks/validate_task_created.py:111-112`).
- La clasificación por palabras puede marcar tareas comunes como optimizador.

# Runbook

## Primera instalación (Linux)

Ejecutar en este orden. Cada bloque es un solo comando.

Paso 1. Situarse en la raíz del repo:

```bash
cd /home/mpera/BetDeportivo
```

Paso 2. Crear el entorno virtual:

```bash
python3 -m venv .venv
```

Paso 3. Instalar dependencias de análisis y pruebas:

```bash
.venv/bin/python -m pip install -r requirements-analisis.txt
```

Paso 4. Copiar la plantilla de claves. Luego el usuario edita `config.json` con sus claves reales:

```bash
cp config.example.json config.json
```

Paso 5. Crear la base nueva con semillas:

```bash
.venv/bin/python scripts/db/inicializar_db.py
```

Paso 6. Verificar el estado sin tocar la base:

```bash
.venv/bin/python ejecutar_proyecto.py --status
```

Paso 7. Correr las pruebas:

```bash
.venv/bin/python -m pytest
```

Paso 8. Opcional. Cargar historia desde CSV. Hoy falla si falta `modelo_estable.csv`. Además corre la cascada completa y consulta APIs:

```bash
.venv/bin/python ejecutar_proyecto.py --rebuild
```

## Operación diaria

Pipeline completo:

```bash
.venv/bin/python ejecutar_proyecto.py
```

Resumen tras la última corrida:

```bash
.venv/bin/python ejecutar_proyecto.py --summary
```

Estado del sistema:

```bash
.venv/bin/python ejecutar_proyecto.py --status
```

Dashboard local en 127.0.0.1:

```bash
./iniciar_dashboard.sh
```

Ver el log del día:

```bash
tail -n 200 data/logs/pipeline_$(date +%Y%m%d).log
```

Línea de crontab para correr dos veces al día (pegar con `crontab -e`):

```bash
0 9,17 * * * /home/mpera/BetDeportivo/ejecutar_robot.sh
```

Registrar un aporte. Reemplazar los valores entre `<>`:

```bash
.venv/bin/python ejecutar_proyecto.py --aporte <monto> --fecha <YYYY-MM-DD> --desc "<texto>"
```

Listar aportes y retiros:

```bash
.venv/bin/python ejecutar_proyecto.py --aportes-list
```

Generar el Excel bajo demanda:

```bash
.venv/bin/python ejecutar_proyecto.py --exportar-excel
```

Ver cambios de pretest sin aplicarlos:

```bash
.venv/bin/python scripts/evaluar_pretest.py --dry-run
```

Aplicar pasos a LIVE. Mueve dinero real. Requiere aprobación humana:

```bash
.venv/bin/python scripts/evaluar_pretest.py --aprobar-live
```

## Antes de cambiar la base

Crear un respaldo con la API de SQLite:

```bash
.venv/bin/python adepor_guard.py snapshot
```

Ver los respaldos disponibles:

```bash
.venv/bin/python adepor_guard.py status
```

Comparar el estado actual contra el último respaldo:

```bash
.venv/bin/python adepor_guard.py compare
```

Restaurar un respaldo. Revisar antes el archivo. Reemplazar `<archivo>`:

```bash
.venv/bin/python adepor_guard.py restore snapshots/<archivo>.db
```

No usar `cp` sobre la base viva. La base corre en modo WAL y `cp` puede omitir commits (`adepor_guard.py:33-35`).

## Operaciones destructivas

Vaciar tablas derivadas y correr la cascada. No pide confirmación. Crear respaldo antes:

```bash
.venv/bin/python ejecutar_proyecto.py --purge-history
```

Resetear estados a Pendiente y correr la cascada. Pide escribir RESET. Crear respaldo antes:

```bash
.venv/bin/python ejecutar_proyecto.py --unlock
```

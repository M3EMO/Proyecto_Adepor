# Ingesta

## Propósito

Este documento describe cómo entran los datos al pipeline. Cubre cuatro módulos. El código es la fuente de verdad. Las fuentes activas son ESPN y The Odds API. SofaScore y API-Football están retirados. El v1 (`motor_data`, `motor_arbitro`) se borró en D-023.

Los módulos son estos:

- `motor_fixture` crea los partidos próximos en `partidos_backtest`.
- `motor_cuotas` captura las cuotas de mercado para cada partido vivo.
- `gestor_nombres` resuelve cada nombre crudo al nombre oficial de la liga.
- `tiempo` convierte fechas y calcula la hora ART.

## Entradas

| Fuente | Endpoint o clave | Usado por | Referencia |
|---|---|---|---|
| ESPN scoreboard | `site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates=YYYYMMDD` | `motor_fixture` | `src/ingesta/motor_fixture.py:54` |
| The Odds API scores | `api.the-odds-api.com/v4/sports/{liga}/scores/` | `motor_fixture` (failover) | `src/ingesta/motor_fixture.py:68` |
| The Odds API odds | `api.the-odds-api.com/v4/sports/{liga}/odds/` | `motor_cuotas` | `src/ingesta/motor_cuotas.py:85` |
| Configuración | `LIGAS_ESPN`, `MAPA_LIGAS_ODDS`, `API_KEYS_ODDS`, `DB_NAME` | Todos | `src/comun/config_sistema.py` |
| Diccionario de nombres | `diccionario_equipos.json` (ruta relativa al directorio de trabajo) | `gestor_nombres` | `src/comun/gestor_nombres.py:24` |
| Base de datos | `partidos_backtest` | `motor_cuotas` | `src/ingesta/motor_cuotas.py:183-187` |

## Salidas (tablas y columnas que escribe)

| Módulo | Tabla | Columnas escritas | Referencia |
|---|---|---|---|
| `motor_fixture` | `partidos_backtest` | `id_partido`, `fecha`, `local`, `visita`, `pais`, `estado` (valor `'Pendiente'`) | `src/ingesta/motor_fixture.py:149-153` |
| `motor_cuotas` | `partidos_backtest` | `cuota_1`, `cuota_x`, `cuota_2`, `cuota_o25`, `cuota_u25` | `src/ingesta/motor_cuotas.py:267-275` |
| `motor_cuotas` | `partidos_backtest` | `cuota_cierre_1x2`, `cuota_cierre_ou` | `src/ingesta/motor_cuotas.py:294-300` |
| `gestor_nombres` | `diccionario_equipos.json` (archivo, no tabla) | Alias nuevos por liga | `src/comun/gestor_nombres.py:49-51` |


## Comportamiento (reglas exactas, en orden, con path:line)

### motor_fixture (`src/ingesta/motor_fixture.py`)

1. El módulo abre la base en modo WAL con `isolation_level=None` (`motor_fixture.py:25-27`).
2. El módulo crea `partidos_backtest` si no existe (`motor_fixture.py:29-39`).
3. El módulo recorre 7 fechas, desde ayer hasta 5 días adelante en UTC (`motor_fixture.py:43`).
4. Para cada fecha y cada liga de `LIGAS_ESPN`, pide el scoreboard de ESPN (`motor_fixture.py:48-57`).
5. Si ESPN falla por red o por HTTP, el módulo cambia a The Odds API (`motor_fixture.py:59-61`).
6. El failover solo corre si la liga está en `MAPA_LIGAS_ODDS` y quedan claves (`motor_fixture.py:64`).
7. Si no hay claves, el failover devuelve cero eventos sin mensaje (`motor_fixture.py:64-78`).
8. La rotación de clave ocurre solo con respuesta 401 o 429 (`motor_fixture.py:72-73`).
9. El módulo parsea la fecha UTC del evento con dos formatos (`motor_fixture.py:88-93`).
10. Si el formato no coincide, el módulo registra alerta y omite el evento (`motor_fixture.py:94-96`).
11. El ID usa la fecha UTC del evento en formato `YYYY-MM-DD` (`motor_fixture.py:99`).
12. La fecha guardada es la fecha UTC menos 3 horas, en formato `YYYY-MM-DD HH:MM` (`motor_fixture.py:101-102`).
13. Cada nombre pasa por `gestor_nombres.obtener_nombre_estandar` con modo interactivo solo si hay TTY (`motor_fixture.py:108-109`, `motor_fixture.py:11`).
14. Si un equipo no es conocido en la liga, el módulo omite el partido (`motor_fixture.py:112-117`).
15. El ID es `fecha_iso + local_limpio + visita_limpio` (`motor_fixture.py:120-122`).
16. El módulo busca el mismo par local-visita en la base (`motor_fixture.py:127`).
17. Si una fecha existente está a 3 días o menos, el módulo bloquea la inserción (`motor_fixture.py:140-147`).
18. La inserción usa `ON CONFLICT(id_partido) DO NOTHING` (`motor_fixture.py:149-156`).
19. Cualquier excepción por evento registra un aviso y sigue con el siguiente (`motor_fixture.py:157-159`).

### motor_cuotas (`src/ingesta/motor_cuotas.py`)

1. Sin claves en `API_KEYS_ODDS`, el módulo imprime error y sale con código 1 (`motor_cuotas.py:172-175`).
2. El módulo toma partidos con `estado != 'Liquidado'` y sin goles (`motor_cuotas.py:183-187`).
3. El módulo agrupa los partidos por liga de The Odds API (`motor_cuotas.py:194-200`).
4. La consulta pide solo eventos con inicio futuro, usando `commenceTimeFrom` en UTC (`motor_cuotas.py:86-92`).
5. Si la respuesta es 429 o 401, el módulo rota la clave y reintenta (`motor_cuotas.py:99-101`).
6. Un error de red devuelve vacío y registra solo el tipo de error (`motor_cuotas.py:104-107`).
7. Cada evento de la API pasa por el mismo gestor de nombres (`motor_cuotas.py:216-228`).
8. Solo compiten eventos cuyo kickoff cae a 12 horas o menos de la fecha del partido (`motor_cuotas.py:53-62`, `:289-290`).
9. El primer intento de match es exacto sobre nombres normalizados (`motor_cuotas.py:292-297`).
10. Si no hay match exacto, el módulo usa similitud media de al menos 0,75 (`motor_cuotas.py:299-311`).
10. El 1X2 sale de Pinnacle. Si Pinnacle no da las tres cuotas, sale de bet365 (`motor_cuotas.py:113-131`).
11. Un libro vale solo si da local, empate y visita a la vez (`motor_cuotas.py:129-131`).
12. El O/U 2,5 sale del primer libro del orden Pinnacle, bet365, 1xbet, betfair_ex_eu, draftkings que tenga Over y Under (`motor_cuotas.py:137-159`).
13. Si el O/U sale de un libro blando, el módulo avisa (`motor_cuotas.py:162-163`).
14. Las cuotas del partido se escriben solo si no hubo alerta confirmada y el kickoff es futuro (`motor_cuotas.py:266`, `motor_cuotas.py:49-60`).
15. Si el partido ya empezó o tiene apuesta confirmada, el módulo omite la escritura (`motor_cuotas.py:278-279`).
16. Si el kickoff está entre 0 y 2 horas en el futuro, el módulo captura la cuota de cierre para picks con stake (`motor_cuotas.py:26`, `motor_cuotas.py:33-46`, `motor_cuotas.py:286-301`).
17. La cuota de cierre se escribe aunque el partido tenga apuesta confirmada (`motor_cuotas.py:286`, `motor_cuotas.py:19-20`).
18. El módulo hace un solo commit al final (`motor_cuotas.py:308`).

### gestor_nombres (`src/comun/gestor_nombres.py`)

1. El modo interactivo queda activo solo con TTY (`gestor_nombres.py:185`).
2. `limpiar_texto` pasa a minúsculas, quita tildes y deja solo a-z y 0-9 (`gestor_nombres.py:59-66`).
3. Un nombre vacío vuelve sin cambios (`gestor_nombres.py:187-189`).
4. El alcance de búsqueda es la liga, una copa, o todas las ligas si la liga es desconocida (`gestor_nombres.py:81-108`).
5. Una liga desconocida activa el fallback global y no usa fuzzy (`gestor_nombres.py:203-206`, `gestor_nombres.py:236-238`).
6. La fase 1 busca el nombre limpio y sus raíces sin sufijos ruido (`gestor_nombres.py:69-78`, `gestor_nombres.py:209-221`).
7. La fase 2 acepta el nombre si ya es un oficial de la liga (`gestor_nombres.py:224-231`).
8. La fase 3 usa `difflib` con umbral 0,95 dentro del alcance acotado (`gestor_nombres.py:31`, `gestor_nombres.py:239-242`).
9. La fase 3 rechaza un match si el oficial pertenece a otra liga (`gestor_nombres.py:250-259`).
10. La fase 4 devuelve el nombre crudo si no hay modo interactivo (`gestor_nombres.py:269-270`).
11. En modo interactivo, el módulo sugiere un oficial con similitud 0,55 y pide confirmación S/N (`gestor_nombres.py:272-287`).
12. Un nombre manual se acepta solo si `nombre_equipo_valido` lo aprueba (`gestor_nombres.py:134-138`, `gestor_nombres.py:290-292`).
13. Cada alias aprendido se guarda en `diccionario_equipos.json` (`gestor_nombres.py:261-262`, `gestor_nombres.py:301`).

### tiempo (`src/comun/tiempo.py`)

1. `fecha_a_espn` devuelve la fecha en formato `YYYYMMDD` (`tiempo.py:12-14`).
2. `fecha_db_a_espn` acepta `YYYY-MM-DD` o `DD/MM/YYYY` (`tiempo.py:22-29`).
3. `ahora_art` devuelve la hora UTC menos 3 horas, sin zona horaria (`tiempo.py:32-38`).

## Invariantes (lo que nunca debe pasar)

- Ningún equipo sin mapear entra a `partidos_backtest` sin TTY (`motor_fixture.py:112-117`).
- Ningún partido se inserta dos veces con el mismo ID (`motor_fixture.py:30`, `motor_fixture.py:152`).
- Ningún par local-visita se inserta dos veces dentro de 3 días (`motor_fixture.py:140-147`).
- Ninguna cuota de un partido empezado se sobrescribe (`motor_cuotas.py:49-60`, `motor_cuotas.py:266`).
- Ninguna cuota de un pick confirmado se sobrescribe (`motor_cuotas.py:63-65`, `motor_cuotas.py:266`).
- Ningún evento de la API se empareja con un partido de otra fecha (`motor_cuotas.py:53-62`).
- Ningún libro mezcla cuotas de 1X2 de dos casas distintas (`motor_cuotas.py:129-131`).
- Ningún nombre inválido se guarda como alias (`gestor_nombres.py:290-292`).
- Ningún match fuzzy cruza países (`gestor_nombres.py:250-259`).
- Ninguna clave de API aparece en mensajes de error (`motor_fixture.py:80-82`, `motor_cuotas.py:105-106`).

## Parámetros (clave de config_motor_valores, default en código, efecto)

Los módulos de ingesta no leen claves de `config_motor_valores`.

Constantes fijas en código, sin clave en la base:

| Constante | Valor | Efecto | Referencia |
|---|---|---|---|
| `VENTANA_CIERRE` | 2 horas | Ventana para capturar la cuota de cierre. | `motor_cuotas.py:26` |
| `AUTO_LEARN_CUTOFF` | 0,95 | Similitud mínima para aprender un alias por fuzzy. | `gestor_nombres.py:31` |
| Umbral de sugerencia interactiva | 0,55 | Similitud mínima para sugerir un oficial al usuario. | `gestor_nombres.py:276` |
| Ventana de fechas de fixture | -1 a +5 días | Días que busca `motor_fixture`. | `motor_fixture.py:43` |
| Ventana anti time-shift | 3 días | Días de distancia que bloquean una inserción. | `motor_fixture.py:140` |
| Estados finalizados de ESPN | `STATUS_FINAL`, `STATUS_FULL_TIME` | Estados que cuentan como partido terminado. | `src/comun/constantes_espn.py:11` |

## Tests de aceptación

Tests existentes que cubren este componente:

| Archivo | Tests | Cubre |
|---|---|---|
| `tests/test_ingesta_cuotas.py` | `test_puede_actualizar_cuotas_reglas`, `test_tiene_alerta_con_y_sin_tabla`, `test_extraer_1x2_prefiere_pinnacle_aunque_bet365_vaya_primero`, `test_extraer_1x2_no_mezcla_libros_si_pinnacle_no_tiene_empate`, `test_obtener_datos_api_key_fuera_de_url`, `test_obtener_datos_api_error_red_imprime_solo_tipo`, `test_main_sin_keys_falla` | `motor_cuotas`: reglas de escritura, prioridad de libros, claves, salida sin claves. |
| `tests/test_ingesta_apifootball.py` | `test_odds_fixture_no_mezcla_bookies` | Adaptador de odds. API-Football está retirado. |
| `tests/test_gestor_nombres.py` | `test_es_conocido`, `test_sin_tty_no_pide_input`, `test_nombre_equipo_valido`, `test_prompt_rechaza_comando` | `gestor_nombres`: conocidos, modo sin TTY, validación. |
| `tests/test_confirmaciones.py` | `test_confirmar_guarda_cuota_y_stake_reales`, `test_no_confirma_partido_empezado`, y otros | Confirmaciones que `motor_cuotas` respeta al escribir cuotas. |

Huecos sin test (no encontré test directo para estos puntos):

- `motor_fixture.main` completo, incluida la ventana anti time-shift (`motor_fixture.py:127-147`).
- El match fuzzy de `motor_cuotas` (`motor_cuotas.py:244-255`).
- `ahora_art` (`tiempo.py:32-38`).
- El aprendizaje de alias de `gestor_nombres` por fuzzy y raíces (`gestor_nombres.py:209-243`).

## Limitaciones conocidas

- La ventana anti time-shift bloquea rematches legítimos dentro de 3 días (`motor_fixture.py:140-147`).
- `motor_fixture` fija el desfase ART en 3 horas (`motor_fixture.py:101`).
- Ese valor duplica `tiempo.py:38` y no lo llama.
- `motor_cuotas` escribe `1xBet` en la consulta (`motor_cuotas.py:91`).
- `motor_cuotas` escribe `1xbet` en el orden de O/U (`motor_cuotas.py:137`).
- No verifiqué si The Odds API distingue mayúsculas.
- El comentario de `gestor_nombres.py:29-30` dice 0,92.
- El valor real es 0,95 (`gestor_nombres.py:31`).
- En `gestor_nombres.py:294-303`, un nombre manual no se guarda si la liga no está en el diccionario.
- `DICCIONARIO_FILE` es una ruta relativa al directorio de trabajo (`gestor_nombres.py:24`, `motor_cuotas.py:68`).
- Correr desde otra carpeta lee o crea otro archivo.
- La escritura de `diccionario_equipos.json` no tiene bloqueo entre procesos (`gestor_nombres.py:49-51`).
- `src/ingesta/motor_cuotas_apifootball.py` y su test siguen en el repo, aunque ningún módulo los llama.

## Anexo v2 (D-021): cuotas Pinnacle

- Desde el 2026-10-22, `MAPA_LIGAS_ODDS` también cubre Libertadores, Sudamericana, EFL Cup, DFB Pokal, Copa del Rey, Coppa Italia y Coupe de France.
- `motor_cuotas` consulta solo ligas con partidos vivos y clave no nula, así que una copa fuera de temporada no gasta cupo.

- `motor_cuotas` guarda también las cuotas de Pinnacle solas en `pin_1`, `pin_x`, `pin_2`, `pin_o25` y `pin_u25`.
- Esas columnas se actualizan hasta el kickoff, aunque el partido tenga una apuesta confirmada.
- Dentro de la ventana de cierre se guardan `pin_cierre_*` para todos los partidos emparejados.
- Ningún UPDATE pisa un valor existente con cero.
- Tests: `tests/test_ingesta_pinnacle.py`.

# Ingesta

## Propósito

Este documento describe cómo entran los datos al pipeline. Cubre seis módulos. El código es la fuente de verdad. Las fuentes activas son ESPN y The Odds API. SofaScore es un enriquecimiento opcional. API-Football está retirado.

Los módulos son estos:

- `motor_fixture` crea los partidos próximos en `partidos_backtest`.
- `motor_data` carga resultados y estadísticas, y actualiza las EMA por equipo.
- `motor_cuotas` captura las cuotas de mercado para cada partido vivo.
- `motor_arbitro` asigna árbitro y mantiene estadísticas por árbitro.
- `gestor_nombres` resuelve cada nombre crudo al nombre oficial de la liga.
- `tiempo` convierte fechas y calcula la hora ART.

## Entradas

| Fuente | Endpoint o clave | Usado por | Referencia |
|---|---|---|---|
| ESPN scoreboard | `site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates=YYYYMMDD` | `motor_fixture`, `motor_data`, `motor_arbitro` | `src/ingesta/motor_fixture.py:54`, `src/ingesta/motor_data.py:740`, `src/ingesta/motor_arbitro.py:71` |
| ESPN summary | `.../summary?event={id}` | `motor_arbitro` | `src/ingesta/motor_arbitro.py:96` |
| The Odds API scores | `api.the-odds-api.com/v4/sports/{liga}/scores/` | `motor_fixture` (failover) | `src/ingesta/motor_fixture.py:68` |
| The Odds API odds | `api.the-odds-api.com/v4/sports/{liga}/odds/` | `motor_cuotas` | `src/ingesta/motor_cuotas.py:85` |
| SofaScore (tabla local) | `sofascore_match_features` | `motor_data` (stats y xG v2) | `src/ingesta/motor_data.py:186-193`, `src/ingesta/motor_data.py:322-326` |
| Configuración | `LIGAS_ESPN`, `MAPA_LIGAS_ODDS`, `API_KEYS_ODDS`, `DB_NAME`, `LIGAS_SOFA_PRIMARY` | Todos | `src/comun/config_sistema.py` |
| Diccionario de nombres | `diccionario_equipos.json` (ruta relativa al directorio de trabajo) | `gestor_nombres`, `motor_arbitro` | `src/comun/gestor_nombres.py:24` |
| Base de datos | `partidos_backtest` | `motor_cuotas`, `motor_arbitro`, `motor_data` | `src/ingesta/motor_cuotas.py:183-187`, `src/ingesta/motor_arbitro.py:33-38` |

El scraper `scripts/scrape_sofa_post_liquidacion.py` alimenta `sofascore_match_features`. Ese scraper no forma parte de este documento.

## Salidas (tablas y columnas que escribe)

| Módulo | Tabla | Columnas escritas | Referencia |
|---|---|---|---|
| `motor_fixture` | `partidos_backtest` | `id_partido`, `fecha`, `local`, `visita`, `pais`, `estado` (valor `'Pendiente'`) | `src/ingesta/motor_fixture.py:149-153` |
| `motor_data` | `partidos_backtest` | `sot_l`, `shots_l`, `corners_l`, `sot_v`, `shots_v`, `corners_v` | `src/ingesta/motor_data.py:841-844` |
| `motor_data` | `historial_equipos` | `equipo_norm`, `equipo_real`, `liga`, `ultima_actualizacion`, `ema_xg_favor/contra` (home y away), `partidos_home`, `partidos_away`, `ema_var_*`, `ema_corto_*`, `partidos_corto_*` | `src/ingesta/motor_data.py:862-897` |
| `motor_data` | `ligas_stats` | `liga`, `total_partidos`, `empates`, `rho_calculado`, `total_goles`, `total_corners`, `coef_corner_calculado` | `src/ingesta/motor_data.py:899-913` |
| `motor_data` | `ema_procesados` | `id_partido` | `src/ingesta/motor_data.py:915-916` |
| `motor_data` (con `--rebuild`) | `ema_procesados`, `historial_equipos`, `ligas_stats` | Borra todas las filas | `src/ingesta/motor_data.py:546-552` |
| `motor_cuotas` | `partidos_backtest` | `cuota_1`, `cuota_x`, `cuota_2`, `cuota_o25`, `cuota_u25` | `src/ingesta/motor_cuotas.py:267-275` |
| `motor_cuotas` | `partidos_backtest` | `cuota_cierre_1x2`, `cuota_cierre_ou` | `src/ingesta/motor_cuotas.py:294-300` |
| `motor_arbitro` | `arbitros_stats` | `id_arbitro`, `nombre`, `partidos`, `ema_faltas`, `ema_amarillas`, `ema_rojas`, `ema_penales` | `src/ingesta/motor_arbitro.py:138-144` |
| `motor_arbitro` | `partidos_backtest` | `arbitro`, `id_arbitro`, `auditoria` (valor `'SI'`) | `src/ingesta/motor_arbitro.py:146` |
| `gestor_nombres` | `diccionario_equipos.json` (archivo, no tabla) | Alias nuevos por liga | `src/comun/gestor_nombres.py:49-51` |

`motor_arbitro` no crea la tabla `arbitros_stats`. La tabla debe existir antes de correr el módulo.

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

### motor_data (`src/ingesta/motor_data.py`)

1. Si se pasa `--rebuild`, el módulo pide confirmación con `CONFIRMAR` (`motor_data.py:486-502`).
2. La variable de entorno `REBUILD_YES=1` reemplaza la confirmación manual (`motor_data.py:495`).
3. Con `--rebuild`, el módulo borra `ema_procesados`, `historial_equipos` y `ligas_stats` (`motor_data.py:546-552`).
4. El módulo agrega columnas `sot_l` a `corners_v` en `partidos_backtest` si faltan (`motor_data.py:538-543`).
5. El módulo carga el estado EMA de cada par `(equipo_norm, liga)` (`motor_data.py:554-574`).
6. El módulo carga `ligas_stats` y los IDs de `ema_procesados` (`motor_data.py:576-580`).
7. Cada liga entra a un grupo de profundidad de escaneo (`motor_data.py:680-715`).
8. Una liga sin equipos usa `profundidad_inicial` (`motor_data.py:686`).
9. Una liga con más de 15 por ciento de equipos con menos de 15 partidos usa `profundidad_profunda` (`motor_data.py:698`, `motor_data.py:706-710`).
10. Los equipos con 10 partidos o menos se excluyen del cálculo de profundidad (`motor_data.py:663`, `motor_data.py:693-695`).
11. Las demás ligas usan `profundidad_mantenimiento` (`motor_data.py:712`).
12. Noruega usa 365 días fijos (`motor_data.py:672-674`).
13. El escaneo recorre días desde el más antiguo hasta hoy (`motor_data.py:733-735`).
14. El módulo pide los scoreboards de la fecha en paralelo, con 6 hilos (`motor_data.py:724-741`).
15. Las respuestas se procesan en el hilo principal, en serie (`motor_data.py:745-749`).
16. El módulo omite eventos no finalizados (`motor_data.py:754-755`).
17. Los nombres pasan por `obtener_nombre_estandar` con `modo_interactivo=False` (`motor_data.py:765-766`).
18. El módulo omite el evento si su ID ya está en `ema_procesados`, en formato legacy o en formato nuevo (`motor_data.py:772-776`).
19. El módulo omite el evento si el marcador no es numérico (`motor_data.py:779-784`).
20. El xG de cada equipo se calcula con `calcular_xg_v2_hibrido_sofa` (`motor_data.py:796-805`).
21. Con `xg_v2_hibrido_modo='shadow'`, la función usa el xG V0 (`motor_data.py:293-296`).
22. El xG V0 suma tiros al arco, tiros fuera y corners por sus coeficientes (`motor_data.py:241`).
23. Si el xG V0 da cero y hubo goles, el xG es igual a los goles (`motor_data.py:242-243`).
24. Si no, el xG es 0,70 por el xG calculado más 0,30 por los goles (`motor_data.py:245`).
25. `ajustar_xg_por_estado_juego` ajusta el xG por diferencia de goles (`motor_data.py:807-808`, `motor_data.py:454-477`).
26. El prior de la liga se calcula con `prior_liga_por_equipo` (`motor_data.py:810`).
27. Con la bandera `ema_prior_por_equipo` activa, el prior es el promedio por partido dividido por 2 (`motor_data.py:61-63`).
28. `actualizar_estado` crea el equipo con EMA inicial 1,4 si no existe (`motor_data.py:594-603`).
29. La EMA usa `alfa` por liga (`motor_data.py:591`).
30. La EMA nueva es `xg * alfa + valor_anterior * (1 - alfa)` (`motor_data.py:613-614`).
31. El peso del prior es `N0 / (N0 + N)`, con `N0 = 5` por defecto (`motor_data.py:616`).
32. El valor final es `w_ema * EMA + w_liga * prior`, redondeado a 3 decimales (`motor_data.py:618-619`).
33. La EMA corta usa `alfa_corto = min(2 * alfa, 0,50)` sin prior (`motor_data.py:643-655`).
34. `estado_ligas` acumula partidos, goles, empates y corners de la liga (`motor_data.py:818-825`).
35. Con más de 20 partidos, `rho` se recalcula con una fórmula fija (`motor_data.py:847-849`).
36. Con más de 50 goles y corners positivos, `coef_corner` se recalcula (`motor_data.py:852-855`).
37. Si la liga está en `LIGAS_SOFA_PRIMARY`, las stats de SofaScore reemplazan las de ESPN (`motor_data.py:836-839`).
38. El módulo escribe las stats en `partidos_backtest` (`motor_data.py:841-844`).
39. El módulo guarda `historial_equipos`, `ligas_stats` y `ema_procesados` en un solo commit al final (`motor_data.py:862-918`).

### motor_cuotas (`src/ingesta/motor_cuotas.py`)

1. Sin claves en `API_KEYS_ODDS`, el módulo imprime error y sale con código 1 (`motor_cuotas.py:172-175`).
2. El módulo toma partidos con `estado != 'Liquidado'` y sin goles (`motor_cuotas.py:183-187`).
3. El módulo agrupa los partidos por liga de The Odds API (`motor_cuotas.py:194-200`).
4. La consulta pide solo eventos con inicio futuro, usando `commenceTimeFrom` en UTC (`motor_cuotas.py:86-92`).
5. Si la respuesta es 429 o 401, el módulo rota la clave y reintenta (`motor_cuotas.py:99-101`).
6. Un error de red devuelve vacío y registra solo el tipo de error (`motor_cuotas.py:104-107`).
7. Cada evento de la API pasa por el mismo gestor de nombres (`motor_cuotas.py:216-228`).
8. El primer intento de match es exacto sobre nombres normalizados (`motor_cuotas.py:238-242`).
9. Si no hay match exacto, el módulo usa similitud media de al menos 0,75 (`motor_cuotas.py:244-255`).
10. El 1X2 sale de Pinnacle. Si Pinnacle no da las tres cuotas, sale de bet365 (`motor_cuotas.py:113-131`).
11. Un libro vale solo si da local, empate y visita a la vez (`motor_cuotas.py:129-131`).
12. El O/U 2,5 sale del primer libro del orden Pinnacle, bet365, 1xbet, betfair_ex_eu, draftkings que tenga Over y Under (`motor_cuotas.py:137-159`).
13. Si el O/U sale de un libro blando, el módulo avisa (`motor_cuotas.py:162-163`).
14. Las cuotas del partido se escriben solo si no hubo alerta confirmada y el kickoff es futuro (`motor_cuotas.py:266`, `motor_cuotas.py:49-60`).
15. Si el partido ya empezó o tiene apuesta confirmada, el módulo omite la escritura (`motor_cuotas.py:278-279`).
16. Si el kickoff está entre 0 y 2 horas en el futuro, el módulo captura la cuota de cierre para picks con stake (`motor_cuotas.py:26`, `motor_cuotas.py:33-46`, `motor_cuotas.py:286-301`).
17. La cuota de cierre se escribe aunque el partido tenga apuesta confirmada (`motor_cuotas.py:286`, `motor_cuotas.py:19-20`).
18. El módulo hace un solo commit al final (`motor_cuotas.py:308`).

### motor_arbitro (`src/ingesta/motor_arbitro.py`)

1. El módulo toma partidos `Liquidado` sin auditoría `'SI'` desde hace 21 días (`motor_arbitro.py:12`, `motor_arbitro.py:33-38`).
2. El módulo agrupa los partidos por fecha y país (`motor_arbitro.py:47-50`).
3. El módulo pide un scoreboard por grupo (`motor_arbitro.py:71-74`).
4. Cada evento se empareja con el partido local usando `son_equivalentes` (`motor_arbitro.py:89`).
5. El módulo pide el summary del evento y toma el primer oficial (`motor_arbitro.py:96-103`).
6. Sin boxscore, el módulo no marca el partido y lo reintenta después (`motor_arbitro.py:107-109`).
7. El módulo suma faltas, amarillas, rojas y penales de ambos equipos (`motor_arbitro.py:112-122`).
8. Cada métrica se actualiza con EMA de factor 0,15 (`motor_arbitro.py:20`, `motor_arbitro.py:125-131`).
9. Una EMA igual a cero se reemplaza por el valor nuevo (`motor_arbitro.py:23`).
10. El módulo guarda el árbitro y marca el partido con `auditoria='SI'` (`motor_arbitro.py:138-150`).

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
- Ningún marcador ausente se convierte en 0-0 (`motor_data.py:778-784`).
- Ningún partido entra dos veces a la EMA (`motor_data.py:772-776`, `motor_data.py:915-916`).
- Ningún cambio parcial de la EMA queda guardado si el proceso falla antes del commit (`motor_data.py:918`).
- Ninguna cuota de un partido empezado se sobrescribe (`motor_cuotas.py:49-60`, `motor_cuotas.py:266`).
- Ninguna cuota de un pick confirmado se sobrescribe (`motor_cuotas.py:63-65`, `motor_cuotas.py:266`).
- Ningún libro mezcla cuotas de 1X2 de dos casas distintas (`motor_cuotas.py:129-131`).
- Ningún partido sin boxscore queda marcado como auditado (`motor_arbitro.py:107-109`).
- Ningún nombre inválido se guarda como alias (`gestor_nombres.py:290-292`).
- Ningún match fuzzy cruza países (`gestor_nombres.py:250-259`).
- Ninguna clave de API aparece en mensajes de error (`motor_fixture.py:80-82`, `motor_cuotas.py:105-106`).

## Parámetros (clave de config_motor_valores, default en código, efecto)

| Clave | Scope | Default en código | Efecto | Referencia |
|---|---|---|---|---|
| `alfa_ema` | liga o `global` | Diccionario `ALFA_EMA_POR_LIGA`, fallback 0,15 | Peso de cada partido nuevo en la EMA. | `motor_data.py:45`, `motor_data.py:75-112`, `motor_data.py:591` |
| `n0_ancla` | global | 5 | Peso del prior de liga frente a la EMA. | `motor_data.py:46`, `motor_data.py:616` |
| `ema_prior_por_equipo` | global | `'FALSE'` | Si `TRUE`, el prior es el promedio por equipo. | `motor_data.py:62` |
| `profundidad_inicial` | liga o global | 365 | Días de carga la primera vez que aparece una liga. | `motor_data.py:664`, `motor_data.py:686` |
| `profundidad_profunda` | global | 210 | Días de re-calibración de una liga. | `motor_data.py:665` |
| `profundidad_mantenimiento` | global | 7 | Días de una liga consolidada. | `motor_data.py:666` |
| `beta_sot` | liga o global | 0,352 | Peso de cada tiro al arco en el xG V0. | `motor_data.py:238` |
| `beta_shots_off` | global | 0,010 | Peso de cada tiro fuera o bloqueado en el xG V0. | `motor_data.py:239` |
| `xg_v2_hibrido_modo` | global | `'shadow'` | Si `active`, el xG usa SofaScore con mezcla. | `motor_data.py:293` |
| `alpha_xg_v2_hibrido_sofa` | liga o global | 0,30 | Peso de SofaScore en el xG v2 cuando el modo es `active`. | `motor_data.py:371` |

Constantes fijas en código, sin clave en la base:

| Constante | Valor | Efecto | Referencia |
|---|---|---|---|
| `N0_ANCLA` | 5 | Ver `n0_ancla`. | `motor_data.py:46` |
| `UMBRAL_PARTIDOS_MINIMOS` | 15 | Partidos para considerar un equipo con datos suficientes. | `motor_data.py:660` |
| `UMBRAL_RECIEN_ASCENDIDO` | 10 | Partidos máximos para excluir un equipo recién ascendido. | `motor_data.py:663` |
| Porcentaje de disparo de re-calibración | 0,15 | Fracción de equipos con pocos datos que activa profundidad profunda. | `motor_data.py:706` |
| `LAMBDA_EMA` (árbitro) | 0,15 | Peso de cada partido en la EMA del árbitro. | `motor_arbitro.py:20` |
| `VENTANA_DIAS` (árbitro) | 21 | Días hacia atrás que audita el árbitro. | `motor_arbitro.py:12` |
| `VENTANA_CIERRE` | 2 horas | Ventana para capturar la cuota de cierre. | `motor_cuotas.py:26` |
| `AUTO_LEARN_CUTOFF` | 0,95 | Similitud mínima para aprender un alias por fuzzy. | `gestor_nombres.py:31` |
| Umbral de `son_equivalentes` | 0,85 | Similitud mínima para emparejar nombres en árbitro. | `gestor_nombres.py:147` |
| Umbral de sugerencia interactiva | 0,55 | Similitud mínima para sugerir un oficial al usuario. | `gestor_nombres.py:276` |
| Ventana de fechas de fixture | -1 a +5 días | Días que busca `motor_fixture`. | `motor_fixture.py:43` |
| Ventana anti time-shift | 3 días | Días de distancia que bloquean una inserción. | `motor_fixture.py:140` |
| Estados finalizados de ESPN | `STATUS_FINAL`, `STATUS_FULL_TIME` | Estados que cuentan como partido terminado. | `src/comun/constantes_espn.py:11` |

## Tests de aceptación

Tests existentes que cubren este componente:

| Archivo | Tests | Cubre |
|---|---|---|
| `tests/test_ingesta_cuotas.py` | `test_puede_actualizar_cuotas_reglas`, `test_tiene_alerta_con_y_sin_tabla`, `test_extraer_1x2_prefiere_pinnacle_aunque_bet365_vaya_primero`, `test_extraer_1x2_no_mezcla_libros_si_pinnacle_no_tiene_empate`, `test_obtener_datos_api_key_fuera_de_url`, `test_obtener_datos_api_error_red_imprime_solo_tipo`, `test_main_sin_keys_falla` | `motor_cuotas`: reglas de escritura, prioridad de libros, claves, salida sin claves. |
| `tests/test_ingesta_arbitro.py` | `test_fecha_db_a_espn_acepta_iso_y_ddmmyyyy`, `test_auditar_usa_fecha_iso_y_no_marca_si_sin_boxscore`, `test_no_reintenta_partidos_fuera_de_ventana` | `motor_arbitro` y `tiempo.fecha_db_a_espn`. |
| `tests/test_ingesta_apifootball.py` | `test_odds_fixture_no_mezcla_bookies` | Adaptador de odds. API-Football está retirado. |
| `tests/test_gestor_nombres.py` | `test_es_conocido`, `test_sin_tty_no_pide_input`, `test_nombre_equipo_valido`, `test_prompt_rechaza_comando` | `gestor_nombres`: conocidos, modo sin TTY, validación. |
| `tests/test_confirmaciones.py` | `test_confirmar_guarda_cuota_y_stake_reales`, `test_partido_confirmado_queda_congelado`, `test_no_confirma_partido_empezado`, y otros | Congelamiento de partidos confirmados, usado por `motor_cuotas`. |
| `tests/test_prior_ema.py` | `test_prior_por_equipo_escala_correcta`, `test_prior_liga_por_equipo_respeta_flag`, `test_aplicar_migra_escala_flag_y_factores`, `test_rebuild_no_pisa_emas_sin_sofa_activo` | Prior por equipo y reglas de `--rebuild`. |
| `tests/test_sofa_hook.py` | `test_pendientes_salen_de_partidos_backtest` | Selección de partidos pendientes para SofaScore. |

Huecos sin test (no encontré test directo para estos puntos):

- `motor_fixture.main` completo, incluida la ventana anti time-shift (`motor_fixture.py:127-147`).
- La EMA de `motor_data`, porque `actualizar_estado` vive dentro de `main` (`motor_data.py:588`).
- La idempotencia de `ema_procesados` en `motor_data` (`motor_data.py:772-776`).
- `calcular_xg_hibrido` y `ajustar_xg_por_estado_juego` (`motor_data.py:208`, `motor_data.py:454`).
- `calcular_ema` de árbitro y su caso de EMA igual a cero (`motor_arbitro.py:22-24`).
- El orden de equipos en el summary de árbitro (`motor_arbitro.py:85-86`).
- La ruta de error de `motor_arbitro` (`motor_arbitro.py:152-157`).
- El match fuzzy de `motor_cuotas` (`motor_cuotas.py:244-255`).
- `ahora_art` (`tiempo.py:32-38`).
- El aprendizaje de alias de `gestor_nombres` por fuzzy y raíces (`gestor_nombres.py:209-243`).

## Limitaciones conocidas

- `motor_data` no rechaza equipos desconocidos.
- Esa falta crea filas EMA con nombres crudos (`motor_data.py:765-766`, `gestor_nombres.py:270`).
- `motor_fixture` sí rechaza equipos desconocidos (`motor_fixture.py:112-117`).
- `motor_data` toma `hoy` de `datetime.now()` del host (`motor_data.py:582`, `motor_data.py:734`).
- Un host en otra zona horaria desfasa los IDs legacy cerca de medianoche.
- La tabla `historial_equipos` no define las columnas `ema_corto_*` en su `CREATE TABLE` (`motor_data.py:510-520`).
- El `SELECT` de `motor_data` sí usa esas columnas (`motor_data.py:554-560`).
- Una base nueva sin `scripts/db/inicializar_db.py` falla en `motor_data`.
- `ALFA_EMA_POR_LIGA` no aplica cuando existe fila `global` en `alfa_ema`.
- `get_param` devuelve la fila `global` antes que el default (`src/comun/config_motor.py:60-66`).
- En la base leída, la fila `global` de `alfa_ema` vale 0,15.
- Por eso Italia, España, Alemania y Francia usan 0,15 y no sus valores del diccionario (0,12; 0,12; 0,13; 0,14).
- `rho_calculado` tiene dos escritores.
- `src/nucleo/calibrar_rho.py` lo escribe por MLE (`calibrar_rho.py:415-417`).
- `motor_data` lo sobrescribe con una fórmula fija (`motor_data.py:847-849`) al procesar un partido nuevo de una liga con más de 20 partidos.
- El prior con cero partidos devuelve 1,4 sin importar la bandera (`motor_data.py:59-60`).
- Con la bandera en `FALSE`, el prior usa escala por partido, no por equipo (`motor_data.py:61-63`).
- `motor_data` usa default `'FALSE'` para `ema_prior_por_equipo` (`motor_data.py:62`).
- En la base leída, la fila `global` de `ema_prior_por_equipo` vale `TRUE`.
- `motor_arbitro` toma local y visita por posición en `competitors` (`motor_arbitro.py:85-86`).
- `motor_data` usa el campo `homeAway` (`motor_data.py:759-760`).
- Un orden distinto en ESPN invierte el emparejamiento de árbitros.
- Un `KeyError` antes de `motor_arbitro.py:89` deja `partido_db` sin asignar.
- El manejador de `motor_arbitro.py:155` usa esa variable.
- En el primer evento de la corrida lanza `UnboundLocalError`; después imprime un partido viejo.
- `calcular_ema` de árbitro trata una EMA igual a cero como sin inicializar (`motor_arbitro.py:23`).
- Para rojas, casi siempre cero, el siguiente valor reemplaza la EMA entera.
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
- `src/ingesta/motor_cuotas_apifootball.py` y su test siguen en el repo.
- No verifiqué si el pipeline los llama.
- El lookup de SofaScore falla el primer día de un evento nuevo (`motor_data.py:152-156`).
- El scraper de SofaScore corre después de `motor_data`, así que el dato llega al día siguiente.

## Anexo v2 (D-021): cuotas Pinnacle

- `motor_cuotas` guarda también las cuotas de Pinnacle solas en `pin_1`, `pin_x`, `pin_2`, `pin_o25` y `pin_u25`.
- Esas columnas se actualizan hasta el kickoff, aunque el partido tenga una apuesta confirmada.
- Dentro de la ventana de cierre se guardan `pin_cierre_*` para todos los partidos emparejados.
- Ningún UPDATE pisa un valor existente con cero.
- Tests: `tests/test_ingesta_pinnacle.py`.

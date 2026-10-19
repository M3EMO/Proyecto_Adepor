# Liquidación, confirmaciones y métricas de dinero

## Propósito

Este bloque registra resultados reales y cierra cada apuesta. Calcula el CLV de cada pick con stake. Calcula también el yield y el P/L en dinero real. Cubre cinco piezas: `motor_backtest`, `motor_liquidador`, `resolucion`, `picks` y `confirmaciones`. Los agregados viven en `metricas`, `bankroll` y `yield_potencial`.

El bloque no usa claves de `config_motor_valores`. Sus constantes están en el código.

## Entradas

| Fuente | Campos | Uso |
|---|---|---|
| `partidos_backtest` | id_partido, local, visita, pais, fecha, estado, goles_l, goles_v | Partidos pendientes de resultado y partidos finalizados |
| `partidos_backtest` | apuesta_1x2, apuesta_ou, stake_1x2, stake_ou | Picks y stakes a liquidar |
| `partidos_backtest` | cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25 | Cuota de entrada. Tras una confirmación, guarda la cuota tomada |
| `partidos_backtest` | cuota_cierre_1x2, cuota_cierre_ou | Cuota de cierre para CLV. La escribe `src/ingesta/motor_cuotas.py:296` |
| ESPN scoreboard | eventos, status, competidores, score | Resultado real. URL en `src/persistencia/motor_backtest.py:85` |
| Usuario | id_partido, mercado, cuota_tomada, stake | Entrada de `confirmar_apuesta`. El módulo `dashboard.py` referencia esta función |
| `src/comun/constantes_espn.py:11` | ESTADOS_ESPN_FINALIZADO | Estados ESPN que cuentan como terminados |
| `src/comun/mapas.py` | MAPA_LIGAS_ESPN | Liga a código ESPN |

## Salidas (tablas y columnas que escribe)

| Módulo | Tabla | Columnas | Condición |
|---|---|---|---|
| `motor_backtest` | `partidos_backtest` | goles_l, goles_v, estado = 'Finalizado' | Evento ESPN emparejado y score entero (`motor_backtest.py:116-120`) |
| `motor_liquidador` | `partidos_backtest` | apuesta_1x2, apuesta_ou (tokens), estado | Estado 'Liquidado', o 'Finalizado' si queda una apuesta sin token (`motor_liquidador.py:106-120`) |
| `motor_liquidador` | `partidos_backtest` | clv_pct_1x2, clv_pct_ou | Solo con stake mayor a 0 y cuota de cierre válida (`:88-93`, `:117-118`) |
| `confirmaciones` | `apuestas_confirmadas` | id_partido, mercado, pick, cuota_tomada, stake, ts | Una fila por partido y mercado (`confirmaciones.py:18-21`, `:59-62`) |
| `confirmaciones` | `partidos_backtest` | cuota_1/x/2 u cuota_o25/u25 (cuota tomada), stake_1x2 o stake_ou | Misma transacción que el insert (`:66-67`) |

`metricas.metricas_dinero` y `yield_potencial.yield_potencial` no escriben en la base. Devuelven diccionarios para el dashboard.

## Comportamiento (reglas exactas, en orden, con path:line)

### motor_backtest (`src/persistencia/motor_backtest.py`)

1. El módulo busca partidos con estado Pendiente o Calculado y fecha no posterior a ahora (`:57-62`).
2. El módulo consulta ESPN solo en las fechas únicas donde hay pendientes (`:77`, `:79`).
3. El módulo consulta un scoreboard por liga y fecha, con timeout de 5 segundos (`:82-87`).
4. El módulo ignora respuestas distintas de 200 (`:88`).
5. El módulo acepta un evento si `completed` es verdadero o si su estado está en `ESTADOS_ESPN_FINALIZADO` (`:92-97`).
6. El módulo normaliza los nombres de equipos con `obtener_nombre_estandar` (`:103-104`).
7. Un evento empareja con un pendiente si el país coincide, la fecha difiere en 1 día o menos y los nombres limpios son iguales (`:32-45`, `:106-107`).
8. Si un score no es entero, el módulo avisa y deja el partido pendiente (`:109-113`).
9. Al emparejar, el módulo escribe goles y pone estado 'Finalizado' (`:116-120`).
10. Un error de red se ignora en esa consulta, sin reintento inmediato (`:130`).
11. Un error al procesar un evento se registra y el módulo sigue con el siguiente (`:127-129`).

### motor_liquidador (`src/persistencia/motor_liquidador.py`)

12. El módulo toma solo partidos con estado 'Finalizado' (`:48-55`).
13. El módulo omite partidos sin goles (`:72-73`).
14. El módulo reemplaza `[APOSTAR]` por `[GANADA]` o `[PERDIDA]` en cada mercado resoluble (`:76-83`).
15. El módulo calcula CLV en 1X2 solo si stake_1x2 es mayor a 0 (`:88-90`).
16. El módulo calcula CLV en O/U solo si stake_ou es mayor a 0 (`:91-93`).
17. El CLV es (cuota apostada / cuota de cierre − 1) × 100 (`:21-31`).
18. El CLV es None si la cuota apostada o la de cierre es 0, vacía o negativa (`:27-30`).
19. Si una apuesta con stake no tiene token, el partido queda 'Finalizado' y el módulo avisa (`:98-104`, `:107`).
20. Si no hay apuesta sin token, el partido pasa a 'Liquidado', aunque no tenga apuestas (`:107`).
21. El UPDATE usa COALESCE en CLV, así que un CLV previo no se borra (`:114-118`).
22. Un error SQL revierte la transacción y no escribe nada (`:128-131`).

### Resolución de tokens (`src/comun/resolucion.py`)

23. `determinar_resultado_token` devuelve None si el pick no contiene `[APOSTAR]` o si faltan goles (`:36-37`).
24. LOCAL gana si goles locales son mayores que goles visita (`:38`).
25. EMPATE gana si los goles son iguales (`:39`).
26. VISITA gana si goles visita son mayores que goles locales (`:40`).
27. OVER 2.5 gana si el total es mayor que 2.5, y UNDER 2.5 gana si es menor (`:41-42`).

### Cuota del pick (`src/comun/picks.py`)

28. `cuota_para_pick` reconoce los prefijos `[APOSTAR]`, `[GANADA]` y `[PERDIDA]` (`:18`, `:30-33`).
29. Cada token canónico lee su columna: LOCAL a cuota_1, EMPATE a cuota_x, VISITA a cuota_2, OVER 2.5 a cuota_o25 y UNDER 2.5 a cuota_u25 (`:19-22`, `:47-57`).
30. La función devuelve 0.0 si el pick no se reconoce o si falta la cuota (`:58`).

### Confirmación (`src/persistencia/confirmaciones.py`)

31. `confirmar_apuesta` rechaza un mercado distinto de 1X2 u OU (`:44-45`).
32. La función rechaza una cuota menor o igual a 1 o un stake menor o igual a 0 (`:46-47`).
33. La función exige que la columna del mercado empiece con `[APOSTAR]` (`:49-52`).
34. La función rechaza partidos cuya fecha ya pasó (`:53-54`).
35. La función toma el pick sin prefijo y busca su columna de cuota (`:55-58`).
36. Una sola transacción inserta en `apuestas_confirmadas` y actualiza el partido (`:63-67`).
37. Un chequeo previo lanza ValueError si el mercado ya está confirmado, y la clave primaria lo respalda (`:59-62`, `:18-21`).
38. La función escribe la cuota tomada en la columna de cuota del pick (`:66-67`).
39. La función escribe el stake real en stake_1x2 o stake_ou (`:66-67`).
40. La función devuelve el pick sin prefijo (`:68`).

### Métricas de dinero (`src/persistencia/metricas.py`)

42. `metricas_dinero` suma P/L y volumen solo en filas con estado 'Liquidado', goles cargados y stake mayor a 0 (`:84-88`).
43. El módulo descarta resultados sin token válido, porque `determinar_resultado_entero` devuelve 0 (`:89-91`).
44. Una victoria da P/L igual a stake × (cuota − 1) (`:43-44`).
45. Una derrota da P/L igual a −stake, aunque no tenga cuota (`:45`).
46. Una victoria sin cuota válida no suma P/L ni volumen (`:92-94`).
47. El yield es P/L dividido por volumen, y el hit es ganadas dividido por N (`:57-58`).
48. El módulo calcula un t de Student sobre los yields por apuesta, con p-valor de dos colas (`:59-67`).
49. `obtener_bankroll_operativo` suma base, aportes y P/L liquidado desde la fecha de corte en modo dinámico (`src/persistencia/bankroll.py`).

### Yield potencial (`src/persistencia/yield_potencial.py`)

50. `apuestas_potenciales` toma filas con token GANADA o PERDIDA en 1X2 y en OU (`:19-31`).
51. El módulo no revisa el estado ni el stake de la fila (`:21-24`).
52. Cada apuesta vale 1 unidad: P/L es cuota − 1 si gana, o −1 si pierde (`:29-31`).
53. El módulo omite todo pick con cuota menor o igual a 1, incluidas las derrotas sin cuota (`:27-28`).
54. Yield es la suma de P/L dividida por N, y break-even es la media de 1/cuota (`:56`, `:58`).
55. El IC 95% sale de un bootstrap de 2000 remuestreos con semilla 42 (`:12-13`, `:35-40`).
56. `filas_yield` lee toda la tabla `partidos_backtest` sin filtro de estado (`dashboard.py:168-173`).

## Invariantes (lo que nunca debe pasar)

- Ningún partido sin goles pasa a 'Liquidado' (`motor_liquidador.py:72-73`).
- Ninguna apuesta con stake mayor a 0 pasa a 'Liquidado' sin token (`motor_liquidador.py:98-107`).
- Ningún CLV se escribe si falta la cuota tomada o la de cierre (`:27-30`).
- Ninguna victoria sin cuota entra en P/L ni en volumen (`metricas.py:92-94`).
- Ningún partido tiene dos confirmaciones para el mismo mercado (`confirmaciones.py:59-62`).
- Ninguna confirmación se acepta después del kickoff (`confirmaciones.py:53-54`).
- Ningún score no numérico llega a la base (`motor_backtest.py:109-113`).
- Ninguna métrica de dinero usa filas sin stake (`metricas.py:87`).

## Parámetros (clave de config_motor_valores, default en código, efecto)

Este bloque no lee claves de `config_motor_valores`. Sus constantes son fijas en el código.

| Constante | Valor | Efecto | Referencia |
|---|---|---|---|
| `_RESAMPLES` | 2000 | Remuestreos del bootstrap | `src/persistencia/yield_potencial.py:12` |
| `_SEED` | 42 | Semilla del bootstrap | `:13` |
| Timeout ESPN | 5 s | Tiempo máximo por consulta | `src/persistencia/motor_backtest.py:87` |
| Tolerancia de fecha | 1 día | Diferencia máxima entre fecha de partido y scoreboard | `:42` |
| `ESTADOS_ESPN_FINALIZADO` | STATUS_FINAL, STATUS_FULL_TIME | Estados que cuentan como terminados | `src/comun/constantes_espn.py:11` |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

Test de punta a punta: `tests/test_flujo_dinero_real.py:26` (`test_flujo_v2_pinnacle_como_verdad`). Confirmación en BetWarrior a 2.20 con stake 100. Cierre Pinnacle a 1.90. Resultado ESPN 1-0. Liquidación 'Liquidado' con `[GANADA] LOCAL`. CLV v2 positivo. Bankroll de 100120.

Tests por módulo:

| Módulo | Tests | Cubre |
|---|---|---|
| `tests/test_persistencia_backtest.py` | líneas 6, 10, 14, 18, 23, 27, 31, 39 | Regla de emparejamiento, score entero y pendientes pasados |
| `tests/test_persistencia_liquidador.py` | líneas 19, 27, 35, 42, 49 | Liquidación, stake sin token, OU sin token, stake 0 y token ya liquidado |
| `tests/test_confirmaciones.py` | líneas 18, 25, 34, 44, 51, 59, 65 | Guardado de cuota y stake, valores inválidos, post-kickoff, duplicado, pick v2 y casa |
| `tests/test_metricas.py` | líneas 15, 36 | Solo liquidadas, victoria sin cuota excluida, derrota sin cuota contada, p-valor t |
| `tests/test_yield_potencial.py` | líneas 12, 22, 31, 46, 58, 69, 81, 87 | Yield, break-even, picks sin cuota, mercados, por liga, IC y casos vacíos |
| `tests/test_persistencia_picks.py` | líneas 18, 25, 29, 37 | Cuota por token, token no reconocido, cuota faltante, pick válido |

Huecos sin test:

- `_calcular_clv_pct` no tiene test unitario para cuota de cierre nula o cero.
- No hay test de CLV con stake 0 que confirme que no se escribe.
- No hay test de `motor_backtest.main` con score no numérico. Solo prueba `_score_entero`.
- No hay test de error de red ni de respuesta distinta de 200 en `motor_backtest`.
- No hay test de un evento con `completed` falso y estado no finalizado.
- No hay test que compare `metricas` y `yield_potencial` con la misma derrota sin cuota.
- No hay test de `filas_yield` ni de su falta de filtro por estado.

## Limitaciones conocidas

- `yield_potencial` no filtra por estado ni por stake, y depende solo del token (`src/persistencia/yield_potencial.py:21-24`).
- `metricas` cuenta derrotas sin cuota, pero `yield_potencial` las omite (`src/persistencia/metricas.py:45`, `src/persistencia/yield_potencial.py:27-28`).
- Las dos métricas usan criterios distintos para el mismo caso, así que sus yields no son comparables.
- `confirmar_apuesta` sobrescribe cuota_1/x/2 y cuota_o25/u25 con la cuota tomada, y no guarda la cuota original (`src/persistencia/confirmaciones.py:66-67`).
- `confirmar_apuesta` acepta cualquier cuota mayor a 1 y cualquier stake positivo, sin tope ni comparación con la cuota del modelo (`:46-47`).
- El módulo `motor_backtest` dice "CON FAILOVER" en su encabezado, pero no tiene failover (`src/persistencia/motor_backtest.py:12`).
- `API_KEYS_ODDS` se importa y no se usa, y `KEY_INDEX` queda sin uso (`:5`, `:21`).
- Un partido sin evento ESPN queda pendiente y se consulta de nuevo en cada corrida (`:130`, `:132`).
- `motor_liquidador` deja 'Liquidado' los partidos sin apuestas, así que ese estado no prueba que hubo dinero.
- El COALESCE de CLV conserva un valor viejo si la nueva corrida no lo recalcula (`src/persistencia/motor_liquidador.py:117-118`).

## Anexo v2 (D-021): confirmación con pick elegido

- `confirmar_apuesta(..., pick=, casa=)` acepta un pick elegido por el usuario y lo escribe como `[APOSTAR] <pick>`.
- La casa (BetWarrior, Bet365 o casa local) queda en `apuestas_confirmadas.casa`.
- El CLV v2 es `cuota_tomada × prob_justa_cierre − 1`, con la probabilidad de cierre de Pinnacle sin margen.
- Tests: `tests/test_confirmaciones.py` y `tests/test_flujo_dinero_real.py::test_flujo_v2_pinnacle_como_verdad`.

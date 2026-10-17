# Modelo de probabilidades

## Propósito

Este documento describe cómo el motor calcula las probabilidades de cada partido. Cubre las EMA por equipo, las lambdas de xG, el modelo Poisson con corrección Dixon-Coles y las reglas de decisión. También cubre las arquitecturas shadow y el motor adaptativo. El código es la fuente de verdad. Los números de `Evidencia medida` vienen de un análisis separado.

El modelo produce tres salidas por partido. Son probabilidades 1X2, probabilidades O/U 2,5 y un pick con stake. Solo la arquitectura V0 decide. Las arquitecturas V6, V7, V12 y V13 se registran en modo shadow. La excepción es la capa V12 de la sección `Capa 2`, que solo actúa si una liga figura en la configuración.

El módulo de ingesta que alimenta el modelo se documenta en `01-ingesta.md`.

## Entradas

| Entrada | Tabla o clave | Uso | Referencia |
|---|---|---|---|
| EMA por equipo | `historial_equipos` | xG de local y visita | `src/nucleo/motor_calculadora.py:1789-1801` |
| Rho por liga | `ligas_stats.rho_calculado` | Corrección Dixon-Coles | `src/nucleo/motor_calculadora.py:1803-1804` |
| Cuotas | `partidos_backtest.cuota_1`, `cuota_x`, `cuota_2`, `cuota_o25`, `cuota_u25` | Valor esperado y coherencia | `src/nucleo/motor_calculadora.py:1840-1841` |
| Altitud | `equipos_altitud` | Cálculo shadow | `src/nucleo/motor_calculadora.py:1807-1808` |
| Banca y drawdown | `configuracion`, `partidos_backtest` | Tamaño de stake | `src/nucleo/motor_calculadora.py:536`, `src/nucleo/motor_calculadora.py:560` |
| Estadísticas de equipo | `historial_equipos_stats` | Filtro M.2 y M.3 | `src/nucleo/motor_calculadora.py:1029`, `src/nucleo/motor_calculadora.py:1062` |
| EMA V6 shadow | `historial_equipos_v6_shadow` | Arquitecturas V6, V7, V12 | `src/nucleo/motor_calculadora.py:1177` |
| Histórico externo | `partidos_historico_externo` | H2H para V12 | `motor_adaptativo.py:150-159` |
| Configuración | `config_motor_valores` | Todos los parámetros | `src/comun/config_motor.py:38-68` |
| Pesos V12 | `config_motor_valores` con clave `lr_v12_weights` | Capa 2 y motor adaptativo | `src/nucleo/motor_calculadora.py:1280-1285` |

## Salidas (tablas y columnas que escribe)

`main` escribe en `partidos_backtest` una fila por partido pendiente (`src/nucleo/motor_calculadora.py:2249-2268`).

| Tabla | Columnas | Condición | Referencia |
|---|---|---|---|
| `partidos_backtest` | `prob_1`, `prob_x`, `prob_2`, `prob_o25`, `prob_u25` | Siempre | `motor_calculadora.py:2251-2260` |
| `partidos_backtest` | `apuesta_1x2`, `apuesta_ou`, `stake_1x2`, `stake_ou` | Siempre. Stake en cero si el mercado no es live. | `motor_calculadora.py:2252-2262` |
| `partidos_backtest` | `apuesta_shadow_1x2`, `stake_shadow_1x2` | Grupo de control | `motor_calculadora.py:2253-2263` |
| `partidos_backtest` | `incertidumbre`, `xg_local`, `xg_visita` | `xg_*` es el xG con gamma de display | `motor_calculadora.py:2254-2255`, `motor_calculadora.py:2234` |
| `partidos_backtest` | `shadow_xg_local`, `shadow_xg_visita`, `xg_local_corto`, `xg_visita_corto` | Solo registro | `motor_calculadora.py:2256-2257` |
| `partidos_backtest` | `estado = 'Calculado'` | Siempre | `motor_calculadora.py:2257` |
| `partidos_backtest` | Columnas shadow añadidas con `ALTER TABLE` | Si no existen | `motor_calculadora.py:1766-1771` |
| `picks_shadow_arquitecturas` | Variantes V0 a V4, V6, V7, V12, V13 | Registro shadow | `motor_calculadora.py:1438-1492`, `motor_calculadora.py:1385-1394`, `motor_calculadora.py:978-1017` |
| `picks_shadow_layer3_log` | Decisión H4 X-rescue, con `aplicado = 0` | Registro shadow | `motor_calculadora.py:1406-1436` |
| `picks_shadow_margen_log` | Umbral de margen por liga | Registro shadow | `motor_calculadora.py:724-769` |
| `config_motor_valores` | `lr_v12_weights` (por liga y global) | Escrito por `motor_adaptativo` | `scripts/online_sgd_v12.py:201-207`, `motor_adaptativo.py:246-249` |
| `config_motor_valores` | `motor_adaptativo_last_run` | Marca de la corrida | `motor_adaptativo.py:62-67` |
| `motor_adaptativo_procesados` | `id_partido`, `ts` | Idempotencia del SGD | `motor_adaptativo.py:85-89`, `motor_adaptativo.py:296-297` |
| `online_sgd_log` | Un paso SGD o una reversión | Auditoría del SGD | `scripts/online_sgd_v12.py:60-72`, `motor_adaptativo.py:251-255` |
| `xg_pesos_dinamicos_shadow` | Coeficientes Kalman por liga, con `aplicado_produccion = 0` | Solo `scripts/xg_pesos_dinamicos_shadow.py` | `scripts/xg_pesos_dinamicos_shadow.py:26-31`, `scripts/xg_pesos_dinamicos_shadow.py:80-84` |

## Comportamiento (reglas exactas, en orden, con path:line)

### EMA por equipo

Las EMA se actualizan en `motor_data`. Este bloque resume la fórmula que consume el modelo. La carga y el orden de procesamiento están en `01-ingesta.md`.

1. Cada equipo tiene cuatro EMA de xG. Son favor y contra, en casa y fuera (`src/ingesta/motor_data.py:613-636`).
2. La EMA nueva es `xg * alfa + EMA_anterior * (1 - alfa)` (`src/ingesta/motor_data.py:613-614`).
3. El peso del prior de liga es `N0 / (N0 + N)`, con `N0 = 5` (`src/ingesta/motor_data.py:616`).
4. El valor que usa el modelo es `w_ema * EMA + w_liga * prior`, redondeado a 3 decimales (`src/ingesta/motor_data.py:618-619`).
5. La EMA corta usa `alfa_corto = min(2 * alfa, 0,50)` sin prior (`src/ingesta/motor_data.py:643-655`).
6. La EMA corta solo alimenta el registro shadow (`src/nucleo/motor_calculadora.py:1874-1882`).

### Lambdas de xG

1. El modelo lee las EMA de local y visita del partido (`src/nucleo/motor_calculadora.py:1864-1865`).
2. El xG local es `(fav_home del local + con_away de la visita) / 2` (`src/nucleo/motor_calculadora.py:1868`).
3. El xG visita es `(fav_away de la visita + con_home del local) / 2` (`src/nucleo/motor_calculadora.py:1869`).
4. El xG de display es el xG crudo por `gamma_1x2` (`src/nucleo/motor_calculadora.py:1889-1891`).
5. El xG de display se persiste y no entra al Poisson (`src/nucleo/motor_calculadora.py:2234`).
6. La incertidumbre es `sqrt((var_fh + var_ca + var_fa + var_ch) / 4)` (`src/nucleo/motor_calculadora.py:1895-1897`).
7. Por defecto, el 1X2 usa el xG crudo (`src/nucleo/motor_calculadora.py:1910`).
8. Si `escalar_lambda_1x2` es `TRUE`, el 1X2 multiplica ambos xG por `factor_corr_xg_ou` (`src/nucleo/motor_calculadora.py:1911-1914`).
9. El O/U usa siempre el xG crudo por `factor_corr_xg_ou` (`src/nucleo/motor_calculadora.py:1938-1941`).

### Poisson Dixon-Coles

1. El rho de la liga sale de `ligas_stats.rho_calculado` (`src/nucleo/motor_calculadora.py:1918`).
2. Si la liga no tiene rho, se usa `RHO_FALLBACK = -0,09` (`src/nucleo/motor_calculadora.py:520`, `src/nucleo/motor_calculadora.py:1918`).
3. La matriz recorre goles de 0 a 9 para cada equipo (`src/nucleo/motor_calculadora.py:521`, `src/nucleo/motor_calculadora.py:1920-1921`).
4. Cada celda es `Poisson(i, lambda_L) * Poisson(j, lambda_V) * tau(i, j)` (`src/nucleo/motor_calculadora.py:1922-1923`).
5. `tau` corrige solo los marcadores 0-0, 0-1, 1-0 y 1-1 (`src/nucleo/motor_calculadora.py:679-703`).
6. Local gana si `i > j`, empate si `i == j`, visita gana si `i < j` (`src/nucleo/motor_calculadora.py:1925-1927`).
7. El O/U suma las celdas con `i + j > 2,5` como Over (`src/nucleo/motor_calculadora.py:1928`, `src/nucleo/motor_calculadora.py:1947`).
8. El 1X2 se normaliza sobre la suma de sus tres resultados (`src/nucleo/motor_calculadora.py:1932-1933`).
9. El O/U se recalcula con su propio xG y sus propias celdas (`src/nucleo/motor_calculadora.py:1940-1950`).

### Ajustes de probabilidad (solo shadow)

1. Hallazgo G y Fix #5 se calculan sobre las probabilidades crudas (`src/nucleo/motor_calculadora.py:1961-1962`).
2. La decisión usa las probabilidades crudas, sin estos ajustes (`src/nucleo/motor_calculadora.py:1955-1960`, `src/nucleo/motor_calculadora.py:2139-2141`).
3. Las variantes con y sin ajustes se registran en `picks_shadow_arquitecturas` (`src/nucleo/motor_calculadora.py:1972-1991`).

### Capa 2: V12 por liga

1. La capa lee `arch_decision_per_liga` del alcance global. El default es `'{}'` (`src/nucleo/motor_calculadora.py:2011`).
2. Si la liga tiene `'V12'`, el modelo calcula probabilidades con regresión logística (`src/nucleo/motor_calculadora.py:2013-2019`).
3. Si los pesos V12 no existen, la función devuelve `1/3` para cada resultado.
4. Con esa salida uniforme, la capa conserva las probabilidades V0.

### Capa 3: H4 X-rescue (solo shadow)

1. La capa lee `h4_x_rescue_threshold`. El default es `'{}'` (`src/nucleo/motor_calculadora.py:2041-2043`).
2. La capa solo corre si la liga tiene umbral y no tiene Capa 2 (`src/nucleo/motor_calculadora.py:2046`).
3. Si `argmax` de V12 es `X` y su probabilidad supera el umbral, la capa evalúa tres filtros (`src/nucleo/motor_calculadora.py:2060-2069`).
4. Los filtros bloquean si el local está en el top 3 o si ambos equipos juegan con poco descanso (`src/nucleo/motor_calculadora.py:2066-2085`).
5. El resultado se registra en `picks_shadow_layer3_log` con `aplicado = False` (`src/nucleo/motor_calculadora.py:2106-2112`).
6. La capa no cambia `p1`, `px` ni `p2` (`src/nucleo/motor_calculadora.py:2095-2112`).

### Evaluación 1X2 (`evaluar_mercado_1x2`, `src/nucleo/motor_calculadora.py:1495`)

1. Si el filtro V5.1 está cargado, una liga no apostable devuelve PASAR (`src/nucleo/motor_calculadora.py:1513-1516`).
2. Si la EMA local tiene `n_acum` igual o mayor al máximo, devuelve PASAR (`src/nucleo/motor_calculadora.py:1520-1531`).
3. Si `excluir_q4` está activo y el bin temporal es 3, devuelve PASAR (`src/nucleo/motor_calculadora.py:1533-1535`).
4. El modelo aplica la calibración de P(LOCAL) si su flag está activo (`src/nucleo/motor_calculadora.py:1540`).
5. La divergencia máxima sale de `divergencia_max_1x2` por liga (`src/nucleo/motor_calculadora.py:1543-1545`).
6. Sin cuotas válidas, devuelve PASAR (`src/nucleo/motor_calculadora.py:1552-1553`).
7. `margen_real` es la diferencia entre la mayor y la segunda probabilidad (`src/nucleo/motor_calculadora.py:1555-1556`).
8. Si `margen_real` es menor al margen predictivo, devuelve PASAR (`src/nucleo/motor_calculadora.py:1566-1567`).
9. El empate entra solo si `APUESTA_EMPATE_PERMITIDA` es verdadero (`src/nucleo/motor_calculadora.py:1571-1572`).
10. El camino 1 evalúa el favorito del modelo (`src/nucleo/motor_calculadora.py:1575-1576`).
11. Si `1/cuota < 0,5 * p` del favorito, devuelve PASAR por cuotas incoherentes (`src/nucleo/motor_calculadora.py:1583-1584`).
12. El camino 1 apuesta si cuota ≤ 5,0, EV ≥ umbral y divergencia ≤ `div_max` (`src/nucleo/motor_calculadora.py:1589-1590`).
13. El umbral de EV es `0,03 * (0,5 / p)` (`src/nucleo/motor_calculadora.py:70`, `src/nucleo/motor_calculadora.py:1586`).
14. El camino 2B apuesta el favorito del modelo si el mercado favorece otro resultado (`src/nucleo/motor_calculadora.py:1599-1604`).
15. El camino 2B exige probabilidad ≥ 0,40, divergencia entre `div_max` y 0,30, EV mínimo escalado y cuota ≤ 8,0 (`src/nucleo/motor_calculadora.py:1600-1603`).
16. El camino 3 apuesta si probabilidad ≥ 0,33, EV ≥ 1,0 y cuota ≤ 8,0 (`src/nucleo/motor_calculadora.py:1610-1613`).
17. El camino 4 apuesta si modelo y mercado coinciden en el favorito (`src/nucleo/motor_calculadora.py:1621-1626`).
18. El camino 4 exige probabilidad ≥ 0,36, cuota entre 1,12 y 2,00, y divergencia ≤ `div_max` (`src/nucleo/motor_calculadora.py:1623-1626`).
19. El camino 2 busca el resultado con mayor EV y se evalúa al final (`src/nucleo/motor_calculadora.py:1639-1641`).
20. El camino 2 devuelve PASAR si el pick es VISITA, la probabilidad está entre 0,33 y 0,40, y la liga está en Brasil, Inglaterra, Noruega o Turquía (`src/nucleo/motor_calculadora.py:1638-1649`).
21. El camino 2 apuesta si cuota ≤ 5,0, EV ≥ umbral y divergencia ≤ `div_max` (`src/nucleo/motor_calculadora.py:1651-1652`).
22. Si ningún camino aplica, devuelve PASAR con diagnóstico (`src/nucleo/motor_calculadora.py:1654-1657`).
23. `min_ev_escalado` exige EV 0,03 con probabilidad de 0,50 o más (`src/nucleo/motor_calculadora.py:359-364`).
24. `min_ev_escalado` exige EV 0,08 con probabilidad entre 0,40 y 0,50 (`src/nucleo/motor_calculadora.py:362`).
25. `min_ev_escalado` exige EV 0,12 con probabilidad entre 0,33 y 0,40 (`src/nucleo/motor_calculadora.py:363`).

### Evaluación O/U (`evaluar_mercado_ou`, `src/nucleo/motor_calculadora.py:1660`)

1. Sin cuotas de Over y Under válidas, devuelve PASAR (`src/nucleo/motor_calculadora.py:1667-1668`).
2. El total esperado es la suma de los xG del O/U (`src/nucleo/motor_calculadora.py:1673-1674`).
3. El margen de xG es 0,30 si el total es 2,5 o más, y 0,25 si no (`src/nucleo/motor_calculadora.py:1675`, `src/nucleo/motor_calculadora.py:337-338`).
4. Si `|total - 2,5|` es menor al margen, devuelve PASAR (`src/nucleo/motor_calculadora.py:1676-1677`).
5. Si `|po - pu|` es menor a 0,05, devuelve PASAR (`src/nucleo/motor_calculadora.py:1679-1680`).
6. El pick es el lado con mayor probabilidad (`src/nucleo/motor_calculadora.py:1685-1686`).
7. Si la cuota del pick es 1,0 o menos, devuelve PASAR (`src/nucleo/motor_calculadora.py:1688-1689`).
8. El umbral de EV es `0,03 * (0,5 / p)` (`src/nucleo/motor_calculadora.py:1692`).
9. Apuesta si EV supera el umbral y la cuota es 6,0 o menos (`src/nucleo/motor_calculadora.py:1694-1695`).

### Filtros de la decisión y stakes (`main`)

1. Con menos de 5 partidos en la EMA de local o visita, la decisión pasa a PASAR (`src/nucleo/motor_calculadora.py:2188-2193`).
2. Un pick 1X2 con probabilidad bajo 0,33 pasa a PASAR por piso (`src/nucleo/motor_calculadora.py:2153-2154`).
3. Un pick 1X2 con EV menor al mínimo escalado pasa a PASAR (`src/nucleo/motor_calculadora.py:2155-2156`).
4. El stake 1X2 es cero si `apuestas_live` no está activo para la liga (`src/nucleo/motor_calculadora.py:2199-2201`).
5. El stake O/U es cero si `apuesta_ou_live` no está activo para la liga (`src/nucleo/motor_calculadora.py:2204-2212`).
6. Si hay stake 1X2 y stake O/U, el O/U se anula (`src/nucleo/motor_calculadora.py:2223-2225`).
7. El stake es Kelly fraccional: `bankroll * min(kelly * 0,50, max_kelly_pct)` (`src/nucleo/motor_calculadora.py:1721-1735`).
8. `max_kelly_pct` es 0,025 en régimen normal y 0,010 con drawdown (`src/nucleo/motor_calculadora.py:64-65`, `src/nucleo/motor_calculadora.py:1774-1776`).
9. Los stakes vivos pasan por ajuste de covarianza (`src/nucleo/motor_calculadora.py:2241-2244`, `src/nucleo/motor_calculadora.py:1738`).
10. El pick shadow usa las probabilidades crudas con los mismos filtros (`src/nucleo/motor_calculadora.py:2165-2182`).
11. El stake shadow es cero si `apuestas_live` no está activo (`src/nucleo/motor_calculadora.py:2213-2214`).

### Motor shadow V6, V7, V12 y V13

1. V6 recalcula el xG con coeficientes OLS guardados en `config_motor_valores` (`src/nucleo/motor_calculadora.py:1177-1205`).
2. V6 usa Poisson con corrección Dixon-Coles (`src/nucleo/motor_calculadora.py:1207-1230`).
3. V7 usa Skellam sin corrección Dixon-Coles (`src/nucleo/motor_calculadora.py:772-795`).
4. V12 usa regresión logística multinomial con 13 variables (`src/nucleo/motor_calculadora.py:1265-1342`).
5. V13 usa un xG ridge por liga para las ligas con coeficientes guardados (`src/nucleo/motor_calculadora.py:797-961`).
6. Los registros V6, V7, V12 y V13 se actualizan en `picks_shadow_arquitecturas` (`src/nucleo/motor_calculadora.py:1385-1394`, `src/nucleo/motor_calculadora.py:978-1017`).
7. Todo error en el registro shadow se ignora sin detener el motor (`src/nucleo/motor_calculadora.py:2001-2002`).

### xG dinámico Kalman (solo shadow)

1. El modelo supone goles ~ Poisson(x · theta), con x = (tiros al arco, tiros fuera, corners) (`src/nucleo/xg_pesos_dinamicos.py:4-6`).
2. El prior de theta es el coeficiente estático vigente (`src/nucleo/xg_pesos_dinamicos.py:8-10`).
3. El olvido exponencial usa `lambda = 0,995` (`src/nucleo/xg_pesos_dinamicos.py:20`).
4. La varianza de observación es `r = 1,3` (`src/nucleo/xg_pesos_dinamicos.py:21`).
5. Cada observación se predice antes de actualizar theta (`src/nucleo/xg_pesos_dinamicos.py:14`, `src/nucleo/xg_pesos_dinamicos.py:49-53`).
6. El script recorre los partidos liquidados por liga y escribe coeficientes en `xg_pesos_dinamicos_shadow` (`scripts/xg_pesos_dinamicos_shadow.py:59-84`).
7. El módulo no se importa desde `motor_calculadora.py` (búsqueda por nombre sin resultados).

### Motor adaptativo (`motor_adaptativo.py`)

1. El motor toma partidos liquidados con stats y goles, que no estén en `motor_adaptativo_procesados` (`motor_adaptativo.py:72-76`, `motor_adaptativo.py:269-276`).
2. Cada partido sin features se omite y queda pendiente (`motor_adaptativo.py:287-290`).
3. Las features V12 usan EMA V6 shadow, varianza legacy y H2H (`motor_adaptativo.py:118-180`).
4. Si falta la EMA V6, el partido se omite (`motor_adaptativo.py:133-134`).
5. Cada partido aplica un paso SGD al pesos de su liga y al pesos global (`motor_adaptativo.py:294-295`).
6. El paso y la marca de procesado se confirman en la misma transacción (`motor_adaptativo.py:296-298`).
7. El SGD usa tasa 0,005, ridge 0,1 y anclaje 0,05 (`scripts/online_sgd_v12.py:37-39`).
8. El SGD arranca tras 100 partidos de calentamiento (`scripts/online_sgd_v12.py:40`).
9. La auditoría revierte `W` al anclaje si la norma supera 50 (`motor_adaptativo.py:40`, `motor_adaptativo.py:196-197`).
10. La auditoría revierte si la norma del gradiente promedio supera 5 (`motor_adaptativo.py:41`, `motor_adaptativo.py:198-199`).
11. La auditoría revierte si el Brier promedio supera 0,587 en 10 por ciento (`motor_adaptativo.py:42`, `motor_adaptativo.py:211-213`).
12. Una reversión tiene un enfriamiento de 7 días (`motor_adaptativo.py:43`, `motor_adaptativo.py:219-227`).
13. Al final, el motor corre el detector de drift con ventana de 30 días (`motor_adaptativo.py:340-349`).
14. El motor guarda la marca `motor_adaptativo_last_run` (`motor_adaptativo.py:352-353`).

## Invariantes (lo que nunca debe pasar)

- Ninguna decisión usa datos de una tabla shadow (`src/nucleo/motor_calculadora.py:1955-1960`, `src/nucleo/motor_calculadora.py:2112`).
- Ningún partido empezado o alertado se recalcula (`src/nucleo/motor_calculadora.py:1837-1847`).
- Ningún partido liquidado se recalcula (`src/nucleo/motor_calculadora.py:1843-1845`).
- Ningún pick se decide con menos de 5 partidos en la EMA (`src/nucleo/motor_calculadora.py:2188-2193`).
- Ningún pick 1X2 sale sin cuotas válidas (`src/nucleo/motor_calculadora.py:1552-1553`).
- Ningún pick O/U sale con cuota de 1,0 o menos (`src/nucleo/motor_calculadora.py:1688-1689`).
- Ningún stake se asigna sin `apuestas_live` activo para la liga (`src/nucleo/motor_calculadora.py:2199-2201`).
- Ningún partido recibe 1X2 y O/U con stake al mismo tiempo (`src/nucleo/motor_calculadora.py:2223-2225`).
- Ningún pick sale de una liga no apostable del filtro V5.1 (`src/nucleo/motor_calculadora.py:1515-1516`).
- Ningún paso SGD se aplica dos veces al mismo partido (`motor_adaptativo.py:72-76`, `motor_adaptativo.py:296`).
- Ningún stake supera `max_kelly_pct` (`src/nucleo/motor_calculadora.py:1733`).
- Ninguna reversión del SGD se aplica dentro de 7 días de la anterior (`motor_adaptativo.py:219-227`).

## Parámetros (clave de config_motor_valores, default en código, efecto)

| Clave | Scope | Default en código | Efecto | Referencia |
|---|---|---|---|---|
| `alfa_ema` | liga o global | Diccionario por liga, fallback 0,15 | Peso del partido nuevo en la EMA. | `src/ingesta/motor_data.py:75-112`, `src/ingesta/motor_data.py:591` |
| `n0_ancla` | global | 5 | Peso del prior de liga en la EMA. | `src/ingesta/motor_data.py:46` |
| `ema_prior_por_equipo` | global | `'FALSE'` | Escala del prior de liga. | `src/ingesta/motor_data.py:62` |
| `escalar_lambda_1x2` | liga | `'FALSE'` | Si `TRUE`, el 1X2 usa xG por `factor_corr_xg_ou`. | `src/nucleo/motor_calculadora.py:1911` |
| `factor_corr_xg_ou` | liga | Diccionario por liga, fallback 0,627 | Factor de corrección del xG. | `src/nucleo/motor_calculadora.py:84-112`, `src/nucleo/motor_calculadora.py:1912-1913`, `src/nucleo/motor_calculadora.py:1938-1939` |
| `gamma_1x2` | liga | 0,59 | Compresión del xG de display. | `src/nucleo/motor_calculadora.py:1889` |
| `rho_fallback` | global | -0,09 | Rho de liga sin valor. | `src/nucleo/motor_calculadora.py:520` |
| `umbral_ev_base` | global | 0,03 | Umbral base de EV. | `src/nucleo/motor_calculadora.py:70` |
| `techo_cuota_1x2` | global | 5,0 | Cuota máxima en los caminos 1 y 2. | `src/nucleo/motor_calculadora.py:71` |
| `techo_cuota_ou` | global | 6,0 | Cuota máxima en O/U. | `src/nucleo/motor_calculadora.py:72` |
| `techo_cuota_alta_conv` | global | 8,0 | Cuota máxima en caminos 2B y 3. | `src/nucleo/motor_calculadora.py:167` |
| `conviccion_ev_min` | global | 1,0 | EV mínimo del camino 3. | `src/nucleo/motor_calculadora.py:166` |
| `divergencia_max_1x2` | liga | 0,15 y diccionario por liga | Divergencia máxima entre modelo y mercado. | `src/nucleo/motor_calculadora.py:73`, `src/nucleo/motor_calculadora.py:121`, `src/nucleo/motor_calculadora.py:1544` |
| `margen_predictivo_1x2` | liga | 0,03 | Margen mínimo entre el primer y segundo resultado. | `src/nucleo/motor_calculadora.py:153`, `src/nucleo/motor_calculadora.py:1547` |
| `margen_predictivo_ou` | global | 0,05 | Margen mínimo entre Over y Under. | `src/nucleo/motor_calculadora.py:154`, `src/nucleo/motor_calculadora.py:1679` |
| `margen_xg_ou_over` | global | 0,30 | Margen de xG para Over. | `src/nucleo/motor_calculadora.py:337` |
| `margen_xg_ou_under` | global | 0,25 | Margen de xG para Under. | `src/nucleo/motor_calculadora.py:338` |
| `floor_prob_min` | global | 0,33 | Probabilidad mínima para apostar. | `src/nucleo/motor_calculadora.py:159` |
| `ratio_min_implicita` | global | 0,5 | Filtro de cuotas incoherentes. | `src/nucleo/motor_calculadora.py:199` |
| `n_min_partidos_equipo` | global | 5 | Partidos mínimos en la EMA. | `src/nucleo/motor_calculadora.py:200` |
| `desacuerdo_prob_min` | global | 0,40 | Probabilidad mínima del camino 2B. | `src/nucleo/motor_calculadora.py:177` |
| `divergencia_desacuerdo_max` | global | 0,30 | Divergencia máxima del camino 2B. | `src/nucleo/motor_calculadora.py:178` |
| `consenso_prob_min` | global | 0,36 | Probabilidad mínima del camino 4. | `src/nucleo/motor_calculadora.py:190` |
| `consenso_cuota_min` | global | 1,12 | Cuota mínima del camino 4. | `src/nucleo/motor_calculadora.py:191` |
| `consenso_cuota_max` | global | 2,00 | Cuota máxima del camino 4. | `src/nucleo/motor_calculadora.py:192` |
| `apuesta_empate_permitida` | global | `False` | Permite apostar empate. | `src/nucleo/motor_calculadora.py:198` |
| `fraccion_kelly` | global | 0,50 | Fracción del Kelly completo. | `src/nucleo/motor_calculadora.py:67` |
| `max_kelly_pct_normal` | global | 0,025 | Tope de stake en régimen normal. | `src/nucleo/motor_calculadora.py:64` |
| `max_kelly_pct_drawdown` | global | 0,010 | Tope de stake con drawdown. | `src/nucleo/motor_calculadora.py:65` |
| `drawdown_threshold` | global | 5 | Pérdidas seguidas que activan el drawdown. | `src/nucleo/motor_calculadora.py:66` |
| `apuestas_live` | liga | `'FALSE'` | Si `FALSE`, el stake 1X2 es cero. | `src/nucleo/motor_calculadora.py:2199` |
| `apuesta_ou_live` | liga | `APUESTA_OU_ACTIVA` (True) | Si `FALSE`, el stake O/U es cero. | `src/nucleo/motor_calculadora.py:324`, `src/nucleo/motor_calculadora.py:2204` |
| `m2_per_liga_activo` | global | `'FALSE'` | Umbral de madurez por liga en el filtro M.2. | `src/nucleo/motor_calculadora.py:245` |
| `filtro_picks_v51` | global | Sin default (JSON) | Ligas apostables y reglas M.1, M.2 y M.3. | `src/nucleo/motor_calculadora.py:211-240` |
| `prob_local_calibration_activa` | global | Ver código | Activa la calibración de P(LOCAL). | `src/nucleo/motor_calculadora.py:261-266` |
| `calibracion_activa` | global | `True` | Activa el ajuste de compresión de Fix #5. | `src/nucleo/motor_calculadora.py:372` |
| `calibracion_delta` | global | 0,042 | Tamaño del ajuste de Fix #5. | `src/nucleo/motor_calculadora.py:375` |
| `hallazgo_g_activo` | global | `True` | Activa Hallazgo G, solo en shadow. | `src/nucleo/motor_calculadora.py:402` |
| `n_min_hallazgo_g` | global | 50 | Partidos mínimos para Hallazgo G. | `src/nucleo/motor_calculadora.py:400` |
| `arch_decision_per_liga` | global | `'{}'` | Liga con Capa 2 V12. | `src/nucleo/motor_calculadora.py:2011` |
| `h4_x_rescue_threshold` | global | `'{}'` | Umbral de la Capa 3 H4. Solo shadow. | `src/nucleo/motor_calculadora.py:2041` |
| `incertidumbre_umbral_shadow` | global | 1,40 | Umbral de registro de incertidumbre alta. | `src/nucleo/motor_calculadora.py:329` |
| `motor_adaptativo_last_run` | global | `'1970-01-01 00:00:00'` | Marca de la última corrida. | `motor_adaptativo.py:54-59` |

## Tests de aceptación

Tests existentes que cubren este componente:

| Archivo | Tests | Cubre |
|---|---|---|
| `tests/test_nucleo_calculadora.py` | `test_poisson_dc_suma_uno`, `test_kelly_medio_y_cap`, `test_flag_escalar_lambda_1x2_no_doble_escala_ou`, `test_cuotas_invertidas_no_generan_pick`, `test_cuotas_coherentes_siguen_evaluandose`, `test_hallazgo_g_infla_locales_no_favoritos`, `test_main_no_aplica_hallazgo_g_ni_fix5`, `test_main_solo_calcula_futuros_sin_alerta`, `test_m2_no_bloquea_sin_opt_in`, `test_m2_bloquea_con_opt_in`, `test_n_acum_resuelve_display_name_espn`, `test_drawdown_detecta_racha_de_perdidas_liquidadas`, `test_drawdown_corta_con_ganada_reciente`, `test_drawdown_cuenta_mercado_ou_e_ignora_stake_cero`, `test_drawdown_cuenta_un_resultado_por_partido`, `test_bankroll_bajo_piso_usa_capital_real` | Tau y Poisson, Kelly, escalado de lambdas, cuotas incoherentes, filtros M.2 y drawdown, y reglas de `main`. |
| `tests/test_prior_ema.py` | `test_prior_por_equipo_escala_correcta`, `test_prior_liga_por_equipo_respeta_flag`, `test_aplicar_migra_escala_flag_y_factores` | Escala del prior y factores por liga. |
| `tests/test_xg_pesos_dinamicos.py` | `test_dinamico_supera_al_estatico_cuando_los_pesos_reales_difieren_y_cambian`, `test_sin_senal_se_queda_cerca_del_prior`, `test_kalman_update_no_muta_argumentos`, `test_script_shadow_registra_por_liga` | Kalman y script shadow. |
| `tests/test_ops_motor_adaptativo.py` | `test_no_reaplica_y_procesa_tardios`, `test_crash_no_reaplica_pasos_commiteados`, `test_migracion_marca_partidos_previos_al_watermark`, `test_migracion_interrumpida_siembra_igual`, `test_features_con_null_devuelven_none`, `test_cli_sgd_dry_run_no_escribe` | Idempotencia y features del motor adaptativo. |
| `tests/test_pretest.py` | `test_hit_55_con_cuota_baja_no_flipea`, `test_yield_positivo_significativo_flipea`, `test_evaluar_sin_aprobacion_no_pasa_a_live`, `test_evaluar_revierte_a_pretest_sin_aprobacion` | Paso de liga a live. |
| `tests/test_drift.py` | `test_umbral_usa_error_estandar_de_la_media`, `test_detect_drift_db_nueva_no_falla` | Umbral del detector de drift. |
| `tests/test_flujo_dinero_real.py` | `test_flujo_completo_de_una_apuesta_real` | Flujo completo de una apuesta. |

Huecos sin test (no encontré test directo para estos puntos):

- Las fórmulas de lambda de `main` (`src/nucleo/motor_calculadora.py:1868-1869`).
- Los caminos 2B, 3, 4 y 2 de `evaluar_mercado_1x2` (`src/nucleo/motor_calculadora.py:1599-1652`).
- `evaluar_mercado_ou` (`src/nucleo/motor_calculadora.py:1660-1697`).
- La Capa 2 conserva V0 cuando faltan pesos V12 (`tests/test_nucleo_calculadora.py::test_layer2_sin_pesos_v12_mantiene_v0`).
- La Capa 3 H4 (`src/nucleo/motor_calculadora.py:2039-2114`).
- Los registros de V6, V7, V12 y V13 (`src/nucleo/motor_calculadora.py:1992-2002`).
- La auditoría del motor adaptativo, `auto_audit` (`motor_adaptativo.py:183-260`).
- La actualización de EMA, porque `actualizar_estado` vive dentro de `main` (`src/ingesta/motor_data.py:588`).

## Limitaciones conocidas

- La Capa 2 no cae a V0 cuando faltan pesos V12.
- Sin pesos V12, la Capa 2 conserva V0.
- El comentario de `src/nucleo/motor_calculadora.py:2008` dice lo contrario.
- El motor adaptativo escribe `lr_v12_weights` que la Capa 2 lee (`scripts/online_sgd_v12.py:201-207`, `src/nucleo/motor_calculadora.py:1280-1285`).
- Esa escritura contradice el docstring que dice que el motor adaptativo no afecta la producción (`motor_adaptativo.py:16`).
- En la base leída no existe la fila `arch_decision_per_liga`. La Capa 2 está inactiva.
- En la base leída no existen filas `lr_v12_weights`. El SGD no tiene anclaje (`scripts/online_sgd_v12.py:21-22`).
- El `CLAUDE.md` del proyecto dice que V12 está activo en Turquía. La base leída no confirma esa fila.
- `calc_xg_v6` de `motor_adaptativo.py` no tiene llamadores fuera de `analisis/`.
- `OLS_GLOBAL` de `motor_adaptativo.py:37` no coincide con los coeficientes de la configuración.
- La varianza por defecto del motor adaptativo es 0,5 (`motor_adaptativo.py:145-148`). La de `motor_data` es 0,1 (`src/ingesta/motor_data.py:516`).
- El Brier de referencia 0,587 está fijo en código (`motor_adaptativo.py:211`).
- El 1X2 usa xG crudo salvo que el flag esté activo (`src/nucleo/motor_calculadora.py:1908-1914`).
- El O/U usa siempre xG crudo por `factor_corr_xg_ou` (`src/nucleo/motor_calculadora.py:1938-1941`).
- Por eso las dos lambdas difieren por defecto.
- En la base leída, ninguna fila `apuestas_live` vale `TRUE`. Los stakes salen en cero.
- `get_param` abre una conexión por cada llamada (`src/comun/config_motor.py:51`).
- Cada partido llama a `get_param` varias veces.
- `scripts/xg_pesos_dinamicos_shadow.py:41` ordena por `fecha` como texto. Un formato `DD/MM/YYYY` rompería el orden. La base leída no tiene filas en ese formato.
- `RHO` por liga viene de `ligas_stats`, que tiene dos escritores (ver `01-ingesta.md`).
- Los parámetros de `scripts/evaluar_prior_ema.py` ajustan el factor de O/U y `gamma_1x2` juntos con el prior.

## Evidencia medida

La validación usa `analisis/validacion_fdco_walkforward.py` y su salida `analisis/validacion_fdco_walkforward.json`. Lee CSV de football-data.co.uk para cuatro ligas: Inglaterra (E0), España (SP1), Italia (I1) y Alemania (D1). El código no declara la temporada. Esa temporada depende del CSV de entrada. Evalúa 1445 partidos por motor. El mercado de comparación es el cierre de Pinnacle (columnas `PSCH`, `PSCD`, `PSCA`), no la apertura.

| Métrica | Motor nuevo | Mercado (cierre Pinnacle) | Fuente |
|---|---|---|---|
| Brier 1X2 | 0,6366 (0,637) | 0,5716 (0,572) | `analisis/validacion_fdco_walkforward.json`, `nuevo.brier_modelo` y `nuevo.brier_mercado_cierre` |
| Log-loss 1X2 | 1,0558 (1,056) | 0,9612 (0,961) | `nuevo.logloss_modelo` y `nuevo.logloss_mercado_cierre` |
| Yield plano | -15,8 por ciento (175 picks) | No aplica | `nuevo.yield_plano` |
| IC del yield (clave `yield_ic95`) | [-0,364; +0,040] | No aplica | `nuevo.yield_ic95` |
| CLV medio | -0,0092 | No aplica | `nuevo.clv_medio` |

Puntos de contraste dentro de la misma validación:

- El motor anterior (`viejo`) tiene Brier 0,6489 y yield -17,0 por ciento.
- El motor con pesos dinámicos (`nuevo_dinamico`) tiene Brier 0,6393, peor que el nuevo (0,6366).
- El IC del yield incluye cero. El resultado no prueba una pérdida significativa.

La mezcla p ∝ q_apertura^(1−w) · p_modelo^w está en `mezcla_con_pinnacle()` del mismo script. El JSON la guarda en `mezcla_modelo_pinnacle`. El peso óptimo es w = 0 (N = 1341). En la 2da mitad, la log-loss del mercado es 0.965 y la del modelo solo es 1.054.

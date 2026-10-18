# Capa de decisión: motor_calculadora y evaluar_pretest

> Estado: motor v1, fuera de la cascada diaria desde D-022. El código sigue en disco hasta la fase 2 de `adepor-i1n`.

## Propósito

Esta capa elige el pick y el stake de cada partido futuro. Trabaja con dos mercados: 1X2 y Over/Under 2.5. El motor escribe el pick en `partidos_backtest`. El script `scripts/evaluar_pretest.py` decide cuándo un mercado pasa a live.

El motor no recibe argumentos. Lee la base en cada corrida. Las cifras de estado citadas salen de `fondo_quant.db`, leído el 2026-10-17.

## Entradas

| Fuente | Campos | Uso |
|---|---|---|
| `partidos_backtest` | id_partido, local, visita, pais, fecha, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, estado, goles_l, goles_v | Partidos a calcular y cuotas de entrada |
| `historial_equipos` | equipo_norm, liga, ema_xg_*, ema_var_*, ema_corto_*, partidos_home, partidos_away | xG EMA, varianza y conteo de partidos |
| `ligas_stats` | liga, rho_calculado | rho de Dixon-Coles por liga |
| `equipos_altitud` | equipo_norm, altitud | Solo log shadow |
| `historial_equipos_stats`, `liga_calendario_temp` | n_acum, momento_bin_4 | Filtros M.2 y M.3 (`src/nucleo/motor_calculadora.py:1029`, `:1062`) |
| `configuracion` | bankroll, bankroll_modo, bankroll_fecha_corte, bankroll_piso, bankroll_techo | Bankroll para Kelly |
| `aportes_capital` | fecha, monto | Aportes del bankroll dinámico |
| `apuestas_confirmadas` | id_partido | Congela partidos confirmados (`src/persistencia/confirmaciones.py:24`) |
| `config_motor_valores` | clave, scope, valor_real, valor_texto, tipo | Parámetros vía `get_param` (`src/comun/config_motor.py:38`) |

La hora de corte viene de `ahora_art()` en `src/comun/tiempo.py`. Scripts de pretest leen `partidos_backtest` con tokens `[GANADA]` y `[PERDIDA]`.

## Salidas (tablas y columnas que escribe)

| Tabla | Columnas | Condición |
|---|---|---|
| `partidos_backtest` | prob_1, prob_x, prob_2, prob_o25, prob_u25 | Siempre, por partido calculado (`src/nucleo/motor_calculadora.py:2249-2260`) |
| `partidos_backtest` | apuesta_1x2, apuesta_ou | Siempre. Valor `[APOSTAR] ...` o `[PASAR] ...` |
| `partidos_backtest` | stake_1x2, stake_ou | Kelly solo si el mercado está live. Si no, 0 (`:2201`, `:2212`) |
| `partidos_backtest` | apuesta_shadow_1x2, stake_shadow_1x2 | Stake shadow solo si 1X2 está live (`:2213-2214`) |
| `partidos_backtest` | incertidumbre, xg_local, xg_visita, shadow_xg_local, shadow_xg_visita, xg_local_corto, xg_visita_corto | xG mostrado con gamma (`:2234`) y valores shadow |
| `partidos_backtest` | estado | Pasa a `Calculado` (`:2257`) |
| Tablas `*_shadow*` y de log | filas de log | Escritas por `_log_shadow_margen` (`:724`), `_log_shadow_v13` (`:963`), `_log_shadow_v6_v7` (`:1343`), `_log_layer3` (`:1406`) y `_log_shadow_arquitecturas` (`:1438`) |
| `config_motor_valores` | valor_texto, fuente, fecha_actualizacion | Solo `scripts/evaluar_pretest.py` (`:122-134`, `:191-193`) |

El motor agrega columnas shadow con `ALTER TABLE` al arrancar (`src/nucleo/motor_calculadora.py:1767-1771`).

## Comportamiento (reglas exactas, en orden, con path:line)

### Selección de partidos

1. El motor calcula solo partidos con estado Pendiente o Calculado, sin goles y con fecha posterior a ahora (`src/nucleo/motor_calculadora.py:1839-1845`).
2. El motor excluye partidos con apuesta confirmada según `ids_confirmados` (`:1838`, `:1847`).
3. El motor termina sin cambios si no quedan partidos (`:1849-1852`).
4. El motor lee el bankroll una vez por corrida (`:1781`).
5. El motor baja el tope Kelly a `MAX_KELLY_PCT_DRAWDOWN` si detecta drawdown (`:1773-1779`).

### Probabilidades

6. El motor calcula xG local como promedio de `fav_home` local y `con_away` visita (`:1868`).
7. El motor calcula xG visita como promedio de `fav_away` visita y `con_home` local (`:1869`).
8. El motor calcula la matriz Dixon-Coles de 10 por 10 con el rho de la liga (`:1918-1933`).
9. Si `escalar_lambda_1x2` es TRUE, el 1X2 usa xG multiplicado por `factor_corr_xg_ou` (`:1911-1914`).
10. El motor calcula O/U con xG multiplicado por `factor_corr_xg_ou` de la liga (`:1938-1950`).
11. El motor reemplaza p1, px y p2 por V12 solo si `arch_decision_per_liga` asigna V12 a la liga (`:2009-2023`).
12. El motor no aplica Hallazgo G ni Fix #5 a la decisión, solo los loggea (`:1955-1962`, `:1986`).
13. El motor solo loggea H4 X-rescue con `aplicado=False`, sin cambiar probabilidades (`:2030-2114`).
14. Gamma 0.59 solo afecta el xG persistido, no las probabilidades (`:1889-1891`, `:2234`).

### Decisión 1X2 (`evaluar_mercado_1x2`, `src/nucleo/motor_calculadora.py:1495`)

15. Si el filtro V5.1 existe, el motor bloquea ligas fuera de `ligas` (`:1514-1516`).
16. Si `m2_activo` es TRUE y n_acum local iguala o supera el umbral, el motor pasa el partido (`:1520-1531`).
17. Si `excluir_q4` es TRUE y `momento_bin_4` es 3, el motor pasa el partido (`:1533-1535`).
18. El motor aplica la calibración P(LOCAL) si `prob_local_calibration_activa` es TRUE (`:1540`, `:279-317`).
19. El motor toma `div_max` y `margen_predictivo_1x2` por liga, con fallback global (`:1543-1550`).
20. El motor pasa el partido si alguna cuota no es número positivo (`:1552-1553`).
21. El motor pasa el partido si la distancia entre la primera y la segunda probabilidad es menor que `margen_predictivo_1x2` (`:1556-1567`).
22. El motor pasa todo el 1X2 si 1/c es menor que `ratio_min_implicita` multiplicado por p del favorito (`:1583-1584`).
23. Camino 1 aprueba el favorito si cuota no supera `techo_cuota_1x2`, EV supera el umbral y divergencia no supera `div_max` (`:1585-1590`).
24. Camino 2B aprueba el favorito distinto al del mercado si p es al menos 0.40 y la divergencia está entre `div_max` y 0.30 (`:1598-1604`).
25. Camino 2B exige además EV mínimo escalado y cuota no mayor a 8 (`:1603`).
26. Camino 3 aprueba el favorito si p es al menos FLOOR, EV es al menos 1.0 y cuota no supera 8 (`:1610-1613`).
27. Camino 4 aprueba el favorito si coincide con el del mercado, p es al menos 0.36 y cuota está entre 1.12 y 2.00 (`:1621-1626`).
28. Camino 4 exige además que la divergencia no supere `div_max` (`:1625`).
29. Camino 2 busca el outcome de mayor EV con cuota no mayor a 5 y EV sobre el umbral (`:1639-1652`).
30. Camino 2 rechaza VISITA con p entre 0.33 y 0.40 en Brasil, Inglaterra, Noruega o Turquía (`:1645-1649`).
31. Si ningún camino aplica, el motor devuelve un diagnóstico PASAR (`:1655-1658`).

### Filtros posteriores del 1X2 (`main`)

32. Si el pick es APOSTAR y p es menor que `floor_prob_min`, el motor cambia el pick a PASAR Floor (`:2152-2154`).
33. Si el pick sigue en APOSTAR y EV es menor que `min_ev_escalado(p)`, el motor cambia el pick a PASAR EV Insuf (`:2155-2156`).
34. `min_ev_escalado` exige EV 0.03 si p es al menos 0.50, 0.08 si p es al menos 0.40 y 0.12 si p es al menos 0.33 (`:359-364`).
35. `min_ev_escalado` devuelve 999 si p es menor que el floor, lo que bloquea el pick (`:364`).
36. El motor repite el 1X2 con probabilidades crudas como grupo control, con los mismos filtros (`:2165-2182`).

### Decisión O/U (`evaluar_mercado_ou`, `src/nucleo/motor_calculadora.py:1660`)

37. Si hay xG, el motor pasa el partido cuando |xG total − 2.5| es menor que 0.30 con xG de al menos 2.5 (`:1673-1677`).
38. Si hay xG, el motor pasa el partido cuando |xG total − 2.5| es menor que 0.25 con xG menor que 2.5 (`:1673-1677`).
39. El motor pasa el partido si |over − under| es menor que `margen_predictivo_ou` (`:1679-1680`).
40. El motor elige el lado más probable y pasa el partido si su cuota es 1 o menos (`:1685-1689`).
41. El motor aprueba si EV supera `0.03 × 0.5/p` y la cuota no supera `techo_cuota_ou` (`:1691-1695`).
42. El O/U no pasa por el piso ni por `min_ev_escalado` (`:2152-2156` aplica solo al 1X2).

### Arranque en frío

43. Si min(n_home local, n_away visita) es menor que 5, el motor pasa ambos mercados con Datos Insuficientes (`:2186-2193`).
44. Un equipo sin fila en `historial_equipos` cuenta con n igual a 0 (`:661`).

### Pretest y stake del motor

45. Si `apuestas_live` es FALSE para la liga, el stake 1X2 es 0 y el pick queda registrado (`:2199-2201`).
46. Si `apuesta_ou_live` no tiene fila, el código usa TRUE (`:324`, `:2204-2206`).
47. Los flags de 1X2 y O/U son independientes entre sí (`:2209-2211`).
48. Si ambos stakes son mayores a 0, el motor pone stake O/U en 0 y el pick en PASAR Overlap (`:2223-2225`).

### Kelly y drawdown

49. El motor calcula p como (1/c) × (1 + EV) y el Kelly completo como (p·c − 1)/(c − 1) (`:1731-1732`).
50. El stake es bankroll × max(0, min(Kelly × `fraccion_kelly`, `MAX_KELLY_PCT`)) (`:1733-1734`).
51. El stake es 0 si el pick no contiene APOSTAR, si EV es 0 o menor, o si la cuota es 1 o menos (`:1728-1729`).
52. `MAX_KELLY_PCT` vale 0.025 sin drawdown y 0.010 con drawdown (`:1774-1779`).
53. `detectar_drawdown` lee las últimas 40 filas liquidadas con stake mayor a 0 (`src/nucleo/motor_calculadora.py:542-546`).
54. `detectar_drawdown` devuelve TRUE si cinco partidos PERDIDA aparecen antes de cualquier GANADA (`:549-556`).
55. Una GANADA en cualquier mercado del partido cuenta como partido ganado (`:550-552`).

### Covarianza

56. El motor agrupa apuestas vivas por (país, fecha) y multiplica cada stake por 1/√N si N es mayor que 1 (`:1738-1750`, `:2240-2244`).
57. La covarianza ajusta stake_1x2 y stake_ou, pero no stake_shadow (`:1747-1750`, `:2213-2214`).

### Bankroll (`obtener_bankroll_operativo`, `:560-637`)

58. En modo fijo, el motor usa `configuracion.bankroll` con default 100000 (`:578-585`).
59. En modo dinámico, el motor suma base, aportes desde la fecha de corte y P/L liquidado desde esa fecha (`:587-632`).
60. El P/L de una GANADA usa la cuota guardada en `partidos_backtest` (`:617-621`).
61. Si el bankroll queda bajo el piso, el motor usa el capital real con mínimo 0 y avisa (`:633-636`).
62. Si el bankroll supera el techo, el motor lo limita al techo (`:637`).

### Escritura

63. El motor escribe un UPDATE por partido y marca el estado Calculado (`:2246-2270`).

### Pretest (`scripts/evaluar_pretest.py`)

64. El script fija N mínimo en 15 para 1X2 y para O/U (`:146-147`).
65. El script cuenta por liga los picks con token GANADA o PERDIDA y cuota mayor a 1 (`:66-83`).
66. El script calcula yield plano como suma de P/L dividida por N, con stake 1 (`:81`, `:95`).
67. El script calcula break-even como media de 1/cuota (`:82`, `:94`).
68. El script calcula el p-valor binomial exacto one-sided contra el break-even (`:96`).
69. El script propone TRUE si N es al menos N mínimo, yield es mayor que 0 y p no supera p_max, con flag hoy FALSE (`:99-107`).
70. El script propone FALSE si el flag hoy es TRUE, N es suficiente y el yield es 0 o menor (`:112-114`).
71. Sin `--aprobar-live`, el script descarta las propuestas TRUE y solo las imprime (`:166-172`).
72. El script aplica FALSE siempre, con UPSERT para ambos flags (`:122-134`, `:191-193`).

## Invariantes (lo que nunca debe pasar)

- Ningún partido confirmado se recalcula ni cambia de pick.
- Ningún stake mayor a 0 aparece con un mercado que no está live.
- Ningún stake supera `MAX_KELLY_PCT` multiplicado por el bankroll de la corrida.
- Ningún pick 1X2 queda en APOSTAR si su p está bajo el floor o su EV bajo `min_ev_escalado`.
- Ningún 1X2 se aprueba con una cuota de favorito incoherente.
- Ningún partido con ambos stakes positivos conserva stake O/U.
- Ningún flip a LIVE ocurre sin `--aprobar-live`.

## Parámetros (clave de config_motor_valores, default en código, efecto)

| Clave | Default en código | Efecto | Referencia |
|---|---|---|---|
| `max_kelly_pct_normal` | 0.025 | Tope de stake sin drawdown | `src/nucleo/motor_calculadora.py:64` |
| `max_kelly_pct_drawdown` | 0.010 | Tope de stake con drawdown | `:65` |
| `drawdown_threshold` | 5 | Partidos perdidos seguidos para drawdown | `:66` |
| `fraccion_kelly` | 0.50 | Multiplica el Kelly completo | `:67` |
| `umbral_ev_base` | 0.03 | EV mínimo base, escalado por 0.5/p | `:70` |
| `techo_cuota_1x2` | 5.0 | Cuota máxima en caminos 1 y 2 | `:71` |
| `techo_cuota_ou` | 6.0 | Cuota máxima en O/U | `:72` |
| `divergencia_max_1x2` | 0.15 global; por liga en `DIVERGENCIA_MAX_POR_LIGA` | Divergencia máxima modelo-mercado | `:73`, `:121-152`, `:1544` |
| `margen_predictivo_1x2` | 0.03 | Distancia mínima entre primera y segunda probabilidad | `:153`, `:1547` |
| `margen_predictivo_ou` | 0.05 | Distancia mínima entre over y under | `:154`, `:1679` |
| `floor_prob_min` | 0.33 | Probabilidad mínima en camino 3 y en el filtro posterior | `:159`, `:1610`, `:2153` |
| `conviccion_ev_min` | 1.0 | EV mínimo en camino 3 | `:166` |
| `techo_cuota_alta_conv` | 8.0 | Cuota máxima en caminos 2B y 3 | `:167`, `:1603`, `:1612` |
| `desacuerdo_prob_min` | 0.40 | Probabilidad mínima en camino 2B | `:177`, `:1600` |
| `divergencia_desacuerdo_max` | 0.30 | Divergencia máxima en camino 2B | `:178`, `:1601` |
| `consenso_prob_min` | 0.36 | Probabilidad mínima en camino 4 | `:190`, `:1623` |
| `consenso_cuota_min` | 1.12 | Cuota mínima en camino 4 | `:191`, `:1624` |
| `consenso_cuota_max` | 2.00 | Cuota máxima en camino 4 | `:192`, `:1624` |
| `apuesta_empate_permitida` | False | Permite EMPATE como pick | `:198`, `:1571` |
| `ratio_min_implicita` | 0.5 | Umbral de coherencia de cuota | `:199`, `:1583` |
| `n_min_partidos_equipo` | 5 | Partidos mínimos por equipo | `:200`, `:2188` |
| `margen_xg_ou_over` | 0.30 | Distancia mínima de xG a 2.5 para over | `:337`, `:1676` |
| `margen_xg_ou_under` | 0.25 | Distancia mínima de xG a 2.5 para under | `:338`, `:1676` |
| `rho_fallback` | -0.09 | rho si la liga no tiene `rho_calculado` | `:520`, `:1918` |
| `factor_corr_xg_ou` | 0.627 global; por liga en `FACTOR_CORR_XG_OU_POR_LIGA` | Escala xG del O/U | `:112`, `:1912`, `:1938` |
| `escalar_lambda_1x2` | 'FALSE' | Escala xG del 1X2 con el factor de O/U | `:1911` |
| `filtro_picks_v51` | None (filtro apagado) | JSON con `ligas`, `n_acum_max` 60, `excluir_q4` True, `m2_activo` False | `:216-232` |
| `m2_per_liga_activo` | 'FALSE' | Usa `m2_n_acum_max` por liga | `:244-246` |
| `m2_n_acum_max` | 60 (fallback del JSON) | Umbral de M.2 por liga | `:1522` |
| `prob_local_calibration_activa` | 'FALSE' | Activa la calibración P(LOCAL) | `:261-263` |
| `prob_local_calibration_v1`, `prob_local_calibration_buckets` | None | Tablas de calibración | `:266-267` |
| `apuestas_live` | 'FALSE' por liga | Activa stake 1X2 real | `:2199-2201` |
| `apuesta_ou_live` | True en código si no hay fila | Activa stake O/U real | `:324`, `:2204-2212` |
| `arch_decision_per_liga` | '{}' | JSON liga a 'V12' que cambia probabilidades | `:2011-2023` |
| `h4_x_rescue_threshold` | '{}' | Solo log shadow, no decide | `:2041-2112` |
| `gamma_1x2` | 0.59 | Solo xG mostrado | `:1889` |
| `incertidumbre_umbral_shadow` | 1.40 | Umbral del log shadow | `:329` |
| `hallazgo_g_activo`, `n_min_hallazgo_g`, `boost_g_fraccion` | True, 50, 0.50 | Solo shadow | `:400-402`, `:1812` |
| `calibracion_activa`, `calibracion_delta` | True, 0.042 | Solo shadow (`corregir_calibracion`) | `:372-375` |
| `delta_stake_activo`, `delta_stake_mult_alto`, `delta_stake_mult_med` | True, 1.30, 1.15 | Sin llamadores (código muerto) | `:386-390` |
| `bankroll`, `bankroll_modo`, `bankroll_piso`, `bankroll_techo`, `bankroll_fecha_corte` (tabla `configuracion`) | 100000, 'fijo', 100000, 1000000, '1970-01-01' | Bankroll y límites del modo dinámico | `:579-590` |
| `pretest_hit_threshold`, `pretest_ou_hit_threshold` | 0.55 | Solo informativo, ninguna decisión lo usa | `scripts/evaluar_pretest.py:139`, `:144` |
| `pretest_n_minimo`, `pretest_ou_n_minimo` | 15 (con piso 15) | N mínimo para flip | `:140`, `:146-147` |
| `pretest_p_max`, `pretest_ou_p_max` | 0.30 | p-valor máximo para flip | `:141`, `:148` |

Estado en `fondo_quant.db` (lectura del 2026-10-17):

- `apuestas_live` no tiene filas, por eso el 1X2 queda en pretest en todas las ligas.
- `apuesta_ou_live` tiene fila global FALSE, por eso el O/U queda en pretest.
- `filtro_picks_v51` no tiene filas, por eso M.1, M.2 y M.3 no corren.
- `m2_activo`, `m2_per_liga_activo` y `pretest_*` no tienen filas, por eso usan su default.
- `apuesta_empate_permitida` vale FALSE.
- `floor_prob_min` vale 0.33, `max_kelly_pct_normal` 0.025, `max_kelly_pct_drawdown` 0.01, `fraccion_kelly` 0.5 y `drawdown_threshold` 5.
- La tabla `configuracion` no tiene filas `bankroll*`. El bankroll efectivo es 100000 en modo fijo.

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

Tests existentes:

| Test | Ubicación | Cubre |
|---|---|---|
| `test_drawdown_*` (4 casos) | `tests/test_nucleo_calculadora.py:22`, `:28`, `:35`, `:149` | Detección de drawdown |
| `test_n_acum_resuelve_display_name_espn` | `tests/test_nucleo_calculadora.py:42` | Lookup de n_acum |
| `test_m2_no_bloquea_sin_opt_in`, `test_m2_bloquea_con_opt_in` | `tests/test_nucleo_calculadora.py:54`, `:63` | Opt-in de M.2 |
| `test_hallazgo_g_infla_locales_no_favoritos` | `tests/test_nucleo_calculadora.py:72` | Hallazgo G |
| `test_main_solo_calcula_futuros_sin_alerta` | `tests/test_nucleo_calculadora.py:79` | Selección de partidos |
| `test_poisson_dc_suma_uno` | `tests/test_nucleo_calculadora.py:100` | Normalización Dixon-Coles |
| `test_kelly_medio_y_cap` | `tests/test_nucleo_calculadora.py:105` | Kelly y tope |
| `test_flag_escalar_lambda_1x2_no_doble_escala_ou` | `tests/test_nucleo_calculadora.py:131` | Escala de lambda |
| `test_cuotas_invertidas_no_generan_pick`, `test_cuotas_coherentes_siguen_evaluandose` | `tests/test_nucleo_calculadora.py:138`, `:144` | Guardia de coherencia |
| `test_main_no_aplica_hallazgo_g_ni_fix5` | `tests/test_nucleo_calculadora.py:156` | Probabilidades de decisión |
| `test_bankroll_bajo_piso_usa_capital_real` | `tests/test_nucleo_calculadora.py:171` | Bankroll bajo piso |
| `test_hit_55_con_cuota_baja_no_flipea`, `test_yield_positivo_significativo_flipea` | `tests/test_pretest.py:13`, `:20` | Criterio de flip |
| `test_evaluar_sin_aprobacion_no_pasa_a_live` | `tests/test_pretest.py:33` | Aprobación de LIVE |
| `test_evaluar_revierte_a_pretest_sin_aprobacion` | `tests/test_pretest.py:44` | Reversión automática |
| `test_flujo_completo_de_una_apuesta_real` | `tests/test_flujo_dinero_real.py:26` | Flujo de punta a punta |

Huecos sin test:

- Caminos 2, 2B, 3 y 4 no tienen test directo.
- El filtro F2b no tiene test.
- M.1 y M.3 no tienen test.
- `evaluar_mercado_ou` no tiene test directo.
- Los filtros posteriores de piso y EV no tienen test.
- El overlap 1X2 sobre O/U no tiene test.
- La covarianza no tiene test.
- `arch_decision_per_liga` (V12) y H4 no tienen test.
- La calibración P(LOCAL) no tiene test.
- El bankroll dinámico con `aportes_capital` no tiene test. El P/L dinámico lo cubre solo el test de flujo.
- Ningún test cubre `--aprobar-live` con la fila de `apuestas_live` ausente (`scripts/evaluar_pretest.py:191-193`).
- Ningún test verifica que `stake_shadow` no pase por covarianza.

## Limitaciones conocidas

- La coherencia de cuota corta todo el 1X2 antes de evaluar otros caminos (`src/nucleo/motor_calculadora.py:1583-1584`).
- Si `filtro_picks_v51` no trae la clave `ligas`, el filtro M.1 no restringe ligas.
- `apuesta_ou_live` vale TRUE en código si no hay fila, pero FALSE en el script de pretest (`:324`, `scripts/evaluar_pretest.py:97`).
- `obtener_ema` cambia cualquier valor 0.0 por el default, porque usa `or` (`:671`).
- Los filtros de piso y EV solo corren sobre el 1X2 (`:2152-2156`).
- `multiplicador_delta_stake` y las constantes `DELTA_STAKE_*` no tienen llamadores (`:386-425`).
- El parámetro `hit_thr` y `fuente_prefix` no se usan en `_evaluar_mercado` (`scripts/evaluar_pretest.py:61`).
- La docstring del script dice N mínimo 5 para O/U, pero el código fija 15 (`scripts/evaluar_pretest.py:25`, `:146`).
- La covarianza ignora apuestas confirmadas del mismo día, porque esos partidos quedan fuera (`:1847`, `:2240-2244`).
- La covarianza no ajusta el stake shadow (`:2213-2214`).
- El drawdown cuenta filas, no días. Filas sin token no suman ni cortan la racha (`:549-556`).

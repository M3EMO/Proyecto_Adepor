# Estudios forward: casas locales, oddspoll y ligas con poca cobertura

Estado: borrador del 2026-10-23. Los protocolos se fijan antes de recolectar datos. Ningún estudio cambia el motor.

## Propósito

El edge contra el cierre de Pinnacle no apareció con modelos propios (D-026, D-028, D-029, D-030). Estos estudios buscan edge en el precio de las casas, no en el modelo. Miden el CLV de cada casa contra el cierre de Pinnacle sin margen.

## Hallazgos del 2026-10-23 (instantánea, no concluyente)

### FotMob `matchOdds` con `ccode3=ARG`
- Devuelve una casa por partido: 1xBet Argentina en 44 partidos y Mostbet AR en 23, de 67 cruzados con Pinnacle.
- Un cruce salió con local y visita invertidos (Augsburg contra Union Berlin): el cruce por nombres necesita chequear la orientación.
- Margen medio de la casa: 2.4% en 1xBet Argentina y 5.5% en Mostbet AR.
- EV previo contra Pinnacle previo, máximo por partido: +0.66% en 1xBet Argentina y −1.7% en Mostbet AR.
- Partidos con algún resultado de EV mayor a 2%: 12 de 43 en 1xBet Argentina y 1 de 23 en Mostbet AR.
- El máximo de tres resultados sobreestima el EV, porque elige el mayor de tres valores ruidosos.
- Solo hay cuota para partidos con cobertura de FotMob: ligas grandes de Europa, Brasil y Noruega. La Liga Profesional devolvió vacío.

### `cuotas_forward` (OddsPapi, captura del 2026-10-23 01:56)
- 104 partidos con Pinnacle y bet365 AR en la misma captura.
- Media del EV máximo por partido: −1.24%.
- Partidos con algún resultado de EV mayor a 2%: 19 de 104 (18%).
- El ritmo histórico de Bet365 contra Pinnacle en Europa fue 4% a 7% de los partidos.

### Cobertura de FotMob en LATAM y Noruega (un partido por liga)
| Cobertura | Ligas |
|---|---|
| `xG` | Liga Profesional, Série A, Série B, Colombia Primera A, Liga MX, Eliteserien |
| `ratings` | Bolivia Primera, Ecuador Serie A, Paraguay, Perú Liga 1 |
| `lower` | Primera Nacional (ARG), Primera B Chile, Primera B Colombia, Uruguay, Venezuela, divisiones menores de Noruega |

## E1. CLV de las casas contra el cierre de Pinnacle

- **Captura:** en cada corrida del pipeline, para los partidos próximos con `pin_*`, se guarda la cuota 1X2 de 1xBet Argentina o Mostbet AR (FotMob `ARG`) y de Bet365 UK (FotMob `GBR`). Se usa la tabla `cuotas_forward` con `casa` = `1xbet_ar_fm`, `mostbet_ar_fm` o `bet365_uk_fm`. No cambia el esquema.
- **Cruce:** por nombres y fecha, con chequeo de orientación. Se descarta un cruce sin similitud mínima en las dos orientaciones.
- **Apuesta simulada:** todo resultado con EV previo mayor que `umbral_ev_v2` contra Pinnacle previo sin margen.
- **Métrica:** CLV medio de las apuestas simuladas, es decir cuota por probabilidad de cierre de Pinnacle sin margen, menos 1. IC95 por bootstrap.
- **Éxito:** el límite inferior del IC95 es mayor que 0, con al menos 80 apuestas simuladas por casa (contrato, patrón shadow).
- **Comparación:** una casa por prueba. Las casas son tres, así que se corrige el nivel por tres comparaciones.
- **Cierre:** `pin_cierre_*` de `motor_cuotas`.

## E2. `oddspoll` de FotMob como variable

- **Contenido:** no son votos. Son frases generadas con parámetros, como rachas de victorias y goles (`TextTemplateId`, `StatValues`). No hay probabilidades.
- **Traducción a hándicap:** no existe una regla directa. Cada partido trae un conjunto distinto de frases.
- **Prueba:** se extraen variables numéricas por plantilla (por ejemplo, largo de la racha) y se evalúan con el diseño de `11-evaluacion-xg.md`: log-loss contra Pinnacle, entrenamiento y prueba separados en el tiempo.
- **Expectativa:** baja. Las rachas salen de estadísticas públicas que Pinnacle ya incorpora.
- **Condición previa (verificada 2026-10-23):** las frases no filtran el resultado. En rachas h2h de 4 partidos o más, el equipo de la racha gana entre 59% y 61% de las veces, no 100%.
- **Variables (fijadas antes de correr), 0 si la plantilla falta:**
  - `f_forma`: (victorias menos derrotas del local en 5 partidos, menos las del visitante) dividido 5. Plantilla `team_form_both`.
  - `f_h2h_gana`: racha de victorias h2h, positiva si es del local y negativa si es del visitante. Plantilla `h2h_winstreak`.
  - `f_h2h_invicto`: partidos h2h sin perder, con el mismo signo. Plantilla `h2h_undefeated`.
  - `f_goles`: goles del local menos goles del visitante en los últimos 3 partidos. Plantilla `goals_total_last_3_both`.
- **Modelo y datos:** el diseño de `11-evaluacion-xg.md` (Europa 2024/25 contra 2025/26, Argentina 2024 contra 2025), regresión logística con L2 C=1.0, solo mercado 1X2.
- **Éxito:** el límite superior del IC95 del cambio de log-loss contra Pinnacle de cierre sin margen es menor que 0.
- **Código:** `analisis/oddspoll_vs_pinnacle.py`. Resultado: `analisis/oddspoll_vs_pinnacle_<estrato>.json`.

### Resultados de E2 (2026-10-23)

| Estrato | n de prueba | Cambio en log-loss con las 4 variables | IC95 | Éxito |
|---|---|---|---|---|
| Europa (2025/26) | 898 | +0.0044 | [−0.0017, +0.0105] | No |
| Argentina (2025) | 464 | +0.0060 | [−0.0090, +0.0213] | No |

- Las variables están presentes en 79% a 81% de los partidos de prueba en Europa y en 70% en Argentina.
- La base recalibrada sin variables da +0.0023 y +0.0055: el candidato no supera ni a la recalibración.
- Conclusión: el oddspoll no agrega información al cierre de Pinnacle.

## E2b. Oddspoll separado por local y visitante (fijado 2026-10-23, antes de correr)

Pedido del usuario: un 60% de acierto en las rachas es mucho, hay que diferenciar local y visitante.

- **Variables, 8 en lugar de 4 con signo:** `forma_local`, `forma_visita`, `h2h_gana_local`, `h2h_gana_visita`, `h2h_invicto_local`, `h2h_invicto_visita`, `goles_local`, `goles_visita`. Cada una vale 0 si la plantilla falta o si la racha es del otro lado.
- **Diagnóstico previo:** para rachas h2h de 4 o más victorias, por lado de la racha: porcentaje de victorias real, probabilidad media de victoria que da el cierre de Pinnacle sin margen a ese equipo, y N. Si ambas cifras coinciden, la racha ya está en el precio.
- **Modelo y criterio:** igual que E2. Es una segunda comparación sobre los mismos datos, así que el resultado se lee con esa corrección: no se promueve por un IC95 que apenas excluya 0.
- **Código:** `analisis/oddspoll_local_visita.py`.

## E6. Porcentaje de victorias por equipo, separado por local y visitante (fijado 2026-10-23, antes de correr)

Pedido del usuario: buscar quién gana más seguido y definir por quién apostar a partir de ese porcentaje.

- **Datos:** `data/football_data/eu/` de 5 ligas grandes (E0, SP1, D1, I1, F1), siete temporadas en orden cronológico. Resultados y cuotas de cierre de Pinnacle.
- **Variables por partido:** `wl` = porcentaje de victorias del local en sus últimos 10 partidos como local; `wv` = porcentaje de victorias del visitante en sus últimos 10 como visitante. Se exige 5 partidos previos de cada equipo. Los equipos y partidos son solo los previos al partido.
- **Regla ingenua:** apostar al local si `wl > wv` y al visitante si `wv > wl`, a la cuota de cierre de Pinnacle. Se informa el rendimiento (yield) con IC95 por bootstrap.
- **Prueba de información:** regresión logística con los dos logits de Pinnacle más `wl` y `wv`, ajustada con las temporadas anteriores a 2024/25 y probada en 2024/25. Cambio de log-loss contra Pinnacle de cierre, IC95 por bootstrap.
- **Éxito:** el límite superior del IC95 del cambio de log-loss es menor que 0. La regla ingenua tiene yield esperado negativo igual al margen de Pinnacle; solo importa si su IC95 supera 0.
- **Código:** `analisis/winrate_local_visita.py`.

### Resultado de E2b y diagnóstico exploratorio (2026-10-23)

| Estrato | Cambio de log-loss con 8 variables | IC95 |
|---|---|---|
| Europa | +0.0077 | [+0.0008, +0.0147] |
| Argentina | +0.0478 | [+0.0154, +0.0837] |

- Separar por lado empeora el modelo: 8 variables sobreajustan. Ninguno cumple el criterio.
- Rachas h2h de 4 o más victorias en Europa (entrenamiento y prueba juntos), contra la probabilidad de cierre de Pinnacle:
  - Racha del local: real 76.7%, Pinnacle 68.2%, n=103, z=+1.92.
  - Racha del visitante: real 61.1%, Pinnacle 52.7%, n=108, z=+1.82.
- Es una pista exploratoria: se miró en los mismos datos, con seis cortes probados (3, 4 y 5 por lado), y ningún z supera 2. Se confirma en E6b con datos independientes.

## E6b. Rachas h2h calculadas desde resultados (fijado 2026-10-23, antes de correr)

- **Hipótesis:** el equipo con una racha de 4 o más victorias seguidas en los últimos enfrentamientos directos gana más seguido que la probabilidad que da el cierre de Pinnacle.
- **Datos:** `data/football_data/eu/` de todas las divisiones. Racha = enfrentamientos previos de la misma división, del más reciente hacia atrás, ganados por el mismo equipo (un empate la corta; el local o visitante de cada partido no importa).
- **Conjunto independiente:** temporadas 2019/20 a 2023/24 (carpetas 0, 1, 2, 6 y 3). La pista salió de 2024/25 y 2025/26 de las 5 ligas grandes, así que no se usan para confirmar.
- **Métrica:** diferencia entre el porcentaje real de victorias del equipo con racha y la probabilidad media de victoria de Pinnacle de cierre, con z calculado con la varianza de Pinnacle. Se reporta por lado (la racha es del local o del visitante). También el yield de apostar al equipo con racha a la cuota de cierre de Pinnacle, con IC95 por bootstrap.
- **Éxito:** z mayor que 2 en el conjunto independiente agrupado, con la misma señal en ambos lados y al menos 300 casos.
- **Código:** `analisis/winrate_local_visita.py`.

### Resultados de E6 y E6b (2026-10-23)

**E6, porcentaje de victorias local y visitante (5 ligas grandes, prueba 2024/25, n=1.712):**
- Cambio de log-loss contra Pinnacle: −0.00006, IC95 [−0.0019, +0.0018]. No hay información.
- La regla ingenua (apostar al lado con mayor porcentaje de victorias) acierta 51.4% contra 50.8% que da Pinnacle. Su yield es −1.6%, IC95 [−7.0%, +4.2%].

**E6b, rachas h2h de 4 o más victorias (todas las divisiones):**

| Conjunto | N | Gana real | Pinnacle | z | Yield | IC95 del yield |
|---|---|---|---|---|---|---|
| Independiente 2019/20 a 2023/24, local | 444 | 70.5% | 67.5% | +1.44 | +0.5% | [−6.2%, +7.3%] |
| Independiente, visitante | 523 | 53.0% | 53.0% | −0.03 | −5.4% | [−14.1%, +3.5%] |
| Independiente, agrupado | 967 | 61.0% | 59.7% | +0.92 | −2.7% | [−8.2%, +3.1%] |
| 2024/25 y 2025/26, agrupado | 561 | 64.9% | 59.0% | +3.01 | +6.0% | [−1.6%, +13.6%] |

- El criterio de éxito (z mayor que 2 en el conjunto independiente) no se cumple: z=+0.92.
- La pista de 2024/25 y 2025/26 no estaba en las temporadas anteriores. Un efecto que aparece solo en los dos últimos años puede ser ruido, un cambio de régimen o un efecto real reciente.
- El yield del período reciente tiene IC95 que incluye 0.
- Queda como hipótesis para seguir hacia adelante, sin cambiar el motor.

## E6c. Rachas por localía y por liga (fijado 2026-10-23, antes de correr)

Pedido del usuario: el efecto puede depender de la liga y de la localía. Se ven las rachas de cada equipo en su cancha y fuera.

- **Rachas, calculadas desde resultados de la misma división (`eu/`, todas las divisiones):**
  - `L_gana_en_casa`: victorias seguidas del local en sus partidos como local.
  - `V_gana_fuera`: victorias seguidas del visitante en sus partidos como visitante.
  - `V_sin_ganar_fuera`: partidos seguidos del visitante sin ganar como visitante.
- **Umbral principal:** 4 partidos. Se informan 3 y 5 como sensibilidad, sin elegir entre ellos.
- **Conjunto independiente:** temporadas 2019/20 a 2023/24. El posterior (2024/25 y 2025/26) se informa aparte.
- **Métrica:** diferencia entre el porcentaje real de victorias del equipo señalado (o de no ganar, para `V_sin_ganar_fuera`) y la probabilidad de Pinnacle de cierre, con z. Yield de apostar al equipo con racha a la cuota de cierre, cuando corresponde.
- **Éxito:** z mayor que 2.4 en el conjunto independiente para al menos una racha (corrección de Bonferroni por tres rachas), con al menos 300 casos.
- **Por liga:** se informa z por división con al menos 100 casos. La heterogeneidad entre divisiones no se usa para elegir ligas (D-030).
- **Código:** `analisis/winrate_local_visita.py`, función `rachas_localia`.

### Resultados de E6c (2026-10-23)

| Racha (umbral 4) | N independiente | Gana real | Pinnacle | z |
|---|---|---|---|---|
| Local gana en casa | 1.992 | 58.9% | 58.1% | +0.72 |
| Visitante gana fuera | 701 | 47.9% | 49.6% | −0.95 |
| Visitante no gana fuera | 9.126 | 74.7% | 74.8% | −0.18 |

- Ninguna racha alcanza z de 2.4 (criterio con corrección por tres rachas). Los umbrales 3 y 5 dan el mismo resultado.
- En el período 2024/25 y 2025/26 los z suben a +1.2 y +1.8 en algunas rachas, sin llegar a 2.4.
- Por división (36 combinaciones con al menos 100 casos), dos pasan z de 1.96: Premier League con racha de local (+1.96) y Eredivisie con visitante sin ganar (+2.02). Con 36 pruebas se esperan unos dos falsos positivos.
- Conclusión: Pinnacle ya precia las rachas por localía, y la heterogeneidad entre ligas es compatible con ruido.

## E7. Jugadores: ausencias, disciplina y descanso (fijado 2026-10-23, antes de correr)

Pedido del usuario: tener en cuenta a los jugadores. Se usan solo datos deportivos públicos de FotMob. Los datos de vida privada quedan fuera (ver abajo).

- **Datos:** `content.lineup` de cada partido terminado en `data/fotmob/raw/` (valor de mercado de los titulares, edad, capitán) y `content.stats` (tarjetas). Mismo conjunto y cruce con Pinnacle que E2.
- **Variables por equipo, calculadas solo con partidos previos del mismo equipo en el conjunto (mínimo 3 previos):**
  - `ausencia`: logaritmo del valor de mercado de los titulares del partido, menos el logaritmo del promedio de los últimos 5 partidos. Negativo significa un once más débil que el habitual, es decir bajas de titulares.
  - `disciplina`: tarjetas amarillas más roja (cuenta doble) por partido, promedio de los últimos 10.
  - `descanso`: días desde el partido anterior del equipo en el conjunto, con tope de 10.
- **Limitación del conjunto:** solo hay partidos de liga. El descanso no ve copas ni selecciones.
- **Modelo y datos:** igual que E2: Europa 2024/25 contra 2025/26, Argentina 2024 contra 2025, logística L2 C=1.0, 1X2, seis variables (tres por lado).
- **Éxito:** el límite superior del IC95 del cambio de log-loss contra Pinnacle de cierre sin margen es menor que 0.
- **Expectativa:** baja. Pinnacle cierra en el inicio y la alineación se publica antes.
- **Código:** `analisis/jugadores_vs_pinnacle.py`.

### Resultados de E7 (2026-10-23)

| Estrato | n de entrenamiento | n de prueba | Cambio de log-loss con 6 variables | IC95 | Éxito |
|---|---|---|---|---|---|
| Europa | 391 | 723 | +0.0130 | [+0.0002, +0.0263] | No |
| Argentina | 78 | 247 | +0.0312 | [−0.0079, +0.0718] | No |

- Solo ausencias: Europa +0.0070 [−0.0013, +0.0154]; Argentina +0.0196 [−0.0024, +0.0431].
- La potencia es baja, sobre todo en Argentina: el entrenamiento tiene 78 partidos. El conjunto empieza en 2024/25 y las variables exigen 3 partidos previos con valor del once.
- Ninguna variante supera a la base recalibrada. No hay evidencia de información sobre Pinnacle.
- Para un resultado más sólido hace falta historia de alineaciones de más temporadas.

### Vida privada de los jugadores (decisión de alcance)

- No se recopilan ni se infieren datos de vida privada de personas con nombre (relaciones, familia, salud, carácter, vida nocturna), desde redes sociales ni prensa del espectáculo.
- Motivo: es perfilar a individuos con datos personales, el valor predictivo de un rumor o de una etiqueta como "fiestero" no se puede verificar, y los modelos que usan datos así heredan sesgo y error de atribución.
- La pregunta de fondo (conducta y liderazgo) se cubre con datos deportivos objetivos: tarjetas y faltas (`disciplina`), capitanía (`isCaptain` en la alineación), minutos juntos y rotación.
- Si algún día se quiere ir más allá, el camino es una fuente profesional y con consentimiento (por ejemplo, información de un club), no scraping de redes.

## E3. Ligas con poca cobertura

- **Primera Nacional y otras `lower`:** FotMob no trae estadísticas ni tiros. No hay base para xG. Quedan fuera.
- **Ligas `ratings` (Bolivia, Ecuador, Paraguay, Perú):** traen estadísticas agregadas (tiros, tiros al arco, tiros dentro del área, ocasiones claras, toques en el área rival).
- **Proxy de xG:** una regresión sobre esas estadísticas, entrenada donde FotMob da xG (Liga Profesional, Europa) con el xG de equipo como objetivo. Se mide el R² en partidos reservados.
- **Variables:** tiros totales, tiros al arco, tiros dentro del área, ocasiones claras, toques en el área rival y córners de cada equipo, desde `content.stats`.
- **Partición:** el 80% más antiguo de los partidos para ajustar y el 20% más reciente para medir.
- **Modelos:** solo tiros totales, tiros totales y al arco, y el conjunto completo, con regresión de mínimos cuadrados.
- **Éxito:** R² del conjunto completo en la prueba de al menos 0.6 y al menos 0.05 mayor que el de solo tiros totales. Con menos, el proxy no justifica usarlo en ligas sin xG.
- **Código:** `analisis/proxy_xg.py`. Resultado: `analisis/proxy_xg.json`.
- **Límite duro:** sin cuotas históricas de Pinnacle para esas ligas no hay benchmark de mercado. Solo se puede evaluar contra resultados.
- **Cuotas:** `cuotas_forward` (OddsPapi) cubre torneos LATAM sin The Odds API. Acumula solo hacia adelante.
- **Reverse engineering del modelo de Opta:** exige coordenadas de tiros por liga. FotMob las da solo donde hay cobertura `xG`. En las demás ligas no existe una fuente de tiros.

## E4. Cruce entre Pinnacle, Bet365 y el promedio del mercado (histórico)

Pregunta: cuando Pinnacle da más chance a un resultado que las otras dos casas a la vez, ¿la cuota de esas casas tiene CLV positivo contra el cierre de Pinnacle?

- **Datos:** `data/football_data/eu/` de todas las divisiones. Cuotas previas PSH/D/A, B365H/D/A y AvgH/D/A. Cierre PSCH/D/A. Temporada 2023/24 para explorar y 2024/25 para validar.
- **Probabilidades:** cada casa se normaliza por separado, método proporcional. Se obtienen q_pin, q_b365 y q_avg.
- **Señal S1 (base):** EV de Bet365 contra Pinnacle mayor que 0.02, es decir `B365 × q_pin − 1 > 0.02`.
- **Señal S2 (cruce):** S1 y además `Avg × q_pin − 1 > 0.02`. Las dos casas pagan menos chance que Pinnacle.
- **Señal S3:** S1 y `Avg × q_pin − 1 ≤ 0`. Solo Bet365 difiere de Pinnacle.
- **Métrica:** CLV de la apuesta en Bet365, es decir `B365 × q_cierre_pin − 1`, con IC95 por bootstrap sobre las apuestas.
- **Éxito:** en 2024/25, el CLV medio de S2 tiene límite inferior del IC95 mayor que 0, con al menos 80 apuestas.
- **Diagnóstico:** movimiento medio de Pinnacle `q_cierre_pin − q_pin` en cada señal. Si es negativo, Pinnacle se mueve hacia las otras casas.
- **Código:** `analisis/cruce_casas_pinnacle.py`. Resultado: `analisis/cruce_casas_pinnacle.json`.
- **Forward:** con `cuotas_forward` se repite con bet365 AR y Betano, cuando haya N suficiente.

### Resultados de E4 (2026-10-23)

| Señal | Temporada | N | CLV medio | IC95 | Movimiento de Pinnacle |
|---|---|---|---|---|---|
| S1 base | 2023/24 | 574 | +1.68% | [+0.52%, +2.83%] | −0.55 pp |
| S1 base | 2024/25 | 506 | −0.16% | [−1.36%, +1.02%] | −0.90 pp |
| S2 cruce | 2023/24 | 20 | +5.72% | [−6.71%, +20.53%] | −1.05 pp |
| S2 cruce | 2024/25 | 53 | −2.98% | [−8.76%, +3.35%] | −1.69 pp |
| S3 solo Bet365 | 2023/24 | 530 | +1.39% | [+0.29%, +2.50%] | −0.52 pp |
| S3 solo Bet365 | 2024/25 | 422 | +0.34% | [−0.79%, +1.48%] | −0.73 pp |

- El criterio de éxito no se cumple: S2 tiene 53 apuestas en validación, menos de 80, y su IC95 incluye 0.
- S2 es rara, porque el promedio del mercado incluye a Pinnacle y casi siempre coincide con él.
- S1 tuvo CLV positivo en 2023/24 y nulo en 2024/25. El efecto no se sostiene entre temporadas, igual que en D-030.
- En todas las señales, Pinnacle se mueve hacia las otras casas hasta el cierre. El EV previo mayor a 2% se evapora en parte por ese movimiento.

## E5. Trayectoria de las líneas, de la apertura al cierre

Pregunta: entre la apertura y el cierre, ¿hay momentos en que una casa paga más que Pinnacle y esa ventaja sobrevive al cierre?

- **Fuente:** OddsPapi `GET /v4/historical-odds?fixtureId=...&bookmakers=pinnacle,bet365.bet.ar,betano`. Devuelve cada movimiento de línea con marca de tiempo (`createdAt`, `price`), desde la apertura. Una sola llamada trae las tres casas.
- **Prueba hecha el 2026-10-23:** un partido con 12 días de historia: Pinnacle 146 movimientos, bet365 AR 249 en el local, Betano 37. La respuesta pesó 12.7 MB.
- **Costo:** una llamada por partido, contra 250 pedidos por mes. La captura diaria de `cuotas_forward` ya usa una parte. Se pide una muestra de partidos terminados, no toda la liga.
- **Muestra:** partidos con `fixture_id` en `cuotas_forward`, terminados, de ligas con cobertura de las tres casas. Mínimo 40 partidos, repartidos entre Europa y LATAM.
- **Reconstrucción:** el precio de cada casa en cada instante es el último movimiento conocido. Se evalúa cada 30 minutos desde que las tres casas tienen precio.
- **Oportunidad:** un instante y un resultado donde la casa paga un EV mayor que `umbral_ev_v2` sobre el Pinnacle de ese instante sin margen.
- **Métrica primaria:** CLV de cada oportunidad contra el cierre de Pinnacle (último precio antes del inicio), promediado por partido para no pesar más a los partidos con más instantes. IC95 por bootstrap de partidos.
- **Perfil por horas al inicio:** el CLV y la frecuencia de oportunidades en tramos de horas antes del inicio (más de 72, 24 a 72, 6 a 24, menos de 6).
- **Éxito:** el CLV medio por partido tiene límite inferior del IC95 mayor que 0 en al menos 40 partidos.
- **Rezago:** tiempo medio desde que Pinnacle se mueve más de 2% hasta que la casa se mueve en la misma dirección.
- **Sesgo conocido:** la normalización proporcional distorsiona a los resultados de cuota alta. Se informa el CLV aparte para cuotas mayores que 4.
- **Prototipo (un partido, anecdótico):** bet365 AR pagaba 7.0 al visitante mientras Pinnacle pagaba 6.12: EV previo de +8%. Al cierre Pinnacle pagaba 7.68 y el CLV de esa cuota fue de −12%. El EV previo se evaporó porque Pinnacle se movió hacia bet365.

### Resultados de E3 (2026-10-23)

| Modelo | R² en prueba | RMSE |
|---|---|---|
| Solo tiros totales | 0.421 | 0.636 |
| Tiros totales y al arco | 0.508 | 0.587 |
| Conjunto completo (6 variables) | 0.726 | 0.438 |

- Datos: 9.729 filas de equipo y partido con xG; prueba con el 20% más reciente (desde 2026-02-21, n=1.946).
- El criterio de éxito se cumple: R² de 0.726 (mínimo 0.6) y 0.30 por encima de solo tiros (mínimo 0.05).
- Las ocasiones claras (`big_chance`) pesan más: 0.255 de xG por ocasión.
- Lo que el proxy no demuestra: que sirva para apostar. Sin cuotas de Pinnacle en las ligas `ratings` no hay benchmark de mercado.
- Un proxy de xG exacto no es un edge: el xG real de Opta tampoco superó a Pinnacle (D-029).

## E8. CLV de bet365 AR contra el cierre de Pinnacle, vía OddsPapi (bead `adepor-1uk`)

Protocolo fijado el 2026-10-23, antes de ver ningún CLV. Complementa a E1 con la cuota argentina real de bet365 (`bet365.bet.ar`).

- **Datos:** `cuotas_forward` con `casa` = `pinnacle` y `bet365.bet.ar`, captura diaria de `motor_oddspapi`. El cierre sale de `pin_cierre_*`.
- **Cruce:** misma liga, kickoff a 3 horas o menos, y nombres iguales o parecidos (enmienda del 2026-10-23, antes de ver datos).
- **Pick:** primera captura de cada partido; cada resultado con EV de 2% o más sobre Pinnacle de la misma captura.
- **Filtro de calidad:** se descarta una fila con EV de 100% o más, o con probabilidad a más de 25 puntos de Pinnacle.
- **Estrato primario:** Liga Profesional, Copa Argentina, Libertadores y Sudamericana.
- **Regla:** hay edge si el CLV medio es mayor que 0 con IC95 entero sobre 0, y el yield plano no es negativo.
- **Parada:** una sola decisión, con 300 picks con cierre en el estrato primario o el 2027-06-30.
- **Corte secundario, sin decisión:** picks con probabilidad de Pinnacle de 35% o más.
- **Seguimiento:** `analisis/clv_bet365ar.py`, paso 9 de la cascada, escribe `data/oddspapi/clv_bet365ar.json`; el dashboard lo muestra en Valor v2.
- **Banco de nombres:** el mismo script guarda como alias los nombres de OddsPapi de un cruce claro (`gestor_nombres.aprender_alias`). Los dudosos quedan en `alias_a_revisar`.
- **CUSUM, alerta temprana sin decisión:** `S = max(0, S + k − CLV)`, con `k` = 1% y `h` = 2,10. Si `S` supera `h`, el edge probablemente se apagó.
- **Calibración del CUSUM:** con Bet365 en Europa 2019-2022, 10% de falsas alarmas en 300 picks con edge. En retro, la primera alarma llega el 2024-05-18; sin edge, tarda una mediana de 79 picks.

## E9. Piso de probabilidad (bead `adepor-aua`)

Protocolo fijado el 2026-10-23, antes de correr. Datos: football-data, Europa top 6.

- **Pick como el v2:** por partido, el resultado de mayor EV de Bet365 previo sobre Pinnacle previo, si ese EV es de 2% o más.
- **Elección:** con 2019 a 2022, el piso con mayor CLV entre los que dejan 200 picks o más.
- **Resultado:** solo el piso 0 llega a 200 picks, así que el elegido es "sin piso".
- **Prueba 2023-2025:** CLV −0,02%, IC95 [−1,97%, +1,82%], n=243. No pasa: no se agrega piso (D-037).
- **Hallazgo:** los picks son casi todos underdogs, con cuota mediana de 6,5 y probabilidad mediana de 16,5%.

## E10. Pinnacle y Bet365 por nivel de división (bead `adepor-4c8`)

Protocolo fijado el 2026-10-23, antes de correr. Datos: football-data 2019-2025.

| Nivel | Divisiones | Margen Pinnacle | Pendiente de calibración | CLV 2023-2025 | IC 98,75% | Pasa |
|---|---|---|---|---|---|---|
| N1 | E0 SP1 I1 D1 F1 SC0 | 2,8% | 1,05 | +0,11% | [−2,21%, +2,41%] | No |
| N2 | E1 SP2 I2 D2 F2 SC1 | 3,3% | 1,01 | +2,06% | [+0,72%, +3,46%] | Sí |
| N3 | E2 SC2 | 4,1% | 1,13 | +1,17% | [−1,96%, +4,74%] | No |
| N4 | E3 EC SC3 | 4,5% | 1,01 | +1,43% | [−0,38%, +3,31%] | No |

- El cierre de Pinnacle está bien calibrado en todos los niveles (pendiente cercana a 1).
- N2 tiene CLV positivo en las 7 temporadas.
- Por tramo de probabilidad, los picks de 20% a 35% tienen CLV positivo todas las temporadas; los de menos de 20% caen a cero desde 2021.
- Los favoritos de 50% o más casi nunca dan EV de 2% con Bet365.

## E11. bet365 AR en segundas divisiones, forward (bead `adepor-dch`)

Protocolo fijado el 2026-10-23, antes de capturar datos de estas ligas. Sigue a D-038.

- **Torneos:** Championship (18), Primera Nacional de Argentina (703) y Primera B de Chile (1240), tres niveles distintos.
- **Pick:** igual que E8.
- **Cierre:** Championship usa `pin_cierre_*`. Las otras dos ligas no están en The Odds API, así que usan la última captura de Pinnacle posterior al pick y anterior al inicio.
- **Regla:** CLV medio de los tres torneos juntos con IC95 entero sobre 0, y yield plano no negativo.
- **Parada:** una sola decisión con 300 picks con cierre o el 2027-06-30.
- **Límite:** el cierre aproximado es más temprano que un cierre real; el Pinnacle previo está casi tan calibrado como el cierre.

## Orden propuesto

1. E1, porque ya hay datos y el CLV es la métrica del contrato.
2. E3, el proxy de xG, solo para medir si el proxy reproduce el xG real.
3. E2, de baja expectativa y de bajo costo.

## Pruebas de aceptación (a escribir antes del código)

| Id | Criterio |
|---|---|
| W1 | El cruce descarta un partido con local y visita invertidos |
| W2 | Una respuesta `null` de `matchOdds` no guarda filas |
| W3 | La captura es idempotente por partido, casa y captura |
| W4 | El CLV usa la cuota guardada, no la última |

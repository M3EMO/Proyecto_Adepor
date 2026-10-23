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
- **Condición previa:** confirmar que las frases de un partido terminado se calcularon antes del partido.

## E3. Ligas con poca cobertura

- **Primera Nacional y otras `lower`:** FotMob no trae estadísticas ni tiros. No hay base para xG. Quedan fuera.
- **Ligas `ratings` (Bolivia, Ecuador, Paraguay, Perú):** traen estadísticas agregadas (tiros, tiros al arco, tiros dentro del área, ocasiones claras, toques en el área rival).
- **Proxy de xG:** una regresión sobre esas estadísticas, entrenada donde FotMob da xG (Liga Profesional, Europa) con el xG de equipo como objetivo. Se mide el R² en partidos reservados.
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

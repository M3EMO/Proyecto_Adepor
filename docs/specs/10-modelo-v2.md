# Modelo v2 (en diseño)

Estado: diseño aprobado (D-019) e implementado el 2026-10-17 (D-021).

## Propósito

El v2 busca un edge medible y apuesta solo si lo demuestra fuera de muestra. Reemplaza al motor actual, que no le gana a Pinnacle (D-014).

## Decisiones tomadas

| Tema | Decisión del usuario |
|---|---|
| Estrategia | Investigación primero; si no aparece algo mejor, modelo híbrido |
| Casas para apostar | BetWarrior, Bet365 y casas locales de Argentina |
| Mercados | 1X2, Over/Under 2.5, hándicap asiático y ambos marcan |
| Ligas | Europa top y LATAM |

**Híbrido** significa: la probabilidad base es la de Pinnacle sin margen. El modelo propio solo agrega una corrección donde demuestre información propia.

## Protocolo de evaluación (fijado antes de ver resultados)

1. Los datos se separan por tiempo: entrenamiento, validación y prueba, sin solapamiento.
2. La prueba final se corre una sola vez, al terminar el diseño.
3. Métrica primaria: log-loss contra el cierre de Pinnacle sin margen, por mercado.
4. Métricas secundarias: CLV medio y yield plano con IC95 bootstrap.
5. Regla de promoción: CLV medio > 0 con IC95 que excluya 0, y yield no negativo.
6. Cada variante probada se registra, para corregir por comparaciones múltiples.

## Datos

| Fuente | Uso |
|---|---|
| football-data.co.uk | Historia EU con tiros y cuotas de Pinnacle y Bet365, apertura y cierre |
| ESPN | Fixtures, resultados y stats recientes |
| The Odds API | Cuotas en vivo de varias casas para operar |

## Resultados de la investigación (2026-10-17)

### Literatura (`vault/research/betdeportivo-modelo-v2-evidencia.md`)
- El edge publicado sale de comparar casas contra un consenso o una casa sharp, no de un modelo propio.
- Kaunitz et al. (2017) reportan 8.5% de ROI con 265 apuestas reales, y las casas los limitaron en semanas.
- No aparece un modelo propio de fútbol que le gane al cierre fuera de muestra tras el margen.
- El hándicap asiático no muestra el sesgo favorito-underdog del 1X2.

### Factibilidad (`vault/research/betdeportivo-modelo-v2-factibilidad.md`)
- The Odds API no lista BetWarrior ni casas argentinas.
- Bet365 aparece solo como Bet365 AU, cuyas cuotas pueden diferir de Bet365 Argentina.
- football-data no tiene cuotas de BTTS; sí tiene hándicap asiático de Pinnacle y Bet365.

### Backtest propio: Pinnacle como verdad, apuesta en Bet365
Script: `analisis/value_pinnacle_bet365.py` (resultado en `.json`). Datos: EU top 2023-25, 8676 resultados posibles.

| Umbral EV | N | ROI realizado | IC95 | EV vs cierre Pinnacle | Cuota mediana |
|---|---|---|---|---|---|
| > 0% | 304 | −2.4% | [−27.8%, +22.9%] | −0.6% | 5.5 |
| > 2% | 129 | −17.6% | [−58.7%, +32.2%] | +0.8% | 7.5 |
| > 4% | 69 | −47.0% | [−85.1%, −2.5%] | +1.5% | 9.0 |

- Bet365 supera a Pinnacle solo en el 3.5% de los resultados posibles.
- Con umbral 0 no hay edge: el EV contra el cierre es negativo.
- Con umbrales mayores el EV contra el cierre es levemente positivo, pero el N es chico.
- Esas apuestas son underdogs de cuota alta, con varianza enorme: el resultado no es concluyente.

## Diseño aprobado (D-019)

1. El sistema calcula la probabilidad justa con Pinnacle sin margen.
2. El dashboard muestra para cada pick la **cuota mínima** que vuelve positiva la apuesta.
3. El usuario compara esa cuota con BetWarrior o su casa local, y confirma solo si la supera.
4. La confirmación guarda la cuota real tomada; el CLV contra el cierre de Pinnacle mide el edge.
5. El modelo propio queda como corrección, y entra solo si mejora la log-loss contra Pinnacle.
6. BTTS queda fuera hasta conseguir historia de cuotas para validarlo.

Motivo: las casas donde apostás no tienen cuotas automáticas, y Bet365 no muestra edge contra Pinnacle.

## Implementación (D-021)

| Pieza | Código |
|---|---|
| Probabilidad justa, cuota mínima, stake y CLV | `src/nucleo/valor_v2.py` |
| Cuotas Pinnacle previas y de cierre | `src/ingesta/motor_cuotas.py` (`pin_*`, `pin_cierre_*`) |
| Confirmación con pick elegido y casa | `src/persistencia/confirmaciones.py` (`pick=`, `casa=`) |
| Pestaña "Valor v2" y CLV por casa | `dashboard.py` |
| Test de punta a punta | `tests/test_flujo_dinero_real.py::test_flujo_v2_pinnacle_como_verdad` |

Parámetros (config_motor_valores, default en código):
| Clave | Default | Efecto |
|---|---|---|
| `umbral_ev_v2` | 0.02 | EV mínimo sobre la prob justa para la cuota mínima |
| `fraccion_kelly_v2` | 0.25 | Fracción de Kelly del stake sugerido |
| `tope_stake_v2` | 0.005 | Fracción máxima del bankroll por apuesta (Max DD p95 ≤ 15%, D-020) |

- La normalización proporcional sobreestima levemente a los underdogs; si su CLV sale peor, se cambia a Shin.
- El CLV v2 es el EV de la cuota tomada contra el cierre de Pinnacle sin margen.
- La fracción y el tope se recalibran con `analisis/pareto_stake.py` cuando haya 50 apuestas liquidadas (D-020).

### Método de margen y tiros (D-026, 2026-10-22)
Script: `analisis/margen_y_tiros_pinnacle.py`. Protocolo pre-registrado en el bead `adepor-4kg`.

| Prueba | Estrato | N | Diferencia de log-loss | IC95 | Pasa |
|---|---|---|---|---|---|
| Shin vs proporcional, 1X2 | Europa | 13880 | −0.00026 | [−0.00049, −0.00004] | Sí |
| Shin vs proporcional, 1X2 | ARG, BRA, NOR | 7386 | +0.00007 | [−0.00024, +0.00036] | No |
| Shin vs proporcional, O/U 2.5 | Europa | 13809 | −0.00016 | [−0.00028, −0.00004] | Sí |
| Tiros al arco vs cierre | Europa | 11014 | −0.00009 | [−0.00052, +0.00031] | No |
| Tiros al arco vs pre-cierre | Europa | 11004 | −0.00038 | [−0.00091, +0.00010] | No |

- El proporcional se queda, porque Shin no pasa en los dos estratos.
- En Europa, el proporcional sobreestima a los underdogs y subestima al favorito fuerte (decil p=0.69 gana 71%).
- En Argentina, Brasil y Noruega, el cierre de Pinnacle no muestra desvíos por decil.
- Los tiros al arco no agregan información al precio de Pinnacle.

### Evolución del bankroll y piso de probabilidad (D-037, 2026-10-23)
Script: `analisis/bankroll_y_piso_v2.py`. Un pick por partido: el de mayor EV de Bet365 previo sobre Pinnacle previo, con EV de 2% o más.

| Período | Picks | Resultado | Yield |
|---|---|---|---|
| 2019-2022 | 497 | +28.811 | positivo en las 4 temporadas |
| 2023-2025 | 243 | −7.450 | negativo en las 3 temporadas |
| Total | 740 | 100.000 → 121.361 | +10,7% |

- La caída máxima fue de 9,4%, bajo el tope de 15% de D-020.
- El acierto fue de 18,6%, porque los picks son casi todos underdogs.
- Un piso de probabilidad no pasa la prueba fuera de muestra.

## Investigación pendiente

- Probar Shin solo para ligas europeas, fuera de muestra, con los `pin_cierre_*` del pipeline.

- Medir con datos de LATAM si las casas blandas se desvían más de Pinnacle.

## Preguntas abiertas

- Bankroll: 100.000 en modo fijo, cargado el 2026-10-20.
- Max DD p95 tolerado: 15% (D-020). El stake sale del frente de Pareto bajo ese tope.
- ¿Cuánto tarda BetWarrior en limitar una cuenta ganadora? No hay evidencia pública.

# Evaluación del xG de FotMob contra Pinnacle

Estado: protocolo fijado el 2026-10-22, antes de ver resultados. Resultados del 2026-10-23: sin edge (D-029).

## Propósito

Este documento define si el xG de FotMob agrega información sobre el cierre de Pinnacle sin margen en 1X2. Si no la agrega, el xG no entra al modelo. La evidencia previa apunta a que no (D-026: los tiros al arco no corrigen a Pinnacle).

## Hipótesis

- H0: el xG acumulado no mejora la log-loss del cierre de Pinnacle sin margen.
- H1: el xG acumulado reduce la log-loss de forma significativa fuera de muestra.

## Protocolo

El detalle está en `analisis/fotmob_xg_vs_pinnacle_prereg.md`. Resumen:

| Elemento | Europa | Argentina |
|---|---|---|
| Ligas | Premier, LaLiga, Bundesliga, Serie A, Ligue 1 | Liga Profesional |
| Entrenamiento | 2024/25 | 2024 |
| Prueba | 2025/26 | 2025 |
| Cuotas | PSCH, PSCD, PSCA de football-data `eu/` | PSCH, PSCD, PSCA de `new/ARG.csv` |
| Base | Pinnacle de cierre sin margen, proporcional | Igual |
| Candidato | Regresión logística: dos logits de Pinnacle y `dxg` | Igual |
| Control | Igual con goles en lugar de xG | Igual |

- `dxg` es la EMA (alpha 0.1) de xG a favor menos xG en contra, del local menos la del visita.
- La EMA usa solo partidos previos de la misma liga y temporada. Cada equipo necesita 5 partidos previos.
- Los coeficientes se ajustan en entrenamiento y no se reajustan en la prueba.
- La prueba se corre una sola vez por estrato.

## Criterio de éxito

- Métrica: diferencia de log-loss (candidato menos base), con bootstrap pareado por partido (10000 remuestreos, IC95).
- Éxito: el límite superior del IC95 es menor que 0.
- Cualquier otro resultado cierra la hipótesis sin edge.
- La base recalibrada sin xG es un control exploratorio. No decide.

## Entradas y salidas

| Elemento | Ruta |
|---|---|
| Partidos FotMob | `data/fotmob/raw/*.json` (spec `07-fotmob.md`) |
| Cuotas Europa | `data/football_data/eu/{4,5}/{E0,SP1,D1,I1,F1}.csv` |
| Cuotas Argentina | `data/football_data/new/ARG.csv` |
| Script | `analisis/fotmob_xg_vs_pinnacle.py` |
| Resultado | `analisis/fotmob_xg_vs_pinnacle.json` |

## Resultados (2026-10-23)

| Estrato | n de prueba | Candidato con xG: cambio en log-loss | IC95 | Éxito |
|---|---|---|---|---|
| Europa | 656 | +0.0071 | [+0.0002, +0.0140] | No |
| Argentina | 388 | +0.0059 | [−0.0109, +0.0227] | No |

- H0 no se rechaza en ningún estrato.
- En Europa la prueba cubre media temporada 2025/26: football-data trae el cierre de Pinnacle en unos 900 de 1.752 partidos.
- En Argentina, 203 filas de entrenamiento no cruzan porque son de la Copa de la Liga, que la descarga de FotMob no incluye.
- La Liga Profesional usa ids de subtorneo en 2024 y 2025: la liga queda en `parentLeagueId`.

## Pruebas de aceptación

| Id | Criterio | Estado |
|---|---|---|
| X1 | El cruce reporta cuántos partidos quedan sin pareja y rechaza parejas con nombres muy distintos | Cubierta |
| X2 | `features()` no usa el partido actual para su propia EMA | Cubierta |
| X3 | Con `dxg` aleatorio, el candidato no mejora a la base (control negativo) | Cubierta |
| X4 | Con un `dxg` que filtra el resultado, el candidato mejora (control positivo) | Cubierta |

## Cierre

- El resultado se registra en `docs/decisiones/registro.md` como decisión nueva, aunque sea negativo.
- Un resultado positivo no cambia el motor. Abre un bead `[PROPOSAL: MANIFESTO CHANGE]` y entra primero a shadow.

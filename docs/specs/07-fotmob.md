# Ingesta FotMob

Estado: borrador del 2026-10-22. El código es `scripts/research/fotmob_pedir.py`. Es investigación, no entra al pipeline diario.

## Propósito

Este documento describe cómo se baja el detalle de un partido desde FotMob. El detalle incluye stats, tiros con xG, alineaciones y eventos. FotMob reemplaza a SofaScore como fuente de stats (decisión del usuario, 2026-10-18).

## Contrato del pedido

| Modo | Entrada | Salida |
|---|---|---|
| `partido <id>` | Un id de partido de FotMob | `data/fotmob/raw/<id>.json` y una fila por la salida estándar |
| `liga <id> <temporada> [--max N] [--solo-xg]` | Liga y temporada, por ejemplo `47 2025%2F2026` | Un JSON crudo por partido terminado |
| `dia <YYYYMMDD> [--liga ID] [--solo-xg]` | Fecha en hora de Argentina | Un JSON crudo por partido terminado de ese día |

- El pedido usa `curl_cffi` con `impersonate="chrome"`. No usa el token proxy del paquete `fotmob-wrapper`.
- El script espera 1 s entre pedidos.
- Un archivo existente no se vuelve a bajar. El modo `partido` siempre lo baja de nuevo.
- El script valida que `general.matchId` coincida con el id pedido.
- Un partido que falla se informa por el error estándar y no frena el lote.
- `--solo-xg` descarta los partidos cuyo `general.coverageLevel` no sea `xG`.

## Cobertura medida (2026-10-22)

| `coverageLevel` | Contenido | Ejemplos |
|---|---|---|
| `xG` | Tiros con xG por tiro y `expected_goals` en stats | Top 5 de Europa, Liga Profesional, Libertadores, MLS, Liga MX, Colombia |
| `ratings` | Stats agregadas sin tiros | Copa Sudamericana, US Open Cup |
| `lower` | Casi nada | Divisiones menores y copas menores |

- La muestra fue un partido por liga en 40 ligas. Una liga puede cambiar de nivel según la fase.
- La Liga Profesional tiene `xG` en 2023, 2024, 2025 y 2026.
- El top 5 de Europa tiene `xG` de 2020/21 a 2025/26.

## Límites y riesgos

- La API no es pública y puede cambiar sin aviso.
- El uso roza los términos de FotMob. El usuario aceptó ese riesgo.
- El xG de FotMob es de Opta. No equivale al `xg_v3` retirado, que venía de SofaScore.
- Los datos crudos pesan cerca de 150 KB por partido. `data/fotmob/` no se versiona.

## Pruebas de aceptación

| Id | Criterio | Estado |
|---|---|---|
| F1 | `fila()` devuelve xG por equipo igual a la suma del xG por tiro, con tolerancia 0.05 | Cubierta |
| F2 | Un id que devuelve otro `matchId` lanza `ValueError` y no guarda archivo | Cubierta |
| F3 | Con `--solo-xg`, un partido `ratings` no se guarda | Cubierta |
| F4 | Un archivo existente no dispara un pedido de red | Cubierta |

Las pruebas usan un JSON de muestra y un doble de `pedir`. Ninguna toca la red.

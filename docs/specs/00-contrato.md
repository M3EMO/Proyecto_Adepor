# Contrato del sistema

Este documento reemplaza a `Reglas_IA.txt`. Define qué cambios requieren aprobación y qué reglas no se rompen.

## Reglas que no se rompen

1. Un pick se decide con información disponible antes del kickoff.
2. Un partido empezado o con apuesta confirmada no se recalcula.
3. El P/L se valora con la cuota realmente tomada, no con la última capturada.
4. Las métricas de dinero real cuentan solo partidos `Liquidado` con stake > 0.
5. Ninguna liga pasa a dinero real sin yield positivo significativo y aprobación humana (`--aprobar-live`).
6. Un modelo apuesta dinero real solo si le gana a Pinnacle fuera de muestra (D-014, D-018).
7. Toda evaluación es walk-forward: cada pronóstico usa solo datos anteriores al partido.
8. Antes de modificar la base de producción se hace un backup con la API de SQLite (`adepor_guard.py snapshot`).

## Cambios que requieren aprobación

Un cambio requiere un bead `[PROPOSAL: MANIFESTO CHANGE]` con label `approved-by-lead` si toca:
- La capa de decisión de `src/nucleo/motor_calculadora.py`.
- Las probabilidades que usan las decisiones.
- Los parámetros de riesgo: `fraccion_kelly`, `max_kelly_pct_*`, `floor_prob_min`, `ratio_min_implicita`, `n_min_partidos_equipo`.
- El criterio de pretest de `scripts/evaluar_pretest.py`.

La task que aplica el cambio lleva el tag `MANIFESTO-CHANGE-APPROVED:bd-<id>`. El hook `scripts/hooks/validate_task_created.py` verifica el label en el bead.

## Patrón shadow

- Todo cambio de modelo se registra primero en una tabla shadow con `aplicado_produccion = 0`.
- El motor nunca decide con datos shadow.
- La promoción exige evidencia walk-forward con N ≥ 80 partidos liquidados y la métrica fijada por adelantado.

## Mapa de specs

| Spec | Componente |
|---|---|
| `01-ingesta.md` | Fixtures, resultados, stats y cuotas |
| `02-modelo.md` | EMAs, xG proxy y Poisson Dixon-Coles |
| `03-decision.md` | Picks, filtros, Kelly y pretest |
| `04-liquidacion.md` | Resultados, liquidación, CLV y métricas |
| `05-presentacion.md` | Dashboard Streamlit y exportación Excel |
| `06-operacion.md` | Orquestador, base de datos, configuración y runbook |
| `10-modelo-v2.md` | Modelo nuevo (en diseño) |

Las decisiones vigentes están en `docs/decisiones/registro.md`.

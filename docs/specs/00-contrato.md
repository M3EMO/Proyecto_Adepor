# Contrato del sistema

Este documento reemplaza a `Reglas_IA.txt`. Define qué cambios requieren aprobación y qué reglas no se rompen.

## Reglas que no se rompen

1. Un pick se decide con información disponible antes del kickoff.
2. Un partido empezado o con apuesta confirmada no se recalcula.
3. El P/L se valora con la cuota realmente tomada, no con la última capturada.
4. Las métricas de dinero real cuentan solo partidos `Liquidado` con stake > 0.
5. El v2 se promueve solo con la regla fijada antes de ver resultados (`10-modelo-v2.md`, protocolo, punto 5) y aprobación humana.
6. Un modelo apuesta dinero real solo si le gana a Pinnacle fuera de muestra (D-014, D-018).
7. Toda evaluación es walk-forward: cada pronóstico usa solo datos anteriores al partido.
8. Antes de modificar la base de producción se hace un backup con la API de SQLite (`adepor_guard.py snapshot`).

## Cambios que requieren aprobación

Un cambio requiere un bead `[PROPOSAL: MANIFESTO CHANGE]` con label `approved-by-lead` si toca:
- La capa de decisión de `src/nucleo/valor_v2.py`.
- Las probabilidades que usan las decisiones.
- Los parámetros de riesgo: `umbral_ev_v2`, `fraccion_kelly_v2`, `tope_stake_v2`.

La task que aplica el cambio lleva el tag `MANIFESTO-CHANGE-APPROVED:bd-<id>`. El hook `scripts/hooks/validate_task_created.py` verifica el label en el bead.

## Patrón shadow

- Todo cambio de modelo se registra primero en una tabla shadow con `aplicado_produccion = 0`.
- El motor nunca decide con datos shadow.
- La promoción exige evidencia walk-forward con N ≥ 80 partidos liquidados y la métrica fijada por adelantado.

## Mapa de specs

| Spec | Componente |
|---|---|
| `01-ingesta.md` | Fixtures, resultados, stats y cuotas |
| `04-liquidacion.md` | Resultados, liquidación, CLV y métricas |
| `05-presentacion.md` | Dashboard Streamlit |
| `06-operacion.md` | Orquestador, base de datos, configuración y runbook |
| `07-fotmob.md` | Ingesta FotMob: pedido por partido, cobertura xG y límites |
| `10-modelo-v2.md` | Modelo v2: Pinnacle como verdad, cuota mínima, stake y CLV |
| `11-evaluacion-xg.md` | Estudio del xG de FotMob contra el cierre de Pinnacle |
| `12-producto-deploy.md` | Producto terminado: integración, chequeo de salud, informe de medición y deploy |

Las decisiones vigentes están en `docs/decisiones/registro.md`.

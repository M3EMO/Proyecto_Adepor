# GAPS T1 ↔ T2 — Notas de reconciliación

> Notas de reconciliación T1 ↔ T2 — para la fase futura de implementación del dashboard operativo. Los documentos firmados (`MOCKUPS.md`, `SPEC_DASHBOARD_OPERATIVO.md`, `AUDITORIA_VISOR_EVALS.md`) **NO se modifican**; este archivo es complemento informativo y no bloquea ningún cierre del refactor en curso.

---

## Contexto

El reporte completo de T1 (`analista-riesgos`) llegó después del cierre formal de la Tarea 2 de T2 (`disenador-ux`). Una pasada cruzada entre el reporte de T1 y los entregables de T2 detectó cuatro puntos donde T1 aporta granularidad adicional o entra en conflicto puntual con la SPEC ya firmada. Esta nota los captura para que la **fase futura de implementación del `dashboard_operativo.html`** los reconcilie sin tener que releer el thread original.

Fuentes:
- T1: `docs/ux/REPORTE_FRICCIONES.md`
- T2: `docs/ux/MOCKUPS.md`, `docs/ux/SPEC_DASHBOARD_OPERATIVO.md`, `docs/ux/AUDITORIA_VISOR_EVALS.md`

---

## Gap 1 — Bloque "Predicción vs Mercado" lado-a-lado

**Estado en T2**: la SPEC cubre los vectores `p1 / px / p2` del modelo y las cuotas del mercado de forma separada (en distintos bloques del cluster). No existe un bloque dedicado que los muestre **lado-a-lado** con el gap explícito.

**Aporte de T1**: clasifica este bloque como **P0** (impacto operativo alto) porque es el insumo visual que justifica la decisión de operar — el operador necesita ver simultáneamente la probabilidad del modelo y la probabilidad implícita del mercado para validar la asimetría que motiva la apuesta.

**Propuesta de UI textual** (no se entrega mockup ASCII; lo produce quien implemente):

- Tabla de tres filas (1 / X / 2) y tres columnas: **Modelo (%)**, **Mercado implícito (%)**, **Δ (pp)**.
- La columna Δ se colorea con el gradiente de la SPEC (verde si Δ a favor del modelo supera el umbral de la liga; rojo si Δ contrario; gris si dentro de banda).
- El bloque se ubica **entre** el bloque de pipeline xG y el bloque de stake, dentro de cada cluster.
- Reutilizar tokens tipográficos `--font-numeric` (SF Mono) y la paleta de la SPEC sin introducir colores nuevos.

**Prioridad recomendada**: P0 — debe estar en el primer release del dashboard operativo.

---

## Gap 2 — Conflicto cromático LOCAL / VISITA vs SHADOW / DEFENSIVO

**Estado en T2 (SPEC sección 6 — Sistema de color)**:
- Azul → marca de **SHADOW** (apuesta sombra vs OP1).
- Rojo (`--red`) → marca de **MODO DEFENSIVO** y de banca en drawdown.

**Estado en T1**: estándar visual operativo asigna:
- Azul → **LOCAL**.
- Rojo / naranja-vino → **VISITA**.

**Conflicto**: dos canales semánticos distintos compiten por el mismo color (azul) y por el mismo rojo. Si se respetan ambos estándares en simultáneo sin reasignación, el operador pierde lectura inmediata.

**Propuesta concreta de reasignación** (decisión final la toma quien implemente, idealmente con QA cromático sobre pantalla real):

| Concepto | Color propuesto | Token sugerido |
|---|---|---|
| LOCAL | Azul (heredado del estándar T1) | `--blue-local` (#2c6cb0 aprox.) |
| VISITA | Naranja-vino oscuro | `--orange-visita` (variante oscura de `--accent`) |
| SHADOW | Violeta neutro | `--violet-shadow` (#6b5b8a aprox.) |
| MODO DEFENSIVO | Rojo (`--red` actual de SPEC) | sin cambio |
| BANCA EN DRAWDOWN | Rojo (`--red` actual de SPEC) | sin cambio |

Razonamiento: SHADOW es un concepto **de auditoría** (no de localía), por lo que tolera bien un color terciario poco usado en el resto del dashboard. LOCAL/VISITA es lectura **de primer vistazo** y debe quedarse con los colores más reconocibles.

**Acción para implementación**: validar contraste WCAG AA del violeta sobre `--bg` antes de fijar el hex.

---

## Gap 3 — Tabs horizontales vs storytelling vertical de 5 niveles

**Estado en T2**: SPEC sección 4 (Jerarquía y navegación) propone **tabs horizontales** (Hoy / Histórico / Auditoría) como navegación principal.

**Estado en T1**: propone una **narrativa vertical** organizada en cinco niveles descendentes (identidad del partido → predicción → apuesta → detalles → auditoría) en una sola página, con scroll guiado.

**Veredicto**: **ambas formas son válidas**. La decisión queda a quien implemente, con la condición vinculante de que **se respeten los hard stops H1-H8 de la SPEC** (sección 2):

- Las strings exactas emitidas por el backend sobreviven a ambas formas de navegación (no se reformatean ni se traducen).
- La jerarquía de información (KPIs above-the-fold → clusters → rechazos → auditoría matemática) se preserva, ya sea distribuida en tabs o en secciones verticales.
- Los pipelines xG y de stake mantienen el orden y los nombres de etapa exactos.

**Recomendación blanda**: si el dashboard se usa principalmente en una pantalla amplia y con sesión de operación de 45-80 min/día (ver Gap 4), la narrativa vertical de T1 reduce carga cognitiva al eliminar cambios de contexto. Si se prevé uso multipantalla o consulta puntual, los tabs de T2 dan acceso aleatorio más rápido.

**No es bloqueante**.

---

## Gap 4 — Métrica de impacto: 45-80 min / día

**Aporte de T1**: cuantifica el costo operativo actual del flujo manual sobre Excel + visor en **45 a 80 minutos por día** de trabajo del operador.

**Uso recomendado**: justificación de priorización para el roadmap de implementación del dashboard operativo. Sirve como referencia para decidir el orden de cierre de los Gaps 1-3 y para evaluar el ROI de features adicionales fuera de scope de la SPEC.

**No requiere acción técnica** en esta fase.

---

## Cierre

T1 cerró su tarea (auditoría de fricciones). T2 cerró su tarea (mockups + SPEC + auditoría del visor de evals). Esta reconciliación queda como **insumo para la fase futura de implementación del `dashboard_operativo.html`**; **ningún teammate del refactor en curso la ejecuta**. Los docs firmados se mantienen intactos.

# PROPUESTAS_MATEMATICAS — propuestas consolidadas

**Autor**: team-lead (producido directo por bloqueo de `experto-deportivo` y `experto-apuestas`).
**Fecha**: 2026-04-17.
**Uso**: fuente de verdad para las propuestas que requieren autorización del usuario antes de implementar en código productivo.

**Contrato**: cada propuesta registra:
- **Estado**: PROPUESTA / APROBADA / IMPLEMENTADA / DESCARTADA.
- **Descripción técnica exacta**: qué líneas cambian, qué constantes se modifican.
- **Evidencia empírica**: números del repo.
- **Riesgos**: impacto colateral.
- **Prerequisitos**: qué tiene que pasar antes.

---

## Sección A — Propuestas de Calibración (experto-deportivo)

### P1 — Fix nombres stats ESPN (corners/totalShots)

**Estado**: APROBADA (usuario autorizó en el set de decisiones D7).
**Tipo**: bug de código, NO matemática (pero tiene efecto matemático).

**Descripción**:
- `motor_data.py` busca claves `'cornerKicks'` y `'shots'` en el payload de ESPN.
- ESPN real devuelve `'wonCorners'` y `'totalShots'`.
- Resultado actual: corners y shots_off son 0 en todos los partidos → fórmula híbrida se reduce de facto a `shotsOnTarget × 0.30`.

**Líneas exactas a modificar**: `src/ingesta/motor_data.py` líneas 75, 77, 98, 100, 397, 398 (6 cambios).

**Evidencia empírica**:
- 138/138 partidos liquidados tienen `corners_l=0`.
- `total_corners=0` en las 12 ligas de `ligas_stats`.
- `shotsOnTarget` SÍ matchea (por eso el sistema funciona, pero con input reducido).

**Riesgos**:
- Post-fix, los xG CAMBIAN materialmente (corners y shots_off ahora entran).
- Invalida todas las calibraciones actuales del manifiesto (Hallazgo G thresholds, Fix #5, FACTOR_CORR_XG_OU_POR_LIGA).
- **Requiere rebuild EMA obligatorio** después del fix.

**Prerequisitos**: B1 fix estado (para medir impacto limpio sobre los 201 liquidados).

**Implementación**: fase3 STEP 5 (antes del rebuild shadow).

---

### P2 — Recalibrar `FACTOR_CORR_XG_OU_POR_LIGA`

**Estado**: APROBADA (usuario autorizó F10 post-rebuild con N≥50).

**Descripción**:
Dict del manifiesto §II.E. Corrige el xG para el mercado O/U 2.5. Valores actuales vs empíricos medidos:

| Liga | N | Actual | Empírico (goles_real/xG_pred) | Delta |
|---|---|---|---|---|
| Argentina | 55 | 0.642 | 0.624 | -0.018 (OK) |
| Brasil | 52 | 0.603 | **0.547** | **-0.056** (sobrecalibrado) |
| Inglaterra | 19 | 0.627 (fallback) | **0.573** | -0.054 (N insuf) |
| Noruega | 24 | 0.524 | 0.535 | +0.011 (OK) |
| Turquía | 25 | 0.648 | **0.680** | +0.032 (sub-corregido) |

**Líneas**: `src/nucleo/motor_calculadora.py` dict `FACTOR_CORR_XG_OU_POR_LIGA`.

**Evidencia**: medido en consolidado de `experto-deportivo` pre-rebuild.

**Riesgos**: los ratios pre-rebuild pueden cambiar post-rebuild (porque los xG crudos cambian con corners arreglados). **NO calibrar con los valores de arriba** — volver a medir post-rebuild con N≥50.

**Prerequisitos**: P1 implementada + rebuild completo.

**Implementación**: fase3 STEP 9 (post-promoción).

---

### P3 — Validar Hallazgo G (prior local por liga)

**Estado**: APROBADA en diseño (usuario aprobó N=50 umbral en D5).

**Descripción**: Reglas_IA.txt §IV.H define prior local por liga, hoy INACTIVO porque ninguna liga tenía N≥50 liquidados con el bug del estado.

**Evidencia del gap local medido**:
- Global: freq_real_local = 48.76% vs freq_pred_local = 42.71% → modelo infraestima local **6pp**.
- Argentina específicamente: 52.73% real vs 40.89% pred → gap **11.8pp**.

**Líneas**: Reglas_IA.txt §IV.H — solo se ACTIVA, no se modifica. La lógica ya está implementada.

**Riesgos**: con Argentina y Brasil (N≥50 post-fix-estado) se activaría automáticamente. Puede cambiar probs materialmente.

**Prerequisitos**: B1 fix estado (para que los liquidados cuenten correctamente y pasen el umbral N=50).

**Implementación**: fase3 STEP 4 (automática post-B1).

---

### P4 — Recalibrar coeficientes `calcular_xg_hibrido`

**Estado**: PROPUESTA (BLOQUEADA por P1).

**Descripción**: Reglas_IA.txt §II.A define `Tiros_al_Arco*0.30 + Tiros_Fuera/Bloq*0.04 + Corners*Coef_Liga`. Los coeficientes 0.30 y 0.04 son globales; deberían validarse por liga post-fix.

**Razón bloqueo**: imposible medir hoy porque corners=0 y shots_off=0. Una vez que P1 esté implementada y haya datos nuevos, correr regresión OLS `goles_real ~ SoT + shots_off + corners` por liga.

**Prerequisitos**: P1 + rebuild + N≥50 liquidados post-rebuild.

**Implementación**: **fase 4 o posterior** (no en fase3 actual).

---

### P5 — `MARGEN_PREDICTIVO_1X2` por liga (con auto-fill)

**Estado**: APROBADA (usuario aprobó F9 con auto-implementación al agregar liga nueva).

**Descripción**: hacer la constante `MARGEN_PREDICTIVO_1X2 = 0.03` (global, §IV.A) configurable **por liga** en `config_motor_valores`.

**Justificación empírica**:
- Argentina: avg delta_xG = 0.13 (partidos parejos). Margen 0.03 raramente se supera.
- Inglaterra: delta_xG mayor, margen 0.03 es aceptable/estricto.

**Diseño**:
- Tabla `config_motor_valores` clave `margen_predictivo_1x2__<liga>`.
- Fallback: 0.03 (valor actual del manifiesto).
- **Auto-fill al agregar liga nueva**: insertar entrada con valor fallback automáticamente.
- Valores iniciales propuestos (a validar con backtest):
  - Argentina: 0.02
  - Inglaterra: 0.04
  - Resto: 0.03 (fallback)

**Líneas afectadas**:
- `src/comun/config_sistema.py` — remover constante hardcoded.
- `src/comun/config_motor.py` (nuevo) — `get_param('margen_predictivo_1x2', scope=liga, default=0.03)`.
- `src/nucleo/motor_calculadora.py` — llamada a `get_param` en lugar del literal.

**Riesgos**: bajar el margen en Argentina abre más picks marginales — validar con backtest antes.

**Prerequisitos**: `config_motor_valores` creada (T1 fase3).

**Implementación**: fase3 STEP 9 (post-promoción).

---

### P6 — EMA pre-partido lookahead-free

**Estado**: APROBADA en diseño (usuario autorizó F6: "diseñar y evaluar").

**Descripción**: la fórmula EMA bayesiana (§II.B) queda INTACTA. Lo único que cambia: al calcular un partido del 16/03, se lee el valor del EMA tal como estaba al 15/03 (sin incluir partidos posteriores).

**Justificación**: eliminar lookahead bias en backtest.

**Implementación propuesta**:
1. Verificar si `ema_procesados` (3599 filas) tiene el schema necesario para reconstruir "EMA al momento X".
2. Si no: crear tabla `ema_historico_por_fecha` con `(equipo, fecha, ema_xg_favor_home, ...)`.
3. Modificar el cálculo en backtest para leer el EMA pre-partido en lugar del actual.
4. Backtest comparativo: Brier con lookahead (actual) vs Brier lookahead-free. Esperado: Brier puede mejorar (modelo honesto) o empeorar (EMA actual es accidentalmente mejor predictor).

**Líneas afectadas** (cuando se implemente):
- Nueva tabla en DB.
- `src/nucleo/motor_calculadora.py` — modificar query de historial para filtrar por fecha.

**Riesgos**:
- NO cambia predicciones en vivo (en vivo ya es lookahead-free).
- Cambia toda la medición del backtest histórico → las calibraciones actuales fueron medidas CON lookahead bias.

**Prerequisitos**: `config_motor_valores` + evidencia empírica de mejora.

**Implementación**: fase3 STEP 10 SI el backtest comparativo muestra mejora >0% en Brier.

---

## Sección B — Propuestas de Apuestas (experto-apuestas)

### P-A1 — Subir `FLOOR_PROB_MIN` 0.33 → 0.40

**Estado**: APROBADA (usuario decidió F1).

**Descripción**: el piso de prob mínima para apostar sube. Camino 3 (alta convicción) MANTIENE 0.33 como excepción.

**Evidencia**: backtest muestra hit rate del bucket 33-40% = 29-33% (destructor). Subir floor esperado: yield +120%, hit 60%.

**Líneas**: `src/nucleo/motor_calculadora.py` constante `FLOOR_PROB_MIN`.

**Prerequisitos**: migrar a `config_motor_valores` como `floor_prob_min` + `floor_prob_min_camino3 = 0.33` override.

**Implementación**: fase3 STEP 4.

---

### P-A2 — Restringir Camino 2 al subset destructor + baja prioridad

**Estado**: APROBADA (usuario decidió F2b + orden de evaluación).

**Descripción**: Camino 2 (value hunting) se evalúa **ÚLTIMO**. Si Camino 1, 2B o 3 ya dispararon pick, Camino 2 no corre. Además, se CORTA cuando:
- Pick = VISITA (no LOCAL).
- prob entre 33-40%.
- Liga con sesgo xG_visita alto: Brasil, Inglaterra, Noruega, Turquía.

**Evidencia**: Camino 2 destructor n=24 hit 29% yield +10% vs el resto con hit 50+%.

**Líneas**: `src/nucleo/motor_calculadora.py` función `evaluar_mercado_1x2`.

**Riesgos**: el cambio en la lógica de Cuatro Caminos es DELICADO — requiere bit-a-bit audit de regresión con snapshot previo.

**Prerequisitos**: R6 auditoría completa + OK específico antes de tocar evaluar_mercado_1x2.

**Implementación**: fase3 STEP 4, con validación obligatoria.

---

### P-A3 — O/U 2.5 en modo shadow hasta post-rebuild

**Estado**: APROBADA (usuario decidió F3 Opción C).

**Descripción**: pausar apuestas LIVE en mercado O/U 2.5. Los picks O/U se siguen calculando y registrando como "shadow O/U" (sin stake real) para acumular N hasta post-rebuild.

**Evidencia**: O/U n=4 (D8) / n=8 (reporte apuestas) — N insuficiente. Yield mezclado.

**Líneas**: `src/nucleo/motor_calculadora.py` — introducir flag `APUESTA_OU_LIVE = False` (default), picks se escriben a `apuesta_shadow_ou` en lugar de `apuesta_ou`.

**Riesgos**: consume espacio de cálculo pero no plata real. Post-rebuild reactivar.

**Prerequisitos**: ninguno.

**Implementación**: fase3 STEP 4.

---

### P-A4 — `DELTA_STAKE_MULT_MED` 1.15 → 1.25 (backtest primero)

**Estado**: APROBADA pendiente backtest (usuario decidió F4 "probar offline, aplicar post-rebuild").

**Descripción**: multiplicador de stake para delta_xG medio (0.3-0.5) sube de 1.15 a 1.25.

**Validación previa obligatoria**: experto-apuestas corre backtest retrospectivo con 1.25 vs 1.15 sobre los 50 picks resueltos. Si yield mejora → aprobar.

**Líneas**: `src/nucleo/motor_calculadora.py` constante `DELTA_STAKE_MULT_MED`.

**Prerequisitos**: backtest retrospectivo en `docs/fase2/BACKTEST_DELTA_STAKE_125.md`.

**Implementación**: fase3 STEP 9 (post-promoción) SI el backtest pasa.

---

### P-A5 — `FACTOR_CORR_XG_OU_POR_LIGA` recalibrar con ratios empíricos

**Duplicada con P2**. Ver sección A.

---

### P-A6 — Subir `MARGEN_XG_OU_OVER` 0.30 → 0.40

**Estado**: SUPERSEDED por P-A3 (pausa shadow O/U). Si se reactiva post-rebuild, re-evaluar con nuevos xG.

---

### P-A7 — Monitorear Turquía VISITA

**Estado**: PROPUESTA (observación, no acción).

**Descripción**: Turquía tuvo 3/3 picks VISITA perdidos. Watchlist si el patrón continúa post-fixes.

**Implementación**: no es cambio de código, es política de monitoreo.

---

## Sección C — Resumen orden de implementación

| Fase3 STEP | Propuestas implementadas |
|---|---|
| STEP 4 | P-A1 (FLOOR 0.40), P-A2 (C2 restringido), P-A3 (O/U shadow) |
| STEP 5 | P1 (fix corners) → rebuild |
| STEP 9 | P3 (Hallazgo G auto-activa con N≥50), P2 (recalibrar FACTOR_CORR_OU con datos nuevos), P5 (margen predictivo por liga), P-A4 (DELTA_STAKE 1.25 si backtest pasa) |
| STEP 10 | P6 (EMA pre-partido) SI backtest comparativo aprueba |
| Fase 4+ | P4 (recalibrar coeficientes híbrido) |

---

## Sección D — Decisiones del usuario pendientes de registro

Todas las F1-F10 ya decididas (ver `PLAN.md` §2). Este archivo traza cómo se implementan.

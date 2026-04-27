# Plan ML Adaptativo — Adepor

## Contexto

Hoy el motor Adepor tiene componentes **adaptativos parciales** que requieren ejecución manual (rho calibration, EMA backfill, OLS xG). El objetivo: **automatizar** la adaptación al régimen-cambio y agregar **online learning** para que los pesos se ajusten partido a partido sin re-entrenamiento batch.

## Triple capa adaptativa

| Capa | Componente | Frecuencia | Trigger | Implementación |
|---|---|---|---|---|
| **L1: EMA + rho** | xG_v6 EMA legacy/shadow + rho_calculado | Por partido | Cada partido liquidado | Ya existe (motor_data + calibrar_rho.py). Falta cron diario. |
| **L2: V12 weights online** | LR multinomial (13 features → 3 clases) | Por partido | Cada partido liquidado | NUEVO: SGD step de tamaño constante sobre payload `lr_v12_weights`. |
| **L3: Drift detector** | Brier rolling 30 días por liga | Diario | Brier > baseline + 2σ | NUEVO: detecta degradación y dispara re-train batch. |

## L2: Online SGD para V12

### Algoritmo

Para cada partido liquidado en orden cronológico:

```
1. Predecir P_pre = softmax(W · x_std)  # snapshot pre-update (se persiste a shadow)
2. Observar y_real (one-hot 1/X/2)
3. Computar grad = (P_pre - y_real)^T × x_std + λ × W
4. Update: W ← W − lr × grad
5. Persistir W en config_motor_valores
```

### Parámetros

- `lr = 0.005` (10× más chico que batch GD para estabilidad)
- `λ = 0.1` (ridge, mismo que batch)
- `mean/std`: **frozen** del último entrenamiento batch — no se recalculan online (mantiene scale estable)
- Update solo si `partidos_acumulados >= 100` (warmup)

### Persistencia

Tabla nueva `online_sgd_log`:
```sql
CREATE TABLE online_sgd_log (
    fecha_log TEXT,
    bead_id TEXT,
    arch TEXT,                  -- 'v12_global', 'v12_<liga>'
    n_partidos_acum INTEGER,
    grad_norm REAL,             -- ||grad|| L2
    weight_norm REAL,           -- ||W|| L2
    brier_pre REAL,             -- Brier sobre el partido (pre-update)
    delta_weight REAL,          -- ||W_new - W_old||
    notes TEXT
);
```

Permite auditar la velocidad de cambio de los pesos.

### Trigger

- Hook en `motor_data.py` después de actualizar EMAs. Si el partido tiene stats raw + resultado real:
  - Computar features V12 con EMAs pre-update.
  - Aplicar SGD step.
  - Persistir W actualizado + log.

## L3: Drift detector

### Algoritmo

Diario (cron `bd schedule`):

```
1. Para cada liga + global:
   a. brier_rolling_30d = AVG(Brier ultimos 30 dias)
   b. brier_baseline = Brier in-sample del entrenamiento batch
   c. brier_2sigma = baseline + 2 * std(Brier_baseline)
2. Si brier_rolling_30d > brier_2sigma:
   a. Crear bead [PROPOSAL] re-entrenar V12 batch
   b. Notificar via bd remember (alerta visible en próxima sesión)
3. Si brier_rolling_30d < baseline (mejora): no-op (modelo siendo conservador)
```

### Persistencia

Tabla `drift_alerts`:
```sql
CREATE TABLE drift_alerts (
    fecha_deteccion TEXT,
    arch TEXT,
    liga TEXT,
    brier_rolling REAL,
    brier_baseline REAL,
    brier_2sigma REAL,
    severity TEXT,              -- 'warning' | 'critical'
    accion_sugerida TEXT,
    bead_creado TEXT            -- ID del bead PROPOSAL si severity = critical
);
```

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **SGD diverge** (lr alto) | lr clamp [0.001, 0.01]. Loss check post-step: si > pre × 1.5, revertir. |
| **Catastrophic forgetting** (peso drifta lejos del óptimo batch) | Anchor regularization: `λ_anchor × \|W − W_batch\|^2`. |
| **Sample bias** por liga | Updates SOLO sobre weights `lr_v12_weights[liga_partido]` o pool global. |
| **Drift falso positivo** (período corto malo) | Min N=30 partidos en ventana antes de alertar. Min días=14. |
| **Gradient noise alto** | Mini-batch de 5 partidos antes de update (no SGD puro). |

## Roadmap

| Fase | Entregable | Esfuerzo |
|---|---|---|
| **F1** | Tabla `online_sgd_log` + script `online_sgd_step.py` standalone para testing | 1 sesión |
| **F2** | Hook en motor_data.py + integración con flujo diario | 1 sesión |
| **F3** | Tabla `drift_alerts` + script `drift_detector.py` con cron diario | 1 sesión |
| **F4** | Backtest comparativo: V12 batch vs V12 online sobre walk-forward | 1 sesión |
| **F5** | Si F4 muestra mejora: PROPOSAL Manifesto V12 online activo | bead |

## Justificación

Sin features nuevos (alineaciones, lesiones), el ML adaptativo da ganancia esperada **moderada**: +0.5–1pp hit por captura de régimen-cambio. NO compensa la barrera de Cohen's d <0.13 en empates.

**Vale la pena si**:
- El régimen cambia más rápido que la frecuencia de re-train batch (típicamente trimestral).
- Hay ligas nuevas con muestras chicas (online aprende más rápido que batch frío).

**NO vale la pena si**:
- El batch monthly + recalibración rho mensual ya captura el drift.

## Decisión

Implementar F1+F2 como **prototipo experimental sobre V12 SHADOW** — los updates online afectan solo el shadow log, no los argmax productivos. Si F4 muestra mejora consistente OOS, escalar.

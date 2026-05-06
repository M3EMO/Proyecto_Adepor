# Walk-forward paradigmas — Schema A, Schema B, TRUE-OOS

**Define:** las 3 estrategias de validación cronológica usadas en el proyecto, cuándo usar cada una, y sus garantías estadísticas.

---

## Schema A — Train-all, evaluar-each-year

**Descripción:** entrenar/calibrar con TODOS los datos disponibles. Evaluar sobre cada año individualmente.

**Pseudocódigo:**
```python
filtro = optimizar_filtro(bets_todos_los_anios)
yield_2022 = aplicar_filtro_y_evaluar(filtro, bets[year=2022])
yield_2023 = aplicar_filtro_y_evaluar(filtro, bets[year=2023])
...
yield_IS_pool = aplicar_filtro_y_evaluar(filtro, bets_todos_los_anios)
```

**Garantías:** ninguna OOS estricta. La optimización ve todos los años → riesgo overfit alto.

**Cuándo usar:**
- Análisis exploratorio inicial.
- Identificar yield IS pool de un filtro.
- Verificar consistencia cross-año (años positivos / total).

**Cuándo NO usar:**
- Para promover a producción.
- Para reportar yield esperado real.

---

## Schema B — Leave-One-Year-Out (LOYO)

**Descripción:** entrenar con cada año individualmente, evaluar sobre el resto.

**Pseudocódigo:**
```python
for year_train in YEARS:
    bets_train = bets[year == year_train]
    bets_test  = bets[year != year_train]
    filtro = optimizar_filtro(bets_train)
    yield_oos = aplicar_filtro_y_evaluar(filtro, bets_test)
    record(year_train=year_train, yield_oos=yield_oos)
```

**Garantías:** OOS estricta del año test (no se usó para entrenar). Pero hay leakage temporal: train 2022 evalúa en 2023+ (futuro respecto al train) y también en 2024+, 2025+ (futuro lejano).

**Cuándo usar:**
- Validar consistencia del filtro: ¿se mantiene cuando NO se entrenó con ese año?
- Identificar one-shots (yield IS bonito pero LOYO colapsa).

**Cuándo NO usar:**
- Para promover a producción sin holdout adicional.

**Métricas reportadas:**
- yield avg OOS (ponderado por N_oos cada fold)
- consistencia: # folds con yield_oos > 0 / total folds

---

## Schema TRUE-OOS estricto

**Descripción:** train con datos antiguos, validation para tunear, holdout congelado para evaluación final.

**Splits típicos:**
```
TRAIN:   year ≤ 2024
VALID:   year == 2025
HOLDOUT: year == 2026  (CONGELADO — no tocar durante diseño)
```

**Pseudocódigo:**
```python
# Fase 1: descubrimiento
filtro_candidato = optimizar_filtro(bets[year <= 2024])

# Fase 2: tunear (opcional, si parámetros libres)
filtro_tuneado = ajustar(filtro_candidato, bets[year == 2025])

# Fase 3: evaluación FINAL en holdout
yield_holdout = aplicar_filtro_y_evaluar(filtro_tuneado, bets[year == 2026])
```

**Garantías:** OOS verdadero. Holdout 2026 NO se ve hasta evaluación final → no overfit posible.

**Cuándo usar:**
- Promoción a SHADOW MODE.
- Validación final pre-producción.
- Cualquier propuesta de cambio al motor.

**Reglas de promoción (acumulativas, todas obligatorias):**
- Yield IS pool train ≥ +5%
- Bootstrap percentile 5 > 0
- ≥ 50% años train con yield > 0 (consistencia)
- Yield holdout 2026 confirma direccionalidad (>0 OR N<10 no concluyente)
- N ≥ 100 (50 si N_oos limitado)

**Reglas de VETO:**
- Yield holdout 2026 negativo significativo (CI95% < 0)
- One-shot (1 año bueno + 3 malos)
- Selection bias: filtro descubierto SOBRE el holdout

---

## IS=2026 paradigma (variante reciente)

**Descripción:** invertir IS/OOS — usar 2026 (más reciente) como referencia y 2022-2025 como OOS retrospectivo.

**Razonamiento:** 2026 representa el régimen actual del mercado. Si un filtro funciona en 2026 pero no en 2022-2024, el régimen cambió → no production-ready.

**Pseudocódigo:**
```python
RMSE_IS_2026 = calc_rmse(predicciones[year == 2026])
RMSE_OOS_pool = calc_rmse(predicciones[year ∈ 2022, 2023, 2024, 2025])
RMSE_2022 = calc_rmse(predicciones[year == 2022])
RMSE_2023, RMSE_2024, RMSE_2025 idem
```

**Cuándo usar:**
- Validación del motor xG cuando el régimen 2026 importa más que histórico.
- Detectar régimen shifts (gran diferencia entre `RMSE_IS_2026` y `RMSE_OOS_pool`).

---

## Tabla resumen — qué paradigma usar cuándo

| Objetivo | Paradigma | Garantía |
|---|---|---|
| Exploración inicial | Schema A | ninguna |
| Identificar one-shots | Schema B (LOYO) | OOS marginal |
| Promoción producción | TRUE-OOS holdout congelado | OOS estricta |
| Validar régimen actual | IS=2026 | revela shifts |
| Validar motor xG global | RMSE forward-EMA en 2 paradigmas | doble check |

---

## Anti-overfit obligatorio en cualquier paradigma

- Bonferroni si se prueban N hipótesis: α = 0.05 / N
- Bootstrap percentile CI95%: percentile 5 > 0 requerido
- DOF / N ratio ≥ 10:1 (idealmente 25:1)
- Documentar todas las hipótesis probadas (no solo la ganadora)

Ver `docs/definiciones/bonferroni_y_bootstrap.md`.

---

## Documentación relacionada

- `docs/definiciones/rmse_forward_ema.md` — métrica para validar motor
- `docs/definiciones/divergencia_modelo_mercado.md` — métrica para filtros
- `docs/papers/walk_forward_true_oos_5_propuestas.md` — ejemplo aplicado

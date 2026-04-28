# Caracterización de regímenes 2022/2023/2024 — Fase 1 predictor

> Bead: `adepor-bix` (Fase 1 del plan predictor de régimen híbrido)
> Sample: `partidos_historico_externo` N=12,283 (3 temps × 16 ligas)
> Output: `analisis/regimen_caracterizacion.{py,json}`

## Resumen ejecutivo (hallazgo crítico)

**El régimen 2023 NO se distingue por features estructurales del partido.** De 15 features
testeadas (frecuenciales, estilísticas, calibración, mercado), **solo `yield_v0_unitario`
separa 2023 con significancia estadística (p=0.0336, t=−2.12)**.

**Implicación:** el "régimen tóxico 2023" no es predecible desde la estructura del juego.
Es un **mismatch interno del motor** entre expectativas calibradas (2022) y realidad
(2023). Esto cambia el plan de predictor de régimen: pasa de "predictor proactivo
basado en features del partido" a "**detector retrospectivo basado en métricas del motor**".

## Tabla agregada por temporada (todas las ligas)

| temp | N | avg_g | %LW | %X | %VW | %R | BS_v0 | Y_v0% | vig% | edge |
|---|---|---|---|---|---|---|---|---|---|---|
| 2022 | 4145 | 2.61 | 45.2% | 26.1% | 28.7% | 0.210 | 0.637 | **+9.82%** | 2.69 | 0.280 |
| 2023 | 4308 | 2.67 | 45.6% | 27.1% | 27.3% | 0.193 | 0.629 | **−4.40%** | 2.98 | 0.257 |
| 2024 | 3830 | 2.65 | 44.5% | 25.9% | 29.6% | 0.190 | 0.620 | **+0.12%** | 3.30 | 0.263 |

Patrón visible:
- Yield V0 cae 2022 → 2023 (−14.2pp) y se recupera parcialmente 2023 → 2024 (+4.5pp)
- Brier V0 mejora monotónicamente (cae de 0.637 → 0.620): el motor se vuelve
  **mejor calibrado pero menos rentable** entre 2022 y 2024 (replica del paradox
  Brier↔Yield ya documentado).
- Vig Pinnacle SUBE año tras año (2.69 → 2.98 → 3.30) — el bookie ajusta más fino,
  reduce edge del apostador.
- Avg goles, pct empates, corners, yellow, red **estables** cross-temp.

## Welch t-test: 2023 vs (2022+2024)

Se evaluó cada feature como (liga, temp) tuple, resultando en N≈8 puntos por grupo.
P-values aprox via normal (df grande).

| Feature | t | p_aprox | Sig | 2023 mean | 22+24 mean |
|---|---|---|---|---|---|
| **yield_v0_unitario** | **−2.124** | **0.0336** | ★★ | −8.83% | +7.90% |
| pct_visita_win | −1.264 | 0.21 | — | 26.6% | 28.6% |
| edge_motor_avg | −1.171 | 0.24 | — | 0.256 | 0.270 |
| avg_yellow_partido | +0.877 | 0.38 | — | 4.28 | 4.12 |
| pct_empate | +0.875 | 0.38 | — | 27.3% | 26.2% |
| avg_goles_total | +0.470 | 0.64 | — | 2.66 | 2.61 |
| pct_local_win | +0.482 | 0.63 | — | 46.1% | 45.2% |
| home_advantage | +0.482 | 0.63 | — | 0.011 | 0.002 |
| avg_corners_partido | +0.095 | 0.92 | — | 6.50 | 6.36 |
| avg_shots_partido | +0.136 | 0.89 | — | 17.16 | 16.63 |
| avg_sots_partido | +0.134 | 0.89 | — | 5.90 | 5.72 |
| avg_red_partido | −0.257 | 0.80 | — | 0.194 | 0.200 |
| avg_fouls_partido | +0.256 | 0.80 | — | 24.0 | 23.8 |
| brier_v0_avg | +0.060 | 0.95 | — | 0.629 | 0.629 |
| pinnacle_vig_avg | −0.246 | 0.81 | — | 2.99% | 3.02% |

## Heterogeneidad por liga × temp

Algunas ligas SÍ muestran perfil 2023 distinto en yield:

| Liga | Y22 | Y23 | Y24 | Δ23 vs (22,24) |
|---|---|---|---|---|
| **España** | +17.2% | **−34.0%** | −40.4% | España colapsa 22→23 (−51pp) y se mantiene mal. |
| Italia | +9.5% | −23.3% | −6.0% | Italia 23 mucho peor que vecinos |
| Inglaterra | +31.5% | −4.9% | +5.4% | England 23 cae fuerte vs 22 (+31), recupera 24 |
| Francia | +67.7% | −3.6% | +13.1% | Francia 22 explosivo, 23 cero |
| Argentina | +10.0% | +9.8% | +21.6% | Argentina ESTABLE — no regimen toxico aqui |
| Brasil | −9.8% | +8.5% | −13.7% | Brasil INVERTIDO — 23 fue su mejor año |
| Turquía | −6.8% | −14.0% | +19.1% | Turkey: 24 explosivo |

**Nota crítica:** Argentina y Brasil NO muestran patrón "régimen tóxico 2023".
Argentina yield estable (+10/+10/+22), Brasil incluso mejora en 2023 (+8.5%).
**El "régimen tóxico" es un fenómeno principalmente EUR mid-tier
(Esp/Ita/Ing/Fra), no global.**

## Conclusiones

### 1. El régimen 2023 es invisible en features del partido

Las medias de avg_goles, % empates, corners, yellow, red, etc. son **estadísticamente
idénticas** cross-temp (todos los p > 0.20). El partido de fútbol "se ve igual" en
2022 que en 2023.

### 2. El régimen 2023 ES detectable en métricas del motor

El yield V0 cae significativamente. La diferencia es entre **prob_modelo** y
**prob_implícita_pinnacle** (edge_motor) — direccionalmente baja en 2023 (0.256 vs
0.270) aunque no sig estadísticamente con N=8.

### 3. El "régimen tóxico" es heterogéneo por liga

- Esp/Ita/Ing/Fra colapsan 23 vs 22.
- Argentina/Brasil inmunes.
- LATAM (Bolivia/Chile/Colombia/Ecuador/Peru/Uruguay/Venezuela) sin OOS, no medible.

Esto sugiere que el "predictor de régimen" debe ser **per-liga, no global**.

## Implicaciones para Fase 2 (clasificador entrenado)

### Plan original revisado

**Lo que NO funciona (descartado):**
- Predictor proactivo basado en features del partido (avg_goles, % empates, etc.).
  No hay señal estadística suficiente.

**Lo que SÍ es factible:**

#### Opción A — Detector retrospectivo basado en métricas del motor

Trigger por liga (rolling 30/60d):
```
Si yield_rolling(liga) < umbral_baseline_liga - 2σ por 14+ días:
  → Estado: REGIMEN_TOXICO(liga)
  → Aplicar políticas adaptativas (Kelly cap reducido, V5.1 más restrictivo)
```

Esto NO predice el régimen — lo **detecta una vez establecido**. Lag típico ≈ 2-4 semanas.

#### Opción B — Clasificador per-liga sobre serie temporal

Train un clasificador (LR/RF) que, **dado las últimas K métricas del motor en una liga**, prediga si la liga está en régimen tóxico:

```
Features rolling (ventana K = 30 picks últimos en liga):
  brier_motor_rolling_k
  yield_motor_rolling_k
  edge_motor_avg_rolling_k
  ratio_pretest_to_live_k
  std_brier_rolling_k

Label: yield_próximos_K_picks_post-cutoff > 0
```

Esto es predicción CONDICIONADA al estado actual del motor, no al futuro estructural.

#### Opción C — Bayesian online updating

Cada pick liquidado actualiza un prior sobre el "régimen actual de la liga":
```
P(régimen=tóxico | datos_liquidados) ∝ P(datos|tóxico) × P(tóxico)
```

Más sofisticado pero requiere implementación cuidadosa.

### Recomendación

**Opción A** (detector retrospectivo) es la más simple y ya parcialmente implementada
en `motor_adaptativo.py` (drift_alerts vía Brier rolling). Puede extenderse a yield
rolling en una sola sesión cuando el trigger N≥600 se cumpla.

**Opción B** (clasificador entrenado) requiere más data pero da mejor pronóstico
(con CI). Es el siguiente paso lógico tras Opción A.

## Próximos pasos

- [x] Fase 1 ejecutada y documentada
- [x] Hallazgo crítico identificado: features estructurales no separan régimen
- [ ] Cuando N≥600 in-sample post-2026-03-16: implementar Opción A en `adepor-09s`
- [ ] Si Opción A funciona, evaluar Opción B (clasificador) como upgrade
- [ ] Política adaptativa per-liga: PROPOSAL: MANIFESTO CHANGE post-validación

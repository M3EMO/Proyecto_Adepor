# xG model derivado del shotmap SofaScore — metodología

**Fecha:** 2026-05-03
**Branch:** `experimentos`
**Script:** `analisis/motor_xg_v2_14_xg_from_shotmap.py`
**Output:** `analisis/motor_xg_v2_14_xg_from_shotmap.json` + `config_motor_valores.xg_model_coefs_v2`

---

## TL;DR

Reconstruimos un xG model interno a partir del **shotmap** que SofaScore expone por partido (sin field xG explícito, pero con coordenadas + situación + body part). Approach: regresión logística sobre features geométricas, validada con 5-fold CV. Coefs persistidos para reaplicar en backfill posteriores sin re-entrenar.

**Por qué interno**: SofaScore NO expone `xg` directo en `/event/{id}/shotmap`. Solo coordenadas + metadata. Pero esos campos son **suficientes** para reconstruir un xG model (lo que hace cualquier modelo open-source: Caley-Maye 2015, Statsbomb-internal pre-2020, Wyscout).

---

## Datos input por shot

Endpoint: `https://api.sofascore.com/api/v1/event/{eid}/shotmap`

Cada shot expone:

```json
{
  "id": 7111901,
  "incidentType": "shot",
  "isHome": false,
  "playerCoordinates": {"x": 13.2, "y": 61.5, "z": 0},
  "goalMouthCoordinates": {"x": 0, "y": 50, "z": 23.4},
  "goalMouthLocation": "high-centre",
  "blockCoordinates": {"x": 3.3, "y": 54, "z": 0},
  "bodyPart": "right-foot",
  "situation": "assisted",
  "shotType": "save",
  "time": 90,
  "addedTime": 2,
  "player": { "name": "...", "id": ... },
  "goalkeeper": { "name": "...", "id": ... }
}
```

Campos clave:
- `playerCoordinates.x, .y` — desde dónde shoteó (% cancha 0-100)
- `bodyPart` — right-foot / left-foot / head / unknown
- `situation` — penalty / set-piece / corner / fast-break / assisted / regular-play
- `shotType` — goal / save / miss / post / block (target = `goal`)

---

## Verificación empírica de coordenadas

Las coordenadas SofaScore son ambiguas en docs. **Verificación**: comparar `mean(playerCoordinates.x)` para shots `goal` vs `no-goal`.

```
Hipótesis: x BAJO = cerca arco contrario
  → goles deberían tener x más bajo que no-goles
  → si confirmado, distance_to_goal = sqrt(x² + (y-50)²)
```

El script imprime las medias y elige orientación automáticamente.

---

## Features extraídas

| Feature | Cálculo | Interpretación |
|---|---|---|
| `distance` | `sqrt(x_m² + y_m²)` con conversión a metros (105×68) | distancia euclidiana al centro del arco |
| `angle` | `atan2(W·x, x²+y²-(W/2)²)` con W=7.32m | ángulo subtendido por el arco (Caley 2015) |
| `inv_distance_sq` | `1/distance²` | decay físico de prob (Statsbomb) |
| `is_inside_box` | `distance < 16.5m` | dentro área grande |
| `body_head` | bool | shots de cabeza son ~50% xG penalty |
| `body_left_foot` | bool | si jugador zurdo distinto al pie default |
| `body_other` | bool | unknown / out-of-distribution |
| `sit_penalty` | bool | xG ≈ 0.76 |
| `sit_set_piece` | bool | xG ≈ 0.06 (penalty area) |
| `sit_corner` | bool | xG ≈ 0.04 |
| `sit_fast_break` | bool | xG ≈ 0.15 |
| `sit_assisted` | bool | xG ≈ 0.12 |

---

## Modelo

**Logistic Regression** con features estandarizados (z-score):

```
P(goal=1) = sigmoid(β₀ + β·X_scaled)
```

Hyperparams:
- C=1.0 (regularización L2 default)
- max_iter=500
- solver=lbfgs

Por qué LogReg y no XGBoost:
1. **Interpretable** — coefs directos
2. **Bajo riesgo overfit** con N moderado (DOF ≈ 12 << N_shots)
3. **Computacionalmente estable** — refit posterior es cheap

Para xG production-grade en Statsbomb/Wyscout usan tree-based models (CatBoost / Wyscout LGBM). Pero ese complexity gain es marginal sobre LogReg cuando los features son los mismos. Prefiero simple + interpretable acá.

---

## Validación 5-fold CV

Reportamos:
- **Brier score** (esperado ~0.08-0.10 para xG models calibrados)
- **Log-loss** con clipping eps=1e-15
- Mean ± std cross folds

Si Brier > 0.12 → modelo subajustado. Si <0.05 → sospechoso (probable leakage).

---

## Aplicación por partido

Para cada partido:

```
xG_local = Σ P(goal | shot_i) sobre shots_i con isHome=True
xG_visita = Σ P(goal | shot_i) sobre shots_i con isHome=False
```

Persistido en `sofascore_match_features.xg_shotmap_l` y `.xg_shotmap_v`.

---

## Persistencia coefs

Para re-aplicar en backfill posteriores sin entrenar:

```sql
INSERT INTO config_motor_valores
  (clave, scope, valor_texto, tipo, fuente)
VALUES
  ('xg_model_coefs_v2', 'global', '<JSON con coefs+scaler+features>',
   'json', 'motor_xg_v2_14_xg_from_shotmap.py')
```

Estructura JSON:

```json
{
  "orientation": "low_x_near_goal",
  "n_shots": 5421,
  "n_goals": 542,
  "pct_goals": 0.10,
  "cv5_brier_mean": 0.085,
  "cv5_brier_std": 0.003,
  "coefs": {"distance": -0.42, "angle": +0.31, ...},
  "intercept": -2.18,
  "feature_names": ["distance", "angle", ...],
  "scaler_mean": [...],
  "scaler_scale": [...]
}
```

---

## Limitaciones conocidas

1. **No incluye `goalMouthCoordinates`** (z) — la altura a la que va el shot. Statsbomb usa esto para shots aéreos. Posible mejora futura.
2. **No considera `goalkeeper.position`** — habilidad del portero rival. Sería refinar a "expected xG vs portero específico".
3. **`situation` es coarse** — no distingue "header desde corner" vs "header en jugada". Statsbomb tiene 28 situaciones, SofaScore tiene 5-6.
4. **No considera presión defensiva** — shots con marcaje vs sin marcaje. Requiere event-level data (no disponible).
5. **No considera tipo de pase asistente** — pass through vs pase corto vs corner. El campo `assisted` es booleano sin profundidad.

**Implicación**: nuestro xG model será **menos preciso** que Statsbomb / Opta enterprise. Esperamos Brier ~0.09-0.10 (vs ~0.07 enterprise). PERO mejora claramente sobre `xg_calc = β·SOT + 0.010·shots_off` que no usa coordenadas.

---

## Comparación con xG model actual del proyecto

| Aspecto | V0 motor productivo | xG_shotmap (este model) |
|---|---|---|
| Input | SOT + shots_off + corners (counts agregados por equipo) | shot-level coordenadas + situación |
| Granularidad | partido | shot |
| Posición del shot | NO sabe | SÍ (x,y exacto) |
| Body part | NO sabe | head/foot |
| Situation | NO sabe | penalty/set-piece/etc. |
| Brier esperado | n/a (no es modelo proba) | ~0.085 |
| Coefs | β_sot per liga (post-OLS) | LogReg shot-level |

**Si xG_shotmap aporta** sobre baseline en Bayesian hierarchical → motor xG v2 promueve a SHADOW.

---

## Documentación relacionada

- `analisis/motor_xg_v2_14_xg_from_shotmap.py` — script implementación
- `docs/papers/research_fuentes_features_premarch.md` — research SofaScore
- `docs/papers/sofascore_anti_bot_strategy.md` — anti-bot guide
- `docs/papers/motor_xg_v2_propuesta.md` — propuesta consolidada motor v2

## Referencias académicas

- Caley & Maye (2015): "A Better Way to Quantify Soccer Performance" — xG geometric formula
- Sumpter (2017): "Soccermatics: Mathematical Adventures in the Beautiful Game" — xG fundamentals
- Statsbomb Open Data — public xG model coefficients
- Lucey et al. (2014): "Quality vs Quantity: Improved Shot Prediction in Soccer using Strategic Features" — 91% feature importance to body+coords

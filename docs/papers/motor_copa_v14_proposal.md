# PROPOSAL Motor Copa V14 — Ensemble xG + Elo Logistic Regression

> **Bead:** `adepor-141`
> **Fecha:** 2026-04-28
> **Process gate:** fundamentación académica obligatoria.

---

## 1. Investigación académica fundante

### Hallazgos consolidados

**Hvattum & Arntzen (2010)** — pionero ELO en regresión logística ordenada para fútbol. ELO como covariate. Predictive accuracy 52.4% standalone — alineado con Adepor Elo 49.5% global (gap 3pp explicable por canonicalización + cobertura).

**Berrar et al. — pi-ratings + CatBoost (2019)**:
- pi-ratings: extensión de ELO con momentum + form. Datos públicos open challenge.
- CatBoost + pi-ratings: 55.82% accuracy, RPS 0.1925.
- Vence Random Forest, XGBoost, redes neuronales en este dataset.

**Logistic regression como baseline interpretable** ([Spotintelligence 2023](https://spotintelligence.com/2023/07/10/name-matching-algorithm/), [SignalOdds](https://signalodds.com/blog/harnessing-logistic-regression-models-for-smart-sports-betting)):
- Interpretable (coeficientes muestran peso de cada feature).
- Calibration via Brier (RPS).
- Fellegi-Sunter framework aplicable a multinomial 1X2.

**xG + Elo combination**:
- Cattelan et al. (2013): dynamic Bradley-Terry-EWMA.
- xG calibration: paper publicado ~0.08 Brier (alta calidad).
- Para 1X2: Brier baseline aleatoria 0.25, BLR puede llegar a 0.18-0.20.

### Implicación arquitectónica

Adoptar **ensemble lineal interpretable** como V14 inicial:
- Features lineales: xG, delta_elo, dummies competicion_formato
- Regresión logística multinomial 1X2 con L2
- Ventaja: interpretable, calibrable, puede beneficiarse de online updates (paralela a V12 SGD)

Mejoras futuras escalonadas (post-V14):
- pi-ratings (extensión Elo con momentum)
- CatBoost gradient boosting (literatura best-in-class)

### Fuentes

- [Hvattum & Arntzen (2010) — Using ELO ratings for match result prediction](https://www.sciencedirect.com/science/article/abs/pii/S0169207009001708)
- [arXiv 2403.07669 — Machine Learning for Soccer Match Result Prediction (chapter)](https://arxiv.org/pdf/2403.07669)
- [arXiv 2211.15734 — Predicting Football Match Outcomes with eXplainable ML](https://arxiv.org/pdf/2211.15734)
- [Springer / Journal of Big Data — Data-driven prediction of soccer outcomes (2024)](https://link.springer.com/article/10.1186/s40537-024-01008-2)
- [SignalOdds — Logistic Regression for Sports Betting](https://signalodds.com/blog/harnessing-logistic-regression-models-for-smart-sports-betting)
- [The xG Football Club (Substack) — Which ML Models Perform Best](https://thexgfootballclub.substack.com/p/which-machine-learning-models-perform)

---

## 2. Diseño V14

### Features (entrenamiento)

| Feature | Origen | Tipo | Justificación |
|---|---|---|---|
| `xg_l` | `_get_xg_v6_para_partido` (V6 SHADOW) | float | xG local pre-partido |
| `xg_v` | idem | float | xG visita pre-partido |
| `delta_xg` | xg_l - xg_v | float | Polarización ofensiva |
| `elo_l_pre` | `equipo_nivel_elo` lookup | float | Rating local pre-partido |
| `elo_v_pre` | idem | float | Rating visita pre-partido |
| `delta_elo` | elo_l_pre - elo_v_pre + HOME_ADV(100) | float | **Robusto al bias** ClubElo |
| `competicion_formato_dummies` | partidos_no_liga.competicion_formato | one-hot | grupo/knockout_single/knockout_two_leg |
| `n_partidos_l` | equipo_nivel_elo.n_partidos_acumulados | int | Cold-start indicator (Tandfonline 2025) |
| `n_partidos_v` | idem | int | Idem |
| `agg_local_pre` | partidos_no_liga.agregado_local_pre | int (NULL→0) | Ventaja ida en 2-legs |
| `agg_visita_pre` | idem | int | Idem |

**Target:** outcome 1X2 (categórico → multinomial logistic).

### Modelo

```python
from sklearn.linear_model import LogisticRegression
import numpy as np

# Train: copa partidos liquidados 2022-2024 OOS
# Test: 2025 OOS
# Validation hold-out: 2026 in-sample (rare check)

X_train, y_train = build_features(train_set)
X_test, y_test = build_features(test_set)

model = LogisticRegression(
    multi_class='multinomial',
    solver='lbfgs',
    C=1.0,         # L2 regularization (1/lambda)
    max_iter=1000,
)
model.fit(X_train, y_train)

# Probas 1X2
probs = model.predict_proba(X_test)  # shape (N, 3)

# Brier score 1X2
brier = ((probs - one_hot(y_test)) ** 2).mean()
```

### Métricas y aceptación

| Criterio | Threshold | Comentario |
|---|---|---|
| **Brier copa OOS 2025** < min(Brier_V0, Brier_Elo_solo) | -0.005 absoluto | V14 debe dominar. |
| Hit rate ≥ V0 - 1pp | tolerancia | Brier es métrica primaria. |
| Coeficientes con sign correcto | β(delta_elo) > 0, β(delta_xg) > 0 | Sanity check. |
| N partidos test ≥ 200 | bound CI95 | sin esto, no estadísticamente significativo. |

### Aceptación PROPOSAL [MANIFESTO CHANGE]

V14 reemplaza V0 SOLO en partidos de `partidos_no_liga` (no en liga regular).
Activación gradual via `arch_decision_per_competicion = {"Champions League": "V14", ...}` (paralelo a V5.0 §L Layer 2).

---

## 3. Roadmap implementación

### Fase 1 (próxima sesión): Calibración + backtest

```
scripts/calibrar_motor_copa_v14.py:
  1. Cargar partidos copa liquidados 2022-2024 (train) + 2025 (test).
  2. Build feature matrix con helpers existentes.
  3. Train LogisticRegression multinomial.
  4. Persist coefs en config_motor_valores.lr_v14_weights (JSON).
  5. Reportar Brier train/test + coeficientes.
  6. A/B: Brier V0 raw, Elo solo, V12, V14.
```

### Fase 2: integración SHADOW

```
src/nucleo/motor_calculadora.py:
  Hook _calcular_probs_v14 dentro del bloque V12 existente.
  Loggear a picks_shadow_arquitecturas con shadow_label='V14'.
  NO afecta picks productivos hasta promoción explícita.
```

### Fase 3: PROPOSAL [MANIFESTO CHANGE]

```
Bead adepor-141 update con:
- Brier OOS 2025 evidence
- Yield contrafáctico V14 vs V0 sobre subset copa con cuotas
- Snapshot DB pre-cambio
- Diff de Reglas_IA.txt §M (motor copa per-competicion)
```

---

## 4. Riesgo conocido

1. **Bias Elo Adepor** (descubierto en cross-validation ClubElo):
   - Mitigación: usar `delta_elo` no absoluto. Bias se cancela en diferencia.
   - Sub-bead `adepor-recalibrar-K` para fix raíz.

2. **Cobertura partidos_no_liga limitada**:
   - 8,952 partidos pre-ESPN scraping → 9,391 post (8,952 + 439 nuevos).
   - Algunos países sin liga_home resuelta (79% NULL en partidos_no_liga.liga_local).
   - Mitigación: model trained on subset con liga_home conocida.

3. **Sample chico copa knockout**:
   - 282 two-leg + 4,658 single OOS 2022-2024.
   - Train/test split require N≥1000 train + N≥200 test.

---

## 5. Estado pendiente para PROPOSAL final

- [ ] Implementar `calibrar_motor_copa_v14.py`
- [ ] Backtest Brier + RPS V14 vs V0 vs Elo solo sobre 2025 OOS
- [ ] Documentar coeficientes + interpretación (delta_elo coef alto = funciona)
- [ ] Comparar accuracy con literatura (~55% baseline para ML buenos)
- [ ] Bead adepor-141 actualizado con evidencia + decisión de promoción

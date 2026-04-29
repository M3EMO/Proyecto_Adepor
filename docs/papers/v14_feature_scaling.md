# Papers: V14 feature scaling (StandardScaler en LR multinomial 1X2)

> **Fecha:** 2026-04-29
> **Pregunta de investigación:** ¿Es necesario aplicar StandardScaler antes de
> `LogisticRegression(penalty='l2', C=1.0)` cuando las features tienen escalas
> dispares (xG ∈ [0,4], delta_elo ∈ [-500,+500], dummies ∈ {0,1})?
> **Sources:**
>
> - Semantic Scholar via `scripts/research/buscar_papers.py` (rate-limited → fallback arXiv)
> - sklearn 1.8 documentation (oficial)
> - WebSearch sklearn LogisticRegression L2 + StandardScaler

---

## Hallazgos clave

### 1. sklearn `Preprocessing data §7.3` (fuente oficial)

> "Many elements used in the objective function of a learning algorithm (such as the
> RBF kernel of Support Vector Machines or **the l1 and l2 regularizers of linear
> models**) may assume that all features are centered around zero or have variance
> in the same order. **If a feature has a variance that is orders of magnitude
> larger than others, it might dominate the objective function** and make the
> estimator unable to learn from other features correctly as expected."
>
> Source: https://scikit-learn.org/stable/modules/preprocessing.html (§7.3)

> "For solvers like 'sag' and 'saga', fast convergence is only guaranteed on
> features with approximately the same scale, **and you can preprocess the data
> with a scaler from sklearn.preprocessing**."
>
> Source: https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html

**Aplicación al caso V14:**

| Feature | Rango observado | Std aprox | Comentario |
|---|---|---|---|
| `xg_l`, `xg_v` | [0.0, 4.0] | ~0.6 | natural xG |
| `delta_xg` | [-3.5, +3.5] | ~0.9 | derived |
| `delta_elo` | [-500, +500] | ~120 | **massive** |
| `d_copa_int`, `d_copa_nac` | {0,1} | ~0.5 | dummy |
| `log1p(n_l+n_v)` | [0, 7] | ~1.2 | log-scaled |

`delta_elo` tiene std ~200x mayor que xG. Con L2 (C=1), el penalty `||w||₂²` lo
empuja fuerte hacia 0 — confirmado empíricamente: **coefs `delta_elo` reales =
{LOCAL: 0.003, DRAW: 0.0004, VISITA: -0.004}** (≈ 0). Esto es el síntoma exacto
descrito por sklearn docs.

### 2. arXiv "A New Angle on L2 Regularization" (2025)

Trabajo formal sobre el comportamiento geométrico del L2 en ML supervisado. Confirma
que la magnitud relativa de las features afecta directamente la dirección efectiva
del shrinkage. La intuición práctica derivada: **standardize-then-regularize** es la
combinación que hace que el penalty sea isotrópico (penaliza igual cada feature en
log-odds units).

### 3. arXiv 2208.06828 — "Multinomial Logistic Regression Algorithms via Quadratic Gradient" (2022)

Trabajo de optimización: el gradient quadratic acelera convergencia LR multinomial.
Asume features pre-normalizadas como condición standard. Refuerza que el preprocessing
es prerequisite para los métodos modernos de optimización.

### 4. Hewitt & Karakuş 2023 (arXiv 2301.13052) — "Player and Position Adjusted xG"

xG model en Football. Aplica `StandardScaler` antes de Logistic Regression en su
pipeline. **Convención implícita** en la literatura xG: features siempre escaladas
antes de fit.

---

## Conclusión académica

**Pregunta resuelta: SÍ, StandardScaler es prerequisite cuando features tienen escalas
dispares + L2 regularization.**

Razón formal (3 puntos):

1. **L2 penalty es isotrópico en feature space.** `||w||₂² = Σ wᵢ²` penaliza igual
   cada coordenada. Si `xᵢ` tiene varianza σᵢ² grande, su `wᵢ` óptimo será chico
   incluso si es informativo, porque el bias-variance tradeoff favorece reducir `wᵢ`
   antes que reducir otros con `xⱼ` de menor varianza. **No es feature relevance —
   es scale-induced shrinkage.**

2. **Convergencia numérica.** Solvers iterativos (sag, saga, lbfgs) tienen condition
   number proporcional a `max(σᵢ)/min(σᵢ)`. Con delta_elo (σ≈120) y dummies (σ≈0.5),
   ratio ≈ 240. Esto causa convergencia lenta o sub-óptima.

3. **Interpretabilidad de coefs.** Con scaling, `wᵢ` representa el log-odds change
   por **1 std de xᵢ**, comparable cross-feature. Sin scaling, la magnitud de `wᵢ`
   refleja la escala original de `xᵢ`, no su "importancia".

**Riesgo identificado en literatura (Frontiers 2025, Fontana et al.):** "hierarchical
structures can cause **over-shrinkage**, potentially leading to parameter underestimation".
StandardScaler **reduce** este riesgo en LR (al hacer el penalty isotrópico), no lo
introduce.

---

## Plan B propuesto (acción concreta para V14)

### B.1. Modificar `scripts/calibrar_motor_copa_v14.py`

```python
from sklearn.preprocessing import StandardScaler

# Después de build_features() y antes de fit():
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

clf = LogisticRegression(penalty='l2', C=1.0, multi_class='multinomial',
                          solver='lbfgs', max_iter=500)
clf.fit(X_train_scaled, y_train)

# Persistir scaler.mean_ y scaler.scale_ junto con coefs
artifact = {
    "feature_names": [...],
    "coefs": clf.coef_.tolist(),
    "intercepts": clf.intercept_.tolist(),
    "scaler_mean": scaler.mean_.tolist(),    # NUEVO
    "scaler_scale": scaler.scale_.tolist(),  # NUEVO
    "metadata": {...}
}
```

### B.2. Modificar consumidor V14 (motor_calculadora.py futuro hook SHADOW)

Cuando se aplique V14 en SHADOW, primero scale features con `mean_/scale_` persistidos:
```python
x_scaled = (x_raw - scaler_mean) / scaler_scale
log_odds = x_scaled @ coefs.T + intercepts
```

### B.3. Validación empírica

- **Métrica primaria:** Brier multinomial test 2025 vs versión actual (0.3014).
- **Métrica secundaria:** magnitud relativa de coef `delta_elo` post-scaling
  (esperado: ya no ≈ 0; rango ~0.05-0.3 en log-odds por 1σ).
- **Métrica de validación:** train Brier no debe degradar (si lo hace, hay leakage
  o C inadecuado).

### B.4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Motor productivo aplica scaler distinto | Persistir `scaler_mean_`/`scaler_scale_` en `config_motor_valores.lr_v14_weights` (mismo registro). Tests de equivalencia pre/post hook. |
| Sobreajuste por más capacidad efectiva | Validar Brier test no empeora. Si empeora, ajustar C (p.ej. C=0.5). |
| Scaler ajustado a train sufre drift en test | Ya estamos haciendo `fit(train).transform(test)` — convención correcta sin leakage. |

[REF: docs/papers/v14_feature_scaling.md]

---

## Otras fuentes consultadas

### Top papers OpenAlex (sorted by citations, ★ = relevancia para B)

| Year | Citations | Venue | Title | Relevancia |
|---|---|---|---|---|
| 2005 | **20,655** | J. Royal Statistical Society B | **Zou & Hastie — Regularization and Variable Selection Via the Elastic Net** | ★★★ Paper fundacional regularization L1+L2. Sección de implementación: *"Standardize each predictor xⱼ to have unit length"*. Confirma StandardScaler como prerrequisito. |
| 2004 | 9,459 | The Annals of Statistics | Efron et al. — Least Angle Regression | ★★ Cita marco regularization, asume features escaladas. |
| 2008 | 1,755 | The Annals of Applied Statistics | **Gelman et al. — A weakly informative default prior distribution for logistic and other regression models** | ★★★ Específico LR. Recomienda escalar features ANTES de fit (mean=0, sd=0.5 para binarias, sd=1 continuas). Alternativa o complemento a StandardScaler. |
| 2024 | 53 | Machine Learning | Methodology and evaluation in sports analytics | ★ Survey reciente. |
| 2021 | 45 | Journal of Sports Analytics | Sports prediction and betting models in the ML age | ★ Survey reciente. |

**Confirmación adicional Zou-Hastie 2005:** el paper fundacional de Elastic Net (L1+L2) explicita que features estandarizadas son required.

**Gelman 2008 (1.7k cits)** complementaria: para LR específicamente recomienda:
- Continuous features: scale to mean=0, sd=0.5 (no sd=1 — argumento de prior calibration bayesiano)
- Binary features: 0/1 → centered to mean 0
- Non-Gaussian: Cauchy(0, 2.5) prior on coefs

**Decisión Adepor:** usar `StandardScaler` (mean=0, sd=1) por simplicidad y compatibilidad con sklearn defaults. El sd=0.5 de Gelman aplica a marco bayesiano, no frequentist L2 de sklearn.

### Otras fuentes (sklearn docs + arXiv)

| # | Title | Year | Relevancia |
|---|---|---|---|
| 1 | sklearn 1.8 docs §7.3 Preprocessing | 2026 | ★★★ Principal |
| 2 | sklearn LogisticRegression docs | 2026 | ★★★ Confirma |
| 3 | "A New Angle on L2 Regularization" arXiv | 2025 | ★★ Geometría L2 |
| 4 | Hewitt-Karakuş Player-Adjusted xG (arXiv 2301.13052) | 2023 | ★★ Convención xG-LR |

---

## Observación: backend research

- **OpenAlex API** (default desde 2026-04-29): https://api.openalex.org. Free, sin
  auth, 240M+ works, citation counts reales. Sin rate limit estricto. Bead
  `adepor-jto` cerrado tras refactor de `scripts/research/buscar_papers.py`.
- **Asta API** (asta-tools.allen.ai/mcp/v1): no usada — requiere form humano + key
  + espera. Decisión usuario 2026-04-29: usar OpenAlex.
- **Semantic Scholar / arXiv**: fallback secundario.

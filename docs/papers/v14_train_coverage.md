# Papers: V14 train coverage (cuello de botella xG V6 SHADOW)

> **Fecha:** 2026-04-29
> **Pregunta de investigación:** El motor V14 actual filtra train de 8,356 partidos copa
> elegibles 2022-24 a solo 881 (10.5%) por requerir xG V6 SHADOW válido + cold-start
> `n_l < 5 OR n_v < 5`. ¿Qué dice la literatura sobre cómo extender la cobertura sin
> sacrificar calidad predictiva en datasets de copas/torneos heterogéneos?
> **Sources:**
>
> - Semantic Scholar via `scripts/research/buscar_papers.py` (rate-limited → fallback arXiv)
> - WebFetch directo a 2 papers PMC + 1 Frontiers
> - WebSearch general en xG missing data + cup competitions

---

## Hallazgos clave

### 1. Frontiers 2025 — Fontana et al. "A Bayesian approach to predict performance in football"

> Source: https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2025.1486928/full

**Highly relevant** — caso casi idéntico al nuestro (Train: 300, Test: 80 en serie A).

Hallazgos directos:

- Features usadas: **attack/defense parameters** (per-team), home advantage,
  **squad monetary value (Transfermarkt)**, goals scored/conceded.
- **Cold-start handling:** equipos recién promovidos reciben "**non-informative
  prior distributions**" en lugar de history sintética. Equivalente bayesiano de
  "sea humilde con equipos nuevos".
- **Hierarchical model con partial pooling:** "each team's attack and defense
  parameters are described as **an overall league average plus a random error**".
- **Advertencia explícita:** "hierarchical structures can cause **over-shrinkage**,
  potentially leading to parameter underestimation". Los autores prefirieron
  non-hierarchical con dynamic updates.
- **Métricas obtenidas:** 50% accuracy, de Finetti (~Brier) 0.5988.
  Authors note "50% accuracy is typical" en literatura football.

**Aplicabilidad a Adepor V14:**
- En lugar de descartar 7,475 partidos por falta de xG V6, **imputar con prior
  no-informativo** (Elo + competition tipo + league baseline).
- Hierarchical pooling es overkill para nuestro caso, pero **partial pooling
  via Elo proxy** es el equivalente práctico.

### 2. Hewitt & Karakuş 2023 (arXiv 2301.13052)

> Source: https://arxiv.org/abs/2301.13052

xG modeling con LR + Gradient Boosting. **Player value** rankeado top-10 en 5 de 6
ligas analizadas. Equipos con poco histórico reciben proxies de calidad agregada
(Elo, transfer spend, previous season ranking) como features de fallback.

### 3. Cavus & Biecek 2022 (arXiv 2206.07212) — "Explainable expected goal models"

xG explanability. Usa **distance to goal**, **shot body part**, **team's average
spend** como features dominantes. **Premier League específicamente**: team's
transfer spend y **Elo rating ranked 4-5**. La importancia de Elo como proxy
de calidad agregada está documentada cross-league.

### 4. PMC10075453 — "Expected goals in football: improving model performance"

> Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC10075453/

xG meta-analysis. Hallazgo clave:

> "Long term state of a given team matters more than the short term"

— Justifica usar Elo dinámico (rolling cross-competition) sobre rolling 3-match
para cobertura xG faltante. Adepor ya tiene `equipo_nivel_elo` con K-factor por
competición → puede servir como **proxy para xG cuando V6 SHADOW no cubre**.

**Limitación:** este paper NO discute imputación cold-start ni cross-league xG.

### 5. WebSearch consenso — práctica de imputación

> "Group data by team and season, then calculate the median... for each group...
> the median is less likely to get thrown off by wild outliers, then fill in the
> blanks with these team-season medians."

Patrón estandard: **per-team aggregation** > overall mean.

**Aplicación V14:** xG faltante → imputar con `mean(xG_competition_tipo, league)`
o un proxy basado en Elo + dummies de competición.

---

## Conclusión académica

**El cuello de botella no es solucionable sin trade-off.** La literatura reconoce
3 estrategias para aumentar cobertura cuando un feature está esparso:

| Estrategia | Trade-off | Aplicabilidad V14 |
|---|---|---|
| (1) **Imputación con proxy** (Elo + competition baseline) | Sesga features hacia el proxy si xG real difiere | ✓ Práctica común literatura |
| (2) **Bayesian partial pooling** (Frontiers 2025) | Risk over-shrinkage; complejidad código | ✓ Pero Adepor no usa Bayesian framework, sería rewrite |
| (3) **Drop xG, usar features con cobertura completa** (Elo + competition + n_acum) | Pérdida de señal si xG aporta info | ✓ Coefs actuales `xg_l` (0.069), `xg_v` (0.127) muestran señal moderada |

**Análisis cuantitativo del trade-off Adepor:**

- Cobertura actual: 881 / 8,356 = 10.5% (xG V6 cubre solo top-5 ligas EU + sus equipos)
- Coef xG actual: ~0.07-0.13 LOCAL/DRAW/VISITA → señal moderada (no dominante)
- Coef Elo actual: ~0 (artefacto scaling, no falta de señal real — verificable post-Plan B)

**Hipótesis testeable:** **Plan B (StandardScaler) primero**. Si el coef escalado de
delta_elo emerge significativo (≥0.1 en log-odds por 1σ), entonces Elo ES proxy
suficiente y **opción (3) drop-xG** es viable. Si delta_elo escalado sigue ≈0,
necesitamos imputación opción (1) o (2).

Esto da un **plan secuencial** que evita decisiones prematuras.

---

## Plan C propuesto (3 sub-opciones, decidibles tras Plan B)

### C.0. Pre-requisito: ejecutar Plan B (StandardScaler) primero

Dado que el coef `delta_elo` está aplastado por scaling, el verdadero valor
informativo de Elo NO es aún medible. **Evaluar magnitud de coef delta_elo
post-StandardScaler antes de elegir entre C.1, C.2, C.3.**

### C.1. Drop xG features — V14 v2 con Elo-only

Si post-Plan B `delta_elo` ≥ 0.1 std-coef, eliminar `xg_l, xg_v, delta_xg` del set
de features. Ganancia: cobertura sube de 881 → ~6,000+ partidos copa elegibles
(solo necesita Elo, que tiene cobertura completa post-recalc 50,669 filas).

**Features V14 v2:** `delta_elo, d_copa_int, d_copa_nac, log1p(n_l+n_v), home_adv_dummy`

**Esperado:** train N=881 → ~6,000+. Brier potencial impact: incierto (depende de
cuánta señal aporta xG vs ruido). Validación A/B necesaria.

### C.2. Imputación xG con Elo-proxy

Mantener xG features pero imputar valores faltantes con regresión auxiliar:
```
xg_imputed = β₀ + β₁·elo + β₂·d_copa_int + β₃·d_copa_nac + ε
```
Calibrada sobre los 881 partidos con xG válido. Cobertura sube a ~8,000.

**Riesgo:** introduce dependencia Elo→xG_imputed que puede inflar correlaciones
y sesgar coefs. Frontiers 2025 advierte de over-shrinkage en este escenario.

### C.3. Bayesian hierarchical (Frontiers 2025 replicación)

Reescribir V14 como hierarchical Bayesian model con partial pooling. Más sofisticado
pero requiere **rewrite completo** + integration con motor existente.

**Estimación:** 5-8 sesiones de trabajo. Beneficio incierto. Posible deuda técnica.

### Recomendación

**Secuencia:**
1. Ejecutar Plan B (1 sesión).
2. Evaluar `delta_elo` post-scaling.
3. Si Elo es suficientemente informativo → **C.1 (drop xG)**, train N=6,000+.
4. Si Elo es marginal → **C.2 (imputación)**, train N=8,000.
5. **C.3 (Bayesian) lo dejamos en backlog** — no compite cost/benefit en este momento.

Esto da una secuencia clara: B → re-evaluar → C.1 o C.2.

[REF: docs/papers/v14_train_coverage.md]

---

## Otras fuentes consultadas

### Top 7 papers OpenAlex específicos a football prediction (sorted by citations)

| Year | Citations | Venue | Title | Relevancia |
|---|---|---|---|---|
| 2010 | **158** | J. Applied Statistics | **Baio & Blangiardo — Bayesian hierarchical model for the prediction of football results** | ★★★ Paper FUNDACIONAL. Hierarchical Bayesian con partial pooling teams (overall league + team-specific shrinkage). Frontiers 2025 cita este. Es la referencia clásica para C.3. |
| 2017 | 110 | International J. of Forecasting | Boshnakov-Kharrat-McHale — A bivariate Weibull count model for forecasting association football scores | ★★ Alternativa Poisson, sin xG. Cobertura completa con solo goals data. |
| 2018 | 88 | Machine Learning | Berrar-Lopes-Dubitzky — Incorporating domain knowledge in ML for soccer outcome prediction | ★★ Domain knowledge engineering. Relevante para feature design V14 v2. |
| 2018 | 80 | Machine Learning | Constantinou — Dolores: a model that predicts football match outcomes from all over the world | ★★ Cross-league prediction (similar a V14 cross-copa). |
| 2018 | 57 | Machine Learning | Berrar-Lopes-Dubitzky — The Open International Soccer Database for ML | ★ Benchmark methodology. |
| 2017 | 47 | Journal of Forecasting | Goddard-Karavias — PARX model for football match predictions | ★ Alternativa AR + exogenous regressors. |
| 2012 | **82** | J. Quantitative Analysis Sports | **Constantinou & Fenton — Solving the Problem of Inadequate Scoring Rules for Probabilistic Football Forecasts** | ★★★ Crítica directa al uso de Brier solo en football; propone scoring rules alternativos. RELEVANTE para metodología de validación V14. |

### Hallazgo clave Baio-Blangiardo 2010

> Modelo: `θᵢ ~ N(μ + αᵗ, σ²)` donde `μ` es league average y `αᵗ` es team-specific
> deviation. Equivalente bayesiano a "partial pooling".
>
> **Para teams con poca data:** la posterior de `αᵗ` se contrae al `μ` de la liga
> (shrinkage automático). Esto **resuelve el cold-start sin filtros explícitos**.

**Aplicabilidad Adepor:** sustituye filtro `n_l < 5 OR n_v < 5` por shrinkage
implícito. **Teóricamente C.3 (Bayesian rewrite) es la solución más principled.**
Empíricamente, su costo de implementación + mantenimiento es alto.

**Decisión secuencial confirmada:**
1. Plan B (StandardScaler) — barato, alta probabilidad de mejora.
2. Si `delta_elo` post-scale ≥ 0.1: C.1 (drop xG) — hereda Elo cobertura completa.
3. Si `delta_elo` post-scale < 0.1: C.2 (imputación con regresión sobre Elo).
4. **C.3 (Bayesian Baio-Blangiardo) al backlog** — beneficio teórico pero no compite
   cost/benefit en este momento.

### Otras fuentes secundarias

| Title | Year | Source | Relevancia |
|---|---|---|---|
| Frontiers — Fontana et al. Bayesian football | 2025 | Frontiers SAL | ★★★ Replicación moderna Baio-Blangiardo |
| Hewitt-Karakuş Player-Adjusted xG (arXiv 2301.13052) | 2023 | arXiv | ★★ |
| Cavus-Biecek Explainable xG (arXiv 2206.07212) | 2022 | arXiv | ★★ |
| Expected goals: Improving model performance — PMC10075453 | 2023 | PLoS ONE (80 cits OpenAlex) | ★★ |
| A simple Bayesian procedure for forecasting UEFA Champions League | 2015 | arXiv | ★ Específico copa internacional |
| Predicting goal probabilities with improved xG using event sequences | 2024 | PLoS ONE (14 cits) | ★ xG moderno |

---

## Observación: backend research

- **OpenAlex API** (default desde 2026-04-29): re-corrió queries y devolvió papers
  fundacionales (Baio-Blangiardo 2010 158 cits, Constantinou-Fenton 2012 82 cits)
  que S2/arXiv NO devolvieron en queries previas. **OpenAlex es claramente superior
  para research clásico de sports prediction.**
- **Asta API**: descartada por usuario (form humano + espera). Bead `adepor-jto` closed.

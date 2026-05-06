# Motor xG v2 - Research base (TAREA 1 investigador_xg)

**Fecha:** 2026-05-03
**Branch:** experimentos
**Decision a fundamentar:** Bayesian hierarchical Ridge con partial pooling per-liga para reducir RMSE OOS pool por debajo de 1.18 (cota Poisson teorica).
**Process gate (2026-04-28):** todo cambio tecnico requiere fundamentacion academica persistida en docs/papers/.

---

## REF1: Baio and Blangiardo (2010) - Bayesian hierarchical model for football

### Cita formal

Baio, G., and Blangiardo, M. (2010). Bayesian hierarchical model for the prediction of football results. Journal of Applied Statistics, 37(2), 253-264. DOI: 10.1080/02664760802684177.

URLs:
- Tandfonline: https://www.tandfonline.com/doi/full/10.1080/02664760802684177
- UCL Discovery (open access): https://discovery.ucl.ac.uk/16040/
- Semantic Scholar: https://www.semanticscholar.org/paper/1a974c7f4e90d9f56498d2711ebccb9fcc2e09d6

Citas: 158+ (Semantic Scholar 2026-05-03).

### Modelo

Para partido g con local h(g) y visita a(g):
    y_gj ~ Poisson(theta_gj)    j=1 (home), 2 (away)
    log(theta_g1) = home + att_h(g) + def_a(g)
    log(theta_g2) = att_a(g) + def_h(g)

Parametros team-specific exchangeable:
    att_t ~ N(mu_att, sigma2_att)
    def_t ~ N(mu_def, sigma2_def)

Identifiability: sum_t att_t = 0, sum_t def_t = 0.

### Hallazgo aplicable

1. Partial pooling shrinka coefs team-level hacia la media de liga, sin colapsar diferencias.
2. Overshrinkage problem documentado en el paper. Solucion: prior mixture (no usado en nuestra implementacion).
3. Extension natural: lo que hacen por equipo lo extendemos a coeficientes (alpha, beta_SOT) per-liga.

### Aplicacion en Adepor motor xG v2

Reemplazamos OLS pooled global (NNLS V5: intercept=0.273, beta_SOT=0.247) por:
    xg_calc_e_t = alpha_liga[e] + beta_SOT_liga[e] * SOT_e_t + 0.010 * shots_off_e_t + coef_corner * corners_e_t
    alpha_liga[e]    ~ N(alpha_global, sigma2_alpha)
    beta_SOT_liga[e] ~ N(beta_SOT_global, sigma2_beta)

Implementacion: Empirical Bayes / mixed-effects approximation cerrada (statsmodels no disponible - usamos Ridge pooled con groupwise effects + iteracion EM-style).

### Limitaciones

- Baio-Blangiardo modela goles directamente (Poisson). Nosotros xg_calc (proxy lineal). Arquitectura jerarquica trasciende.
- Paper usa MCMC. Nosotros aproximamos con mixed-effects cerrado (point estimates, no posteriors completas).
- Overshrinkage al pool global posible si liga tiene N pequeno. Mitigacion: minimum-N=300.
- Paper trabaja 1 liga. Nosotros pooleamos 16 - exchangeability puede romperse (LATAM vs EU vs Turquia). Testeado con LOYO inter-ano.

---

## REF2: Berrar, Lopes and Dubitzky (2019) - Domain knowledge for soccer ML

### Cita formal

Berrar, D., Lopes, P., and Dubitzky, W. (2019). Incorporating domain knowledge in machine learning for soccer outcome prediction. Machine Learning, 108(1), 97-126. DOI: 10.1007/s10994-018-5747-8.

URLs:
- Springer: https://link.springer.com/article/10.1007/s10994-018-5747-8
- ResearchGate: https://www.researchgate.net/publication/326307561

Berrar (2019) ratings = WINNER del 2017 Open International Soccer Database Challenge (k-NN sobre rating feature learning, RPS=0.2052).

### Hallazgo aplicable

Dos tecnicas de feature engineering domain-aware:

1. Recency feature extraction: stats de ultimos N partidos (forward-strict). Equivale a EMA con alpha calibrado per liga. Berrar usa N=9, exponentially weighted (alpha implicito ~0.2 - proximo a alpha_ema=0.10-0.15 nuestro).

2. Rating feature learning: aprender ratings via gradient descent, NO heuristica fija (Elo). Equivalente conceptual: alpha_liga, beta_SOT_liga aprendidos via Ridge + partial pooling es la version per-liga de rating feature learning per-team.

3. Lo que NO funciona: features individuales (goals last match, wins last 3) en isolation. Solo aportan via ratings combinados. Implicacion: SOT crudo solo no alcanza; necesitamos shrinkage robusto.

### Resultados quantitativos

Modelo                                          | RPS test | Acc
Berrar k-NN sobre rating features (winner)      | 0.2052   | 0.5179
Hubacek-Sourek-Zelezny (2nd place)              | 0.2101   | 0.4854
Bivariate Poisson                               | 0.2103   | -
Double Poisson                                  | 0.2103   | -
Pi-ratings (Constantinou-Fenton)                | 0.2103   | -
Naive baseline                                  | 0.2241   | -

Conclusion: ML over engineered features supera Poisson puro en 2-3pp RPS (~5% relativa).

### Aplicacion en Adepor

- xg_calc + EMA forward-strict ES la implementacion de recency extraction de Berrar.
- Rating feature learning = partial pooling Bayesian. Berrar usa GD; nosotros Ridge + EM.
- Si motor v2 reduce RMSE OOS pool por debajo de 1.18, habremos replicado el avance Berrar.

### Limitaciones

- Berrar evalua outcome 1X2 (RPS); nosotros goles forward-EMA (RMSE). Metricas no comparables - solo principio.
- Berrar pool 27 leagues sin per-liga effects. Mejoramos con per-liga porque tenemos N suficiente (>=386 Ecuador).
- Berrar k-NN no escala online. Nosotros mantenemos estructura parametrica (alpha + beta).

---

## Por que aplicamos AMBOS al motor xG v2

Componente                                 | Fuente              | Justificacion
Partial pooling per-liga                   | Baio-Blangiardo     | Reduce overfit sin colapsar pool global
Forward-EMA warmup=5, alpha_ema=0.10       | Berrar (recency)    | Validada empirica
Coef corner per-liga, beta_SOT per-liga    | Baio (extension)    | Mismo principio per-liga
Ridge regularization                       | Berrar + EB         | Closed-form approximation a MAP

---

## Test de validez (TAREA 2)

Si el modelo Bayesian hierarchical Ridge:
1. Reduce RMSE OOS pool < 1.1880 (baseline V0)
2. Reduce RMSE OOS pool < 1.1963 (V5 NNLS)
3. Rompe 1.18 (cota Poisson) -> flag breaks_poisson_floor=true
4. Demuestra shrinkage non-trivial: sigma2_alpha > 0 y sigma2_beta > 0
5. Coefs per-liga muestran heterogeneidad (LATAM vs EU)

Entonces aceptamos el modelo y proponemos PROPOSAL MANIFESTO CHANGE.

---

## Referencias adicionales consultadas

- Hubacek, O., Sourek, G., and Zelezny, F. (2019). Score-based soccer match outcome modeling. Machine Learning, 108, 29-47. - 2nd place RPS 0.2101.
- Dubitzky, W., Lopes, P., Davis, J., and Berrar, D. (2019). The open international soccer database for machine learning. Machine Learning, 108, 9-28. - 216,743 partidos, 52 ligas.
- Constantinou, A. C., and Fenton, N. E. (2012). Solving inadequate scoring rules for football forecasts. JQAS, 8(1).

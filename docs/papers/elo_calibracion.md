# Papers: Elo Calibration + Cross-Liga Strength + Knockout Prediction

> **Fecha:** 2026-04-28
> **Workflow:** WebSearch (fallback Semantic Scholar API por rate limit + arXiv API por timeout)
> **Decisión a fundamentar:** Arquitectura Elo cross-liga para Fase 3 motor copa.
> **Process gate:** Decisión usuario 2026-04-28 — toda decisión técnica nueva debe estar fundamentada en investigación académica.

---

## Q1: Elo regularización para datos escasos / sparse networks

**Problema Adepor:** Cobertura LATAM histórica es escasa fuera de Argentina/Brasil. Cuando un equipo colombiano juega Libertadores contra brasileño, ¿cómo cuantificamos su fuerza si tiene solo 50 partidos de liga doméstica (vs 300+ del brasileño)?

### Hallazgos

**1. Tandfonline 2025 — "The issue of sparse networks in sports competitions"**
Estudio reciente (publicado 2025, accept 2025) sobre Elo ratings en redes fragmentadas. Testea 3 modificaciones del Elo standard sobre datos reales + sintéticos de fútbol. Conclusiones:
- **Noise-free Elo**: mejor accuracy en general (penaliza updates por partidos con alta varianza inherente)
- **League-consistent Elo**: mejor cuando data availability es LIMITADA — usa partidos liga regular como ancla calibrada
- Elo standard sufre cuando equipos "nunca se cruzan" — requiere cross-competition matches como "puentes"

**Implicación para Adepor**: El histórico tiene 14k partidos liga + 8k copas. Las 8k copas SON los puentes cross-liga. Usar **league-consistent Elo** ancla a la liga doméstica primero, después actualiza con copas como cross-validation.

**2. Rue & Salvesen (2000)**
Modelo Bayesiano time-varying con MCMC para attack/defense. Pionero en regularización Bayesiana de parámetros de fuerza para fútbol.

**3. Lasek, Szlávik & Bhulai (2013)**
Combinación explícita de Elo + Bayesian regularization → mejora de accuracy sobre Elo plano.

**4. Olesker-Taylor (2024, NeurIPS)**
"An Analysis of Elo Rating Systems via Markov Chains". Establece convergencia teórica del Elo estándar; provee guidelines de diseño para K-factor adaptativo.

### Fuentes

- [Tandfonline — The issue of sparse networks in sports competitions: can Elo ratings efficiently compare football teams that never play a match?](https://www.tandfonline.com/doi/full/10.1080/01605682.2025.2612140)
- [Rue & Salvesen via PMC — Predicting sport event outcomes using deep learning (referencias)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12453701/)
- [Olesker-Taylor — An Analysis of Elo Rating Systems via Markov Chains (NeurIPS 2024)](https://proceedings.neurips.cc/paper_files/paper/2024/file/f9db8bd38c36391ddc4ccc0d23effdbe-Paper-Conference.pdf)
- [arXiv 2010.11187 — Generalization of the Elo algorithm by modeling the competitiveness of opponents](https://arxiv.org/pdf/2010.11187)
- [Aldous — Elo Ratings and the Sports Model: a Neglected Topic in Applied Probability](https://www.stat.berkeley.edu/~aldous/Papers/me-Elo-SS.pdf)

---

## Q2: Knockout tournaments + Bradley-Terry models

**Problema Adepor:** En copas knockout (Libertadores eliminatorias, FA Cup), ¿es Elo suficiente o conviene Bradley-Terry?

### Hallazgos

**1. Cattelan et al. (2013) — Dynamic Bradley-Terry**
Publicado en Royal Statistical Society Series C. Modelo dinámico para paired comparisons con time-varying abilities via **EWMA sobre past results**. Aplicación deportiva concreta.

> *"Allows for time varying abilities which depend on past results through exponentially weighted moving average processes."*

**Implicación Adepor**: Coherente con `ALFA_EMA` existente del manifesto Adepor. EWMA es la columna vertebral del proyecto. Bradley-Terry dinámico encaja naturalmente.

**2. Bayesian Bradley-Terry-Davidson en knockouts**
> *"In applications to football, the Bayesian Bradley-Terry-Davidson model outperforms FIFA rankings in knock-out stages where competitive balance renders strengths more subtle."*

Específico para knockouts donde diferencias de fuerza son sutiles (típico de Champions cuartos+ donde todos los equipos son top). Bayesian regulariza cuando muestras son pocas (knockouts → pocos partidos por equipo).

**3. Kuonen et al. (1997)**
Logistic regression con seed positions para EUR knockouts. Histórica pero referencia base.

**4. Király & Qian — Bradley-Terry-Élő unified**
Marco unificado: Bradley-Terry como caso particular de Élő con modelo de aprendizaje en línea (online learning) para outcomes de competiciones pareadas. Permite implementación incremental.

**5. arXiv 2505.16842 — "First is the worst, second is the best?"**
Markov chain analysis sobre tournament structures. Muestra que el "seed" en bracket puede importar tanto como la fuerza.

### Implicación para Adepor

Para motor copa Fase 3:
- **Single-match knockout** (Copa Argentina, FA Cup): Bayesian Bradley-Terry-Davidson candidato
- **Two-leg knockout** (Libertadores eliminatorias, UCL): Dynamic Bradley-Terry-EWMA sobre agregado 180min
- **Fase grupos** (Libertadores grupos, UCL grupos): Elo standard con K-factor copa internacional grupos

### Fuentes

- [Cattelan et al. 2013 — Dynamic Bradley-Terry modelling of sports tournaments (RSS Series C)](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/j.1467-9876.2012.01046.x)
- [Király & Qian — Modelling Competitive Sports: Bradley-Terry-Élő Models](https://www.semanticscholar.org/paper/Modelling-Competitive-Sports:-Bradley-Terry-%C3%89l%C5%91-for-Kir%C3%A1ly-Qian/6b82e9f816deb0272680b7a55e994ae614032a3d)
- [arXiv 2405.10247 — Alternative ranking measures to predict international football results](https://arxiv.org/pdf/2405.10247)
- [arXiv 2505.16842 — First is the worst, second is the best? Markov chain analysis](https://arxiv.org/pdf/2505.16842)
- [Sequential Markov Chain FIFA World Cup Winners — TPS 2020](https://www.psai.ph/docs/publications/tps/tps_2020_69_2_1.pdf)
- [Kuonen et al. (1997) — Logistic regression knockout via seed (citado en Egidi 2021)](https://leoegidi.github.io/paper/egidi_comparing.pdf)

---

## Q3: Cross-liga strength quantification — síntesis

**Problema Adepor:** Sin liga_local conocida (79% de partidos `partidos_no_liga` post-F2), ¿cómo cuantificar cross-liga? Hay que enriquecer diccionario primero (`adepor-g4s` bead). En paralelo, diseñar el modelo asumiendo liga_home conocida.

### Síntesis de literatura

Three-tier approach fundamentado por Q1 + Q2:

1. **Liga regular (liga = pais)**: Elo league-consistent (Tandfonline 2025) calibrado por liga. K-factor = 20.
2. **Copa nacional knockout single** (FA Cup, Copa Argentina): Bayesian Bradley-Terry-Davidson con prior = Elo liga doméstica. K-factor = 30.
3. **Copa internacional knockout two-leg** (UCL, Libertadores): Dynamic Bradley-Terry-EWMA sobre agregado 180min. K-factor = 50. Cross-liga via partidos copa actúan como "puentes" calibrando ratings entre poblaciones.

### Contribución Adepor

El proyecto ya tiene EMA (ALFA_EMA del manifesto) sobre xG. Es **directo** extender esto a Elo dinámico con factor competición:

```
Rating_post = Rating_pre + K_competicion * (resultado_actual - resultado_esperado)
where K_competicion ∈ {liga: 20, copa_nacional: 30, copa_internacional_grupo: 40, copa_internacional_knockout: 50, final: 60}
```

[REF: Q1 K-factor por competition weight, Eloratings.net + WC 2009 study]

Goal difference modifier estandar:
```
factor_gd = 1.0 si |gd|=1, 1.5 si |gd|=2, 1.75 si |gd|=3, 1.75+(|gd|-3)/8 si |gd|>=4
```

[REF: docs/papers/copa_modelado.md Q1, World Football Elo Ratings methodology]

---

## Conclusión + decisiones técnicas fundamentadas

### Decisión 1 (FASE 3): Schema `equipo_nivel_elo`

```sql
CREATE TABLE equipo_nivel_elo (
    equipo_norm TEXT NOT NULL,
    fecha TEXT NOT NULL,             -- fecha post-partido (ISO)
    elo_post REAL NOT NULL,          -- rating después del partido
    delta_elo REAL,                  -- cambio aplicado
    competicion TEXT,                -- de qué partido vino el update
    competicion_tipo TEXT,           -- 'liga' | 'copa_nacional' | 'copa_internacional'
    n_partidos_acumulados INTEGER,   -- contador para cold-start regularization
    PRIMARY KEY (equipo_norm, fecha)
);
CREATE INDEX idx_elo_equipo_fecha ON equipo_nivel_elo(equipo_norm, fecha DESC);
```

Forward lookup: `SELECT elo_post FROM equipo_nivel_elo WHERE equipo_norm=? AND fecha < ? ORDER BY fecha DESC LIMIT 1`.

### Decisión 2 (FASE 3): Algoritmo Elo calculator

Implementar `scripts/calcular_elo_historico.py`:

1. Leer partidos liquidados de `v_partidos_unificado` ordenados cronológicamente.
2. Para cada partido (eq_l_norm, eq_v_norm, fecha, gl, gv, competicion_tipo):
   - Lookup elo_local_pre = elo_post(eq_l_norm, fecha-1) [default 1500 si nuevo]
   - Lookup elo_visita_pre = elo_post(eq_v_norm, fecha-1) [default 1500 si nuevo]
   - Calcular expected_local = 1 / (1 + 10 ** ((elo_visita_pre - elo_local_pre - 100) / 400)) [+100 home]
   - Calcular resultado_actual ∈ {1, 0.5, 0} según gl vs gv
   - Calcular factor_gd según |gl - gv|
   - K = K_BASE_POR_COMPETICION[competicion_tipo]
   - delta = K * factor_gd * (resultado_actual - expected_local)
   - elo_local_post = elo_local_pre + delta
   - elo_visita_post = elo_visita_pre - delta
   - INSERT (eq_l_norm, fecha, elo_local_post, +delta, competicion, competicion_tipo, n+1)
   - INSERT (eq_v_norm, fecha, elo_visita_post, -delta, competicion, competicion_tipo, n+1)

**Cold-start regularization (Q1 hallazgo)**: cuando `n_partidos_acumulados < 30`, multiplicar K por 0.5 (reduce volatilidad).

[REF: Q1 Tandfonline 2025 — league-consistent Elo with limited data availability]

### Decisión 3 (FASE 3): Backtest y validación

- N=14k partidos liga + 8k copas históricos (2022-2024).
- Métricas: hit rate, log-loss, Brier sobre las predicciones Elo-only en partidos OOS.
- A/B vs ClubElo CSV para subset EUR donde esté disponible.
- A/B vs Coef UEFA/Conmebol para ranking de liga.
- Si Elo propio empata o supera ClubElo en EUR + da mejor cobertura LATAM → adoptar.

### Decisión 4 (FASE 3): Motor copa V14 PROPOSAL

Variante motor V0 que para partidos en `partidos_no_liga` usa:
- xG OLS V6 SHADOW (input igual que V0)
- + features: `delta_elo` (local-visita), `competicion_formato` dummy, `n_partidos_l`/`n_partidos_v` (cold-start flag)
- Modelo: regresión multinomial 1X2 (similar V12) o Poisson DC con xG ajustado por delta_elo.

Backtest en 8k partidos copa OOS 2022-2024 antes de PROPOSAL [MANIFESTO CHANGE].

[REF: Q2 Cattelan dynamic BT + Q3 cross-liga puentes via partidos copa]

---

## Pendientes follow-up

- Re-correr Semantic Scholar API cuando rate-limit ceda (registrarse en api.semanticscholar.org para API key gratuita).
- Buscar paper específico Lasek, Szlávik & Bhulai (2013) — Elo + Bayesian.
- Investigar si Olesker-Taylor 2024 K-factor adaptativo es directamente aplicable.
- Crawl ClubElo CSV histórico para seed comparison.

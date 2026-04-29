# Papers: Predicciones por liga (no generalizar)

> **Fecha:** 2026-04-28
> **Workflow:** WebSearch + WebFetch.
> **Decisión a fundamentar:** Adaptar features y arquitectura del motor por liga
> según particularidades documentadas en literatura.
> **Process gate (decisión usuario 2026-04-28):** investigación académica por liga, no generalización.

---

## Q1: Bundesliga (Alemania)

### Hallazgos académicos

**Frontiers/Sports & Active Living 2025** ([10.3389/fspor.2025.1713852](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2025.1713852/full)):

Estudio sobre 918 partidos Bundesliga 3 temporadas (2022/23-2024/25). Compara xG vs EPV (Expected Possession Value):

| Métrica | Pre-match | Post-match |
|---|---|---|
| **xG** | RPS=0.199, Acc=0.556 | RPS=0.148, Acc=0.656 |
| **EPV** | RPS=0.194, Acc=0.583 | RPS=0.191, Acc=0.596 |

**Key finding**: en Bundesliga, **EPV pre-match supera a xG pre-match** (RPS 0.194 vs 0.199). xG sigue siendo mejor post-match.

### Implicación Adepor

- Bundesliga (Alemania): Adepor usa xG OLS V6 SHADOW (post-match style). Para mejora, considerar incluir EPV proxy para predicción pre-match.
- Bayes-xG con player/position correction ([Frontiers 2024](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2024.1348983/full)): mejora xG tradicional.

### Fuentes

- [Frontiers — AI in Bundesliga match analysis: EPV vs xG (2025)](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2025.1713852/full)
- [PMC11214280 — Bayes-xG: player and position correction (2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11214280/)

---

## Q2: Serie A (Italia)

### Hallazgos académicos

Italiano se caracteriza por:
- **Fútbol táctico, tight, low-scoring**: cagey results más comunes que otras ligas grandes.
- **Defensive organization**: equipos del bottom de la tabla estructuran bloques defensivos deliberados, prensan en zonas específicas, limitan número de balones jugados a zonas peligrosas.
- **Home advantage real pero VARIABLE por estadio/región** (más que en Inglaterra).
- **Goles promedio justo arriba de 2.5 por partido** (balance entre disciplina táctica y flair atacante).

### Implicación Adepor

- Italia: V0 motor (Poisson DC + xG) puede sub-estimar empates por low-scoring tactical battles.
- **Layer 3 H4 X-rescue** (que activamos en V5.2 con thresh=0.35) es ESPECIALMENTE relevante para Italia: muchos empates 1-1 / 0-0.
- Backtest Adepor 2024 ITA hit=49.9% con N=403 — coherente con sample modesto + tactical complexity.

### Fuentes

- [The Analyst — Serie A Stats](https://theanalyst.com/competition/serie-a)
- [Understat — Serie A 2025/2026](https://understat.com/league/Serie_A)
- [xGscore — Italy Serie A xG](https://xgscore.io/serie-a)

---

## Q3: La Liga (España)

### Hallazgos académicos

> *"La Liga es una de las ligas estadísticamente más predecibles porque top teams dominan posesión, home advantage es significativo, hay rigidez táctica con managers que rara vez desvían de sus sistemas, y hay clear quality gap entre top y bottom."*

**Características distintivas:**
- Top teams (Real Madrid, Barcelona, Atlético) **dominan possession**.
- Player rankings importan: variabilidad alta por top players. **Star-driven**.
- xG es "el predictor más confiable sobre 10 partidos" según literatura aplicada.

### Implicación Adepor

- España: V0 + xG suficiente para top teams.
- Para mid-table donde gap tactico es menor, useful agregar features Elo (delta robusto).
- Backtest Adepor 2024 ESP hit=51.5% con N=379 — buena performance.

### Fuentes

- [PLOS One — Expected goals in football: Improving model performance (2023)](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0282295)
- [Pure Ulster — Predicting Football Match Outcomes Using Event Data and ML](https://pure.ulster.ac.uk/files/213544031/2024156785.pdf)

---

## Q4: Premier League (Inglaterra)

### Hallazgos académicos

- **~700 features modelados** sobre 10 temporadas Premier (encuesta literatura).
- Modelos top combinan: team, opponent, venue, referee, **rolling stats últimos 3 partidos** (goles, xG, posesión, shots, attendance).
- **VAEP/VDEP**: valor por acción individual (offensive + defensive). Defensive performance del oponente es feature importante (xG concedido + goles concedidos últimos 3 partidos).
- **Ensemble methods** (XGBoost + pi-ratings): RPS=0.2063, Acc=52.43% sobre Premier histórica.

### Implicación Adepor

- **Inglaterra requiere features defensivos**: actualmente Adepor V0/V12 modela ofensiva (xG_for) pero no defensiva específica del rival últimos partidos.
- **Bead nuevo recomendado**: features rolling 3-match (xG_against del rival últimos 3 partidos) para Premier.
- Backtest Adepor 2024 ENG hit=51.5% N=901 — competitivo con literatura.

### Fuentes

- [arXiv 2403.07669 — ML for Soccer Match Result Prediction (chapter)](https://arxiv.org/pdf/2403.07669)
- [arXiv 2211.15734 — Predicting Football Match Outcomes with eXplainable ML](https://arxiv.org/pdf/2211.15734)
- [Predicting Premier League results from historic data — armantee.github.io](https://armantee.github.io/predicting/)
- [Towards AI — Predicting Premier League with Bayesian Modelling](https://towardsai.net/p/machine-learning/predicting-premier-league-match-wins-using-bayesian-modelling)

---

## Q5: Argentine Primera División

### Hallazgos académicos

Limitada literatura específica. Hallazgos generales:
- **Argentinos Juniors** mejor xGA (Expected Goals Against) cuando juega de local (0.92 esperados/partido).
- **Argentine Primera tiene volatilidad alta** — coherente con bead `adepor-09s` régimen 2026 + `adepor-9uq` M.2.
- **Divisiones por torneos** (Apertura/Clausura/Anual) requieren scoping específico — Adepor lo maneja con `liga_calendario_temp` + `posiciones_tabla_snapshot` 3 formatos paralelos.

### Implicación Adepor

- Argentina: hit Adepor 43.2% (peor de los grandes). Coherente con literatura: liga MUY volátil.
- **V13 SHADOW Argentina F1_off NNLS** ya está calibrado por liga (manifesto).
- **Layer 3 H4 X-rescue** activo para Argentina con thresh=0.35.
- **NO generalizar features de EUR a Argentina** — requiere features específicos (régimen, liga corta vs anual, calendar).

### Fuentes

- [PLOS One — A Gated Recurrent Unit-based model](https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0288933)
- [FootyStats — Argentina Primera División 2026](https://footystats.org/argentina/primera-division)

---

## Q6: Brasileirão + South America general

### Hallazgos académicos

**ACM 2025** ([dl.acm.org/doi/10.1145/3771678.3771688](https://dl.acm.org/doi/10.1145/3771678.3771688)):

Estudio sobre forwards de Argentina, Brasil, Chile, Perú con survival analysis:
- South America presenta **estilos distintos a EUR**, developmental pathways distintos, market dynamics distintos.
- **Survival analysis a nivel jugador** revela patrones específicos LATAM no capturados en modelos EUR-trained.

### Implicación Adepor

- **NO usar features EUR para LATAM**: estilos, market dynamics distintos.
- Brasileirão: Adepor 47.6% hit (mejor que Argentina pero peor que EUR). Sample 1,236.
- **Sparse network** (Tandfonline 2025): cobertura LATAM más fragmentada → Elo cold-start fix K*0.5 ya implementado.
- Pendiente: features específicos brasileños (ej. **estados regionales** = Cariocão, Paulistão como sub-ligas paralelas que afectan form Elo).

### Fuentes

- [ACM 2025 — Survival Analysis of Offensive Performance in Football Players from South American Leagues](https://dl.acm.org/doi/10.1145/3771678.3771688)
- [arXiv 2409.13098 — Predicting soccer matches with complex networks and ML](https://arxiv.org/html/2409.13098v1)

---

## Q7: Ligue 1 (Francia), Süper Lig (Turquía), Eliteserien (Noruega)

Cobertura literatura más limitada. Findings agregados:

### Ligue 1
- Características: media goleadora intermedia entre Premier y Serie A.
- PSG dominante crea distribución bimodal: predictabilidad alta para PSG, alta varianza para resto.
- Adepor 2024 hit=49.8% N=331 — coherente.

### Süper Lig (Turquía)
- Liga muy predecible para top: hit Adepor 53.3% (mejor que muchas EUR top).
- 2025 hit=62% sobre N=189 — sorprendentemente alto. Justifica `Layer 2 V12` standalone para Turquía.
- Posibles features: **promedio del rendimiento home top-3 vs resto** (Galatasaray + Fenerbahce + Besiktas concentran títulos).

### Eliteserien (Noruega)
- Liga de verano (apr-nov) — distinto al ciclo EUR/LATAM.
- Sample chico, no en backtest mayor.

### Implicación Adepor

- **No tratar Turquía como liga genérica**: hit 53-62% justifica V12 standalone.
- Noruega: validar coverage temporal + Elo calibration.

---

## Conclusión y plan operativo

### Decisiones técnicas fundamentadas POR LIGA

| Liga | Approach actual | Mejora fundamentada |
|---|---|---|
| Argentina | V0 + V13 SHADOW + Layer 3 ARG | Mantener. NO generalizar EUR features. Features régimen + liga corta. |
| Brasil | V0 | Sparse network handling. Features regionales (Cariocão/Paulistão como sub-ligas). |
| Inglaterra | V0 + Layer 3 ING | **Agregar features defensivos rolling 3-match (xG_against rival)**. |
| Italia | V0 + Layer 3 ITA | **Layer 3 X-rescue muy relevante**: tactical low-scoring → empates frecuentes. |
| Alemania | V0 + Layer 3 ALE | **Considerar EPV proxy** (Frontiers 2025) para mejorar pre-match. |
| España | V0 | xG suficiente para top. Para mid-table agregar Elo. |
| Francia | V0 | Bimodal: PSG vs resto. Modelo separado mid-table? |
| Turquía | **V12 Layer 2 standalone** ✓ | Validar 2025+ extensiones. |
| Noruega | V0 | Verificar cobertura temporal (liga de verano). |
| LATAM (Bol/Chi/Per/Ecu/Col/Ven/Uru) | V0 | Sparse network: K-factor recalibration crítica + datos de copas suplementan. |

### Bead nuevo recomendado

`[F4 sub-A] Features defensivos rolling 3-match para Inglaterra` (P3)
- Hallazgo Premier League literature: VAEP/VDEP + defensive xG_against rival últimos 3 partidos mejora predicción.
- Adepor actualmente NO captura defensiva rival explícitamente.

`[F4 sub-B] EPV proxy Bundesliga` (P3)
- Bundesliga 2025 paper: EPV pre-match supera xG pre-match.
- Implementación posible: aproximación EPV via stats existentes (poss avg, shots, accuracy).

`[F4 sub-C] Régimen detector Argentina` — ya existe como `adepor-09s` (P2).

### Pendiente próxima sesión

- Validar implementación features defensivos 3-match en motor adepor-existente.
- Investigar publicaciones recientes específicas Süper Lig Turquía (Galatasaray/Fenerbahce dominio).
- Validar Noruega Eliteserien con su ciclo temporal distinto.

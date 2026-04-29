# Papers: Modelado de Copas (Knockout + Cross-Liga)

> **Fecha:** 2026-04-28
> **Workflow:** WebSearch (fallback de Semantic Scholar API por rate limit estricto)
> **Decisión a fundamentar:** Schema enriquecido `partidos_no_liga` para Fase 2 + arquitectura motor copa para Fase 3
> **Process gate (decisión usuario 2026-04-28):** Toda decisión técnica nueva debe estar fundamentada en investigación académica.

---

## Q1: Elo rating model para fútbol

### Hallazgos consolidados

**Adaptaciones standard del Elo de ajedrez al fútbol:**

| Parámetro | Valor canónico | Fuente |
|---|---|---|
| **Home advantage** | +100 puntos al rating del local antes de calcular expected | Eloratings.net, ClubElo, World Football Elo Ratings |
| **Goal difference index** | K × 1.0 (1 gol diff), × 1.5 (2 goles), × 1.75 (3 goles), × 1.75+(N-3)/8 (≥4 goles) | World Football Elo Ratings |
| **K-factor base** | 30 (juego típico) | Eloratings.net |
| **K-factor por competición** | World Cup final: 60, Continental championship: 50, WC/continental qualifiers: 40, otros torneos: 30, amistosos: 20 | Eloratings.net |
| **Rating inicial** | 1500 (nuevos equipos) | World Football Elo Ratings |
| **Bandas de strength** | Elite >1700, Mid-table 1500-1650, Bajo <1450 | clubelo.com |

**Predictive capability:**
Estudio comparativo 2009 (Hvattum & Arntzen) sobre 8 métodos de rating: **Elo system mostró la más alta capacidad predictiva** para partidos de fútbol cuando se compara con métodos de Markov, ELO, Glicko, Bradley-Terry.

Standalone Elo: ~60% accuracy en EUR top-flight (citado en múltiples implementaciones).

### Implicación para Adepor

Para cuantificar nivel cross-liga (Fase 3), Elo adaptado al fútbol con:
- **K-factor distinto por competición**: copa internacional > copa nacional > liga
- **Home advantage** calibrado al subset de la DB (no necesariamente +100 universal)
- **Goal difference modifier** estandar 1.0/1.5/1.75/...

### Fuentes

- [World Football Elo Ratings — Wikipedia](https://en.wikipedia.org/wiki/World_Football_Elo_Ratings)
- [Football Club Elo Ratings (clubelo.com)](http://clubelo.com/) — CSV histórico free
- [Methodology — FootballDatabase](https://www.footballdatabase.com/methodology)
- [Tuning the Elo ratings: K-factor and home field advantage — opisthokonta.net](https://opisthokonta.net/?p=1387)
- [Betfair Data Scientists — Elo tutorial R](https://betfair-datascientists.github.io/modelling/soccerEloTutorialR/)
- [ratingslib — Python library con Elo implementation](https://ktalattinis.github.io/ratingslib/apidocs/ratingslib.ratings.elo.html)

---

## Q2: Knockout matches vs liga regular

### Hallazgos consolidados

**Diferencia metodológica comprobada:**

> *"In two-legged ties, the better team over 180 minutes usually wins, whereas in single-match competitions, the better team on a single night might still lose to a moment of brilliance or misfortune."*

Implica:
- **Single-leg knockout** (Copa Argentina, FA Cup, finales): mayor varianza → modelo debe inflar incertidumbre.
- **Two-leg ties** (Champions League fase eliminatoria, Libertadores knockout): predicción robusta sobre agregado 180 min.

**xG en knockouts vs liga:**
- Adjusting xG por home/away mejora predicción **16% más** que ajustar por defensa rival.
- xG models acumulados sobre series two-leg son más predictivos que single-match.

### Implicación para Adepor

Schema necesita campos para discriminar:
- `numero_partido_serie` (1 = ida, 2 = vuelta, NULL = single-match)
- `id_serie_eliminatoria` (link entre ida y vuelta)
- `agregado_local_pre`, `agregado_visita_pre` (goles acumulados pre-partido si es vuelta)
- `competicion_formato` (`liga` | `copa_grupo` | `copa_knockout_single` | `copa_knockout_two_leg`)

### Fuentes

- [arXiv 2512.00203 — Beyond Expected Goals: A Probabilistic Framework for Shot Occurrences in Soccer](https://arxiv.org/pdf/2512.00203)
- [Two-legged tie — Wikipedia](https://en.wikipedia.org/wiki/Two-legged_tie)
- [JSR — Modeling of Football Match Outcomes with Expected Goals Statistic](https://www.jsr.org/index.php/path/article/download/1116/906/6318)
- [PMC11524524 — Predicting goal probabilities with improved xG models using event sequences](https://pmc.ncbi.nlm.nih.gov/articles/PMC11524524/)
- [Champions League Knockout Stage Betting Strategy 2026](https://champions-league-bet.com/articles/knockout-stage-betting/)

---

## Q3: Cross-league strength comparison

### Hallazgos consolidados (parcial — Semantic Scholar 429)

Findings de WebSearch + literatura general:

- **Coeficientes UEFA / Conmebol**: ranking oficial de federación basado en performance acumulado de los clubes en competiciones internacionales (5-temp móvil). Provee ranking de ligas, no de clubes individuales.
- **ClubElo cross-comparison**: ratings de clubes en escala única, comparables cross-league. Calibrado vía partidos internacionales (UCL, UEL, etc.) que actúan como "puentes" entre ligas.
- **Bundesliga research (Bundesliga AI 2024-2025)**: usa xG + EPV (Expected Possession Value) sobre 3 temporadas. Best Brier RPS=0.148 con xG post-match.

### Implicación para Adepor

Cross-league strength puede modelarse de 3 formas (a comparar A/B):

1. **ClubElo CSV ingesta** (más simple): lookup club → rating histórico. Cubre EUR sólido.
2. **Elo propio sobre tu DB**: 14k partidos liga + 8k copas → calibrar K-factor + home advantage propios. Mejor para LATAM (donde ClubElo es escaso).
3. **Coef UEFA/Conmebol**: ranking de liga, no de club. Útil como prior agregado.

**Combinación recomendada (a backtest)**: Elo propio (B) calibrado sobre histórico Adepor, con seed inicial de ClubElo (A) para clubes EUR cubiertos.

### Fuentes

- [PMC12640942 — AI in Bundesliga match analysis: EPV vs xG](https://pmc.ncbi.nlm.nih.gov/articles/PMC12640942/)
- [PLOS One — Data-driven understanding on soccer team tactics: Elo rating-based trends](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0318485)
- [European Club Football Elo Rankings](https://elofootball.com/)
- [eloratings.net — World Football Elo Ratings](https://www.eloratings.net/)

### Pendiente

Re-correr Semantic Scholar API cuando rate limit ceda (puede requerir API key gratuita registrándose en api.semanticscholar.org). Query específicas:
- `cross-league soccer strength quantification` (general)
- `tournament rating bridge teams` (técnica de calibración entre poblaciones)
- `Bayesian network football knockout prediction`

---

## Conclusión y decisiones técnicas fundamentadas

### Decisión 1 (FASE 2): Schema enriquecido `partidos_no_liga`

Agregar columnas:

```sql
ALTER TABLE partidos_no_liga ADD COLUMN liga_local TEXT;
ALTER TABLE partidos_no_liga ADD COLUMN liga_visita TEXT;
ALTER TABLE partidos_no_liga ADD COLUMN competicion_formato TEXT;
-- Valores: 'liga' (no debería estar en esta tabla),
--          'copa_grupo', 'copa_knockout_single', 'copa_knockout_two_leg'
ALTER TABLE partidos_no_liga ADD COLUMN id_serie_eliminatoria TEXT;
ALTER TABLE partidos_no_liga ADD COLUMN numero_partido_serie INTEGER;
-- 1 = ida, 2 = vuelta, NULL = single-match
ALTER TABLE partidos_no_liga ADD COLUMN agregado_local_pre INTEGER;
ALTER TABLE partidos_no_liga ADD COLUMN agregado_visita_pre INTEGER;
```

**Justificación:**
- `liga_local`/`liga_visita`: necesarios para cuantificar nivel cross-liga (Q3 implicación).
- `competicion_formato`: discriminar single vs two-leg para incertidumbre del modelo (Q2 implicación).
- `id_serie_eliminatoria` + `numero_partido_serie` + `agregado_*_pre`: tracking de eliminatorias 2-legs (literatura two-leg ties).

[REF: docs/papers/copa_modelado.md Q2]

### Decisión 2 (FASE 3): Cuantificación nivel cross-liga

Implementar **Elo propio (Opción B)** con calibración sobre histórico Adepor 14k+8k partidos, parámetros **fundamentados en Q1**:
- Home advantage: +100 default, recalibrar via grid search sobre Adepor.
- Goal difference modifier: 1.0/1.5/1.75/...+(N-3)/8 (estandar Eloratings).
- K-factor por competición: liga=20, copa_nacional=30, copa_internacional_grupo=40, copa_internacional_knockout=50, finales=60.

**Validación:** seed inicial via ClubElo CSV para clubes EUR cubiertos (cross-check), backtest sobre 8k partidos copa con yield + Brier.

[REF: docs/papers/copa_modelado.md Q1+Q3]

### Decisión 3 (FASE 3): Modelo motor copa

Variante de motor V0 con inputs adicionales:
- `elo_local_pre`, `elo_visita_pre` (rating al momento del partido)
- `delta_elo` (local − visita)
- `competicion_formato` (categórico)
- `nivel_liga_local`, `nivel_liga_visita` (factor agregado de Coef UEFA/Conmebol)

Modelo: regresión multinomial (similar V12) sobre features [xg_l, xg_v, elo_diff, formato_dummy, nivel_dif] entrenado sobre 8k partidos copa OOS.

**Cuotas validation:** bloqueado por API Pro (`adepor-4tb`, `adepor-8je`) — modelo calibrado por Brier inicialmente, yield diferido.

[REF: docs/papers/copa_modelado.md Q1+Q2+Q3]

---

## Próximos pasos research

- Semantic Scholar API con key (cuando rate limit ceda)
- Búsqueda específica papers sobre **calibración Elo cuando muestras son escasas** (relevante LATAM Adepor)
- Búsqueda específica **regularización Elo via Bayesian priors** (e.g., con Coef UEFA/Conmebol como prior)

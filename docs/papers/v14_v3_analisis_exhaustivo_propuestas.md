# V14 v3 — Análisis exhaustivo + propuestas mejora motor

> **Fecha:** 2026-04-29
> **Alcance:** análisis OOS/IS por (año × país × edición × bin4/bin8/bin12) +
> investigación académica acumulada + auditoría arquitectura + propuestas ranked.
> **Convención:** IS 2026 = año en curso; OOS = 2022-2025.

---

## I. ESTADO ACTUAL DEL PROYECTO (auditoría)

### Arquitectura motor xG

```
Stats post-partido → β_sot·sot + 0.010·shots_off + 0.030·corners → xG_OLS
xG_OLS → EMA per equipo (alpha 0.85) → xG_pre_partido predicho
xG_pre × Poisson DC (rho per liga) → prob 1X2 + prob O/U
× gamma_1x2 display correction
```

### Filtros V5.2 productivos

- **M.1**: liga in {ARG, BRA, ENG, NOR, TUR}
- **M.2**: n_acum_l < 60 (calibrado 2024)
- **M.3**: DESACTIVADO (calibración OOS no transfiere)
- **Layer 2 V12**: arch_decision_per_liga={Turquia: V12} standalone
- **Layer 3 H4 X-rescue**: ARG+ITA+ING+ALE thresh 0.35

### Hallazgos cuantitativos sesión 2026-04-29

#### β_sot per liga calibrado SOBREESTIMA todo

| Liga | β actual | β recom | Δ |
|---|---|---|---|
| Inglaterra | 0.352 | 0.272 | -23% |
| Italia | 0.352 | 0.260 | -26% |
| España | 0.352 | 0.257 | -27% |
| Francia | 0.352 | 0.268 | -24% |
| Alemania | 0.352 | 0.285 | -19% |
| Turquía | 0.414 | 0.360 | -13% |
| Holanda | 0.352 | 0.265 | -25% |
| Argentina | 0.331 | 0.210 | -37% |
| Brasil | 0.331 | 0.216 | -35% |

#### β_sot per copa internacional

| Edición | β recom OOS | Conv vs Premier | Drift IS 2026 |
|---|---|---|---|
| Champions League | 0.279 | 100% | +8% alcista |
| Europa League | 0.266 | 97% | -5% |
| Conference League | 0.272 | 99% | estable |
| Libertadores | 0.238 | 89% | **-17% bajista** |
| Sudamericana | 0.237 | 89% | **-15% bajista** |

#### Bins temporales — shifts IS 2026 detectados

**bin4 fuerte:**
- Italia bin1: -17% (defensivización inicio temporada)

**bin8 fuerte:**
- Argentina bin2: **-24% bajista** (cambio formato Apertura impact)
- España bin5+7: **+23% ALCISTA** (mid-season productivo)
- Turquía bin8: -22%
- Italia bin1+2: -16-19% bajista

**bin12 fuerte (más granular):**
- **Turquía bin9: -32% bajista** ★
- **Francia bin3: +32% alcista** ★
- Italia bin3: -26% bajista
- España bin7+10: +22-25% alcista
- Argentina bin3: -22% bajista

### Datos disponibles

| Fuente | N | Cobertura |
|---|---|---|
| `cuotas_historicas_fdco` | 23,599 | 8 EU 2022-26 + ARG/BRA 2012-26 |
| `stats_partidos_no_liga` | 3,979+ | UEFA + LATAM int + EU domésticas (ESPN summary) |
| `partidos_historico_externo` | 14,489 | Ligas 2021-24 con stats |
| `partidos_backtest` | 612 | IS 2026 con cuotas + stats |
| `picks_shadow_v14_copa` | 9,300 | V14 v2 SHADOW backfill |

---

## II. INVESTIGACIÓN ACADÉMICA ACUMULADA (sesiones múltiples)

### Papers fundacionales con citation count alto

| Paper | Cits | Aplicación Adepor |
|---|---|---|
| **Zou & Hastie 2005** — Elastic Net Regularization (J. Royal Stat. Soc. B) | 20,655 | StandardScaler obligatorio L2. Aplicado V14 v2. |
| **Efron LARS 2004** (Annals of Statistics) | 9,459 | Marco regularization general |
| **Gelman 2008** — Weakly informative prior LR (Annals of Applied Stats) | 1,755 | LR específico, scaling features mean=0 sd=0.5. Considerar prior bayesiano V14 v3 |
| **Baio & Blangiardo 2010** — Bayesian hierarchical football (J. Applied Stats) | 158 | Partial pooling teams. Frontiers 2025 cita. C.3 si N≥6 meses SHADOW |
| **Boshnakov-Kharrat-McHale 2017** — Bivariate Weibull count (Int. J. Forecasting) | 110 | Alternativa Poisson, sin xG. Backup V14 v3 |
| **Constantinou-Fenton 2012** — Scoring Rules football (J. Quant. Anal. Sports) | 82 | Brier alternativos (de Finetti, Rank Probability Score) |
| **Constantinou — Dolores 2018** (Machine Learning) | 80 | Cross-league prediction (similar a V14 cross-copa) |
| **PMC10075453 — Expected goals improving model performance** | 80 | xG meta-analysis; player value top feature |
| **Berrar-Lopes-Dubitzky 2018** — Domain knowledge soccer (ML) | 88 | Feature engineering manual + Open Soccer DB |
| **Carling 2019 PLoS ONE** — Six weeks congested play | 54 | Fixture congestion → conversion shot→goal cae |
| **Sports Medicine 2022** — Fixture congestion + Injury | 46 | Schedule effect documentado |
| **Davis et al. 2024 ML journal** — Sports analytics methodology | 53 | Concept drift recommends walk-forward + rolling retraining |
| **Frontiers 2025 Fontana** — Bayesian football | (recent) | Replicación moderna Baio-Blangiardo. N=300 train, 80 test |
| **Hewitt-Karakuş 2023 (arXiv 2301.13052)** — Player adjusted xG | (arXiv) | StandardScaler + LR convención xG-ML |
| **Cavus-Biecek 2022 (arXiv 2206.07212)** — Explainable xG | (arXiv) | Distance-to-goal dominante; player value top |

### Hallazgos consensuados literatura

1. **β_sot Premier-style 0.32-0.35** documentado (Hewitt 2023). Adepor default 0.352 está bien para Premier, **mal para resto**.
2. **Concept drift sports REAL** (Davis 2024): walk-forward + rolling required. Coincide con shifts detectados IS 2026.
3. **Fixture congestion → performance decline** (Carling 2019): explica valles bin8/bin12 mid-season.
4. **Bayesian hierarchical (Baio 2010, Frontiers 2025) RESUELVE cold-start** sin filtros explícitos (partial pooling). Backlog C.3.
5. **xG calibration: gamma per liga es práctica común** (PMC 2023).
6. **Possession dominance predictor fuerte UEFA** (Cavus-Biecek 2022 confirma).

### COVID 2020-21 régimen documentado

Frontiers SAL 2021, PMC 2021, ScienceDirect 2023 — home advantage redujo 48% sin público. **No afecta Adepor (data 2022+)** pero confirma que régimen REAL existe.

---

## III. PROPUESTAS MEJORA RANKED (impacto / esfuerzo)

### P0 — Aplicar β_sot recom (PROPOSAL adepor-3py)

**Impacto**: yield contrafactual +3.68pp IS 2026 EU agregado (techo teórico).

**Esfuerzo**: 30 min código (UPDATE config_motor_valores.beta_sot per scope) + 4 sem SHADOW.

**Bloqueantes**: PROPOSAL formal aprobación + validación SHADOW dedicada.

**Persistido**: `config_motor_valores.beta_sot_recom_calibrado_v2` + `beta_sot_recom_copa_internacional_v2`.

### P0 — Promover V14 v2 a producción (PROPOSAL adepor-141)

**Impacto**: V14 v2 SHADOW subset apostable hit 69.4% (Wilson_lo 65.7%). +21.6pp vs pool. **TRIGGER MET** N≥200.

**Esfuerzo**: F2-sub-15 fase 2 (cross-liga EMA + bias hook). 2-3 sesiones de trabajo.

**Bloqueantes**: cross-liga EMA architecture rewrite necesaria.

### P1 — Bias temporal bin4/bin8/bin12 al motor (NUEVO sesión actual)

**Impacto**: ajuste contextual por momento de temporada. Italia bin1 -17%, España bin7 +25%.

**Esfuerzo**: hook en motor_calculadora durante predict_xg + recalibración mensual cron.

**Persistido**: `v14_v3_bias_bin4_ligas`, `v14_v3_bias_bin8_ligas`, `v14_v3_bias_bin12_ligas`.

### P1 — Tabla shadow M.2 logging (adepor-9uq)

**Impacto**: desbloquear validación trigger M.2 universal vs régimen 2026 (yield +43% in-sample observado).

**Esfuerzo**: ALTER TABLE + hook motor_calculadora pre-filtro M.2. 2h.

### P2 — Possession dominance feature (V14 v3)

**Impacto**: UEFA copas predictor fuerte (UCL home-dom hit 62.5% vs 46.2% away-dom). Adepor V14 v2 actualmente no usa. **Considerar OPCIONAL solo UEFA copas**.

**Esfuerzo**: feature engineering + re-fit V14 v2 con feature adicional. 1 sesión.

**Caveat**: requiere stats live possession pre-partido (no solo histórico). Difícil de obtener para predicción ex-ante.

### P2 — Bayesian hierarchical (Baio-Blangiardo) BACKUP

**Impacto**: resolver cold-start sin filtros explícitos. Frontiers 2025 reporta 50% accuracy típica, calibración mejor.

**Esfuerzo**: rewrite completo modelo a PyMC/Stan. 5-8 sesiones.

**Decisión**: NO ahora. Backlog para si V14 v2 + bias factors no alcanza objetivos.

### P2 — Walk-forward retraining mensual (Davis 2024)

**Impacto**: detectar concept drift automáticamente. Adepor adaptive engine ya hace SGD step → falta retrain batch ventana móvil.

**Esfuerzo**: cron mensual + script `recalibrar_betas_mensual.py`. 3h.

### P3 — Constantinou-Fenton scoring rules

**Impacto**: validación más robusta que Brier. Adepor usa Brier — agregar de Finetti + RPS.

**Esfuerzo**: helper en `analisis/`. 1h.

### P3 — XGBoost ensemble baseline

**Impacto**: literatura sugiere ensemble XGBoost mejora ~3-5pp Brier vs single LR. Adepor ya tiene V14 LR + V0 Poisson; XGBoost candidato V15.

**Esfuerzo**: feature engineering completo + train XGBoost + comparar Brier. 2-3 sesiones.

**Decisión**: backlog hasta V14 v2 valide en producción.

### P3 — xT (Expected Threat) feature

**Impacto**: literatura sugiere xT > xG pre-match Bundesliga (Frontiers 2025 paper "AI in Bundesliga match analysis"). Adepor usa xG only.

**Esfuerzo**: requiere event data StatsBomb (paid) o scraping moderno. 5+ sesiones.

**Decisión**: backlog largo plazo.

---

## IV. ANÁLISIS POR PAÍS / EDICIÓN — síntesis sesión

### LIGAS EU (cuotas_historicas_fdco)

**Inglaterra** (1,859 partidos): bin4 estables (-9 a -13% IS), Premier 23-24 outlier alcista. β recom 0.272 (-23%).

**Italia** (1,860): **DEFENSIVIZACIÓN 2026** (β IS bin1-2 -16-19%). β recom 0.260.

**España** (1,850): **MID-SEASON ALCISTA 2026** (bin7+10 +22-25%). β recom 0.257.

**Francia** (1,649): bin3 +32% alcista IS (sample chico). β recom 0.268.

**Alemania** (1,502): estable, bin11 +15% alcista. β recom 0.285.

**Turquía** (1,692): bin9 **-32% bajista** (outlier). β actual 0.414 → grid yield 0.36.

**Holanda** (1,503): estable. β recom 0.267.

### LIGAS LATAM

**Argentina** (6,205 cuotas + 1,113 stats): bin1-3 IS bajista (cambio formato Apertura). β actual 0.331 (mantener).

**Brasil** (5,447 cuotas + 1,097 stats): bin1 IS +10% alcista. β actual 0.331 (yield-óptimo).

### COPA INTERNACIONAL

**UEFA top (UCL/UEL/UECL)**: conv ≈ Premier (β 0.27-0.28). UCL alcista IS, UEL/UECL estables.

**CONMEBOL (Lib/Sud)**: conv 88% Premier. Drift -15-17% IS 2026 (defensivización).

### COPA NACIONAL EU (3/4 completas post-backfill)

| Edición | β recom | Conv vs Premier | Poss_L | Insight |
|---|---|---|---|---|
| **Copa del Rey** | **0.355** | **123%** | **36.6%** | Big-3 visita y MASACRE (eficiencia max) |
| **DFB Pokal** | 0.294 | 105% | 42.2% | Bayern visita y domina |
| **Coupe de France** | 0.284 | 102% | 44.1% | PSG visita amateurs |
| **Coppa Italia** | 0.278 | 101% | 53.6% | Inter/Milan/Juve más balanceado |
| **FA Cup** | 0.261 | 96% | 50.7% | Top Premier rotan early rounds |

**Patrón unificado**: en copas con Big-3 dominantes (España/Alemania/Francia), los favoritos juegan VISITA y convierten con eficiencia ALTA. Resulta en β intermedio-alto y poss_L bajo (<45%).

**Excepciones**:
- **Coppa Italia**: poss_L 53.6% más alto (Italia tactical balance, no Big-3 abrumador)
- **FA Cup**: top Premier rotan en early rounds, conversion baja vs Premier liga

**Implicación motor V14 v3 cuando F2-sub-15 fase 2 implemente copas:**
- Copa del Rey: usar β default 0.352 (compatible)
- DFB Pokal: β 0.294
- Coupe de France: β 0.284
- Coppa Italia: β 0.278
- FA Cup: β 0.261

---

## V. ROADMAP PROPUESTO

### Fase A (próximas 4 semanas) — SHADOW VALIDATION
1. Aplicar β_recom_v2 a SHADOW dedicada
2. Loggear V14 v2 SHADOW continuo (audit mensual)
3. Validar trigger PROPOSALs adepor-3py + adepor-141
4. Tabla shadow M.2 logging (adepor-9uq)

### Fase B (mes 2-3) — F2-sub-15 fase 2
1. Cross-liga EMA en motor_calculadora
2. Hook bias factors per (liga, edición, mes, bin)
3. Implementar pick_apostable_v14_v2 como filtro M.5 candidato
4. Validar Brier + yield SHADOW vs producción

### Fase C (mes 4-6) — V14 v3
1. Possession dominance feature (UEFA only)
2. Walk-forward retraining mensual
3. Recalibrar bias factors automáticamente
4. Constantinou-Fenton scoring rules como métrica adicional

### Fase D (mes 6+) — V15 candidato
1. Bayesian hierarchical Baio-Blangiardo (cold-start sin filtros)
2. XGBoost ensemble baseline
3. xT feature engineering (si hay budget event data)

---

## VI. CAVEATS Y LIMITACIONES

1. **Yields contrafactuales son TECHO TEÓRICO** (stats post-partido conocidos pre-Poisson). Yield real con EMAs pre-partido será mucho menor.
2. **Sin cuotas para copas internacionales** (bead adepor-4tb bloqueado). V14 v2 SHADOW yield real desconocido.
3. **Sample IS 2026 chico** en muchos buckets — direccionales pero no estadísticamente bulletproof.
4. **OpenAlex search ruidoso** — papers off-topic abundan. Confiable solo cross-reference manual.
5. **Asta API** sin uso (form humano + key + espera). OpenAlex equivalente funcional.

---

## VII. PRINCIPIOS NO-NEGOCIABLES MANTENIDOS

- **SHA manifesto** `471c1c00...4ab6c` intacto (sin cambios estructura V5.2)
- **Yield NO se rompe** — todos los β recom en SHADOW
- **Filtros M.1, M.2, Layer 2, Layer 3** sin cambios productivos
- **Snapshots DB** pre-cambios estructurales

[REF: docs/papers/v14_v3_analisis_exhaustivo_propuestas.md]

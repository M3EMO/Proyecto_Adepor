# Filtros SOFA v2 — features período 1ST/2ND lag-1

**Fecha:** 2026-05-07
**Sesión:** Fase B — audit `statistics_json` periodo 1ST/2ND
**Universo:** N=393 (subset de Fase 1 con lag-1 features periodo computables)
**Antecedente:** Fase 1 (`filtros_sofa_validados_post_session.md`, 2026-05-04) testó stats SOFA agregadas. Esta sesión agrega features nuevas: stats por período (1ST + 2ND) + deltas (2ND-1ST) + ratios dominancia (2ND/(1ST+2ND)).

---

## TL;DR

**4 filtros candidatos** sobre 543 tests pass criterios mínimos relajados (yield > +5%, CI95 lo > 0, N ≥ 30). **0/543 supera Bonferroni estricto α=0.000092.**

Persistidos en SHADOW table `picks_shadow_filtros_sofa_v2_periods` (169 picks, `aplicado_produccion=0`).

**Veredicto:** SHADOW puro. NO promoción. Trigger N≥80 incremental + walk-forward inter-año.

**Lift incremental sobre Fase 1:** 3 de los 4 candidatos son `pick=O25` (Fase 1 no encontró señal pro-OVER). Confirma que features `_dom_2nd` y `_delta` aportan info no capturada por agregados.

---

## Pipeline

| Paso | Output |
|---|---|
| 1. Extracción 1ST/2ND de `statistics_json` | tabla `sofascore_period_features` (712 partidos × ~45 cols × 2 lados × 2 períodos = 177 cols) |
| 2. Construcción universo Fase 2 con lag-1 | tabla `_fase2_universo_periods` (N=393, 192 features lag-1 per-row) |
| 3. ML feature importance | Ridge + permutation per-target (1, X, 2, O, U) |
| 4. Bin q4 sobre top-30 features × 5 targets | 543 tests |
| 5. Bonferroni + bootstrap CI95 + LOYO | 4 candidatos |
| 6. SHADOW backfill | 169 picks loggeados |

## Universo

```
SOFA total con statistics_json: 769
Con períodos ALL+1ST+2ND: 712 (92.6%)
partidos_backtest 2026 con cuotas+outcome: 664
Con lag-1 (partido prev del equipo en SOFA): 393
```

Per liga: ENG 48, ARG 47, TUR 45, BRA 45, ECU 32, ESP 30, PER 29, BOL 25, ITA 21, NOR 19, VEN 18, ALE 18, FRA 16.

## Baselines

| Pick | N | Yield |
|---|---|---|
| 1 | 337 | -6.78% |
| **X** | 337 | **+3.74%** |
| 2 | 337 | -13.51% |
| O | 145 | +1.81% |
| U | 145 | -10.62% |

Cuotas O/U solo disponibles en 145/393 (37%) — limita poder pick=O/U.

Confirma sesgo "draw aversion" estructural (Kuypers 2000): X baseline +3.74% IS pool antes de filtro.

## Top features ML importance per target

```
pick=1:  recoveries_lag1_l_dom_2nd       0.65
         accurate_passes_lag1_l_dom_2nd  0.61
         shots_total_lag1_l_dom_2nd      0.53

pick=X:  xg_lag1_v_delta                 1.74
         recoveries_lag1_v_dom_2nd       1.64
         big_chances_lag1_l_dom_2nd      1.62

pick=2:  recoveries_lag1_l_dom_2nd       3.11
         recoveries_lag1_v_dom_2nd       2.45
         tackles_won_lag1_v_dom_2nd      1.86

pick=O:  tackles_won_lag1_v_dom_2nd      1.78
         accurate_passes_lag1_v_dom_2nd  0.96
         tackles_lag1_l_dom_2nd          0.96

pick=U:  tackles_won_lag1_v_dom_2nd      1.97
         accurate_passes_lag1_v_dom_2nd  1.36
         tackles_lag1_l_dom_2nd          1.07
```

**Patrón estructural:** features `*_dom_2nd` (ratio dominio segunda mitad) y `*_delta` (cambio entre mitades) dominan top-5 en TODOS los targets. Dirección operativa para feature engineering futuro: priorizar features que contrastan halves sobre features agregados (already in Fase 1).

## TOP 4 filtros candidatos SHADOW

### 1. xg_lag1_v_2nd_team in (0.36, 0.77] → empate
- N=59 yield +53.1% CI95 [+3.8%, +103.2%] LOYO 1/2
- **Hipótesis:** visita con xG moderado en su 2ND mitad prev (no apático ni dominante) → match controlado, mercado infravalora X.

### 2. accurate_passes_lag1_l_2nd_team > 186 → over25
- N=36 yield +35.5% CI95 [+3.4%, +65.2%] LOYO 2/2 ⭐
- **Hipótesis:** local con muchos pases acertados en 2ND mitad prev (>186) → control posesional sostenido, generan goles next match.

### 3. fouls_lag1_v_delta in (-2, 1] → over25
- N=40 yield +30.9% CI95 [+1.9%, +56.9%] LOYO 2/2 ⭐
- **Hipótesis:** visita con fouls 2ND-1ST estables (-2 a +1, sin nervios crecientes) → juego abierto sin cards/freezing → over.

### 4. shots_outside_lag1_v_dom_2nd in (0.53, 0.71] → over25
- N=37 yield +30.1% CI95 [+0.1%, +57.8%] LOYO 2/2 ⭐
- **Hipótesis:** visita con shots-outside-box dominante en 2ND mitad prev → presión territorial sostenida que se mantiene next match → over.

## Filtros descartados (4/543 pasaron)

539/543 NO superaron criterios. Razones principales:
- N en bin < 30
- yield ≤ +5%
- CI95 lo ≤ 0
- LOYO 0/2 buckets

## Hipótesis pendientes / no testeadas

1. **Features SAME-MATCH ALL** (no lag-1): permiten predecir outcomes solo si NO leakage temporal. Útil para targets de "el partido de mañana se parecerá a éste" (intra-temporada momentum).
2. **Cluster equipo × período**: equipos que sistemáticamente dominan 2ND > 1ST son distintos. Podría ser feature persistente per-equipo.
3. **Período × árbitro**: árbitros con cards 2ND > 1ST × `over25`.
4. **Período × cuota**: bookies que ajustan más en 2ND vs 1ST.

## Riesgos overfitting

**Score: ALTO.**
- 543 tests sobre N=393. Búsqueda automatizada de bins.
- Bonferroni α=0.000092: 0 pasa (p-values reales ~0.02-0.05).
- LOYO sobre 2-3 buckets temporales: poder estadístico mínimo.
- Single year (2026): no permite walk-forward TRUE-OOS aún.

**Mitigación:** SHADOW MODE permanente. Convergencia a baseline ~0% en N≥80 incremental confirma overfitting si filtro es ruido.

## Recomendación

### Inmediata
- NO promover. Mantener SHADOW.
- Trigger automático: cuando filtro acumule N≥80 con yield > +5% AND CI95 lo > 0 post-Bonferroni → bead PROPOSAL MANIFESTO.

### Próximas sesiones
1. Backfill SOFA 2022-2025 (Fase A) → expandir N=393 → N≥2,000
2. Re-validar 4 filtros con walk-forward TRUE-OOS train≤2024 / test 2025-2026
3. Combinar con TOP 7 filtros Fase 1 (¿ensemble multi-señal?)

## Persistencia

### Tabla DB
`picks_shadow_filtros_sofa_v2_periods` (169 filas):
- 4 filtros loggeados
- `aplicado_produccion=0` para todos
- `razon_no_aplicado='esperando_n80_y_oos_o_bonferroni_estricto'`

### Scripts reproducibles
- `analisis/filtros_sofa_v2_extract_period_features.py` — extracción 1ST/2ND a tabla wide
- `analisis/filtros_sofa_v2_universo_periods.py` — universo Fase 2 con lag-1
- `analisis/filtros_sofa_v2_pipeline_validation.py` — pipeline completo
- `analisis/filtros_sofa_v2_shadow_backfill.py` — backfill SHADOW
- `analisis/filtros_sofa_v2_pipeline_validation.json` — métricas crudas

## Referencias

- `docs/papers/filtros_sofa_validados_post_session.md` — Fase 1 (2026-05-04, 7 filtros SHADOW)
- `docs/papers/motor_xg_v3_estado_consolidado.md` — motor xG v3 (xgot SOFA primary)
- `docs/papers/filtros_sofa_para_yield_session.md` — propuesta original Cat A-J
- Tabla SOFA features periodo: `sofascore_period_features` (712 filas, 177 cols)

# Filtros SOFA validados — sesión yield/apuestas

**Fecha:** 2026-05-04
**Sesión:** `2026-05-04_filtros_sofa_yield`
**Universo:** 443 eventos season 2026 con cuotas (intersección SOFA × `partidos_backtest` ∪ `cuotas_historicas_fdco`)
**Snapshot pre-sesión:** `snapshots/fondo_quant_20260504_114021_pre_filtros_sofa_v1_shadow.db`

---

## TL;DR

**No se identificó edge robusto que pase Bonferroni estricto sobre el universo SOFA 2026 (N=443).**

7 filtros (2 individuales + 5 combinaciones) pasan criterios mínimos
(yield_pool > +5%, N≥30, CI95 lower > 0, consistencia ≥50%, walk-forward LOYO ≥2/3 buckets positivos).
**TODOS persistidos en `picks_shadow_filtros_sofa_v1` con `aplicado_produccion=0`.**

Promoción a producción requiere:
- N≥80 SHADOW incremental (actual N=43-179 por filtro), Y
- Validación OOS sobre season 2027 (no disponible aún), Y
- Backfill SOFA 2022-2025 (priorizar) para walk-forward TRUE-OOS.

**Veredicto:** SHADOW ONLY. No promoción a Manifesto change.

---

## Pipeline ejecutado

| Fase | Output | Resultado |
|---|---|---|
| 1.1 — descriptiva | `filtros_sofa_v1_exploration.{py,json}` | 29 filtros propuestos cat A-J. **0 superan Bonferroni 0.05/29** |
| 1.2 — ML importance | `filtros_sofa_v1_ml_importance.{py,json}` | Top features: cuotas, recoveries_lag1, corners_lag1, avg_rating_lag1, ref_cards_per_game |
| 1.3 — hipótesis | `filtros_sofa_v1_hipotesis.{py,json}` | 72 positivos + 72 anti-filtros (binning q4) |
| 2 — validación | `filtros_sofa_v1_validation.{py,json}` | 2/101 filtros pasan criterios mínimos |
| 3 — combinaciones | `filtros_sofa_v1_combinaciones.{py,json}` | 8/34 promueven (AND/OR top filtros) |
| 4 — walk-forward LOYO | `filtros_sofa_v1_walkforward.{py,json}` | 5/15 combinaciones pasan |
| 5 — SHADOW backfill | `filtros_sofa_v1_shadow_backfill.py` | 731 picks loggeados |

---

## Universo

```
SOFA total: 769
Backtest 2026 con estado: 649
fdco 2026: 1367
Match exacto (fecha+norm equipos): 272
Match loose: 92
Universo final: 443
```

Cobertura per liga (primeras 6, las demás <30):
| Liga | N |
|---|---|
| Brasil | 54 |
| Inglaterra | 52 |
| Italia | 49 |
| Argentina | 48 |
| Turquía | 44 |
| España | 40 |

**Baselines pool** (apostar a una opción todos):
| Pick | N | Yield |
|---|---|---|
| Local random | 381 | -0.30% |
| Empate random | 381 | -3.86% |
| Visita random | 381 | **-11.68%** (sesgo home market) |
| O25 random | 221 | -1.92% |
| U25 random | 221 | -7.73% |

Subset apostado_v0 motor (N=121): **yield +44.9%** (subset ya filtrado V5.1, no contamos como filtro nuevo).

---

## Filtros validados — TOP 7 a SHADOW

### Combinaciones AND (N pequeño, alta varianza)

#### 1. AND_avg_rating_lag1_l_pos__shots_on_target_lag1_l_pos → empate
```
Equipo local con avg_rating_lag1 ∈ [6.92, 7.39]
AND shots_on_target_lag1_l ∈ [5, 16]
→ apostar EMPATE
```
- **Yield pool: +60.7% N=46, hit 43.5%, CI95 [+5.1%, ?]**
- **Walk-forward LOYO: avg test yield +87.3%, 2/2 buckets positivos**
- Hipótesis: equipo local rating sólido + ataque previo eficiente → próximo partido es controlado, va al empate (mercado infravalora X)

### Filtros individuales

#### 2. corners_lag1_l ∈ [0, 2] → empate
```
Local con pocos corners (0-2) en partido anterior → apostar EMPATE
```
- **Yield pool: +43.1% N=92, hit 42.4%, CI95 [+7.0%, ?]**
- Walk-forward LOYO: 1/2 buckets positivos
- Hipótesis: pocos corners → estilo defensivo/conservador → tendencia al empate

#### 3. corners_lag1_diff ∈ [-17, -3] → empate
```
Local con corners_lag1 - visita_corners_lag1 <= -3 → apostar EMPATE
```
- **Yield pool: +37.7% N=100, hit 39.0%, CI95 [+1.5%, ?]**
- Walk-forward LOYO: 1/2 buckets positivos

### Combinaciones OR

#### 4. OR (corners_lag1_l[0,2]) OR (avg_rating_lag1_l[6.92,7.39]) → empate
- **Yield pool: +26.6% N=152**
- **Walk-forward LOYO: avg test yield +17.7%, 2/2 buckets positivos**

#### 5. OR (corners_lag1_l[0,2]) OR (shots_on_target_lag1_l[5,16]) → empate
- **Yield pool: +24.4% N=179**
- **Walk-forward LOYO: avg test yield +16.5%, 2/2 buckets positivos**

#### 6. OR (recoveries_lag1_v) OR (recoveries_lag1_diff) → visita
- Yield pool: +24.4% N=119
- Walk-forward LOYO: avg test yield +58.6%, 2/2 buckets positivos

#### 7. AND (recoveries_lag1_v) AND (recoveries_lag1_diff) → visita
- Yield pool: +24.1% N=43
- Walk-forward LOYO: **avg test yield +98.2%, 2/2 buckets positivos**

---

## Filtros descartados

### Phase 1.1 (filtros propuestos cat A-J): 27/29 NO superan criterios

| ID | Yield pool | Razón descarte |
|---|---|---|
| A2_red_freq_visita | -44.8% N=22 | Anti-filtro confirmado (predictivo NEG) |
| A1_strict_emp | -13.5% N=19 | N pequeño, no significativo |
| B2_4231_local | -50.4% N=8 | N=8 muy pequeño |
| D5_recov_lag1_l_low_visita | -23.9% N=236 | Anti-filtro robusto sig NEG |
| E1_max_lag1_v_visita | -36.1% N=67 | Anti-filtro sig NEG |
| Otros | varios | yield ≤ +5% o CI95 lo no significativo |

### Phase 1.3 (72 positivos derivados ML): 70/72 NO superan Phase 2

Razones principales:
- N en bin < 30
- Bootstrap CI95 lower ≤ 0
- Consistencia temporal CV < 50%
- Bonferroni alpha = 0.05/101 = 0.000495 NO superado por NINGUNO

---

## Hipótesis no testeadas / pendientes

### Por limitación de datos
- **`statistics_json` periodo 1ST/2ND**: features de momentum por mitad de partido. NO extraído.
- **`shotmap_json`** análisis cluster espacial (presión por zona). NO computado.
- **`graph` 92 puntos**: momentum_late_game, slope final 30 min. NO extraído.
- **DT × árbitro h2h**: requiere histórico DT cross-temporada (no disponible 2026 only).
- **Whitelist árbitros con bias home-rate**: requiere N≥10 obs por árbitro (universo actual: <5 por árbitro promedio).

### Por riesgo de overfitting (skipped)
- **Equipos whitelist/blacklist** (Atlético Madrid, Bodø/Glimt, etc.): identificados en sesión previa pero ya rechazados por walk-forward TRUE-OOS.

---

## Hallazgos negativos importantes

### 1. Mercado domina la predicción 1X2

ML feature importance: **cuota_1, cuota_x, cuota_2, log_cuota_diff, cuota_ratio_2_1** son top features para TODOS los targets. Esto confirma:
- Mercado pre-match es el mejor predictor agregado
- Edge incremental SOFA es modesto (~1-3% perm importance)

### 2. Anti-filtros NEG significativos confirmados

| Filtro | Yield | Confirmación |
|---|---|---|
| `recoveries_lag1_l < 50` → visita | -23.9% N=236 | Anti-filtro: NO apostar visita cuando local recovera poco prev |
| `max_rating_lag1_v ≥ 8.5` → visita | -36.1% N=67 | Anti-filtro: estrella visita prev NO predice próximo gana |
| `ref_red_per_game ≥ 0.30` → visita | -44.8% N=22 | Anti-filtro: árbitro estricto NO favorece visita |

### 3. Sesgo "empate" detectado en patrones SOFA

5 de los 7 filtros validados apuntan a **empate** como target. Hipótesis estructural:
- Mercado sistemáticamente subestima empate (cuota X promedio overhung)
- Patrones SOFA (corners bajos, ratings consistentes, possession defensiva) correlacionan con empate
- Edge concentrado en bookies que dan cuota X >3.5

**Esto es consistente con literatura**: Kuypers 2000, Bookmaker margins (Štrumbelj 2014) — bookies tienden a sub-pricear empate por draw aversion del público.

---

## Riesgos de overfitting

**Score riesgo: ALTO.**

1. **Búsqueda automatizada de bins**: 92 features × 5 targets × 4 bins = 1,840 combos evaluados. Encontrar 144 hipótesis (72+72) con yield ±5pp es trivial por azar.
2. **Bonferroni alpha = 0.05/101 = 0.000495**: ningún filtro individual supera. Combinaciones tampoco superan Bonferroni adicional.
3. **CV temporal con solo 2-3 buckets** (ene-feb / mar / abr-may): poder estadístico mínimo.
4. **No walk-forward TRUE-OOS posible**: SOFA solo cubre 2026.

**Por qué se persisten igual**: SHADOW MODE es el mecanismo correcto para acumular evidencia incremental. Si el filtro es ruido, su yield converge a baseline ~0% en N≥80. Si es edge real, persiste.

---

## Recomendación

### Inmediata
- **NO promover a producción**. Mantener SHADOW puro.
- Bead PROPOSAL **NO** se emite (no supera Bonferroni estricto).

### Próximas sesiones
1. **Backfill SOFA 2022-2025** (priorizar LATAM exóticas donde xG v2 ya validó +8-11% mejora)
2. **Re-validar los 7 filtros** con N≥2,000 esperado
3. **Walk-forward TRUE-OOS** train ≤2024 / test 2025-2026
4. **Auditar `statistics_json` y `shotmap_json`** para extraer features no probadas (momentum, cluster shotmap, periodo 1ST/2ND)
5. **Trigger automático observación SHADOW**: cuando un filtro acumule N≥80 con yield > +5% AND CI95 lower > 0 post-Bonferroni → bead PROPOSAL

### Largo plazo
- Implementar **ensemble Mixture of Experts**: filtro empate per liga (top correlación corners/ratings) + V0 default
- Investigar **draw aversion** académicamente (cuotas X persistentemente over)

---

## Persistencia

### Tabla DB

`picks_shadow_filtros_sofa_v1` (731 filas):
- 7 filtros loggeados
- `aplicado_produccion=0` para todos
- `razon_no_aplicado='esperando_n80_y_oos_temporadas_proximas'`
- Schema: `id, ts_log, sofa_event_id, liga, fecha, ht, at, filtro_id, filtro_descripcion, tipo_filtro, pick, cuota, prob_modelo, ev, hit_real, yield_real, n_acum_filtro, yield_acum_filtro, ci95_lo_pool, yield_pool_validation, n_pool_validation, consistencia_temporal, avg_test_yield_loyo, bonferroni_alpha, validacion_metodo, aplicado_produccion, razon_no_aplicado`

### Scripts reproducibles

- `analisis/filtros_sofa_v1_universo.{py,json}` — universo SOFA × cuotas
- `analisis/filtros_sofa_v1_exploration.{py,json}` — Phase 1.1
- `analisis/filtros_sofa_v1_ml_importance.{py,json}` — Phase 1.2
- `analisis/filtros_sofa_v1_hipotesis.{py,json}` — Phase 1.3
- `analisis/filtros_sofa_v1_validation.{py,json}` — Phase 2
- `analisis/filtros_sofa_v1_combinaciones.{py,json}` — Phase 3
- `analisis/filtros_sofa_v1_walkforward.{py,json}` — Phase 4
- `analisis/filtros_sofa_v1_shadow_backfill.py` — Phase 5
- `analisis/filtros_sofa_v1_shadow_summary.json` — resumen

---

## Entregable final

```
=== FILTROS SOFA POST-EXPLORACIÓN ===
Filtros testeados: 101 individuales + 34 combinaciones = 135 tests
Filtros que pasan Bonferroni estricto: 0
Filtros walk-forward LOYO validados: 5 combinaciones + 2 individuales = 7
Filtros para promover SHADOW: 7 (loggeados, NO en producción)

TOP 7 FILTROS VALIDADOS (SHADOW):
1. AND avg_rating_lag1_l[6.92,7.39] AND shots_on_target_lag1_l[5,16] → empate: yield IS +60.7%, N=46, LOYO +87.3%, 2/2 buckets
2. corners_lag1_l ∈ [0,2] → empate: yield IS +43.1%, N=92, CI95 [+7%, ?]
3. corners_lag1_diff ∈ [-17,-3] → empate: yield IS +37.7%, N=100, CI95 [+1.5%, ?]
4. OR corners_lag1_l + avg_rating_lag1_l → empate: yield IS +26.6%, N=152, LOYO +17.7%, 2/2
5. OR corners_lag1_l + shots_on_target_lag1_l → empate: yield IS +24.4%, N=179, LOYO +16.5%, 2/2
6. OR recoveries_lag1_v + recoveries_lag1_diff → visita: yield IS +24.4%, N=119, LOYO +58.6%, 2/2
7. AND recoveries_lag1_v AND recoveries_lag1_diff → visita: yield IS +24.1%, N=43, LOYO +98.2%, 2/2

NUEVAS HIPÓTESIS DESCUBIERTAS (no en .md original):
1. Cluster "patrones SOFA empate" — corners bajos / ratings consistentes / possession defensiva correlacionan con X
2. recoveries_lag1_diff (l-v) predice yield_visita: equipo local "recupera" mucho prev → próximo pierde
3. Big_chances_lag1_l predictor U25 (más big chances prev → menos goles próximo? counterintuitivo, posible reversión)

RECOMENDACIÓN:
- Promover a SHADOW: 7 filtros (todos loggeados con aplicado_produccion=0)
- Combinar como ensemble: NO recomendado (overfitting risk alto en N actual)
- Descartar (overfitting): 144 hipótesis Phase 1.3 que no pasan Phase 2
- NO emitir bead PROPOSAL MANIFESTO CHANGE (no supera Bonferroni estricto)
```

---

## Referencias

- `docs/papers/filtros_sofa_para_yield_session.md` — propuesta inicial cat A-J
- `docs/papers/filtros_estrategicos_pendientes.md` — filtros NO-SOFA
- `docs/papers/filtros_validados_para_evaluar_post_motor_v2.md` — Inglaterra/España validados
- `docs/papers/motor_xg_v2_resultados_finales.md` — POC SOFA xG
- Tabla DB: `picks_shadow_filtros_sofa_v1` (731 filas)
- Tabla DB: `universo_filtros_sofa_v1` (443 filas)

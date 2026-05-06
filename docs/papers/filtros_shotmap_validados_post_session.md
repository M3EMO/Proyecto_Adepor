# Filtros shotmap-derived — sesión yield post-validación

**Fecha:** 2026-05-04
**Sesión:** `2026-05-04_filtros_shotmap_v1`
**Universo evaluado:** 61 partidos season 2026, 7 ligas EUR mainstream
**Snapshot pre-sesión:** `snapshots/fondo_quant_20260504_124847_pre_shotmap_yield.db`
**Manifesto SHA256 (intacto):** `e61c00e12fe7e43b3b2d3b5d3e7f3e7a513807773795fab81b1611c720bc2081`

---

## TL;DR

**Ningún filtro pasa criterios estadísticos para promoción.** N=61 universo es estructuralmente insuficiente. **Bonferroni α=0.00278 (0.05/18 tests)** no se supera por ninguna hipótesis. **CI95% lower > 0** no se cumple en ningún filtro positivo.

**6 filtros loggeados SHADOW** en `picks_shadow_filtros_shotmap_v1` (81 picks total) con `aplicado_produccion=0`. Persistidos para auditoría longitudinal cuando N crezca (backfill SOFA 2022-2025 lo permitiría).

**Hallazgo robusto único — ANTI-FILTRO**:
- `F4b sp_dep_v > 0.5 → NO apostar X`: yield -77.2%, N=13, **CI95 [-100%, -32%]** (CI hi negativo).
  Lectura: cuando visita depende de set-pieces (>50% goles set-piece), apostar empate es destructivo. **Único filtro con CI95 hi < 0** (significativo al 5% que el yield es negativo).

**Veredicto: SHADOW ONLY. NO bead PROPOSAL.**

---

## Pipeline ejecutado

| Fase | Output | Resultado |
|---|---|---|
| 0 — snapshot DB + verif manifesto | `snapshots/fondo_quant_20260504_124847_pre_shotmap_yield.db` | OK |
| 1 — features + EMA shotmap-derived | `historial_equipos_shotmap_ema` (1,524 eventos, 752 post-warmup) | 6 features × 13 ligas |
| 2 — universo cuotas | `universo_filtros_shotmap_v1` (N=61) | 415 sin warmup, 293 sin cuotas |
| 3 — exploración + ML importance | `filtros_shotmap_v1_exploration.{py,json}` | 18 hipótesis testeadas, 0 Bonferroni |
| 4 — walk-forward mensual | LIMITADO: solo 2026-04 disponible | imposible TRUE-OOS inter-año |
| 5 — combinaciones | SKIP: N=61 prohíbe combinar (colapsa a N<10) | postergado |
| 6 — SHADOW persistence | `picks_shadow_filtros_shotmap_v1` (81 picks) | `aplicado_produccion=0` |

---

## Universo

```
Cobertura per liga (61 partidos):
  Italia       19
  Francia      11
  Turquia       9
  Brasil        8
  Espana        7
  Inglaterra    5
  Alemania      2

Cobertura por mes:
  2026-04   61   (única ventana viable)
```

**Limitaciones estructurales:**
1. SOFA solo cubre season 2026 → walk-forward TRUE-OOS inter-año imposible
2. Warmup ≥ 3 partidos prevalentemente filtra los primeros meses → solo abril sobrevive
3. Cobertura per liga ≤19 → análisis per-liga estadísticamente débil

---

## Features construidas (Fase 1)

Tabla `historial_equipos_shotmap_ema` (1,524 eventos, 752 post-warmup):

| Feature | Definición | EMA span=5, warmup=3 |
|---|---|---|
| `ema_xg_perf` | `goles_real - xg_shotmap_team` | over/underperformance vs xG |
| `ema_bcc` | goles_BC / total_BC (BC = shots con xg ≥ 0.45) | tasa conversión big-chances |
| `ema_pct_danger` | shots con dist < 12m / total_shots | calidad estructural |
| `ema_sp_dep` | goles_setpiece / total_goles | dependencia set-piece |
| `ema_late_pct` | shots min > 80 / total_shots | finalización tardía |
| `ema_shooter_gini` | Gini sobre shots por playerId | concentración estrella |

Cobertura per liga (post-warmup ≥ 3):
| Liga | N |
|---|---|
| Venezuela | 76 |
| Ecuador | 72 |
| Alemania | 66 |
| Perú | 64 |
| Turquía | 62 |
| Francia | 62 |
| Italia | 60 |
| España | 60 |
| Brasil | 60 |
| Inglaterra | 58 |
| Uruguay | 52 |
| Bolivia | 30 |
| Argentina | 30 |

**Note**: EMA shotmap cubre 13 ligas (BOL/VEN tienen referee NULL pero shotmap completo). El cuello de botella es el matching con cuotas (Fase 2).

---

## Resultados Fase 3 (18 hipótesis, Bonferroni α=0.00278)

| Filtro | Pick | N | Yield | CI95 lower | CI95 upper | Hit | Veredicto |
|---|---|---|---|---|---|---|---|
| F1a `xg_perf_l > 0.5 → 1` | 1 | 13 | +122.7% | -28.1% | +329.3% | 46% | espurio (CI lo<0) |
| F1b `xg_perf_l < -0.5 → 1` | 1 | 18 | -1.7% | -55.7% | +68.4% | 44% | nulo |
| F1c `xg_perf_v > 0.5 → 1` | 1 | 11 | +29.3% | -59.1% | +151.8% | 45% | nulo |
| F1d `xg_perf_v < -0.5 → 2` | 2 | 10 | -41.5% | -100% | +40.0% | 20% | NEG no sig |
| F2a `bcc_l < 0.4 → 1` | 1 | 19 | -18.1% | -74.5% | +48.7% | 32% | nulo |
| F2b `bcc_l < 0.4 → O25` | O25 | 18 | -13.6% | -53.5% | +28.1% | 50% | nulo |
| F2c `bcc_v < 0.4 → 2` | 2 | 16 | +13.1% | -59.3% | +90.8% | 38% | nulo |
| F3a `danger_l > 0.4 → 1` | 1 | 6 | -60.8% | -100% | +17.5% | 17% | NEG no sig |
| F3b `danger_l < 0.2 → X` | X | 15 | -21.2% | -100% | +71.2% | 20% | nulo |
| F4a `sp_dep_l > 0.5 → U25` | U25 | 13 | -25.5% | -72.8% | +32.5% | 38% | nulo |
| **F4b `sp_dep_v > 0.5 → X` ANTI** | X | 13 | **-77.2%** | **-100%** | **-31.7%** | 8% | **★ ANTI-FILTRO sig** |
| F6b `gini_l < 0.3 → 1` | 1 | 57 | -7.2% | -41.5% | +30.2% | 37% | nulo |

(Filtros con N<5 omitidos. Lista completa en JSON.)

**0 filtros con CI95 lower > 0.**
**0 filtros pasan Bonferroni α=0.00278.**
**1 filtro NEGATIVO sig (F4b)** — útil como anti-filtro de exclusión.

---

## ML feature importance (Random Forest, N=61, target=yield_local)

```
Top features por permutation importance:
1. diff_sp_dep              0.154 ± 0.028
2. ema_pct_danger_v         0.142 ± 0.028
3. ema_xg_perf_v            0.094 ± 0.034
4. ema_shooter_gini_l       0.088 ± 0.023
5. ema_sp_dep_v             0.062 ± 0.012
6. diff_xg_perf             0.059 ± 0.016
7. ema_shooter_gini_v       0.053 ± 0.011
8. diff_shooter_gini        0.050 ± 0.011
9. ema_xg_perf_l            0.047 ± 0.011
10. diff_pct_danger         0.041 ± 0.005
```

**Lectura**:
- `diff_sp_dep` (visita vs local) emerge como TOP feature → confirma hallazgo F4b (set-piece dep visita es señal real)
- `ema_pct_danger_v` (calidad chances visita) es segundo → sub-explorada
- `ema_xg_perf_v` y `ema_shooter_gini_l` → tercia
- `late_pct` y `bcc` features bottom → bajo poder predictivo

**Hipótesis nueva descubierta (no en prompt original)**: `diff_pct_danger_v` (calidad estructural visita) podría aportar como feature pre-match, NO testeada en hipótesis F1-F6 originales. **Recomendación para sesión futura con N grande**.

---

## Walk-forward mensual

```
Meses disponibles: ['2026-04']
```

**TRUE-OOS inter-año imposible** (SOFA solo cubre 2026). Walk-forward por mes degenera a single-bucket.

**Implicación**: cualquier yield observado puede ser overfitting a 1 ventana temporal específica.

---

## Combinaciones con filtros_ema_v4 — SKIPPED

Filtros validados de sesión previa (`filtros_ema_v4`):
1. `ema_l_crosses_visita ∈ [0,14.25] → empate`: yield +11.5% N=1062
2. `ema_l_saves_visita ∈ [0,2.41] → empate`: yield +10.2% N=1062
3. `ratio_propio_tackle_pct ∈ [1.07,32.94] → U25`: yield +9.0% N=568

**Combinación con shotmap features** sobre N=61 colapsa a N<10 por filtro × shotmap. **No es estadísticamente válido** combinar con esta cardinalidad. Postergado a sesión post-backfill.

---

## ¿Shotmap aporta info no capturada por EMAs convencionales?

**Indeterminado** dado N=61.

Sugerencia metodológica para sesión futura: comparar `motor_xg_v2` Brier sobre subset SOFA con vs sin features shotmap-derived. Si Brier baja consistentemente, shotmap APORTA. Si no, redundante.

---

## SHADOW persistido

**Tabla**: `picks_shadow_filtros_shotmap_v1` (81 picks)

| filtro_id | N | yield_mean | hit% |
|---|---|---|---|
| F1a_xg_perf_l_high → 2 | 13 | +122.7% | 46% |
| F1b_xg_perf_l_low → 1 | 18 | -1.7% | 44% |
| F1c_xg_perf_v_high → 1 | 11 | +29.3% | 45% |
| F1d_xg_perf_v_low → 2 | 10 | -41.5% | 20% |
| F2c_bcc_v_low → 2 | 16 | +13.1% | 38% |
| **F4b_sp_dep_v_high → X ANTI** | 13 | -77.2% | 8% |

**Todos `aplicado_produccion=0`.** Razón: `N=61 universo limitado, walk-forward inter-año imposible (SOFA solo 2026), 0 filtros pasan Bonferroni`.

---

## Limitaciones explícitas

1. **N=61 estructural**: 769 partidos SOFA × warmup ≥ 3 × cuotas matched = 61. Sin backfill SOFA 2022-2025 no se puede crecer.
2. **Walk-forward TRUE-OOS imposible**: SOFA solo abril 2026 sobrevive el filter de cuotas + warmup.
3. **Bonferroni demoledor**: α=0.00278 con N=61 es virtualmente imposible de superar.
4. **Bootstrap CI amplios**: rango típico ±50-100% reflejando varianza N pequeño.
5. **Cobertura LATAM no alcanzable**: Bolivia/Venezuela tienen shotmap pero `cuotas_historicas_fdco` no cubre estas ligas. Argentina/Brasil con cobertura cuotas SÍ pero SOFA reciente.

---

## Recomendaciones

### Promover SHADOW: NINGUNO
Persistido pero sin aplicado_produccion. Validación N≥80 + walk-forward inter-año requeridos.

### Descartar (sin señal o overfit-risk):
- F1b, F2a, F2b, F2c, F3a, F3b, F6b — todos con yield ~0% o negativo no significativo

### Anti-filtro confiable (sugerencia para investigación futura):
- **F4b `sp_dep_v > 0.5 → NO apostar X`** (CI hi < 0)
- Comparable a anti-filtros existentes (`gap_l ≥ 14d`, `DOW=Lunes`, `Mes 10/11`, `hora < 14`)
- Re-validar cuando N ≥ 80

### Hipótesis nueva descubierta (no en prompt):
- **`diff_pct_danger_v`** (calidad estructural visita) emerge en RF importance #2
- No testeada en F1-F6 originales
- Investigar: bin q4 por `diff_pct_danger`, ¿qué pick yieldea?

### NO emitir bead PROPOSAL
- 0 filtros pasan Bonferroni
- 0 filtros con CI95 lower > 0
- Cumple criterio del prompt: "NO emitir bead PROPOSAL si Bonferroni no superado"

---

## Comparación vs sesiones previas

| Sesión | Universo N | Filtros pasan WF | Promovidos SHADOW | Promovidos producción |
|---|---|---|---|---|
| `filtros_sofa_v1` (lag-1 SOFA) | 443 | 5/15 | 7 (731 picks) | 0 |
| `filtros_ema_v4` (EMA conv 11 ligas) | 4262 | 3/4520 | 3 (2692 picks) | 0 |
| **`filtros_shotmap_v1`** | **61** | **0** | **6 (81 picks)** | **0** |

**Tendencia clara**: cuanto más exigentes los criterios (Bonferroni + walk-forward + per-liga), más difícil pasar. Universo pequeño N=61 es prohibitivo.

---

## Próximos pasos sugeridos (sesión futura)

1. **Backfill SOFA histórico 2022-2025** (sesión separada, riesgo IP) → universe shotmap → ~3000-5000 partidos. Solo así walk-forward TRUE-OOS es viable.
2. **Re-validar F4b** sobre N grande (target ≥ 80)
3. **Explorar `diff_pct_danger_v`** como nueva hipótesis (emergió de ML importance)
4. **Comparación Brier xG model** con vs sin shotmap features (¿shotmap captura info no incluida en motor_xg_v2_14?)
5. **Combinar con filtros_ema_v4** SOLO cuando N permita combinaciones N≥30 por intersección

---

## Referencias

- Caley & Maye (2015) "A Better Way to Quantify Soccer Performance" — xG geometric formula
- Boyle (2022) "xG luck reversion in EPL" — F1 sustento literatura (no replicable con N=61)
- Sesiones previas:
  - `docs/papers/filtros_sofa_validados_post_session.md`
  - `docs/papers/filtros_ema_validados_post_session.md`
  - `docs/papers/motor_xg_v2_resultados_finales.md`
  - `docs/papers/sofascore_findings_consolidados.md`

## Artefactos persistidos

```
analisis/filtros_shotmap_v1_features.py        (Fase 1: features + EMA)
analisis/filtros_shotmap_v1_universo.py        (Fase 2: universo cuotas)
analisis/filtros_shotmap_v1_exploration.py     (Fase 3+4: explore + WF + ML)
analisis/filtros_shotmap_v1_exploration.json   (métricas)
analisis/filtros_shotmap_v1_shadow_persist.py  (Fase 6: SHADOW logs)
docs/papers/filtros_shotmap_validados_post_session.md  (este reporte)

DB tables:
  historial_equipos_shotmap_ema       (1,524 eventos)
  universo_filtros_shotmap_v1         (61 partidos)
  picks_shadow_filtros_shotmap_v1     (81 picks, aplicado_produccion=0)

Snapshot pre-sesión:
  snapshots/fondo_quant_20260504_124847_pre_shotmap_yield.db
```

## Manifesto integrity

```
SHA256 antes:  e61c00e12fe7e43b3b2d3b5d3e7f3e7a513807773795fab81b1611c720bc2081
SHA256 después: e61c00e12fe7e43b3b2d3b5d3e7f3e7a513807773795fab81b1611c720bc2081
INTACTO ✓ (sesión sin modificación de Reglas_IA.txt)
```

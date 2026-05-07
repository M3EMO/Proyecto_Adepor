# Filtros SOFA v3 — features espaciales shotmap_json lag-1

**Fecha:** 2026-05-07
**Sesión:** Fase C — audit `shotmap_json` cluster espacial
**Universo:** N=421 (lag-1 sobre 762 partidos shotmap × 393 driver backtest 2026)

---

## TL;DR

**4 filtros candidatos sobre 312 tests** pasan criterios mínimos relajados (yield>+5%, CI95 lo>0, N≥30). **0/312 supera Bonferroni estricto α=0.000160.**

Persistidos en SHADOW table `picks_shadow_filtros_sofa_v3_shotmap` (287 picks, `aplicado_produccion=0`).

**Patrón estructural confirmado**: 3/4 candidatos → pick=X. Consistente con sesgo "draw aversion" detectado en Fase 1 (5/7 → X) y Fase B (1/4 → X). **El edge SOFA tiende a concentrarse en empates infravalorados por mercado.**

---

## Features extraídas (16 per equipo per partido)

```
n_shots                  # total shots
n_shots_inside_box       # x ≤ 18 (área grande aproximada)
n_shots_outside_box      # x > 18
n_shots_central          # 35 < y < 65 (banda central 30%)
n_shots_wide             # y ≤ 35 o y ≥ 65 (bandas)
mean_dist_goal           # promedio playerCoordinates.x (% campo)
mean_xg_per_shot         # avg xg por shot
max_xg_shot              # mejor shot por xg
n_high_xg                # count xg > 0.3 (big chances)
hi_xg_ratio              # n_high_xg / n_shots
n_shots_first15          # quick start: time ≤ 15
n_shots_last15           # late pressure: time ≥ 76
n_shots_set_piece        # situation in {set-piece, corner, free-kick}
n_shots_assisted         # situation == 'assisted'
body_part_diversity      # 1=solo pies, 2=pies+cabeza, 3=+other
goal_y_spread            # max-min goalMouthCoordinates.y (variación dirección)
```

## Top features ML importance per target

```
pick=1:  max_xg_shot_lag1_v             0.061
         mean_xg_per_shot_lag1_l        0.056

pick=X:  n_high_xg_lag1_l               0.341
         mean_dist_goal_lag1_l          0.207
         hi_xg_ratio_lag1_v             0.178

pick=2:  n_high_xg_lag1_l               0.536  (signo invertido posible)
         hi_xg_ratio_lag1_l             0.163

pick=O:  n_high_xg_lag1_l               0.303
         hi_xg_ratio_lag1_l             0.257

pick=U:  n_high_xg_lag1_l               0.421
         hi_xg_ratio_lag1_l             0.333
```

**Estructura informacional**: `n_high_xg_lag1_l` y `hi_xg_ratio_lag1_l` son top features para 4/5 targets. Cantidad/calidad de big chances generadas por LOCAL en su partido prev tiene poder predictivo cross-target.

## TOP 4 candidatos SHADOW

### 1. n_high_xg_lag1_l > 1 → empate (PROMETEDOR)
- N=69 yield +56.5% CI95 [+8.7%, +105.9%] LOYO 2/2 ⭐
- **Hipótesis:** local generó 2+ big chances (xg>0.3) en su partido prev → mercado lo favorece como ofensivo, pero rival lo neutraliza tácticamente → empate.
- Posible regresión: equipos que generan muchas chances pero no concretan tienden a sub-rendir.

### 2. hi_xg_ratio_lag1_l > 0.11 → empate
- N=80 yield +43.2% CI95 [+4.3%, +88.8%] LOYO 1/2
- **Hipótesis:** ratio alto de big chances (≥1 cada 9 shots) → similar a #1.
- LOYO 1/2 más débil (un bucket positivo, otro negativo).

### 3. mean_dist_goal_lag1_l ≤ 13.46 → empate
- N=88 yield +41.1% CI95 [+1.0%, +84.5%] LOYO 2/2 ⭐
- **Hipótesis:** local con shots desde MUY cerca del arco en partido prev (avg <13.5% del campo) → ataque concentrado en penal area → próximo partido será cerrado.
- N grande (88), LOYO 2/2 sólido.

### 4. n_shots_assisted_lag1_l in (5, 8] → over25
- N=50 yield +29.1% CI95 [+2.3%, +54.2%] LOYO 2/2 ⭐
- **Hipótesis:** local con asistencias moderadas (5-8) en prev → juego asociativo que produce goles → next partido también goles.

## Hipótesis no testeadas (overfitting risk)

- **Cluster KMeans** sobre playerCoordinates (zonas no rectangulares aprendidas)
- **Heatmap distribution distance** entre partidos consecutivos (Wasserstein)
- **Goal direction concentration** (variance goalMouthCoordinates.y)
- **Time-density** (shots por minuto en períodos críticos)
- **xg vs xgot gap** per shot (calidad finalización)

## Riesgos overfitting

**ALTO.** 312 tests sobre N=421. Patrones similares Fase 1 + B + C confirman tendencia (draw aversion structural) pero ninguno aislado supera Bonferroni.

## Recomendación

### Inmediata
- NO promover. SHADOW puro.
- 287 picks loggeados con `aplicado_produccion=0`.
- Trigger N≥80 incremental + walk-forward TRUE-OOS.

### Próximas sesiones
1. **Fase A** — backfill SOFA 2022-2025 → walk-forward TRUE-OOS posible
2. **Ensemble multi-señal**: combinar TOP filtros Fase 1 + B + C como votación. ¿Reducir overfitting per-filtro?
3. **Cluster pattern recognition**: KMeans sobre coords → zonas aprendidas en lugar de bins fijos

## Persistencia

- `picks_shadow_filtros_sofa_v3_shotmap` (287 picks, 4 filtros)
- `_fase3_universo_shotmap` (421 partidos, 32 features lag-1)
- `sofascore_shotmap_features` (762 partidos, 37 cols)
- `analisis/filtros_sofa_v3_extract_shotmap_features.py`
- `analisis/filtros_sofa_v3_pipeline.py`
- `analisis/filtros_sofa_v3_pipeline.json`

## Resumen acumulado SHADOW (Fase 1+B+C)

| Sesión | Tabla | Filtros | Picks | Bonferroni |
|---|---|---|---|---|
| Fase 1 (2026-05-04) | `picks_shadow_filtros_sofa_v1` | 7 | 731 | 0/135 |
| Fase B (2026-05-07) | `picks_shadow_filtros_sofa_v2_periods` | 4 | 169 | 0/543 |
| Fase C (2026-05-07) | `picks_shadow_filtros_sofa_v3_shotmap` | 4 | 287 | 0/312 |
| **Total** | | **15 filtros** | **1,187 picks** | **0/990** |

**Insight cross-sesión:** **9/15 filtros → empate** (60%). Sesgo estructural confirmado. Posible bead PROPOSAL futuro: "ensemble draw-bias multi-señal" si N≥80 incremental confirma.

## Referencias

- `docs/papers/filtros_sofa_validados_post_session.md` — Fase 1
- `docs/papers/filtros_sofa_v2_period_findings.md` — Fase B
- `docs/papers/filtros_sofa_para_yield_session.md` — propuesta original Cat A-J
- Kuypers 2000 — bookmaker draw aversion estructural

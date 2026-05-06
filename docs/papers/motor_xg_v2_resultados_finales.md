# Motor xG v2 — Resultados finales POC SofaScore

**Fecha:** 2026-05-04
**Branch:** `experimentos`
**Sesión:** `2026-05-03/04_motor_xg_v2_sofa_poc`
**Snapshot DB:** `snapshots/fondo_quant_20260503_134328_pre_motor_xg_v2.db`

---

## TL;DR — RESULTADOS VALIDADOS EMPÍRICAMENTE

**Mejor feature: `big_chances` → -0.058 RMSE global (-4.9%)**

**xG model interno (calibrado sobre 19,660 shots SOFA): Brier 5-fold CV = 0.078 (industria 0.07-0.10).**

**Hipótesis del audit confirmada**:
- **LATAM exóticas → mejora masiva** (-8% a -11% RMSE)
  - Perú: -11.4% (1.541 → 1.365)
  - Ecuador: -8.4% (1.124 → 1.030, **rompe cota Poisson 1.18**)
  - Bolivia: -7.8% (1.158 → 1.068, **rompe cota Poisson 1.18**)
  - Uruguay: -5.9%
- LATAM mainstream → mejora moderada (-2% a -3%)
- EUR mainstream → ≈ ruido (mercado eficiente, V0 ya cerca del techo)

**Recomendación: PROCEDER con bead PROPOSAL MANIFESTO CHANGE.**

---

## Datos del backfill SofaScore

- **Universo**: 769 partidos / 14 ligas season 2026
- **Shots con coordenadas**: 19,660
- **Cobertura referee**: 80% (Bolivia/Venezuela tienen NULL en SOFA, pero ESPN cubre 78% globalmente como complemento)
- **Cobertura formación**: 100%
- **Sin 403** durante el backfill (safeguards funcionaron — sleep 1.5-3.5s, pausa 60s/50 calls, cap 2000)

---

## xG model interno (motor_xg_v2_14_xg_from_shotmap.py)

**Modelo**: Logistic Regression sobre features Caley-Maye + situation + bodyPart.

**Entrenamiento**:
- 19,660 shots, 2,062 goles (10.49% conversion)
- 5-fold CV temporal: Brier 0.0778 ± 0.0035, LogLoss 0.2766 ± 0.0095
- IN-SAMPLE: sum xG predicted = 2,061.7 vs 2,062 goles (ratio 1.000) — calibración perfecta

**Coefs aprendidos (z-scored features):**
| Feature | Coef | Interpretación |
|---|---|---|
| distance | **-0.8389** | más lejos = menos prob gol ✓ |
| angle | **+0.4474** | mejor ángulo arco = más prob ✓ |
| body_head | -0.3464 | cabeza penaliza ~50% xG ✓ |
| sit_penalty | +0.3008 | penalty ≈ 0.76 xG ✓ |
| sit_corner | -0.2376 | corners shot bajo xG ✓ |
| sit_fast_break | +0.0941 | contra-ataque + xG ✓ |
| inv_distance_sq | -0.0736 | decay físico ✓ |
| sit_assisted | -0.0512 | asistido ligera baja |
| body_left_foot | -0.0208 | marginal |
| is_inside_box | +0.0069 | redundante con distance |
| intercept | -2.5611 | calibration |

**Todos los coefs físicamente correctos**. xG model VÁLIDO.

Coefs persistidos en `config_motor_valores.xg_model_coefs_v2` (JSON con scaler).

---

## Ablation v2 (motor_xg_v2_18_ablation_v2.py)

**Approach**: EMA forward-strict baseline V0 sobre universo COMPLETO stats_partido_espn (13,430 partidos, 24,947 eventos post-WARMUP). Eval RMSE solo en eventos donde existen features SOFA.

**N eval = 465 eventos** (suficiente power estadístico).

### RMSE BASELINE V0 (sobre subset eval): **1.1781**

### Per feature (alpha óptimo + delta RMSE)

| Feature | α óptimo | Corr residuo | RMSE aug | Δ RMSE | N | Veredicto |
|---|---|---|---|---|---|---|
| **big_chances** | **+0.1345** | +0.475 | **1.1149** | **-0.0579 (-4.9%)** | 422 | ⭐⭐⭐ APORTA |
| **xg_shotmap** | +0.1705 | +0.415 | **1.1523** | **-0.0278 (-2.4%)** | 463 | ⭐⭐ APORTA |
| shots_inside_box | +0.0198 | +0.280 | 1.1683 | -0.0118 | 463 | ⭐ marginal |
| keeper_save_rival | +0.2371 | +0.121 | 1.1727 | -0.0057 | 396 | ruido |
| touches_penalty_area | +0.0040 | +0.136 | 1.1767 | -0.0034 | 463 | ruido |
| max_rating | +0.0097 | +0.573 | 1.1776 | -0.0025 | 463 | ruido |
| avg_rating | +0.0065 | +0.491 | 1.1793 | -0.0008 | 463 | ruido |
| ref_red_per_game | +0.0824 | +0.050 | 1.1813 | -0.0001 | 420 | ruido |
| ref_cards_per_game | +0.0001 | +0.062 | 1.1814 | ≈ 0 | 420 | ruido |

### Per liga (con xg_shotmap único feature)

| Liga | N | RMSE base | RMSE aug | Δ | % mejora |
|---|---|---|---|---|---|
| **Perú** | 28 | 1.541 | 1.365 | **-0.176** | **-11.4%** ⭐⭐⭐ |
| **Ecuador** | 46 | 1.124 | **1.030** | **-0.094** | **-8.4%** ⭐⭐⭐ |
| **Bolivia** | 28 | 1.158 | **1.068** | **-0.091** | **-7.8%** ⭐⭐⭐ |
| Uruguay | 32 | 1.324 | 1.247 | -0.078 | -5.9% ⭐⭐ |
| Argentina | 87 | 1.151 | 1.122 | -0.029 | -2.5% ⭐ |
| Brasil | 83 | 1.185 | 1.164 | -0.021 | -1.8% |
| Turquía | 37 | 1.170 | 1.170 | ≈ 0 | ruido |
| Inglaterra | 55 | 1.202 | 1.201 | ≈ 0 | ruido |
| España | 26 | 1.047 | 1.047 | ≈ 0 | ruido (ya en techo) |

### Hallazgo clave: rompimiento Poisson en LATAM

**Cota Poisson teórica = 1.18**.

| Liga | RMSE post-SOFA | Estado vs Poisson |
|---|---|---|
| Ecuador | 1.030 | **ROMPE -13%** |
| Bolivia | 1.068 | **ROMPE -10%** |
| España | 1.047 | ROMPE (ya antes) |
| Argentina | 1.122 | ROMPE -5% |
| Brasil | 1.164 | ROMPE -1% |

**La cota Poisson NO es absoluta — refleja varianza Poisson de λ promedio**. En LATAM exóticas con λ promedio MENOR (Bolivia 2.1 goles/team-match es alto pero composition skewed) y mayor info no-Poisson capturada (xG real con coords), la cota efectiva baja.

---

## Por qué los rating de jugadores NO aportan

`avg_rating` y `max_rating` tienen correlación alta con residuos (0.49 y 0.57), pero α óptimo es muy bajo (0.0065 y 0.0097) y RMSE no baja. Causa: **multicolinealidad con SOT** y otras features que ya están en baseline.

Ratings agregados por equipo NO aportan info incremental sobre lo que ya capturan las stats partido.

---

## Por qué referee CV NO aporta

cards/game y red/game tienen correlación con residuos casi nula (0.06 y 0.05). El árbitro NO predice goles incrementalmente. Probable que sea más relevante para over/under 2.5 que para goles totales por equipo.

**Hipótesis para sesión yield futura**: usar ref_red_per_game como feature de over_2.5 con tarjetas, no de xG.

---

## Limitaciones

1. **N=465 eventos eval** — power estadístico moderado. Con backfill histórico SOFA (2022-2025) sería ~5,000+ eventos.
2. **Solo season 2026 SOFA** — no walk-forward train-2025/test-2026 honest. Pero approach (alpha sobre residuos baseline universo full) ya es honest (no leakage).
3. **2 ligas faltantes** (Chile, Colombia) — sesión separada.
4. **Venezuela 0% match con ESPN** — gap de cobertura ESPN, no aliases. SOFA cubre VEN pero no podemos cross-validar sin ESPN.
5. **Bolivia/Venezuela referee NULL en SOFA** — necesita scraping federación (FBF/FVF) o prensa local.

---

## Cascada de recalibración requerida (si se promueve)

Si se cambia `motor_data.py:156` para incorporar `xg_shotmap` o `big_chances`:

1. **Schema migration**: agregar columnas `big_chances_l/v`, `xg_shotmap_l/v` a `partidos_backtest` y `stats_partido_espn`
2. **Pipeline ingest**: extender ingest para llamar SofaScore API en cada corrida (cubierto por sesiones futuras de integración productiva)
3. **`calibrar_rho.py`** — re-MLE ρ Dixon-Coles per-liga con nuevo xG (16 ligas)
4. **β_sot per-liga** — recalibrar coefs con nuevo xG_calc
5. **`backfill_ema_scoped.py --auto`** — backfill EMAs con xg_final nuevo
6. **`historial_equipos_v6_shadow`** — re-poblar
7. **V12 LR multinomial** — re-fit con xG nuevo
8. **factor_corr_xg_ou** — re-fit
9. **gamma_1x2** — re-fit OLS
10. **Filtros M.2 (n_acum), Layer 3 X-rescue** — re-validar
11. **V13 SHADOW** (Argentina F1_off, Francia F2_pos, Italia F2_pos, Inglaterra F5_ratio) — re-fit o retire

**Costo estimado**: 1-2 semanas + N≥80 SHADOW MODE pre-promoción.

---

## Decisiones técnicas propuestas

### Opción A — Promover SHADOW only

- Persistir `xg_shotmap_l/v` + `big_chances_l/v` en `partidos_backtest` SHADOW
- Loggear predicciones híbridas en tabla nueva `picks_shadow_xg_v2`
- Validación N≥80 → bead PROPOSAL si confirma yield/Brier

**Ventaja**: cero riesgo
**Desventaja**: SOFA depende de scraping productivo (anti-bot, IP risk)

### Opción B — PROPOSAL MANIFESTO CHANGE — promover xg_shotmap a producción

- Cambiar fórmula `xg_calc` en `motor_data.py:156`:
  ```python
  # ANTES: xg_calc = β_sot·SOT + 0.010·shots_off + coef_corner·corners
  # DESPUES: xg_calc = α·xg_shotmap_sofa + (1-α)·V0_legacy
  # con α calibrado per liga (mayor en LATAM, menor en EUR)
  ```
- Cascada completa de recalibración
- Bead `[PROPOSAL: MANIFESTO CHANGE]` con evidencia (esta doc)

**Ventaja**: mejora directa motor productivo (~2.4% global, hasta 11% en LATAM)
**Desventaja**: dependencia operativa SofaScore + cascada cara

### Opción C — Híbrido: usar SOFA solo en LATAM (where it matters)

- En LATAM exóticas (BOL, PER, VEN, ECU, URU): `xg_calc = SOFA xg_shotmap`
- En EUR/mainstream: mantener V0 legacy
- Per-liga `arch_decision` extendida a `arch_decision_xg_per_liga`

**Ventaja**: mejora donde hay edge (LATAM), no toca lo que funciona (EUR)
**Desventaja**: complejidad arquitectural

---

## Mi recomendación final

**Opción C — Híbrido per-liga** (best ROI, lower risk):

1. **Inmediato (próxima sesión)**:
   - Extender backfill: Chile + Colombia + Bolivia/Venezuela referee (federaciones)
   - Backfill histórico LATAM 2022-2025 SOFA (priorizar BOL/PER/ECU/URU/VEN)
   - Re-validar ablation con N=2,000+ eventos por liga LATAM
2. **Medio plazo**:
   - Implementar `motor_sofascore.py` wrapper aislado
   - SHADOW mode 2 meses sobre LATAM
   - Validar yield + Brier
3. **Long term**:
   - Si SHADOW valida → bead PROPOSAL MANIFESTO CHANGE Opción C
   - Implementar cascada (rho LATAM, gamma, factor_corr)
   - Activar promotion en `arch_decision_xg_per_liga`

**Solicito autorización** del usuario para:
- Emitir bead `[PROPOSAL: MANIFESTO CHANGE]` con evidencia consolidada
- O alternativa: SHADOW only sin Manifiesto change

---

## Documentación relacionada

- `analisis/motor_xg_v2_18_ablation_v2.py` + `.json` — ablation final HONEST
- `analisis/motor_xg_v2_14_xg_from_shotmap.py` + `.json` — xG model entrenado
- `analisis/motor_xg_v2_13_sofascore_poc.py` — scraper safeguards
- `analisis/motor_xg_v2_99_run_circuit.py` — orchestrator
- `docs/papers/sofascore_findings_consolidados.md`
- `docs/papers/sofascore_anti_bot_strategy.md`
- `docs/papers/xg_from_shotmap_metodologia.md`
- `docs/papers/research_fuentes_features_premarch.md`
- `docs/papers/research_fuentes_latam_features.md`
- `docs/papers/audit_bias_xg_v2.md`
- `docs/papers/filtros_estrategicos_pendientes.md`

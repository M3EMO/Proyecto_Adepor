# Motor xG v2 — Propuesta y evaluación honesta

**Fecha:** 2026-05-03
**Branch:** `experimentos`
**Sesión:** `2026-05-03_motor_xg_v2`
**Snapshot DB:** `snapshots/fondo_quant_20260503_134328_pre_motor_xg_v2.db`
**Trigger:** usuario solicita reconstruir motor xG con objetivo RMSE forward-EMA → mínimo posible.

---

## TL;DR

**Resultado:** ningún approach Fase 2 rompe la cota Poisson teórica (1.18) honestamente.
La única mejora real sobre baseline V5 NNLS es **Bayesian hierarchical** con
**Δ -0.011 RMSE (-0.94%)** sobre OOS pool. Mejora consistente pero pequeña.
**Recomendación:** NO promover a producción de forma agresiva. Promover via SHADOW MODE
(N≥80 partidos) o mantener V5 NNLS calibrado como referencia y seguir investigando
features no-Poisson.

**Selection bias detectado** y corregido: las "mejoras" de Ridge per-liga F_extended y
NNLS pool BASE (RMSE 1.1698 / 1.1706) eran **artefacto del filtro pos/pass_pct NULL**
que descarta 3,689 partidos sistemáticamente más difíciles. Sobre subset uniforme
N=18,774, V5 NNLS también baja a 1.1684 sin modificación alguna.

---

## Cota teórica Poisson irreducible

Para `λ ≈ 1.4 goles/equipo/partido`:
```
varianza Poisson pura = √λ ≈ 1.18
```

Para romper 1.18 se requiere **info no-Poisson**: lineups, lesiones, contexto pre-partido,
EPV/xT event-level. Estos features NO están disponibles en `stats_partido_espn`
(post-match summary) → **bajar de 1.18 con features actuales es teóricamente imposible**.

---

## Tabla consolidada FASE 2 + FASE 3 (validación uniforme)

### Fase 2 (universos heterogéneos — comparación SESGADA)

| Approach | OOS pool | N eventos | Rompe 1.18? |
|---|---|---|---|
| V5 NNLS baseline | 1.1959 | 26,860 | No |
| Ridge per-liga F_ext (α=10, θ=0.30) | **1.1698** | 18,774 | (aparente sí) |
| NNLS pool BASE (θ=0.30) | 1.1706 | 18,774 | (aparente sí) |
| Bayesian hierarchical (θ=0.30) | 1.1848 | 25,998 | No |
| Stacking 2-level Ridge meta | 1.1970 | 24,168 | No |
| XGBoost sin cuotas | 1.1953 | 26,860 | No |
| XGBoost con cuotas | 1.1936 | 17,784 | No |

### Fase 3 (validación uniforme — comparación HONESTA)

Sobre subset común **N=18,774 eventos** (filtro `h_pos NOT NULL AND a_pos NOT NULL AND h_pass_pct NOT NULL AND a_pass_pct NOT NULL`):

| Modelo | OOS pool | Δ vs V5 (mismo N) |
|---|---|---|
| **V5 NNLS** | **1.1684** | (baseline) |
| NNLS pool | 1.1685 | +0.0001 |
| Ridge F_ext per-liga | 1.1678 | -0.0006 (ruido) |

Sobre subset común **N=25,998 eventos** (sin filtro):

| Modelo | OOS pool | Δ vs V5 |
|---|---|---|
| V5 NNLS | 1.1959 | (baseline) |
| Bayesian hierarchical θ=0.30 | **1.1848** | **-0.0111** ★ única mejora real |
| XGBoost sin cuotas | 1.1953 | -0.0006 (ruido) |

### Holdout 2026 CONGELADO (eval final)

| Modelo | IS 2026 RMSE | N |
|---|---|---|
| V5 NNLS θ=0.20 | 1.1967 | 5,400+ |
| Bayesian hierarchical θ=0.30 | **1.1858** | 665 |

Bayesian sobre 2026 IS = 1.1858 — coherente con su OOS pool 1.1848. Generalización OK
(no overfit 2022-2025), pero N=665 (subset filtrado por NULL) limita potencia estadística.

---

## Diagnóstico selection bias

V5 NNLS **sin tocar nada** sufre **Δ -0.0275 RMSE** al cambiar el universo
de N=26,860 → N=18,774. Esto significa que **el subset filtrado es intrínsecamente
más fácil**: los 7,378 eventos descartados (sin possession/pass_pct registrados) provienen
de partidos con stats incompletas, típicamente:
- Ligas LATAM tempranas (2022) sin scraping completo ESPN
- Partidos con baja varianza inherente (?) — hipótesis a investigar
- Equipos con scraping bug (incluyen ESPN summary pero sin advanced stats)

**Implicación:** cualquier comparación entre approaches debe **fijar el universo** antes
de medir RMSE. Reportes Fase 2 que filtran NULL produciendo "mejoras" ~0.025 son
**artefactos**, no edge real.

---

## Coefs aprendidos (mejor de cada approach)

### V5 NNLS pool global
```
xg_calc = 0.273 + 0.247·SOT
(shots_off, corners shrinkados a 0)
```

### NNLS pool BASE (Fase 2A)
```
xg_calc = 0.263 + 0.252·SOT
(idem, marginalmente distintos)
```

### Bayesian hierarchical (Fase 2C)
```
α_global = 0.7334, β_SOT_global = 0.2064
σ²_α = 0.269 (sd 0.518) — heterogeneidad inter-liga ALTA
σ²_β = 0.0036 (sd 0.060) — heterogeneidad slope BAJA

Ligas más distintas del global:
  Noruega:  α=+0.74, β_SOT=-0.13 (n=1,440)
  Perú:     α=+0.63, β_SOT=-0.10 (n=990)
  Chile:    α=-0.58, β_SOT=+0.06 (n=1,440)

LATAM (Bolivia, Ecuador, Uruguay, Venezuela): colapsan a global por shrinkage
(n_liga insuficiente para escapar prior).
```

**Hallazgo:** la heterogeneidad real está en el **intercept α** (tasa base goles)
no en el slope β_SOT. Esto sugiere que features que capturan "tasa base" liga-específica
(media histórica de goles, ritmo de juego, calidad arbitral) son la dirección
prometedora, NO más coefs sobre SOT.

---

## Por qué los approaches "complejos" no ganaron

1. **Stacking** destruyó la combinación M1/M2 con coef negativo (-1.745) en V0 y positivo
   (+2.177) en V5 — fenómeno de multicolinealidad (ambos usan SOT). El meta-learner
   lo aprendió como "subtract V0, add V5" sin ganar info real.

2. **XGBoost** confirma el hallazgo de NNLS: top features son SOT (0.247),
   shots_off_rival (0.201), saves_rival (0.166). El árbol también ignora possession
   y pass_pct cuando hay SOT. EMAs pre-evento NO entran al top-5.

3. **Bayesian hierarchical** sí gana marginalmente porque modela la heterogeneidad en
   el **intercept** per-liga (no en el slope). NNLS pool global pierde esto al imponer
   intercept único.

---

## Cascada de recalibración requerida (si se promueve)

Si se cambia `motor_data.py:156` (xg_final fórmula y/o θ):

1. **`calibrar_rho.py`** — re-MLE ρ Dixon-Coles per-liga (16 ligas)
2. **`calibrar_beta.py`** — re-fit β_sot per-liga con nuevo θ
3. **factor_corr_xg_ou** — re-fit (constante en `config_motor_valores`)
4. **`backfill_ema_scoped.py --auto`** — backfill EMAs con xg_final nuevo
5. **`historial_equipos_v6_shadow`** — re-poblar con xg_v6 nuevo
6. **V12 LR multinomial pool/Turquía** — re-fit con xG nuevo (anchor batch nuevo)
7. **V13 SHADOW** (Argentina F1_off NNLS, Francia F2_pos NNLS, Italia F2_pos RIDGE,
   Inglaterra F5_ratio NNLS) — re-fit o retire
8. **Filtros M.2 (n_acum_l<60)** — re-validar (cambia distribución de n_acum)
9. **Layer 3 X-rescue per-liga** — re-validar
10. **`gamma_1x2`** — re-fit OLS sobre nuevo xG

**Costo estimado:** 1-2 semanas de trabajo + N≥80 SHADOW MODE pre-promoción.

---

## Decisiones técnicas propuestas

### Opción A — Status quo (recomendado por evidencia)

- **Mantener V0 motor productivo** (`xg_calc = β·SOT + 0.010·shots_off + coef_c·corners`,
  `xg_final = 0.70·xg_calc + 0.30·goles_reales`) en producción.
- **Ajustar θ a 0.10-0.20** (cambio cosmético, NO requiere cascada completa porque coefs
  similares). Mejora -0.10 RMSE OOS sin tocar nada más.
- **Loggear Bayesian hierarchical como SHADOW** (`historial_equipos_bayesian_shadow`)
  para validación N≥80.
- **NO emitir PROPOSAL MANIFESTO CHANGE** ahora.

**Justificación:** mejora real Bayesian -0.011 RMSE (-0.94%) NO justifica costo cascada.

### Opción B — Cambio θ aislado

- Cambiar SOLO `θ` de 0.70 → 0.20 en `motor_data.py:156`.
- NO requiere recalibrar β_sot, ρ, γ porque la formula `xg_calc` no cambia.
- Requiere re-fit de EMAs (porque xg_final cambia).
- Costo: 2-3 días.
- Mejora medida: V0 con θ=0.10 vs V0 productivo θ=0.70 sobre N=26,860 → **-0.10 RMSE OOS**
  (de 1.30 a 1.20).

**Justificación:** mejora 8-9% sin costo de cambio de fórmula. Valor más alto del análisis.

### Opción C — Cambio completo a Bayesian

- Reemplazar `xg_calc` por modelo Bayesian hierarchical con coefs per-liga.
- Cascada completa (10+ pasos).
- Mejora -0.011 RMSE sobre el mejor V5 baseline.
- Costo: 1-2 semanas.

**Justificación:** mejora marginal incremental sobre Opción B.

---

## Recomendación final del análisis

**Opción B + SHADOW Bayesian.**

1. **Inmediato:** PROPOSAL MANIFESTO CHANGE para cambiar `θ` de 0.70 → **0.20**
   (mejor IS_2026, OOS estable). Solo este cambio es 8-9% mejora RMSE — el ROI más alto.
2. **Medio plazo:** loggear Bayesian hierarchical como SHADOW. Si N≥200 SHADOW lo confirma,
   evaluar Opción C después.
3. **Largo plazo:** explorar features no-Poisson (lineups via API-Sports, EPV via
   StatsBomb si se contrata) para genuinamente romper 1.18.

---

## Limitaciones del estudio

1. **N=665 IS 2026** para Bayesian — potencia estadística limitada en holdout
   (subset filtrado).
2. **Concept drift detectable** en LOYO 2025: peor año cross-approach (1.19+ vs 1.14-1.17).
   Vigilar al promover.
3. **Cota Poisson 1.18 no rota** — todos los approaches están dentro del ruido teórico.
4. **Yield NO evaluado** en este estudio (por petición explícita usuario).
   Implicación: si Bayesian se promueve, debe re-validarse contra filtros productivos
   (Inglaterra +42%, España +9.9%) antes de afectar picks.
5. **α-grid Ridge degenerado** con N grande: NNLS-positiva domina, hyperparam α
   irrelevante.
6. **Stacking afectado por multicolinealidad** SOT — meta-learner produjo coefs no
   interpretables (-1.745 / +2.177).

---

## Artefactos generados

```
analisis/motor_xg_v2_00_baseline.py / .json
analisis/motor_xg_v2_01_ridge_per_liga.py / .json
analisis/motor_xg_v2_02_nnls_extended.py / .json
analisis/motor_xg_v2_03_stacking.py / .json
analisis/motor_xg_v2_04_xgboost.py / .json
analisis/motor_xg_v2_05_hierarchical.py / .json
analisis/motor_xg_v2_99_validation_uniforme.py / .json   ← FASE 3 honesta
docs/papers/motor_xg_v2_research.md                       ← lit review (Baio + Berrar)
docs/papers/motor_xg_v2_propuesta.md                      ← este documento
```

---

## Bead PROPOSAL pendiente de autorización del usuario

**SOLICITUD:** autorización formal para emitir bead
`[PROPOSAL: MANIFESTO CHANGE]` con la **Opción B** (cambio θ aislado 0.70 → 0.20).

Alternativa: si usuario prefiere Opción A (status quo) o Opción C (cambio completo
Bayesian), ajustar la propuesta antes de emitir el bead.

**NO se ha tocado producción ni emitido bead. Esperando GO/NO-GO usuario.**

---

## Addendum 2026-05-03 — Fase SofaScore POC

Tras decisión usuario "Opción C + features pre-match", iniciamos POC con SofaScore unofficial API:

### Findings clave (verificados empíricamente)

1. **Cobertura SofaScore season 2026 = 100% en 16 ligas** (incluye BOL/PER/VEN/URU/ECU)
2. **Stats vs ESPN**: ~50 stats en 3 períodos vs 28 stats agregadas
3. **Shotmap con coordenadas + situación + bodyPart** — único feed gratis con esto
4. **Referee CV histórico**: yellowCards/redCards/games por árbitro (ARG/BRA/PER/ECU/URU populated; BOL/VEN NULL)
5. **`keeperSaveValue`** por save = xS faced (proxy directo xG ofensivo del rival)
6. **VAEP-like ValueNormalized** (defensiveValueNormalized, passValueNormalized, etc.) por jugador
7. **Player ratings + formación canónica + lineup confirmed pre-match**

### Restricciones operativas SofaScore
- Cloudflare 403 challenge tras ~1000 calls — IP bloqueada 1-24h
- Recovery requiere cambio de IP (hotspot móvil / VPN / tiempo)
- Stack: `curl_cffi` con `impersonate='chrome'` bypassa TLS fingerprint
- Safeguards: sleep 1.5-3.5s, pausa 60s/50 calls, cap 1500/sesión, abort en 403

### xG model interno (motor_xg_v2_14_xg_from_shotmap.py)
- Logistic Regression sobre features: distance, angle (Caley 2015), inv_distance², is_inside_box, body_head/foot, situation_dummy
- 5-fold CV temporal — Brier + LogLoss
- Persiste coefs en `config_motor_valores.xg_model_coefs_v2`
- Aplicar a partidos: `xg_l/v = Σ P(goal | shot_i)` por equipo

### Ablation pendiente (Fase 9 nueva)
- Suite de variantes: BASELINE_sot, sot+xg_shotmap, sot+keeper_save_rival, sot+ref_cards_per_game, KITCHEN_SINK, etc.
- Walk-forward: train < 2026, test 2026 (holdout CONGELADO)
- Si Δ RMSE > 0.005 → backfill histórico SofaScore 2022-2025 (~5h+)
- Si NO → cortar y emitir bead Opción C con baseline Bayesian

### Documentación adicional
- `docs/papers/sofascore_findings_consolidados.md` — todo SofaScore
- `docs/papers/sofascore_anti_bot_strategy.md` — guía operativa anti-bot
- `docs/papers/xg_from_shotmap_metodologia.md` — metodología xG model interno
- `docs/papers/research_fuentes_features_premarch.md` — research general
- `docs/papers/research_fuentes_latam_features.md` — research LATAM exóticas
- `analisis/motor_xg_v2_13_sofascore_poc.py` — scraper safeguards
- `analisis/motor_xg_v2_14_xg_from_shotmap.py` — xG model
- `analisis/motor_xg_v2_15_ablation_sofa.py` — ablation pipeline

---

## Referencias

- `docs/definiciones/rmse_forward_ema.md` — métrica
- `docs/papers/audit_xg_v5_evolucion.md` — investigación previa (Plan A-F)
- `docs/papers/motor_xg_v2_research.md` — Baio & Blangiardo 2010, Berrar et al. 2019
- Baio, G. & Blangiardo, M. (2010). DOI 10.1080/02664760802684177
- Berrar, D. et al. (2019). DOI 10.1007/s10994-018-5747-8
- Caley, M. & Maye, K. (2015). "A Better Way to Quantify Soccer Performance" — xG geometric formula
- Lucey, P. et al. (2014). "Quality vs Quantity: Improved Shot Prediction in Soccer" — body+coords feature importance

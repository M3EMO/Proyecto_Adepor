# Motor xG v3 — estado consolidado post-sesión

**Fecha:** 2026-05-04
**Branch:** `experimentos`
**Bead PROPOSAL:** `adepor-173` (label `proposal-manifesto` + `approved-by-lead`)
**Manifesto SHA256:** `8973fe535cb0ef1440efd70cb47aef4c3e8328795d050a585a0ced0a36c477d0`
**Snapshots de seguridad:**
- `snapshots/fondo_quant_20260504_102513_pre_xg_v2_hibrido.db`
- `snapshots/fondo_quant_20260504_105548_pre_backfill_ema_v2.db`
- `snapshots/fondo_quant_20260504_124847_pre_shotmap_yield.db`
- `snapshots/fondo_quant_20260504_133955_pre_xg_v3_rebuild.db`

---

## TL;DR

Motor xG v3 **OPERATIVO en producción**. Mejora **-16% RMSE descriptor** (1.05 → 0.88) sobre V_custom puro vía descubrimiento de que SofaScore expone `xgot` field por shot directamente.

**Cobertura xgot**:
- 100% en 9 ligas mainstream (ENG/ESP/ITA/ALE/FRA/TUR/NOR/BRA + URU 36% partial)
- 0% en 5 LATAM exóticas (ARG/BOL/ECU/PER/VEN) → fallback a LogReg custom
- 0% en ligas no scrapeadas SOFA (Chile, Colombia, copas) → fallback V0 ESPN

Anti-filtro F4b (sp_dep_v > 0.5 → no apostar X) en SHADOW logging runtime.

---

## Cascada V0 → V_custom → V_v3 → fallback chain

`src/ingesta/motor_data.py:160` (`calcular_xg_v2_hibrido_sofa`):

```
Nivel 1: SOFA xgot directo (por shot, sumar por equipo)
         + LogReg custom fallback para shots sin xgot     ← V_v3 (BEST)
Nivel 2: LogReg custom puro sobre coords + situation     ← V_custom (xg_shotmap)
Nivel 3: V0 ESPN (β·SOT + 0.010·shots_off + coef_c·corners) ← V0 fallback
Nivel 4: goles_reales si xg_calc=0 y goles>0              ← último recurso
```

Todos los niveles incorporan híbrido `xg_final = θ·xg_calc + (1-θ)·goles_reales`.
α per-liga determina blend SOFA vs V0 (ver `config_motor_valores.alpha_xg_v2_hibrido_sofa`).

---

## Pipeline diario actualizado (`ejecutar_proyecto.py`)

```
FASE 0   motor_purga.py
FASE 1   motor_backtest, motor_liquidador, evaluar_pretest, motor_arbitro
FASE 3   motor_data.py                              → scrape ESPN + xG cascada V3>V_custom>V0
FASE 3.1 scripts/scrape_sofa_post_liquidacion.py    → llena sofascore_match_features (cap 30/día)
FASE 3.15 analisis/motor_xg_v2_14_xg_from_shotmap   → recompute xg_shotmap_l/v (V_custom)
FASE 3.16 analisis/xg_v3_hibrido_sofa_custom        → recompute xg_v3_l/v (xgot SOFA + custom fallback)
FASE 3.17 scripts/rebuild_ema_v2.py                 → OVERWRITE EMAs con V3
FASE 3.2 actualizar_posiciones
FASE 3.5 motor_adaptativo
FASE 4-6 motor_fixture, motor_tactico, motor_cuotas
FASE 7   motor_calculadora                          → lee EMAs V3 → Poisson DC → probs 1X2/OU
FASE 7.5 scripts/aplicar_antifiltro_shotmap_f4b.py  → SHADOW logging F4b sp_dep_v anti-X
FASE 8-9 motor_backtest, motor_sincronizador        → escribe Excel
```

---

## Validación empírica V3 vs V_custom

### RMSE descriptor (xG vs goles del partido en curso, N=762)

| Modelo | RMSE | Corr | Calibración |
|---|---|---|---|
| V_custom (LogReg coords + situation) | 1.0467 | +0.4914 | 1.000 |
| **V_v3 (xgot SOFA + custom fallback)** | **0.8836** | **+0.6753** | 1.015 |
| Mejora | **-15.6%** | **+37%** | similar |

### Per liga (RMSE)

| Liga | V_custom | V_v3 | Δ | Veredicto |
|---|---|---|---|---|
| Italia | 1.09 | **0.74** | -0.35 | WIN -32% |
| Brasil | 1.04 | **0.68** | -0.36 | WIN -35% |
| Francia | 1.11 | **0.72** | -0.39 | WIN -35% |
| Inglaterra | 1.05 | **0.72** | -0.34 | WIN -32% |
| Turquía | 1.09 | **0.79** | -0.30 | WIN -28% |
| Alemania | 1.07 | **0.82** | -0.25 | WIN -24% |
| España | 1.05 | **0.81** | -0.24 | WIN -23% |
| Noruega | 1.22 | **0.99** | -0.23 | WIN -19% |
| Argentina, Bolivia, Ecuador, Perú, Venezuela | igual | igual | 0 | TIE (xgot NULL → fallback custom) |
| Uruguay | 0.94 | 1.04 | +0.10 | LOSS (xgot 36% partial) |

### Brier predictor forward-EMA pre-match (N=562)

| Modelo | Brier 1X2 | Brier O25 |
|---|---|---|
| V_custom forward | 0.5710 | 0.1988 |
| **V_v3 forward** | **0.5671** (-0.7%) | **0.1980** (-0.4%) |
| Mercado (P_implícita cuotas) | 0.6794 | 0.2434 |

**Lectura honesta**: mejora descriptor (-16%) NO se traduce 1:1 en mejora forward predictor (-0.7%). Razón: EMA forward "promedia" 5+ partidos previos → mejora individual se diluye.

---

## Otras stats SOFA exploradas (37 features evaluadas)

**Top 5 con mejora marginal sobre V_v3 (descriptor)**:

| Feature | corr_g | α óptimo | Δ RMSE | Comentario |
|---|---|---|---|---|
| big_chances_missed | +0.17 | -0.066 | -0.010 | regresion-to-mean débil |
| errors_lead_to_shot | +0.00 | -0.070 | -0.007 | defensiva crackeada |
| blocked_shots | -0.01 | -0.028 | -0.007 | defensa rival |
| n_shots_head | +0.05 | -0.033 | -0.005 | shots cabeza |
| corners | +0.03 | -0.018 | -0.005 | marginal |

**Multivariado V_v3 + 5 features (NNLS sobre N=672)**:
```
V_v3 solo:        RMSE 0.8128
V_v3 + 5 features: RMSE 0.7937 (Δ -0.019, -2.4%)

Coefs NNLS:
  xg_v3                +0.770   ← dominante
  big_chances          +0.113   ← solo aporta significativo
  errors_lead_to_shot  +0.013   ← marginal
  bc_missed, sib, hit_woodwork: shrinkados a 0
```

**Conclusión**: V_v3 ya capturó ~95% del boost informacional disponible. SOFA xgot fue el "Holy Grail". Mejoras adicionales son <2% y no justifican complejidad.

---

## Anti-filtro F4b SHADOW runtime activo

Trigger: `ema_sp_dep_v > 0.5` (visita set-piece dependent) → **NO apostar X (empate)**.

**Validación empírica SHADOW** (N=58 picks=X que el filtro habría suprimido):
- Yield SHADOW: **-21.3%**
- Hit empate: 24.1% (vs ~28-30% baseline)
- Confirma señal del POC original (-77% N=13)

**Per liga heterogéneo**:
| Liga | N | Yield | Veredicto |
|---|---|---|---|
| Ecuador | 12 | -100% | ⭐⭐⭐ funciona |
| Perú | 3 | -100% | tiny |
| Uruguay | 2 | -100% | tiny |
| Venezuela | 3 | -100% | tiny |
| Brasil | 7 | -58% | ⭐⭐ funciona |
| España | 7 | -51% | ⭐⭐ funciona |
| Italia | 5 | +115% | ✗ INVIERTE |
| Inglaterra | 6 | +20% | ✗ no funciona |
| Turquía | 7 | +24% | ✗ no funciona |

**Whitelist sugerido para activación futura**: BRA/ECU/ESP/PER/URU/VEN
**Blacklist**: Italia, Inglaterra, Turquía (filtro INVIERTE)

Modo actual: `shadow` (no afecta producción). Configuración:
- `config_motor_valores.antifiltro_shotmap_f4b_modo` = 'shadow'
- `config_motor_valores.antifiltro_shotmap_f4b_threshold` = 0.5

---

## Tablas DB clave

| Tabla | Filas | Estado |
|---|---|---|
| `sofascore_match_features` | 769 | xg_shotmap_l/v + xg_v3_l/v populated 762 partidos |
| `picks_shadow_xg_v2` | 1,524 | SHADOW logs V0 vs V2 backfilled |
| `picks_shadow_filtros_shotmap_v1` | 81 | F1-F6 shotmap-derived (aplicado_produccion=0) |
| `picks_shadow_antifiltro_f4b_runtime` | 58 | F4b runtime (SHADOW only) |
| `historial_equipos` | 1,305 | 322 equipos con EMAs V3 reconstruidas |
| `historial_equipos_shotmap_ema` | 1,524 | EMA features shotmap-derived (752 post-warmup) |
| `universo_filtros_shotmap_v1` | 61 | universe shotmap + cuotas |

---

## Configs persistidas

```
config_motor_valores:
  xg_v2_hibrido_modo                    = 'active'
  alpha_xg_v2_hibrido_sofa              per liga (16 ligas + global)
  xg_model_coefs_v2                     LogReg custom Brier 0.078
  antifiltro_shotmap_f4b_modo           = 'shadow'
  antifiltro_shotmap_f4b_threshold      = 0.5
```

---

## Pendientes (sesiones futuras, NO urgentes)

1. **Backfill SOFA histórico 2022-2025** — sesión separada con cuidado anti-bot, prioridad para validar V3 LATAM exóticas con N grande
2. **Backfill Chile + Colombia** + 14 copas season 2026 — pendientes sin urgencia
3. **Investigar Uruguay xgot 36% LOSS** — por qué cobertura partial es problemática
4. **Whitelist per-liga F4b** activación tras N≥80 SHADOW (BRA/ECU/ESP/PER/URU/VEN)
5. **Cascada recalibración rho DC + gamma 1X2 + factor_corr_xg_ou** — opcional, recomendado tras N≥80 SHADOW V3
6. **Investigar fuentes alternativas xG LATAM** — StatsBomb open data?, xG calibrado por academia
7. **Federaciones BOL/VEN referee scraping** — cierra gap referee LATAM (yield future session)

---

## Documentación relacionada

- `docs/papers/motor_xg_v2_propuesta.md` — POC original V2
- `docs/papers/motor_xg_v2_resultados_finales.md` — resultados V2
- `docs/papers/sofascore_findings_consolidados.md` — features SOFA
- `docs/papers/sofascore_anti_bot_strategy.md` — guía anti-bot
- `docs/papers/filtros_shotmap_validados_post_session.md` — sesión shotmap analysis
- `docs/papers/filtros_sofa_para_yield_session.md` — filtros SOFA para yield
- `docs/papers/filtros_estrategicos_pendientes.md` — pendientes generales
- `docs/papers/PROMPT_sesion_shotmap_analysis.md` — prompt sesión shotmap
- `Reglas_IA.txt` — Manifesto V3 update sección A.bis

---

## Scripts ejecutables del flujo V3

```
src/ingesta/motor_data.py:160          calcular_xg_v2_hibrido_sofa
                                        (lookup xg_v3 > xg_shotmap > V0 fallback)
analisis/motor_xg_v2_14_xg_from_shotmap LogReg custom training (idempotente)
analisis/xg_v3_hibrido_sofa_custom      híbrido shot-level (idempotente)
analisis/xg_v3_sofa_vs_custom_comparativa  comparación empírica
analisis/xg_v3_brier_score              Brier descriptor
analisis/xg_v3_brier_forward_ema        Brier predictor forward-EMA
analisis/xg_v4_features_unused          exploración 37 features adicionales
scripts/scrape_sofa_post_liquidacion    hook scrape SOFA pipeline (cap 30/día)
scripts/rebuild_ema_v2.py               rebuild EMAs con V3 idempotente
scripts/aplicar_antifiltro_shotmap_f4b  hook anti-filtro F4b SHADOW runtime
```

---

## Beads relevantes

- `adepor-atn` — PROPOSAL motor xG v2 hibrido (proposal-manifesto + approved-by-lead)
- `adepor-173` — PROPOSAL motor xG v3 hibrido SOFA xgot (proposal-manifesto + approved-by-lead)
- Anti-filtro F4b: SHADOW only, sin bead PROPOSAL (Bonferroni no superado en POC N=61)

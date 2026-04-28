# xG Calibration History — guía para LLM/Lead

Persistencia del aprendizaje de los walk-forward backtests (`adepor-bgt`).

## Dónde está la data

| Recurso | Ubicación | Para qué |
|---|---|---|
| Tabla SQL | `fondo_quant.db` → `xg_calibration_history` | Métricas agregadas, queryables |
| Cache crudo | `analisis/cache_espn/{liga}_{temp}.json` | Partidos ESPN scrapeados, re-runs sin re-scraping |
| Resultados | `analisis/walk_forward_*.json` | Output completo con calibration buckets |
| Memory | `bd memories xg` | Resumen narrativo |
| Bead vivo | `adepor-bgt` (OPEN) | Estado + extensiones futuras |

## Schema xg_calibration_history

```sql
CREATE TABLE xg_calibration_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_corrida TEXT,
    bead_id TEXT,
    iter INTEGER,                    -- 1=EUR CSV, 2=LATAM API goals, 3=ESPN full stats
    fuente TEXT,                     -- football-data.co.uk | api-football | espn-core
    liga TEXT,
    temp_train TEXT,
    temp_predict INTEGER,
    n_total INTEGER,
    n_predict INTEGER,
    n_zero_stats INTEGER,
    promedio_liga REAL,
    rho_usado REAL,
    hit_rate REAL,
    base_rate_local REAL,
    edge_pp REAL,                    -- (hit_rate - base_rate) * 100
    brier_mean REAL,
    xg_mse_local REAL,
    xg_mse_visita REAL,
    xg_bias_local REAL,
    xg_bias_visita REAL,
    calibracion_json TEXT,           -- buckets prob_max -> hit_rate
    notes TEXT
);
```

## Queries útiles

```sql
-- Edge promedio por iteracion
SELECT iter, COUNT(*) AS n_ligas, AVG(hit_rate) AS hit_avg, AVG(edge_pp) AS edge_avg
FROM xg_calibration_history GROUP BY iter;

-- Top 5 ligas por edge real
SELECT liga, iter, hit_rate, base_rate_local, edge_pp
FROM xg_calibration_history WHERE iter IN (1,3) ORDER BY edge_pp DESC LIMIT 5;

-- xG bias por liga (full stats vs goals-only)
SELECT liga, iter, xg_bias_local, xg_bias_visita, fuente
FROM xg_calibration_history ORDER BY xg_bias_local DESC;

-- Cobertura ESPN stats por liga
SELECT liga, iter, n_predict, n_zero_stats,
       ROUND(100.0 * (n_predict - n_zero_stats) / NULLIF(n_predict, 0), 1) AS coverage_pct
FROM xg_calibration_history WHERE iter = 3;
```

## Hallazgos clave (2026-04-26)

### 1. Edge real del motor por liga (target temp 2024)

| Tier | Ligas | Edge promedio |
|---|---|---|
| 🟢 Excelente | Inglaterra, Italia, Francia, Turquía | +7-11pp |
| 🟡 Marginal | Alemania, Brasil, Ecuador, Venezuela | +2-5pp |
| 🔴 Sin edge | España, Argentina, Bolivia, Colombia | ≈0pp |

### 2. xG bias dual-pattern

- **Full stats (CSV EUR + ESPN Arg/Bra)**: bias positivo +0.05 a +0.23 → modelo crudo SOBRE-estima goles. `gamma_display=0.59` del motor real existe para corregir esto.
- **Goals-only (API LATAM, ESPN Bol/Ecu/Per/Uru/Ven)**: bias negativo -0.05 a -0.22 → modelo SUB-estima.

**Implicación**: el motor con full stats produce xG inflado que se compresa con gamma_display. Con goals-only no hay inflación → no hace falta gamma → modelo termina sub-estimado.

### 3. Cobertura ESPN stats por liga (iter 3)

| Liga | ESPN provee SoT/shots/corners |
|---|---|
| Argentina, Brasil, Chile, Colombia | ✅ Sí (>95%) |
| Bolivia, Ecuador, Peru, Uruguay, Venezuela | ❌ No (0%) |

### 4. Findings estructurales asociados

- **Bug grid `calibrar_rho.py`** (`adepor-cae`): grid `[-0.30, 0]` retorna 0 espurio cuando true rho es positivo. Visto en EPL temp 2021-23 y LaLiga.
- **Shift de régimen EPL post-COVID** (`adepor-wxv`): rho temp 2025-26 = -0.142 (DC clásico volviendo) vs 2021-23 rho = 0.000. Ventana móvil 2-temp recomendada (`adepor-s7m`).
- **xG bias Bolivia** (-0.20): coherente con feature altitud en SHADOW. Si se activara altitud, bias debería neutralizarse.

## Cómo extender este registro

1. **Nueva iteración walk-forward**: ejecutar script en `analisis/walk_forward_*.py`, guardar JSON, correr `scripts/persistir_walk_forward.py` para insertar en DB.
2. **Nueva liga**: ampliar `LIGAS_LATAM` o `LIGAS` en script + scrape ESPN si aplica + re-run + re-persistir.
3. **Nueva temporada (2025+)**: cuando ESPN tenga la temp, scrape + walk-forward con esa como target.
4. **Audit incremental**: comparar `edge_pp` actual vs anterior en una liga; si caída >2pp, alerta de degradación.

## Para LLM agentes futuros

> Si vas a tocar `motor_calculadora.py`, `gamma_display`, `xg_hibrido` o `ALFA_EMA`, **primero consulta esta tabla** con:
> ```sql
> SELECT * FROM xg_calibration_history WHERE liga = '<liga_target>' ORDER BY iter DESC;
> ```
> y revisa si tu cambio mejoraría el edge (`hit_rate - base_rate_local`) sin romper Brier ni xG_bias.

## Referencias

- Bead: `adepor-bgt` (investigation), `adepor-d7h` (V6 SHADOW infra), `adepor-617` (PROPOSAL H4)
- Commits: `dd25dec` (iter1), `3840acb` (iter2), `8ddb07c` (iter3 inicial)
- Memory: `bd memories xg`, `bd memories v12`, `bd memories motor-adaptativo`
- Scripts: `analisis/walk_forward_{multiliga,latam,full_stats}.py`, `analisis/calibrar_xg_por_liga_ols.py`
- Scraper ESPN: `analisis/scraper_espn_historico.py`

---

## Anexo 2026-04-26: V6 SHADOW (xG OLS recalibrado)

Audit detectó 3 errores estructurales en la fórmula original del manifiesto §II.A:

1. **β_shots_off positivo en código (+0.010) vs OLS empírico (−0.027)** — signo invertido
2. **coef_corner positivo en código (+0.02) vs OLS empírico (−0.055)** — signo invertido
3. **Intercept ausente** (asume 0) vs OLS estima ~+0.46 goles baseline

### Coeficientes OLS persistidos (snapshot 2026-04-26)

44 filas en `config_motor_valores` con sufijo `*_v6_shadow`, 10 ligas + global pool. Fuente: `OLS_2026-04-26_adepor-d7h`.

```sql
SELECT clave, scope, valor_real FROM config_motor_valores
WHERE clave LIKE '%_v6_shadow' ORDER BY clave, scope;
```

### V6 SHADOW EMA + arquitecturas derivadas

- **`historial_equipos_v6_shadow`**: 402 equipos, EMA paralelo construido sobre N=12,455 partidos (12,082 históricos + 373 backtest). Backfill: `scripts/backfill_xg_v6_shadow.py`.
- **V6** = Poisson DC + xG OLS
- **V7** = Skellam + xG OLS (sin tau)
- **V12** = LR multinomial 13 features (xG + H2H + varianza + mes), per-liga + global pool. Calibración: `analisis/calibrar_v12.py`. Pesos: `config_motor_valores.lr_v12_weights`.
- **V12b1/b2/b3** = LR pool global ridge=0.1 con/sin H2H + class_weights. Persistidos: `lr_v12b{1,2,3}_weights`. Re-generar: `analisis/calibrar_v12b.py`.

### Hallazgo OOS estricto (test 2024 N=2,768)

Walk-forward EMA cutoff 2023-12-31, sin leak.

| Modelo | hit | Brier | %X picks |
|---|---:|---:|---:|
| **V0 raw** | **0.488** | **0.6182** | 0.0% |
| V6 OLS+DC | 0.482 | 0.6222 | 0.1% |
| V7 Skellam | 0.482 | 0.6223 | 0.0% |
| V12 LR | 0.473 | 0.6219 | 4.2% |

V0 raw GANA OOS estricto. La superioridad in-sample de V12 (5pp hit) era 100% **leak comparativo** (EMAs incluían el partido evaluado). Conclusión: **xG OLS recalibrado NO mejora la predicción 1X2 OOS** — aunque el bias xG total mejora (+0.08 vs +1.93), eso no se traduce en mejor argmax.

### Audit parches V0 OOS

| Parche | Δhit | ΔBrier | Veredicto |
|---|---:|---:|---|
| Hallazgo G | **−1.2pp** | +0.0044 | EMPEORA. Tóxico OOS. |
| Fix #5 | =0 | =0 | Inocuo. |
| Hallazgo G + Fix #5 | −1.2pp | +0.0057 | Mismo que solo HG |

`HALLAZGO_G_ACTIVO=True` (motor producción default) está degradando hit rate OOS. PROPOSAL `adepor-617` propone desactivarlo.

### Híbrido H4 V0+X-rescue (sobre cuotas reales N=127)

H4 = V0 default + override 'X' si V12 dice argmax=X y P(X) > 0.30.

| | hit | yield_A (argmax siempre) | yield_B (filtro EV>5%) |
|---|---:|---:|---:|
| V0 baseline | 0.488 | +0.157 | +0.255 |
| **H4** | **0.520** | **+0.246** | +0.317 |

Threshold sweep [0.25, 0.50] confirma robustez en [0.25, 0.35]. Threshold elegido: 0.30. **Caveat**: N=127 es chico, CI95 yield ~ ±10pp. PROPOSAL `adepor-617` BLOQUEADO pending N≥500 con scraper football-data.co.uk (ver `docs/plan_ampliacion_cuotas.md`).

### Anexo 2026-04-26 (PARTE 3): F2 plan_ampliacion_cuotas EJECUTADO + V5.0 APROBADO

**Walk-forward OOS estricto sobre Pinnacle closing 2024 (N=2.348, 8 ligas):**

Tabla `cuotas_externas_historico` poblada con 13.332 filas (8.600 mmz4281 EUR + 967 NOR + 3.765 ARG/BRA). Fecha 2026-04-26.

```
Yield walk-forward por liga (warmup 2021-2023, test 2024):
  liga         arch    N    hit    yield     CI95              sig 95%
  Alemania     V12   239  0.477  -0.085  [-0.212, +0.056]   .
  Argentina    V12   279  0.416  -0.010  [-0.165, +0.154]   .
  Brasil       V12   263  0.468  -0.041  [-0.170, +0.094]   .
  Espana       V12   342  0.497  -0.070  [-0.182, +0.044]   .
  Francia      V12   306  0.552  +0.077  [-0.054, +0.207]   .
  Inglaterra   V12   342  0.515  +0.015  [-0.100, +0.142]   .
  Italia       V12   306  0.533  +0.049  [-0.074, +0.169]   .
  Turquia      V12   271  0.594  +0.116  [+0.003, +0.242]  *** UNICA SIGNIF.
```

**H4 sin filtro NO se valida con N grande:**
- H4 yield +0.011 CI95 [-0.040, +0.060] (vs +0.246 con N=127 inicial)
- Reconciliación con N=127 ORIGINAL imposible: partidos_backtest tiene fechas 2026 (mixto LATAM+EUR), cuotas_externas cubre 2021-2024 EUR Pinnacle. Match cuotas internas ↔ Pinnacle 2024: 0/418. Poblaciones disjuntas.

**Decisión final adepor-edk APPROVED:**
- Layer 1 (filtro liga apostar/no): RECHAZADO por usuario.
- Layer 2 (V12 standalone Turquía): APLICADO en motor producción. Manifesto V4.6 → V5.0.
- Layer 3 (H4 X-rescue thresh=0.35): SHADOW, no aplicado.

Implementación V5.0:
- `Reglas_IA.txt` §L (nueva subsección "Arquitectura de Decisión por Liga")
- `motor_calculadora.py:1397-1418` (override fail-silent)
- `config_motor_valores.arch_decision_per_liga = '{"Turquia": "V12"}'`
- SHA-256 actualizado en `configuracion.manifesto_sha256`

Validación end-to-end (corrida real 2026-04-26): 8 partidos turcos re-evaluados, 3 cambiaron pick (Gaziantep FK 2→1, Samsunspor 1→2, Trabzonspor 1→2). Logs `[ARCH-V5.0:V12]` visibles.

Bug colateral resuelto: `config_motor.py::_coerce` no manejaba `tipo='json'` → config flag re-tipado a `'text'` (motor parsea con `json.loads` localmente).

Archivos generados:
- `analisis/yield_v0_v12_F2_extendido_1806.json` (6 EUR base)
- `analisis/audit_yield_F2_sweep_y_ci.json` (sweep H4 + CI95 por liga)
- `analisis/audit_yield_F2_filtro_liga.json` (políticas filtro)
- `analisis/yield_v0_v12_F2_completo_LATAM.json` (8 ligas LATAM+EUR)
- `analisis/yield_v0_v12_F2_sin_filtro_liga.json` (todas las ligas, decisión usuario B)
- `scripts/scraper_football_data_cuotas.py` (con ALIASES_NEW_FORMAT 30 mappings ARG/BRA)
- Snapshot DB: `snapshots/fondo_quant_20260426_224017_pre_v5_layer2_v12_tur.db`

---

## Anexo 2026-04-27 (PARTE 4): Fix #6 piecewise DESCARTADO — yield NO acompaña Brier

### Contexto

PROPOSAL `adepor-u4z` (Fix #6 multi-bucket piecewise) fue aprobado conceptualmente por
el crítico (`adepor-0ll`) en CONDICIONAL pendiente de 5 condiciones. La C5 — "test de
yield con cuotas reales, no solo Brier" — quedó como única condición crítica no
resuelta para promoción a producción. Este anexo documenta la ejecución de C5 y el
descarte definitivo de Fix #6.

### Setup del test

- **Fuente probs**: `predicciones_walkforward.fuente='walk_forward_sistema_real'`
  (resuelve C4: las probs ya tienen HG + Fix #5 aplicado, evitando doble-corrección)
- **Fuente cuotas**: `cuotas_externas_historico.psch/pscd/psca` (Pinnacle closing
  2022-2024, 8 ligas EUR + LATAM)
- **JOIN**: `liga + substr(fecha_partido,1,10) + ht + at` → N=7,867 predicciones
  (23× el N=342 del fix6_v3 ablation original)
- **Filtros operativos del motor**: MARGEN≥0.05, EV≥0.03, KELLY_CAP=0.025
- **Bootstrap pareado**: B=2,000 iteraciones, mismos índices muestreados para A y X
  (captura correlación, más sensible que bootstrap individual)

### Escenarios comparados

- **A** Sistema actual (HG + Fix #5 ya aplicado) — baseline
- **B** + Fix #6 v1 sin shrinkage (11 buckets gap empírico bruto)
- **C** + Fix #6 v2 shrink 50% (recomendación crítico C2)
- **D** + Fix #6 v3 selectivo (1 bucket robusto: 1_0.30-0.35 corr=−0.0236)

### Resultado global (paired bootstrap delta yield vs A)

| Escenario | ΔBrier | ΔY obs | CI95 paired | P(ΔY<0) | sig95 |
|---|---:|---:|---:|---:|---|
| B Fix #6 v1 (sin shrink) | −0.0032 | −1.35 | [−4.94, +2.40] | 74.7% | no |
| C Fix #6 v2 (shrink 50%) | −0.0049 | −2.14 | [−4.59, +0.32] | 95.6% | borderline |
| D Fix #6 v3 (selectivo) | −0.0004 | −0.93 | [−1.63, **−0.21**] | 99.4% | **★ NEG sig** |

**Patrón clave**: correlación inversa Brier ↔ yield. A medida que Fix #6 tiene más
buckets activos, Brier mejora más y yield empeora más. v3 selectivo (1 bucket) — el
más conservador — es el único con CI95 que excluye cero, y excluye por arriba.

### Resultado per-liga (Fix #6 v2 vs baseline, paired bootstrap)

| Liga | N | ΔY% | CI95 | P(ΔY>0) |
|---|---:|---:|---:|---:|
| Brasil | 855 | +2.39 | [−1.19, +6.04] | 0.902 |
| España | 1098 | +3.72 | [−5.21, +13.68] | 0.773 |
| Alemania | 878 | +2.73 | [−4.79, +10.34] | 0.763 |
| Turquia | 987 | −2.38 | [−11.68, +6.19] | 0.295 |
| Italia | 1092 | −5.55 | [−16.82, +6.61] | 0.180 |
| Inglaterra | 1098 | −3.65 | [−11.18, +3.75] | 0.168 |
| Argentina | 907 | −2.69 | [−6.36, +0.79] | 0.071 |
| Francia | 952 | −10.66 | [−21.25, +0.09] | 0.026 |

**0/8 ligas con ΔY > 0 significativo**. Brasil mejor candidato pero CI95_lo=−1.19
(no excluye 0). Aplicar selectivamente sería overfit a 1 liga.

### Reliability alignment NO predice yield

Para cada bucket Fix #6 v2 con N≥30 por liga, calculé `gap × corr_v2`:
- Si `>0`: la corrección va en la dirección del sesgo empírico → debería mejorar Brier
- Si `<0`: la corrección va contra el sesgo → debería empeorar Brier

| Liga | Buckets OK | Buckets WRONG | ΔY |
|---|---:|---:|---:|
| Italia | 9 | 0 (perfect) | −5.55 |
| Inglaterra | 8 | 0 (perfect) | −3.65 |
| Turquia | 7 | 0 (perfect) | −2.38 |
| España | 7 | 0 (perfect) | +3.72 |
| Brasil | 3 | 1 | +2.39 |
| Francia | 6 | 2 | −10.66 |

3 ligas con alineamiento perfecto rompen yield (Italia, Inglaterra, Turquia).
Brasil con 1 WRONG mejora. **No hay correlación entre "reliability bien calibrada"
y "yield mejora"**. Confirmación empírica de que Brier y yield miden cosas distintas.

### Mecanismo identificado

El piecewise opera por outcome y bucket independientes, luego renormaliza a Σ=1.
Es transformación NO monótona conjunta: puede invertir el orden 1>X>2 dentro de un
mismo partido. El motor decide pick por argmax y filtra por margen entre top1 y top2.
Cuando Fix #6 estrecha el margen (caso típico), partidos que el filtro rechazaba con
margen<0.05 pasan a apostarse, y su yield es negativo (eran rechazados por una razón).

Volumen apostado por escenario (N=7,867):
- A baseline: 2,002 picks
- B Fix #6 v1: 3,672 picks (+83%)
- C Fix #6 v2: 2,489 picks (+24%)
- D Fix #6 v3: 2,043 picks (+2%)

Esto es exactamente la patología que `adepor-dx8` (V4.5) intentó cerrar subiendo
margen mínimo a 0.05. Fix #6 lo deshace.

### Veredicto

Fix #6 (en cualquier variante) **NO debe promoverse al sistema de decisión del motor**.
La separación BS Sistema (probs crudas) / BS Calibrado (display-only) queda confirmada
estructuralmente correcta. El BS Calibrado seguirá siendo display-only.

Estado de las 5 condiciones críticas (`adepor-0ll`):

| Cond | Tema | Estado |
|---|---|---|
| C1 | SHADOW MODE primero | OBSOLETO — yield ya descartado OOS |
| C2 | Shrinkage 50% | EJECUTADO (v2). Yield igual de malo |
| C3 | Resolver inconsistencia HG-Manifesto | PENDIENTE en `adepor-6rv` (separado) |
| C4 | Re-calibrar WF con HG+Fix5 | EJECUTADO — `walk_forward_sistema_real` |
| C5 | Test de yield real | EJECUTADO. Veredicto: yield NO acompaña Brier |

Beads cerrados con esta evidencia:
- `adepor-u4z` PROPOSAL: DESCARTADO empíricamente
- `adepor-0ll` CRITICO DECISION: VETO ACTIVO sobre aplicación a producción

Archivos generados:
- `analisis/fix6_yield_vs_brier.py` / `.json` — escenarios A-D, bootstrap individual
- `analisis/fix6_paired_y_per_liga.py` / `.json` — paired bootstrap + reliability per liga

### Implicación para futuros calibradores

Cualquier propuesta futura de calibrador que toque las probs del motor (no solo
display) debe pasar el mismo filtro yield-vs-Brier antes de PROPOSAL. Brier ↓ por sí
solo es condición necesaria pero no suficiente. El test de referencia es:

1. Walk-forward OOS con probs en régimen del sistema actual (HG+Fix5)
2. Cuotas Pinnacle closing reales (no implícitas vig-reducidas)
3. Filtros operativos del motor (margen, EV, Kelly cap)
4. Paired bootstrap con N≥3,000 sobre cuotas reales
5. Criterio promoción: ΔY > 0 con CI95_lo > 0 a nivel global, no per-liga aislada

---

## Anexo 2026-04-27 (PARTE 5): drift estructural V4.7 (HG + Fix #5) — adepor-6rv NO se cierra

### Contexto

PROPOSAL `adepor-6rv` (V4.7 desactivar HG + Fix #5) fue auditado con la misma
metodología paired-bootstrap usada en Fix #6. El resultado es estructuralmente
distinto: V4.7 muestra drift por temporada Y por altura de temporada, lo que lo
hace régimen-dependiente y NO descartable de forma simple.

### Test 1: OOS por temporada (Pinnacle closing 2022-2024, N=7.867)

| Temp | N | YldA% | YldD% (V4.7) | ΔY V4.7 | CI95 | sig | YldF6% | ΔY Fix#6 | sig |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|
| 2022 | 2.442 | +9.82 | +20.95 | **+11.13** | [−6.40, +28.43] | no (P=0.90) | +8.03 | −1.78 | no |
| 2023 | 2.703 | −4.40 | −20.09 | **−15.69** | [−24.89, **−6.51**] | **★ NEG** | −8.04 | −3.64 | borderline |
| 2024 | 2.722 | +0.12 | −1.48 | −1.60 | [−9.85, +6.49] | no | −1.04 | −1.16 | no |

V4.7 oscila entre **+11.13** y **−15.69** (rango **26.82pp**). Signos MIXTOS entre
temps. 2023 sig negativo (P=0.000). 2022 cerca de sig positivo (P=0.90).

Fix #6 estable en [−1.78, −3.64] (rango **2.48pp**, 10× menor). Confirmación de
que el descarte de adepor-u4z es robusto a régimen.

### Test 2: in-sample post-2026-03-16 (cuotas motor real, N=376)

| Escenario | NApost | Hit% | Yield% | ΔY vs A | CI95 paired | P(ΔY>0) |
|---|---:|---:|---:|---:|---:|---:|
| A. sistema_real (HG+Fix5) | 148 | 46.62 | +48.58 | 0 | — | — |
| D. V4.7 puro | 24 | 79.17 | **+208.12** | +159.54 | [+92.51, +232.99] | **1.000** |

V4.7 in-sample tiene yield +208% sobre **24 picks** (CI95 paired ±70pp).
Direccion opuesta al OOS 2023 pero con N pequeño y CI95 amplio. Probable
continuación de régimen 2022-tipo + amplificación por muestra chica.

### Test 3: yield por altura de temporada (todas las temps, N=7.867)

Cuartiles de altura = % de fixture transcurrido por (liga, temp).

| Altura | N | YldA% | YldD% | ΔY V4.7 | CI95 | sig | ΔY Fix#6 | sig |
|---|---:|---:|---:|---:|---:|---|---:|---|
| Q1 (0-25%, arranque) | 1.870 | −6.46 | −27.50 | **−21.03** | [−34.91, **−7.43**] | **★ NEG** | −0.83 | no |
| Q2 (25-50%) | 1.704 | +15.50 | +18.31 | +2.81 | [−11.17, +16.56] | no | **−5.66** | **★ NEG** |
| Q3 (50-75%) | 2.030 | +11.06 | +15.07 | +4.01 | [−6.99, +15.16] | no | **−6.50** | **★ NEG** |
| Q4 (75-100%, cierre) | 2.263 | −13.87 | −22.13 | −8.26 | [−17.60, +1.08] | borderline | +2.60 | no |

**Patrón Q1 catastrófico → Q2-Q3 neutro → Q4 vuelve negativo:**
- En Q1 (arranque) el motor puro destruye yield −21pp con confianza ≥97.5%. Coherente
  con teoría: poca data EMA por equipo (warmup ~10 partidos liquidados), `gamma_display`
  mal calibrado, alta varianza xG. HG+Fix#5 son **prior estabilizador** crítico.
- En Q2-Q3 la EMA convergió, los xG son confiables. Motor puro PUEDE competir
  (yield delta no sig, dirección puntual positiva en regímenes favorables).
- Q4 vuelve negativo: posible fixture congestion (rotaciones, equipos clasificados,
  decisivos descenso/playoff).

Fix #6 invertido: malo en Q2-Q3 (cuando V4.7 podría ser bueno), neutro en Q1/Q4.

### Test 4: drill-down temp × altura (V4.7 ΔY)

| Temp | Q1 | Q2 | Q3 | Q4 |
|---|---:|---:|---:|---:|
| 2022 | −41.90 | −0.22 | **+32.93** ★ POS | +8.33 |
| 2023 | **−21.94** ★ | −5.39 | −11.80 | **−20.18** ★ |
| 2024 | −13.82 | +12.58 | +2.37 | −6.46 |

- **2022**: V4.7 catastrófico Q1, **GANA sig +32.93pp en Q3**, neutro Q4.
- **2023**: V4.7 tóxico EN TODOS los cuartos. Régimen adverso completo (post-COVID
  home advantage extremo? mercado más eficiente?).
- **2024**: Mixed amortiguado.

**La interacción altura × régimen es la fuente del drift, no solo régimen anual.**

### Veredicto

V4.7 NO se cierra. NO se promueve. Re-categorizado como **régimen-dependiente**:
- Sistema actual A (HG+Fix5 ON) es defensivo cross-régimen — la elección segura.
- V4.7 puro podría dominar en regímenes específicos (tipo-2022/24, Q2-Q3) pero
  la implementación requeriría detector validado.
- In-sample 2026 yield +208% es seductor pero CI95 paired ±70pp + drift histórico
  hacen impossible inferir señal estructural con N=24 picks.

Fix #6 (`adepor-u4z`) sí se cerró como descartado: estable cross-régimen, siempre
malo o neutro en todas las particiones del análisis.

### Beads activos derivados

| Bead | Rol |
|---|---|
| `adepor-6rv` | PROPOSAL V4.7 régimen-dependiente, OPEN sin promover |
| `adepor-09s` | INFRA detector régimen + altura, P2 |
| `adepor-j4e` | TRIGGER mensual re-correr análisis OOS-temp + in-sample, P3 |

### Artefactos

- `analisis/v47_yield_validation.py` / `.json` — OOS N=7,867 vs Pinnacle
- `analisis/v47_yield_in_sample.py` / `.json` — in-sample N=376 vs cuotas motor real
- `analisis/yield_por_temp_v47_y_fix6.py` / `.json` — drift por temp 2022/2023/2024
- `analisis/yield_por_altura_temporada.py` / `.json` — Q1/Q2/Q3/Q4 + drill-down

### Implicación general

El test yield-vs-Brier debe completarse con análisis temporal (por temp + por
altura) cuando el PROPOSAL toque parches que actúan como prior estabilizador
(HG, Fix#5, gamma_display). Estos parches pueden parecer "tóxicos" en agregado
de regímenes favorables y "protectores" en regímenes adversos. El análisis
agregado puede esconder ambas narrativas. Al menos 3 cortes recomendados:

1. Por temporada (drift estructural anual)
2. Por altura de temp (prior vs convergencia EMA)
3. Por régimen detectado (cuando exista detector validado)

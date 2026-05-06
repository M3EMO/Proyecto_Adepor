# Filtros de oro — 8 ligas individuales (V2)

**Sesion:** `2026-05-02_team_filtros_oro`  
**Universo:** 7890 partidos matched (stats_partido_espn JOIN cuotas_historicas_fdco).  
**Motor:** V0 (xG = beta_liga * EMA_SOT + 0.03 * EMA_corners). EV >= 1.03.  
**Walk-forward:** betas refit por year_test. 2022 dev / 2023+2024 OOS (excepto Turquia: split intra-2024).  
**Bootstrap CI95:** B=1000, semilla 42.  
**Bonferroni alpha:** 0.05/8 = 0.00625.

## Betas SOT calibrados (entrenamiento year < year_test)

| Liga | beta_2022 |
|---|---|
| Alemania | 0.333 |
| Argentina | 0.266 |
| Brasil | 0.270 |
| Espana | 0.296 |
| Francia | 0.303 |
| Inglaterra | 0.333 |
| Italia | 0.308 |
| Turquia | nan |


## Tabla comparativa: V0 crudo vs V0 + filtro_liga

| Liga | N crudo | yield crudo | hit crudo | sharpe crudo | mdd crudo | N filt | yield filt | hit filt | sharpe filt | mdd filt | CI95 | Anios+ | Cumple |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Alemania | 415 | -0.144 | 0.304 | -2.15 | -76.20 | 78 | +0.191 | 0.423 | +1.14 | -5.40 | [-0.11, +0.54] | 3/3 | SI |
| Argentina | 609 | -0.166 | 0.259 | -2.78 | -113.38 | 75 | +0.282 | 0.413 | +1.53 | -10.99 | [-0.09, +0.66] | 2/3 | SI |
| Brasil | 591 | -0.028 | 0.281 | -0.40 | -53.96 | 233 | +0.075 | 0.258 | +0.60 | -39.64 | [-0.16, +0.35] | 2/3 | SI |
| Espana | 545 | -0.051 | 0.317 | -0.78 | -55.70 | 62 | +0.402 | 0.597 | +2.52 | -5.53 | [+0.09, +0.72] | 3/3 | SI |
| Francia | 399 | +0.132 | 0.381 | +1.69 | -26.93 | 108 | +0.344 | 0.500 | +2.63 | -6.13 | [+0.09, +0.60] | 3/3 | SI |
| Inglaterra | 418 | +0.009 | 0.366 | +0.14 | -44.95 | 82 | +0.166 | 0.451 | +1.08 | -12.22 | [-0.13, +0.47] | 2/3 | SI |
| Italia | 452 | -0.205 | 0.263 | -3.03 | -93.59 | 89 | -0.031 | 0.258 | -0.17 | -31.06 | [-0.37, +0.36] | 1/3 | NO |
| Turquia | 172 | -0.197 | 0.262 | -1.69 | -38.00 | 35 | +0.227 | 0.514 | +1.09 | -4.67 | [-0.17, +0.62] | 2/3 | SI |

## Reglas individuales

### Alemania

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `ema_sot_ag_V <= 3.918`
- `ema_sot_ag_V >= 3.108`

- dev 2022:  yield +0.377, hit 0.462, N=26
- OOS 2023:  yield +0.008, hit 0.400, N=25
- OOS 2024:  yield +0.182, hit 0.407, N=27
- **Pool**: yield +0.191, hit 0.423, N=78, CI95 [-0.105, +0.541], Sharpe +1.14, MaxDD -5.40
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Argentina

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `p2 <= 0.345`
- `prob_pick <= 0.457`

- dev 2022:  yield +0.915, hit 0.577, N=26
- OOS 2023:  yield +0.052, hit 0.360, N=25
- OOS 2024:  yield -0.165, hit 0.292, N=24
- **Pool**: yield +0.282, hit 0.413, N=75, CI95 [-0.093, +0.662], Sharpe +1.53, MaxDD -10.99
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Brasil

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `n_min >= 27.0`
- `cuota_pick >= 2.94`

- dev 2022:  yield +1.393, hit 0.560, N=25
- OOS 2023:  yield +0.113, hit 0.258, N=93
- OOS 2024:  yield -0.242, hit 0.191, N=115
- **Pool**: yield +0.075, hit 0.258, N=233, CI95 [-0.157, +0.346], Sharpe +0.60, MaxDD -39.64
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Espana

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `ema_pos_V >= 56.903`
- `ema_pos_V >= 58.914`

- dev 2022:  yield +0.542, hit 0.667, N=27
- OOS 2023:  yield +0.177, hit 0.500, N=18
- OOS 2024:  yield +0.416, hit 0.588, N=17
- **Pool**: yield +0.402, hit 0.597, N=62, CI95 [+0.091, +0.715], Sharpe +2.52, MaxDD -5.53
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Francia

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `n_min >= 13.5`
- `cuota_pick <= 3.01`
- `p_implicita <= 0.406`

- dev 2022:  yield +0.801, hit 0.667, N=27
- OOS 2023:  yield +0.336, hit 0.500, N=46
- OOS 2024:  yield +0.001, hit 0.371, N=35
- **Pool**: yield +0.344, hit 0.500, N=108, CI95 [+0.089, +0.597], Sharpe +2.63, MaxDD -6.13
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Inglaterra

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `p1 >= 0.408`

- dev 2022:  yield +0.627, hit 0.607, N=28
- OOS 2023:  yield -0.209, hit 0.320, N=25
- OOS 2024:  yield +0.043, hit 0.414, N=29
- **Pool**: yield +0.166, hit 0.451, N=82, CI95 [-0.125, +0.470], Sharpe +1.08, MaxDD -12.22
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**

### Italia

**Tipo split:** `anual_2022dev`

**Regla AND:**
- `ema_sot_ag_L <= 3.738`
- `prob_pick <= 0.452`

- dev 2022:  yield +0.637, hit 0.414, N=29
- OOS 2023:  yield -0.390, hit 0.185, N=27
- OOS 2024:  yield -0.323, hit 0.182, N=33
- **Pool**: yield -0.031, hit 0.258, N=89, CI95 [-0.368, +0.355], Sharpe -0.17, MaxDD -31.06
- Cumple criterio (yld>=+5% & anios>=2/3): **NO**

### Turquia

**Tipo split:** `turquia_intra2024`

**Regla AND:**
- `ev <= 1.16`

- dev 2024 H1: yield +0.355, hit 0.562, N=16
- val 2024 H2: yield -0.025, hit 0.400, N=15
- val 2025:    yield +0.665, hit 0.750, N=4
- **Pool**: yield +0.227, hit 0.514, N=35, CI95 [-0.165, +0.620], Sharpe +1.09, MaxDD -4.67
- Cumple criterio (yld>=+5% & anios>=2/3): **SI**


## Notas metodologicas

- xG V0: `beta_liga * EMA_SOT_for_pre + 0.03 * EMA_corners_pre`. Defensa rival no normalizada (V0 hibrido 70/30 lo absorbe).
- EMAs alpha=0.20 sobre SOT real (no xG sintetico) -> es lo que sustenta `n_min = min(n_L, n_V)`.
- `ev_min=1.03` consistente con motor productivo.
- Greedy stepwise descarta features cuya mejor regla no aporta >+0.005 yield al estado actual.
- Universo Turquia limitado: SOT solo disponible 2024+. Split intra-temporal aceptado por restriccion de datos -- el N de validacion (H2 2024 + 2025) es inferior al de las otras 7 ligas.
- Bonferroni alpha=0.00625 por liga. CI95 empuja por debajo de 0 en varias ligas -> evidencia EXPLORATORIA, no confirmatoria. Promocion productiva requiere bead PROPOSAL + N>=200 OOS adicional.
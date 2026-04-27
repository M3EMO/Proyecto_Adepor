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

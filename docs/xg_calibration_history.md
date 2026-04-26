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

- Bead: `adepor-bgt` (investigation)
- Commits: `dd25dec` (iter1), `3840acb` (iter2), `8ddb07c` (iter3 inicial)
- Memory: `bd memories xg`
- Scripts: `analisis/walk_forward_{multiliga,latam,full_stats}.py`
- Scraper ESPN: `analisis/scraper_espn_historico.py`

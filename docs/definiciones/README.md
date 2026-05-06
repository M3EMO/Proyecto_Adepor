# docs/definiciones/

Especificaciones matemáticas y operacionales de los conceptos clave del proyecto. Cada documento define **una sola cosa** con precisión: notación, fórmulas, pseudocódigo, interpretación.

**Diferencia con docs/papers/:** los `papers/` son hallazgos de investigación (resultados, propuestas, análisis con datos). `definiciones/` son especificaciones formales — referencias atemporales que cualquier sesión futura debe respetar.

## Índice (10 definiciones)

### Motor xG y EMAs

| Archivo | Define |
|---|---|
| `motor_v0_xg.md` | Fórmula motor xG productivo (xg_calc + xg_final híbrido θ=0.70) |
| `ema_forward_strict.md` | EMA forward-strict (warmup=5, α per-liga, no leakage) |
| `rmse_forward_ema.md` | Métrica RMSE forward-EMA goles para validar motor |

### Probabilidades 1X2

| Archivo | Define |
|---|---|
| `dixon_coles_rho.md` | τ(h,a,λ_h,λ_v,ρ), Poisson DC + MLE ρ per-liga |
| `divergencia_modelo_mercado.md` | div = P_modelo[pick] − P_implícita_mercado[pick] |

### Filtros y bins

| Archivo | Define |
|---|---|
| `filtros_picks_v51.md` | M.1 (whitelist liga), M.2 (n_acum), M.3 (Q4) |
| `bin_temporal.md` | bin4/bin8/bin12 desde liga_calendario_temp |

### Datos y validación

| Archivo | Define |
|---|---|
| `match_cuotas_stats.md` | JOIN: ht_fdco_norm, at_fdco_norm, fecha_fdco |
| `walk_forward_paradigmas.md` | Schema A / B / TRUE-OOS / IS=2026 |
| `bonferroni_y_bootstrap.md` | α corregido y CI95% percentile |

## Convención de uso

- **Cualquier nueva sesión que toque motor xG, calibración, o backtests DEBE leer `definiciones/` primero.**
- **Si una sesión modifica una definición:** crear nuevo archivo `<concepto>_v2.md`, NO sobreescribir `<concepto>.md`. Marcar el viejo como deprecated en su header.
- **Cada `paper` que cite una métrica/fórmula debe linkear al archivo de definición correspondiente.**

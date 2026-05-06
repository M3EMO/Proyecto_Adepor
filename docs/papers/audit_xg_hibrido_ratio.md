# Audit ratio híbrido xG (motor_data.calcular_xg_hibrido)

**Fecha:** 2026-05-02
**Trigger:** consulta sobre validez empírica del ratio 0.70/0.30 (xg_calc / goles_reales) en `src/ingesta/motor_data.py:156`.
**Script reproducible:** `analisis/audit_xg_hibrido_ratio_grid.py`
**JSON resultados:** `analisis/audit_xg_hibrido_ratio_grid.json`

## Pregunta

¿`xg_final = 0.70·xg_calc + 0.30·goles_reales` es empíricamente óptimo?

`xg_calc = β_sot(liga)·SOT + 0.010·shots_off + 0.03·corners`

## Método

- Grid θ ∈ {0.0, 0.05, ..., 1.0}.
- Para cada partido del equipo (local o visita): `xg_p(θ) = θ·xg_calc + (1−θ)·goles_propios`.
- EMA forward-looking con α(liga) sobre `xg_p(θ)` — solo pasado estricto.
- Predicción partido `t` = `EMA_{t-1}`. Warmup ≥ 5 partidos del equipo.
- Métrica: RMSE, MAE, Poisson-NLL.
- Universo: `stats_partido_espn` 13,430 partidos × 16 ligas (eventos = 26,860).
- Splits: por año 2022..2026 + IS agregado.

## Resultados

### RMSE forward por año

| θ | 2022 | 2023 | 2024 | 2025 | 2026 | IS |
|---|---|---|---|---|---|---|
| 0.00 | 1.1967 | 1.2214 | 1.1941 | 1.2162 | 1.2058 | 1.2071 |
| **0.10** | **1.1920** | **1.2175** | 1.1891 | 1.2115 | **1.2023** | **1.2026** |
| 0.15 | 1.1927 | 1.2184 | **1.1886** | 1.2098 | 1.2026 | 1.2028 |
| 0.30 | 1.2066 | 1.2322 | 1.1955 | **1.2075** | 1.2120 | 1.2128 |
| 0.50 | 1.2519 | 1.2755 | 1.2234 | 1.2112 | 1.2436 | 1.2479 |
| **0.70** | 1.3249 | 1.3448 | 1.2715 | 1.2225 | 1.2954 | 1.3057 ← motor actual |
| 1.00 | 1.4766 | 1.4891 | 1.3764 | 1.2530 | 1.4059 | 1.4289 |

### Gap motor actual (θ=0.70) vs óptimo

| Split | θ_opt | RMSE_opt | RMSE_motor | Gap RMSE | Gap NLL |
|---|---|---|---|---|---|
| 2022 | 0.10 | 1.1920 | 1.3249 | +11.1% | +26.5% |
| 2023 | 0.10 | 1.2175 | 1.3448 | +10.5% | +25.0% |
| 2024 | 0.15 | 1.1886 | 1.2715 | +7.0% | +15.3% |
| 2025 | 0.30 | 1.2075 | 1.2225 | +1.2% | +1.1% |
| 2026 | 0.10 | 1.2023 | 1.2954 | +7.8% | +17.5% |
| **IS** | **0.10** | **1.2026** | **1.3057** | **+8.6%** | **+19.9%** |

## Hallazgos

1. **El ratio 0.70/0.30 está refutado empíricamente.** En 4 de 5 años el óptimo es 0.10-0.15. Gap NLL +19.9% IS.
2. **xg_calc puro (θ=1.00) es PEOR predictor que goles puros (θ=0).** RMSE 1.4289 vs 1.2071 IS (+18% peor).
3. **2025 es outlier** (N=2,246, año más chico) — único año donde 0.70 es competitivo.
4. **Implicación arquitectural:** la fórmula `β·SOT + 0.01·shots_off + 0.03·corners` agregada partido-a-partido tiene MENOS info incremental que goles directos para predicción forward via EMA. Coherente con el veto Opción B (`memory/project_opcion_B_xg_veto.md`) que documentó multicolinealidad SOT/shots/corners y R² bajo.

## Implicación para Opción B (EMA xG real extranjeros)

**PAUSADA.** Si reemplazamos EMA goles → EMA xg_calc puro para los 1,134 equipos `copa_internacional`, **proyectando esta curva el resultado sería ~+18% peor RMSE**. El beneficio prometido del doc original ("Olimpia 2.456 goles → 1.85 xG real más calibrado") no se sostiene en métrica forward-EMA.

**Pre-requisito para retomar Opción B:** reoptimizar `xg_calc` para que sea efectivamente mejor predictor que goles directos cuando se EMA-iza forward.

## Limitaciones del test

- Métrica RMSE/NLL forward — ortogonal a Brier 1X2 / yield real. Falta validación cruzada con esas métricas.
- α=0.15 fijo per-liga. θ óptimo puede co-variar con α.
- WARMUP=5 (EMA fría excluida). Resultados pueden cambiar con WARMUP distinto.
- β_sot per-liga del motor actual usado tal cual. Si rev β_sot, θ óptimo cambia.

## Decisión

1. Opción B pausada.
2. Iniciar exploración de re-optimización de `xg_calc`. Plan en bead/PR a definir.
3. NO tocar `motor_data.py:156` aún — requiere PROPOSAL formal con evidencia Brier+yield, no solo RMSE.

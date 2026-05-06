# Audit bias goles vs xG_pred — findings

**Fecha:** 2026-05-03
**Sesión:** `2026-05-03_motor_xg_v2`
**Trigger:** usuario pide auditar goles inflados por país/año/equipo para detectar patrones correctibles.

---

## TL;DR

**Bias global:** +0.0618 goles (modelo subestima 6%, leve).

**Bias estructural por liga:** ligas LATAM no-mainstream + Noruega + Turquía → modelo predice **menos goles** de los que realmente caen (+0.15 a +0.22 goles consistentemente).

**Bias por equipo:** existe (15 equipos sub-estimados ≥ 0.20 goles) pero **NO transfiere walk-forward** (overfit — los planteles cambian año-a-año).

**Corrección estática por liga:** mejora 2023 (-0.55%) y 2026 (-0.20%), neutro 2024, **PEOR 2025 (+0.28%)** → inconsistente, no se promueve.

**Insight final:** el Bayesian hierarchical (Fase 2C) **YA captura este bias** vía α_liga aprendido (Noruega α=+0.74, Perú α=+0.63, Chile α=-0.58 — coherentes con residuos por liga). Aplicar corrección estática encima del Bayesian sería doble corrección.

---

## Metodología

Modelo de referencia: V5 NNLS (`xg_calc = 0.273 + 0.247·SOT`, θ=0.20).

Para cada evento (equipo, partido_t):
- `pred_t` = EMA forward de `xg_final` hasta antes del partido t (forward-strict, WARMUP=5)
- `real_t` = goles que metió el equipo en partido t
- `residuo_t` = real_t − pred_t

Agrupado por:
- **Liga** (16 ligas)
- **Liga × año** (drift detection)
- **Equipo** (top 30 con bias > 0.20 goles, N≥30)

Test corrección walk-forward por año: train correcciones < year_test, eval == year_test.

---

## Findings

### 1. Sesgo global

```
N=24,833 eventos post-warmup
mean(residuo) = +0.0618 goles
std(residuo)  = 1.1947
RMSE          = 1.1963
% subestima   = 46.6%
```

Modelo subestima ~6% de un gol promedio. Magnitud **leve, no urgente**.

### 2. Bias por liga (★ patrón sistémico LATAM/Noruega/Turquía)

| Liga | n | mean residuo | std | RMSE | flag |
|---|---|---|---|---|---|
| Bolivia | 1,036 | **+0.225** | 1.310 | 1.330 | ★★★ subestima |
| Noruega | 1,369 | **+0.222** | 1.295 | 1.314 | ★★★ subestima |
| Perú | 905 | **+0.213** | 1.264 | 1.282 | ★★★ subestima |
| Venezuela | 1,006 | **+0.206** | 1.109 | 1.128 | ★★★ subestima |
| Ecuador | 672 | +0.202 | 1.141 | 1.159 | ★★★ |
| Turquía | 2,056 | +0.182 | 1.267 | 1.280 | ★★ |
| Uruguay | 642 | +0.150 | 1.123 | 1.133 | ★★ |
| Inglaterra | 2,220 | +0.061 | 1.278 | 1.279 | ? leve |
| Brasil | 2,253 | -0.024 | 1.122 | 1.122 | OK |
| Argentina | 2,211 | -0.032 | 1.064 | 1.064 | OK |
| España | 2,187 | +0.016 | 1.138 | 1.138 | OK |
| Italia | 2,165 | -0.005 | 1.123 | 1.123 | OK |
| Francia | 1,888 | -0.018 | 1.203 | 1.203 | OK |
| Alemania | 1,743 | +0.027 | 1.320 | 1.320 | OK |
| Chile | 1,370 | -0.023 | 1.192 | 1.192 | OK |
| Colombia | 1,110 | -0.022 | 1.050 | 1.050 | OK |

**Hipótesis explicativa**: las ligas LATAM exóticas tienen porteros más débiles + defensas más permisivas → **conversión SOT→gol es mayor que el β_SOT calibrado**. El motor productivo predice menos goles de los que realmente caen.

### 3. Drift temporal — auto-corrección via EMA

```
Turquía:  2022:+0.331 → 2023:+0.244 → 2024:+0.168 → 2025:+0.049 → 2026:-0.073
Noruega:  2022:+0.365 → 2023:+0.231 → 2024:+0.105
Francia:  2022:-0.182 → 2023:-0.092 → 2024:+0.077 → 2025:+0.060
Inglaterra:2022:+0.110 → 2023:+0.109 → 2024:+0.043 → 2025:-0.016 → 2026:-0.081
```

El bias se **autocorrige** con el tiempo a medida que la EMA acumula datos. Este es exactamente el comportamiento esperado de un EMA sin sesgo estructural — pero la convergencia es **lenta** (~3 años para que el bias caiga de 0.33 → 0.05).

### 4. Top equipos con bias persistente (subestimados ≥ 0.30)

| Liga | Equipo | n | bias |
|---|---|---|---|
| Uruguay | Defensor Sporting | 41 | +0.518 |
| Perú | Alianza Lima | 50 | +0.496 |
| Perú | Sporting Cristal | 50 | +0.489 |
| Noruega | Bodø/Glimt | 85 | +0.478 |
| Perú | Melgar | 50 | +0.451 |
| Noruega | Molde | 88 | +0.393 |
| Uruguay | Nacional | 42 | +0.392 |
| Ecuador | Universidad Católica (Quito) | 43 | +0.391 |
| Turquía | Galatasaray | 109 | +0.389 |
| Uruguay | Peñarol | 43 | +0.379 |
| Ecuador | Deportivo Cuenca | 44 | +0.366 |
| Ecuador | Independiente del Valle | 44 | +0.359 |
| Bolivia | Nacional Potosí | 63 | +0.348 |
| Bolivia | Bolívar | 66 | +0.325 |
| Perú | ADT | 50 | +0.314 |

Top equipos sobre-estimados (3 únicos):
- Montpellier (FRA) -0.232, Troyes (FRA) -0.258, FC Cologne (ALE) -0.293

Los top equipos LATAM son los **dominadores** de su liga (Galatasaray, Bodø/Glimt, Bolívar, Peñarol, Nacional, Independiente del Valle) — meten mucho más de lo que el modelo predice.

### 5. Test corrección walk-forward

#### Corrección bias-equipo
```
IS-sample:           1.1963 → 1.1878 (mejora aparente)
Walk-forward 2026:   1.1967 → 1.2044 (+0.0077, EMPEORA)
Veredicto: OVERFIT — el bias por equipo cambia año-a-año (planteles)
```

#### Corrección bias-liga
| Year test | RMSE orig | RMSE corregido | Δ | Veredicto |
|---|---|---|---|---|
| 2023 | 1.2124 | 1.2069 | **-0.0055** | MEJORA -0.45% |
| 2024 | 1.1805 | 1.1802 | -0.0002 | NEUTRO |
| 2025 | 1.1957 | 1.1991 | **+0.0034** | PEOR +0.28% |
| 2026 | 1.1967 | 1.1942 | -0.0024 | MEJORA -0.20% |

**Inconsistente** → no se promueve.

---

## Por qué la corrección estática falla

El bias por liga **drift-a** con el tiempo (Turquía 2022:+0.33 → 2025:+0.05). Una corrección estática entrenada con todos los años pasados:
- En años con bias todavía alto (2023, 2026): mejora.
- En años con bias ya bajo (2025): empuja **demasiado** → empeora.

**El modelo EMA productivo ya hace parte de esta corrección** vía aprendizaje incremental. Adicionar corrección estática rompe ese balance.

---

## Bayesian hierarchical YA captura este bias

Coefs aprendidos por agente Fase 2C:

```
α_global = 0.7334, β_SOT_global = 0.2064
σ²_α = 0.269 (sd 0.518) — heterogeneidad inter-liga ALTA
σ²_β = 0.0036 (sd 0.060) — heterogeneidad slope BAJA

Top ligas más distintas del global:
  Noruega:  α=+0.74, β_SOT=-0.13 (n=1,440) — coherente con residuo +0.22 ✓
  Perú:     α=+0.63, β_SOT=-0.10 (n=990)   — coherente con residuo +0.21 ✓
  Chile:    α=-0.58, β_SOT=+0.06 (n=1,440) — coherente con residuo -0.02 ✓
```

**El α_liga del Bayesian hierarchical ABSORBE el bias por liga detectado en este audit.** Esa es la razón por la que Bayesian mejora -0.011 RMSE sobre V5 baseline.

**Conclusión**: aplicar corrección estática encima del Bayesian sería **doble corrección**. El finding del audit confirma que Bayesian hierarchical es el approach correcto — porque la heterogeneidad real está en el INTERCEPT por liga, no en pendiente.

---

## Acciones derivadas

1. **NO promover corrección estática bias-por-liga** (inconsistente walk-forward).
2. **NO promover corrección bias-por-equipo** (overfit).
3. **CONFIRMAR Bayesian hierarchical como approach correcto** para Opción C — captura el bias estructural sin overfit.
4. **Re-calibrar β_SOT per-liga con datos recientes (2024+)** podría ser válido ortogonal al Bayesian — pendiente investigación si vale el costo cascada.
5. **Auto-corrección via EMA es lenta (~3 años)**: considerar reducir warmup o ajustar α_ema per-liga para ligas con drift fuerte (Turquía, Noruega).

---

## Artefactos

- `analisis/motor_xg_v2_08_audit_bias.py / .json` — audit completo
- `analisis/motor_xg_v2_09_correccion_bias_liga.py / .json` — test correcciones walk-forward

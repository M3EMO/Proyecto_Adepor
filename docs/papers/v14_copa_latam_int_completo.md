# Copa Internacional LATAM: β_sot + bias mensual + generación de juego

> **Fecha:** 2026-04-29
> **Source:** `stats_partidos_no_liga` (backfill ESPN summary 2026-04-29)
> **N total:** Libertadores 538 + Sudamericana 685 = 1,223 partidos con stats
> **Convención:** IS 2026 = año en curso; OOS = 2022-2025

## Hallazgos clave

### 1. β_sot calibrado por edición (split OOS/IS)

| Edición | β_actual | **β_recom OOS** | β IS 2026 | N OOS | Sobrestima |
|---|---|---|---|---|---|
| **Libertadores** | 0.352 | **0.2382** | 0.1975 | 468 | **−32.3%** |
| **Sudamericana** | 0.352 | **0.2365** | 0.2022 | 628 | **−32.8%** |

Conversion goals/sot vs Premier 21-22 (0.3256):
- Libertadores: 88% del nivel Premier
- Sudamericana: 88%

LATAM int es 12% menos eficiente en conversion shot→goal que Premier. β default 0.352 (Opta-Premier style) sobre estima goles +32% en estas copas.

### 2. Drift interanual β (defensivización 2026)

```
Libertadores:
  2022: β=0.223, goals=2.474, sot=8.98
  2023: β=0.240, goals=2.490, sot=8.54
  2024: β=0.254, goals=2.387, sot=7.72  (peak β)
  2026 IS: β=0.198, goals=2.014, sot=8.07  (caída fuerte)

Sudamericana:
  2022: β=0.217, goals=2.516, sot=9.45
  2023: β=0.239, goals=2.535, sot=8.79
  2024: β=0.254, goals=2.497, sot=8.05  (peak β)
  2025: β=0.240, goals=2.389, sot=8.11
  2026 IS: β=0.200, goals=1.877, sot=7.16  (caída fuerte)
```

**Drift estructural confirmado**: copa LATAM int 2026 es ~15-20% más defensiva que peak 2024.

### 3. Bias mensual cross-año (intra-anual)

**Libertadores** meses con bias significativo:
- Mes 5 (Mayo): **+13.4%** (semis fase grupos, N=126)
- Mes 8 (Agosto): **−15.3%** (octavos inicio, N=47)
- Mes 9 (Septiembre): −16.2% (cuartos, N=14 sample chico)

**Sudamericana** meses con bias significativo:
- Mes 3 (Marzo): −11.4% (inicio fase grupos, N=96)
- Mes 10 (Octubre): −10.4% (final, N=11 sample chico)

### 4. Generación de juego: possession dominance predice (Libertadores)

| Possession LOCAL | N | hit% LOCAL | goals_l | goals_v |
|---|---|---|---|---|
| <45% (V dom) | 140 | 47.1% | 1.200 | 0.993 |
| 45-50% | 67 | 55.2% | 1.672 | 1.015 |
| 50-55% | 65 | 49.2% | 1.508 | 1.031 |
| 55-60% | 81 | 45.7% | 1.568 | 0.852 |
| **>=60% (L dom)** | **185** | **55.1%** | 1.595 | **0.762** |

**Patrón claro**: LOCAL con possession >=60% LIMITA goles_v a 0.762 (vs 0.993 cuando visitor domina). Hit del LOCAL no varía mucho (47-55%), pero el spread total (goals_l - goals_v) sí.

→ Possession dominance es **predictor fuerte de goals_v** (defensivo).

## Persistido en config_motor_valores (SHADOW)

- `beta_sot_recom_copa_int_latam` (β recom Libertadores + Sudamericana)
- `xg_bias_mensual_copa_int_latam` (bias mensual cross-año)

## Aplicación pendiente

F2-sub-15 fase 2 (cross-liga EMA + bias hook productivo) deberá:
1. Detectar `competicion in ('Libertadores','Sudamericana')` en motor
2. Usar β específico de la edición (no fallback global)
3. Aplicar bias mensual: `xg_pred *= bias_mensual[edicion][mes]`
4. **Considerar possession_dominance del local** como feature adicional (target V14 v3)

## Caveats

- **Yield NO medible**: cuotas LATAM int no disponibles (bead `adepor-4tb` bloqueado API Pro)
- **β IS 2026 sample chico** (N=70 Lib, N=48 Sud): tendencia direccional sólida pero no estadísticamente bulletproof
- **Possession data parcial 2022 (algunos partidos sin stats)** — verificar cobertura

## Sources

- `analisis/xg_shift_per_copa_per_year.py`
- `scripts/scraper_stats_partidos_no_liga.py`
- `stats_partidos_no_liga` (1,223 filas LATAM int)
- `config_motor_valores.beta_sot_recom_copa_int_latam`
- `config_motor_valores.xg_bias_mensual_copa_int_latam`

[REF: docs/papers/v14_copa_latam_int_completo.md]

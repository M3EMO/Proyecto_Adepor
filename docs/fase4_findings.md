# Fase 4 — EMA stats por equipo (snapshot 2026-04-27)

> Bead padre: `adepor-6kw`. Estado: **C bloqueado, D entregado, B+A re-evaluar.**
> Re-correr: `py analisis/fase4_ema_stats.py && py analisis/fase4_graficar_timelines.py`

## Setup

EMA dual de 21 stats avanzadas por equipo, walk-forward, snapshot ANTES de
cada partido (sin look-ahead).

- Tabla: `historial_equipos_stats` (PK `liga, equipo, fecha`)
- Columnas: 21 stats × 2 alphas = 42 cols EMA + `n_acum`, `outcome`
- α_corto = 0.40 (≈3-4 partidos para convergir)
- α_largo = 0.10 (≈10 partidos para convergir)
- Snapshots: **19.154** sobre **328 equipos × 12 ligas × 3 temps**
- Smoke: Barcelona ema_pos = 70.6%, Crystal Palace 37.8% ✓ coherente

API consumible para el motor:
```python
from analisis.fase4_ema_stats import predecir_stats_pre_partido
ema = predecir_stats_pre_partido(con, liga, equipo, fecha)
# → dict con 21 EMAs largo + 21 EMAs corto + n_acum
```

## D — Visualización (entregado)

`analisis/fase4_graficar_timelines.py` genera:
- 124 timelines individuales (`graficos/fase4/{liga}/{equipo}_timeline.png`),
  6 paneles por equipo (pos / sots / shot_pct / clearance / crosses / pass_pct).
- 30 comparativos top-5 por liga (`_top5_pos_evolucion.png`, etc).
- 1 arquetipos global (`_global_arquetipos.png`) — Barcelona, PSG, Man City,
  Crystal Palace, Hellas Verona, Boca con líneas de filtro 45/55%.

## C — Score apostable lineal (FALLA)

`analisis/fase4_score_apostable.py` — score = combinación lineal pesada
de EMAs normalizadas (z-score) usando los pesos derivados de los
`delta_g_pct` globales de Fase 3:

| Stat       | Peso  |
|---         |---:   |
| sots       | +1.00 |
| shot_pct   | +0.92 |
| clearance  | +0.69 |
| pos        | −0.44 |
| crosses    | −0.66 |
| pass_pct   | −0.27 |

**Resultado**: Q5 − Q1 yield = **+3.0pp** (no discrimina). Output en
`analisis/fase4_score_validation.json`.

**Diagnóstico**: la señal post-match de Fase 3 (`pos_local 55-65% → yield −49%`)
**no es replicable como predicción pre-partido con EMA absoluta**. La posesión
del próximo partido depende del rival, no sólo del propio equipo.

### Hallazgos colaterales (mismo dataset)

1. **Madurez EMA (`n_acum`) sí discrimina**:

   | Bucket n_acum_l | N apost | Hit% | Yield% |
   |---              |---:     |---:  |---:    |
   | <10             | 92      | 38.0 | **+33.3** |
   | 10-29           | 387     | 38.5 | +5.4   |
   | 30-59           | 392     | 35.7 | -3.8   |
   | ≥60             | 210     | 31.4 | **-13.7** |

   → Motor gana fuerte en arranque de temporada y pierde con EMA madura.
   Posible overfitting a regimenes de temp tardía.

2. **Asimetría posesión rinde, valor absoluto no**:

   | (pos_l − pos_v) | N apost | Yield% |
   |---              |---:     |---:    |
   | <-15            | 77      | +24.1  |
   | -5 a +5         | 455     | -0.0   |
   | >+15            | 10      | -29.5  |

   | ratio pos_l / (l+v) | N apost | Yield% |
   |---                  |---:     |---:    |
   | <0.45               | 244     | +8.5   |
   | 0.45-0.50           | 483     | +4.2   |
   | 0.50-0.55           | 310     | -5.9   |
   | >0.55               | 44      | -18.2  |

## C.bis — Filtro ratio (BORDERLINE)

`analisis/fase4_filtro_asimetrico_bootstrap.py` — política: **NO apostar
local si `ema_pos_l / (ema_pos_l + ema_pos_v) > 0.55`** sobre N=3.117 OOS
con n_acum ≥ 10 ambos equipos.

| Métrica         | Base | +Filtro | Δ |
|---              |---:  |---:     |---:|
| N apostadas     | 1.081 | 1.039  | -42 |
| Yield %         | +1.32 | +2.34  | **+1.01pp** |
| Bootstrap CI95  | -    | -      | [-0.28, +2.30] |
| P(Δ>0)          | -    | -      | 0.932 |

**Veredicto: NO significativo** (CI95 incluye 0, P<0.975). Direccionalmente
positivo pero N bloqueadas (42) insuficiente. Output en
`analisis/fase4_filtro_asimetrico_bootstrap.json`.

## B — Integración al motor (PENDIENTE, baja prioridad)

Dado que C falló y C.bis no es significativo, **NO** hay justificación
empírica para integrar `historial_equipos_stats` al motor todavía.

Si se retoma:
- Hook en `motor_data.py` post-liquidación que actualiza EMAs por equipo
  cada partido nuevo (incremental, no rebuilds completos).
- Pre-fase en `ejecutar_proyecto.py` que llama `predecir_stats_pre_partido`
  para cada partido upcoming y persiste en tabla `pre_partido_stats_features`.

## A — PROPOSAL filtro pos_EMA > 55% (PENDIENTE, recomendado descartar)

Bead pendiente NO crear. La hipótesis original (filtro absoluto) está
falsada por C. La variante asimétrica (ratio) no alcanza significancia.

**Antes de proponer cualquier filtro pos-based**: ampliar OOS para subir N
de partidos donde el filtro aplica (44 → 200+) o cambiar a feature
multivariable (NO un filtro binario).

## Próximos pasos sugeridos (orden empírico)

1. **Re-evaluar significancia con N mayor**: los ~3 años actuales dan
   N=44 partidos donde ratio>0.55. Esperar onboarding de más temps o
   bajar el cut a 0.52 (no probado todavía).
2. **Predecir pos del próximo partido como función de EMA propio Y EMA
   rival** (modelo lineal, no umbral binario). Esto es V13 SHADOW.
3. **Investigar el handoff `n_acum` (madurez EMA)**: el hallazgo
   "yield decae con EMA madura" es REAL (delta -47pp entre <10 y ≥60)
   y merece su propia investigación. ¿Es un proxy de partidos
   tardíos de temp donde el motor degrada? Cruzar con momento_temp
   (otro feature pendiente del epic 6kw).

## Artefactos

```
analisis/fase4_ema_stats.py                       # Build EMA tabla
analisis/fase4_score_apostable.py                 # C — falló
analisis/fase4_score_validation.json              # output C
analisis/fase4_graficar_timelines.py              # D — entregado
analisis/fase4_filtro_asimetrico_bootstrap.py     # C.bis — borderline
analisis/fase4_filtro_asimetrico_bootstrap.json   # output C.bis
graficos/fase4/                                    # 124 + 30 + 1 PNG
```

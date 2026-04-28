# Fase 2 — Análisis yield × momento_temp × diff_pos × granularidad

> Snapshot 2026-04-27. Bead: `adepor-6kw` (Fase 2).
> Re-correr con: `py analisis/fase2_yield_por_features.py && py analisis/graficar_fase2.py`

## Setup

Tras Fase 1 (tabla `momento_temporada` + `posicion_tabla` + 2 views), evaluamos
si las features de altura de temporada y diferencia de ranking explican el
drift observado en el motor.

| Cobertura | In-sample (Si Hubiera) | OOS (walk-forward 2022-2024) |
|---|---:|---:|
| N total | 358 picks reales | 7.867 predicciones × Pinnacle |
| Con `momento_bin` | 358 (100%) | 7.867 (100%) |
| Con `diff_pos` (pj≥3) | 246 (69%) | 7.488 (95%) |

3 granularidades simultáneas: `bin4` (Q1-Q4), `bin8` (O1-O8), `bin12` (D1-D12).

Bootstrap CI95 sobre yield por bin/diff_pos/cell con N≥20 (cells), B=1500 iter.

## Hallazgo #1 — `diff_pos = vis_mucho_mejor` es la única señal sig OOS

OOS agregado N=7.867:

| diff_pos bucket | N apost | Hit% | Yield% | CI95 paired | sig |
|---|---:|---:|---:|---:|---|
| **vis_mucho_mejor** (vis − loc ≤ −5) | 853 | 36.1 | **+10.1** | [+0.1, +20.6] | **★ POS** |
| vis_mejor (−1 a −4) | 516 | 33.9 | −3.6 | [−15.6, +8.6] | no |
| loc_mejor (+1 a +4) | 311 | 35.7 | −5.5 | [−20.1, +9.3] | no |
| loc_mucho_mejor (≥+5) | 197 | 38.1 | −0.5 | [−18.4, +17.9] | no |

El motor identifica **edge real cuando apuesta a visitantes mucho mejores rankeados**.
CI95 al borde (lo=+0.1) — borderline pero significativo al 95%.

In-sample mostró loc_mucho_mejor +52% y vis_mucho_mejor +44% como los dos picos,
pero OOS desmiente loc_mucho_mejor: con N grande el yield colapsa a −0.5%.

## Hallazgo #2 — Drift por temporada estructural

OOS por temp del bucket `vis_mucho_mejor`:

| Temp | N apost | Yield% | CI95 |
|---|---:|---:|---:|
| 2022 | 209 | +10.8 | [−8.4, +31.9] |
| 2023 | 300 | +2.5 | [−15.4, +20.6] |
| **2024** | 344 | **+16.4** | [−0.4, +34.0] |

2024 muestra el yield más alto pero CI95_lo=−0.4 no llega a sig al 95%. La señal
del bucket `vis++` se sostiene cross-temp pero con magnitud variable.

Por contraste, **`vis_mejor` y `loc_mejor` rompen yield en 2023 y 2024** (−10 a −14%
con CI95 que cruza 0 pero apunta neg).

## Hallazgo #3 — Distribución temporal del yield (forma de U invertida confirmada)

OOS yield_A% por momento_bin (con CI95 paired):

| Granularidad | Pico | Valle inicio | Valle final |
|---|---|---|---|
| bin4 | Q2/Q3 ~+15 | Q1=−6.5 | Q4=−13.9 |
| bin8 | O3=+17.3 | O1=−20.7 | O8=−13.4 |
| **bin12** | **D5=+22.6** | **D1=−23.3** | **D12=−18.6** |

bin12 expone que el yield óptimo está en **D5 (~50% de temporada)** y los valles
son D1 y D12. La señal del cierre de temporada (D11-D12) consistentemente negativa
en las 3 temps (2022 D12=+28 atípico, 2023 D12=−35, 2024 D12=−40).

Cross `momento_bin × diff_pos` revela que **D12×loc_mejor tiene −31.3% sig** (CI95
excluye 0): apostar a favoritos locales en cierre de temp es categóricamente malo.

## Hallazgo #4 — Heatmap por temp revela zonas operativas específicas

`fase2_oos_por_temp_bin8.png`:

**Temp 2022**: zonas verdes en O5×vis++ (+25), O6×vis++ (+33), O7-O8 mostly negativo.
**Temp 2023**: pocas verdes — O7×vis++ (+54), D7×vis++ (+19); resto negativo.
**Temp 2024**: O3×vis++ (+37), O4×loc+ (+59), pero D12×loc+ (−59 sig).

**Patrón común**: vis++ en mitad-temp (O3-O7) tiende a verde en todas las temps.
loc+ en cierre (O7-O8) tiende a rojo. Confirma el hallazgo #1 + #3.

## Hallazgo #5 — In-sample 2026 NO replica patrón OOS

In-sample (358 picks, todos en Q1-Q4 calendario):

| diff_pos | Yield_unit% | CI95 unit | sig |
|---|---:|---:|---|
| **vis_mucho_mejor** | +43.8 | [+11.7, +80.4] | ★ POS |
| vis_mejor | +20.7 | [−7.7, +48.4] | no |
| loc_mejor | +37.1 | [−2.5, +77.9] | no |
| **loc_mucho_mejor** | **+52.3** | [+18.3, +90.7] | ★ POS |

In-sample muestra DOS picos sig (vis++ y loc++). OOS solo confirma vis++.
Probable explicación: in-sample 2026 está en arranque/inicio de temp donde
los favoritos locales fuertes (loc++) sí ganan, pero a lo largo de la temp completa
el efecto se diluye.

Confirma la hipótesis "in-sample se inflará en buckets que OOS no sostiene"
asociada al bankroll dinámico amplificado en Q4.

## Implicación operativa preliminar

1. **Considerar PROPOSAL futura**: sobre-ponderar (Kelly cap × 1.5) picks con
   `diff_pos ≤ −5` (vis++) cuando momento_bin esté en zona dorada (bin12 D3-D7).
   Edge OOS estable +10pp. Validar primero con backtest y N≥1500.

2. **Considerar evitar** picks con `diff_pos ≥ +5` (loc++) en cierre de temp
   (bin12 D11-D12). Yield OOS sig negativo en esa intersección.

3. **No promover** la hipótesis loc++ basada en in-sample. Es regresión a la media
   confirmada en OOS.

## Per liga (drill-down adicional)

OOS yield por liga (ver `analisis/fase2_oos_bin8.json`):
- Argentina: vis++ +29.8 (sig), loc++ negativo
- Brasil: vis++ +13, loc++ neutro
- Inglaterra: vis++ +29 sig, loc++ −22 sig negativo
- Italia: extrema volatilidad (D7 −83 sig)

Implicación: hay heterogeneidad por liga. Puede haber subset (TOP-3 por edge) donde
la regla "apostar vis++" sea más segura que en el agregado.

## Limitaciones

- **In-sample N=358 es chico**, los CI95 unitarios son amplios (±35-40pp típicos).
- **OOS no es paired test contra baseline alternativo** (solo CI95 sobre yield del
  bucket). Para PROPOSAL formal: paired bootstrap delta vs sistema actual A.
- **Fase 1 cobertura de posicion_tabla en arranque de temp es 0** (sin partidos
  previos para acumular ranking) — bin12 D1 in-sample tiene N apost = 14 stake_real.
  Esos casos están infrarrepresentados.

## Archivos generados

| Tipo | Ubicación |
|---|---|
| Scripts | `analisis/fase2_yield_por_features.py`, `analisis/graficar_fase2.py` |
| JSONs | `analisis/fase2_in_sample_bin{4,8,12}.json` (3) |
| JSONs | `analisis/fase2_oos_bin{4,8,12}.json` (3, c/u con `agregado` + `por_temp`) |
| Plots | `graficos/fase2_in_sample_bin{4,8,12}.png` (3) |
| Plots | `graficos/fase2_oos_agregado_bin{4,8,12}.png` (3) |
| Plots | `graficos/fase2_oos_por_temp_bin{4,8,12}.png` (3) |
| Plot | `graficos/fase2_diff_pos_overview.png` (vista comparativa con CI95) |

## Próximos pasos sugeridos

- Si la señal `vis_mucho_mejor` se sostiene en N nuevos in-sample (esperar 2 meses),
  diseñar PROPOSAL Fase 3 (ajuste Kelly per diff_pos bucket).
- Fase 3 (scraping posesión) está condicionada a que Fase 2 muestre señal.
  **Resultado actual: hay señal débil en `diff_pos`, justifica Fase 3.**
- Detector de régimen `adepor-09s` debe incluir `momento_bin × diff_pos` matrix
  como feature de clasificación (zonas verde vs rojo cambian por temp).

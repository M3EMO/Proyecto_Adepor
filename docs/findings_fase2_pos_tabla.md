# Findings — Fase 2: poder explicativo de posicion_tabla + momento

> Bead: `adepor-6kw` (claimed 2026-04-28)
> Sample: predicciones_oos_con_features N=7,743 (con pos_local + pos_visita), 8 ligas, temps 2022-24
> Output: `analisis/posicion_tabla_poder_explicativo.json`

## Resumen ejecutivo

**posicion_tabla (pos_local, pos_visita, diff_pos) NO agrega poder explicativo
incremental sobre V5.1**. Hay efectos direccionales en mismatches extremos
y en interaction con momento, pero **CI95 cruzan 0** en casi todas las celdas
suficientemente pobladas. **NO se recomienda avanzar a Fase 3** (scraping
posesion) ni Fase 4 (V12 extendido) sin más datos.

## Hipótesis evaluadas

| Hipótesis | Veredicto |
|---|---|
| pos_local discrimina yield monotónicamente | **NO**. Patrón U-shape ruidoso (+0.7/−2.2/−5.6/+2.6/+8.6 por bucket). |
| diff_pos = mismatch tabla → motor sobreestima dominante | **DIRECCIONAL pero NO sig**. L<<V +13.6 [−2.9,+30.3] borderline; L>>V +18.9 (N=53 ruido). |
| Matriz top-vs-bottom revela hotspots | **HOTSPOT con N grande**: BOT-3 vs TOP-6 +30.5% (N=77). Resto ruidoso. |
| Momento × diff_pos interaction | **PRESENTE pero NO sig**. Q1 L<<V +43.5 (N=52); Q4 globalmente negativo. |
| pos agrega valor sobre V5.1 puro | **NO**. V5.1+pos_filter da +13.9 vs V5.1 puro +17.4 (degrada). |

## Evidencia clave

### T1 — Yield por bucket pos_local

| bucket | NPred | NApost | Hit% | Yield% | CI95 |
|---|---|---|---|---|---|
| TOP-3 | 1042 | 88 | 37.5 | +0.7 | [−26.6, +27.0] |
| TOP-6 | 1105 | 185 | 35.1 | −2.2 | [−22.5, +17.7] |
| MID | 2327 | 549 | 34.2 | −5.6 | [−16.5, +6.7] |
| BOT-6 | 1567 | 502 | 36.5 | +2.6 | [−9.4, +16.1] |
| BOT-3 | 1702 | 634 | 35.5 | +8.6 | [−3.4, +20.2] |

Sin discriminación monotónica. CI95 todos cruzan 0.

### T5 — V5.1 puro vs V5.1 + filtros pos

| Filtro | N | Hit% | Yield% | CI95 |
|---|---|---|---|---|
| BASELINE | 1958 | 35.4 | +1.7 | [−4.7, +8.2] |
| **V5.1 puro** (TOP-4 OOS + n_acum<60 + Q!=3) | **699** | **40.2** | **+17.4** | **[+5.7, +29.0]** ★ |
| V5.1 + diff_pos NOT extremos | 498 | 40.6 | +13.9 | [+1.6, +26.4] (degrada) |
| V5.1 + pos_local ≤ 6 | 91 | 44.0 | +20.7 | [−8.3, +51.2] (N chico, no sig) |
| V5.1 + pos_local > 6 | 608 | 39.6 | +16.9 | [+4.3, +28.8] ★ |

V5.1 puro gana. Cualquier sub-filtro pos reduce N sin mejorar yield.

### T4 — Momento × diff_pos (yields celdas con N≥20)

| momento | L<<V | L<V | L~V | L>V | L>>V |
|---|---|---|---|---|---|
| Q1 arr | **+43.5** (N=52) | +1.4 | −27.7 | −5.7 | −26.1 |
| Q2 ini | +9.7 | +13.4 | +9.0 | +34.6 | +50.5 |
| Q3 mit | **+42.1** (N=101) | +0.1 | +15.8 | −23.7 | +41.9 |
| Q4 cie | −20.0 | −4.8 | −17.7 | −25.5 | +6.3 |

Patrón: Q1+Q3 con local-underdog (L<<V) son las celdas más rentables.
Q4 daña globalmente (consistente con findings 0ac M.3).

### T6 — Heterogeneidad por liga

España es drenador en TODOS los buckets diff_pos (yields negativos).
Argentina positivo en todos. Brasil mixto. Pero estos son patrones a nivel
liga ya capturados por filtro M.1 (TOP-5).

## Conclusión

**Fase 1** (backbone interno momento + pos): completada. Datos en
`predicciones_oos_con_features` cubren 7,743 picks con pos completa.

**Fase 2** (poder explicativo): SIN señal incremental sobre V5.1.

**Fase 3** (scraping posesion): NO se recomienda. Sin señal en Fase 2,
invertir tiempo en scraping no se justifica.

**Fase 4** (V12 extendido con 3 features): NO se recomienda. Las features
disponibles (momento + pos) ya están en el sample y no agregan valor.

## Pendientes / triggers futuros

- Si en N≥1,000 picks adicionales se observa drift en Argentina o España, re-evaluar pos por liga.
- Si en alguna interaction (momento × pos × n_acum) emergiera señal robusta con N≥200 por celda, re-considerar.
- Mantener bead `adepor-6kw` cerrado pero documentado para futura referencia si aparece data nueva (eg. scraping posesion gratuita).

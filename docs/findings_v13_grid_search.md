# Findings — V13 Grid Search: regularización × features × ligas

> Bead: `adepor-3ip` (claimed 2026-04-28)
> Sample: `partidos_historico_externo` JOIN `historial_equipos_stats` N=5,005
> Output: `analisis/v13_grid_search.json`, `analisis/v13_recalibrar_best_variants.json`

## Resumen ejecutivo

Grid search 3 regularizaciones × 3 feature sets × 8 ligas × 2 targets = **144 calibraciones**
evaluadas. Hallazgos:

1. **NNLS gana en yield** (3 de top-5). Ridge gana en Brier, OLS variable.
2. **Argentina F1 NNLS yield +8.3% sobre N=107 OOS Pinnacle 2024** ★ — única liga
   TOP-5 V5.1 con yield positivo en V13 + N grande.
3. **España domina Brier** pero **yields todos negativos** (replica del paradoja
   Brier↔Yield: mejorar calibración no = ganar dinero).
4. **F1 (ofensivas core) > F2 > F3** en muchas ligas. Más features = más overfit.

## Variantes evaluadas

### Regularizaciones

| Reg | Descripción | Pros | Contras |
|---|---|---|---|
| OLS | Sin regularización | Interpretable | Singular en colinealidad, overfit |
| **NNLS** | Coefs ≥ 0, projected gradient | **Sparse, conservador, mejor yield** | Rígido (no permite coefs negativos) |
| RIDGE | L2 con λ ∈ {0.01, 0.1, 1, 10, 100}, CV 5-fold | Suave, todos coefs no-cero | Mejor Brier pero peor yield |
| ENET | L1+L2 mix, coordinate descent + soft thresholding | Sparse + suavidad, α∈{0.1..0.9} | NO supera a NNLS en yield ni a Ridge en Brier |

### Feature sets

| Set | Features | N feats |
|---|---|---|
| F1_off | sots, shot_pct, corners + def_sots_c, def_shot_pct_c | 5 |
| F2_pos | F1 + pos, pass_pct | 7 |
| F3_def | F2 + tackles_c (visita), blocks_c (visita) | 9 |

## TOP-10 yield OOS (N≥10 picks)

| Rank | Liga | Feat | Reg | N | Hit% | Yield% | CI95 | Brier |
|---|---|---|---|---|---|---|---|---|
| 1 | Francia | F2_pos | NNLS | 36 | 38.9 | **+20.3** | [−30.2, +76.4] | 0.6304 |
| 2 | Francia | F3_def | NNLS | 36 | 38.9 | +20.3 | (igual) | 0.6304 |
| 3 | Francia | F3_def | RIDGE | 39 | 35.9 | +10.6 | [−41.0, +59.2] | 0.6435 |
| 4 | **Argentina** | **F1_off** | **NNLS** | **107** | **34.6** | **+8.3** | **[−20.7, +39.3]** | 0.6427 |
| 5 | Italia | F2_pos | RIDGE | 52 | 38.5 | +3.7 | [−34.9, +40.9] | 0.6326 |
| 6 | Francia | F3_def | OLS | 46 | 34.8 | +3.6 | [−38.1, +45.6] | 0.6451 |
| 7 | Francia | F2_pos | RIDGE | 36 | 36.1 | +3.6 | [−45.0, +53.8] | 0.6277 |
| 8 | Argentina | F2_pos | NNLS | 66 | 33.3 | +2.2 | [−36.6, +39.9] | 0.6438 |

## TOP-10 mejor Brier (España domina pero rompe yield)

| Rank | Liga | Feat | Reg | Brier | Yield% | CI95 |
|---|---|---|---|---|---|---|
| 1 | España | F1_off | NNLS | 0.6044 | −28.5 | [−70.1, +19.8] |
| 2 | España | F3_def | NNLS | 0.6072 | −47.4 | [−84.7, −6.6] |
| 3 | España | F1_off | RIDGE | 0.6086 | −34.0 | [−71.9, +10.7] |
| ... | ... | ... | ... | ... | ... | ... |

## Decisión BEST variant por liga (post-grid)

| Liga | Decisión | Razón |
|---|---|---|
| **Argentina** | F1_off NNLS | yield +8.3% N=107 ★ TOP-5 V5.1 (LIVE) |
| **Francia** | F2_pos NNLS | yield +20.3% N=36 (mejor variante absoluta) |
| **Italia** | F2_pos RIDGE | yield +3.7% N=52 (Ridge también funciona) |
| Brasil | NO calibrar | yields todos < 0 con N≥10 |
| Chile | NO calibrar | yields todos < 0 |
| Colombia | NO calibrar | yields negativos |
| España | NO calibrar | yields todos negativos a pesar de mejor Brier |
| Inglaterra | NO calibrar | yields todos negativos |
| Turquía | NO calibrar | sin train data 22+23 (fallout calibrar_rho.py adepor-a0i fix) |

## Observaciones técnicas

### NNLS produce coefs sparse

Argentina F1 NNLS solo activa `atk_sots = +0.160`. Todos los demás coefs en cero.
Argentina F1 NNLS visita: solo `atk_sots = +0.072` y `atk_corners = +0.068`.

**Interpretación**: el motor con NNLS aprende que SOTs es la única señal robusta para
predecir goles del local en Argentina, y rechaza las otras features como ruido. Esto es
lo opuesto de Ridge que retiene todos los coefs (incluyendo `atk_shot_pct = -1.222`
en Italia, signo contraintuitivo).

### Italia RIDGE tiene coefs raros

Italia F2 RIDGE local: `atk_shot_pct = -1.222`, `def_shot_pct_c = +1.555`. Esto
**no tiene sentido físico** (mejor shot_pct del atacante DEBERÍA aumentar xG, no
disminuirlo). Es el sello de Ridge sin restricciones de signo. Pero el yield agregado
es +3.7%, así que la combinación lineal compensa.

### CI95 todos cruzan 0

Ningún top-yield cruza el umbral de significancia estadística (CI95_lo > 0).
N picks insuficiente para conclusión definitiva. Necesario validar longitudinalmente
con N≥200 SHADOW post-2026-04-28.

## Implicaciones operativas

### Para SHADOW logging actual

V13 ahora se logea con la BEST variant por liga. El motor:
- En Argentina: aplica F1 NNLS (xG = ~0.16 × sots + intercept)
- En Francia: aplica F2 NNLS (xG = ~0.024 × pos + 0.027 × corners + intercept)
- En Italia: aplica F2 RIDGE (combo de 7 features)
- Otras 9 ligas: V13 marcado como no aplicable (v13_aplicable=0)

### Para futura promoción

Trigger N≥200 picks SHADOW liquidados con yield V13 > V0 CI95_lo > 0 → considerar
`[PROPOSAL: MANIFESTO CHANGE]` para activar V13 en argmax para esa liga
(análogo a V5.0 Layer 2 Turquía V12).

### Lo que NO hace este grid

- **ElasticNet AÑADIDO 2026-04-28**: implementado coordinate descent + soft thresholding.
  CV grid (lambda × alpha). Resultado: ENET aparece 4 veces en top-10 yield pero NO
  supera a NNLS en ninguna liga TOP. Argentina F1 ENET +3.7 (vs NNLS +8.3). Francia F2
  ENET +13.2 (vs NNLS +20.3). En Italia degrada (F2 RIDGE +3.7 → F2 ENET -17.5).
  Conclusión: ENET es menos selectivo (más picks apostados) pero peor yield. Mantener
  NNLS/RIDGE como BEST.
- **NO testea Alquimia B** (LR multinomial sobre features): ya existe V12 con esa
  arquitectura sobre xG legacy.
- **NO testea Alquimia C** (xG ridge + piecewise post-hoc): se agregaría como capa
  display-only si fuera relevante.

## Próximos pasos

- [x] Grid search ejecutado y documentado
- [x] BEST variants persistidas en `v13_coef_por_liga`
- [x] `motor_calculadora.py` refactorizado para usar feature_sets dinámicos por liga
- [ ] Acumular N≥200 picks SHADOW con V13 (ETA ~3-6 meses)
- [ ] Re-evaluar mensualmente con datos OOS nuevos (`adepor-j4e`)
- [ ] Si V13 sostiene yield CI95_lo > 0 sobre N≥200 → PROPOSAL: MANIFESTO CHANGE para
  activar V13 en argmax (al menos en Argentina)

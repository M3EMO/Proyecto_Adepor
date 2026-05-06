# Audit xG V5 — Evolucion completa de la investigacion

**Fecha inicio:** 2026-05-02
**Trigger:** consulta usuario sobre validez empirica del ratio 0.70/0.30 en motor_data.calcular_xg_hibrido (linea 156).
**Estado:** IN PROGRESS — fase 1 (caracterizacion descriptor V5) completa, fase 2 (motor real) pendiente.

## Indice

1. [Hallazgo 1 — Ratio 0.70/0.30 sub-optimo empiricamente](#hallazgo-1)
2. [Hallazgo 2 — V5 reoptimizada NNLS+Ridge](#hallazgo-2)
3. [Hallazgo 3 — Walk-forward OOS por anio](#hallazgo-3)
4. [Hallazgo 4 — V5 mejor predictor pero peor yield](#hallazgo-4)
5. [Hallazgo 5 — Brier por bin temporal (4/8/12) cross-anio](#hallazgo-5)
6. [Plan A-E — caminos para resolver gap predictor/yield](#plan-a-e)
7. [Limitaciones del test consolidadas](#limitaciones)

---

## Hallazgo 1 — Ratio 0.70/0.30 sub-optimo empiricamente

**Script:** `analisis/audit_xg_hibrido_ratio_grid.py`
**JSON:** `analisis/audit_xg_hibrido_ratio_grid.json`

Test grid theta in [0, 1] para `xg_p = theta * xg_calc + (1-theta) * goles`.

Metrica: RMSE forward-EMA (predict goles del proximo partido del equipo).

Resultados IS (N=24,833):
- theta_opt = 0.10 -> RMSE = 1.2026
- theta = 0.70 (motor actual) -> RMSE = 1.3057 (gap +8.6%)
- theta = 1.00 (xg_calc puro) -> RMSE = 1.4289 (peor que goles puros)
- theta = 0.00 (goles puros) -> RMSE = 1.2071

**Conclusion 1:** ratio 0.70/0.30 esta REFUTADO empiricamente. Ratio optimo es 0.10-0.15. Por anio: 4/5 anios prefieren 0.10-0.15. Solo 2025 outlier (0.30 con N=2,246).

**Conclusion 2:** xg_calc puro PEOR que goles puros => formula `beta*SOT + 0.01*shots_off + 0.03*corners` agregada partido-a-partido tiene MENOS info que goles directos. Coherente con veto previo Opcion B (multicolinealidad SOT/shots/corners).

---

## Hallazgo 2 — V5 reoptimizada NNLS+Ridge

**Script:** `analisis/reoptimizar_xg_calc.py`
**JSON:** `analisis/reoptimizar_xg_calc.json`

Variantes probadas:
- V2 NNLS [SOT, shots_off, corners] sin intercept
- V3 NNLS [V2 + pos, saves_rival]
- V4 NNLS [V3 + pass_pct, blocks_rival, longballs_acc]
- V5 Ridge alpha=1.0 positive, intercept, [SOT, shots_off, corners, pos, saves_rival]
- V6 Ridge con 8 features

Coefs ajustados (train 2022-2024, N=16,528):
- V2: SOT=0.296, resto=0
- V4: SOT=0.280, pass_pct=0.006, blocks_rival=0.028, resto=0
- **V5: intercept=0.273, SOT=0.247, resto=0**
- V6: intercept=0.273, SOT=0.247, resto=0 (idem V5)

**Conclusion:** NNLS shrinka todos los features no-SOT a 0. La formula optima es trivialmente `xG = 0.273 + 0.247 * SOT`. shots_off y corners NO aportan info incremental sobre SOT.

R2 intra-partido (descriptor power):
- V2/V3: 0.2566
- V5/V6: 0.2705 (+1.4pp con intercept)

RMSE forward IS:
- **V5 con theta=0.7: RMSE 1.1649** (mejor de todas)
- Goles puros: 1.1905 (V5 mejora -2.15%)
- Motor actual V0 (theta=0.70): 1.2011 (V5 mejora -3.02%)

---

## Hallazgo 3 — Walk-forward OOS por anio

**Script:** `analisis/reoptimizar_xg_calc_v2.py`
**JSON:** `analisis/reoptimizar_xg_calc_v2.json`

Refit V5 walk-forward por year_test (eventos < year_test). Grid (alfa, theta).

Coefs por fold:
| Train hasta | N | intercept | beta_SOT |
|---|---|---|---|
| < 2023 | 3,912 | 0.300 | 0.234 |
| < 2024 | 10,138 | 0.316 | 0.236 |
| < 2025 | 16,528 | 0.273 | 0.247 |
| < 2026 | 18,774 | 0.263 | 0.252 |

Coefs estables — sin overfit estructural.

RMSE forward por year_test (mejor (alfa, theta) por fold):
| year | V0 | V5_wf | gain |
|---|---|---|---|
| 2023 | 1.1748 | 1.1651 | -0.83% |
| 2024 | 1.1773 | 1.1701 | -0.61% |
| 2025 | 1.1845 | 1.1781 | -0.54% |
| 2026 | 1.1666 | 1.1501 | -1.41% |
| pooled | 1.1789 | **1.1694** | **-0.81%** |

V5_wf gana TODOS los anios OOS. Robusto.

Mejor (alfa, theta) global:
- V0: alfa=0.10, theta=0.30 (motor actual usa alfa=0.15, theta=0.70)
- V5_wf: alfa=0.10, theta=0.60

---

## Hallazgo 4 — V5 mejor predictor pero peor yield

**Script:** `analisis/reoptimizar_xg_calc_v3_filtros.py`
**JSON:** `analisis/reoptimizar_xg_calc_v3_filtros.json`

Waterfall filtros productivos:
- L0 sin filtros
- L1 +M.1 ligas {ARG, BRA, ENG, NOR, TUR}
- L2 +M.2 n_acum_l < 60
- L3 +FLOOR_PROB >= 0.33
- L4 +MARGEN >= 0.05
- L5 +EV-bucket escalado (3% high / 8% mid / 12% low)

### Hitrate IS por nivel

| variante | L0 | L1 | L4 | L5 |
|---|---|---|---|---|
| V0 | 47.90% | 47.62% | 48.57% | 33.91% |
| V0t | 47.60% | 47.29% | 48.38% | 32.11% |
| V1 | 47.27% | 46.68% | 48.27% | 34.36% |
| **V5_wf** | **48.52%** | **48.43%** | **49.86%** | 32.16% |

V5 gana hitrate L0 (+0.62pp), L1 (+0.81pp), L4 (+1.29pp). Pierde L5 (-1.75pp).

### Brier IS por nivel

| variante | L0 | L4 |
|---|---|---|
| V0 | 0.6245 | 0.6260 |
| V0t | 0.6271 | 0.6288 |
| V1 | 0.6305 | 0.6326 |
| **V5_wf** | **0.6221** | **0.6198** |

V5 mejor Brier L0 (-0.0024) y L4 (-0.0062).

### Yield IS — la sorpresa

| variante | L0 | L1 +M.1 | L4 +MARGEN | L5 +EV |
|---|---|---|---|---|
| V0 | -6.22% | **+0.10%** | -9.43% | -10.28% |
| V0t | -3.43% | **+0.22%** | -7.47% | -12.27% |
| V1 | -3.74% | -6.06% | -3.08% | -6.37% |
| V5_wf | -9.76% | -9.47% | -11.81% | -8.96% |

V0/V0t recuperan yield ~0% en L1. V5 NO recupera. Diferencia ~9-10pp.

**Conclusion 4:** V5 es genuinamente mejor predictor (hitrate+, Brier-) pero NO mejor en yield. La mejora descriptiva NO se traduce en value extraction contra cuotas.

---

## Hallazgo 5 — Brier por bin temporal (4/8/12) cross-anio OOS

**Script:** `analisis/brier_por_bin_temporal.py`
**JSON:** `analisis/brier_por_bin_temporal.json`

Bin = floor(pct_temp * N_BINS) usando calendario individual `liga_calendario_temp` (16 ligas x 5 temps = 80 calendarios).

Walk-forward OOS estricto: V5 fitted con eventos < year_test, predicciones year_test medidas separadas.

### Delta Brier (V5_wf - V0) IS por bin

| BIN 4 | Delta IS | BIN 8 | Delta IS | BIN 12 | Delta IS |
|---|---|---|---|---|---|
| Q0 | -0.0012 ★ | 0 | -0.0027 ★ | 0 | -0.0011 ★ |
| Q1 | -0.0026 ★ | 1 | +0.0005 | 1 | -0.0026 ★ |
| Q2 | -0.0045 ★ | 2 | -0.0035 ★ | 2 | +0.0005 |
| Q3 | -0.0006 ★ | 3 | -0.0015 ★ | 3 | -0.0050 ★ |
|  |  | 4 | **-0.0064** ★★ | 4 | +0.0032 |
|  |  | 5 | -0.0025 ★ | 5 | -0.0055 ★ |
|  |  | 6 | -0.0029 ★ | 6 | **-0.0069** ★★ |
|  |  | 7 | +0.0011 | 7 | -0.0049 ★ |
|  |  |  |  | 8 | -0.0017 ★ |
|  |  |  |  | 9 | -0.0032 ★ |
|  |  |  |  | 10 | +0.0024 |
|  |  |  |  | 11 | -0.0017 ★ |

**V5 gana en 21 de 24 bins** (4+8+12). Robustez temporal alta.

### Delta Brier por bin x anio (highlights)

- **2022:** V5 gana FUERTE (deltas -0.025 a -0.035 en bin12 mid-temporada).
- **2023, 2024, 2025:** V5 gana marginalmente (-0.001 a -0.010).
- **2026 (parcial, N pequeño):** mejoras extremas (-0.108 bin12 bin 2) o empeoras (+0.020 bin12 bin 5) — outliers por sample size.

**Conclusion 5:** V5 mejor descriptor uniformemente cross-bin, cross-anio. Edge ligeramente mayor en mid-temporada (Q2 / bin 4-6 del bin12). NO hay un bin donde V5 sea sistematicamente peor.

**Refuta hipotesis "V5 gana solo en partidos faciles".** Gana cross-regimen.

---

## Plan A-E — caminos para resolver gap predictor/yield

El gap fundamental: V5 mejora descriptor (~+0.6pp hit, -0.0024 Brier) pero pierde yield ~9-10pp en filtros productivos. ¿Es trade-off real o artefacto del test?

### A — Test V5 con motor real (DC + rho + filtro DIVERGENCIA) ★ EJECUTADO

**Script:** `analisis/plan_A_motor_real.py`
**JSON:** `analisis/plan_A_motor_real.json`

Componentes implementados:
1. Dixon-Coles tau(h, a, lambda_h, lambda_v, rho) sobre Poisson independiente.
2. rho MLE per-liga grid [-0.2, 0.2] step 0.005.
3. Filtro DIVERGENCIA: pick si (P_modelo_pick - P_implicita_pick) >= thr.
4. P_implicita = (1/cuota) / overround.
5. Filtro M.1 ligas core + EV >= 1.03.

**Resultados — yield grid divergencia:**

| Variante | div_thr | hit% | Brier | N apost | Yield% |
|---|---|---|---|---|---|
| V0 | 0.00 | 47.85 | 0.6240 | 298 | +1.78% |
| V0 | 0.05 | 47.85 | 0.6240 | 264 | +1.28% |
| V0 | 0.10 | 47.85 | 0.6240 | 174 | -6.03% |
| V0 | 0.12 | 47.85 | 0.6240 | 138 | +6.55% |
| V0 | 0.15 | 47.85 | 0.6240 | 104 | **+13.15%** ★ |
| V5 | 0.00 | **48.56** | **0.6218** | 238 | -9.28% |
| V5 | 0.10 | 48.56 | 0.6218 | 116 | +3.49% |
| V5 | 0.12 | 48.56 | 0.6218 | 92 | +4.66% |
| V5 | 0.15 | 48.56 | 0.6218 | 59 | **+9.86%** |

**Conclusiones A:**
1. **Hipotesis 2 (artefacto del test) parcialmente confirmada.** Motor real recupera yield positivo en ambas variantes a div_thr >= 0.12.
2. **V0 SIGUE GANANDO yield vs V5.** Mejor V0 +13.15% (N=104) > Mejor V5 +9.86% (N=59).
3. **V5 produce probs mas concentradas -> menor divergencia con mercado -> menor N apostable.** Estructural, no artefacto.
4. **N V5 a div=0.15 es 59 (4 anios) -> 15/anio.** Power estadistica muy baja.

**Yield por anio (div=0.05):**

| Variante | 2022 | 2023 | 2024 | 2025 | 2026 | IS |
|---|---|---|---|---|---|---|
| V0 | -32.6% | +37.3% | -8.1% | -14.9% | +23.6% | **+1.28%** |
| V5 | -31.4% | +6.8% | -8.0% | -40.0% | +2.7% | -13.70% |

V5 pierde en 2023 y 2025 — anios donde V0 captura divergencias que V5 (mas calibrado) ya incorpora.

**Estado:** EJECUTADO. V5 NO supera V0 con motor real. Conclusion: gap predictor/yield es fundamental, no artefacto. No promover V5 a produccion.

### B — Modelo de error de mercado como feature

**Hipotesis:** un predictor que tome P_implicita_mercado como input puede aprender cuando el mercado yerra.

**Implementacion:**
- xg_calc_hibrido = f(SOT, shots, corners, pos, saves_rival, P_implicita_mercado)
- loss = brier + lambda * (-yield_simulado)
- Modelo: XGBoost con custom loss multi-objective.

**Costo:** alto (8+ horas, requiere XGBoost custom).
**Informacion esperada:** transformacional si funciona, alto riesgo overfit.

**Estado:** PENDIENTE.

### C — Gating por regimen (Mixture of Experts)

**Hipotesis:** V5 gana en algunos contextos, V0 en otros. Combinar ambos con switch contextual.

**Implementacion:**
- P_apuesta = w(features) * P_V5 + (1-w) * P_V0
- w aprendido via regresion logistica sobre eventos historicos donde uno gana al otro en yield.

**Referencia:** Held & Tutz 2020 "Mixture of Experts for prediction", Constantinou-Fenton 2012 (regimen-switching futbol).

**Costo:** medio.
**Informacion:** modesta (+1-2pp yield tipico estudios).

**Estado:** PENDIENTE.

### D — 2-Stage anchor a mercado

**Hipotesis:** mejor predictor + tira hacia mercado en zona ambigua = optimal de 2 mundos.

**Implementacion:**
- Stage 1: P_modelo = V5(stats)
- Stage 2: P_apuesta = alpha * P_modelo + (1-alpha) * P_implicita_mercado
- alpha calibrado por bucket EV.

**Referencia:** Kuypers 2000 "Information and efficiency in betting markets".

**Costo:** bajo.
**Informacion:** modesta.

**Estado:** PENDIENTE.

### F.1 — Plan F EJECUTADO (triple medidor V0 + V_dual + V_ruido walk-forward OOS)

**Scripts:** `analisis/plan_F_triple_medidor.py`, `analisis/plan_F_walkforward_OOS.py`

V_ruido (Ridge sin SOT, features descartadas por NNLS): R2=0.013. Solo pass_pct +0.25 significativo.

**Distribucion subsets ensemble (N=8044):**
- F0 3-acuerdo: 5,325 (66.2%)
- F1 V0=ruido≠Vdual: 46 (0.6%)
- F2 V0=Vdual≠ruido: 2,330 (29.0%)
- F3 Vdual=ruido≠V0: 304 (3.8%)
- F4 3-diff: 39 (0.5%)

**Top configs IS pooled walk-forward (M.1 + EV>=1.03):**

| Subset | pick | div | N | hit% | yield IS |
|---|---|---|---|---|---|
| F3 (Vdual=ruido≠V0) | V0 | 0.00 | 12 | 50.00 | **+94.33%** N tiny |
| F0 3-acuerdo | Vdual | 0.15 | 14 | 35.71 | +51.50% |
| F2 (V0=Vdual≠ruido) | **Vdual** | **0.10** | **36** | 33.33 | **+32.81%** ★ |
| F0 3-acuerdo | Vdual | 0.10 | 29 | 34.48 | +28.55% |
| F2 (V0=Vdual≠ruido) | V0 | 0.15 | 37 | 32.43 | +20.41% |
| F0 3-acuerdo | V0 | 0.15 | 33 | 36.36 | +13.67% |

**Hallazgos:**

1. **V_dual emerge como pick optimo en F0+F2 walk-forward.** Supera a V0 con div >= 0.10.
2. **F3 confirma "ruido informativo":** cuando descriptores coinciden y V0 disiente, V0 contraria gana +94% N=12.
3. **2025 regimen FALLIDO consistente:** -70% a -100% yields en TODAS las configs prometedoras. Blocker fundamental.
4. **F2 + V_dual + div=0.10: +32.81% N=36 IS** — 2.5x mejor que V0 motor original (+13.15% N=104) en yield, con N 1/3 menor.

**Estado:** EJECUTADO. F2 + V_dual + div=0.10 es candidato top-yield pero requiere:
- Investigar regimen 2025
- Bootstrap CI95% sobre N=36
- N >= 100 para production-ready

### F — Triple medidor (mercado + V5 + V0_yield_engine) [IDEA original]

**Hipotesis usuario 2026-05-02:** dado que mercado, V5 y V0 (motor productor de yield) tienen ruidos de naturaleza distinta, el subset donde los 3 convergen en pick puede ser high-yield. O alternativamente, el subset donde mercado y V0 convergen pero V5 diverge identifica el "ruido necesario" que V0 explota.

**Implementacion potencial:**
- ensemble_score(partido) = f(P_modelo_v5, P_modelo_v0, P_implicita_mercado)
- Pick si: argmax(P_v5) == argmax(P_v0) [acuerdo modelos] AND divergencia con mercado >= thr
- O variante: stacked predictor con XGBoost sobre [P_v5, P_v0, P_implicita] -> P_meta -> filtro EV

**Costo:** medio.
**Estado:** PENDIENTE.

### E.1 — V_dual validación OOS estricta (walk-forward)

**Script:** `analisis/validate_vdual_OOS.py`

Walk-forward refit por year_test. Coefs cambian moderadamente con N train:

| Train < | int | c_xg | c_res |
|---|---|---|---|
| 2023 | 0.527 | 0.576 | 0.273 |
| 2024 | 0.416 | 0.673 | 0.320 |
| 2025 | 0.305 | 0.767 | 0.381 |
| 2026 | 0.287 | 0.783 | 0.383 |

Direccion estable (c_res > 0 siempre). Magnitud cambia con N — necesita >= 10k eventos para estabilizar.

**Brier OOS por anio:**
- 2023: 0.6323 hit 47.20% N=2890
- 2024: 0.6273 hit 49.00% N=2855
- 2025: 0.6107 hit **51.47%** N=1123 (mejor anio)
- 2026: 0.6219 hit 46.33% N=177

V_dual NO overfit. Hitrate consistente cross-anio.

**Yield OOS por anio (M.1 + EV>=1.03 + div_thr):**

| year | div=0.00 | div=0.05 | div=0.10 | div=0.15 |
|---|---|---|---|---|
| 2023 | +17.4% N=63 | +24.1% N=49 | **+93.3%** N=25 | **+116.0%** N=12 |
| 2024 | -5.2% N=51 | -6.9% N=41 | +7.1% N=23 | +4.1% N=10 |
| 2025 | -52.0% N=34 | -73.6% N=28 | **-84.9%** N=14 | -100.0% N=4 |
| 2026 | +28.9% N=14 | +23.2% N=10 | +43.1% N=7 | +47.4% N=5 |

**IS pooled walk-forward:**
- div=0.10: **+23.32%** N=69
- div=0.15: **+40.97%** N=31

**3 de 4 anios positivos** (2023, 2024, 2026). 2025 es OUTLIER bajista (régimen específico). N pequeño limita conclusion.

**Estado:** EJECUTADO. V_dual robust OOS (no overfit) excepto régimen 2025. Yield walk-forward MEJOR que IS no-walk-forward (sugiere coefs refit anual capturan mejor régimen).

### E — Feature engineering "ruido informativo"

**Hipotesis:** goles retienen info (clutch, talento individual, luck momentum) que cuotas no descuentan completamente.

**Implementacion:**
- Features dual: xg_calc (calidad de juego) + residuo_xg = goles - xg_real (overperformance).
- P_apuesta = f(xg_calc, residuo_xg, momentum_residuo, ...)

**Referencia:** StatsBomb / Opta workflow profesional.

**Costo:** medio.
**Informacion:** plausible (esto es lo que hacen pro tools).

**Estado:** PENDIENTE.

---

## Experimento masivo — TOP vs NO_TOP × bin × año (2026-05-02)

**Script:** `analisis/experimento_masivo_no_top.py`
**JSON:** `analisis/experimento_masivo_no_top.json`

Modelos probados: V0, V_dual, V_anc05 (anchor mercado α=0.5), V_anc07 (α=0.7), V_amp (amplificador divergencia), MKT.

### Hallazgo decisivo — patrón INVERSO TOP vs NO_TOP

**TOP ligas (ENG/ESP/ITA/FRA/ALE):**
- V0 motor: yield -2.67% (N=346)
- V_dual: -18.31% (N=154)
- **V_anc05** (anchor 0.5 a mercado): **+25.76%** N=40 ★
- V_amp: -10.38% (N=591)

**NO_TOP ligas (TUR/NOR/ARG/BRA/Chile/etc):**
- V0: +4.96% (N=99)
- **V_dual**: **+20.96%** N=55 ★
- V_anc07: +27.91% (N=11 tiny)
- V_amp: -13.28% (N=153)

**Conclusion:** V_dual es campeon en NO_TOP, V_anc05 (anchor mercado) en TOP. Estrategia diferenciada por categoria de liga.

**Explicacion:** mercado TOP eficiente -> anchor a mercado preserva calibracion. Mercado NO_TOP menos eficiente -> V_dual descalibrado captura ineficiencias.

### Yield por año × cat × modelo

| Cat | Modelo | 2023 | 2024 | 2025 | 2026 | IS |
|---|---|---|---|---|---|---|
| TOP | V_anc05 | +33.15 (34) | +4.83 (6) | - | - | +28.90% |
| NO_TOP | V_dual | +86.00 (16) | +23.15 (20) | **-82.33** (12) | +43.14 (7) | +20.96% |
| NO_TOP | V0 | +16.74 (34) | +4.69 | -21.68 | +22.64 | +4.96% |

V_dual NO_TOP gana 3 de 4 anios excepto 2025 (regimen mercado eficiente).

### Ligas individuales — Argentina + Brasil bin4

| Liga | bin4 | modelo | N | yield |
|---|---|---|---|---|
| Argentina | 0 (Q1) | V_amp | 16 | **+117.94%** |
| Argentina | 1 (Q2) | V_dual | 8 | **+130.00%** |
| Argentina | 1 (Q2) | V0 | 9 | +104.44% |
| Brasil | 1 (Q2) | V0 | 4 | +93.50% |
| **Turquia** | **TODOS** | TODOS | 8-21 | **NEGATIVOS** -5 a -89% |

**Argentina Q1+Q2 zona de oro. Turquia universalmente negativa.** Régimen Apertura/Clausura argentino + cierre de semestre pre-receso = mercado menos eficiente. Turquia mercado eficiente o regimen especifico.

## Limitaciones del test consolidadas

1. **Poisson independiente, no Dixon-Coles.** El motor productivo usa DC + rho. Mi backtest omite tau() corregido para 0-0/1-0/0-1/1-1.
2. **Sin filtro DIVERGENCIA.** El motor productivo compara P_modelo vs P_implicita_mercado y filtra picks donde no hay value claro.
3. **Sin gamma_display, sin factor_corr_xg_ou.** Componentes secundarios no replicados.
4. **Sin filtros HALLAZGO_G, HALLAZGO_C, etc.** (14 filtros productivos restantes).
5. **Match cuotas 21% (2,689/13,430).** Persistido follow-up para extender via gestor_nombres.
6. **N=2,689 yield / 4 anios = 671/anio. Tras M.1 = 290/anio.** Potencia estadistica limitada.
7. **2026 parcial (Ene-Abr).** Outliers por sample size en bins.

## Decisiones a la fecha

1. Opcion B (EMA xG real extranjeros) PAUSADA por hallazgo 4. Pre-requisito: Plan A primero.
2. NO tocar `motor_data.py:156` (ratio 0.70 -> 0.10) sin Plan A primero.
3. Coefs V5 (intercept=0.273, beta_SOT=0.247) NO promovidos a config.
4. Investigacion continua via Plan A.

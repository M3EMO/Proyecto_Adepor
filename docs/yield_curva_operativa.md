# Curva operativa yield / hit / Brier por liga × octavos in-sample y OOS

> Documento vivo. Snapshot 2026-04-27. **Granularidad: 8 octavos** (mayor
> resolución que cuartos para detectar tendencia gradual).
>
> Fuentes:
> - **In-sample**: hoja "Si Hubiera" de `Backtest_Modelo.xlsx` (358 picks
>   desde 2026-03-16) JOIN `partidos_backtest` para probs y outcome.
> - **OOS**: `predicciones_walkforward` × `cuotas_externas_historico` Pinnacle
>   closing 2022-2024 (N=7.867).
>
> Re-correr mensualmente con `adepor-j4e` y los scripts `analisis/si_hubiera_*`
> + `analisis/yield_por_altura_temporada.py` + `analisis/graficar_*.py`.

## Propósito

Detectar si el sistema degrada operativamente in-sample, distinguir si la
degradación es estructural por liga o por momento del período, e inferir
recomendación operativa por liga. Complementario al análisis OOS por
temporada (`docs/xg_calibration_history.md` PARTE 5).

## Visualización

**Cada análisis se genera en TRES granularidades simultáneamente**:
- `bin4` = cuartos (Q1-Q4) — vista gruesa, detecta dirección
- `bin8` = octavos (O1-O8) — vista intermedia
- `bin12` = dozavos (D1-D12) — vista fina, detecta picos exactos

### In-sample (Si Hubiera, N=358 picks 2026-03-16 a 2026-04-26)

| Archivo | bin4 (Q1-Q4) | bin8 (O1-O8) | bin12 (D1-D12) |
|---|---|---|---|
| Curva combinada (yield + hit + Brier) | [`curva_combinada_bin4.png`](../graficos/curva_combinada_bin4.png) | [`curva_combinada_bin8.png`](../graficos/curva_combinada_bin8.png) | [`curva_combinada_bin12.png`](../graficos/curva_combinada_bin12.png) |
| Yield por liga × bin | [`yield_curva_por_liga_bin4.png`](../graficos/yield_curva_por_liga_bin4.png) | [`yield_curva_por_liga_bin8.png`](../graficos/yield_curva_por_liga_bin8.png) | [`yield_curva_por_liga_bin12.png`](../graficos/yield_curva_por_liga_bin12.png) |
| Hit rate por liga × bin | [`hitrate_curva_por_liga_bin4.png`](../graficos/hitrate_curva_por_liga_bin4.png) | [`hitrate_curva_por_liga_bin8.png`](../graficos/hitrate_curva_por_liga_bin8.png) | [`hitrate_curva_por_liga_bin12.png`](../graficos/hitrate_curva_por_liga_bin12.png) |
| Yield agregado + CI95 vertical | [`yield_global_con_ci95_bin4.png`](../graficos/yield_global_con_ci95_bin4.png) | [`yield_global_con_ci95_bin8.png`](../graficos/yield_global_con_ci95_bin8.png) | [`yield_global_con_ci95_bin12.png`](../graficos/yield_global_con_ci95_bin12.png) |
| Yield horizontal por color | [`yield_por_liga_horizontal_bin4.png`](../graficos/yield_por_liga_horizontal_bin4.png) | [`yield_por_liga_horizontal_bin8.png`](../graficos/yield_por_liga_horizontal_bin8.png) | [`yield_por_liga_horizontal_bin12.png`](../graficos/yield_por_liga_horizontal_bin12.png) |

### OOS (walk-forward 2022-2024 sobre Pinnacle, N=7.867)

| Archivo | bin4 | bin8 | bin12 |
|---|---|---|---|
| Yield + hit + Brier agregado (A vs V4.7) | [`oos_curva_por_octavo_agregado_bin4.png`](../graficos/oos_curva_por_octavo_agregado_bin4.png) | [`oos_curva_por_octavo_agregado_bin8.png`](../graficos/oos_curva_por_octavo_agregado_bin8.png) | [`oos_curva_por_octavo_agregado_bin12.png`](../graficos/oos_curva_por_octavo_agregado_bin12.png) |
| Drill-down ΔY V4.7 por (temp × bin) | [`oos_yield_por_temp_x_octavo_bin4.png`](../graficos/oos_yield_por_temp_x_octavo_bin4.png) | [`oos_yield_por_temp_x_octavo_bin8.png`](../graficos/oos_yield_por_temp_x_octavo_bin8.png) | [`oos_yield_por_temp_x_octavo_bin12.png`](../graficos/oos_yield_por_temp_x_octavo_bin12.png) |

### Re-generar gráficos

Cada script auto-ejecuta `bin4` + `bin8`:

```bash
py analisis/si_hubiera_por_cuartos.py            # genera *_bin4.json + *_bin8.json
py analisis/si_hubiera_top5_y_c4.py              # idem
py analisis/si_hubiera_por_liga_cuartos.py       # idem
py analisis/yield_por_altura_temporada.py        # idem (incluye drill-down liga x bin)
py analisis/graficar_yield_curva.py              # plots in-sample bin4 + bin8
py analisis/graficar_oos_por_octavos.py          # plots OOS bin4 + bin8
```

## Snapshot 2026-04-27 — N=358 picks simulados, fechas 2026-03-16 a 2026-04-26

### Tabla por liga × cuartos temporales (yield % unitario)

| Liga | N | Hit% | Yield% | Q1 | Q2 | Q3 | Q4 | HQ1 | HQ4 | Etiqueta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **Argentina** | 55 | 67.3 | **+72.7** | +131.3 | +86.4 | +87.0 | +18.2 | 93 | 48 | ESTABLE_POSITIVA |
| **Turquia** | 47 | 66.0 | **+42.1** | +55.5 | +97.6 | +33.2 | +22.1 | 75 | 59 | ESTABLE_POSITIVA |
| Brasil | 58 | 56.9 | +55.6 | +6.9 | +158.7 | **−26.7** | +11.3 | 44 | 60 | INESTABLE |
| Inglaterra | 34 | 67.6 | +42.9 | +69.3 | n/a | −29.4 | +63.7 | 57 | 84 | bins incompletos |
| Noruega | 29 | 69.0 | +65.1 | +92.0 | n/a | +66.1 | +54.1 | 75 | 73 | bins incompletos |
| Colombia | 13 | 69.2 | +41.9 | n/a | n/a | n/a | +41.9 | n/a | 69 | solo Q4 |
| Ecuador | 17 | 64.7 | +38.8 | n/a | n/a | n/a | +38.8 | n/a | 65 | solo Q4 |
| Chile | 19 | 47.4 | +2.4 | n/a | n/a | −100.0 | +8.1 | n/a | 50 | mayoría Q4 |
| Bolivia | 21 | 61.9 | −4.4 | n/a | n/a | n/a | −4.4 | n/a | 62 | solo Q4 |
| **España** | 20 | 45.0 | **−13.8** | n/a | n/a | n/a | −13.8 | n/a | 45 | solo Q4 |
| Francia | 11 | 63.6 | +2.2 | — | — | — | — | — | — | N<12 |
| Peru | 10 | 50.0 | −2.5 | — | — | — | — | — | — | N<12 |
| Uruguay | 6 | 33.3 | −4.0 | — | — | — | — | — | — | N<12 |
| **Alemania** | 10 | 40.0 | **−30.5** | — | — | — | — | — | — | N<12 |
| **Italia** | 8 | 25.0 | **−59.5** | — | — | — | — | — | — | N<12 |

### Recomendación operativa por liga (snapshot 2026-04-27)

| Liga | N | CI95 yield (paired) | Acción operativa |
|---|---:|---:|---|
| Argentina | 55 | [+32.05, +113.83] | **APOSTAR** (yield positivo cross-Q sig). Cuidado caída Q4 (+18 vs Q1 +131) → ver `adepor-dex`. |
| Turquia | 47 | [+9.82, +74.35] | **APOSTAR** (yield consistente positivo cross-Q sig). |
| Inglaterra | 34 | [+2.87, +82.85] | **APOSTAR** (CI95 sig positivo, bins incompletos pero magnitud sólida). |
| Brasil | 58 | [+13.07, +102.77] | APOSTAR conservador (Q3 −26.7%, volatilidad alta). |
| Noruega | 29 | [+16.81, +116.98] | APOSTAR (sig pos, sin Q2 evaluado). |
| Colombia | 13 | [−15.67, +106.54] | OBSERVAR (CI95 cruza 0, solo Q4). |
| Ecuador | 17 | [−18.77, +99.36] | OBSERVAR (CI95 cruza 0, solo Q4). |
| España | 20 | [−55.70, +29.55] | OBSERVAR (yield neg, CI95 cruza 0). |
| Bolivia | 21 | [−36.67, +27.22] | OBSERVAR. |
| Chile | 19 | [−49.19, +52.29] | OBSERVAR. |
| Italia | 8 | [−100.00, −7.50] | NO APOSTAR (sig neg, N chico, esperar más). |
| Alemania | 10 | [−85.20, +29.61] | OBSERVAR (yield neg, esperar más). |
| Francia, Peru, Uruguay | 6-11 | amplios | OBSERVAR (N chico). |

## Hallazgo OOS confirmado: forma de "U invertida" por octavo de temporada

Test OOS walk-forward N=7.867 sobre Pinnacle closing 2022-2024. Yield del
sistema A (HG+Fix5) por octavo de temp:

| Octavo | pct trayecto | N | Yield A% | Hit A% | Brier A | Yield V4.7% | ΔY V4.7 sig |
|---|---|---:|---:|---:|---:|---:|---|
| O1 | 0-12% | 875 | **−20.67** | 29.2 | 0.641 | −39.62 | **★ NEG** |
| O2 | 12-25% | 995 | +8.14 | 35.2 | 0.632 | −15.37 | **★ NEG** |
| O3 | 25-38% | 776 | **+17.29** | **41.0** | **0.619** | +20.58 | no |
| O4 | 38-50% | 928 | +13.92 | 40.2 | 0.630 | +16.40 | no |
| O5 | 50-62% | 1006 | +8.05 | 36.7 | 0.627 | +18.43 | no |
| O6 | 62-75% | 1024 | +13.96 | 39.1 | 0.627 | +12.19 | no |
| O7 | 75-88% | 945 | **−14.59** | 31.9 | 0.632 | −23.56 | borderline |
| O8 | 88-100% | 1318 | **−13.35** | 30.1 | 0.622 | −21.15 | borderline |

**Patrón clave: el sistema NO es estable a lo largo de la temporada.**
- O1 (arranque, 0-12%): yield catastrófico −20.67%, hit 29% (peor que random 33.3%).
- O3-O6 (mitad, 25-75%): yield +8 a +17%, hit 37-41%. **Zona dorada**.
- O7-O8 (cierre, 75-100%): yield −14 a −13%, hit ~30%. **Crash de cierre**.

Brier sigue la misma forma de U invertida: peor en O1 (0.641) → mejor en O3
(0.619) → peor en O7 (0.632). La incertidumbre del modelo es máxima al
arranque (poca data EMA) y al cierre (fixture atípico).

V4.7 (sin parches HG+Fix5) **empeora yield aún más en O1-O2** (−18 a −24pp
sig negativo), confirmando que los parches actúan como prior estabilizador
exactamente cuando el modelo es más débil (arranque).

## Inferencias sobre comportamiento del sistema

### 1. Degradación monotónica agregada NO es estructural

Cuando se mira yield agregado por cuartos cross-todas-las-ligas, hay caída
+143% (Q2) → +5% (Q4). Pero **filtrando a TOP-5 estables, la degradación
desaparece**: Q4 mantiene +31.72% sig positivo. La degradación agregada era
artefacto de incorporar gradualmente las ligas marginales (LATAM secundarias,
EUR menores) durante el período.

### 2. El sistema tiene firmas por liga distintas

- **Apostables sostenidas**: Argentina, Turquía. CI95 positivo, hit consistente
  cross-cuarto. Ningún Q rompe.
- **Apostables con volatilidad**: Brasil. Yield global positivo pero Q3
  catastrófico (−26.7%). El sistema acierta menos en Brasil cuando entra
  régimen específico (¿Copa Libertadores? ¿fixtures atípicos?).
- **Inglaterra/Noruega**: probablemente apostables, pero distribución temporal
  irregular impide CI95 paired robusto por cuarto.
- **Marginales nuevas (Col/Ecu/Chi/Bol/Esp)**: solo Q4 cubierto. Demasiado
  pronto para juzgar. Bolivia y España con yield negativo agregado.
- **Marginales pequeñas (Fra/Per/Uru/Ale/Ita)**: N<12, ruido puro.

### 3. Bankroll dinámico amplifica error en Q4

Stake real Q1=$239k vs Q4=$11.05M (46×). El Kelly cap 2.5% aplicado sobre
bankroll que creció 9× concentra exposición en último cuarto. Cuando hay
regresión a la media (esperable tras streak Q1-Q2 hit 65%), el daño absoluto
es desproporcionado.

### 4. C4 (camino conservador) es advisory, no operativo

C4 tiene hit 76% global y yield estable (+12 a +30 cross-cuarto), pero solo
4 de 84 picks C4 tienen stake operativo (los demás caen en `[PASAR] Margen
Predictivo Insuficiente <5%`). Cuotas bajas → EV chico → filtro lo rechaza.
Para que C4 sea apostable habría que relajar EV-min específicamente para C4
(propuesta separada).

## Cómo extender este registro

Re-correr mensualmente:

```bash
py analisis/si_hubiera_por_cuartos.py
py analisis/si_hubiera_top5_y_c4.py
py analisis/si_hubiera_por_liga_cuartos.py
```

Persistir snapshots en `analisis/si_hubiera_*.json`. Comparar contra snapshot
anterior — alertar si:
- Alguna liga ESTABLE_POSITIVA cambia a INESTABLE o DEGRADANTE
- Yield Q4 de una liga cae >25pp respecto al snapshot anterior
- Volumen stake Q4/Q1 ratio crece >50× (Kelly explota)

## Referencias

- Bead `adepor-j4e`: trigger mensual de re-corrida
- Bead `adepor-dex`: cautela operativa Argentina (drop Q4 −113pp)
- Bead `[PROPOSAL] filtro TOP-5` (creado 2026-04-27)
- Bead `[PROPOSAL] C4 operativo EV-min reducido` (creado 2026-04-27)
- Bead `[INFRA] features adicionales scraping` (creado 2026-04-27)
- Scripts `analisis/si_hubiera_*.py`
- JSON: `analisis/si_hubiera_*.json`
